"""Production Actor temporal/native and edge topology checkpoint guard scenarios.

Typed native boundary fixtures exercise the shipping header; they do not claim
actual Unity graph/GPU rendering or whole source closure.
"""
from pathlib import Path
import shutil
import subprocess


def test_actor_native_temporal_and_edge_checkpoint(tmp_path):
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which("g++")
    assert compiler
    binary = tmp_path / "temporal"
    command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(root / "client-presentation/native"), str(root / "tests/mp4_actor_temporal_harness.cpp"), "-o", str(binary)]
    build = subprocess.run(command, capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "42 temporal checkpoint scenarios passed" in run.stdout
