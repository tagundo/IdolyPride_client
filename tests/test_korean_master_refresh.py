"""The Korean refresh is bounded to text, keeps the frozen JP cohort and sorts."""
from copy import deepcopy
import json
import os
from pathlib import Path
from zipfile import ZipFile, ZipInfo
import zlib

import pytest

from tools import korean_server_data_pin as frozen
from tools.prepare_korean_master_data import text_changes


def test_checked_in_refresh_preserves_every_non_korean_member():
    pin = frozen.load_pin()
    original = frozen.latest().load_pin()["output"]
    assert pin["source"]["revision"] == "11ecceb451833b81c614f666a3667be0d08e0281"
    assert len(pin["source"]["files"]) == 90
    assert len(pin["semantic_proof"]["changed_source_files"]) == 14
    old = {row["path"]: row for row in original["members"]}
    current = {row["path"]: row for row in pin["output"]["members"]}
    assert old.keys() <= current.keys()
    assert {name for name in old if old[name] != current[name]} == frozen.METADATA
    assert pin["preservation"]["unchanged_members"] == 566
    assert pin["preservation"]["removed_paths"] == []
    assert len(pin["preservation"]["added_paths"]) == 26
    for mode in ("normal", "media"):
        proof = pin["semantic_proof"]["modes"][mode]
        assert proof["translated_tables"] == 89
        assert len(proof["sorts"]) == proof["sort_variants"] == 9
        for row in proof["tables"].values():
            assert row["nontext_fields_preserved"] is True
            assert row["expected_rows_sha256"] == row["readback_rows_sha256"]
        for row in proof["sorts"].values():
            assert row["nonorder_fields_preserved"] is True
            assert row["expected_rows_sha256"] == row["readback_rows_sha256"]
    assert pin["semantic_proof"]["raw_compile_repeat_byte_identity_claim"] is False


def test_checked_in_overlay_is_byte_pinned_and_has_only_allowed_members():
    result = frozen.verify_overlay()
    assert result["members"]
    assert all(frozen.allowed_overlay(row["path"]) for row in result["members"])
    assert {row["path"] for row in result["members"]} == (
        frozen.METADATA | set(frozen.load_pin()["preservation"]["added_paths"]))


@pytest.mark.parametrize("name", ["../data/original-master/languages/ko/coverage.json",
    "data/original-master/languages/en/coverage.json", "data/master-json/Card.json",
    "data/original-master/master-tag.json", "data/original-master/response.pb",
    "data/account.json", "data/original-master/assets/master/Card.db"])
def test_overlay_rejects_unrelated_or_unsafe_members(tmp_path, name):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(name, b"data")
    with ZipFile(path) as archive, pytest.raises(ValueError, match="korean_zip_member_invalid"):
        frozen.archive_rows(archive, overlay=True)


def test_zip_rejects_case_aliases_and_symbolic_members(tmp_path):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as archive:
        name = next(iter(frozen.METADATA))
        archive.writestr(name, b"a")
        archive.writestr(name.upper(), b"b")
    with ZipFile(path) as archive, pytest.raises(ValueError, match="duplicate"):
        frozen.archive_rows(archive, overlay=True)
    path.unlink()
    with ZipFile(path, "w") as archive:
        info = ZipInfo(name)
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, b"target")
    with ZipFile(path) as archive, pytest.raises(ValueError, match="member_invalid"):
        frozen.archive_rows(archive, overlay=True)


@pytest.mark.parametrize("field,value", [("id", "changed"), ("order", 8),
    ("assetId", "another-asset"), ("isUserUnavailable", True)])
def test_independent_semantic_audit_rejects_nontext_changes(field, value):
    before = [{"id": "card-a", "name": "日本語", "order": 7,
               "assetId": "asset-a", "isUserUnavailable": False}]
    after = deepcopy(before)
    after[0][field] = value
    with pytest.raises(ValueError, match="nontext"):
        text_changes(before, after)


def test_independent_semantic_audit_accepts_only_string_text_leaf_changes():
    before = [{"id": "a", "name": "日本語", "branchChoices": [{"text": "選択"}], "texts": ["元"]}]
    after = [{"id": "a", "name": "한국어", "branchChoices": [{"text": "선택"}], "texts": ["번역"]}]
    assert text_changes(before, after) == {"name": 1, "text": 1, "texts": 1}
    with pytest.raises(ValueError, match="count"):
        text_changes(before, after + [after[0]])


def test_pin_rejects_changed_source_and_refresh_proof(tmp_path, monkeypatch):
    pin = frozen.load_pin()
    wrong = deepcopy(frozen.refresh_proof(pin))
    wrong["output"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="proof_differs"):
        frozen.verify_refresh_proof(wrong)
    path = tmp_path / "pin.json"
    pin["source"]["revision"] = "f" * 40
    path.write_bytes(frozen.canonical(pin))
    monkeypatch.setattr(frozen, "PIN_PATH", path)
    with pytest.raises(ValueError, match="translation_source_differs"):
        frozen.load_pin()


