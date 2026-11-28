"""Actual shipping per-operation provenance, independent of worker readiness.

All provenance bodies, including the selected deferred-duty getter, are extracted
from Bridge. Typed services/records are explicit host fixtures. This proves no
engine execution, physical worker fence, GPU retirement, or successful MP4.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def marker(text, name):
    return text.split("// BEGIN_" + name + "\n", 1)[1].split(
        "// END_" + name, 1
    )[0]


@pytest.fixture(scope="module")
def origin_binaries(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("c++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    text = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    prefix = "#include <cstdlib>\n" + (
        FIXTURES / "mp4_child_pending_origin_prefix.cpp.inc"
    ).read_text()
    operation = marker(text, "MP4_CHILD_PENDING_OPERATION_ORIGIN")
    deferred = marker(text, "MP4_CHILD_DEFERRED_SETTLEMENT_HOST")
    deferred = deferred.split("mp4child::Result mp4_child_deferred_admission", 1)[0]
    deferred += "\n" + marker(text, "MP4_CHILD_PENDING_DEFERRED_ORIGIN")
    originals = (
        "\nvoid*mp4_animation_original[8]={(void*)0x800,(void*)0x804,"
        "(void*)0x808,(void*)0x80c,(void*)0x810,(void*)0x814,"
        "(void*)0x818,(void*)0x81c};\n"
    )
    folder = tmp_path_factory.mktemp("shipping-pending-operation-origin")
    binaries = {}
    for kind, body in (("operation", operation), ("deferred", originals + deferred)):
        path, binary = folder / (kind + ".cpp"), folder / kind
        path.write_text(
            prefix
            + "\n"
            + body
            + "\n"
            + (FIXTURES / ("mp4_child_pending_origin_" + kind + ".cpp.inc")).read_text()
        )
        result = subprocess.run(
            [
                compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra",
                "-Werror", "-Wno-misleading-indentation", "-Wno-unused-function",
                "-Wno-unused-variable",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-fno-pie", "-no-pie", str(path), "-o", str(binary),
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        binaries[kind] = binary
    return binaries


@pytest.mark.parametrize("case", range(1, 45))
def test_actual_prepared_entered_and_native_phase_origins(origin_binaries, case):
    result = subprocess.run(
        [str(origin_binaries["operation"]), str(case)],
        capture_output=True, text=True, timeout=5,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1"},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", range(1, 13))
def test_actual_selected_deferred_origin(origin_binaries, case):
    result = subprocess.run(
        [str(origin_binaries["deferred"]), str(case)],
        capture_output=True, text=True, timeout=5,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1"},
    )
    assert result.returncode == 0, result.stderr
