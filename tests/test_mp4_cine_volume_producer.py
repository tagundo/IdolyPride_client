"""Exercise the shipping selected Cine hidden-volume transaction."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_cine_producer_receipts_and_handoff(tmp_path):
    source = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    start, end = "// BEGIN_MP4_CINE_VOLUME_PRODUCER", "// END_MP4_CINE_VOLUME_PRODUCER"
    assert source.count(start) == source.count(end) == 1
    (tmp_path / "cine-volume-producer.inc").write_text(source.split(start, 1)[1].split(end, 1)[0])
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "cine-producer"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp_path), str(ROOT / "tests/mp4_cine_volume_producer_harness.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
