"""Actual consumer helper with modeled Unity leaves; this is not a GPU run."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin = bridge.index("// BEGIN_MP4_SHADER_CONSUMER_HOST")
    end = bridge.index("// END_MP4_SHADER_CONSUMER_HOST", begin)
    source = (FIXTURES / "mp4_shader_consumer_host_prefix.cpp.inc").read_text()
    source += bridge[begin:end]
    source += (FIXTURES / "mp4_shader_consumer_host_driver.cpp.inc").read_text()
    directory = tmp_path_factory.mktemp("mp4-shader-consumer-host")
    path = directory / "host.cpp"
    path.write_text(source)
    binary = directory / "host"
    result = subprocess.run([
        shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-Wno-misleading-indentation", "-g", "-O1", "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
        "-I", str(ROOT / "client-presentation/native"), str(path), "-o", str(binary),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("case", [
    "normal", "downloaded", "builtin", "scene", "scene_changed", "scene_unknown", "scene_compute", "unknown", "disabled", "inactive", "unculled",
    "unknown_pass_shader", "null_material", "skybox", "unknown_skybox", "config", "queue", "unknown_queue",
    "vlb", "vlb_unknown", "role_changed", "shader_id_changed", "shader_native_changed", "material_shader_changed",
    "root_failure", "source_changed", "unheld", "owner_lost", "unknown_node", "builtin_changed", "source_program_changed",
])
def test_actual_renderer_shader_consumers(host, case):
    result = subprocess.run([str(host), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
