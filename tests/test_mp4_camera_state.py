"""Bounded selected-camera state restores real payloads and native audio state."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_camera_state_scope_remaps_and_verifies_without_unowned_writes(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    binary = tmp_path / 'camera-state'
    subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT), str(ROOT / 'tests/mp4_camera_state_harness.cpp'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
