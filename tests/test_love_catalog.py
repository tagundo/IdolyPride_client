"""Pinned reference/proof and synthetic integrity/cache contracts; no game calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local import love_catalog as catalog
from idoly_local.schema import Schema

ROOT = Path(__file__).resolve().parents[1]


def test_original_schema_fingerprint_is_distinct_from_original_file_hash():
    descriptor = ROOT / "data/protocol/idolypride-6.1.1.pb"
    assert descriptor.is_file(), "Focused CI must prepare the pinned original descriptor"
    assert hashlib.sha256(descriptor.read_bytes()).hexdigest() == catalog.RAW_DESCRIPTOR_SHA256
    assert Schema.from_descriptor_set(descriptor).fingerprint == catalog.SCHEMA_SHA256
    assert catalog.RAW_DESCRIPTOR_SHA256 != catalog.SCHEMA_SHA256


def test_exact_prepared_reference_and_original_adv_proof_are_six_events_and_honest_partial():
    reference, proof = catalog._reference(ROOT / "data/love-reference.json", ROOT / "data/love-adv-proof.json")
    assert len(reference["reference"]["sources"]) == 12
    assert reference["reference"]["commit"] == catalog.REFERENCE_COMMIT
    assert len(reference["reference"]["license_sha256"]) == 64
    assert reference["policy"]["score_bonus_grants"] is False
    assert reference["policy"]["routes"] == "inferred_reference_not_official_capture"
    assert set(reference["events"]) == set(catalog.EVENT_IDS)
    assert sum(len(row["route"]["episodes"]) for row in reference["events"].values()) == 71
    assert proof["story_count"] == 72 and proof["unique_asset_count"] == 69
    assert len(proof["assets"]) == proof["available_asset_count"] == 68
    assert proof["missing_asset_ids"] == ["love_2411_04_02"]
    assert "love_2411_04_02" not in proof["assets"]
    assert "love-event-story-love-24-1114-004-bad" not in reference["events"]["love-24-1114"]["route"]["episodes"]
    assert proof["limits"] == {"raw_dialogue_bundled": False, "official_weights_verified": False,
                               "unknown_branches_inferred_as_verified": False}
    assert (ROOT / "data/love-adv-proof.json").stat().st_size <= 12 * 1024
    for row in proof["assets"].values():
        assert len(row["sha256"]) == 64 and type(row["bytes"]) is int and row["bytes"] > 0
        assert all(type(count) is int and 1 <= count <= 32 for count in row["choices"] + row["conditions"])


@pytest.mark.parametrize("name,expected", [("love-reference.json", catalog.REFERENCE_SHA256),
                                           ("love-adv-proof.json", catalog.ADV_PROOF_SHA256)])
def test_modified_reference_or_proof_fails_before_preparation(tmp_path, name, expected):
    path = tmp_path / name
    path.write_bytes((ROOT / "data" / name).read_bytes() + b" ")
    with pytest.raises(catalog.LoveCatalogError, match="love_catalog_source_changed"):
        catalog._load_source(path, expected, 128 * 1024)


@pytest.mark.parametrize("table", catalog.LOVE_TABLES)
def test_original_pack_version_count_and_unique_identity_gates(table):
    digest, count = catalog.LOVE_MASTER_PINS[table]
    rows = [{"loveId": catalog.EVENT_IDS[0], "id": "synthetic-" + str(i), "level": i + 1} for i in range(count)]
    before = deepcopy(rows)
    catalog.validate_love_master(table, catalog.MASTER_VERSION, digest, rows)
    assert rows == before
    for version, sha, invalid in (("wrong", digest, rows), (catalog.MASTER_VERSION, "0" * 64, rows),
                                  (catalog.MASTER_VERSION, digest, rows[:-1])):
        with pytest.raises(catalog.LoveCatalogError):
            catalog.validate_love_master(table, version, sha, invalid)
    if count > 1:
        rows[-1] = dict(rows[0])
        with pytest.raises(catalog.LoveCatalogError):
            catalog.validate_love_master(table, catalog.MASTER_VERSION, digest, rows)


def test_default_unprepared_settings_projection_never_throws_or_creates_files(tmp_path):
    before = list(tmp_path.iterdir())
    assert catalog.event_catalog(tmp_path) == {"schema": 1, "available": False, "events": [],
        "ruleset_sha256": None, "reason_code": "love_catalog_unavailable"}
    assert list(tmp_path.iterdir()) == before
    with pytest.raises(catalog.LoveCatalogError, match="love_catalog_schema_changed"):
        catalog.load_love_catalog(SimpleNamespace(fingerprint="wrong"), tmp_path)


def _synthetic_record(directory):
    directory.mkdir()
    (directory / "!version.txt").write_text(catalog.MASTER_VERSION)
    for name in catalog.SOURCE_TABLES:
        (directory / (name + ".json")).write_text("[]")
    events = {}
    for index, event_id in enumerate(catalog.EVENT_IDS):
        events[event_id] = {"loveId": event_id, "name": "Synthetic " + str(index), "description": "reference test",
            "startTime": 1700000000000 + index, "source_grade": catalog.SOURCE_GRADE,
            "inference_status": catalog.INFERENCE_STATUS,
            "levels": [{"level": i} for i in range(12 if index == 0 else 9)],
            "episodes": {"synthetic-" + str(i): {} for i in range(12)}}
    value = {"schema": 1, "schema_sha256": catalog.SCHEMA_SHA256, "master_version": catalog.MASTER_VERSION,
        "reference_sha256": catalog.REFERENCE_SHA256, "adv_proof_sha256": catalog.ADV_PROOF_SHA256,
        "primary_packs": {name: {"sha256": pin[0], "rows": pin[1]} for name, pin in catalog.LOVE_MASTER_PINS.items()},
        "source_files": {name + ".json": hashlib.sha256(b"[]").hexdigest() for name in catalog.SOURCE_TABLES},
        "events": events, "policy": {"synthetic_integrity_fixture": True}}
    value["ruleset_sha256"] = hashlib.sha256(catalog._canonical(value)).hexdigest()
    (directory / "LoveCatalog.json").write_bytes(catalog._canonical(value))
    return value


def test_runtime_integrity_cache_revalidates_replaced_master_and_returns_private_copies(tmp_path, monkeypatch):
    directory = tmp_path / "master-json"
    expected = _synthetic_record(directory)
    calls = []
    original = catalog._hash
    def hashed(path):
        calls.append(path.name)
        return original(path)
    monkeypatch.setattr(catalog, "_hash", hashed)
    schema = SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256)
    first = catalog.load_love_catalog(schema, directory)
    assert first == expected and len(calls) == len(catalog.SOURCE_TABLES)
    first["events"].clear()
    assert len(catalog.load_love_catalog(schema, directory)["events"]) == 6
    assert len(calls) == len(catalog.SOURCE_TABLES)
    options = catalog.event_catalog(tmp_path)
    assert options["available"] and len(options["events"]) == 6
    assert len(calls) == len(catalog.SOURCE_TABLES)
    for row in options["events"]:
        assert row["supported"] and row["source_grade"] == catalog.SOURCE_GRADE
        assert row["original_end_time_ms"] is row["original_duration_ms"] is None
    (directory / "LoveLevel.json").write_text("[{}]")
    with pytest.raises(catalog.LoveCatalogError, match="love_catalog_master_changed"):
        catalog.load_love_catalog(schema, directory)
    assert catalog.event_catalog(tmp_path)["available"] is False


def test_catalog_mutation_without_matching_ruleset_hash_is_rejected(tmp_path):
    directory = tmp_path / "master-json"
    value = _synthetic_record(directory)
    value["events"][catalog.EVENT_IDS[0]]["name"] = "tampered"
    (directory / "LoveCatalog.json").write_bytes(catalog._canonical(value))
    with pytest.raises(catalog.LoveCatalogError, match="love_catalog_ruleset_changed"):
        catalog.load_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256), directory)
    assert not catalog.event_catalog(tmp_path)["available"]


def test_build_rejects_wrong_protocol_before_any_original_master_read(tmp_path):
    with pytest.raises(catalog.LoveCatalogError, match="love_catalog_schema_changed"):
        catalog.build_love_catalog(SimpleNamespace(fingerprint="wrong"), tmp_path, pack_proofs={})
    assert list(tmp_path.iterdir()) == []
