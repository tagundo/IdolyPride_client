"""Run shipping Camera ScriptOutput provider with explicit metadata/graph boundaries."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
CASES = '''brain_binding gameobject_binding gameobject_two_brains gameobject_wrong_brain foreign_binding null_binding
foreign_context foreign_director foreign_asset shot_fallback shot_null_resolved shot_wrong_camera shot_dead_camera
wrong_compiled_mixer missing_track duplicate_track unowned_shot unowned_mixer source_lost wrong_handle
missing_element duplicate_element foreign_runtime_element unknown_clip light_runtime userdata_ignored
mixer_userdata_wrong mismatched_runtime_mixer invalid_reference_metadata'''.split()

@pytest.fixture(scope='module', params=('android', 'ios'))
def camera_provider(tmp_path_factory, request):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    start = bridge.index('// Exact original source factory/callback pins;')
    end = bridge.index('// SHARED ONLY. Distinguish source mutation/restoration PLAN', start)
    actual = bridge[start:end]
    fixture = (ROOT / 'tests/fixtures/mp4_timeline_camera_producer_host.cpp.inc').read_text()
    folder = tmp_path_factory.mktemp('timeline-camera-' + request.param)
    src, binary = folder / 'test.cpp', folder / 'test'
    src.write_text(fixture.replace('// SHIPPING_TIMELINE_CAMERA_PINS_AND_HOST', actual))
    cmd = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    if request.param == 'ios':
        cmd += ['-DIDOLY_DARWIN_BRIDGE=1']
    built = subprocess.run(cmd + [str(src), '-o', str(binary)], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary

@pytest.mark.parametrize('mode', CASES)
def test_shipping_camera_script_producer(camera_provider, mode):
    run = subprocess.run([str(camera_provider), mode], capture_output=True, text=True, timeout=10,
                         env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                              'UBSAN_OPTIONS': 'halt_on_error=1'})
    assert run.returncode == 0, run.stdout + run.stderr
