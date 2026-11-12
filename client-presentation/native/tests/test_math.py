"""Compile and execute the display-geometry contract without Android or Unity."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_original_center_rays_full_parent_and_restore(tmp_path):
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    if compiler is None:
        pytest.skip("A host C++17 compiler is unavailable")
    executable = tmp_path / "presentation-math"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I" + str(root), str(root / "tests/math_test.cpp"), "-o", str(executable)],
                   check=True, timeout=30)
    subprocess.run([str(executable)], check=True, timeout=5)
