"""The installed app must opt in and retain exact receipts across process death."""
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3

import grpc
import pytest

from idoly_local import main_live_qa
from idoly_local import codec
from idoly_local.schema import Schema
from test_tutorial_continuation_qa import Device, qa


TOKEN = "local-original-private-session"
IDS = ("9000000000000000301", "9000000000000000302")
START = "/api.Quest/Start"


def client_schema():
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(descriptor)


@pytest.mark.parametrize("path,identity", ((START, IDS[0]), ("/api.User/Get", None)))
def test_native_rpc_carries_the_exact_request_id_only_when_supplied(monkeypatch, path, identity):
    schema, observed = client_schema(), []
    request = schema.request_type(path)()
    if path == START:
        request.questId, request.deckNumber, request.playCount = "qt-main-1-001-01", 1, 1
    response = schema.response_type(path)()

    class Channel:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def unary_unary(self, method):
            assert method == path

            def call(payload, *, metadata, timeout):
                assert codec.decode(payload) == request.SerializeToString()
                assert 30 <= timeout <= 120
                observed.extend(metadata)
                return codec.encode(response.SerializeToString())

            return call

    def connect(address):
        assert address == "127.0.0.1:12345"
        return Channel()

    monkeypatch.setattr(qa.grpc, "insecure_channel", connect)
    assert qa.rpc(schema, 12345, path, TOKEN, request, request_id=identity) == response
    assert observed == [("x-auth-token", TOKEN)] + ([] if identity is None else [("x-app-request-id", identity)])


class Rejected(grpc.RpcError):
    def __init__(self, code):
        self.status = code

    def code(self):
        return self.status


class ModeDevice(Device):
    def __init__(self):
        super().__init__()
        self.mode = False
        self.forget_mode = False

    def capture(self, stage):
        captured = super().capture(stage)
        if stage.startswith(("48-main-live-find-", "48-main-live-checked-")):
            hierarchy = qa.ET.Element("hierarchy")
            qa.ET.SubElement(hierarchy, "node", {
                "text": "첫 메인 라이브 실험 기능 사용",
                "class": "android.widget.CheckBox", "checkable": "true",
                "enabled": "true", "checked": str(self.mode).lower(),
                "bounds": "[55,700][1025,800]",
            })
            return hierarchy
        return captured

    def tap(self, text, stage):
        if text == "첫 메인 라이브 실험 기능 사용":
            assert self.process and not self.running
            self.mode = not self.mode
        super().tap(text, stage)

    def adb(self, *args):
        super().adb(*args)
        if args[:3] == ("shell", "am", "force-stop") and self.forget_mode:
            self.mode = False


