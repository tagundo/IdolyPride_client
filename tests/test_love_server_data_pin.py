"""Source-frozen upgraded payload pins do not accept donor or caller identities."""
from copy import deepcopy
import hashlib
import binascii
import importlib.util
import json
import os
from pathlib import Path
import struct
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("love_payload_pin", ROOT / "tools/love_server_data_pin.py")
pinmod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pinmod)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fixture(tmp_path, monkeypatch, *, wrong_file_record=False, duplicate_manifest_key=False):
    monkeypatch.setattr(pinmod, "ROOT", tmp_path)
    monkeypatch.setattr(pinmod, "PIN_PATH", tmp_path / "pin.json")
    sources = {}
    for index, name in enumerate(pinmod.SOURCE_FILES):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("component-" + str(index)).encode()
        path.write_bytes(raw)
        sources[name] = sha(raw)
    catalog = {"ruleset_sha256": "c" * 64, "master_version": "d" * 64,
        "schema_sha256": "e" * 64, "events": 6, "episodes": 72,
        "unique_adv_assets": 69, "observed_adv_assets": 68,
        "missing_adv_assets": ["love_2411_04_02"]}
    members = {name: b"{}" for name in pinmod.OVERLAY_MEMBERS}
    members["data/master-json/Item.json"] = b"[]"
    rows = [{"path": name, "bytes": len(raw), "sha256": sha(raw)} for name, raw in sorted(members.items())]
    overlay_path = tmp_path / pinmod.OVERLAY_PATH
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(overlay_path, "x") as archive:
        for name in sorted(pinmod.OVERLAY_MEMBERS):
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type, info.create_system = ZIP_STORED, 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])
    prepared_overlay = {"bytes": overlay_path.stat().st_size, "sha256": sha(overlay_path.read_bytes()),
                        "members": [row for row in rows if row["path"] in pinmod.OVERLAY_MEMBERS]}
    table_names = sorted(name[len("data/master-json/"):-5] for name in members
                         if name.startswith("data/master-json/") and name.endswith(".json"))
    manifest = {"schema": 1, "tables": {name: 0 for name in table_names if name != "LoveCatalog"},
        "files": deepcopy(rows), "love_catalog": catalog,
        "source_overlay": {"schema": 1, "operation": pinmod.POLICY,
            "base_sha256": pinmod.BASE_SHA256, "base_bytes": pinmod.BASE_BYTES,
            "component_sources": sources, "component_sources_sha256": sha(canonical(sources))}}
    if wrong_file_record:
        manifest["files"][0]["sha256"] = "f" * 64
    manifest_raw = canonical(manifest)
    if duplicate_manifest_key:
        manifest_raw = b'{"schema":1,"schema":1,' + manifest_raw[1:]
    members[pinmod.MANIFEST] = manifest_raw
    payload = tmp_path / "ServerData.zip"
    with ZipFile(payload, "x") as archive:
        for name, raw in sorted(members.items()):
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    output = {"bytes": payload.stat().st_size, "sha256": sha(payload.read_bytes()),
              "entries": len(members), "master_json_tables": len(table_names),
              "payload_manifest_sha256": sha(manifest_raw),
              "member_inventory_sha256": sha(canonical(rows)),
              "member_names": sorted(members), "master_json_table_names": table_names}
    proof = {"schema": 1, "status": "PASS", "operation": pinmod.POLICY,
             "base": dict(pinmod.base_pin(), entries=2, master_json_tables=1),
             "output": deepcopy(output), "component_sources": sources,
             "component_sources_sha256": sha(canonical(sources)), "prepared_overlay": prepared_overlay,
             "unchanged_old_entries": {"count": 1, "content_manifest_sha256": sha(canonical({
                 "data/master-json/Item.json": {"bytes": 2, "sha256": sha(b"[]"),
                     "compress_type": ZIP_STORED, "crc32": binascii.crc32(b"[]")}})),
                 "local_record_prefix_bytes": 10,
                 "local_record_prefix_sha256": sha(payload.read_bytes()[:10]), "verified": True},
             "added_members": [row for row in rows if row["path"] in pinmod.OVERLAY_MEMBERS],
             "replaced_members": [pinmod.MANIFEST],
             "love_catalog": catalog,
             "determinism": {"format": "zip-stored-append-v1", "new_entry_timestamp": "2000-01-01T00:00:00",
                             "old_compressed_records_preserved": True}}
    pin = {"schema": 1, "policy": pinmod.POLICY, "base_payload": pinmod.base_pin(),
           "component_sources": sources, "output": output,
           "prepared_overlay": dict(prepared_overlay, path=pinmod.OVERLAY_PATH),
           "preparation": {"source_commit": "1" * 40, "run_id": 123, "report_sha256": sha(canonical(proof) + b"\n")},
           "upgrade_proof": proof}
    pinmod.PIN_PATH.write_bytes(canonical(pin))
    return payload, pin, proof


