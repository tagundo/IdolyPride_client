"""Latest resources retain new identities and reuse only verified unchanged translations."""
import hashlib
import json

import pytest

from idoly_local.octo_manifest import Database, OctoObject
from idoly_local.resource_translation import (ResourceTranslation, RebasedResourceTranslation,
    load_resource_translation)
from idoly_local.resource_translation_build import build_resource_overlay
from idoly_local.resource_translation_runtime import select_resource_translation

SOURCE = {"repository": "https://example.invalid/public", "revision": "a" * 40}


def prepared(tmp_path):
    old = Database(revision=1087, urlFormat="original")
    old.resourceList.add(id=1, name="adv_bond_ai_01_01.txt", objectName="Obj001",
        generation=1, uploadVersionId=202050, size=3,
        md5=hashlib.md5(b"old").hexdigest(), state=3, priority=9)
    old.assetBundleList.add(id=1, name="existing_model", objectName="Obj002",
        generation=1, uploadVersionId=202050, size=3,
        md5=hashlib.md5(b"old").hexdigest(), state=3)
    raw = old.SerializeToString()
    source = tmp_path / "source"; source.mkdir()
    body = "[title title=번역]\n검증된 번역".encode()
    (source / "adv_bond_ai_01_01.txt").write_bytes(body)
    target = tmp_path / "overlay"
    build_resource_overlay(raw, source, target, language="ko", revision=1088, source=SOURCE)
    current = Database.FromString(raw); current.revision = 1200
    current.resourceList[0].id = 5
    current.resourceList[0].dependencie.append(77)
    current.tagname.append("latest-only")
    current.assetBundleList.add(id=77, name="latest_mana_model", objectName="Obj003",
        generation=2, uploadVersionId=202051, size=3,
        md5=hashlib.md5(b"new").hexdigest(), state=3)
    return raw, current, target, body


def record(row):
    return OctoObject("resources", row.uploadVersionId, row.objectName,
        row.generation, row.size, row.md5, row.name)


def test_rebase_preserves_new_models_ids_dependencies_tags_and_unknown_fields(tmp_path):
    old, current, target, body = prepared(tmp_path)
    current_raw = current.SerializeToString() + b"\x38\x01"
    layer = ResourceTranslation(target, old, language="ko")
    rebased = RebasedResourceTranslation(layer, old, current_raw)
    try:
        actual = Database.FromString(rebased.manifest)
        assert actual.revision == 1201
        assert actual.assetBundleList == current.assetBundleList
        assert actual.tagname == current.tagname
        assert actual.resourceList[0].id == 5
        assert list(actual.resourceList[0].dependencie) == [77]
        with rebased.open_source(record(actual.resourceList[0])) as stream:
            assert stream.read() == body
        assert rebased.report["coverage"] == {
            "adv_resources": 1, "translated": 1, "missing": 0, "unchanged_original": 0}
        reverted = Database.FromString(rebased.manifest)
        reverted.revision = current.revision
        for field in ("objectName", "generation", "size", "md5", "crc", "state"):
            setattr(reverted.resourceList[0], field, getattr(current.resourceList[0], field))
        assert reverted == Database.FromString(current_raw)
        assert len(rebased.object_aliases) == 1
        assert current.SerializeToString() + b"\x38\x01" == current_raw
    finally:
        rebased.close()
    with pytest.raises(ValueError, match="closed"):
        rebased.open_source(record(actual.resourceList[0]))


@pytest.mark.parametrize("field,value", [
    ("size", 4), ("md5", "c" * 32), ("generation", 2),
    ("objectName", "Changed"), ("uploadVersionId", 202051), ("name", "adv_bond_ai_01_02.txt"),
    ("state", 4)])
def test_changed_original_identity_falls_back_to_latest_original(tmp_path, field, value):
    old, current, target, _body = prepared(tmp_path)
    setattr(current.resourceList[0], field, value)
    raw = current.SerializeToString()
    layer = ResourceTranslation(target, old, language="ko")
    rebased = RebasedResourceTranslation(layer, old, raw)
    try:
        actual = Database.FromString(rebased.manifest)
        assert actual.resourceList == current.resourceList
        assert actual.assetBundleList == current.assetBundleList
        assert rebased.report["coverage"]["translated"] == 0
        assert not rebased.object_aliases
        assert rebased.open_source(record(actual.resourceList[0])) is None
    finally:
        rebased.close()


def test_rebase_rejects_duplicate_current_names(tmp_path):
    old, current, target, _body = prepared(tmp_path)
    current.resourceList.add().CopyFrom(current.resourceList[0])
    layer = ResourceTranslation(target, old, language="ko")
    try:
        with pytest.raises(ValueError, match="Duplicate latest"):
            RebasedResourceTranslation(layer, old, current.SerializeToString())
    finally:
        layer.close()


def test_factory_requires_pinned_new_and_legacy_manifest_bytes(tmp_path, monkeypatch):
    import idoly_local.resource_translation as translation
    import idoly_local.latest_cohort_pins as pins
    old, current, target, body = prepared(tmp_path)
    raw = current.SerializeToString(); data = tmp_path / "data"; data.mkdir()
    archive = data / "public-octo"; archive.mkdir()
    (archive / "legacy-manifest.pb").write_bytes(old)
    approved = {"application_version": 205051, "revision": 1200,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "legacy_manifest_sha256": hashlib.sha256(old).hexdigest()}
    monkeypatch.setattr(translation, "LEGACY_MANIFEST_SHA256", {"android": hashlib.sha256(old).hexdigest()})
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {})
    with pytest.raises(ValueError, match="not approved"):
        load_resource_translation(target, raw, language="ko", data_dir=data, platform="android")
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {"android": approved})
    layer = load_resource_translation(target, raw, language="ko", data_dir=data, platform="android")
    try:
        with layer.open_source(record(Database.FromString(layer.manifest).resourceList[0])) as stream:
            assert stream.read() == body
    finally:
        layer.close()
    (archive / "legacy-manifest.pb").write_bytes(old + b"\x38\x01")
    with pytest.raises(ValueError, match="legacy manifest differs"):
        load_resource_translation(target, raw, language="ko", data_dir=data, platform="android")
    assert not tuple(data.glob("*.json"))


def test_factory_does_not_accept_an_unrelated_prepared_source(tmp_path, monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    old, current, target, _body = prepared(tmp_path)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {})
    report = json.loads((target / "manifest.json").read_text())
    report["original_manifest_sha256"] = "f" * 64
    (target / "manifest.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="not approved"):
        load_resource_translation(target, current.SerializeToString(), language="ko",
            data_dir=tmp_path, platform="android")


def test_original_strict_translation_remains_compatible_without_latest_pins(tmp_path, monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    old, _current, target, body = prepared(tmp_path)
    monkeypatch.setattr(pins, "RESOURCE_ARCHIVES", {})
    layer = load_resource_translation(target, old, language="ko", data_dir=tmp_path, platform="android")
    try:
        with layer.open_source(record(Database.FromString(layer.manifest).resourceList[0])) as stream:
            assert stream.read() == body
    finally:
        layer.close()
