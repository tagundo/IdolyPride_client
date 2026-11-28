"""Run the shipping lazy history-bank allocator with explicit allocator fixtures.

The large Host's default values and ABI are tested by its own collectors; this
checks allocation lifetime, OOM, bounds, source-thread denial and slot reuse.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ("defaults_and_reuse", "bounded_index", "wrong_thread", "oom_retry",
         "independent_slots", "reset_reuses_storage", "no_foreign_thread_lookup")


@pytest.fixture(scope="module")
def heap_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    start = bridge.index("// BEGIN_MP4_TEMPORAL_HEAP_HOST")
    end = bridge.index("// END_MP4_TEMPORAL_HEAP_HOST", start)
    fixture = (ROOT / "tests/mp4_temporal_heap_host_harness.cpp").read_text()
    folder = tmp_path_factory.mktemp("temporal-heap-host")
    source, binary = folder / "host.cpp", folder / "host"
    source.write_text(fixture.replace("// SHIPPING_TEMPORAL_HEAP_HOST", bridge[start:end]))
    result = subprocess.run([
        compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-Wno-misleading-indentation", "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(source), "-o", str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("case", range(len(CASES)), ids=CASES)
def test_shipping_temporal_heap_slot_lifetime(heap_host, case):
    result = subprocess.run([str(heap_host), str(case)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
