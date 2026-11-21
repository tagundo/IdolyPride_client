"""Run the actual Timeline cache/port collector with explicit managed queries.

Both profile branches use the production code. Managed dictionary calls and
graph getters are fixtures; original-code/ARM proofs remain separate evidence.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = ("compiled_track_port", "unverified_call", "multiple_roots", "cache_miss",
         "changed_handle_version", "foreign_graph", "wrong_dictionary_class",
         "wrong_method_arity", "wrong_method_owner", "wrong_method_entry",
         "dictionary_mutated", "cache_reference_replaced", "source_replaced",
         "non_passthrough", "native_slot_version_changed", "exception_releases_roots",
         "port_outside_input_count", "invalid_handle")


@pytest.fixture(scope="module", params=("android", "ios"))
def track_host(tmp_path_factory, request):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    start = bridge.index("// Read-only parent Timeline proof.")
    end = bridge.index("// END_MP4_AUDIO_PROGRAM_HOST", start)
    actual = bridge[start:end]
    fixture = (ROOT / "tests/mp4_root_track_cache_harness.cpp").read_text()
    folder = tmp_path_factory.mktemp("root-track-" + request.param)
    source, binary = folder / "host.cpp", folder / "host"
    source.write_text(fixture.replace("// SHIPPING_ROOT_TRACK_CACHE_HOST", actual))
    command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
               "-Wno-misleading-indentation", "-fsanitize=address,undefined",
               "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    if request.param == "ios":
        command.append("-DIDOLY_DARWIN_BRIDGE")
    built = subprocess.run(command + [str(source), "-o", str(binary)],
                           capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", range(len(CASES)), ids=CASES)
def test_shipping_root_track_cache_and_source_port(track_host, case):
    result = subprocess.run([str(track_host), str(case)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
