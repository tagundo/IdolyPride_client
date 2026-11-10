"""Do not report native appearance persistence before restart/DB checks pass."""
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3

import pytest

from idoly_local import appearance_qa
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
    final.user.name = "Local preserved manager"
    final.balance.freeBalance, final.balance.paidBalance = 130, 7
    for suffix in ("a", "b"):
        final.characters.add(characterId="char-" + suffix, favoriteCostumeId="cos-" + suffix,
                             favoriteHairId="hair-" + suffix)
        final.costumes.add(costumeId="cos-" + suffix, checked=True, obtainedTime=123456)
        final.hairs.add(hairId="hair-" + suffix, checked=True)
    final.MergeFromString(qa.QA_UNKNOWN_PB)
    receipt = {"snapshot_sha256": hashlib.sha256(final.SerializeToString(deterministic=True)).hexdigest(),
               "costume_rows": 2, "hair_rows": 2, "character_rows": 2}
    clock = [(b"original raw lesson clock", schema.fingerprint)]
    preserved = {"identity": "original", "settings": "original"}
    calls, checks = [], []

    def rpc(received_schema, port, path, token=None, request=None):
        assert received_schema is schema and port == 12345 and token == "local-original-session"
        assert device.running
        calls.append((device.starts, path))
        return final

    def run(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and master_dir == tmp_path and label == "Android native"
        assert device.starts == 1
        invoke("/api.Costume/SetCostume", schema.request_type("/api.Costume/SetCostume")())
        return dict(receipt)

    def retries(received_schema, invoke, master_dir, saved):
        assert received_schema is schema and device.starts == 2 and master_dir == tmp_path
        assert saved == receipt
        appearance_qa.assert_appearance_snapshot(schema,
            invoke("/api.User/Get", schema.request_type("/api.User/Get")()), saved)
        invoke("/api.Costume/CheckBulk", schema.request_type("/api.Costume/CheckBulk")())

    def wait(received_schema, port, *, expected=True, timeout):
        assert received_schema is schema and port == 12345 and device.running == expected

    def verify_preserved(received_device, expected):
        assert received_device is device and not device.process
        if preserved != expected:
            raise RuntimeError("Appearance changed preserved identity/settings")
        checks.append(("identity/settings", device.starts))

    def database(received_device, received_schema, saved=None, *, expected_clock=None):
        assert received_device is device and received_schema is schema and not device.process
        if saved is not None:
            assert saved == receipt
            if expected_clock != clock[0]:
                raise RuntimeError("Appearance changed raw persistent lesson clock")
            appearance_qa.assert_appearance_snapshot(schema, final, saved)
        checks.append(("database", device.starts))
        return clock[0]

    monkeypatch.setattr(qa, "rpc", rpc)
    monkeypatch.setattr(qa, "wait_server", wait)
    monkeypatch.setattr(qa, "verify_upgrade_database", verify_preserved)
    monkeypatch.setattr(qa, "verify_appearance_database", database)
    monkeypatch.setattr(appearance_qa, "run_appearance_checks", run)
    monkeypatch.setattr(appearance_qa, "assert_appearance_retries", retries)
    return schema, device, final, receipt, clock, preserved, calls, checks, tmp_path


def exercise(native):
    schema, device, _final, _receipt, _clock, _preserved, _calls, _checks, master = native
    return qa.exercise_appearance_checks(device, schema, 12345, "local-original-session", master,
                                         600, {"identity": "original", "settings": "original"})


def test_restart_uses_new_appearance_receipt_and_original_session_before_emitting_flags(native):
    _schema, device, _final, receipt, _clock, _preserved, calls, checks, _master = native
    result = exercise(native)
    assert result["appearance"] == receipt
    assert all(value is True for key, value in result.items() if key != "appearance")
    assert calls == [(1, "/api.Costume/SetCostume"), (2, "/api.User/Get"), (2, "/api.Costume/CheckBulk")]
    assert checks == [("database", 0), ("identity/settings", 1), ("database", 1),
                      ("identity/settings", 2), ("database", 2)]
    assert device.starts == 2 and not device.process
    assert "local-original-session" not in json.dumps(result)


@pytest.mark.parametrize("damage", ("checked", "preference", "duplicate-owned", "wallet", "identity", "settings", "clock"))
def test_lost_or_unrelated_changes_cannot_produce_preservation_success_flags(native, monkeypatch, damage):
    _schema, device, final, _receipt, clock, preserved, _calls, _checks, _master = native
    capture = device.capture

    def corrupted(stage):
        capture(stage)
        if stage != "37-appearance-completed":
            return
        if damage == "checked":
            final.costumes[0].checked = False
        elif damage == "preference":
            final.characters[0].favoriteHairId = "lost-selection"
        elif damage == "duplicate-owned":
            final.hairs.add().CopyFrom(final.hairs[0])
        elif damage == "wallet":
            final.balance.freeBalance += 1
        elif damage == "clock":
            clock[0] = (b"changed raw lesson clock", clock[0][1])
        else:
            preserved[damage] = "changed"

    monkeypatch.setattr(device, "capture", corrupted)
    with pytest.raises(RuntimeError, match="Appearance|appearance"):
        exercise(native)
    assert device.starts == 1 and not device.process


def test_real_stopped_database_verifier_rejects_clock_or_schema_changes(native, monkeypatch):
    schema, device, final, receipt, clock, _preserved, _calls, _checks, master = native
    path = master / "native-state.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE snapshots(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE profile_lesson_progress(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("sandbox", final.SerializeToString(), schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES(?,?,?)", ("sandbox", *clock[0]))
    spec = spec_from_file_location("appearance_database_qa", Path(__file__).with_name("qa_emulator.py"))
    real = module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(real, "_copy_private_database", lambda received, directory: path)
    assert real.verify_appearance_database(device, schema, receipt, expected_clock=clock[0]) == clock[0]
    with pytest.raises(RuntimeError, match="raw persistent lesson clock"):
        real.verify_appearance_database(device, schema, receipt, expected_clock=(b"different", schema.fingerprint))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE snapshots SET schema_sha256='wrong-schema'")
    with pytest.raises(RuntimeError, match="not persisted"):
        real.verify_appearance_database(device, schema, receipt, expected_clock=clock[0])
