"""Execute the production Volume lease with explicit host/GPU fixtures.

These tests establish reference ownership and failure recovery, not actual
Unity parameter cloning, a GPU fence, or selected-game rendering.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def volume_binary(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    begin = source.index("// BEGIN_MP4_PRIVATE_VOLUME")
    end = source.index("// END_MP4_PRIVATE_VOLUME", begin)
    directory = tmp_path_factory.mktemp("mp4-private-volume")
    (directory / "private_volume.inc").write_text(source[begin:end])
    binary = directory / "volume"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", str(directory), str(ROOT / "tests/mp4_private_volume_harness.cpp"),
                    "-o", str(binary)], check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize("scenario", [
    "ordinary", "create_failure", "root_failure", "ref_write_throw", "mode_write_throw",
    "update_throw", "clone_throw", "clone_failure", "source_change_update", "readonly_change",
    "nested_unowned", "source_handoff", "handoff_abandoned", "reference_superseded", "mode_superseded",
    "source_lost", "gpu_wait", "next_draw", "two_jobs",
])
def test_actual_volume_scope_transaction(volume_binary, scenario):
    subprocess.run([str(volume_binary), scenario], check=True, capture_output=True, text=True)
