"""Exercise the shipping private Volume factory with explicit typed-query fixtures.

This executes the real bridge collector/partial-resource/fence/disposal code.
Managed constructors, runtime invocation and Curve pool are named fixtures;
it does not claim Unity rendering, native textures or device validation.
"""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODES = (
    "baseline", "reuse", "unknown_type", "duplicate_type", "unknown_callback",
    "constructor_throw", "reload_throw", "clear_exception", "foreign_generic_method",
    "root_failure", "foreign_frame", "fence_wait", "source_changed", "list_changed",
    "final_fence_wait", "disposal_rebind_fail", "orphaned_globals",
    "disposal_dictionary_replaced", "disposal_extra_component", "disposal_parameter_replaced",
)


@pytest.fixture(scope="module")
def factory_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("Host C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin = bridge.index("// BEGIN_MP4_VOLUME_FACTORY_HOST")
    end = bridge.index("// END_MP4_VOLUME_FACTORY_HOST", begin)
    actual = bridge[begin:end]
    fixture = (ROOT / "tests/fixtures/mp4_volume_factory_host.cpp.inc").read_text()
    assert fixture.count("// SHIPPING_VOLUME_FACTORY_HOST") == 1
    folder = tmp_path_factory.mktemp("volume-factory-host")
    source = folder / "factory.cpp"
    source.write_text(fixture.replace("// SHIPPING_VOLUME_FACTORY_HOST", actual))
    binary = folder / "factory"
    result = subprocess.run(
        [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
         "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", MODES)
def test_shipping_private_volume_factory_transaction(factory_host, mode):
    result = subprocess.run(
        [str(factory_host), mode], capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
