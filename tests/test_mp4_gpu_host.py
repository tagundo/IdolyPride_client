"""Execute the shipping GPU service/ticket adapter with explicit Ledger fixtures.

This checks real host admission, context/epoch mapping and retirement order.
Native driver completion belongs to the separate Ledger/original-source tests;
this fixture does not run a physical GPU or produce an MP4.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
GPU_CASES = ("complete_release", "unknown_queue_producer", "unverified_source",
             "wrong_command_class", "wrong_method_arity", "wrong_method_owner",
             "stale_epoch", "active_or_duplicate_draw", "gpu_wait",
             "retire_once_after_retry", "cleanup_without_old_source_lookup",
             "stale_final_fence", "submit_failure", "execute_did_not_return",
             "aligned_atomic_read", "wrong_thread", "foreign_source", "unknown_gpu_work")


@pytest.fixture(scope="module", params=("android", "ios"))
def gpu_host(tmp_path_factory, request):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    start = bridge.index("// BEGIN_MP4_GPU_FENCE_HOST")
    end = bridge.index("// END_MP4_GPU_FENCE_HOST", start)
    actual = bridge[start:end]
    fixture = (ROOT / "tests/mp4_gpu_host_harness.cpp").read_text()
    folder = tmp_path_factory.mktemp("gpu-host-" + request.param)
    source, binary = folder / "host.cpp", folder / "host"
    source.write_text(fixture.replace("// SHIPPING_GPU_FENCE_HOST", actual))
    command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
               "-Wno-misleading-indentation", "-fsanitize=address,undefined",
               "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    if request.param == "ios":
        command.append("-DIDOLY_DARWIN_BRIDGE")
    built = subprocess.run(command + [str(source), "-o", str(binary)],
                           capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", range(len(GPU_CASES)), ids=GPU_CASES)
def test_shipping_gpu_service_and_ticket_scope(gpu_host, case):
    result = subprocess.run([str(gpu_host), str(case)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
