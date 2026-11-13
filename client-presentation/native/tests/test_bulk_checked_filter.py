"""Keep original predicates and retry synchronization while omitting checked IDs."""
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent


def test_checked_filter_preserves_original_exceptions_and_lost_reply_retry(tmp_path):
    compiler = shutil.which("c++")
    assert compiler, "A C++17 compiler is required for native helper verification"
    binary = tmp_path / "bulk-checked-filter"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(HERE / "bulk_checked_filter_test.cpp"), "-o", str(binary)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)
