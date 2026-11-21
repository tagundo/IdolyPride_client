from pathlib import Path
import json
import shutil
import subprocess

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason='SDK-free C cross contracts require the Linux host toolchain and resource limits')

from idoly_local.presentation import CAPABILITIES, METRICS, PresentationState, validate_settings


@pytest.fixture(scope="module")
def cross_contract(tmp_path_factory):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required for the SDK-free contract tests")
    source = Path(__file__).resolve().parents[1] / "cross/tests/presentation_contract_test.c"
    output = tmp_path_factory.mktemp("cross-presentation") / "contract-test"
    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", str(source), "-o", str(output)],
                   check=True, timeout=30)
    return output


def test_sdk_free_preferences_ack_and_bounded_polling(cross_contract):
    result = subprocess.run([str(cross_contract)], check=True, text=True, capture_output=True, timeout=10)
    assert "SDK-free presentation/ACK/poll checks" in result.stdout


def test_c_generated_preferences_match_actual_server_ack_epoch(cross_contract, tmp_path):
    result = subprocess.run([str(cross_contract), "--json"], check=True, text=True, capture_output=True, timeout=10)
    preferences = [validate_settings(json.loads(line)) for line in result.stdout.splitlines()]
    assert [item["revision"] for item in preferences] == [100, 101, 102]
    assert preferences[0]["render_scale"] == 0.625
    assert preferences[0]["max_buffer_pixel"] == 2000
    path = tmp_path / "client-presentation.json"
    path.write_text(json.dumps(preferences[1]))
    state = PresentationState(path)
    assert state.settings() == preferences[1]
    report = {"schema": 1, "bridge_version": 1, "revision": 101, "status": "applied",
              "capabilities": {name: True for name in CAPABILITIES}, "metrics": {name: 0 for name in METRICS}}
    assert state.receive(json.dumps(report).encode()) == {"accepted": True}
    assert state.status()["client"]["status"] == "applied"
    # A later setting edit must wait for the game's actual new-revision ACK.
    path.write_text(json.dumps(preferences[2]))
    assert state.status()["client"]["status"] == "waiting"
    report["status"] = "unsupported"
    state.receive(json.dumps(report).encode())
    assert state.status()["client"]["status"] == "unsupported"
