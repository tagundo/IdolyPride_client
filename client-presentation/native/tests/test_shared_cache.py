"""Actual native coordinator with fake IL2CPP handles and real private-file IO."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_native_wire_stamps_non_evicting_capacity_and_epoch_gc_lifecycle(tmp_path):
    compiler=shutil.which("c++")
    if compiler is None:
        pytest.skip("Host C++ compiler unavailable")
    source=Path(__file__).with_name("shared_cache_test.cpp")
    binary=tmp_path/"shared-cache-native"
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-pthread",str(source),"-o",str(binary)],
                   check=True,capture_output=True,timeout=20)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)
