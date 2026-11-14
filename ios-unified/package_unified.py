#!/usr/bin/env python3
"""Compose an integrated iOS app using streamed, exact v0.3.31 public inputs."""
from __future__ import annotations
import argparse
import copy
import hashlib
import os
import json
from pathlib import Path
import plistlib
import re
import struct
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED
from packaging_common import *

HERE = Path(__file__).resolve().parent
LOAD_PATH = '@rpath/IdolyEmbeddedServer.framework/IdolyEmbeddedServer'
UNITY = 'Frameworks/UnityFramework.framework/UnityFramework'


def runtime_files(root, target, manifest):
    root = Path(root); require(regular(root / 'runtime-report.json').st_size <= 4 * 1024**2, 'Runtime report exceeds bound'); report = json.loads((root / 'runtime-report.json').read_text())
    require(report['target'] == target and report['python_abi'] == '3.13' and report['protobuf_implementation'] == 'python' and report['frameworks_codesign_verify_passed'] is True, 'Runtime report target differs')
    files = {}
    require(not any(p.is_symlink() for p in root.rglob('*')), 'Runtime must not contain symlinks')
    for relative, row in report['files'].items():
        safe_name(relative); path = root / relative; require(path.resolve().is_relative_to(root.resolve()), 'Runtime path escapes root'); verify_file(path, row); files[relative] = path
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and str(p.relative_to(root)) != 'runtime-report.json'}
    require(actual == set(files) and sum(p.stat().st_size for p in files.values()) <= manifest['capacity']['max_runtime_bytes'], 'Runtime inventory differs')
    audit_frameworks(root / 'Frameworks', target, require_signature=True)
    for module, row in report['extension_mappings'].items():
        fwork = files[row['fwork']]; origin = files[row['origin']]
        require(fwork.read_text().strip() == row['binary'] and origin.read_text().strip() == row['fwork'] and row['binary'] in files, 'Native .fwork/.origin mapping differs')
    require(not any(n.endswith(('.so','.dylib','.dll')) for n in files), 'Loose new native modules are forbidden')
    return files, report


def bundle_files(runtime_root, native_framework, server_data, translations, target, manifest, web_root=None, *, allow_unsigned_native=False):
    files, runtime = runtime_files(runtime_root, target, manifest)
    verify_file(server_data, manifest['inputs']['server_data']); verify_file(translations, manifest['inputs']['translations'])
    native_framework = Path(native_framework); require(native_framework.name == 'IdolyEmbeddedServer.framework' and not native_framework.is_symlink(), 'Exact embedded server framework required')
    info = plistlib.loads((native_framework / 'Info.plist').read_bytes()); require(info.get('CFBundleExecutable') == 'IdolyEmbeddedServer', 'Native framework executable differs')
    native = audit_macho(native_framework / 'IdolyEmbeddedServer', target, require_signature=not allow_unsigned_native)
    for arch in native['slices']:
        require(arch['install_name'] == LOAD_PATH, 'Embedded framework install name differs')
        for dependency in arch['dependencies']:
            require(dependency.startswith(('/usr/lib/','/System/Library/Frameworks/')) or dependency in ('@rpath/Python.framework/Python','@loader_path/../IdolyPresentation.dylib','@rpath/IdolyPresentation.dylib'), 'Unresolved embedded framework dependency')
    for p in native_framework.rglob('*'):
        require(not p.is_symlink(), 'Native framework contains a symlink')
        if p.is_file():
            relative = 'Frameworks/IdolyEmbeddedServer.framework/' + str(p.relative_to(native_framework)); require(relative not in files, 'Native framework overlaps runtime'); files[relative] = p
    files['LocalServer/ServerData.zip'] = Path(server_data); files['LocalServer/bundledTranslations.zip'] = Path(translations)
    web = Path(web_root or HERE / 'web'); require({p.name for p in web.iterdir() if p.is_file()} == {'index.html','styles.css','app.js'}, 'Bundled settings inventory differs')
    for name in ('index.html','styles.css','app.js'):
        p = web / name; require(regular(p).st_size <= 256 * 1024, 'Settings file exceeds bound'); files['LocalServer/settings/' + name] = p
    t = manifest['inputs']['translations']; metadata = {'schema':1,'platform':'ios','sha256':t['sha256'],'bytes':t['bytes']}
    generated = {'LocalServer/bundledTranslations.json':(json.dumps(metadata,indent=2)+'\n').encode()}
    require(len(files) <= manifest['capacity']['max_archive_entries'], 'Unified app inventory exceeds bound')
    return files, generated, {'runtime':runtime,'native':native}


