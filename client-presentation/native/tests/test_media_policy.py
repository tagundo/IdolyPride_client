"""Startup media wire policy without Unity or a device process."""
from pathlib import Path
import shutil
import subprocess
import pytest

def test_media_policy_defaults_immutability_and_strict_ios_wire(tmp_path):
    compiler=shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source=Path(__file__).with_name("media_policy_test.cpp")
    output=tmp_path/"media-policy"
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",str(source),"-o",str(output)],
                   check=True,capture_output=True,timeout=20)
    subprocess.run([str(output)],check=True,capture_output=True,timeout=5)
