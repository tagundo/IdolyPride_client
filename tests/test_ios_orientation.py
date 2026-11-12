"""Pure host ABI/forwarding tests; no Unity, iOS or Mac execution claim."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_original_task_forwarding_and_desktop_frame_readiness(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source = ROOT / "client-presentation/ios/tests/orientation_test.cpp"
    output = tmp_path / "orientation_test"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=5)
