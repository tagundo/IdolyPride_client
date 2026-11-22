"""Run the shipping selected-image host's actual fields and retirement calls.

Synthetic managed objects/fences exercise the native ownership boundary;
these cases do not attest a Unity frame, GPU output or physical device.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def paused_image_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    header = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    scope = header[header.index("// BEGIN_MP4_PAUSED_FRAME_SCOPE"):header.index("// END_MP4_PAUSED_FRAME_SCOPE")]
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    host = bridge[bridge.index("// BEGIN_MP4_PAUSED_IMAGE_HOST"):bridge.index("// END_MP4_PAUSED_IMAGE_HOST")]
    fixtures = ROOT / "tests/fixtures"
    prefix = (fixtures / "mp4_paused_image_host_prefix.cpp.inc").read_text().replace("// __FRAME_SCOPE__", scope)
    driver = (fixtures / "mp4_paused_image_host_driver.cpp.inc").read_text()
    folder = tmp_path_factory.mktemp("paused-image-host")
    source, binary = folder / "test.cpp", folder / "test"
    source.write_text(prefix + host + driver)
    built = subprocess.run([
        compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(source), "-o", str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("mode", [
    "normal", "empty_capture", "missing_provider", "capture_root_failure", "not_held", "queue_busy",
    "not_configured", "foreign_epoch", "foreign_slot", "foreign_replacement", "handoff_slot",
    "preserve_handoff", "unowned", "capture_adoption_root_failure", "alias_wait", "native_swap",
    "deferred_destroy", "throw_destroy", "observed_private_handoff", "partial_production",
])
def test_shipping_paused_image_fields_and_retirement(paused_image_host, mode):
    run = subprocess.run([str(paused_image_host), mode], capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stdout + run.stderr
