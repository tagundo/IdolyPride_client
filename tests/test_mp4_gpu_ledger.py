"""Exercise actual shipping fence ledger with explicit native/GPU fixtures.

The 49 scenarios cover Vulkan/Metal baseline plus conjunctive GL observer,
context/generation/serial checks, quarantine and retirement. No physical GPU.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("platform", ("android", "ios"))
def test_shipping_gpu_ledger_gl_observation_and_lifetime(tmp_path, platform):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    observer_start = bridge.index("namespace mp4_gl_completion {")
    observer_end = bridge.index("} // namespace mp4_gl_completion", observer_start)
    observer_end += len("} // namespace mp4_gl_completion")
    core_start = bridge.index("// BEGIN_MP4_GPU_FENCE_CORE")
    core_end = bridge.index("// END_MP4_GPU_FENCE_CORE", core_start)
    fixture = (ROOT / "tests/mp4_gpu_ledger_harness.cpp").read_text()
    source, binary = tmp_path / "ledger.cpp", tmp_path / "ledger"
    source.write_text(fixture.replace("// SHIPPING_GL_OBSERVER", bridge[observer_start:observer_end])
                      .replace("// SHIPPING_GPU_FENCE_CORE", bridge[core_start:core_end]))
    command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
               "-Wno-misleading-indentation", "-fsanitize=address,undefined",
               "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    if platform == "ios":
        command.append("-DIDOLY_DARWIN_BRIDGE")
    built = subprocess.run(command + [str(source), "-o", str(binary)], capture_output=True,
                           text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "49" in result.stdout
