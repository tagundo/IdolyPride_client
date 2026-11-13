import json
import http.client
import threading
from copy import deepcopy

import pytest

from idoly_local.wardrobe_diagnostics import EXIT_IDLE, MAXIMUM, WardrobeDiagnostics, decode

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


def exit_report(**changes):
    return IDLE | {"schema": 2, "exit": deepcopy(EXIT_IDLE) | changes}


def test_schema_two_idle_keeps_schema_one_compatibility_and_does_not_log():
    logs = []
    state = WardrobeDiagnostics(logs.append)
    assert decode(raw(IDLE)) == IDLE
    assert state.receive(raw(exit_report())) == {"accepted": True}
    assert state.status()["client"] == exit_report()
    assert state.receive(raw(IDLE)) == {"accepted": True}
    assert state.status()["client"] == IDLE
    assert logs == []
    with pytest.raises(ValueError):
        decode(raw(IDLE | {"exit": EXIT_IDLE}))


@pytest.mark.parametrize("phase", ["back", "preclose", "hide", "disable", "selection_show",
                                   "selection_open", "gc", "unload", "completed"])
def test_exit_stages_preserve_typed_timing_without_claiming_completion(phase):
    # A clock failure or a120s tracking expiry can coexist with a call still
    # running. Bounded history need not retain the lifetime maximum's span.
    row = exit_report(room="fitting_room", phase=phase, sequence=MAXIMUM,
                      active=False, in_original=True, elapsed_ms=None,
                      last_sync_ms=MAXIMUM, max_sync_ms=MAXIMUM, max_sync_stage="gc",
                      spans=[{"stage": "preclose", "duration_ms": 0} for _ in range(8)])
    assert decode(raw(row)) == row
    state = WardrobeDiagnostics()
    state.receive(raw(row))
    assert state.status()["client"] == row


def test_nested_snapshots_and_history_are_independent_copies():
    row = exit_report(room="character_costume", phase="completed", sequence=3,
                      elapsed_ms=37000, last_sync_ms=35000, max_sync_ms=35000,
                      max_sync_stage="hide", spans=[{"stage": "hide", "duration_ms": 35000}])
    state = WardrobeDiagnostics()
    state.receive(raw(row))
    snapshot = state.status()
    snapshot["client"]["exit"]["spans"][0]["duration_ms"] = 0
    snapshot["client"]["exit"]["spans"].append({"stage": "back", "duration_ms": 1})
    snapshot["client"]["exit"]["room"] = "none"
    assert state.status()["client"] == row


def test_exit_logs_only_when_exit_sequence_changes_and_legacy_logs_are_unchanged():
    clock = [10.0]
    logs = []
    state = WardrobeDiagnostics(logs.append, clock=lambda: clock[0])
    state.receive(raw(exit_report()))
    row = exit_report(room="character_costume", phase="hide", active=True,
                      in_original=True, elapsed_ms=37000, max_sync_ms=120,
                      max_sync_stage="preclose", sequence=2)
    state.receive(raw(row))
    assert logs == ["의상룸 종료 · 화면 숨김 · 경과 37000 ms · 최장 동기 처리 120 ms (종료 전 처리)"]
    # Polling updates live elapsed time, not the event identity.
    state.receive(raw(row | {"exit": row["exit"] | {"elapsed_ms": 39000}}))
    assert len(logs) == 1
    clock[0] = 13
    assert state.status()["age_seconds"] == 3
    assert state.status()["client"]["exit"]["elapsed_ms"] == 39000
    legacy = {"phase": "show_begin", "sequence": 1, "sample_age_ms": 10}
    state.receive(raw(row | legacy))
    assert logs[-1] == "의상룸 캐릭터 표시 시작"
    assert len(logs) == 2
    completed = row["exit"] | {"phase": "completed", "active": False, "in_original": False,
                                "sequence": 3, "elapsed_ms": None}
    state.receive(raw(row | legacy | {"exit": completed}))
    assert logs[-1] == "의상룸 종료 · 캐릭터 선택창 복귀 콜백 반환 · 경과 측정 불가 · 최장 동기 처리 120 ms (종료 전 처리)"
    assert len(logs) == 3
    # An old client or new game process can reset the optional channel.
    state.receive(raw(IDLE))
    state.receive(raw(row))
    assert len(logs) == 4


