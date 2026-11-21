"""Exercise the native policy used by real UIKit lifecycle and worker callbacks."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("filename,expected", [
    ("mp4_lifecycle_test.c", "PASS MP4 lifecycle policy"),
    ("mp4_finalization_test.c", "PASS MP4 finalization policy"),
])
def test_mp4_lifecycle_preserves_explicit_pause_and_never_resumes_in_background(tmp_path, filename, expected):
    compiler = shutil.which("cc") or shutil.which("clang")
    if not compiler:
        pytest.skip("C compiler required")
    source = Path(__file__).resolve().parents[1] / "ios-unified/native/tests" / filename
    output = tmp_path / "mp4-lifecycle"
    subprocess.run([compiler, "-std=c11", "-pthread", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(source), "-o", str(output)], check=True, timeout=30)
    result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == expected
