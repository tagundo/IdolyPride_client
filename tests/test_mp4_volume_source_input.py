"""Shipping Source Volume snapshots with actual bounded metadata/GC fixtures.

Managed heap, original update and cache constructors are modeled boundaries;
these cases do not claim device rendering, GPU completion, or MP4 success.
"""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def section(text, start, end):
    at = text.index(start)
    return text[at:text.index(end, at)]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    cc = shutil.which("c++")
    if not cc:
        pytest.skip("C++ host compiler required")
    header = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    scope = section(header, "// BEGIN_MP4_SOURCE_VOLUME_INPUT", "// END_MP4_SOURCE_VOLUME_INPUT")
    scope = scope.replace("#pragma once", "")
    lazy = section(bridge, "// Pointer-only global owner: expanded Source snapshots", "Mp4LazySourceVolumeScope mp4_source_volume_scope;")
    # Typed malloc failure is an explicit fixture. Production uses ::malloc.
    lazy = lazy.replace("::malloc(sizeof(mp4vs::Scope))", "bank_allocate(sizeof(mp4vs::Scope))")
    result = {}
    folder = tmp_path_factory.mktemp("source-volume")
    for kind in ("input", "lazy"):
        fixture = (ROOT / f"tests/fixtures/mp4_volume_source_{kind}.cpp.inc").read_text()
        actual = fixture.replace("// SHIPPING_SOURCE_VOLUME_SCOPE", scope)
        actual = actual.replace("// SHIPPING_SOURCE_VOLUME_LAZY", lazy)
        source, binary = folder / f"{kind}.cpp", folder / kind
        source.write_text(actual)
        compiled = subprocess.run([cc, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], capture_output=True, text=True, timeout=90)
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        result[kind] = binary
    return result


@pytest.mark.parametrize("kind,case", [("input", n) for n in range(31)] + [("lazy", n) for n in range(33)])
def test_shipping_source_volume_snapshot(binaries, kind, case):
    run = subprocess.run([str(binaries[kind]), str(case)], capture_output=True, text=True, timeout=40, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"})
    assert run.returncode == 0, run.stdout + run.stderr
