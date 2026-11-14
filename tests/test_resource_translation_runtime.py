from dataclasses import replace
import hashlib
import io
import json
import time

from Crypto.Cipher import AES
import pytest

from idoly_local.octo_cache import OctoCache, OctoCacheError
from idoly_local.octo_manifest import Database, OctoManifest, OctoObject, OctoRequestError, decrypt_manifest
from idoly_local.resource_translation import ResourceTranslation
from idoly_local.resource_translation_build import build_resource_overlay
from idoly_local.resource_translation_runtime import pin_manifest_revision, validate_prepared_translations
from idoly_local.octo_runtime import create_octo_gateway
from idoly_local.resource_library import ResourceLibrary, ResourceLibraryError

URL = "https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media"
SOURCE = {"repository": "https://example.invalid/translations", "revision": "a" * 40}
KEY = b"a" * 32


def database():
    result = Database(revision=1087, urlFormat=URL)
    for rows, name in ((result.assetBundleList, "stage"), (result.resourceList, "adv_bond_ai_01_01.txt")):
        rows.add(id=1, name=name, objectName="original_" + str(len(name)), size=3,
                 md5=hashlib.md5(b"old").hexdigest(), generation=1, uploadVersionId=202050, state=3)
    return result


def aes(encrypt, key, iv, data):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


