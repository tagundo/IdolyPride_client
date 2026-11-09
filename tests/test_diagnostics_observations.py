"""Silent awaits need observations without manufacturing success or exceptions."""
import json

import pytest

from idoly_local.diagnostics import ClientDiagnostics, _PHASES


def send(model, *events):
    return model.receive(json.dumps({"schema": 1, "source": "android-game", "events": events}).encode())


def status(code):
    return {"kind": "status", "code": code}


def network(**values):
    return {"kind": "network", "rx_bytes": 123456, "tx_bytes": 2345, "elapsed_ms": 5000, **values}


def test_phase_is_observation_and_network_does_not_replace_it_or_log_numbers():
    logs = []
    model = ClientDiagnostics(logs.append)
    send(model, status("home_enter"), status("actor_motion_wait"))
    before = model.status()
    response = send(model, network())
    after = model.status()
    assert after["phase"] == {"code": "actor_motion_wait", "summary": "캐릭터 모션 로딩 단계"}
    assert after["summary"] == before["summary"] == response["summary"]
    assert after["network"] == {"rx_bytes": 123456, "tx_bytes": 2345, "elapsed_ms": 5000}
    assert len(logs) == 2
    assert not after["latest_exception"]
    assert after["received_events"] == 3
    assert after["events"][-1] == network()


@pytest.mark.parametrize("code", sorted(_PHASES))
def test_every_allowed_phase_can_be_exported_without_args_or_pointers(code):
    model = ClientDiagnostics()
    send(model, status(code))
    assert model.status()["phase"]["code"] == code
    assert model.status()["events"] == [status(code)]


@pytest.mark.parametrize("field", ["rx_bytes", "tx_bytes", "elapsed_ms"])
@pytest.mark.parametrize("bad", [-1, 2**63, True, 1.5, "123", None])
def test_bad_counters_reject_entire_batch_without_logging_or_mutation(field, bad):
    logs = []
    model = ClientDiagnostics(logs.append)
    original = model.status()
    with pytest.raises(ValueError):
        send(model, status("home_enter"), network(**{field: bad}))
    assert model.status() == original
    assert not logs


def test_network_cannot_carry_free_form_data_and_unavailable_can_recover():
    model = ClientDiagnostics()
    with pytest.raises(ValueError):
        send(model, network(url="https://example.invalid/private"))
    send(model, status("actor_cache_build"))
    observed = model.status()["summary"]
    send(model, status("network_unavailable"))
    assert model.status()["network_unavailable"]
    assert model.status()["summary"] == observed
    send(model, network())
    assert not model.status()["network_unavailable"]


def test_new_collector_clears_stale_current_observations_but_preserves_history():
    model = ClientDiagnostics()
    send(model, status("probe_ready"), status("home_enter"), network(),
         {"kind": "exception", "type": "NullReferenceException", "frames": ["Solis.Old.Frame"]})
    send(model, status("collector_started"))
    latest = model.status()
    assert latest["latest_exception"] is None
    assert latest["phase"] is None
    assert latest["network"] is None
    assert latest["native_probe_status"] is None
    assert len(latest["events"]) == 5
    assert latest["summary"] == "게임 진단 수집 시작"


@pytest.mark.parametrize("code", ["probe_unavailable", "probe_init_failed", "probe_selftest_failed",
                                  "probe_profile_mismatch", "probe_install_failed"])
def test_native_probe_failure_remains_explicit_without_a_fake_exception(code):
    model = ClientDiagnostics()
    send(model, status(code))
    assert model.status()["native_probe_status"] == code
    assert model.status()["phase"] is None
    assert not model.status()["latest_exception"]
