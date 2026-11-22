"""Actual shipping gate ownership and literal bootstrap split; engine calls modeled."""
from pathlib import Path
import ast
import os
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
LEASE_CASES = ['lease_fixed','lease_wrong_owner','lease_raw_release','lease_foreign_entry','lease_move','lease_same_epoch_new_serial','lease_serial_exhausted','lease_target_occupied','lease_unique_across_kinds','lease_animation_transfer','lease_animation_open','lease_animation_inflight','lease_animation_raw_release','world_adopt','world_adopt_measure_fail','world_adopt_source_loss','world_adopt_wrong_epoch','world_adopt_wrong_gate','world_adopt_not_held','world_adopt_source_lost_release','world_adopt_wrong_origin','world_detach_same_epoch_aba']
HOST_CASES = ['host_adopt','host_legacy','host_measure_refuses','host_partial_transfer','host_source_lost_cleanup','host_cleanup_wrong_thread','host_early_partial_acquire','host_detach_adopted','host_detach_configured_only','host_job_changed','host_dirty_retained','host_reacquire_same_epoch']


def _marker(bridge, name):
    first = bridge.index('// BEGIN_' + name)
    last = bridge.index('// END_' + name, first) + len('// END_' + name)
    return bridge[first:last]


@pytest.mark.parametrize('platform', ('android', 'ios'))
@pytest.mark.parametrize('family', ('lease', 'host', 'splits', 'scope'))
def test_shipping_source_bootstrap_gate(tmp_path, platform, family):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    name = {'lease':'mp4_source_gate_lease.cpp.inc', 'host':'mp4_source_gate_host.cpp.inc', 'splits':'mp4_source_bootstrap_splits.cpp.inc', 'scope':'mp4_source_bootstrap_scope.cpp.inc'}[family]
    fixture = (ROOT / 'tests/fixtures' / name).read_text()
    if family == 'host':
        fixture = fixture.replace('// SOURCE_GATE_ADOPTION_HOST', _marker(bridge, 'MP4_SOURCE_GATE_ADOPTION_HOST'))
    if family == 'splits':
        fixture = fixture.replace('// SOURCE_BOOTSTRAP_SPLITS_HOST', _marker(bridge, 'MP4_SOURCE_BOOTSTRAP_SPLITS_HOST'))
    if family == 'scope':
        fixture = fixture.replace('// SOURCE_BOOTSTRAP_SCOPE', _marker(bridge, 'MP4_SOURCE_BOOTSTRAP_SCOPE'))
    source, binary = tmp_path / 'test.cpp', tmp_path / 'test'
    source.write_text(fixture)
    command = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
               '-I', str(ROOT / 'client-presentation/native')]
    if platform == 'ios':
        command += ['-DIDOLY_DARWIN_BRIDGE=1']
    built = subprocess.run(command + [str(source), '-o', str(binary)], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    cases = HOST_CASES if family == 'host' else [None]
    if family == 'lease':
        module = ast.parse((ROOT / 'tests/test_mp4_world.py').read_text())
        legacy = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MODES' for t in n.targets))
        cases = LEASE_CASES + list(dict.fromkeys(legacy))
    for case in cases:
        result = subprocess.run([str(binary)] + ([case] if case else []), capture_output=True, text=True, timeout=30,
                                env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1', 'UBSAN_OPTIONS':'halt_on_error=1'})
        assert result.returncode == 0, str(case) + result.stdout + result.stderr
        if family == 'splits':
            assert '20 source bootstrap literal split cases passed' in result.stdout
        if family == 'scope':
            assert '47 source bootstrap latching/cleanup cases' in result.stdout