def test_ja_ko_en_ja_switches_advance_and_restarts_reuse_the_same_sdk_revision(tmp_path):
    state = tmp_path / "revision.json"; original = database().SerializeToString()
    ja, compatible = pin_manifest_revision(original, state, language="ja", preserve_original=True)
    assert ja == original and not compatible and not state.exists()
    revisions = []
    for language in ("ko", "en", "ja", "ko"):
        raw, compatible = pin_manifest_revision(original, state, language=language)
        parsed = Database.FromString(raw); revisions.append(parsed.revision)
        assert compatible and parsed.resourceList[0].state == 2
        same, _ = pin_manifest_revision(original, state, language=language)
        assert same == raw
        manifest = OctoManifest(raw, aes_key=KEY, client_key="synthetic", base_url="http://127.0.0.1:8080",
                                aes_cbc=aes, allow_previous_revisions=True)
        requested = parsed.revision - 1
        response = manifest.manifest_response(f"/v2/pub/a/212/v/205051/list/{requested}",
            {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic"})
        complete = Database.FromString(decrypt_manifest(response, aes_key=KEY, aes_cbc=aes))
        assert complete.revision == parsed.revision and len(complete.resourceList) == 1
    assert all(a < b for a, b in zip(revisions, revisions[1:]))
    assert database().SerializeToString() == original


def test_compressed_translation_seed_works_offline_through_existing_checksum_cache(tmp_path):
    original = database().SerializeToString(); source = tmp_path / "source"; source.mkdir()
    translated = "번역된 원본 명령과 대사".encode()
    (source / "adv_bond_ai_01_01.txt").write_bytes(translated)
    build_resource_overlay(original, source, tmp_path / "overlay", language="ko", revision=1088, source=SOURCE)
    layer = ResourceTranslation(tmp_path / "overlay", original, language="ko")
    row = Database.FromString(layer.manifest).resourceList[0]
    record = OctoObject("resources", row.uploadVersionId, row.objectName, row.generation, row.size, row.md5, row.name)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args); raise AssertionError("Local translations must not use the CDN")
    cache = OctoCache(tmp_path / "cache", allow_download=False, fetcher=forbidden, local_source=layer.open_source)
    with cache.open_verified(record) as stream:
        assert stream.read() == translated and stream.fileno() >= 0
    assert not calls
    cache.close(); layer.close()


@pytest.mark.parametrize("body", [b"wrong digest", b"longer than the declared size!", b""])
def test_bad_local_seed_never_falls_through_to_cdn_and_never_publishes(tmp_path, body):
    record = OctoObject("resources", 202050, "local_ko_immutable", 1, 3, hashlib.md5(b"yes").hexdigest(), "story")
    calls = []
    cache = OctoCache(tmp_path / "cache", local_source=lambda _record: io.BytesIO(body),
                      fetcher=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(OctoCacheError, match="cache_io"):
        with cache.open_verified(record):
            pass
    assert not calls and not list((tmp_path / "cache").rglob("*.bin"))
    assert not list((tmp_path / "cache").rglob("*.part"))


def test_revision_state_symlinks_and_nonregular_files_never_block(tmp_path):
    target = tmp_path / "target"; target.write_text("not revision data")
    path = tmp_path / "state"; path.symlink_to(target)
    with pytest.raises(OSError):
        pin_manifest_revision(database().SerializeToString(), path, language="ko")


def test_gateway_factory_uses_selected_downloads_language_data_and_restores_japanese(tmp_path):
    private, public = tmp_path / "private", tmp_path / "Downloads/IdolyPride"
    archive = private / "public-octo"; archive.mkdir(parents=True); public.mkdir(parents=True)
    raw = database().SerializeToString()
    (archive / "manifest.pb").write_bytes(raw)
    (archive / "settings.json").write_text(json.dumps({"schema": 1, "application_id": 212,
        "application_version": 205051, "revision": 1087, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "aes_key_hex": KEY.hex(), "client_key": "synthetic"}))
    source = tmp_path / "source"; source.mkdir()
    body = "[title title=로컬 번역]".encode()
    (source / "adv_bond_ai_01_01.txt").write_bytes(body)
    build_resource_overlay(raw, source, public / "translations/ko/android", language="ko", revision=1088, source=SOURCE)
    calls = []
    gateway, _ = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=aes,
        resource_cache_dir=public, language="ko", allow_downloads=False,
        fetcher=lambda *args, **kwargs: calls.append(args))
    record = next(value for value in gateway.manifest.objects.values() if value.kind == "resources")
    original_name = Database.FromString(raw).resourceList[0].objectName
    mixed_path = f"/octo/{record.upload_version}/resources/{original_name}/{record.generation}"
    assert gateway.manifest.lookup_object(mixed_path) == record
    with gateway.cache.open_verified(record) as stream:
        assert stream.read() == body
    assert gateway.translation_layer is not None and not calls
    previous_revision = gateway.manifest.revision; gateway.close()
    japanese, _ = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=aes,
        resource_cache_dir=public, language="ja", allow_downloads=False)
    restored = next(value for value in japanese.manifest.objects.values() if value.kind == "resources")
    assert japanese.manifest.revision > previous_revision
    assert restored.object_name.startswith("original_") and japanese.translation_layer is None
    with pytest.raises(OctoRequestError) as mixed_failure:
        japanese.manifest.lookup_object(mixed_path)
    assert getattr(mixed_failure.value, "status", None) == 404
    assert (archive / "manifest.pb").read_bytes() == raw
    assert list((public / "octo-cache").rglob("*.bin"))
    japanese.close()


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("language", ["ko", "en", "ja"])
def test_bulk_library_keeps_original_catalog_while_game_uses_selected_language(tmp_path, platform, language):
    ios = platform == "ios"
    revision, version = (1159, 105051) if ios else (1087, 205051)
    private, public = tmp_path / "private", tmp_path / "Downloads/IdolyPride"
    archive = private / ("public-octo-ios" if ios else "public-octo")
    archive.mkdir(parents=True); public.mkdir(parents=True)
    original = database(); original.revision = revision
    for rows in (original.assetBundleList, original.resourceList):
        for row in rows:
            row.uploadVersionId = 101050 if ios else 202050
    raw = original.SerializeToString()
    settings = {"schema": 1, "application_id": 212, "application_version": version,
        "revision": revision, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "aes_key_hex": KEY.hex(), "client_key": "synthetic"}
    (archive / "manifest.pb").write_bytes(raw)
    (archive / "settings.json").write_text(json.dumps(settings))
    source = tmp_path / "source"; source.mkdir()
    translated = ("로컬 번역" if language != "en" else "local translation").encode()
    (source / "adv_bond_ai_01_01.txt").write_bytes(translated)
    overlay_language = "ko" if language == "ja" else language
    build_resource_overlay(raw, source, public / "translations" / overlay_language / platform,
        language=overlay_language, revision=revision + 1, source=SOURCE)
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError("Gameplay must reuse local files, never contact the CDN")
    if language == "ja":
        # A previous localized session also pins a newer revision on restored JP.
        previous, _ = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=aes,
            resource_cache_dir=public, platform=platform, language="ko", allow_downloads=False,
            fetcher=forbidden)
        previous.close()
    gateway, _ = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=aes,
        resource_cache_dir=public, platform=platform, language=language, allow_downloads=False,
        fetcher=forbidden)
    library = None
    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Length": "3"}
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(b"old")
    try:
        assert gateway.manifest.revision > revision
        with pytest.raises(ResourceLibraryError, match="invalid_catalog"):
            ResourceLibrary(private, {platform: gateway.manifest}, aes_cbc=aes,
                resource_cache_dir=public)
        library = ResourceLibrary.from_data_dir(private, aes_cbc=aes, fetcher=fetch,
            active_gateway=gateway, resource_cache_dir=public)
        library.catalog_summary(platform)
        catalog = library._catalogs[platform]
        assert catalog.manifest.revision == revision and catalog.raw == raw
        assert all(record.object_name.startswith("original_") for record in catalog.records)
        library.start_download(platform, parallelism=1)
        deadline = time.monotonic() + 2
        while (job := library.status()["job"])["state"] not in {"completed", "partial", "failed", "cancelled"}:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert job["state"] == "completed" and job["verified_files"] == 2
        assert job["received_bytes"] == 6 and len(calls) == 2
        assert set(calls) == {record.upstream_url for record in catalog.records}
        assert gateway.cache.root == public / ("octo-cache-ios" if ios else "octo-cache")
        for record in gateway.manifest.objects.values():
            with gateway.cache.open_verified(record) as stream:
                expected = translated if language != "ja" and record.kind == "resources" else b"old"
                assert stream.read() == expected
        library.start_download(platform, parallelism=1)
        deadline = time.monotonic() + 2
        while (job := library.status()["job"])["state"] not in {"completed", "partial", "failed", "cancelled"}:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert job["state"] == "completed" and job["cache_hit_files"] == 2 and job["received_bytes"] == 0
        assert len(calls) == 2 and (archive / "manifest.pb").read_bytes() == raw
    finally:
        if library is not None:
            library.close()
        gateway.close()