def verify_unity_patch(incoming, patched, original_sha256):
    """Compare all bytes, allowing only one exact zero-padding load command."""
    head = incoming.read(32); require(len(head) == 32 and head[:4] == b'\xcf\xfa\xed\xfe', 'Expected original ARM64 Unity Mach-O')
    cpu, old_count, old_size = struct.unpack_from('<I', head, 4)[0], struct.unpack_from('<I',head,16)[0], struct.unpack_from('<I',head,20)[0]
    require(cpu == ARM64 and 0 < old_size <= MAX_COMMANDS, 'Original Unity header differs')
    command_path = LOAD_PATH.encode() + b'\0'; length = (24 + len(command_path) + 7) & ~7; added = (struct.pack('<6I',0xC,length,24,0,0,0) + command_path).ljust(length,b'\0')
    old_prefix = head + incoming.read(old_size + length); require(len(old_prefix) == 32 + old_size + length and not any(old_prefix[32 + old_size:]), 'New load command is not in original zero padding')
    cursor = 32; section_offsets = []
    for _ in range(old_count):
        require(cursor + 8 <= 32 + old_size, 'Malformed original Unity command')
        command,size = struct.unpack_from('<II',old_prefix,cursor); require(size >= 8 and size % 8 == 0 and cursor + size <= 32 + old_size, 'Malformed original Unity command size')
        if command == 0x19:
            require(size >= 72, 'Malformed Unity segment'); sections = struct.unpack_from('<I',old_prefix,cursor + 64)[0]; require(size == 72 + sections * 80, 'Malformed Unity sections')
            for index in range(sections):
                at = cursor + 72 + index * 80; amount = struct.unpack_from('<Q',old_prefix,at + 40)[0]; offset = struct.unpack_from('<I',old_prefix,at + 48)[0]; flags = struct.unpack_from('<I',old_prefix,at + 64)[0] & 0xFF
                if amount and offset and flags not in (1,12,18): section_offsets.append(offset)
        cursor += size
    require(cursor == 32 + old_size and section_offsets and 32 + old_size + length <= min(section_offsets), 'Added Unity command overlaps original section data')
    expected = bytearray(old_prefix); struct.pack_into('<II',expected,16,old_count + 1,old_size + length); expected[32 + old_size:] = added
    with Path(patched).open('rb') as replacement:
        require(replacement.read(len(expected)) == expected, 'Patched Unity changed existing load commands or added a different command')
        old_hash = hashlib.sha256(old_prefix); new_hash = hashlib.sha256(expected); size = len(old_prefix)
        while block := incoming.read(CHUNK):
            require(replacement.read(len(block)) == block, 'Patched Unity changed code or original SDK bytes'); old_hash.update(block); new_hash.update(block); size += len(block)
        require(replacement.read(1) == b'' and old_hash.hexdigest() == original_sha256, 'Original Unity size/SHA differs')
    return {'original_sha256':old_hash.hexdigest(),'patched_sha256':new_hash.hexdigest(),'bytes':size,'changed_ranges':[[16,24],[32 + old_size,32 + old_size + length]],'load_path':LOAD_PATH,'code_moved':False,'all_other_Unity_bytes_equal':True}


