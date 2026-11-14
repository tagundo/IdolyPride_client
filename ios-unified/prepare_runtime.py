#!/usr/bin/env python3
"""Prepare a signed iOS CPython runtime from exact public support/wheel inputs."""
from __future__ import annotations
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import subprocess
import sys
import tarfile
from zipfile import ZipFile
from packaging_common import *

HERE = Path(__file__).resolve().parent
MAX_FILES = 8192
FORBIDDEN = {'cli','server','collect','event_capture','official_session','profiles','firebase_archive','ios_patch','ios_presentation','font_assets','client_patch','native_bootstrap','android_package'}
STRIP_STDLIB = {'test','tests','idlelib','turtledemo','ensurepip','venv','pydoc_data','tkinter','__pycache__','site-packages','_pyrepl'}

def tar_inventory(archive):
    result = {}; total = 0
    for member in archive.getmembers():
        safe_name(member.name); require(member.name not in result, 'Duplicate support archive path')
        require(member.isdir() or member.isfile() or member.issym(), 'Unsupported support archive entry')
        if member.issym():
            require(not member.linkname.startswith('/') and '\\' not in member.linkname, 'Unsafe support symlink')
            import posixpath
            resolved = posixpath.normpath(str(PurePosixPath(member.name).parent / member.linkname))
            require(not resolved.startswith('../') and resolved != '..', 'Support symlink escapes archive')
        require(0 <= member.size <= 16 * 1024**2, 'Support member exceeds bound')
        total += member.size; require(len(result) < MAX_FILES and total <= 192 * 1024**2, 'Support archive exceeds bound')
        result[member.name] = member
    return result

def select_library(info, target):
    require(target in PLATFORMS and isinstance(info, dict), 'Unknown framework target')
    selected = [r for r in info.get('AvailableLibraries', []) if r.get('SupportedPlatform') == 'ios' and r.get('SupportedPlatformVariant', '') == ('' if target == 'device' else 'simulator')]
    require(len(selected) == 1, 'Exactly one matching iOS framework slice required')
    row = selected[0]; safe_name(row['LibraryIdentifier']); require(row.get('LibraryPath') == 'Python.framework' and row.get('BinaryPath') == 'Python.framework/Python', 'Unexpected Python framework layout')
    require(set(row['SupportedArchitectures']) == ({'arm64'} if target == 'device' else {'arm64','x86_64'}), 'Python framework architectures differ')
    return row

def runtime_sources(root, roots):
    source = Path(root) / 'src'; available = {'idoly_local.' + p.stem: p for p in (source / 'idoly_local').glob('*.py')}
    available['idoly_local'] = available.pop('idoly_local.__init__')
    pending = list(roots) + ['idoly_local']; selected = {}; external = set()
    while pending:
        name = pending.pop()
        if name in selected: continue
        require(name in available, 'Required iOS runtime module missing: ' + name)
        short = name.rsplit('.', 1)[-1]
        require(short not in FORBIDDEN and (not short.endswith(('_qa','_capture','_build')) or short == 'dream_capture'), 'Developer module reached by iOS runtime: ' + name)
        p = available[name]; raw = p.read_bytes(); require(len(raw) <= 2 * 1024**2, 'Python source exceeds bound'); tree = ast.parse(raw, filename=str(p)); selected[name] = (p, raw)
        package = 'idoly_local'; imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
                imports.add(base)
                imports.update(base + '.' + a.name for a in node.names if base + '.' + a.name in available)
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__' or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module': imports.add(node.args[0].value)
        for item in imports:
            if item in available: pending.append(item)
            elif item.startswith('idoly_local.'): require(False, 'Unresolved project runtime import: ' + item)
            else: external.add(item.split('.')[0])
        require(len(selected) <= 128 and sum(len(v[1]) for v in selected.values()) <= 10 * 1024**2, 'Runtime Python source closure exceeds bound')
    require('grpc' not in external, 'grpcio is outside the embedded runtime')
    return selected

def extract_file(archive, member, destination):
    require(member.isfile(), 'Selected support input is not regular')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.extractfile(member) as incoming, destination.open('xb') as outgoing:
        stream_copy(incoming, outgoing, member.size)
    destination.chmod(0o644)