def test_installer_semantic_helper_validates_both_languages_closes_archives_and_rejects_wrong_base(tmp_path, monkeypatch):
    from idoly_local import resource_translation_runtime as runtime
    private = tmp_path / "private"; archive = private / "public-octo"; archive.mkdir(parents=True)
    raw = database().SerializeToString()
    settings = {"schema": 1, "application_id": 212, "application_version": 205051,
                "revision": 1087, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "aes_key_hex": KEY.hex(), "client_key": "synthetic"}
    (archive / "manifest.pb").write_bytes(raw)
    (archive / "settings.json").write_text(json.dumps(settings))
    source = tmp_path / "source"; source.mkdir()
    (source / "adv_bond_ai_01_01.txt").write_text("prepared translation")
    for language in ("ko", "en"):
        build_resource_overlay(raw, source, tmp_path / "staged" / language / "android",
            language=language, revision=1088, source=SOURCE)
    opened = []
    class ObservedLayer(ResourceTranslation):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); opened.append(self)
    monkeypatch.setattr(runtime, "ResourceTranslation", ObservedLayer)
    coverage = validate_prepared_translations(tmp_path / "staged", private, platform="android")
    assert set(coverage) == {"ko", "en"} and all(value["translated"] == 1 for value in coverage.values())
    assert len(opened) == 2 and all(layer._archive is None for layer in opened)
    assert not list(private.glob("client-resource-revision-*.json"))
    altered = database(); altered.assetBundleList[0].priority += 1
    wrong = altered.SerializeToString(); settings["manifest_sha256"] = hashlib.sha256(wrong).hexdigest()
    (archive / "manifest.pb").write_bytes(wrong); (archive / "settings.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="identity"):
        validate_prepared_translations(tmp_path / "staged", private, platform="android")
    assert len(opened) == 2 and not list(private.glob("client-resource-revision-*.json"))
    (archive / "manifest.pb").write_bytes(raw); settings["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    (archive / "settings.json").write_text(json.dumps(settings))
    selected = tmp_path / "staged/ko/android"
    malformed = b"\xff\xff\xff"
    manifest = json.loads((selected / "manifest.json").read_text())
    manifest["manifest_sha256"] = hashlib.sha256(malformed).hexdigest()
    (selected / "manifest.pb").write_bytes(malformed); (selected / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="format"):
        validate_prepared_translations(tmp_path / "staged", private, platform="android")
    assert len(opened) == 2 and not list(private.glob("client-resource-revision-*.json"))
