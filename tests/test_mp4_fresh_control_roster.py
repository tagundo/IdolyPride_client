"""Run the shipping fresh Control roster with explicit public-API VM leaves.

These are source traversal/clock-role/lifetime checks, not original-game,
GPU, native engine or encoded-MP4 evidence.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def roster_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin = bridge.index("// BEGIN_MP4_FRESH_CONTROL_ROSTER")
    end = bridge.index("// END_MP4_FRESH_CONTROL_ROSTER", begin)
    actual = bridge[begin:end]
    fixture = (ROOT / "tests/fixtures/mp4_fresh_control_roster.cpp.inc").read_text()
    directory = tmp_path_factory.mktemp("fresh-control-roster")
    source, binary = directory / "roster.cpp", directory / "roster"
    source.write_text(fixture.replace("// ACTUAL_FRESH_CONTROL_ROSTER", actual))
    built = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g",
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie",
         str(source), "-o", str(binary)], capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "basic", "hierarchy", "valid_null", "same_asset", "self_guard", "prefab",
    "manual_orphan", "cycle", "born", "changed_components", "changed_reference",
    "changed_clip", "dsp", "unreturned_conversion", "retired_reborn",
    "foreign_root", "foreign_asset", "foreign_owner",
    "path_basic", "path_conversion", "path_cache", "path_target", "path_output",
    "path_registry", "path_roots", "path_graph",
])
def test_actual_reachable_control_roles_and_current_custody(roster_binary, scenario):
    ran = subprocess.run([str(roster_binary), scenario], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
