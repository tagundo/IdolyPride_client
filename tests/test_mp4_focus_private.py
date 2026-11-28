"""Exercise the shipping Focus reference/factory leases, including handoff."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("marker", "name"), [
    ("MP4_FOCUS_EXTRA_STATE", "extra-state-lease"),
    ("MP4_FOCUS_FACTORY_LEDGER", "factory-ledger"),
])
def test_shipping_focus_private_lease(tmp_path, marker, name):
    source = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    start, end = "// BEGIN_" + marker, "// END_" + marker
    assert source.splitlines().count(start) == source.splitlines().count(end) == 1
    (tmp_path / ("focus-" + name + ".inc")).write_text(source.split(start + "\n", 1)[1].split(end, 1)[0])
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "focus-lease"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp_path), str(ROOT / ("tests/mp4_focus_" + name.replace("-", "_") + "_harness.cpp")), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
