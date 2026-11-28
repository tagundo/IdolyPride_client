"""Execute concrete shipping curve ownership against explicit native fixtures.

The host ABI/lifetime/failure cases are checked here. Actual unchanged ARM LUT
sampling/Volume dispatch and actual native Curve/GPU behavior are separate gates.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def curve_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin = source.index("// BEGIN_MP4_VOLUME_CURVE_HOST")
    end = source.index("// END_MP4_VOLUME_CURVE_HOST", begin)
    directory = tmp_path_factory.mktemp("volume-curve-host")
    (directory / "volume_curve_host.inc").write_text(source[begin:end])
    binary = directory / "curves"
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                             "-I", str(directory), str(ROOT / "tests/mp4_volume_curve_host_harness.cpp"),
                             "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "ordinary", "empty", "single", "loop", "refresh", "step_tangent",
    "domain_start", "domain_end", "nan_value", "nan_tangent", "ctor_throw", "set_throw",
    "source_change", "initial_root_failure", "fresh_root_failure", "native_root_failure",
])
def test_source_curve_stays_owned_and_private_payload_cleanup_is_complete(curve_host, scenario):
    result = subprocess.run([str(curve_host), scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