def test_preservation_rejects_modified_japanese_and_removed_original_members():
    pin = frozen.load_pin()
    base = frozen.latest().load_pin()["output"]["members"]
    rows = deepcopy(pin["output"]["members"])
    next(row for row in rows if row["path"] == "data/master-json/Card.json")["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="allowlist"):
        frozen.preservation(base, rows)
    with pytest.raises(ValueError, match="removed"):
        frozen.preservation(base, rows[1:])


def test_composed_zip_copies_frozen_deflate_streams_without_compression(tmp_path, monkeypatch):
    base_path, overlay_path, output = (tmp_path / name for name in ("base.zip", "overlay.zip", "result.zip"))
    normal = frozen.PREFIX + "coverage.json"
    media = frozen.PREFIX + "media-coverage.json"
    with ZipFile(base_path, "w", compression=8, compresslevel=1) as archive:
        archive.writestr(normal, b"unchanged " * 1000)
    with ZipFile(overlay_path, "w", compression=8, compresslevel=9) as archive:
        archive.writestr(media, b"updated " * 1000)
    def no_compressor(*args, **kwargs):
        raise AssertionError("Frozen application must not recompress any member")
    monkeypatch.setattr(zlib, "compressobj", no_compressor)
    with ZipFile(base_path) as base, ZipFile(overlay_path) as overlay:
        frozen.write_composed_payload(output, [normal, media, frozen.MANIFEST], base, overlay, b"manifest")
    with ZipFile(output) as archive:
        assert archive.read(normal) == b"unchanged " * 1000
        assert archive.read(media) == b"updated " * 1000
        assert archive.getinfo(frozen.MANIFEST).compress_type == 0
        assert archive.read(frozen.MANIFEST) == b"manifest"


def test_actual_frozen_application_reproduces_exact_final_payload(tmp_path):
    path = os.environ.get("IDOLY_LATEST_SERVER_DATA")
    if not path:
        pytest.skip("Set IDOLY_LATEST_SERVER_DATA to the pinned latest ServerData.zip")
    output = tmp_path / "ServerData.zip"
    proof = frozen.refresh_server_data(Path(path), output)
    assert frozen.verify_refresh_proof(proof) == proof
    assert frozen.file_pin(output) == frozen.output_pin()
    assert proof["base_payload"] == frozen.latest().output_pin()
    with pytest.raises(ValueError, match="fresh_output"):
        frozen.refresh_server_data(Path(path), output)


@pytest.mark.parametrize("mode", ["normal", "media"])
def test_actual_new_card_and_all_costume_sort_variants_have_korean_text(tmp_path, mode):
    path = os.environ.get("IDOLY_KOREAN_SERVER_DATA")
    if not path:
        pytest.skip("Set IDOLY_KOREAN_SERVER_DATA to the pinned refreshed ServerData.zip")
    pytest.importorskip("sqlcipher3")
    from idoly_local.schema import Schema
    from idoly_local.master_build import _sqlcipher_driver
    from idoly_local.master_translation_build import read_master_rows
    stem = "" if mode == "normal" else "media-"
    pool = tmp_path / "pool"
    pool.mkdir()
    with ZipFile(path) as archive:
        descriptor = tmp_path / "schema.pb"
        descriptor.write_bytes(archive.read("data/protocol/idolypride-6.1.1.pb"))
        tag = json.loads(archive.read(frozen.PREFIX + stem + "master-tag.json"))
        packs = {pack["type"]: pack for pack in tag["masterTagPacks"]}
        sort = json.loads(archive.read(frozen.PREFIX + stem + "master-sort.json"))
        selected = [packs["Card"], packs["Costume"],
                    *(variant["pack"] for variant in sort["variants"]["Costume"].values())]
        for pack in selected:
            target = pool / pack["fileName"]
            if not target.exists():
                target.write_bytes(archive.read("data/original-master/assets/master/" + pack["fileName"]))
    schema = Schema.from_descriptor_set(descriptor)
    driver, _ = _sqlcipher_driver()
    cards = {row["id"]: row for row in read_master_rows(schema, driver, pool, packs["Card"])}
    assert cards["card-mna-05-casl-04"]["name"] == "별바다로 이어지는 휴일"
    assert cards["card-mna-05-casl-04"]["obtainMessage"] == "…있잖아, 손 잡아도 돼?"
    expected = {"cos-mna-casl-04": "외출 스타일", "cos-aoi-link-01": "리에루프레", "cos-chs-wedd-00": "스위트 브라이드"}
    for pack in [packs["Costume"], *(variant["pack"] for variant in sort["variants"]["Costume"].values())]:
        costumes = {row["id"]: row for row in read_master_rows(schema, driver, pool, pack)}
        assert {identity: costumes[identity]["name"] for identity in expected} == expected
