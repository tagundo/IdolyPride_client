"""Actual content digest/lineage state; modeled Unity leaves are not a GPU run."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def compile_fixture(directory, source):
    path = directory / "test.cpp"
    path.write_text(source)
    binary = directory / "test"
    result = subprocess.run([
        shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g", "-O1",
        "-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-I", str(ROOT / "client-presentation/native"),
        str(path), "-o", str(binary),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.fixture(scope="module")
def state(tmp_path_factory):
    source = '#include "mp4_actor_state.hpp"\n#include <cassert>\n#include <map>\n#include <string>\n'
    source += (FIXTURES / "mp4_shader_lineage_state.cpp.inc").read_text()
    return compile_fixture(tmp_path_factory.mktemp("mp4-shader-lineage"), source)


@pytest.mark.parametrize("case", [
    "sha_empty", "sha_abc", "sha_long", "sha_chunked", "unknown_input", "input_changed", "no_actual_request",
    "wrong_request_type", "wrong_bundle_type", "wrong_count", "duplicate_shader", "wrong_shader_type",
    "bundle_replaced_during", "request_replaced", "root_failure", "offthread", "sync", "async",
    "shader_native_replaced", "shader_id_replaced", "shader_destroyed", "bundle_unload_keep_objects", "poison",
    "repeat", "offthread_admission", "no_array_root", "array_throw", "reentrant",
])
def test_content_provenance_registry(state, case):
    result = subprocess.run([str(state), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def block(source, name):
    begin = f"// BEGIN_{name}"
    end = f"// END_{name}"
    return source[source.index(begin):source.index(end)]


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    driver = (FIXTURES / "mp4_shader_lineage_host_driver.cpp.inc").read_text()
    known, main = driver.split("int main(", 1)
    source = '#include "mp4_actor_state.hpp"\n'
    source += (FIXTURES / "mp4_shader_lineage_host_prefix.cpp.inc").read_text() + known
    source += block(bridge, "MP4_SHADER_LINEAGE_HOST") + block(bridge, "MP4_SHADER_OBSERVER_ROOTS") + block(bridge, "MP4_SHADER_LINEAGE_HOOKS")
    source += "int main(" + main
    return compile_fixture(tmp_path_factory.mktemp("mp4-shader-lineage-host"), source)


@pytest.mark.parametrize("case", [
    "sync", "async", "file", "bootstrap_main", "bootstrap_bad_prefix", "offthread", "source_prefix", "unknown_bytes", "changed_memory", "changed_file",
    "file_changed_before_result", "observer_throw", "original_throw",
])
def test_actual_typed_hook_and_file_hash_host(host, case):
    result = subprocess.run([str(host), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
