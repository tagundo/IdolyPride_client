import hashlib
import json
from zipfile import ZipFile

import pytest

from idoly_local.octo_manifest import Database, OctoObject
from idoly_local.resource_translation_build import ZipScriptSource, build_resource_overlay

SOURCE = {"repository": "https://example.invalid/public-data", "revision": "a" * 40}


def original():
    database = Database(revision=1087, urlFormat="public-original-format")
    database.assetBundleList.add(id=1, name="stage", size=3, md5="a" * 32, objectName="original_stage", generation=1, uploadVersionId=202050, state=3)
    for number, name in enumerate(("adv_bond_ai_01_01.txt", "adv_event_none_01.txt", "untouched.json"), 1):
        database.resourceList.add(id=number, name=name, size=3, md5="b" * 32,
                                  objectName="original_" + str(number), generation=number,
                                  uploadVersionId=202050, state=3, priority=7, dependencie=[4, 5])
    return database.SerializeToString()


def test_translated_objects_and_manifest_are_consistent_and_original_is_immutable(tmp_path):
    directory = tmp_path / "input"; directory.mkdir()
    script = "[title title=번역]\n아이: 안녕!\n".encode()
    (directory / "adv_bond_ai_01_01.txt").write_bytes(script)
    (directory / "adv_not_in_manifest.txt").write_text("never exposed")
    raw = original()
    report = build_resource_overlay(raw, directory, tmp_path / "output", language="ko", revision=1088, source=SOURCE)
    before, after = Database.FromString(raw), Database.FromString((tmp_path / "output/manifest.pb").read_bytes())
    assert before.revision == 1087 and after.revision == 1088
    assert before.assetBundleList == after.assetBundleList
    assert before.resourceList[1:] == after.resourceList[1:]
    row = after.resourceList[0]
    assert row.name == before.resourceList[0].name and row.id == before.resourceList[0].id
    assert row.priority == 7 and list(row.dependencie) == [4, 5]
    assert row.objectName.startswith("local_ko_") and row.objectName != before.resourceList[0].objectName
    assert row.generation != before.resourceList[0].generation
    assert row.md5 == hashlib.md5(script).hexdigest() and row.size == len(script) and row.state == 2
    record = OctoObject("resources", row.uploadVersionId, row.objectName, row.generation, row.size, row.md5, row.name)
    with ZipFile(tmp_path / "output/objects.zip") as archive:
        assert archive.namelist() == [record.cache_key + ".bin"]
        assert archive.read(archive.namelist()[0]) == script
    assert report["coverage"] == {"adv_resources": 2, "translated": 1, "missing": 1, "unchanged_original": 0}
    assert report["manifest_sha256"] == hashlib.sha256((tmp_path / "output/manifest.pb").read_bytes()).hexdigest()
    assert report == json.loads((tmp_path / "output/manifest.json").read_text())


def test_reproducible_overlay_does_not_reuse_original_content_identity(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    (source / "adv_bond_ai_01_01.txt").write_text("안녕")
    for name in ("one", "two"):
        build_resource_overlay(original(), source, tmp_path / name, language="ko", revision=1088, source=SOURCE)
    for name in ("manifest.pb", "manifest.json", "objects.zip"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_two_scripts_with_identical_translation_still_have_distinct_sdk_identities(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    for name in ("adv_bond_ai_01_01.txt", "adv_event_none_01.txt"):
        (source / name).write_text("동일한 대사")
    build_resource_overlay(original(), source, tmp_path / "output", language="ko", revision=1088, source=SOURCE)
    data = Database.FromString((tmp_path / "output/manifest.pb").read_bytes())
    assert data.resourceList[0].objectName != data.resourceList[1].objectName
    assert data.resourceList[0].md5 == data.resourceList[1].md5


@pytest.mark.parametrize("revision", [1087, 1, True, 2**31])
def test_revision_cannot_leave_stale_client_cache(tmp_path, revision):
    with pytest.raises(ValueError, match="advance"):
        build_resource_overlay(original(), tmp_path, tmp_path / "out", language="ko", revision=revision, source=SOURCE)


def test_scripts_never_escape_source_directory(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    outside = tmp_path / "secret"; outside.write_text("secret")
    (source / "adv_bond_ai_01_01.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="regular"):
        build_resource_overlay(original(), source, tmp_path / "out", language="ko", revision=1088, source=SOURCE)


def test_compressed_source_only_reads_named_adv_members_and_checks_archive_identity(tmp_path):
    archive = tmp_path / "source.zip"
    with ZipFile(archive, "w") as target:
        target.writestr("repo/local-files/resource/adv/adv_bond_ai_01_01.txt", "번역")
        target.writestr("repo/local-files/masterTrans/Unused.json", "never expanded")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with ZipScriptSource(archive, "repo/local-files/resource/adv/", expected_sha256=digest) as reader:
        assert reader("adv_bond_ai_01_01.txt") == "번역".encode()
        assert reader("../../masterTrans/Unused.json") is None
        report = build_resource_overlay(original(), tmp_path / "absent", tmp_path / "output",
            language="en", revision=1088, source=SOURCE, read_script=reader)
        assert report["coverage"]["translated"] == 1
    with pytest.raises(ValueError, match="identity"):
        ZipScriptSource(archive, "repo/local-files/resource/adv/", expected_sha256="0" * 64)
