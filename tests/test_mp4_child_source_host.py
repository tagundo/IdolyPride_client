"""Concrete shipping Child/Birth/Journal joins with explicit service fixtures.

Raw-operation scopes and all helper classes/hosts come from shipping Bridge.
Source module recipes, metadata services and originals are typed unit fixtures;
this is not an original-engine, GPU, device or successful MP4 output claim.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"
FIXTURES = ROOT / "tests/fixtures"


def namespace(text, anchor, name):
    suffix = text.split(anchor, 1)[1]
    start = "namespace " + name + " {"
    end = "} // namespace " + name
    body = start + suffix.split(start, 1)[1].split(end, 1)[0] + end
    return "#pragma once\n" + body + "\n"


def marker(text, name):
    return text.split("// BEGIN_" + name + "\n", 1)[1].split("// END_" + name, 1)[0]


@pytest.fixture(scope="module")
def child_binaries(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    text = (NATIVE / "bridge.cpp").read_text()
    folder = tmp_path_factory.mktemp("shipping-child-source")
    headers = {
        "pending-journal.hpp": marker(text, "MP4_DIRECTOR_MAINTENANCE_CORE"),
        "birth-scope.hpp": namespace(text, "// Shared-only: real native allocation/registration", "mp4_director_birth"),
        "source-origin.hpp": namespace(text, "// Concrete original entry contract.", "mp4_director_birth"),
        "typed-host.hpp": namespace(text, "// Shared typed actual-entry adapters.", "mp4_director_birth"),
        "native-host.hpp": namespace(text, "// Shared-only typed native adapter.", "mp4_director_maintenance"),
        "child-scope.hpp": namespace(text, "// Shared-only. Logical child Director restoration", "mp4_child_source"),
        "original-call-host.hpp": namespace(text, "// Executes only the saved source-pinned typed original.", "mp4_child_source"),
        "execution-host.inc": marker(text, "MP4_CHILD_EXECUTION_HOST"),
        "lineage-host.inc": marker(text, "MP4_CHILD_LINEAGE_HOST"),
        "main-control-host.inc": marker(text, "MP4_MAIN_CONTROL_HOST"),
        "deferred-host.inc": marker(text, "MP4_CHILD_DEFERRED_SETTLEMENT_HOST"),
    }
    completed = marker(text, "MP4_CHILD_COMPLETED_FACTORY_HOST")
    headers["completed-graph-host.inc"] = "// Read-only exact returned-root proof" + completed.split("// Read-only exact returned-root proof", 1)[1].split("bool mp4_child_completed_factory_member(", 1)[0]
    rows = re.findall(r"(?:\[\[maybe_unused\]\] )?inline constexpr SourcePins (?:android|ios)_birth_pins=.*?;", text)
    assert len(rows) == 2
    headers["pins.inc"] = "#pragma once\nnamespace mp4_director_birth {\n" + "\n".join(rows) + "\n}\n"
    for name, source in headers.items():
        (folder / name).write_text("#pragma once\n" + source)
    for fixture in FIXTURES.glob("mp4_child_*_model.cpp.inc"):
        shutil.copyfile(fixture, folder / fixture.name)
    binaries = {}
    for kind, fixture in [("execution", "mp4_child_execution_model.cpp.inc"), ("lineage", "mp4_child_lineage_model.cpp.inc"), ("factory", "mp4_birth_factory_context_model.cpp.inc"), ("main", "mp4_main_control_model.cpp.inc"), ("deferred", "mp4_child_deferred_model.cpp.inc")]:
        source = (FIXTURES / fixture).read_text()
        if kind in ("execution", "main", "deferred"):
            raw = "struct Mp4RawOriginalOperation" + text.split("struct Mp4RawOriginalOperation", 1)[1].split("struct Mp4OriginalEvaluationScope", 1)[0]
            query = "[[maybe_unused]] bool mp4_director_actual_operation" + text.split("[[maybe_unused]] bool mp4_director_actual_operation", 1)[1].split("bool mp4_receipt_same", 1)[0]
            source = source.replace("// ACTUAL_RAW_SCOPE", raw).replace("// ACTUAL_RAW_QUERY", query)
        path, binary = folder / (kind + ".cpp"), folder / kind
        path.write_text(source)
        result = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-Wno-unused-function", "-Wno-unused-variable", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(folder), "-I", str(NATIVE), str(path), "-o", str(binary)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        binaries[kind] = binary
    return binaries


@pytest.mark.parametrize("kind,mode", [("execution", i) for i in range(22)] + [("lineage", i) for i in range(29)] + [("factory", i) for i in range(6)] + [("main", i) for i in (0, 1, 6, 7, 9, 22, 23, 24, 25)] + [("deferred", mode) for mode in "normal no_work reappend physical active_grant unreturned unfinished unclosed_output unowned_queue sourcechange throws budget".split()])
def test_actual_child_execution_lineage_and_factory_stack(child_binaries, kind, mode):
    result = subprocess.run([str(child_binaries[kind]), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
