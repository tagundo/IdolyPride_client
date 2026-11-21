"""Typed managed mixer history/factory/lifetime fixtures for the shipping header."""
from pathlib import Path
import shutil
import subprocess


def test_owned_managed_mixer_history_lifetimes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which("g++")
    assert compiler
    binary = tmp_path / "managed-mixers"
    build = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-O1", "-I", str(root / "client-presentation/native"), str(root / "tests/mp4_actor_managed_mixer_harness.cpp"), "-o", str(binary)], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "20 managed mixer source-history scenarios passed" in run.stdout
