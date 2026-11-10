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
CLIENTS = {
    'local': ('game.qualiarts.idolypride.local', '아이프라 로컬'),
    'original': ('game.qualiarts.idolypride', 'アイプラ'),
}
BACKEND_SOURCE = '42158bade5fce76af03524d2adebafb9334bb44f'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ax-driver', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=480)
    parser.add_argument('--ipa-variant', choices=tuple(CLIENTS), default='local')
    parser.add_argument('--compare-canonical-launch', action='store_true',
        help='After the known UIKit check-in failure, compare normal LaunchServices opening of the prepared installed bundle')
    args = parser.parse_args()
    game, expected_label = CLIENTS[args.ipa_variant]
    args.input = args.input.resolve(); args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + min(max(args.timeout, 1), 480)
    report = {'schema': 1, 'environment': 'ephemeral_GitHub_hosted_Mac_not_user_Mac',
              'source_commit': os.environ.get('GITHUB_SHA'), 'workflow_run_id': os.environ.get('GITHUB_RUN_ID'), 'game_bundle': game,
              'client_variant': args.ipa_variant, 'local_client_patch_present': args.ipa_variant == 'local',
              'backend_applies_to_client': args.ipa_variant == 'local',
              'playcover_source': 'a7b1693d4fa4310367990cd35d4ebafb20e5c965',
              'game_launched': False, 'gameplay_verified': False, 'credentials_supplied': False,
              'security_settings_changed': False, 'unknown_dialog_stopped': False}
    backend = None; mounted = None

    def command(argv, *, timeout=30, check=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('bounded_firstboot_deadline')
        result = subprocess.run([str(value) for value in argv], capture_output=True, text=True,
                                timeout=min(timeout, remaining), check=False)
        if check and result.returncode:
            # Installer and LaunchServices errors are needed to distinguish an
            # application launch refusal from a crash inside a launched app.
            (args.output / 'failed-command.json').write_text(json.dumps({
                'argv': [str(value) for value in argv], 'exit_code': result.returncode,
                'stdout': result.stdout[:8192], 'stderr': result.stderr[:8192]}, indent=2) + '\n')
            result.check_returncode()
        return result

    def observe(stage, bundle=PLAYCOVER, action=None, label=None, allow_starting=False):
        destination = (args.output / stage).with_suffix('.json')
        argv = [args.ax_driver, '--output', destination]
        if action:
            argv += [action, label, '--bundle', bundle]
        else:
            argv += ['--inspect', bundle]
        result = command(argv, timeout=20, check=False)
        destination.with_suffix('.driver-stderr.txt').write_text(result.stderr[:8192])
        destination.with_suffix('.driver-stdout.txt').write_text(result.stdout[:8192])
        # The driver writes snapshots itself even when refusing an input.
        snapshot = destination.with_suffix('.json')
        if snapshot.is_file():
            state = json.loads(snapshot.read_text())
        elif result.stdout.strip().startswith('{'):
            state = json.loads(result.stdout)
        else:
            raise RuntimeError('AX_observation_unavailable_exit_' + str(result.returncode))
        if result.returncode:
            raise RuntimeError('AX_driver_refused_or_failed')
        if state.get('visible_dialog_present') is True:
            report['unknown_dialog_stopped'] = True
            raise RuntimeError('unknown_dialog_observed')
        starting_without_window = allow_starting and (
            state.get('running') is False or state.get('ax_windows_available') is False
            or not state.get('tree'))
        # Losing focus after process exit is an observation, not an input.
        # Before any subsequent launch, recheck the foreground PlayCover UI.
        observed_game_exit = action is None and bundle == game and state.get('running') is False
        if (not starting_without_window and not observed_game_exit
                and state.get('frontmost_bundle') not in (None, '', PLAYCOVER, game)):
            report['unknown_dialog_stopped'] = True
            raise RuntimeError('unknown_frontmost_UI_observed')
        return state

    def game_log(pid, name):
        captured = command(['/usr/bin/log', 'show', '--last', '3m', '--info', '--style', 'compact',
            '--predicate', 'processIdentifier == ' + str(int(pid))], timeout=15, check=False)
        selected = []
        for line in captured.stdout.splitlines():
            if re.search(r'token|authorization|bearer|password|firebase|api.?key|idfa|advertising', line, re.I):
                continue
            if re.search(r'Unity|Metal|Exception|Error|render|initializ|shader|loading|UISApplicationSupportService', line, re.I):
                selected.append(line[:1000])
        text = '\n'.join(selected[-300:]) + '\n'
        (args.output / name).write_text(text)
        return text

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
        # Pinned PlayCover initializes AppsVM.shared from its main library
        # view. A cold file-open event can reach Installer.wrap before that
        # initialization has created Applications. Let the official app finish
        # its normal startup and bundled PlayTools copy before importing.
        command(['/usr/bin/open', '-a', target])
        applications = Path.home() / 'Library/Containers/io.playcover.PlayCover/Applications'
        playtools = Path.home() / 'Library/Frameworks/PlayTools.framework'
        until = min(deadline, time.monotonic() + 90)
        initialization = []
        while time.monotonic() < until:
            initial = observe('00-PlayCover-initialization-' + str(len(initialization)), allow_starting=True)
            ready = {'main_window_present': initial.get('running') is True
                     and any(row.get('role') == 'AXWindow' for row in initial.get('tree', [])),
                     'applications_directory_present': applications.is_dir(),
                     'playtools_binary_readable': os.access(playtools / 'PlayTools', os.R_OK),
                     'playtools_plugin_present': (playtools / 'PlugIns/AKInterface.bundle').is_dir()}
            initialization.append(ready)
            if all(ready.values()):
                break
            time.sleep(2)
        report['official_initialization_observations'] = initialization
        if not initialization or not all(initialization[-1].values()):
            raise RuntimeError('official_PlayCover_initialization_not_complete')
        report['official_PlayCover_initialization_ready'] = True
        ipa = args.input / 'IdolyPride-Under-Test.ipa'
        command(['/usr/bin/open', '-a', target, ipa])
        time.sleep(3)
        observe('01-import-requested')
        installed = applications / (game + '.app')
        until = min(deadline, time.monotonic() + 150)
        while time.monotonic() < until and not (installed / 'Info.plist').is_file():
            observe('02-import-wait')
            time.sleep(5)
        if not (installed / 'Info.plist').is_file():
            raise RuntimeError('official_IPA_import_not_complete')
        info = plistlib.loads((installed / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != game:
            raise RuntimeError('installed_game_bundle_mismatch')
        command(['/usr/bin/codesign', '--verify', '--deep', '--strict', installed])
        report['IPA_installed'] = True
        report[args.ipa_variant + '_IPA_installed'] = True
        report['installed_game_version'] = info.get('CFBundleShortVersionString')
        # Preserve the converted bundle contract before launching. These are
        # installation metadata, not the game's account or preferences files.
        metadata_keys = ('CFBundleIdentifier', 'CFBundleExecutable', 'CFBundleShortVersionString',
            'CFBundleSupportedPlatforms', 'LSRequiresIPhoneOS', 'UIDeviceFamily',
            'UIApplicationSceneManifest', 'UISupportsTrueScreenSizeOnMac',
            'UIRequiresFullScreen', 'UIRequiredDeviceCapabilities', 'MinimumOSVersion')
        (args.output / 'installed-game-info.json').write_text(json.dumps(
            {key: info.get(key) for key in metadata_keys}, ensure_ascii=False, indent=2) + '\n')
        metadata_commands = {
            'installed-game-entitlements': ['/usr/bin/codesign', '--display', '--entitlements', ':-', installed],
            'installed-game-main-load-commands': ['/usr/bin/otool', '-l', installed / info['CFBundleExecutable']],
            'installed-game-unity-load-commands': ['/usr/bin/otool', '-l',
                installed / 'Frameworks/UnityFramework.framework/UnityFramework']}
        for name, argv in metadata_commands.items():
            try:
                captured = command(argv, timeout=10, check=False)
                value = {'exit_code': captured.returncode, 'stdout': captured.stdout[:65536],
                         'stderr': captured.stderr[:8192]}
            except (OSError, subprocess.TimeoutExpired) as error:
                value = {'capture_error': type(error).__name__}
            (args.output / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')
        label = info.get('CFBundleDisplayName') or info.get('CFBundleName')
        if label != expected_label:
            raise RuntimeError('unexpected_game_display_name')
        # Read the installer-created alias without delaying the first process
        # observation after the normal game launch. Do not modify either path.
        alias = Path.home() / 'Applications/PlayCover' / (label + '.app')
        alias_report = {'path': str(alias), 'exists': alias.is_dir()}
        if alias.is_dir():
            alias_info = alias / 'Info.plist'
            alias_report['info_matches_installed'] = alias_info.read_bytes() == (installed / 'Info.plist').read_bytes()
            alias_executable = alias / info['CFBundleExecutable']
            alias_report['executable_is_symlink'] = alias_executable.is_symlink()
            alias_report['executable_resolved_path'] = str(alias_executable.resolve())
            verification = command(['/usr/bin/codesign', '--verify', '--deep', '--strict', alias], check=False)
            alias_report['codesign_verify_exit_code'] = verification.returncode
            alias_report['codesign_verify_stderr'] = verification.stderr[:8192]
        (args.output / 'installed-game-alias.json').write_text(json.dumps(alias_report, ensure_ascii=False, indent=2) + '\n')
        observe('03-before-launch')
        observe('04-normal-doubleclick', action='--double-click-label', label=label)
        until = min(deadline, time.monotonic() + 120)
        samples = []
        phase = 'official_PlayCover_GUI'
        started_this_phase = False
        report['launch_phases'] = [{'kind': phase, 'samples': samples}]
        while time.monotonic() < until:
            state = observe('05-game-' + phase + '-' + str(len(samples)), game)
            samples.append({'running': state.get('running'), 'pid': state.get('pid')})
            if state.get('running') is True and state.get('pid'):
                started_this_phase = True
                report['game_launched'] = True
                report['game_pid'] = state['pid']
            if started_this_phase and state.get('running') is not True:
                if args.compare_canonical_launch and phase == 'official_PlayCover_GUI':
                    original_log = game_log(report['game_pid'], 'game-official-filtered-log.txt')
                    if 'UIKit applications must check-in via UISApplicationSupportService before creating scenes' not in original_log:
                        raise RuntimeError('canonical_comparison_requires_observed_UIKit_checkin_failure')
                    report['launch_phases'][-1]['error'] = 'UIKit_checkin_failure_and_process_exit'
                    # This is a normal LaunchServices application open, after
                    # official PlayCover preparation and the observed failure.
                    # Never execute the game binary directly.
                    command(['/usr/bin/open', '-a', target])
                    time.sleep(1)
                    observe('06-before-canonical-launch')
                    command(['/usr/bin/open', installed])
                    report['canonical_comparison_attempted'] = True
                    phase = 'prepared_canonical_LaunchServices'
                    started_this_phase = False
                    samples = []
                    report['launch_phases'].append({'kind': phase, 'samples': samples})
                    until = min(deadline, time.monotonic() + 120)
                    continue
                raise RuntimeError('game_process_exited_after_launch')
            time.sleep(10)
        report['game_samples'] = samples
        if not started_this_phase:
            raise RuntimeError('game_process_not_observed')
        report['outcome'] = 'game_process_observed_UI_and_loading_require_review'
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error)[:300]
        try: observe('99-final-PlayCover')
        except Exception: pass
    finally:
        if report.get('game_pid'):
            try:
                game_log(report['game_pid'], 'game-filtered-log.txt')
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
        print(json.dumps({key: report.get(key) for key in ('client_variant', 'playcover_installed', 'IPA_installed',
            'game_launched', 'outcome', 'error_type', 'error', 'unknown_dialog_stopped')}, ensure_ascii=False))
    return 0 if report.get('game_launched') and not report.get('error') else 1


if __name__ == '__main__':
    raise SystemExit(main())
