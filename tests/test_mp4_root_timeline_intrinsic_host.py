"""Shipping intrinsic ScriptOutput closure using explicit metadata/graph fixtures.

This checks exact cache/RuntimeElement/output composition and fail-closed family
routing; it does not execute original Unity code, render a frame, or encode MP4.
"""
from pathlib import Path
import os
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
CASES = '''basic actor runtime notification_empty weight active source_restore missing_delegate current_lost
restore_unclosed wrong_port cache_lost unknown_script actor_unclosed runtime_unclosed runtime_unknown
runtime_wrong_parent runtime_foreign_clip userdata_unclosed userdata_changes generation_change list_mutation
notification_nonempty notification_foreign_source weight_unclosed weight_foreign_output weight_foreign_motion
weight_unknown_callback active_foreign'''.split()

@pytest.fixture(scope='module', params=('android', 'ios'))
def intrinsic(tmp_path_factory, request):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    text = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    start = text.index('// BEGIN_MP4_ROOT_TIMELINE_PRODUCER_HOST')
    middle = text.index('enum class Mp4TimelineProofPhase', start)
    end = text.index('// Exact original source factory/callback pins;', middle)
    pins = '#define mp4_timeline_pins generated_timeline_pins\n' + text[start:middle]
    pins += '\n#undef mp4_timeline_pins\nMp4TimelinePins mp4_timeline_pins=generated_timeline_pins;\n'
    fixture = (ROOT / 'tests/fixtures/mp4_root_timeline_intrinsic_host.cpp.inc').read_text()
    source = fixture.replace('// SHIPPING_TIMELINE_INTRINSIC_PINS', pins).replace('// SHIPPING_TIMELINE_INTRINSIC_HOST', text[middle:end])
    folder = tmp_path_factory.mktemp('timeline-intrinsic-' + request.param)
    src, binary = folder / 'test.cpp', folder / 'test'
    src.write_text(source)
    cmd = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    if request.param == 'ios':
        cmd += ['-DIDOLY_DARWIN_BRIDGE=1']
    built = subprocess.run(cmd + [str(src), '-o', str(binary)], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary

@pytest.mark.parametrize('mode', CASES)
def test_shipping_root_timeline_intrinsics(intrinsic, mode):
    run = subprocess.run([str(intrinsic), mode], capture_output=True, text=True, timeout=10,
                         env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                              'UBSAN_OPTIONS': 'halt_on_error=1'})
    assert run.returncode == 0, run.stdout + run.stderr
