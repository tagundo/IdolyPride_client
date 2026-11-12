"""Pure native configuration semantics, without Unity or a device runtime."""
from pathlib import Path
import shutil
import subprocess
import pytest

def test_playback_defaults_revision_and_immutability(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source = Path(__file__).with_name("playback_config_test.cpp")
    output = tmp_path / "playback-config-test"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=5)