@pytest.mark.parametrize("changes", [
    {"schema": True}, {"schema": 2}, {"room": []}, {"room": "player-name"},
    {"phase": []}, {"phase": "unknown"}, {"active": 1}, {"in_original": None},
    {"elapsed_ms": True}, {"elapsed_ms": -1}, {"elapsed_ms": MAXIMUM + 1},
    {"elapsed_ms": float("nan")}, {"last_sync_ms": False}, {"last_sync_ms": -1},
    {"max_sync_ms": MAXIMUM + 1}, {"max_sync_stage": []}, {"max_sync_stage": "unknown"},
    {"sequence": True}, {"sequence": -1}, {"sequence": MAXIMUM + 1},
    {"spans": {}}, {"spans": [{"stage": "back", "duration_ms": 0}] * 9},
    {"spans": [None]}, {"spans": [{"stage": "none", "duration_ms": 0}]},
    {"spans": [{"stage": "back", "duration_ms": True}]},
    {"spans": [{"stage": "back", "duration_ms": -1}]},
    {"spans": [{"stage": "back", "duration_ms": MAXIMUM + 1}]},
    {"spans": [{"stage": "back", "duration_ms": 0, "account": "forbidden"}]},
    {"spans": [{"stage": "back"}]}, {"account": "forbidden"},
])
def test_malformed_nested_exit_reports_do_not_replace_the_last_snapshot(changes):
    state = WardrobeDiagnostics()
    previous = exit_report(room="character_costume", phase="back", active=True,
                           elapsed_ms=0, sequence=1)
    state.receive(raw(previous))
    with pytest.raises(ValueError):
        state.receive(raw(previous | {"exit": previous["exit"] | changes}))
    assert state.status()["client"] == previous


@pytest.mark.parametrize("changes", [{"room": "character_costume"}, {"active": True},
    {"in_original": True}, {"elapsed_ms": 0}, {"last_sync_ms": 1}, {"max_sync_ms": 1},
    {"max_sync_stage": "back"}, {"sequence": 1},
    {"spans": [{"stage": "back", "duration_ms": 0}]}])
def test_idle_exit_is_the_exact_initial_snapshot(changes):
    with pytest.raises(ValueError):
        decode(raw(exit_report(**changes)))


def test_nested_duplicate_fields_and_bounded_message_sizes():
    encoded = raw(exit_report())
    assert len(encoded) < 2048
    assert decode(b" " * (2048 - len(encoded)) + encoded) == exit_report()
    for value in (b" " * (2049 - len(encoded)) + encoded,
                  encoded.replace(b'"room": "none"', b'"room": "none", "room": "none"'),
                  encoded.replace(b'"exit": {', b'"exit": null, "exit": {')):
        with pytest.raises(ValueError):
            decode(value)
    nested = raw(exit_report(room="character_costume", phase="hide", sequence=1,
        spans=[{"stage": "hide", "duration_ms": 1}]))
    with pytest.raises(ValueError):
        decode(nested.replace(b'"duration_ms": 1', b'"duration_ms": 1, "duration_ms": 1'))


def test_optional_log_failure_cannot_drop_a_schema_two_observation():
    def bad_log(_):
        raise RuntimeError("Optional display is unavailable")
    row = exit_report(room="fitting_room", phase="preclose", active=True,
                      in_original=True, elapsed_ms=37000, sequence=2)
    state = WardrobeDiagnostics(bad_log)
    assert state.receive(raw(row)) == {"accepted": True}
    assert state.status()["client"] == row


@pytest.mark.parametrize("value", [None, [], {}, 1, "untyped exit"])
def test_schema_two_requires_a_complete_typed_exit_object(value):
    with pytest.raises(ValueError):
        decode(raw(IDLE | {"schema": 2, "exit": value}))


def test_schema_two_round_trips_through_actual_loopback_http_and_runtime_status(tmp_path):
    from idoly_local.assets import create_asset_server

    probe = WardrobeDiagnostics()
    server = create_asset_server("127.0.0.1", 0, tmp_path, wardrobe_probe=probe,
                                 runtime_status_callback=lambda: {"wardrobe_probe": probe.status()})
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()

    def request(method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    row = exit_report(room="character_costume", phase="hide", active=True, in_original=True,
                      elapsed_ms=37000, sequence=4, max_sync_ms=35000, max_sync_stage="gc",
                      spans=[{"stage": "back", "duration_ms": 0}, {"stage": "gc", "duration_ms": 35000}])
    try:
        assert request("POST", "/client/wardrobe", raw(row)) == (200, {"accepted": True})
        status, value = request("GET", "/client/wardrobe")
        assert status == 200 and value["client"] == row
        status, value = request("GET", "/diagnostics/runtime")
        assert status == 200 and value["wardrobe_probe"]["client"] == row
        bad = row | {"exit": row["exit"] | {"spans": [{"stage": "gc", "duration_ms": -1}]}}
        assert request("POST", "/client/wardrobe", raw(bad)) == (400, {"error": "invalid_wardrobe_status"})
        assert probe.status()["client"] == row
        assert request("POST", "/client/wardrobe", raw(IDLE)) == (200, {"accepted": True})
        assert probe.status()["client"] == IDLE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
