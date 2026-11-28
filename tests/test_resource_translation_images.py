"""Binary image overlays use their own manifest identity and the verified cache."""
import copy
import hashlib
import json
from zipfile import ZIP_DEFLATED, ZipFile

from Crypto.Cipher import AES
import pytest

from idoly_local.octo_cache import OctoCache, OctoCacheError
from idoly_local.octo_manifest import Database, OctoManifest, OctoManifestError, OctoObject
from idoly_local.resource_translation import ResourceTranslation

SOURCE = {"repository": "https://example.invalid/translations", "revision": "a" * 40}
NAME = "img_story_top_main-new"


def fixture(tmp_path):
    original_image, translated = b"original image bundle", b"UnityFS\0translated image bundle"
    database = Database(revision=1087, urlFormat="https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media")
    row = database.assetBundleList.add(id=1, name=NAME, objectName="Image1", size=len(original_image),
        md5=hashlib.md5(original_image).hexdigest(), generation=1, uploadVersionId=202050, state=3,
        priority=7, tagid=[2], dependencie=[2])
    database.assetBundleList.add(id=2, name="stage_model", objectName="Model1", size=3,
        md5=hashlib.md5(b"old").hexdigest(), generation=1, uploadVersionId=202050, state=3)
    database.resourceList.add(id=1, name="adv_test.txt", objectName="Story1", size=3,
        md5=hashlib.md5(b"old").hexdigest(), generation=1, uploadVersionId=202050, state=3)
    original = database.SerializeToString()
    sha = hashlib.sha256(translated).hexdigest()
    before = {"size": row.size, "md5": row.md5, "object_name": row.objectName,
        "generation": row.generation, "upload_version": row.uploadVersionId,
        "sha256": hashlib.sha256(original_image).hexdigest()}
    row.objectName = "local_ko_" + sha[:28] + "_" + hashlib.sha256(NAME.encode()).hexdigest()[:12]
    row.generation = int(sha[40:56], 16) or 1
    row.size, row.md5, row.crc, row.state = len(translated), hashlib.md5(translated).hexdigest(), 0, 2
    record = OctoObject("assetbundle", row.uploadVersionId, row.objectName, row.generation,
        row.size, row.md5, row.name)
    filename = record.cache_key + ".bin"
    database.revision = 1088
    modified = database.SerializeToString()
    report = {"schema": 2, "language": "ko", "source": SOURCE, "image_source": SOURCE,
        "base_revision": 1087, "revision": 1088,
        "original_manifest_sha256": hashlib.sha256(original).hexdigest(),
        "manifest_sha256": hashlib.sha256(modified).hexdigest(),
        "coverage": {"adv_resources": 1, "translated": 0, "missing": 1, "unchanged_original": 0},
        "image_coverage": {"candidates": 1, "translated": 1, "missing": 0, "unchanged_original": 0},
        "objects": {filename: {"name": NAME, "kind": "assetbundle", "bytes": len(translated),
            "md5": row.md5, "sha256": sha}},
        "changed_images": [{"name": NAME, "original": before,
            "local": {"cache_key": record.cache_key, "size": row.size, "md5": row.md5,
                "sha256": sha, "object_name": row.objectName, "generation": row.generation},
            "png": {"bytes": 123, "sha256": "b" * 64, "width": 64, "height": 32},
            "texture": {"name": NAME, "width": 64, "height": 32, "format_before": 50,
                "format_after": 50, "readback_pixel_exact": False, "encoding": "ASTC6x6-medium",
                "source_RGBA_sha256": "c" * 64, "decoded_RGBA_sha256": "d" * 64,
                "quality": 60, "threads": 1}}]}
    destination = tmp_path / "overlay"; destination.mkdir()
    (destination / "manifest.pb").write_bytes(modified)
    (destination / "manifest.json").write_text(json.dumps(report))
    with ZipFile(destination / "objects.zip", "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(filename, translated)
    return original, destination, translated, record, report


def write_report(destination, report):
    (destination / "manifest.json").write_text(json.dumps(report))


def test_image_identity_and_offline_verified_cache_preserve_original_model_and_story(tmp_path):
    original, destination, translated, record, _report = fixture(tmp_path)
    layer = ResourceTranslation(destination, original, language="ko")
    final = Database.FromString(layer.manifest); old = Database.FromString(original)
    assert final.assetBundleList[1] == old.assetBundleList[1]
    assert final.resourceList == old.resourceList
    assert final.assetBundleList[0].name == old.assetBundleList[0].name
    assert final.assetBundleList[0].tagid == old.assetBundleList[0].tagid
    assert final.assetBundleList[0].dependencie == old.assetBundleList[0].dependencie
    assert ("assetbundle", 202050, "Image1", record.generation) in layer.object_aliases
    calls = []
    cache = OctoCache(tmp_path / "cache", allow_download=False, local_source=layer.open_source,
        fetcher=lambda *args, **kwargs: calls.append(args))
    with cache.open_verified(record) as incoming:
        assert incoming.read() == translated
    assert not calls
    cache.close(); layer.close()


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema=1),
    lambda r: r.update(image_source={"repository": "", "revision": "a" * 40}),
    lambda r: r["image_coverage"].update(translated=0),
    lambda r: r["changed_images"].append(copy.deepcopy(r["changed_images"][0])),
    lambda r: r["changed_images"][0]["original"].update(md5="0" * 32),
    lambda r: r["changed_images"][0]["local"].update(cache_key="0" * 64),
    lambda r: r["changed_images"][0]["png"].update(sha256="invalid"),
    lambda r: r["changed_images"][0]["texture"].update(readback_pixel_exact=True),
    lambda r: r["changed_images"][0]["texture"].update(format_after=4),
    lambda r: r["changed_images"][0]["texture"].update(quality=59),
    lambda r: r["changed_images"][0]["texture"].update(threads=2),
    lambda r: r["changed_images"][0]["texture"].update(decoded_RGBA_sha256="invalid"),
    lambda r: next(iter(r["objects"].values())).update(kind="resources"),
])
def test_undeclared_or_incoherent_image_data_is_rejected_before_archive_open(tmp_path, mutation):
    original, destination, _translated, _record, report = fixture(tmp_path)
    mutation(report); write_report(destination, report)
    (destination / "objects.zip").unlink()
    with pytest.raises(ValueError):
        ResourceTranslation(destination, original, language="ko")


