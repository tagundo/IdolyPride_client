from pathlib import Path
import shutil
import subprocess

import pytest


def test_playcover_handoff_policy_and_stale_candidate_rejection(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "launch-policy"
    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                    str(root / "cross/tests/playcover_launch_test.c"), "-o", str(output)], check=True, timeout=30)
    result = subprocess.run([str(output)], check=True, text=True, capture_output=True, timeout=10)
    assert "16 PlayCover launch routing checks" in result.stdout
