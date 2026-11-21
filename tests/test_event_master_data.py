"""Public event master export is explicit and does not import account captures."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import pytest

from test_build_server_payload import payload


@pytest.fixture(scope="module")
def evidence():
    return json.loads((Path(__file__).parent / "fixtures/event-read-master-data.v1.json").read_text())


def values_for(evidence, table):
    pin = evidence["tables"][table]
    return [{pin["identity_field"]: f"synthetic-public-row-{i}"} for i in range(pin["rows"])]


def test_event_read_export_is_optional_and_preserves_existing_table_contract():
    before = payload.TABLES
    assert payload.payload_tables() is before and len(before) == 55
    assert set(before).intersection(payload.EVENT_READ_TABLES) == {"Condition", "EventMission"}
    selected = payload.payload_tables(True)
    assert selected[:55] == before
    assert selected[55:] == tuple(table for table in payload.EVENT_READ_TABLES if table not in before)
    assert len(selected) == len(set(selected)) == 58 and payload.TABLES == before
    for value in (1, "true", None):
        with pytest.raises(TypeError):
            payload.payload_tables(value)


@pytest.mark.parametrize("table", payload.EVENT_READ_TABLES)
def test_public_table_pins_match_independently_archived_evidence(evidence, table):
    pin = evidence["tables"][table]
    rows = values_for(evidence, table)
    before = deepcopy(rows)
    payload.validate_event_master(table, evidence["master_version"], pin["pack_sha256"], rows)
    assert rows == before


@pytest.mark.parametrize("changed", ["table", "version", "pack", "count", "empty", "missing", "ambiguous"])
def test_wrong_public_data_fails_before_preparation_without_mutation(evidence, changed):
    table = "PhotoAbility"
    pin, rows = evidence["tables"][table], values_for(evidence, table)
    version, digest = evidence["master_version"], pin["pack_sha256"]
    if changed == "table": table = "UserPhoto"
    elif changed == "version": version = "other-public-master"
    elif changed == "pack": digest = "0" * 64
    elif changed == "count": rows.pop()
    elif changed == "empty": rows[0]["id"] = ""
    elif changed == "missing": rows[0] = {"other": "value"}
    else: rows[-1]["id"] = rows[0]["id"]
    before = deepcopy(rows)
    with pytest.raises(ValueError):
        payload.validate_event_master(table, version, digest, rows)
    assert rows == before


@pytest.mark.parametrize("table", ["QuestCharacterAdvantage", "LiveBonusGroup"])
def test_group_rows_keep_duplicate_group_identity(evidence, table):
    pin, rows = evidence["tables"][table], values_for(evidence, table)
    field = pin["identity_field"]
    rows[-1][field] = rows[0][field]
    payload.validate_event_master(table, evidence["master_version"], pin["pack_sha256"], rows)
    if table == "LiveBonusGroup":
        rows[0] = {"id": rows[0]["groupId"]}
        with pytest.raises(ValueError):
            payload.validate_event_master(table, evidence["master_version"], pin["pack_sha256"], rows)


def group_schema():
    file = descriptor_pb2.FileDescriptorProto(name="public-live-bonus-group.proto", package="master", syntax="proto3")
    group = file.message_type.add(name="LiveBonusGroup")
    group.field.add(name="groupId", number=1, type=9)
    group.field.add(name="liveBonusIds", number=2, type=9, label=3)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return SimpleNamespace(pool=pool), message_factory.GetMessageClass(pool.FindMessageTypeByName("master.LiveBonusGroup"))


def test_sqlcipher_export_retains_actual_group_field_and_source_order_without_neighbor_reads(evidence, tmp_path, monkeypatch):
    sqlcipher = pytest.importorskip("sqlcipher3.dbapi2")
    schema, message = group_schema()
    sample = evidence["live_bonus_group_sample"]
    raw = base64.b64decode(sample["protobuf_b64"], validate=True)
    assert hashlib.sha256(raw).hexdigest() == sample["protobuf_sha256"]
    first = message.FromString(raw)
    assert first.groupId and first.liveBonusIds
    second = message(groupId=first.groupId, liveBonusIds=["synthetic-second-effect"])
    root = tmp_path / "public"
    root.mkdir()
    original = root / "public.db"
    pack = SimpleNamespace(fileName=original.name, cryptoKey="45" * 32)
    db = sqlcipher.connect(str(original))
    db.execute(f'PRAGMA key="x\'{pack.cryptoKey}\'"')
    db.execute('CREATE TABLE "LiveBonusGroup"(data BLOB NOT NULL)')
    db.executemany('INSERT INTO "LiveBonusGroup" VALUES(?)', [(raw,), (second.SerializeToString(),)])
    db.commit()
    db.close()
    private = root / "dream-private-catalog.json"
    private.write_bytes(b"synthetic-private-capture-never-read")
    before = original.read_bytes()
    normal_open = Path.open

    def guard(path, *args, **kwargs):
        assert path != private, "A public table exporter read a private neighboring capture"
        return normal_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    rows = payload.decode_master_table(schema, sqlcipher, root, pack, "LiveBonusGroup")
    assert rows == [{"groupId": first.groupId, "liveBonusIds": list(first.liveBonusIds)},
                    {"groupId": first.groupId, "liveBonusIds": ["synthetic-second-effect"]}]
    assert all("id" not in row for row in rows)
    assert original.read_bytes() == before and private.stat().st_size > 0


def test_decoder_cannot_open_outside_archive_or_unselected_account_table(tmp_path):
    class NoDatabase:
        def connect(self, *_args, **_kwargs):
            raise AssertionError("Invalid archive metadata reached SQLite")
    outside = tmp_path / "private.archive"
    outside.write_bytes(b"synthetic-account-data")
    root = tmp_path / "public"
    root.mkdir()
    pack = SimpleNamespace(fileName="../private.archive", cryptoKey="45" * 32)
    with pytest.raises(ValueError):
        payload.decode_master_table(None, NoDatabase(), root, pack, "LiveBonusGroup")
    with pytest.raises(ValueError):
        payload.decode_master_table(None, NoDatabase(), root, pack, "UserPhoto")