@pytest.mark.parametrize("encoding,texture_format,lossless", [
    ("RGBA32-lossless", 4, True), ("ASTC4x4-medium", 48, False), ("ASTC6x6-medium", 50, False),
])
def test_encoding_must_preserve_the_original_gpu_format(tmp_path, encoding, texture_format, lossless):
    original, destination, _translated, _record, report = fixture(tmp_path)
    report["changed_images"][0]["texture"].update(encoding=encoding,
        format_before=texture_format, format_after=texture_format, readback_pixel_exact=lossless)
    write_report(destination, report)
    layer = ResourceTranslation(destination, original, language="ko"); layer.close()


@pytest.mark.parametrize("change", ["dependencie", "model", "urlFormat"])
def test_image_translation_does_not_authorize_other_manifest_changes(tmp_path, change):
    original, destination, _translated, _record, report = fixture(tmp_path)
    manifest = Database.FromString((destination / "manifest.pb").read_bytes())
    if change == "dependencie": manifest.assetBundleList[0].dependencie.append(999)
    elif change == "model": manifest.assetBundleList[1].size += 1
    else: manifest.urlFormat = "different"
    modified = manifest.SerializeToString(); (destination / "manifest.pb").write_bytes(modified)
    report["manifest_sha256"] = hashlib.sha256(modified).hexdigest(); write_report(destination, report)
    with pytest.raises(ValueError):
        ResourceTranslation(destination, original, language="ko")


def test_tampered_binary_archive_fails_cache_checksum_without_cdn_fallback(tmp_path):
    original, destination, translated, record, _report = fixture(tmp_path)
    with ZipFile(destination / "objects.zip", "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(record.cache_key + ".bin", b"X" * len(translated))
    layer = ResourceTranslation(destination, original, language="ko"); calls = []
    cache = OctoCache(tmp_path / "cache", local_source=layer.open_source,
        fetcher=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(OctoCacheError):
        with cache.open_verified(record): pass
    assert not calls and not list((tmp_path / "cache").rglob("*.bin"))
    cache.close(); layer.close()


def test_sdk_manifest_accepts_only_the_matching_kind_for_local_image_aliases(tmp_path):
    original, destination, _translated, record, _report = fixture(tmp_path)
    layer = ResourceTranslation(destination, original, language="ko")
    def aes(encrypt, key, iv, data):
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(data) if encrypt else cipher.decrypt(data)
    args = dict(aes_key=b"a" * 32, client_key="synthetic", base_url="http://127.0.0.1:8080", aes_cbc=aes)
    manifest = OctoManifest(layer.manifest, object_aliases=layer.object_aliases, **args)
    path = f"/octo/{record.upload_version}/assetbundle/Image1/{record.generation}"
    assert manifest.lookup_object(path) == record
    wrong_kind = {("resources", 202050, "Image1", record.generation): record}
    with pytest.raises(OctoManifestError, match="alias"):
        OctoManifest(layer.manifest, object_aliases=wrong_kind, **args)
    layer.close()
