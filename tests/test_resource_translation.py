import hashlib
import json

import pytest

from idoly_local.octo_manifest import Database, OctoObject
from idoly_local.resource_translation import ResourceTranslation
from idoly_local.resource_translation_build import build_resource_overlay

SOURCE = {"repository": "https://example.invalid/public-data", "revision": "a" * 40}


def prepare(tmp_path):
    database = Database(revision=1087, urlFormat="original")
    database.assetBundleList.add(id=1, name="stage", size=1, md5="a" * 32, objectName="original", generation=1, uploadVersionId=202050, state=3)
    database.resourceList.add(id=1, name="adv_bond_ai_01_01.txt", size=1, md5="b" * 32, objectName="story", generation=1, uploadVersionId=202050, state=3, priority=9)
    raw = database.SerializeToString()
    source = tmp_path / "source"; source.mkdir(); script = "[title title=번역]\n대사"
    (source / "adv_bond_ai_01_01.txt").write_text(script)
    destination = tmp_path / "ko"
    build_resource_overlay(raw, source, destination, language="ko", revision=1088, source=SOURCE)
    return raw, destination, script.encode()


def test_manifest_first_validation_and_local_source_do_not_touch_network_or_original(tmp_path):
    raw, destination, script = prepare(tmp_path)
    layer = ResourceTranslation(destination, raw, language="ko")
    row = Database.FromString(layer.manifest).resourceList[0]
    record = OctoObject("resources", row.uploadVersionId, row.objectName, row.generation, row.size, row.md5, row.name)
    with layer.open_source(record) as source:
        assert source.read() == script
    untouched = OctoObject("assetbundle", 202050, "original", 1, 1, "a" * 32, "stage")
    assert layer.open_source(untouched) is None
    layer.close()
    with pytest.raises(ValueError, match="closed"):
        layer.open_source(record)


def test_manifest_cannot_relabel_a_gameplay_or_asset_bundle_change_as_translation(tmp_path):
    raw, destination, _script = prepare(tmp_path)
    changed = Database.FromString((destination / "manifest.pb").read_bytes())
    changed.assetBundleList[0].size = 999
    body = changed.SerializeToString()
    (destination / "manifest.pb").write_bytes(body)
    manifest = json.loads((destination / "manifest.json").read_text())
    manifest["manifest_sha256"] = hashlib.sha256(body).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unrelated"):
        ResourceTranslation(destination, raw, language="ko")


def test_prepared_layer_is_tied_to_the_exact_platform_manifest(tmp_path):
    raw, destination, _script = prepare(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        ResourceTranslation(destination, raw + b"\x38\x01", language="ko")
