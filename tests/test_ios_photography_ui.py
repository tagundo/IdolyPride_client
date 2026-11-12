"""Pure-host lifecycle test; not a Mac/Unity execution test."""
from pathlib import Path
import shutil
import subprocess
import pytest

def test_preview_default_hidden_once_per_model_and_user_show_survives(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source = Path(__file__).resolve().parents[1] / "client-presentation/ios/tests/photography_ui_test.cpp"
    output = tmp_path / "photography_ui_test"
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",str(source),"-o",str(output)],
                   check=True,capture_output=True,timeout=20)
    subprocess.run([str(output)],check=True,capture_output=True,timeout=5)