def test_missing_new_pin_never_falls_back_to_base(tmp_path, monkeypatch):
    monkeypatch.setattr(pinmod, "PIN_PATH", tmp_path / "absent.json")
    assert pinmod.base_pin() == {"bytes": 191343014,
        "sha256": "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
    for operation in (pinmod.load_pin, pinmod.output_pin, pinmod.overlay_pin):
        with pytest.raises(ValueError, match="^love_server_data_pin_missing$"):
            operation()


def test_upgrade_receipt_and_zip_are_independently_bound(tmp_path, monkeypatch):
    payload, pin, proof = fixture(tmp_path, monkeypatch)
    assert pinmod.output_pin() == {key: pin["output"][key] for key in ("bytes", "sha256")}
    assert pinmod.verify_upgrade_proof(proof) == proof
    assert pinmod.verify_payload(payload) == pin["output"]
    assert pinmod.overlay_pin() == {key: pin["prepared_overlay"][key] for key in ("bytes", "sha256")}
    assert pinmod.verify_overlay(tmp_path / pinmod.OVERLAY_PATH) == proof["prepared_overlay"]
    # The first-preparation CI identity is provenance, not an equality demand on
    # every later native job. Neither the deterministic receipt nor ZIP has it.
    pin["preparation"]["run_id"] = 456
    pin["preparation"]["source_commit"] = "2" * 40
    pinmod.PIN_PATH.write_bytes(canonical(pin))
    assert pinmod.verify_upgrade_proof(proof) == proof
    returned = pinmod.load_pin()
    returned["output"]["sha256"] = "0" * 64
    assert pinmod.output_pin()["sha256"] == proof["output"]["sha256"]


def test_changed_component_source_requires_a_new_preparation(tmp_path, monkeypatch):
    payload, _, _ = fixture(tmp_path, monkeypatch)
    (tmp_path / "tools/build_server_payload.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="^love_server_data_source_differs$"):
        pinmod.verify_payload(payload)


@pytest.mark.parametrize("change", [
    lambda report: report.update(status="FAIL"),
    lambda report: report["base"].update(sha256="0" * 64),
    lambda report: report["unchanged_old_entries"].update(verified=False),
    lambda report: report["unchanged_old_entries"].update(local_record_prefix_sha256="0" * 64),
    lambda report: report["determinism"].update(old_compressed_records_preserved=False),
    lambda report: report["love_catalog"].update(observed_adv_assets=69, missing_adv_assets=[]),
    lambda report: report.update(source_commit="3" * 40),
])
def test_partial_or_different_success_report_is_not_a_verified_upgrade(tmp_path, monkeypatch, change):
    _, _, proof = fixture(tmp_path, monkeypatch)
    altered = deepcopy(proof)
    change(altered)
    with pytest.raises(ValueError, match="^love_server_data_"):
        pinmod.verify_upgrade_proof(altered)


def test_actual_final_zip_hash_cannot_be_replaced_by_a_report_claim(tmp_path, monkeypatch):
    payload, _, proof = fixture(tmp_path, monkeypatch)
    raw = bytearray(payload.read_bytes())
    raw[40] ^= 1
    payload.write_bytes(raw)
    assert pinmod.verify_upgrade_proof(proof) == proof
    with pytest.raises(ValueError, match="^love_server_data_payload_sha256_differs$"):
        pinmod.verify_payload(payload)


@pytest.mark.parametrize("option,error", [
    ("wrong_file_record", "love_server_data_manifest_files_differ"),
    ("duplicate_manifest_key", "love_server_data_json_duplicate"),
])
def test_even_a_whole_file_pin_must_match_unambiguous_manifest_inventory(tmp_path, monkeypatch, option, error):
    payload, _, _ = fixture(tmp_path, monkeypatch, **{option: True})
    with pytest.raises(ValueError, match="^" + error + "$"):
        pinmod.verify_payload(payload)


def test_zip_directory_bound_is_checked_before_member_allocation(tmp_path, monkeypatch):
    payload, pin, _ = fixture(tmp_path, monkeypatch)
    raw = bytearray(payload.read_bytes())
    position = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<H", raw, position + 8, 65535)
    struct.pack_into("<H", raw, position + 10, 65535)
    payload.write_bytes(raw)
    pin["output"]["sha256"] = sha(raw)
    pin["upgrade_proof"]["output"]["sha256"] = sha(raw)
    pin["preparation"]["report_sha256"] = sha(canonical(pin["upgrade_proof"]) + b"\n")
    pinmod.PIN_PATH.write_bytes(canonical(pin))
    with pytest.raises(ValueError, match="^love_server_data_zip_bound$"):
        pinmod.verify_payload(payload)


def test_pin_rejects_duplicate_keys_and_symlinks(tmp_path, monkeypatch):
    _, _, _ = fixture(tmp_path, monkeypatch)
    raw = pinmod.PIN_PATH.read_bytes()
    pinmod.PIN_PATH.write_bytes(b'{"schema":1,' + raw[1:])
    with pytest.raises(ValueError, match="^love_server_data_json_duplicate$"):
        pinmod.load_pin()
    target = tmp_path / "real-pin.json"
    pinmod.PIN_PATH.rename(target)
    pinmod.PIN_PATH.symlink_to(target)
    with pytest.raises(ValueError, match="^love_server_data_file_invalid$"):
        pinmod.load_pin()


def test_fifo_pin_is_rejected_without_waiting_for_a_writer(tmp_path, monkeypatch):
    path = tmp_path / "fifo"
    os.mkfifo(path)
    monkeypatch.setattr(pinmod, "PIN_PATH", path)
    with pytest.raises(ValueError, match="^love_server_data_file_invalid$"):
        pinmod.load_pin()


def test_overlay_has_its_own_frozen_whole_file_identity(tmp_path, monkeypatch):
    _, pin, proof = fixture(tmp_path, monkeypatch)
    overlay = tmp_path / pinmod.OVERLAY_PATH
    raw = bytearray(overlay.read_bytes())
    raw[40] ^= 1
    overlay.write_bytes(raw)
    assert pinmod.verify_upgrade_proof(proof) == proof
    with pytest.raises(ValueError, match="^love_server_data_overlay_sha256_differs$"):
        pinmod.verify_overlay(overlay)


def test_overlay_pin_cannot_point_outside_checked_in_public_location(tmp_path, monkeypatch):
    _, pin, _ = fixture(tmp_path, monkeypatch)
    pin["prepared_overlay"]["path"] = "../outside.zip"
    pinmod.PIN_PATH.write_bytes(canonical(pin))
    with pytest.raises(ValueError, match="^love_server_data_overlay_pin_differs$"):
        pinmod.load_pin()
