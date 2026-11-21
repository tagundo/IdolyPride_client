"""Actual shipping private-render factory helpers over explicit ownership fixtures.

Original metadata/native instruction proofs and live GPU tests are separate.
These sanitizer cases assert partial-constructor material ownership, exact static
rollback, native clone uniqueness and private-only GC write-barrier destinations.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "client-presentation/native/mp4_camera_owner.hpp"


@pytest.mark.parametrize("marker,harness,header,receipt", [
    ("MP4_PRIVATE_RENDER_CONSTRUCTION", "mp4_private_render_construction_harness.cpp", "mp4-private-render-construction.hpp.inc", "44 bounded private constructor scenarios passed"),
    ("MP4_PRIVATE_RENDERER_DATA", "mp4_private_renderer_data_harness.cpp", "mp4-private-renderer-data-lease.hpp.inc", "28 private renderer data provenance/clone cases passed"),
    ("MP4_PRIVATE_RENDERER_ROOT", "mp4_private_renderer_root_harness.cpp", "mp4-private-renderer-root-check.hpp.inc", "90 private renderer source-role ownership cases passed"),
])
def test_shipping_private_factory_ownership(tmp_path, marker, harness, header, receipt):
    source = HEADER.read_text()
    start, end = "// BEGIN_" + marker, "// END_" + marker
    assert source.count(start) == source.count(end) == 1
    actual = source.split(start, 1)[1].split(end, 1)[0]
    (tmp_path / header).write_text(actual)
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "factory"
    build = subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp_path), str(ROOT / "tests" / harness), "-o", str(binary)], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert receipt in run.stdout
