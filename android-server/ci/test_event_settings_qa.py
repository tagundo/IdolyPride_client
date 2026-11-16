"""Synthetic host checks for actual Native event QA fail-closed observations."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest

DIRECTORY = Path(__file__).parent
ACCOUNT_SPEC = importlib.util.spec_from_file_location("qa_account_management", DIRECTORY / "qa_account_management.py")
account = importlib.util.module_from_spec(ACCOUNT_SPEC)
ACCOUNT_SPEC.loader.exec_module(account)
sys.modules.setdefault("qa_account_management", account)
SPEC = importlib.util.spec_from_file_location("native_event_qa", DIRECTORY / "qa_event_settings.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def settings():
    now = int(probe.time.time()*1000)
    return {"schema": 1, "saved": {"schema": 1, "revision": 1, "love_events": [
        {"event_id": "love-23-0514", "start_time_ms": now, "end_time_ms": now+30*probe.DAY}]}}


def home(entry):
    return SimpleNamespace(DESCRIPTOR=SimpleNamespace(fields_by_name={"eventInfo": object()}),
        eventInfo=SimpleNamespace(loveEventInfos=[SimpleNamespace(id=entry["event_id"],
            startTime=entry["start_time_ms"], endTime=entry["end_time_ms"])]))


def test_saved_observation_requires_exact_cas_event_and_local_duration():
    observed = settings()
    entry = probe.assert_enabled(observed, "love-23-0514", 0)
    assert entry is observed["saved"]["love_events"][0]
    for damage in ("revision", "identity", "duration", "stale-period"):
        changed = copy.deepcopy(observed)
        if damage == "revision": changed["saved"]["revision"] = True
        elif damage == "identity": changed["saved"]["love_events"][0]["event_id"] = "unobserved"
        elif damage == "duration": changed["saved"]["love_events"][0]["end_time_ms"] += 1
        else:
            changed["saved"]["love_events"][0]["start_time_ms"] -= 3600000
            changed["saved"]["love_events"][0]["end_time_ms"] -= 3600000
        with pytest.raises(RuntimeError): probe.assert_enabled(changed, "love-23-0514", 0)


def test_actual_home_projection_requires_exact_id_and_period():
    entry = settings()["saved"]["love_events"][0]
    probe.assert_home_event(home(entry), entry)
    for field in ("id", "startTime", "endTime"):
        changed = home(entry)
        setattr(changed.eventInfo.loveEventInfos[0], field, "wrong" if field == "id" else 0)
        with pytest.raises(RuntimeError, match="encrypted Home"):
            probe.assert_home_event(changed, entry)


@pytest.mark.parametrize("damage", [None, "frozen", "progress", "home", "saved-file"])
def test_native_flow_gates_follow_observed_save_restart_rpc_and_progress(monkeypatch, damage):
    base = {"schema": 1, "revision": 0, "love_events": []}
    model = {"saved": copy.deepcopy(base), "effective": None, "starts": 0, "calls": [], "selected": "sandbox"}
    owned = {table: () for table in account.TABLES}
    owned["profiles"] = (("@slot", "synthetic-server"),)
    owned["snapshots"] = (("@slot", b"unchanged snapshot"),)
    def snapshot(guest, copier, profile):
        value = copy.deepcopy(owned)
        if damage == "progress" and model["saved"]["revision"] == 2:
            value["profile_love_progress"] = (("changed",),)
        return value
    def runtime(port):
        effective = copy.deepcopy(model["effective"])
        if damage == "frozen" and model["saved"]["revision"] == 1 and model["starts"] == 1:
            effective = copy.deepcopy(model["saved"])
        return ({"running": True, "profile": probe.CREATE}, {"schema": 1,
            "saved": copy.deepcopy(model["saved"]), "effective": effective,
            "restart_required": effective != model["saved"], "catalog": {"available": True,
                "events": [{"id": "love-23-0514", "title": "Synthetic", "supported": True}], "ruleset_sha256": "a"*64}})
    class Guest:
        def adb(self, *arguments, **kwargs):
            model["calls"].append(("adb", arguments))
            if arguments[:4] == ("exec-out", "run-as", probe.PACKAGE, "cat"):
                value = model["saved"] if damage != "saved-file" else base
                return json.dumps(value).encode()
            return ""
        def tap(self, text, stage):
            model["calls"].append(("native", text, stage))
            if text == "서버 시작":
                model["starts"] += 1
                model["effective"] = copy.deepcopy(model["saved"])
        def capture(self, stage): model["calls"].append(("capture", stage))
    guest = Guest()
    def find(guest, predicate, stage, direction=None, **kwargs):
        model["calls"].append(("find", stage))
        return ET.fromstring('<node checked="false"/>')
    def enable(guest, node):
        model["calls"].append(("native-checkbox",))
        model["saved"] = settings()["saved"]
    def tap(guest, description, stage, direction=None):
        model["calls"].append(("native-description", description))
        if description == "idoly.events.disable-all":
            model["saved"] = dict(copy.deepcopy(base), revision=2)
    def select(guest, profile, *args):
        model["selected"] = profile
        model["calls"].append(("select", profile))
    def rpc(schema, port, method, token):
        model["calls"].append(("encrypted-rpc", method, token))
        entry = copy.deepcopy(model["effective"]["love_events"][0])
        if damage == "home": entry["end_time_ms"] += 1
        return home(entry)
    monkeypatch.setattr(probe, "projection", snapshot)
    monkeypatch.setattr(probe, "runtime_settings", runtime)
    monkeypatch.setattr(probe, "find", find)
    monkeypatch.setattr(probe, "tap_node", enable)
    monkeypatch.setattr(probe, "tap", tap)
    monkeypatch.setattr(probe, "select_profile", select)
    arguments = (guest, object(), 50051, 8080, 600)
    options = dict(wait_server=lambda *a, **k: None, bootstrap=lambda *a: (None, SimpleNamespace(gameAuthToken=b"synthetic-token")),
                   rpc=rpc, copy_database=object())
    if damage is not None:
        with pytest.raises(RuntimeError): probe.exercise_event_settings(*arguments, **options)
        return
    report = probe.exercise_event_settings(*arguments, **options)
    assert report["native_event_settings_autosave"] is True and report["native_event_settings_restart_preserved"] is True
    detail = report["native_event_settings"]
    assert detail["home_event_verified"] is True and detail["progress_preserved"] is True
    assert detail["gameplay_tested"] is False and detail["physical_device_tested"] is False
    assert model["starts"] == 2 and model["selected"] == "sandbox"
    assert model["saved"]["love_events"] == [] and model["saved"]["revision"] == 2
    assert ("encrypted-rpc", "/api.Home/Enter", b"synthetic-token") in model["calls"]
    assert model["calls"].index(("native-checkbox",)) < model["calls"].index(("native", "서버 시작", "86-event-restart"))
