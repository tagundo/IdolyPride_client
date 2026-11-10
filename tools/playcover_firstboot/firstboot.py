#!/usr/bin/env python3
"""One bounded normal PlayCover import/launch on a fresh GitHub-hosted Mac.

Uses the pinned release's official file-open importer and AX-derived normal
double click. Unknown dialogs stop the run. No login or permission automation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import signal
import socket
import subprocess
import time
from zipfile import ZipFile

PLAYCOVER = 'io.playcover.PlayCover'
GAME = 'game.qualiarts.idolypride.local'
BACKEND_SOURCE = '42158bade5fce76af03524d2adebafb9334bb44f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ax-driver', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=480)
    args = parser.parse_args()
    args.input = args.input.resolve(); args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + min(max(args.timeout, 1), 480)
    report = {'schema': 1, 'environment': 'ephemeral_GitHub_hosted_Mac_not_user_Mac',
              'source_commit': os.environ.get('GITHUB_SHA'), 'workflow_run_id': os.environ.get('GITHUB_RUN_ID'), 'game_bundle': GAME,
              'playcover_source': 'a7b1693d4fa4310367990cd35d4ebafb20e5c965',
              'game_launched': False, 'gameplay_verified': False, 'credentials_supplied': False,
              'security_settings_changed': False, 'unknown_dialog_stopped': False}
    backend = None; mounted = None

    def command(argv, *, timeout=30, check=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('bounded_firstboot_deadline')
        return subprocess.run([str(value) for value in argv], capture_output=True, text=True,
                              timeout=min(timeout, remaining), check=check)

    def observe(stage, bundle=PLAYCOVER, action=None, label=None):
        destination = (args.output / stage).with_suffix('.json')
        argv = [args.ax_driver, '--output', destination]
        if action:
            argv += [action, label, '--bundle', bundle]
        else:
            argv += ['--inspect', bundle]
        result = command(argv, timeout=20, check=False)
        # The driver writes snapshots itself even when refusing an input.
        snapshot = destination.with_suffix('.json')
        if snapshot.is_file():
            state = json.loads(snapshot.read_text())
        elif result.stdout.strip().startswith('{'):
            state = json.loads(result.stdout)
        else:
            raise RuntimeError('AX_observation_unavailable')
        if result.returncode:
            raise RuntimeError('AX_driver_refused_or_failed')
        if state.get('visible_dialog_present') is True:
            report['unknown_dialog_stopped'] = True
            raise RuntimeError('unknown_dialog_observed')
        if state.get('frontmost_bundle') not in (None, '', PLAYCOVER, GAME):
            report['unknown_dialog_stopped'] = True
            raise RuntimeError('unknown_frontmost_UI_observed')
        return state

    try:
        # Both payloads are independently hash-pinned by the workflow. Reject
        # traversal before using the platform's bundle-preserving ZIP tool.
        archive = args.input / 'IdolyPride-Server-macOS.app.zip'
        with ZipFile(archive) as zipped:
            if zipped.testzip() is not None:
                raise RuntimeError('backend_archive_CRC')
            for item in zipped.infolist():
                path = PurePosixPath(item.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in item.filename:
                    raise RuntimeError('backend_archive_path')
        backend_folder = Path(os.environ['RUNNER_TEMP']) / 'playcover-backend'
        command(['/usr/bin/ditto', '-x', '-k', archive, backend_folder])
        apps = list(backend_folder.glob('*.app'))
        if len(apps) != 1:
            raise RuntimeError('backend_bundle_ambiguous')
        resources = apps[0] / 'Contents/Resources'
        provenance = json.loads((resources / 'bundle-provenance.json').read_text())
        if provenance.get('source_commit') != BACKEND_SOURCE:
            raise RuntimeError('backend_source_provenance_mismatch')
        report['backend_source_commit'] = BACKEND_SOURCE
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', apps[0]])
        environment = os.environ.copy()
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH'):
            environment.pop(key, None)
        environment['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
        for port in (50051, 8080):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
        server_log = (args.output / 'backend.jsonl').open('w')
        server_error = (args.output / 'backend-stderr.txt').open('w')
        backend = subprocess.Popen([str(resources / 'runtime/IdolyServerEngine'), '--json-control',
            '--data-dir', str(Path(os.environ['RUNNER_TEMP']) / 'playcover-fresh-local-profile'),
            '--server-data', str(resources / 'ServerData.zip')], stdin=subprocess.PIPE,
            stdout=server_log, stderr=server_error, text=True, env=environment, start_new_session=True)
        backend.stdin.write(json.dumps({'action': 'start', 'experimental_main_live': False}) + '\n'); backend.stdin.flush()
        ready = False
        until = min(deadline, time.monotonic() + 90)
        while time.monotonic() < until and backend.poll() is None:
            try:
                with socket.create_connection(('127.0.0.1', 50051), timeout=1):
                    ready = True; break
            except OSError:
                time.sleep(1)
        if not ready:
            raise RuntimeError('backend_not_ready')
        report['backend_running'] = True
        report['experimental_main_live_enabled'] = False

        disk = command(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', args.input / 'PlayCover.dmg'])
        disks = plistlib.loads(disk.stdout.encode())
        mountpoints = [entry['mount-point'] for entry in disks['system-entities'] if 'mount-point' in entry]
        if len(mountpoints) != 1:
            raise RuntimeError('PlayCover_disk_mount_ambiguous')
        mounted = mountpoints[0]
        source_app = Path(mounted) / 'PlayCover.app'
        if not source_app.is_dir():
            raise RuntimeError('official_PlayCover_app_missing')
        target = Path('/Applications/PlayCover.app')
        if target.exists():
            raise RuntimeError('fresh_host_PlayCover_already_present')
        command(['/usr/bin/ditto', source_app, target])
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', target])
        report['playcover_installed'] = True
        command(['/usr/bin/hdiutil', 'detach', mounted]); mounted = None
        ipa = args.input / 'IdolyPride-Local-PlayCover.ipa'
        command(['/usr/bin/open', '-a', target, ipa])
        time.sleep(3)
        observe('01-import-requested')
        installed = Path.home() / 'Library/Containers/io.playcover.PlayCover/Applications' / (GAME + '.app')
        until = min(deadline, time.monotonic() + 150)
        while time.monotonic() < until and not (installed / 'Info.plist').is_file():
            observe('02-import-wait')
            time.sleep(5)
        if not (installed / 'Info.plist').is_file():
            raise RuntimeError('official_IPA_import_not_complete')
        info = plistlib.loads((installed / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != GAME:
            raise RuntimeError('installed_game_bundle_mismatch')
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', installed])
        report['local_IPA_installed'] = True
        report['installed_game_version'] = info.get('CFBundleShortVersionString')
        label = info.get('CFBundleDisplayName') or info.get('CFBundleName')
        if label != '아이프라 로컬':
            raise RuntimeError('unexpected_local_game_display_name')
        observe('03-before-launch')
        observe('04-normal-doubleclick', action='--double-click-label', label=label)
        until = min(deadline, time.monotonic() + 120)
        samples = []
        while time.monotonic() < until:
            state = observe('05-game-observation-' + str(len(samples)), GAME)
            samples.append({'running': state.get('running'), 'pid': state.get('pid')})
            if state.get('running') is True and state.get('pid'):
                report['game_launched'] = True
                report['game_pid'] = state['pid']
            if report['game_launched'] and state.get('running') is not True:
                raise RuntimeError('game_process_exited_after_launch')
            time.sleep(10)
        report['game_samples'] = samples
        if not report['game_launched']:
            raise RuntimeError('game_process_not_observed')
        report['outcome'] = 'local_game_process_observed_UI_and_loading_require_review'
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error)[:300]
        try: observe('99-final-PlayCover')
        except Exception: pass
    finally:
        if report.get('game_pid'):
            try:
                logs = command(['/usr/bin/log', 'show', '--last', '3m', '--style', 'compact',
                    '--predicate', 'processIdentifier == ' + str(int(report['game_pid']))], timeout=10, check=False)
                selected = []
                for line in logs.stdout.splitlines():
                    if re.search(r'token|authorization|bearer|password|firebase|api.?key|idfa|advertising', line, re.I):
                        continue
                    if re.search(r'Unity|Metal|Exception|Error|render|initializ|shader|loading', line, re.I):
                        selected.append(line[:500])
                (args.output / 'game-filtered-log.txt').write_text('\n'.join(selected[-200:]) + '\n')
            except Exception:
                report['game_log_capture_failed'] = True
        if backend is not None and backend.poll() is None:
            try:
                backend.stdin.write('{"action":"quit"}\n'); backend.stdin.flush(); backend.wait(timeout=10)
            except Exception:
                os.killpg(backend.pid, signal.SIGTERM)
        if mounted:
            subprocess.run(['/usr/bin/hdiutil', 'detach', mounted], capture_output=True, timeout=10)
        report['driver_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({key: report.get(key) for key in ('playcover_installed', 'local_IPA_installed',
            'game_launched', 'outcome', 'error_type', 'error', 'unknown_dialog_stopped')}, ensure_ascii=False))
    return 0 if report.get('game_launched') and not report.get('error') else 1


if __name__ == '__main__':
    raise SystemExit(main())
