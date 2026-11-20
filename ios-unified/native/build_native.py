#!/usr/bin/env python3
"""Build the embedded server framework using an installed Apple SDK.

This is a real iOS/Catalyst-convertible target, never a relabelled Mac binary.
CPython and every native stdlib dependency are separate audited iOS frameworks.
Linux can run --portable-tests only; Objective-C compilation requires Xcode.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(65536), b''): h.update(block)
    return h.hexdigest()


def macho(path, expected_platform, arch='arm64'):
    with Path(path).open('rb') as source:
        header = source.read(32)
        if len(header) != 32: raise ValueError('Truncated Mach-O')
        magic, cpu, _sub, kind, count, size, _flags, _reserved = struct.unpack('<8I', header)
        expected_cpu = {'arm64':0x100000c, 'x86_64':0x1000007}[arch]
        if magic != 0xfeedfacf or cpu != expected_cpu or kind != 6 or not 0 < count < 256 or size > 65536:
            raise ValueError('Expected thin target-architecture Mach-O dylib')
        commands = source.read(size)
    at = 0; versions = []; loads = []
    for _ in range(count):
        command, length = struct.unpack_from('<II', commands, at)
        if length < 8 or at + length > len(commands): raise ValueError('Invalid Mach-O command')
        if command == 0x32:
            platform, minimum, sdk, _tools = struct.unpack_from('<4I', commands, at+8)
            versions.append((platform, minimum, sdk))
        if command in (0xc, 0x80000018, 0x8000001f):
            offset = struct.unpack_from('<I', commands, at+8)[0]
            if not 24 <= offset < length: raise ValueError('Invalid load path')
            loads.append(commands[at+offset:at+length].split(b'\0')[0].decode('utf-8'))
        at += length
    if at != size or len(versions) != 1 or versions[0][0] != expected_platform:
        raise ValueError('Actual binary platform does not match requested SDK')
    return {'platform': versions[0][0], 'minimum': versions[0][1], 'sdk': versions[0][2], 'dependencies': loads}


def portable_tests(here):
    compiler = shutil.which('cc') or shutil.which('clang')
    if not compiler: raise ValueError('C compiler unavailable')
    # Tests own only small temporary executables, never release artifacts.
    with tempfile.TemporaryDirectory(prefix='idoly-ios-native-policy-', dir='/dev/shm' if Path('/dev/shm').is_dir() else None) as scratch:
        results = []
        for source in sorted((here/'tests').glob('*_test.c')):
            output = Path(scratch)/source.stem
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', str(source), '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True); results.append(source.name)
    print(json.dumps({'status':'PASS_PORTABLE_POLICY_ONLY','tests':results,'Apple_SDK_or_device_verified':False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable-tests', action='store_true')
    parser.add_argument('--sdk', choices=('iphoneos','iphonesimulator'), default='iphoneos')
    parser.add_argument('--arch', choices=('arm64','x86_64'), default='arm64')
    parser.add_argument('--python-framework', type=Path)
    parser.add_argument('--presentation-library', type=Path)
    parser.add_argument('--smoke-simulator', action='store_true', help='Probe only: omit device presentation dependency')
    parser.add_argument('--output', type=Path, help='Fresh IdolyEmbeddedServer.framework directory')
    args = parser.parse_args(); here = Path(__file__).resolve().parent
    if args.portable_tests:
        portable_tests(here); return
    if not args.python_framework or not args.output: parser.error('--python-framework and --output required')
    if args.smoke_simulator != (args.sdk == 'iphonesimulator'):
        parser.error('Simulator is probe-only and requires explicit --smoke-simulator')
    if args.sdk == 'iphoneos' and args.arch != 'arm64':
        parser.error('The real device target is arm64 only')
    if args.sdk == 'iphoneos' and not args.presentation_library:
        parser.error('Device framework requires the original iOS presentation dependency')
    if args.smoke_simulator and args.presentation_library:
        parser.error('The fake-Unity simulator probe cannot load the device presentation library')
    xcrun = shutil.which('xcrun')
    if not xcrun: raise ValueError('Xcode xcrun/Apple iOS SDK required; Linux stubs cannot build CPython/UIKit')
    sdk = subprocess.check_output([xcrun,'--sdk',args.sdk,'--show-sdk-path'], text=True).strip()
    compiler = subprocess.check_output([xcrun,'--sdk',args.sdk,'--find','clang'], text=True).strip()
    python = args.python_framework.resolve(strict=True)
    if python.name != 'Python.framework' or not (python/'Headers/Python.h').is_file():
        raise ValueError('Explicit iOS Python.framework Headers/Python.h required')
    # XCFramework simulator slices may be universal. The linker selects arm64;
    # final native output is independently checked below.
    output = args.output.absolute()
    if output.name != 'IdolyEmbeddedServer.framework' or output.exists():
        raise ValueError('Fresh IdolyEmbeddedServer.framework output required')
    sources = [here/name for name in ('IdolyEmbeddedServer.m','IdolySettings.m','IdolyHTTP.m','IdolyMacMenu.m','IdolyClientData.m','IdolyKeyboardLifecycle.m','IdolyLocalHTTP.m','IdolyOctoBudget.m','IdolyUnityHost.m','IdolyMVEncoder.mm','IdolyMP4UI.m')]
    inputs = sources + sorted(here.glob('*.h')) + [here/'../../client-presentation/native/mp4_encoder_api.h', Path(__file__).resolve()]
    pins = {str(p.relative_to(here)):sha(p) for p in inputs}
    command = [compiler,'-target',args.arch+'-apple-ios13.0'+('-simulator' if args.smoke_simulator else ''),
        '-isysroot',sdk,'-dynamiclib','-fobjc-arc','-fblocks','-fvisibility=hidden','-O2',
        '-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-Wno-missing-field-initializers',
        '-I',str(python/'Headers'),'-F',str(python.parent),'-framework','Python',
        '-framework','Foundation','-framework','UIKit','-framework','WebKit',
        '-framework','AVFoundation','-framework','AudioToolbox','-framework','CoreMedia',
        '-framework','CoreVideo','-framework','VideoToolbox','-framework','CoreGraphics','-lc++',
        '-Wl,-install_name,@rpath/IdolyEmbeddedServer.framework/IdolyEmbeddedServer',
        '-Wl,-headerpad_max_install_names']
    if args.presentation_library:
        presentation = args.presentation_library.resolve(strict=True)
        macho(presentation, 2)
        command += ['-Wl,-needed_library,'+str(presentation)]
    if args.smoke_simulator:
        command += ['-DIDOLY_SMOKE_SIMULATOR=1']
    output.mkdir(parents=True)
    binary = output/'IdolyEmbeddedServer'
    command += [*map(str,sources),'-o',str(binary)]
    subprocess.run(command,check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    if args.presentation_library:
        subprocess.run([xcrun,'install_name_tool','-change','@rpath/IdolyPresentation.dylib',
                        '@loader_path/../IdolyPresentation.dylib',str(binary)], check=True)
    image = macho(binary, 7 if args.smoke_simulator else 2, args.arch)
    if args.sdk == 'iphoneos' and '@loader_path/../IdolyPresentation.dylib' not in image['dependencies']:
        raise ValueError('Presentation constructor ordering dependency missing')
    if not any(path.endswith('/Python.framework/Python') for path in image['dependencies']):
        raise ValueError('Python framework dependency missing')
    if pins != {str(p.relative_to(here)):sha(p) for p in inputs}:
        raise ValueError('Native source changed during compilation')
    info = {'CFBundleIdentifier':'local.idoly.embedded-server','CFBundleName':'IdolyEmbeddedServer',
        'CFBundleExecutable':'IdolyEmbeddedServer','CFBundlePackageType':'FMWK','CFBundleVersion':'1',
        'CFBundleShortVersionString':'1.0','MinimumOSVersion':'13.0',
        'CFBundleSupportedPlatforms':['iPhoneSimulator' if args.smoke_simulator else 'iPhoneOS']}
    with (output/'Info.plist').open('xb') as stream: plistlib.dump(info,stream)
    (output/'Headers').mkdir(); shutil.copyfile(here/'IdolyEmbeddedServer.h',output/'Headers/IdolyEmbeddedServer.h')
    report = {'schema':1,'status':'BUILT_REQUIRES_SIMULATOR_AND_DEVICE_VALIDATION','sdk':args.sdk,
        'smoke_probe_only':args.smoke_simulator,'command':command,'source_sha256':pins,
        'python_framework':str(python),'python_binary_sha256':sha(python/'Python'),
        'binary_bytes':binary.stat().st_size,'binary_sha256':sha(binary),'MachO':image,
        'Py_Finalize_used':False,'actual_phone_gameplay_verified':False}
    with output.with_suffix('.build.json').open('x') as stream: json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__': main()
