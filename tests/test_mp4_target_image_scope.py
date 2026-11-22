"""Shipping TargetImage's historical source-state and logical-RT lease."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_shipping_target_image_scope(tmp_path):
    source = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    start, end = "// BEGIN_MP4_TARGET_IMAGE_SCOPE", "// END_MP4_TARGET_IMAGE_SCOPE"
    assert source.splitlines().count(start) == source.splitlines().count(end) == 1
    (tmp_path / "target_image_scope.inc").write_text(source.split(start + "\n", 1)[1].split(end, 1)[0])
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "target-image"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp_path), str(ROOT / "tests/mp4_target_image_scope_harness.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})