@pytest.fixture
def native(tmp_path, monkeypatch):
    schema, device = client_schema(), ModeDevice()
    final = schema.response_type("/api.User/Get")()
    final.user.name = "Preserved manager"
    final.balance.freeBalance, final.balance.paidBalance = 150, 17
    final.MergeFromString(qa.QA_UNKNOWN_PB)
    receipt = {"snapshot_sha256": hashlib.sha256(final.SerializeToString(deterministic=True)).hexdigest()}
    clock = [(b"original raw lesson clock", schema.fingerprint)]
    attempts = [("original seed/time/response 1",), ("original seed/time/response 2",)]
    preserved = {"identity": "original", "settings": "original"}
    state = {"default_code": grpc.StatusCode.UNIMPLEMENTED, "enabled_default": False,
             "default_mutates": False, "preexisting": False}
    calls, checks = [], []

    def rpc(received_schema, port, path, token=None, request=None, request_id=None):
        assert received_schema is schema and port == 12345 and token == TOKEN and device.running
        calls.append((device.starts, path, request_id, device.mode))
        if path == "/api.User/Get":
            assert request_id is None
            return type(final).FromString(final.SerializeToString())
        assert path == START and request.questId == "qt-main-1-001-01" and request.deckNumber == request.playCount == 1
        if not device.mode and not state["enabled_default"]:
            if state["default_mutates"]:
                final.balance.freeBalance += 50
            raise Rejected(state["default_code"])
        return schema.response_type(START)(questId=request.questId)

    def run(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and master_dir == tmp_path and label == "Android native"
        assert device.starts == 2 and device.mode
        for identity in IDS:
            invoke(START, schema.request_type(START)(questId="qt-main-1-001-01", deckNumber=1, playCount=1), identity)
        invoke("/api.User/Get", schema.request_type("/api.User/Get")(), None)
        return dict(receipt)

    def retries(received_schema, invoke, master_dir, saved):
        assert received_schema is schema and device.starts == 3 and master_dir == tmp_path and saved == receipt
        for identity in IDS:
            invoke(START, schema.request_type(START)(questId="qt-main-1-001-01", deckNumber=1, playCount=1), identity)
        main_live_qa.assert_main_live_snapshot(schema,
            invoke("/api.User/Get", schema.request_type("/api.User/Get")(), None), saved)

    def wait(received_schema, port, *, expected=True, timeout):
        assert received_schema is schema and port == 12345 and device.running == expected

    def protected(received_device, expected):
        assert received_device is device and not device.process
        if expected != preserved:
            raise RuntimeError("Native main live changed preserved identity/settings")
        checks.append(("protected", device.starts))

    def database(received_device, received_schema, saved=None, *, expected_clock=None, expected_attempts=None):
        assert received_device is device and received_schema is schema and not device.process
        checks.append(("database", device.starts))
        if saved is None:
            return clock[0], (("preexisting",),) if state["preexisting"] else ()
        main_live_qa.assert_main_live_snapshot(schema, final, saved)
        if expected_clock != clock[0]:
            raise RuntimeError("Native main live changed raw lesson clock")
        current = tuple(attempts)
        if expected_attempts is not None and current != expected_attempts:
            raise RuntimeError("Native main live changed cached seed/time/response")
        return clock[0], current

    monkeypatch.setattr(qa, "rpc", rpc)
    monkeypatch.setattr(qa, "wait_server", wait)
    monkeypatch.setattr(qa, "verify_upgrade_database", protected)
    monkeypatch.setattr(qa, "verify_main_live_database", database)
    monkeypatch.setattr(main_live_qa, "run_main_live_checks", run)
    monkeypatch.setattr(main_live_qa, "assert_main_live_retries", retries)
    return schema, device, final, receipt, clock, attempts, preserved, state, calls, checks, tmp_path


def exercise(native):
    schema, device, *_rest, master = native
    return qa.exercise_main_live_checks(device, schema, 12345, TOKEN, master, 600,
        {"identity": "original", "settings": "original"})


def test_opt_in_is_explicit_and_restart_uses_the_original_session_before_reporting_success(native):
    _schema, device, _final, receipt, _clock, _attempts, _preserved, _state, calls, checks, _master = native
    report = exercise(native)
    assert report["main_live"] == receipt
    assert all(value is True for key, value in report.items() if key != "main_live")
    assert calls[:3] == [(1, "/api.User/Get", None, False), (1, START, "9000000000000000300", False),
                         (1, "/api.User/Get", None, False)]
    assert [(number, identity) for number, path, identity, _mode in calls[3:] if path == START] == [
        (2, IDS[0]), (2, IDS[1]), (3, IDS[0]), (3, IDS[1])]
    assert checks == [("database", 0), ("protected", 2), ("database", 2), ("protected", 3), ("database", 3)]
    assert sum(event[0] == "첫 메인 라이브 실험 기능 사용" for event in device.events) == 1
    assert device.starts == 3 and not device.process
    assert TOKEN not in json.dumps(report)


@pytest.mark.parametrize("failure", ("enabled-by-default", "wrong-default-status", "default-mutation", "preexisting-cache"))
def test_a_default_mode_failure_cannot_be_reported_as_opt_in_success(native, failure):
    _schema, device, _final, _receipt, _clock, _attempts, _preserved, state, _calls, _checks, _master = native
    if failure == "enabled-by-default": state["enabled_default"] = True
    if failure == "wrong-default-status": state["default_code"] = grpc.StatusCode.UNAUTHENTICATED
    if failure == "default-mutation": state["default_mutates"] = True
    if failure == "preexisting-cache": state["preexisting"] = True
    with pytest.raises((RuntimeError, Rejected)):
        exercise(native)
    assert device.starts <= 1


def test_losing_the_preference_on_process_death_fails_the_same_id_restart_checks(native):
    _schema, device, *_rest = native
    device.forget_mode = True
    with pytest.raises(Rejected) as error:
        exercise(native)
    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert device.starts == 3


@pytest.mark.parametrize("damage", ("snapshot", "unknown", "clock", "identity", "settings", "cached-seed-time-response"))
def test_snapshot_protected_state_or_cached_receipt_damage_cannot_produce_success(native, monkeypatch, damage):
    _schema, device, final, _receipt, clock, attempts, preserved, _state, _calls, _checks, _master = native
    capture = device.capture

    def corrupt(stage):
        capture(stage)
        if stage != "53-main-live-cached":
            return
        if damage == "snapshot": final.balance.freeBalance += 50
        elif damage == "unknown": final.DiscardUnknownFields()
        elif damage == "clock": clock[0] = (b"changed lesson clock", clock[0][1])
        elif damage == "cached-seed-time-response": attempts[0] = ("different seed/time/response",)
        else: preserved[damage] = "changed"

    monkeypatch.setattr(device, "capture", corrupt)
    with pytest.raises(RuntimeError):
        exercise(native)
    assert device.starts == 3 and not device.process


@pytest.fixture
def stopped_database(tmp_path, monkeypatch):
    schema = client_schema()
    final = schema.response_type("/api.User/Get")()
    final.user.name = "Saved local manager"
    final.MergeFromString(qa.QA_UNKNOWN_PB)
    bodies = [schema.response_type(START)(questId="qt-main-1-001-01", highestScore=score).SerializeToString(deterministic=True)
              for score in (5000, 6000)]
    digest = lambda payload: hashlib.sha256(payload).hexdigest()
    snapshot = final.SerializeToString(deterministic=True)
    clock = (b"preserved lesson clock", schema.fingerprint)
    receipt = {"snapshot_sha256": digest(snapshot), "request_ids": list(IDS), "started_times": [1000, 1001],
               "request_sha256": "1" * 64, "schema_sha256": schema.fingerprint, "master_version": "test-master",
               "ruleset": "live-v5", "first_response_sha256": digest(bodies[0]), "replay_response_sha256": digest(bodies[1])}
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE snapshots(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE profile_lesson_progress(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE main_live_attempts(profile TEXT,request_id TEXT,request_sha256 TEXT,path TEXT,schema_sha256 TEXT,master_version TEXT,ruleset TEXT,seed TEXT,started_time INTEGER,response BLOB)")
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("sandbox", snapshot, schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES(?,?,?)", ("sandbox", *clock))
        for index, identity in enumerate(IDS):
            db.execute("INSERT INTO main_live_attempts VALUES(?,?,?,?,?,?,?,?,?,?)", ("sandbox", identity,
                receipt["request_sha256"], START, schema.fingerprint, receipt["master_version"], "live-v5",
                str(index + 1), receipt["started_times"][index], bodies[index]))
    spec = spec_from_file_location("main_live_stopped_database_qa", Path(__file__).with_name("qa_emulator.py"))
    real = module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(real, "_copy_private_database", lambda received, directory: path)
    return real, schema, path, final, clock, receipt


def test_real_database_verifier_retains_canonical_seed_and_full_cached_response_across_restart(stopped_database):
    real, schema, path, _final, clock, receipt = stopped_database
    observed_clock, attempts = real.verify_main_live_database(None, schema, receipt, expected_clock=clock)
    assert observed_clock == clock and len(attempts) == 2
    assert real.verify_main_live_database(None, schema, receipt, expected_clock=clock, expected_attempts=attempts) == (clock, attempts)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE main_live_attempts SET seed='99' WHERE request_id=?", (IDS[0],))
    # A different canonical seed still passes the structural oracle. The native
    # restart boundary must additionally require the original complete SQL row.
    real.verify_main_live_database(None, schema, receipt, expected_clock=clock)
    with pytest.raises(RuntimeError, match="seed, time or exact response"):
        real.verify_main_live_database(None, schema, receipt, expected_clock=clock, expected_attempts=attempts)


@pytest.mark.parametrize("damage", ("snapshot-schema", "clock-schema", "clock", "snapshot", "unknown", "missing-attempt", "time", "response", "noncanonical-seed"))
def test_real_database_mismatch_rejects_persistence_evidence(stopped_database, damage):
    real, schema, path, final, clock, receipt = stopped_database
    with sqlite3.connect(path) as db:
        if damage == "snapshot-schema": db.execute("UPDATE snapshots SET schema_sha256='wrong'")
        elif damage == "clock-schema": db.execute("UPDATE profile_lesson_progress SET schema_sha256='wrong'")
        elif damage == "clock": db.execute("UPDATE profile_lesson_progress SET response=?", (b"changed",))
        elif damage in ("snapshot", "unknown"):
            if damage == "snapshot": final.user.managerExp += 50
            else: final.DiscardUnknownFields()
            db.execute("UPDATE snapshots SET response=?", (final.SerializeToString(deterministic=True),))
        elif damage == "missing-attempt": db.execute("DELETE FROM main_live_attempts WHERE request_id=?", (IDS[0],))
        elif damage == "time": db.execute("UPDATE main_live_attempts SET started_time=1234 WHERE request_id=?", (IDS[0],))
        elif damage == "response": db.execute("UPDATE main_live_attempts SET response=? WHERE request_id=?", (b"malformed", IDS[0]))
        else: db.execute("UPDATE main_live_attempts SET seed='01' WHERE request_id=?", (IDS[0],))
    with pytest.raises(RuntimeError):
        real.verify_main_live_database(None, schema, receipt, expected_clock=clock)
