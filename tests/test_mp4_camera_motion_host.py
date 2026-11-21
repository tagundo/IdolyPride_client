"""Execute the production MotionData host, not a second copy of its protocol."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_temporary_motion_history_lease_and_failure_cleanup(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    begin = source.index('// BEGIN_MP4_CAMERA_MOTION_HOST')
    end = source.index('// END_MP4_CAMERA_MOTION_HOST', begin)
    (tmp_path / 'camera_motion_host.inc').write_text(source[begin:end])
    binary = tmp_path / 'camera-motion-host'
    subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT), '-I', str(tmp_path),
                    str(ROOT / 'tests/mp4_camera_motion_host_harness.cpp'),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
