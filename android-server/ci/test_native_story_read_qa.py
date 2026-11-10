"""Guard the installed server's final story-read restart/receipt boundary."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from idoly_local import story_read_qa
from idoly_local.lesson_qa import _clock_digest
from idoly_local.schema import Schema
from test_tutorial_continuation_qa import Device, qa


@pytest.fixture
def native(tmp_path, monkeypatch):
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    device = Device()
    final = schema.response_type("/api.User/Get")()
    final.balance.freeBalance, final.balance.paidBalance = 30, 7
    final.stories.add(storyId="public-event", statusType=2)
    final.stories.add(storyId="public-extra", statusType=2)
    final.MergeFromString(qa.QA_UNKNOWN_PB)
    progress = schema.response_type("/api.Home/Enter")().lessonProgress
    progress.stepRewardGold, progress.stepRewardManagerExp, progress.stepRewardCardEnhanceItem = 5, 8, 3
    progress.currentAreaId, progress.lastReceiveTime = "area-main-001", 100000
    progress.maxRewardTime = progress.lastReceiveTime + 12 * 60 * 60 * 1000
    receipt = {"snapshot_sha256": hashlib.sha256(final.SerializeToString(deterministic=True)).hexdigest(),
               "clock_sha256": _clock_digest(progress), "free_stone_after": 30,
               "paid_stone_before": 7, "story_rows_after": 2}
    calls, checks, clock = [], [], (progress.SerializeToString(), schema.fingerprint)
    def rpc(received_schema, port, path, token=None, request=None):
        assert received_schema is schema and port == 12345 and token == "local-unchanged-session"
        assert device.running
        calls.append((device.starts, path))
        return final
    def run(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and master_dir == tmp_path and label == "Android native"
        assert device.starts == 1
        invoke("/api.Story/ReadEvent", schema.request_type("/api.Story/ReadEvent")(isLast=False))
        return dict(receipt)
    def retries(received_schema, invoke, master_dir, saved):
        assert device.starts == 2 and saved == receipt and master_dir == tmp_path
        story_read_qa.assert_story_read_snapshot(received_schema, invoke("/api.User/Get", schema.request_type("/api.User/Get")()), saved)
        invoke("/api.Story/Read", schema.request_type("/api.Story/Read")(isLast=True))
    def wait(received_schema, port, *, expected=True, timeout):
        assert received_schema is schema and port == 12345 and device.running == expected
    def preserved(received_device, original):
        assert received_device is device and original == {"identity": "unchanged"} and not device.process
        checks.append(("identity", device.starts))
    def database(received_device, received_schema, saved=None, *, expected_clock=None):
        assert received_device is device and received_schema is schema and not device.process
        if saved is not None:
            assert expected_clock == clock and saved == receipt
            story_read_qa.assert_story_read_snapshot(schema, final, saved)
        checks.append(("database", device.starts))
        return clock
    monkeypatch.setattr(qa, "rpc", rpc)
    monkeypatch.setattr(qa, "wait_server", wait)
    monkeypatch.setattr(qa, "verify_upgrade_database", preserved)
    monkeypatch.setattr(qa, "verify_story_read_database", database)
    monkeypatch.setattr(story_read_qa, "run_story_read_checks", run)
    monkeypatch.setattr(story_read_qa, "assert_story_read_retries", retries)
    return schema, device, final, receipt, clock, calls, checks, tmp_path


def exercise(native):
    schema, device, _final, _receipt, _clock, _calls, _checks, master = native
    return qa.exercise_story_read_checks(device, schema, 12345, "local-unchanged-session", master, 600,
                                          {"identity": "unchanged"})


def test_native_story_reads_verify_new_receipt_and_original_session_after_restart(native):
    _schema, device, _final, receipt, _clock, calls, checks, _master = native
    result = exercise(native)
    assert result["story_read"] == receipt
    assert all(value is True for key, value in result.items() if key != "story_read")
    assert calls == [(1, "/api.Story/ReadEvent"), (2, "/api.User/Get"), (2, "/api.Story/Read")]
    assert checks == [("database", 0), ("identity", 1), ("database", 1),
                      ("identity", 2), ("database", 2)]
    assert device.starts == 2 and not device.process
    assert "local-unchanged-session" not in json.dumps(result)


def test_native_story_read_lost_progress_cannot_emit_persistence_flags(native, monkeypatch):
    _schema, device, final, _receipt, _clock, _calls, _checks, _master = native
    capture = device.capture
    def changed(stage):
        capture(stage)
        if stage == "30-story-read-completed":
            final.stories[0].statusType = 1
    monkeypatch.setattr(device, "capture", changed)
    with pytest.raises(RuntimeError, match="snapshot"):
        exercise(native)


def test_native_story_read_checks_raw_saved_clock_not_only_home_projection(native, monkeypatch):
    schema, device, final, receipt, clock, _calls, _checks, master = native
    # Exercise the real stopped-DB verifier instead of the caller stub.
    database = master / "native-state.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE snapshots(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE profile_lesson_progress(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("sandbox", final.SerializeToString(), schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES(?,?,?)", ("sandbox", *clock))
    monkeypatch.setattr(qa, "_copy_private_database", lambda received, directory: database)
    # The unpatched function is available from a fresh module instance.
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("story_read_database_qa", Path(__file__).with_name("qa_emulator.py"))
    real = module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(real, "_copy_private_database", lambda received, directory: database)
    assert real.verify_story_read_database(device, schema, receipt, expected_clock=clock) == clock
    with pytest.raises(RuntimeError, match="raw persistent lesson clock"):
        real.verify_story_read_database(device, schema, receipt, expected_clock=(b"changed", schema.fingerprint))
    with sqlite3.connect(database) as db:
        db.execute("UPDATE snapshots SET schema_sha256='wrong'")
    with pytest.raises(RuntimeError, match="not persisted"):
        real.verify_story_read_database(device, schema, receipt, expected_clock=clock)
