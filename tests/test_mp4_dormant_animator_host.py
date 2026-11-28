"""Exercise the shipping readonly native dormant-Animator predicate."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dormant_animator_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    host = bridge[bridge.index("// BEGIN_MP4_DORMANT_ANIMATOR_HOST"):bridge.index("// END_MP4_DORMANT_ANIMATOR_HOST")]
    fixtures = ROOT / "tests/fixtures"
    prefix = (fixtures / "mp4_dormant_animator_host_prefix.cpp.inc").read_text()
    driver = (fixtures / "mp4_dormant_animator_host_driver.cpp.inc").read_text()
    folder = tmp_path_factory.mktemp("dormant-animator")
    source, binary = folder / "test.cpp", folder / "test"
    source.write_text(prefix + host + driver)
    built = subprocess.run([
        compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(source), "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("kind", [
    "normal", "active_transition", "off_thread", "source_changed", "bad_pin", "controller", "avatar",
    "bound", "root_motion", "keep_state", "write_defaults", "graph", "mode", "culling", "native_swap",
    "bindings", "capacity", "invalid_storage", "job_group", "job_version",
])
def test_native_dormant_animator_measurement(dormant_animator_host, kind):
    run = subprocess.run([str(dormant_animator_host), kind], capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stdout + run.stderr