def unpack_wheel(path, row, destination):
    verify_file(path, row); copied = []
    with ZipFile(path) as archive:
        infos = archive.infolist(); require(len(infos) <= 2048 and len({i.filename for i in infos}) == len(infos), 'Invalid pure wheel inventory')
        wheels = [i for i in infos if i.filename.endswith('.dist-info/WHEEL')]
        require(len(wheels) == 1 and wheels[0].file_size <= 8192 and b'Root-Is-Purelib: true' in archive.read(wheels[0]), 'A universal pure Python wheel is required')
        total = 0
        for info in infos:
            name = info.filename.rstrip('/'); safe_name(name)
            require(not info.flag_bits & 1 and (info.external_attr >> 16 & 0o170000) != 0o120000, 'Invalid wheel member')
            require(not name.endswith(('.so','.dylib','.dll','.a','.exe')), 'Native code in pure dependency wheel')
            if info.is_dir(): continue
            require(info.file_size <= 4 * 1024**2, 'Wheel member exceeds bound'); total += info.file_size; require(total <= 16 * 1024**2, 'Wheel expanded size exceeds bound')
            components = PurePosixPath(name).parts
            is_package = any(name.startswith(prefix + '/') for prefix in row['imports']) and name.endswith(('.py','py.typed'))
            if '_pb2_grpc.py' in name or '/compiler/' in name or '/test' in name: is_package = False
            is_license = '.dist-info' in components[0] and (components[-1].startswith(('LICENSE','COPYING')) or components[-1] in ('METADATA','WHEEL'))
            if not (is_package or is_license): continue
            target = destination / name
            require(not target.exists(), 'Dependency wheel files overlap'); target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as incoming, target.open('xb') as outgoing: stream_copy(incoming, outgoing, info.file_size)
            copied.append(name)
    require(copied, 'Pure dependency wheel contained no selected runtime files')
    return copied

def normalize_python_framework_metadata(framework, target, expected_architectures):
    """Correct BeeWare's Simulator plist only after auditing its actual binary."""
    framework = Path(framework)
    image = audit_macho(framework / 'Python', target)
    require({item['architecture'] for item in image['slices']} == set(expected_architectures), 'Python framework architecture inventory differs')
    require(all(item['filetype'] == 6 and item['install_name'] == '@rpath/Python.framework/Python' for item in image['slices']), 'Python framework dylib identity differs')
    path = framework / 'Info.plist'; require(regular(path).st_size <= 128 * 1024, 'Python Info.plist exceeds bound')
    raw = path.read_bytes(); info = plistlib.loads(raw)
    require(info.get('CFBundleExecutable') == 'Python' and info.get('CFBundlePackageType') == 'FMWK', 'Python framework metadata identity differs')
    expected = ['iPhoneOS' if target == 'device' else 'iPhoneSimulator']
    corrected = target == 'simulator' and info.get('CFBundleSupportedPlatforms') == ['iPhoneOS']
    if corrected:
        info['CFBundleSupportedPlatforms'] = expected
        path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY if raw.startswith(b'bplist00') else plistlib.FMT_XML))
    require(info.get('CFBundleSupportedPlatforms') == expected, 'Python framework metadata platform differs')
    return {'actual_binary': image, 'supported_platforms': expected, 'vendor_Simulator_metadata_corrected': corrected}