def stage_app(runtime_root,native_framework,server_data,translations,output,*,target='simulator',manifest=None,web_root=None):
    manifest = manifest or json.loads((HERE / 'runtime_inputs.json').read_text()); require(target == 'simulator', 'Stage-only app is reserved for the Simulator probe'); output = Path(output); require(not output.exists(), 'Fresh prepared app output required')
    files, generated, proofs = bundle_files(runtime_root,native_framework,server_data,translations,target,manifest,web_root,allow_unsigned_native=True); output.mkdir(parents=True)
    for name,path in files.items():
        dest = output / name; dest.parent.mkdir(parents=True,exist_ok=True)
        with path.open('rb') as incoming,dest.open('xb') as outgoing: stream_copy(incoming,outgoing,regular(path).st_size)
        dest.chmod(regular(path).st_mode & 0o777)
    for name,raw in generated.items():
        dest = output / name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
    return {'schema':1,'target':target,'prepared_app':str(output),'files':len(files)+len(generated),'executable_and_Info_provided_by_probe':True,'actual_simulator_execution':False,'native_signing_deferred_to_probe':True}


def package(base_ipa,patched_unity,runtime_root,native_framework,server_data,translations,output,*,source_commit,manifest=None,web_root=None):
    manifest = manifest or json.loads((HERE / 'runtime_inputs.json').read_text()); require(re.fullmatch('[0-9a-f]{40}',source_commit or ''), 'Exact unified source commit required'); verify_file(base_ipa,manifest['inputs']['base_ipa'])
    output = Path(output); partial = output.with_suffix(output.suffix + '.partial'); require(not output.exists() and not partial.exists(), 'Fresh unified IPA output required')
    files, generated, proofs = bundle_files(runtime_root,native_framework,server_data,translations,'device',manifest,web_root)
    max_bytes = manifest['capacity']['max_ipa_bytes']; original_sha = {}; expected = {}; output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(base_ipa) as source:
        infos = source.infolist(); require(len(infos) <= manifest['capacity']['max_archive_entries'] and len({i.filename for i in infos}) == len(infos), 'Original IPA inventory differs')
        for info in infos:
            safe_name(info.filename.rstrip('/')); require(not info.flag_bits & 1 and (info.external_attr >> 16 & 0o170000) != 0o120000, 'Invalid original IPA member')
        matches = [i.filename[:-len('Info.plist')] for i in infos if i.filename.startswith('Payload/') and i.filename.endswith('.app/Info.plist') and i.filename.count('/') == 2]
        require(len(matches) == 1, 'Expected exactly one app bundle'); app = matches[0]
        require(source.getinfo(app + 'Info.plist').file_size <= 128 * 1024, 'Original Info.plist exceeds bound')
        info_raw = source.read(app + 'Info.plist'); info = plistlib.loads(info_raw); info.update(UIFileSharingEnabled=True,LSSupportsOpeningDocumentsInPlace=True,CFBundleVersion='156.9102',CFBundleDisplayName='아이프라 로컬')
        generated['Info.plist'] = plistlib.dumps(info,fmt=plistlib.FMT_BINARY)
        with source.open(app + UNITY) as incoming: unity = verify_unity_patch(incoming,patched_unity,manifest['inputs']['original_unity']['sha256'])
        audit_macho(patched_unity,'device',maximum=256 * 1024**2)
        expanded = sum(i.file_size for i in infos) + sum(regular(p).st_size for p in files.values()) + sum(len(v) for v in generated.values())
        require(expanded <= manifest['capacity']['max_expanded_bytes'], 'Unified IPA expanded capacity exceeded')
        require(sum(i.compress_size for i in infos) + sum(regular(p).st_size for p in files.values()) + 4 * 1024**2 <= max_bytes, 'Unified IPA capacity preflight exceeded')
        require(not any(app + name in source.namelist() for name in files), 'Added runtime overlaps original game data')
        with ZipFile(partial,'x',allowZip64=False) as destination:
            for entry in infos:
                info_copy = copy.copy(entry); name = entry.filename; target_hash = hashlib.sha256()
                if name == app + UNITY:
                    with Path(patched_unity).open('rb') as incoming,destination.open(info_copy,'w') as outgoing: actual = stream_copy(incoming,outgoing,entry.file_size,unity['patched_sha256'])
                    with source.open(entry) as incoming:
                        for block in iter(lambda:incoming.read(CHUNK),b''): target_hash.update(block)
                    original_sha[name] = target_hash.hexdigest()
                elif name == app + 'Info.plist':
                    destination.writestr(info_copy,generated['Info.plist']); actual = hashlib.sha256(generated['Info.plist']).hexdigest(); original_sha[name] = hashlib.sha256(info_raw).hexdigest()
                else:
                    with source.open(entry) as incoming,destination.open(info_copy,'w') as outgoing: actual = stream_copy(incoming,outgoing,entry.file_size)
                    original_sha[name] = actual
                expected[name] = actual; require(destination.fp.tell() <= max_bytes, 'Unified IPA capacity exceeded')
            for name,path in sorted(files.items()):
                entry = ZipInfo(app + name); entry.compress_type = ZIP_STORED if name.endswith('.zip') else ZIP_DEFLATED; entry.external_attr = (regular(path).st_mode & 0xFFFF) << 16
                with path.open('rb') as incoming,destination.open(entry,'w') as outgoing: expected[entry.filename] = stream_copy(incoming,outgoing,regular(path).st_size)
                require(destination.fp.tell() <= max_bytes, 'Unified IPA capacity exceeded')
            for name,raw in generated.items():
                if name == 'Info.plist': continue
                entry = ZipInfo(app + name); entry.compress_type = ZIP_DEFLATED; destination.writestr(entry,raw); expected[entry.filename] = hashlib.sha256(raw).hexdigest()
    require(regular(partial).st_size <= max_bytes, 'Unified IPA final capacity exceeded')
    with ZipFile(partial) as archive:
        require(set(archive.namelist()) == set(expected), 'Unified output inventory differs')
        for name,wanted in expected.items():
            h = hashlib.sha256()
            with archive.open(name) as incoming:
                for block in iter(lambda:incoming.read(CHUNK),b''): h.update(block)
            require(h.hexdigest() == wanted, 'Unified output member SHA/CRC differs')
    os.link(partial,output); partial.unlink()
    report = {'schema':1,'source_commit':source_commit,'base_ipa_sha256':manifest['inputs']['base_ipa']['sha256'],'output_bytes':regular(output).st_size,'output_sha256':sha_file(output),'member_sha256':expected,'original_member_sha256':original_sha,'original_members_preserved_except_Unity_header_and_Info':True,'original_SDK_members_unchanged':True,'Unity_patch':unity,'runtime_target':'device','runtime_framework_count':len(proofs['runtime']['frameworks']),'max_stream_chunk_bytes':CHUNK,'capacity_bytes':max_bytes,'actual_device_or_PlayCover_execution':False,'requires_user_sideload_resigning':True}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n'); return report


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--runtime-root',type=Path,required=True); p.add_argument('--native-framework',type=Path,required=True); p.add_argument('--server-data',type=Path,required=True); p.add_argument('--translations',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--stage-only',action='store_true'); p.add_argument('--target',choices=tuple(PLATFORMS),default='device'); p.add_argument('--base-ipa',type=Path); p.add_argument('--patched-unity',type=Path); p.add_argument('--source-commit'); a = p.parse_args()
    if a.stage_only: report = stage_app(a.runtime_root,a.native_framework,a.server_data,a.translations,a.output,target=a.target)
    else:
        require(a.target == 'device' and a.base_ipa and a.patched_unity and a.source_commit, 'Device IPA requires exact source, base IPA and patched Unity')
        report = package(a.base_ipa,a.patched_unity,a.runtime_root,a.native_framework,a.server_data,a.translations,a.output,source_commit=a.source_commit)
    print(json.dumps({'status':'PASS_PREPARED_UNIFIED_IOS_PACKAGE','output':str(a.output),'physical_execution_verified':False}))
if __name__ == '__main__': main()
