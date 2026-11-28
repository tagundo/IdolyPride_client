"""Compile shipping capture producer/reader/gate code against finite hosts.

The C++ scenarios exercise ownership and ABI joins, not actual game/GPU export.
No helper implementation is loaded from the shared audit workspace.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"
FIXTURES = ROOT / "tests/fixtures"


def section(name):
    source = BRIDGE.read_text()
    first, last = "// BEGIN_MP4_" + name, "// END_MP4_" + name
    assert source.count(first) == source.count(last) == 1
    return source.split(first, 1)[1].split(last, 1)[0]


def fill(source):
    for name in ("GATE", "JOURNAL", "PINS", "HOST", "HOOKS"):
        source = source.replace("// @QUEUE_" + name + "@", section("CAPTURE_QUEUE_" + name))
    for name in ("PINS", "HOST"):
        source = source.replace("// @ALIAS_" + name + "@", section("CAPTURE_ALIAS_" + name))
    assert "// @QUEUE_" not in source and "// @ALIAS_" not in source
    assert "/workspace/shared" not in source
    return source


def compile_host(directory, name, source, *, fixture_warnings=False):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    code, binary = directory / (name + ".cpp"), directory / name
    code.write_text(fill(source))
    args = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-pthread"]
    if fixture_warnings:
        args += ["-Wno-misleading-indentation", "-Wno-unused-variable"]
    result = subprocess.run([*args, str(code), "-o", str(binary)], text=True,
                            capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("name,count,label", [
    ("journal", 54, "queue custody"),
    ("host", 39, "concrete queue host"),
    ("gate", 11, "CPU gate"),
])
def test_shipping_queue_custody_and_interleavings(tmp_path, name, count, label):
    source = (FIXTURES / ("mp4_capture_queue_" + name + ".cpp.inc")).read_text()
    binary = compile_host(tmp_path, name, source)
    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{count} {label} cases passed"


def test_shipping_frontends_preserve_typed_values_and_scope_lifetime(tmp_path):
    fixture = (FIXTURES / "mp4_capture_queue_frontends.cpp.inc").read_text()
    binary = compile_host(tmp_path, "frontends", fixture)
    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "8 actual frontend cases passed"
