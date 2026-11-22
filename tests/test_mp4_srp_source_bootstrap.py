"""Shipping initial SRP source composition; CPU/query/worker leaves modeled."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'tests/fixtures'


def test_initial_source_receipt_is_not_private_mutation_authority(tmp_path):
    s = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    begin = '// BEGIN_MP4_SRP_SOURCE_BOOTSTRAP_HOST'
    end = '// END_MP4_SRP_SOURCE_BOOTSTRAP_HOST'
    assert s.count(begin) == s.count(end) == 1
    body = s[s.index(begin):s.index(end)+len(end)]+"\n"
    source = ((F / 'mp4_srp_source_bootstrap_prefix.cpp.inc').read_text()+body+
              (F / 'mp4_srp_source_bootstrap_driver.cpp.inc').read_text())
    path, binary = tmp_path / 'host.cpp', tmp_path / 'host'
    path.write_text(source)
    result = subprocess.run([
        shutil.which('g++') or 'clang++', '-std=c++17', '-Wall', '-Wextra',
        '-Werror', '-Wno-misleading-indentation', '-g', '-O1',
        '-fsanitize=address,undefined', '-fno-pie', '-no-pie', str(path),
        '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
    cases = ('source no_worker no_producer no_early wrong_key raw rebuilding '
             'no_gate unheld camera_unheld no_intercept capture_refused '
             'read_refused throw changed_worker queue_changed first_changed '
             'subscriber_changed foreign lease_open lease_poison changed_source '
             'late_real withdraw busy_release program program_open program_owned program_rejected mutated_wait mutated_restore retired_mutation unknown_mutation restore_before_parts new_unknown_after_restore').split()
    for case in cases:
        result = subprocess.run([str(binary), case], capture_output=True, text=True)
        assert result.returncode == 0, (case, result.stdout, result.stderr)
