"""Original UI groups, parent-space conversion, rollback and session defaults."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_panorama_ui_edges_and_user_visibility_choice(tmp_path):
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    if compiler is None:
        pytest.skip("A host C++17 compiler is unavailable")
    executable = tmp_path / "panorama-ui"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-I" + str(root), str(root / "tests/panorama_ui_test.cpp"), "-o", str(executable)],
                   check=True, timeout=30)
    subprocess.run([str(executable)], check=True, timeout=5)
