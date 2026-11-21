"""Exercise shipping private Renderer construction/publication/fence lifecycle."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_shipping_private_renderer_host(tmp_path):
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    start, end = "// BEGIN_MP4_PRIVATE_RENDERER_HOST", "// END_MP4_PRIVATE_RENDERER_HOST"
    assert source.splitlines().count(start) == source.splitlines().count(end) == 1
    (tmp_path / "private_renderer_host.inc").write_text(source.split(start + "\n", 1)[1].split(end, 1)[0])
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "renderer-host"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(ROOT), "-I", str(tmp_path), str(ROOT / "tests/mp4_private_renderer_host_harness.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})
