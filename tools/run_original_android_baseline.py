#!/usr/bin/env python3
"""Observe the signed original game; only acknowledge its exact Android fullscreen hint."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

PACKAGE = 'game.qualiarts.idolypride'
XAPK_SHA = 'ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36'
CERT_SHA = '06cede031cd36c1986928fb5a9339c859253c07e06aff6137503d8385d3291b5'
APK_SHAS = {'3d54e05f897bfb54716a0ad645562955ceb0081cead696cb29595941ac08faa9',
            'b91a53316f230b48e290145f9625ca5caf5d40180c3de6ab1dce5171912aba67'}


def command(args: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, check=check)


def adb(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return command(['adb', *args], **kwargs)


def decoded(result: subprocess.CompletedProcess) -> str:
    return (result.stdout + result.stderr).decode('utf-8', errors='replace')


def optional_adb(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    try:
        return adb(*args, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(['adb', *args], 124, error.stdout or b'',
            (error.stderr or b'') + b'\nADB observation timed out')


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def fullscreen_hint(xml: bytes) -> tuple[int, int, int, int] | None:
    """Recognize the exact OS-owned hint observed in the untouched first run."""
    expected = {'android:id/immersive_cling_title': 'Viewing full screen',
                'android:id/immersive_cling_description': 'To exit, swipe down from the top of your screen',
                'android:id/ok': 'Got it'}
    try:
        nodes = list(ET.fromstring(xml).iter('node'))
    except ET.ParseError:
        return None
    if {node.get('text') for node in nodes if node.get('text')} != set(expected.values()):
        return None
    for identity, text in expected.items():
        matches = [node for node in nodes if node.get('resource-id') == identity]
        if len(matches) != 1 or matches[0].get('text') != text or matches[0].get('package') != 'android':
            return None
        if matches[0].get('enabled') != 'true' or matches[0].get('visible-to-user', 'true') != 'true':
            return None
    button = next(node for node in nodes if node.get('resource-id') == 'android:id/ok')
    if button.get('class') != 'android.widget.Button' or button.get('clickable') != 'true':
        return None
    bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', button.get('bounds', ''))
    if bounds is None:
        return None
    left, top, right, bottom = map(int, bounds.groups())
    return (left, top, right, bottom) if left < right and top < bottom else None


def dump_ui(output: Path, name: str) -> bytes | None:
    result = optional_adb('shell', 'uiautomator', 'dump', '--compressed', '/sdcard/idoly-baseline-window.xml')
    if result.returncode != 0:
        return None
    result = optional_adb('exec-out', 'cat', '/sdcard/idoly-baseline-window.xml')
    if result.returncode != 0 or len(result.stdout) > 262144:
        return None
    (output / name).write_bytes(result.stdout)
    return result.stdout


def dismiss_fullscreen_hint(output: Path, report: dict) -> None:
    action = {'kind': 'Android fullscreen onboarding acknowledgement', 'tap_performed': False}
    report['system_UI_actions'].append(action)
    first = dump_ui(output, 'systemui-hint-before-1.xml')
    second = dump_ui(output, 'systemui-hint-before-2.xml')
    bounds = fullscreen_hint(first or b'')
    if bounds is None or bounds != fullscreen_hint(second or b''):
        action['outcome'] = 'fresh exact hint mismatch; no input'
        return
    screenshot = optional_adb('exec-out', 'screencap', '-p', timeout=30)
    if screenshot.returncode != 0 or not screenshot.stdout.startswith(b'\x89PNG') or len(screenshot.stdout) < 24:
        action['outcome'] = 'fresh screenshot unavailable; no input'
        return
    (output / 'systemui-hint-before.png').write_bytes(screenshot.stdout)
    width, height = struct.unpack('!II', screenshot.stdout[16:24])
    left, top, right, bottom = bounds
    if right > width or bottom > height:
        action['outcome'] = 'hint outside fresh screen; no input'
        return
    action['bounds'] = list(bounds)
    action['center'] = [(left + right) // 2, (top + bottom) // 2]
    tap = optional_adb('shell', 'input', 'tap', *(str(value) for value in action['center']))
    action['tap_returncode'] = tap.returncode
    action['tap_performed'] = True
    report['UI_input_performed'] = True
    report['system_UI_input_performed'] = True
    after = dump_ui(output, 'systemui-hint-after.xml')
    post_image = optional_adb('exec-out', 'screencap', '-p', timeout=30)
    if post_image.returncode == 0 and post_image.stdout.startswith(b'\x89PNG'):
        (output / 'systemui-hint-after.png').write_bytes(post_image.stdout)
    action['hint_absent_after'] = after is not None and b'android:id/immersive_cling_title' not in after
    action['outcome'] = 'hint dismissed' if tap.returncode == 0 and action['hint_absent_after'] else 'dismissal not verified; no further input'


def prepare(xapk: Path, output: Path) -> None:
    assert xapk.stat().st_size == 167699540, 'Original XAPK size mismatch'
    with xapk.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == XAPK_SHA, 'Original XAPK digest mismatch'
    sdk = Path(os.environ['ANDROID_HOME'])
    tools = sdk / 'build-tools/35.0.0'
    destination = Path(os.environ['RUNNER_TEMP']) / 'original-idoly-apks'
    destination.mkdir()
    records = []
    with zipfile.ZipFile(xapk) as archive:
        names = [name for name in archive.namelist() if name.endswith('.apk')]
        assert len(names) == 2 and len({Path(name).name for name in names}) == 2, 'Expected original base and ARM64 split'
        for name in names:
            target = destination / Path(name).name
            content = archive.read(name)
            assert hashlib.sha256(content).hexdigest() in APK_SHAS, 'Unexpected original APK bytes'
            target.write_bytes(content)
            signature = decoded(command([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(target)]))
            certificates = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)', signature)
            assert certificates == [CERT_SHA], 'Original APK signing certificate mismatch'
            badging = decoded(command([str(tools / 'aapt2'), 'dump', 'badging', str(target)]))
            assert "name='game.qualiarts.idolypride'" in badging.splitlines()[0], 'Unexpected package'
            assert "versionCode='414'" in badging.splitlines()[0], 'Unexpected version'
            (output / (target.name + '.signature.txt')).write_text(signature)
            (output / (target.name + '.badging.txt')).write_text(badging)
            records.append({'file': target.name, 'install_path': str(target), 'bytes': len(content),
                            'sha256': hashlib.sha256(content).hexdigest(), 'certificate_sha256': CERT_SHA})
    write_json(output / 'inputs.json', {'asset_id': 725772331, 'xapk_sha256': XAPK_SHA,
        'original_apks_unmodified': True, 'apks': records})


def collect_logs(output: Path, pids: set[str]) -> None:
    sensitive = re.compile(r'token|password|authorization|firebase|api.?key|advertising.?id|eyJ[\w-]+\.[\w-]+\.[\w-]+', re.I)
    logs = decoded(optional_adb('logcat', '-d', '-v', 'threadtime', timeout=30))
    selected = []
    for line in logs.splitlines():
        fields = line.split()
        owned = len(fields) > 2 and fields[2] in pids
        relevant = PACKAGE in line or bool(re.search(
            r'FATAL EXCEPTION|Fatal signal|>>> game\.qualiarts|libndk_translation|UnsatisfiedLinkError', line))
        if (owned or relevant) and not sensitive.search(line):
            selected.append(re.sub(r'(https?://[^\s?]+)\?\S+', r'\1?[query omitted]', line)[:4096])
    (output / 'game-filtered-logcat.txt').write_text('\n'.join(selected)[-2097152:] + '\n')
    crash = decoded(optional_adb('logcat', '-b', 'crash', '-d', '-v', 'threadtime'))
    (output / 'crash-filtered.txt').write_text('\n'.join(line[:4096] for line in crash.splitlines()
        if not sensitive.search(line))[-1048576:] + '\n')


def packet_metadata(path: Path) -> dict:
    """Read only packet headers into aggregates; never export payloads or raw PCAP."""
    if not path.is_file():
        return {'available': False}
    flows: dict[tuple, dict] = {}
    count = 0
    with path.open('rb') as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] not in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4'):
            return {'available': True, 'supported_format': False}
        endian = '<' if header[:4] == b'\xd4\xc3\xb2\xa1' else '>'
        linktype = struct.unpack(endian + 'I', header[20:24])[0]
        if linktype != 1:
            return {'available': True, 'supported_format': False, 'linktype': linktype}
        while count < 200000:
            record = stream.read(16)
            if len(record) != 16:
                break
            _, _, size, original_size = struct.unpack(endian + 'IIII', record)
            if size > 1048576:
                break
            packet = stream.read(size)
            if len(packet) != size:
                break
            count += 1
            if len(packet) < 34 or packet[12:14] != b'\x08\x00':
                continue
            header_size = (packet[14] & 15) * 4
            if packet[14] >> 4 != 4 or header_size < 20 or struct.unpack('!H', packet[20:22])[0] & 0x1fff:
                continue
            offset = 14 + header_size
            protocol = packet[23]
            if protocol not in (6, 17) or len(packet) < offset + 4:
                continue
            ports = struct.unpack('!HH', packet[offset:offset + 4])
            key = (str(ipaddress.ip_address(packet[26:30])), ports[0],
                   str(ipaddress.ip_address(packet[30:34])), ports[1], 'TCP' if protocol == 6 else 'UDP')
            if key not in flows and len(flows) >= 512:
                continue
            entry = flows.setdefault(key, {'packets': 0, 'wire_bytes': 0})
            entry['packets'] += 1
            entry['wire_bytes'] += original_size
    return {'available': True, 'supported_format': True, 'payloads_exported': False,
            'scope': 'whole fresh emulator, not exclusively the game; encrypted traffic is not RPC evidence',
            'records_read': count, 'flows': [dict(zip(('source', 'source_port', 'destination', 'destination_port', 'protocol'), key), **value)
                                             for key, value in sorted(flows.items())]}


def observe(output: Path, duration: int, pcap: Path | None) -> None:
    report = {'workflow_sha': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
              'original_apks_unmodified': True, 'UI_input_performed': False, 'gameplay_verified': False,
              'system_UI_input_performed': False, 'system_UI_actions': [],
              'gameplay_UI_input_performed': False, 'account_UI_input_performed': False,
              'account_credentials_supplied': False, 'observation_seconds_requested': duration, 'samples': []}
    pids: set[str] = set()
    try:
        properties = ['ro.build.version.sdk', 'ro.build.fingerprint', 'ro.product.cpu.abi',
                      'ro.product.cpu.abilist', 'ro.dalvik.vm.native.bridge', 'ro.hardware.egl', 'ro.boot.qemu.avd_name']
        report['image_properties'] = {key: decoded(adb('shell', 'getprop', key)).strip() for key in properties}
        image = Path(os.environ['ANDROID_HOME']) / 'system-images/android-35/google_apis_playstore/x86_64'
        source_properties = (image / 'source.properties').read_text()
        (output / 'image-source.properties').write_text(source_properties)
        assert re.search(r'^Pkg.Revision\s*=\s*9\s*$', source_properties, re.M), 'Unexpected official image revision'
        (output / 'surfaceflinger-before.txt').write_text(decoded(adb('shell', 'dumpsys', 'SurfaceFlinger'))[:131072])
        (output / 'native-bridge-files.txt').write_text(decoded(adb('shell', 'ls', '-l',
            '/system/lib64/libndk_translation.so', '/system/lib64/libhoudini.so', check=False)))
        inputs = json.loads((output / 'inputs.json').read_text())
        installed = optional_adb('install-multiple', *[row['install_path'] for row in inputs['apks']], timeout=180)
        (output / 'install.txt').write_text(decoded(installed))
        report['install_returncode'] = installed.returncode
        assert installed.returncode == 0 and 'Success' in decoded(installed), 'Original installation did not succeed; see install.txt'
        report['original_installed'] = True
        (output / 'installed-package.txt').write_text(decoded(adb('shell', 'dumpsys', 'package', PACKAGE))[:131072])
        activity = decoded(adb('shell', 'cmd', 'package', 'resolve-activity', '--brief', PACKAGE)).strip().splitlines()[-1]
        assert activity == PACKAGE + '/com.google.firebase.MessagingUnityPlayerActivity', 'Unexpected official launch activity'
        report['launch_activity'] = activity
        adb('logcat', '-c')
        started = optional_adb('shell', 'am', 'start', '-W', '-n', activity, timeout=60)
        (output / 'start.txt').write_text(decoded(started))
        report['activity_start_returncode'] = started.returncode
        assert started.returncode == 0 and 'Error:' not in decoded(started), 'Original activity start failed; see start.txt'
        epoch = time.monotonic()
        for target in (0, 15, 30, 60, 120, duration):
            remaining = epoch + target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            current = decoded(adb('shell', 'pidof', PACKAGE, check=False)).strip().split()
            pids.update(value for value in current if value.isdecimal())
            sample = {'elapsed_seconds': round(time.monotonic() - epoch, 1), 'pids': current}
            image_result = optional_adb('exec-out', 'screencap', '-p', timeout=30)
            if image_result.returncode == 0 and image_result.stdout.startswith(b'\x89PNG'):
                (output / f'screen-{target:03d}.png').write_bytes(image_result.stdout)
                sample['screenshot'] = True
            tree = optional_adb('shell', 'uiautomator', 'dump', '--compressed', '/sdcard/idoly-baseline-window.xml')
            sample['ui_dump_returncode'] = tree.returncode
            if tree.returncode == 0:
                xml = optional_adb('exec-out', 'cat', '/sdcard/idoly-baseline-window.xml')
                if xml.returncode == 0:
                    (output / f'ui-{target:03d}.xml').write_bytes(xml.stdout[:262144])
                    if not report['system_UI_actions'] and fullscreen_hint(xml.stdout) is not None:
                        dismiss_fullscreen_hint(output, report)
            report['samples'].append(sample)
            write_json(output / 'result.json', report)
        report['observed_game_pids'] = sorted(pids)
        report['process_alive_at_end'] = bool(report['samples'][-1]['pids'])
        report['baseline_observation_completed'] = True
    except Exception as error:
        report['error'] = str(error)[:2048]
        report['error_type'] = type(error).__name__
        raise
    finally:
        collect_logs(output, pids)
        if pcap is not None:
            write_json(output / 'network-metadata.json', packet_metadata(pcap))
        write_json(output / 'result.json', report)
        print(json.dumps({key: report.get(key) for key in ('original_installed', 'observed_game_pids',
            'process_alive_at_end', 'baseline_observation_completed', 'gameplay_verified', 'error')}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--xapk', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observe-seconds', type=int, default=180, choices=[180])
    parser.add_argument('--pcap', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        assert args.xapk is not None, '--xapk is required to prepare originals'
        prepare(args.xapk, args.output)
    else:
        observe(args.output, args.observe_seconds, args.pcap)


if __name__ == '__main__':
    main()
