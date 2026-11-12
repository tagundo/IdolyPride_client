import json

import pytest

from idoly_local.wardrobe_diagnostics import WardrobeDiagnostics, decode

IDLE = {"schema": 1, "phase": "idle", "show_failures": 0, "released_waits": 0,
        "sequence": 0, "sample_age_ms": None}


def raw(row):
    return json.dumps(row).encode()


def test_transitions_are_read_only_snapshots_and_heartbeat_never_relogs():
    clock = [10.0]
    logs = []
    state = WardrobeDiagnostics(logs.append, clock=lambda: clock[0])
    assert state.status() == {"client": None, "age_seconds": None}
    state.receive(raw(IDLE))
    assert logs == []
    row = IDLE | {"phase": "show_failed", "sequence": 2, "show_failures": 1, "sample_age_ms": 20}
    state.receive(raw(row))
    assert len(logs) == 1
    state.receive(raw(row | {"sample_age_ms": 2020}))
    assert len(logs) == 1
    clock[0] += 3
    snapshot = state.status()
    assert snapshot["age_seconds"] == 3 and snapshot["client"]["sample_age_ms"] == 2020
    snapshot["client"]["phase"] = "tampered"
    assert state.status()["client"]["phase"] == "show_failed"
    state.receive(raw(IDLE | {"phase": "hide_wait_released", "sequence": 3,
        "show_failures": 1, "released_waits": 1, "sample_age_ms": 0}))
    assert len(logs) == 2
    # A new game process can publish its initial state without an old lease.
    state.receive(raw(IDLE))
    assert state.status()["client"] == IDLE


@pytest.mark.parametrize("changes", [{"schema": True}, {"schema": 2}, {"phase": []}, {"phase": "unknown"},
    {"show_failures": True}, {"sequence": -1}, {"released_waits": 2**63}, {"sample_age_ms": 0},
    {"extra": "player-information"}, {"phase": "show_begin", "sequence": 0},
    {"phase": "show_begin", "sequence": 1, "sample_age_ms": None},
    {"phase": "show_begin", "sequence": 1, "sample_age_ms": False},
    {"phase": "show_begin", "sequence": 1, "sample_age_ms": float("nan")},
    {"phase": "show_failed", "sequence": 1, "sample_age_ms": 0},
    {"phase": "hide_wait_released", "sequence": 1, "sample_age_ms": 0}])
def test_invalid_reports_preserve_previous_value(changes):
    state = WardrobeDiagnostics()
    state.receive(raw(IDLE))
    with pytest.raises(ValueError):
        state.receive(raw(IDLE | changes))
    assert state.status()["client"] == IDLE


def test_duplicate_unknown_invalid_utf8_and_large_bodies_are_rejected():
    for value in (b'{"schema":1,"schema":1}', b'\xff', b'[]', b'0', b' '*2049):
        with pytest.raises(ValueError):
            decode(value)


def test_optional_log_callback_cannot_interrupt_valid_observation():
    def bad_log(_):
        raise RuntimeError("UI callback failed")
    state = WardrobeDiagnostics(bad_log)
    row = IDLE | {"phase": "show_begin", "sequence": 1, "sample_age_ms": 0}
    assert state.receive(raw(row)) == {"accepted": True}
    assert state.status()["client"] == row
