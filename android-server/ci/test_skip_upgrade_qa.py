"""The preserving SKIP driver must account for every private-state change."""
from copy import deepcopy
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import qa_skip_upgrade as probe
from idoly_local.schema import Schema
from idoly_local.state import State


@pytest.fixture
def case(tmp_path, monkeypatch):
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    state = State(tmp_path / "synthetic.db")
    state.save_snapshot("sandbox", b"synthetic-opaque-snapshot", schema.fingerprint)
    state.login("sandbox")
    with state.connect() as db:
        db.execute("CREATE TABLE future_ledger (identity TEXT PRIMARY KEY, receipt BLOB)")
        db.execute("INSERT INTO future_ledger VALUES (?,?)", ("receipt", b"preserved"))
        db.execute("INSERT INTO main_live_attempts VALUES(?,?,?,?,?,?,?,?,?,?)", (
            "sandbox", "7", "old", probe.START, schema.fingerprint, "master", "live-v5", "0", 123, b"old"))
    def backup(_qa, directory):
        path = Path(directory) / "state.db"
        with state.connect() as source, sqlite3.connect(path) as target:
            source.backup(target)
        path.chmod(0o600)
        return path
    monkeypatch.setattr(probe.q, "_copy_private_database", backup)
    before = probe.protected_database(object())
    body = schema.response_type(probe.START)(questId="qt-main-1-001-01").SerializeToString()
    receipt = {"request_ids": list(probe.IDS), "request_sha256": "a" * 64,
        "started_times": [12345, 12346], "first_response_sha256": probe.hashlib.sha256(body).hexdigest(),
        "replay_response_sha256": probe.hashlib.sha256(body).hexdigest(),
        "schema_sha256": schema.fingerprint, "master_version": "master", "ruleset": "live-v5"}
    with state.connect() as db:
        for index, identity in enumerate(probe.IDS):
            db.execute("INSERT INTO main_live_attempts VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "sandbox", identity, receipt["request_sha256"], probe.START, schema.fingerprint,
                "master", "live-v5", str(index), receipt["started_times"][index], body))
    after = probe.protected_database(object())
    return schema, before, after, receipt


def test_only_exact_two_new_skip_attempts_and_snapshot_body_may_change(case):
    schema, before, after, receipt = case
    probe.assert_database_preserved(schema, before, after, receipt)
    assert "future_ledger" in before["rows"] and "snapshots" not in before["rows"]


@pytest.mark.parametrize("damage", ("future-table", "session", "schema", "snapshot-schema",
    "old-attempt", "missing-new", "extra-new", "new-hash", "new-seed", "new-time", "new-response"))
def test_sql_preservation_rejects_unrelated_losses_or_unaccounted_attempts(case, damage):
    schema, before, actual, receipt = case
    after = deepcopy(actual)
    if damage == "future-table":
        after["rows"]["future_ledger"] = [("receipt", b"lost")]
    elif damage == "session":
        after["rows"]["sessions"] = []
    elif damage == "schema":
        after["definitions"] = after["definitions"][:-1]
    elif damage == "snapshot-schema":
        after["snapshot_metadata"] = [("sandbox", "other-schema")]
    else:
        rows = after["rows"]["main_live_attempts"]
        columns = after["columns"]["main_live_attempts"]
        request_id = columns.index("request_id")
        row = next(i for i, values in enumerate(rows) if values[request_id] == probe.IDS[0])
        if damage == "old-attempt":
            row = next(i for i, values in enumerate(rows) if values[request_id] == "7")
            values = list(rows[row])
            values[columns.index("seed")] = "9"
            rows[row] = tuple(values)
        elif damage == "missing-new":
            del rows[row]
        elif damage == "extra-new":
            values = list(rows[row]); values[request_id] = "8"; rows.append(tuple(values))
        else:
            field, value = {"new-hash": ("request_sha256", "b" * 64), "new-seed": ("seed", "01"),
                "new-time": ("started_time", 0), "new-response": ("response", b"malformed")}[damage]
            values = list(rows[row]); values[columns.index(field)] = value; rows[row] = tuple(values)
    with pytest.raises(RuntimeError):
        probe.assert_database_preserved(schema, before, after, receipt)


@pytest.mark.parametrize("condition", ("stopped", "pid-remains", "port-remains"))
def test_failure_cleanup_requires_owned_pid_absence_and_closed_forwarded_server(monkeypatch, condition):
    commands = []
    def adb(*args, **kwargs):
        commands.append((args, kwargs))
        if args == ("shell", "am", "force-stop", probe.q.PACKAGE):
            return ""
        assert args == ("shell", "pidof", "-s", probe.q.PACKAGE)
        return "123" if condition == "pid-remains" else ""
    waits = []
    def wait(schema, port, **kwargs):
        waits.append((schema, port, kwargs))
        if condition == "port-remains":
            raise RuntimeError("synthetic private failure text")
    monkeypatch.setattr(probe.q, "wait_server", wait)
    device = SimpleNamespace(adb=adb)
    if condition == "port-remains":
        with pytest.raises(RuntimeError):
            probe.stop_owned_after_failure(device, "schema", 12345)
    else:
        assert probe.stop_owned_after_failure(device, "schema", 12345) is (condition == "stopped")
    assert commands[0][0][-1] == probe.q.PACKAGE
    assert all(item[1] == {"check": False} for item in commands)
    assert bool(waits) is (condition != "pid-remains")
    assert not waits or waits[0][2] == {"expected": False, "timeout": 20}
