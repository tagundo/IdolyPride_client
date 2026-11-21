"""Run the shipping Cine producer host over bounded ownership fixtures."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_shipping_cine_producer_host(tmp_path):
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    blocks = []
    for marker in ("MP4_CINE_VOLUME_HOST", "MP4_CINE_VOLUME_HOST_OPERATIONS"):
        start, end = "// BEGIN_" + marker, "// END_" + marker
        # The shorter marker is a prefix of OPERATIONS, so count exact lines.
        assert source.splitlines().count(start) == source.splitlines().count(end) == 1
        blocks.append(source.split(start + "\n", 1)[1].split(end, 1)[0])
    (tmp_path / "cine_volume_host.inc").write_text("\n".join(blocks))
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "cine-host"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(ROOT), "-I", str(tmp_path), str(ROOT / "tests/mp4_cine_volume_host_harness.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
