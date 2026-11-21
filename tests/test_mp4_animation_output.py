"""Shipping persistent AnimationOutput immutable-input and all-output ledgers.

These ownership fixtures do not replace original ARM callback/writer receipts or
actual game/Animator validation. They extract the code that the bridge ships.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"
CASES = {
    "witness": "stable source thread weight port stream sort reference userdata target native_source native_graph native_output graph_version output_version source_version nan release racy_capture bad_capture".split(),
    "payload": "stable game unverified actor_type animator_type dead graph_slot graph_version handle type target mapped table userdata source source_graph native_target native_source nan port stream sorting registry table_mapping zero_weight port_minus_one".split(),
    "ledger": "idle idle_unknown notheld stable second_output third_actor add remove reorder duplicate source epoch thread release recapture target".split(),
}


def _marker(source, marker):
    start, end = "// BEGIN_" + marker, "// END_" + marker
    assert source.count(start) == source.count(end) == 1
    return source.split(start, 1)[1].split(end, 1)[0]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("animation_output")
    source = BRIDGE.read_text()
    payload = _marker(source, "MP4_ANIMATION_OUTPUT_PAYLOAD_HOST")
    witness = payload.split("// Concrete INPUT reader", 1)[0]
    ledger = _marker(source, "MP4_ANIMATION_OUTPUT_LEDGER_HOST").split("// All persistent Actor graphs", 1)[0]
    (tmp / "mp4-animation-output-payload.hpp.inc").write_text(payload)
    (tmp / "mp4-animation-output-witness.hpp.inc").write_text(witness)
    (tmp / "mp4-animation-output-ledger.hpp.inc").write_text(ledger)
    compiler = shutil.which("c++")
    assert compiler
    result = {}
    for kind in CASES:
        binary = tmp / kind
        build = subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp), str(ROOT / "tests" / f"mp4_animation_output_{kind}_harness.cpp"), "-o", str(binary)], capture_output=True, text=True)
        assert build.returncode == 0, build.stdout + build.stderr
        result[kind] = binary
    return result


@pytest.mark.parametrize("kind,case", [(kind, case) for kind, cases in CASES.items() for case in cases])
def test_shipping_animation_output_guards(binaries, kind, case):
    run = subprocess.run([str(binaries[kind]), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
