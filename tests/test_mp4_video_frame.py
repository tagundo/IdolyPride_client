"""Exact private clip-frame requests, async receipts and 120 Hz frame reuse."""
from pathlib import Path
import os
import shutil
import subprocess
ROOT = Path(__file__).resolve().parents[1]


def test_private_frame_schedule(tmp_path):
    source = (ROOT / 'client-presentation/native/mp4_camera_owner.hpp').read_text()
    start, end = '// BEGIN_MP4_VIDEO_FRAME', '// END_MP4_VIDEO_FRAME'
    assert source.splitlines().count(start) == source.splitlines().count(end) == 1
    (tmp_path / 'video_frame.inc').write_text(source.split(start + '\n', 1)[1].split(end, 1)[0])
    compiler = shutil.which('c++')
    assert compiler
    binary = tmp_path / 'video-frame'
    subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-I', str(tmp_path), '-I', str(ROOT),
                    str(ROOT / 'tests/mp4_video_frame_harness.cpp'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, 'UBSAN_OPTIONS':'halt_on_error=1'})
