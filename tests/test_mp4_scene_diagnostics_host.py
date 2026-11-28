"""Run the actual read-only per-family diagnostic dispatcher with named probes.

The family admission bodies and source query are explicit fixtures. This proves
error collection and temporary admission-ledger lifetime, not those families'
own state safety or actual Unity/GPU admission.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_controller_diagnostics import runtime_function
from test_mp4_controller_lookup import _function

ROOT = Path(__file__).resolve().parents[1]
MODES = ("all_ok", "actor_failed", "camera_wait", "stage_failed", "world_failed",
         "actor_throw", "camera_throw", "stage_throw", "world_throw",
         "unverified", "all_unverified", "source_changed", "empty_error", "failed_none")


@pytest.fixture(scope="module")
def diagnostic_host(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    runtime = (ROOT / "client-presentation/native/mp4_runtime.hpp").read_text()
    structs = "\n".join(_function(runtime, name) + ";" for name in (
        "struct NativeSceneDiagnosticPart", "struct NativeSceneDiagnostics"))
    actual = runtime_function(bridge, "void mp4_scene_diagnostic_parts(")
    fixture = (ROOT / "tests/mp4_scene_diagnostics_host_harness.cpp").read_text()
    folder = tmp_path_factory.mktemp("scene-diagnostic-host")
    source, binary = folder / "diagnostic.cpp", folder / "diagnostic"
    source.write_text(fixture.replace("// DIAGNOSTIC_STRUCTS", structs).replace(
        "// SHIPPING_DIAGNOSTIC_DISPATCH", actual))
    built = subprocess.run([
        compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        str(source), "-o", str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("mode", MODES)
def test_shipping_diagnostic_admission_dispatch(diagnostic_host, mode):
    result = subprocess.run([str(diagnostic_host), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