def _run(tool, args):
    result = subprocess.run([str(tool), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    require(result.returncode == 0 and len(result.stdout) <= 65536 and len(result.stderr) <= 65536, 'Apple framework tool failed')

def sign_framework(framework, codesign):
    _run(codesign, ['--force','--sign','-','--timestamp=none', framework])
    _run(codesign, ['--verify','--strict',framework])

def prepare(support, wheel_dir, output, *, target, architecture, project_root, codesign, install_name_tool, manifest=None):
    manifest = manifest or json.loads((HERE / 'runtime_inputs.json').read_text())
    verify_file(support, manifest['support']); require(not Path(output).exists(), 'Fresh runtime output required')
    sources = runtime_sources(project_root, manifest['project_roots'])
    require(set(sources) == set(manifest['project_modules']), 'Project runtime module whitelist differs')
    for row in manifest['pure_wheels']: verify_file(Path(wheel_dir) / row['filename'], row)
    require(regular(Path(project_root) / 'LICENSE').st_size <= 128 * 1024, 'Project license missing or too large')
    require(architecture in ({'arm64'} if target == 'device' else {'arm64','x86_64'}), 'Architecture differs from iOS target')
    output = Path(output); output.mkdir(parents=True)
    framework_root = output / 'Frameworks'; stdlib = output / 'python-stdlib'; python = output / 'LocalServer/python'
    framework_root.mkdir(); stdlib.mkdir(); python.mkdir(parents=True)
    mappings = {}; skipped = 0
    with tarfile.open(support, 'r:gz') as archive:
        members = tar_inventory(archive); base = manifest['support']['xcframework']
        info = plistlib.loads(archive.extractfile(members[base + '/Info.plist']).read(65537)); selected = select_library(info, target)
        require(selected['LibraryIdentifier'] == manifest['support']['libraries'][target], 'Pinned framework slice differs')
        prefix = base + '/' + selected['LibraryIdentifier'] + '/'
        stdprefix = manifest['support']['stdlib'] + '/'; archprefix = prefix + 'lib-' + architecture + '/python3.13/'
        for name, member in members.items():
            if not member.isfile(): continue
            if name.startswith(prefix + 'Python.framework/'):
                relative = name[len(prefix):]; extract_file(archive, member, framework_root / relative)
            elif name.startswith(stdprefix):
                relative = name[len(stdprefix):]
                if any(part in STRIP_STDLIB for part in PurePosixPath(relative).parts): skipped += 1; continue
                require(not relative.endswith(('.so','.dylib','.a')), 'Native stdlib input outside architecture directory')
                extract_file(archive, member, stdlib / relative)
            elif name.startswith(archprefix):
                relative = name[len(archprefix):]
                if relative.endswith('.py'): extract_file(archive, member, stdlib / relative)
                elif relative.startswith('lib-dynload/') and relative.endswith('.so'):
                    filename = PurePosixPath(relative).name; module = filename.split('.', 1)[0]
                    if module.startswith(('_test','xx','_xx')) or module.endswith('_test'): skipped += 1; continue
                    require(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',module), 'Invalid native module name')
                    framework = framework_root / (module + '.framework'); binary = framework / module
                    extract_file(archive, member, binary); binary.chmod(0o755)
                    module_audit = audit_macho(binary, target)
                    require({s['architecture'] for s in module_audit['slices']} == {architecture}, 'Native extension architecture differs')
                    _run(install_name_tool, ['-id','@rpath/' + module + '.framework/' + module,binary])
                    mapping = 'python-stdlib/lib-dynload/' + filename[:-3] + '.fwork'
                    stub = output / mapping; stub.parent.mkdir(parents=True, exist_ok=True); stub.write_text('Frameworks/' + module + '.framework/' + module + '\n')
                    (framework / (module + '.origin')).write_text(mapping + '\n')
                    (framework / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':module,'CFBundleIdentifier':'org.python.stdlib.mod-' + module.replace('_','-'),'CFBundleName':module,'CFBundlePackageType':'FMWK','CFBundleVersion':'1','CFBundleShortVersionString':'1.0','MinimumOSVersion':'13.0','CFBundleSupportedPlatforms':['iPhoneOS' if target == 'device' else 'iPhoneSimulator']}))
                    mappings[module] = {'fwork':mapping,'binary':'Frameworks/' + module + '.framework/' + module,'origin':'Frameworks/' + module + '.framework/' + module + '.origin'}
    python_metadata = normalize_python_framework_metadata(framework_root / 'Python.framework', target, selected['SupportedArchitectures'])
    require(set(manifest['required_extensions']) <= mappings.keys(), 'Required native stdlib modules are missing')
    for row in manifest['pure_wheels']: unpack_wheel(Path(wheel_dir) / row['filename'], row, python)
    license_path = output / 'LocalServer/licenses/AGPL-3.0.txt'; license_path.parent.mkdir(parents=True, exist_ok=True)
    with (Path(project_root) / 'LICENSE').open('rb') as incoming, license_path.open('xb') as outgoing: stream_copy(incoming, outgoing, regular(Path(project_root) / 'LICENSE').st_size)
    for name, (path, raw) in sources.items():
        dest = python / path.relative_to(Path(project_root) / 'src'); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(raw)
    for prefix in manifest['required_pure_dependencies']: require((python / prefix).is_dir(), 'Required pure dependency missing')
    for framework in sorted(framework_root.glob('*.framework')):
        (framework / framework.stem).chmod(0o755); sign_framework(framework, codesign)
    native = audit_frameworks(framework_root, target, require_signature=True)
    require(not list(output.rglob('*.so')) and not list(output.rglob('*.dylib')), 'Loose native modules cannot be loaded by the target')
    files = {str(p.relative_to(output)): {'bytes':regular(p).st_size,'sha256':sha_file(p)} for p in sorted(output.rglob('*')) if p.is_file()}
    require(sum(v['bytes'] for v in files.values()) <= manifest['capacity']['max_runtime_bytes'], 'Prepared runtime exceeds capacity')
    report = {'schema':1,'target':target,'architecture':architecture,'python_abi':manifest['python_abi'],'support_sha256':manifest['support']['sha256'],'frameworks':native,'python_framework_metadata':python_metadata,'extension_mappings':mappings,'project_source_modules':sorted(sources),'source_sha256':{name:sha_file(path) for name,(path,raw) in sources.items()},'files':files,'stdlib_test_and_editor_members_omitted':skipped,'protobuf_implementation':'python','frameworks_codesign_verify_passed':True,'actual_device_execution':False}
    (output / 'runtime-report.json').write_text(json.dumps(report,indent=2)+'\n'); return report

def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--support',type=Path,required=True); p.add_argument('--wheel-dir',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--target',choices=tuple(PLATFORMS),default='device'); p.add_argument('--architecture',choices=('arm64','x86_64'),default='arm64'); p.add_argument('--project-root',type=Path,default=HERE.parent); p.add_argument('--codesign',type=Path,default=Path('/usr/bin/codesign')); p.add_argument('--install-name-tool',type=Path,default=Path('/usr/bin/install_name_tool')); a = p.parse_args()
    report = prepare(a.support,a.wheel_dir,a.output,target=a.target,architecture=a.architecture,project_root=a.project_root,codesign=a.codesign,install_name_tool=a.install_name_tool); print(json.dumps({'status':'PASS_PREPARED_IOS_RUNTIME','frameworks':len(report['frameworks']),'project_modules':len(report['project_source_modules']),'target':a.target}))
if __name__ == '__main__': main()
