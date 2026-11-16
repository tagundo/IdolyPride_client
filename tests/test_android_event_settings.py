"""Exercise the Android native event boundary without a listener or live account.

The recording backend models only persisted settings and a frozen current run;
production shared validation is exercised separately by test_event_settings.py.
The Java harness compiles the production date-window arithmetic unchanged.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "android-server/app/src/main/python/android_server_runtime.py"
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/EventWindow.java"
EVENT = "event-love-23-0514"
BASE = {"schema": 1, "revision": 0, "love_events": []}


@pytest.fixture
def native_events(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("android_event_boundary", BRIDGE)
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    files = tmp_path / "files"
    data = files / "data"
    data.mkdir(parents=True)
    database = data / "state.db"
    database.write_bytes(b"synthetic account progress: must not change")
    calls = []
    state = {"saved": copy.deepcopy(BASE), "available": True, "failure": None, "override": None}

    class EventError(ValueError):
        def __init__(self, code, detail="private/path sensitive-value"):
            self.code = code
            super().__init__(detail)

    def command(root, action, payload, *, effective=None):
        calls.append((root, action, copy.deepcopy(payload), copy.deepcopy(effective)))
        if state["failure"] is not None:
            raise state["failure"]
        if state["override"] is not None:
            return state["override"]
        if action == "events_save":
            if payload["expected_revision"] != state["saved"]["revision"]:
                raise EventError("event_settings_revision_conflict")
            state["saved"] = dict(copy.deepcopy(payload["settings"]), revision=state["saved"]["revision"] + 1)
            (root / "server-events.json").write_text(json.dumps(state["saved"]))
        return {"schema": 1, "saved": copy.deepcopy(state["saved"]),
                "effective": copy.deepcopy(effective), "restart_required": effective is not None and effective != state["saved"],
                "invalid_settings_file": False,
                "catalog": {"schema": 1, "available": state["available"],
                            "events": [{"id": EVENT, "title": "Synthetic", "supported": True}] if state["available"] else [],
                            "ruleset_sha256": "c" * 64 if state["available"] else None}}

    monkeypatch.setitem(sys.modules, "idoly_local.event_settings", SimpleNamespace(
        event_settings_command=command, EventSettingsError=EventError,
        ERROR_CODES=frozenset({"event_settings_revision_conflict", "event_settings_catalog_unavailable"})))
    def forbidden(*args, **kwargs):
        pytest.fail("Event commands must not prepare account data, switch mode, or start/stop a game")
    monkeypatch.setattr(boundary, "_prepare_management_payload", forbidden)
    monkeypatch.setattr(boundary, "start", forbidden)
    monkeypatch.setattr(boundary, "stop", forbidden)
    monkeypatch.setitem(sys.modules, "idoly_local.account_manager", SimpleNamespace(account_command=forbidden))
    def invoke(action, payload=None):
        return json.loads(boundary.management_command_json(str(files), action, json.dumps(payload or {})))
    return boundary, files, database, state, calls, EventError, invoke


class Active:
    def __init__(self, *, media=False, running=True):
        self.media = media
        self.running = running
        self.frozen = copy.deepcopy(BASE)
    def status(self):
        return {"running": self.running, "profile": "synthetic-slot", "media_mode": self.media,
                "event_settings": {"effective": self.frozen}}


@pytest.mark.parametrize("media", [False, True])
def test_save_is_persist_only_in_both_modes_and_current_run_stays_frozen(native_events, media):
    boundary, files, database, state, calls, Error, invoke = native_events
    runtime = Active(media=media)
    boundary._RUNTIME = runtime
    before = database.read_bytes()
    settings = dict(copy.deepcopy(BASE), love_events=[{"event_id": EVENT, "start_time_ms": 1000, "end_time_ms": 2000}])
    request = {"settings": settings, "expected_revision": 0}
    result = invoke("events_save", request)
    assert result["ok"] is True and result["action"] == "events_save"
    observed = result["event_settings"]
    assert observed["saved"]["love_events"] == settings["love_events"] and observed["saved"]["revision"] == 1
    assert observed["effective"] == BASE and observed["restart_required"] is True
    assert calls == [(files / "data", "events_save", request, BASE)]
    assert boundary._RUNTIME is runtime and runtime.frozen == BASE and runtime.running and runtime.media is media
    assert database.read_bytes() == before
    assert {path.name for path in (files / "data").iterdir()} == {"state.db", "server-events.json"}
    assert json.loads((files / "data/server-events.json").read_text()) == observed["saved"]
    assert result["active"] == {"running": True, "mode": "media" if media else "normal", "profile": "synthetic-slot"}


@pytest.mark.parametrize("runtime", [None, Active(running=False)])
def test_stopped_settings_have_no_claim_of_current_effective_state(native_events, runtime):
    boundary, files, database, state, calls, Error, invoke = native_events
    boundary._RUNTIME = runtime
    result = invoke("events_status")
    assert result["event_settings"]["effective"] is None
    assert result["event_settings"]["restart_required"] is False
    assert calls == [(files / "data", "events_status", {}, None)]
    assert list((files / "data").iterdir()) == [database]


def test_cas_failure_keeps_original_config_and_exposes_only_fixed_code(native_events):
    boundary, files, database, state, calls, Error, invoke = native_events
    invoke("events_save", {"settings": BASE, "expected_revision": 0})
    before = (files / "data/server-events.json").read_bytes()
    request = {"settings": dict(BASE, love_events=[{"event_id": EVENT, "start_time_ms": 10, "end_time_ms": 20}]), "expected_revision": 0}
    result = invoke("events_save", request)
    assert result == {"schema": 1, "ok": False, "error": "event_settings_revision_conflict"}
    assert (files / "data/server-events.json").read_bytes() == before
    assert request["settings"]["love_events"] and request["expected_revision"] == 0
    current = invoke("events_status")["event_settings"]
    assert current["saved"]["revision"] == 1 and current["saved"]["love_events"] == []
    assert all("sensitive-value" not in json.dumps(value) for value in (result, current))


@pytest.mark.parametrize("code,expected", [("event_settings_catalog_unavailable", "event_settings_catalog_unavailable"),
                                           ("sensitive-value", "event_settings_command_invalid")])
def test_unknown_backend_exception_code_and_private_details_are_not_forwarded(native_events, code, expected):
    boundary, files, database, state, calls, Error, invoke = native_events
    state["failure"] = Error(code)
    assert invoke("events_status") == {"schema": 1, "ok": False, "error": expected}
    assert list((files / "data").iterdir()) == [database]


@pytest.mark.parametrize("error", [ValueError("private_snake_case_canary"), OSError("private/path"), RuntimeError("sensitive-value")])
def test_untyped_event_backend_failure_is_always_fixed_and_private(native_events, error):
    boundary, files, database, state, calls, Error, invoke = native_events
    state["failure"] = error
    assert invoke("events_status") == {"schema": 1, "ok": False, "error": "event_settings_io"}


@pytest.mark.parametrize("bad", [[], {"schema": 1}, {"schema": 2, "saved": BASE, "catalog": {}},
                                  {"schema": 1, "saved": [], "catalog": {}}])
def test_invalid_backend_response_is_not_reported_as_saved(native_events, bad):
    boundary, files, database, state, calls, Error, invoke = native_events
    state["override"] = bad
    assert invoke("events_status") == {"schema": 1, "ok": False, "error": "event_settings_response_invalid"}


def test_large_bounded_multi_event_request_is_forwarded_but_over_limit_is_rejected_first(native_events):
    boundary, files, database, state, calls, Error, invoke = native_events
    rows = [{"event_id": "event-" + str(index).zfill(3) + "x" * 85,
             "start_time_ms": 1794800000000, "end_time_ms": 1794800001000} for index in range(64)]
    request = {"settings": dict(BASE, love_events=rows), "expected_revision": 0}
    encoded = json.dumps(request)
    assert 8192 < len(encoded.encode()) < 32768
    assert invoke("events_save", request)["ok"] is True
    assert calls[-1][2] == request
    calls.clear()
    huge = json.dumps({"padding": "x" * 65536})
    assert json.loads(boundary.management_command_json(str(files), "events_save", huge)) == {
        "schema": 1, "ok": False, "error": "account_request_invalid"}
    assert calls == []


def test_unavailable_catalog_is_preserved_and_disable_only_recovery_does_not_touch_progress(native_events):
    boundary, files, database, state, calls, Error, invoke = native_events
    state["available"] = False
    state["saved"] = dict(BASE, revision=7, love_events=[{"event_id": EVENT, "start_time_ms": 10, "end_time_ms": 20}])
    before = database.read_bytes()
    assert invoke("events_status")["event_settings"]["catalog"]["events"] == []
    result = invoke("events_save", {"settings": dict(BASE, revision=7), "expected_revision": 7})
    assert result["event_settings"]["saved"] == dict(BASE, revision=8)
    assert result["event_settings"]["catalog"]["available"] is False
    assert database.read_bytes() == before


def test_production_event_window_bounds_and_duration_preservation(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The required event-window harness needs a JDK"
    package = tmp_path / "game/qualiarts/idolypride/localserver"
    package.mkdir(parents=True)
    (package / "EventWindow.java").write_text(JAVA.read_text())
    source = r'''
package game.qualiarts.idolypride.localserver;
public final class EventWindowHarness {
 static void check(boolean value,String code) { if(!value)throw new AssertionError(code); }
 interface Operation { void run(); }
 static void rejected(Operation operation) {
  try { operation.run(); throw new AssertionError("invalid window accepted"); }
  catch(IllegalArgumentException expected) { check("event_settings_invalid".equals(expected.getMessage()),"unbounded error"); }
 }
 public static void main(String[] ignored) {
  long day=24L*60*60*1000, now=1794800000000L;
  long[] preset=EventWindow.preset(now);
  check(preset[0]==now&&preset[1]==now+30*day,"preset must be explicit local thirty days");
  check(EventWindow.valid(0,366*day)&&!EventWindow.valid(0,366*day+1),"maximum duration");
  check(!EventWindow.valid(-1,1)&&!EventWindow.valid(1,1)&&!EventWindow.valid(2,1),"ordered nonnegative timestamps");
  check(!EventWindow.valid(EventWindow.MAX_SAFE-1,EventWindow.MAX_SAFE+1),"safe integer bound");
  long[] shifted=EventWindow.shiftStart(100,10,20);
  check(shifted[0]==100&&shifted[1]==110,"start edit changed duration");
  long[] maximum=EventWindow.preset(EventWindow.MAX_SAFE-30*day);
  check(maximum[1]==EventWindow.MAX_SAFE,"maximum safe preset");
  rejected(()->EventWindow.preset(-1));rejected(()->EventWindow.preset(EventWindow.MAX_SAFE-30*day+1));
  rejected(()->EventWindow.shiftStart(-1,10,20));rejected(()->EventWindow.shiftStart(100,20,10));
  rejected(()->EventWindow.shiftStart(EventWindow.MAX_SAFE,10,20));
  System.out.println("event-window-harness PASS");
 }
}
'''
    harness = package / "EventWindowHarness.java"
    harness.write_text(source)
    built = subprocess.run([javac, "-encoding", "UTF-8", "--release", "17", str(package / "EventWindow.java"), str(harness)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([java, "-cp", str(tmp_path), "game.qualiarts.idolypride.localserver.EventWindowHarness"],
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout.strip() == "event-window-harness PASS"
