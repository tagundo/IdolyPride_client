from dataclasses import replace
import hashlib
import io
import json
import time
import weakref

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
    for number, (rows, name) in enumerate(((result.assetBundleList, "stage"),
                                          (result.resourceList, "adv_bond_ai_01_01.txt")), 1):
        rows.add(id=1, name=name, objectName=f"Obj{number:03}", size=3,
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


def test_sdk_wire_fix_updates_an_existing_broken_revision_once_and_survives_restart(tmp_path):
    original = database(); original.revision = 1161
    raw = original.SerializeToString(); state = tmp_path / "revision.json"
    old, _ = pin_manifest_revision(raw, state, language="ko")
    assert Database.FromString(old).revision == 1161
    fixed, compatible = pin_manifest_revision(raw, state, language="ko", sdk_identity_compat=True)
    assert compatible and Database.FromString(fixed).revision == 1162
    persisted = state.read_bytes()
    restarted, _ = pin_manifest_revision(raw, state, language="ko", sdk_identity_compat=True)
    assert restarted == fixed and state.read_bytes() == persisted
    # A client with the broken revision gets all corrected rows; after storing
    # it, subsequent checks receive the ordinary empty same-revision delta.
    server = OctoManifest(fixed, aes_key=KEY, client_key="synthetic", base_url="http://127.0.0.1:8080",
        aes_cbc=aes, allow_previous_revisions=True)
    headers = {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic"}
    def response(revision):
        wire = server.manifest_response(f"/v2/pub/a/212/v/205051/list/{revision}", headers)
        return Database.FromString(decrypt_manifest(wire, aes_key=KEY, aes_cbc=aes))
    updated, unchanged = response(1161), response(1162)
    assert updated.revision == 1162 and len(updated.assetBundleList) == len(updated.resourceList) == 1
    assert all(len(row.objectName) == 6 for rows in (updated.assetBundleList, updated.resourceList) for row in rows)
    assert not unchanged.assetBundleList and not unchanged.resourceList
    fresh, _ = pin_manifest_revision(raw, tmp_path / "fresh.json", language="ko", sdk_identity_compat=True)
    assert Database.FromString(fresh).revision == 1162
    revisions = [1162]
    for language in ("en", "ja", "ko"):
        selected, _ = pin_manifest_revision(raw, state, language=language, sdk_identity_compat=language != "ja")
        revisions.append(Database.FromString(selected).revision)
        same, _ = pin_manifest_revision(raw, state, language=language, sdk_identity_compat=language != "ja")
        assert same == selected
    assert revisions == [1162, 1163, 1164, 1165]
    assert original.SerializeToString() == raw


def test_updated_korean_bytes_advance_cached_revision_without_clearing_existing_files(tmp_path):
    """A KO bundle update must refresh an already-KO SDK, even with a reused producer revision."""
    original = database(); original.revision = 1163
    original_raw = original.SerializeToString()
    state = tmp_path / "client-resource-revision-android.json"
    source = tmp_path / "source"; source.mkdir()
    account = tmp_path / "account.sqlite"; account.write_bytes(b"existing account must remain unchanged")
    cache_root = tmp_path / "cache"
    previous = None
    for number, body in enumerate(("기존 한국어 번역", "갱신된 한국어 번역")):
        (source / "adv_bond_ai_01_01.txt").write_text(body, encoding="utf-8")
        directory = tmp_path / ("prepared-" + str(number))
        build_resource_overlay(original_raw, source, directory, language="ko", revision=1164, source=SOURCE)
        layer = ResourceTranslation(directory, original_raw, language="ko")
        try:
            pinned, compatible = pin_manifest_revision(layer.manifest, state, language="ko", sdk_identity_compat=True)
            revision = Database.FromString(pinned).revision
            gateway_manifest = OctoManifest(pinned, aes_key=KEY, client_key="synthetic",
                base_url="http://127.0.0.1:8080", aes_cbc=aes, allow_previous_revisions=compatible,
                object_aliases=layer.object_aliases)
            resource = next(row for row in gateway_manifest.objects.values() if row.kind == "resources")
            cache = OctoCache(cache_root, allow_download=False, local_source=layer.open_source)
            try:
                with cache.open_verified(resource) as incoming:
                    assert incoming.read() == body.encode("utf-8")
            finally:
                cache.close()
            if previous is not None:
                assert revision == previous["revision"] + 1
                response = gateway_manifest.manifest_response(
                    f"/v2/pub/a/212/v/205051/list/{previous['revision']}",
                    {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic"})
                update = Database.FromString(decrypt_manifest(response, aes_key=KEY, aes_cbc=aes))
                assert update.revision == revision and len(update.resourceList) == 1
                assert update.resourceList[0].md5 == resource.md5 != previous["md5"]
                assert len(update.resourceList[0].objectName) == 6
                assert previous["file"].read_bytes() == "기존 한국어 번역".encode("utf-8")
            same, _ = pin_manifest_revision(layer.manifest, state, language="ko", sdk_identity_compat=True)
            assert same == pinned
            previous = {"revision": revision, "md5": resource.md5,
                "file": cache_root / resource.cache_key[:2] / (resource.cache_key + ".bin")}
            assert account.read_bytes() == b"existing account must remain unchanged"
        finally:
            layer.close()
    assert len(list(cache_root.rglob("*.bin"))) == 2


@pytest.mark.parametrize("flag", [None, 1, "true"])
def test_sdk_identity_revision_flag_is_an_explicit_boolean(tmp_path, flag):
    with pytest.raises(ValueError, match="boolean"):
        pin_manifest_revision(database().SerializeToString(), tmp_path / "revision.json",
            language="ko", sdk_identity_compat=flag)
    assert not (tmp_path / "revision.json").exists()


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
    previous_revision = gateway.manifest.revision
    assert previous_revision == 1089  # Prepared1088 must supersede a broken cached1088.
    gateway.close()
    japanese, _ = create_octo_gateway(private, "http://127.0.0.1:8080", aes_cbc=aes,
        resource_cache_dir=public, language="ja", allow_downloads=False)
    restored = next(value for value in japanese.manifest.objects.values() if value.kind == "resources")
    assert japanese.manifest.revision > previous_revision
    assert restored.object_name == original_name and japanese.translation_layer is None
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
        assert all(record.object_name.startswith("Obj") and len(record.object_name) == 6
                   for record in catalog.records)
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
    monkeypatch.setattr("idoly_local.resource_translation.ResourceTranslation", ObservedLayer)
    coverage = validate_prepared_translations(tmp_path / "staged", private, platform="android")
    assert set(coverage) == {"ko", "en"} and all(value["translated"] == 1 for value in coverage.values())
    assert len(opened) == 2 and all(layer._archive is None for layer in opened)
    assert not list(private.glob("client-resource-revision-*.json"))
    altered = database(); altered.assetBundleList[0].priority += 1
    wrong = altered.SerializeToString(); settings["manifest_sha256"] = hashlib.sha256(wrong).hexdigest()
    (archive / "manifest.pb").write_bytes(wrong); (archive / "settings.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="identity|not approved"):
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


def _prepared_lifetime_fixture(tmp_path, platform):
    private = tmp_path / "private"
    archive = private / ("public-octo-ios" if platform == "ios" else "public-octo")
    archive.mkdir(parents=True)
    original = database()
    original.revision = 1159 if platform == "ios" else 1087
    if platform == "ios":
        for rows in (original.assetBundleList, original.resourceList):
            for row in rows:
                row.uploadVersionId = 102050
    raw = original.SerializeToString()
    settings = {"schema": 1, "application_id": 212,
                "application_version": 105051 if platform == "ios" else 205051,
                "revision": original.revision, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "aes_key_hex": KEY.hex(), "client_key": "synthetic"}
    (archive / "manifest.pb").write_bytes(raw)
    (archive / "settings.json").write_text(json.dumps(settings))
    source = tmp_path / "lifetime-source"
    source.mkdir()
    (source / "adv_bond_ai_01_01.txt").write_text("prepared translation")
    staged = tmp_path / "staged"
    for language in ("ko", "en"):
        build_resource_overlay(raw, source, staged / language / platform,
            language=language, revision=original.revision + 1, source=SOURCE)
    return private, staged, archive, raw


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_previous_language_is_released_at_next_constructor_entry(tmp_path, monkeypatch, platform):
    from idoly_local import resource_translation_runtime as runtime
    private, staged, archive, raw = _prepared_lifetime_fixture(tmp_path, platform)
    references, events = {}, []

    class ObservedLayer(ResourceTranslation):
        def __init__(self, *args, **kwargs):
            language = kwargs["language"]
            if language == "en":
                # A close-order assertion alone misses retained manifest/report
                # memory. There must be no strong owner at this exact boundary.
                assert references["ko"]() is None
                assert events == [("opened", "ko"), ("closed", "ko")]
            super().__init__(*args, **kwargs)
            references[language] = weakref.ref(self)
            events.append(("opened", language))

        def close(self):
            opened_archive = self._archive
            assert opened_archive is not None
            super().close()
            assert opened_archive.fp is None and self._archive is None
            events.append(("closed", self.language))

    monkeypatch.setattr("idoly_local.resource_translation.ResourceTranslation", ObservedLayer)
    coverage = validate_prepared_translations(staged, private, platform=platform)
    expected = {"adv_resources": 1, "translated": 1, "missing": 0, "unchanged_original": 0}
    assert coverage == {"ko": expected, "en": expected}
    assert events == [("opened", "ko"), ("closed", "ko"), ("opened", "en"), ("closed", "en")]
    assert set(references) == {"ko", "en"} and all(reference() is None for reference in references.values())
    assert (archive / "manifest.pb").read_bytes() == raw
    assert not list(private.glob("client-resource-revision-*.json"))


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_next_constructor_failure_preserves_exception_after_releasing_previous_language(
        tmp_path, monkeypatch, platform):
    from idoly_local import resource_translation_runtime as runtime
    private, staged, archive, raw = _prepared_lifetime_fixture(tmp_path, platform)
    references, events = {}, []
    failure = ValueError("second language constructor rejected")

    class ObservedLayer(ResourceTranslation):
        def __init__(self, *args, **kwargs):
            language = kwargs["language"]
            if language == "en":
                assert references["ko"]() is None
                assert events == [("opened", "ko"), ("closed", "ko")]
                events.append(("rejected", "en"))
                raise failure
            super().__init__(*args, **kwargs)
            references[language] = weakref.ref(self)
            events.append(("opened", language))

        def close(self):
            opened_archive = self._archive
            super().close()
            assert opened_archive.fp is None
            events.append(("closed", self.language))

    monkeypatch.setattr("idoly_local.resource_translation.ResourceTranslation", ObservedLayer)
    with pytest.raises(ValueError) as caught:
        validate_prepared_translations(staged, private, platform=platform)
    assert caught.value is failure
    assert references["ko"]() is None
    assert events == [("opened", "ko"), ("closed", "ko"), ("rejected", "en")]
    assert (archive / "manifest.pb").read_bytes() == raw
    assert not list(private.glob("client-resource-revision-*.json"))


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_coverage_copy_failure_still_closes_archive_and_releases_layer(tmp_path, monkeypatch, platform):
    from idoly_local import resource_translation_runtime as runtime
    private, staged, archive, raw = _prepared_lifetime_fixture(tmp_path, platform)
    references, closed = [], []
    failure = RuntimeError("coverage could not be copied")

    class BadCoverage:
        def __iter__(self):
            raise failure

    class ObservedLayer(ResourceTranslation):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            references.append(weakref.ref(self))
            self.report = {"coverage": BadCoverage()}

        def close(self):
            opened_archive = self._archive
            super().close()
            closed.append((self.language, opened_archive.fp is None))

    monkeypatch.setattr("idoly_local.resource_translation.ResourceTranslation", ObservedLayer)
    with pytest.raises(RuntimeError) as caught:
        validate_prepared_translations(staged, private, platform=platform)
    assert caught.value is failure
    assert closed == [("ko", True)] and len(references) == 1 and references[0]() is None
    assert (archive / "manifest.pb").read_bytes() == raw
    assert not list(private.glob("client-resource-revision-*.json"))


def _legacy_resource_fingerprint(raw, language, sdk_identity_compat):
    identity = language.encode("ascii") + b"\0" + raw
    if sdk_identity_compat:
        identity = b"octo-sdk-six-byte-object-name-v1\0" + identity
    return hashlib.sha256(identity).hexdigest()


def _expected_complete_revision_snapshot(raw, revision):
    expected = Database.FromString(raw)
    expected.revision = revision
    for rows in (expected.assetBundleList, expected.resourceList):
        for row in rows:
            if row.state != 4:
                row.state = 2
    return expected.SerializeToString(deterministic=True)


@pytest.mark.parametrize("language", ["ja", "ko", "en"])
@pytest.mark.parametrize("sdk_identity_compat", [False, True])
@pytest.mark.parametrize("preserve_original", [False, True])
def test_fresh_revision_fingerprint_matches_legacy_bytes_and_preserve_original_contract(
        tmp_path, language, sdk_identity_compat, preserve_original):
    # Include an unknown wire field so hashing must cover the original bytes,
    # rather than a normalized/re-serialized protobuf representation.
    raw = database().SerializeToString() + b"\x98\x06\x01"
    state = tmp_path / "revision.json"
    selected, compatible = pin_manifest_revision(raw, state, language=language,
        sdk_identity_compat=sdk_identity_compat, preserve_original=preserve_original)
    if preserve_original and not sdk_identity_compat:
        assert selected == raw and compatible is False and not state.exists()
    else:
        revision = 1087 + int(sdk_identity_compat)
        assert compatible is True
        assert selected == _expected_complete_revision_snapshot(raw, revision)
        assert json.loads(state.read_text()) == {
            "schema": 1, "fingerprint": _legacy_resource_fingerprint(raw, language, sdk_identity_compat),
            "revision": revision}


@pytest.mark.parametrize("language", ["ja", "ko", "en"])
@pytest.mark.parametrize("sdk_identity_compat", [False, True])
@pytest.mark.parametrize("preserve_original", [False, True])
def test_existing_legacy_fingerprint_reuses_revision_without_rewriting_state(
        tmp_path, language, sdk_identity_compat, preserve_original):
    raw = database().SerializeToString() + b"\x98\x06\x01"
    state = tmp_path / "revision.json"
    previous = {"schema": 1,
                "fingerprint": _legacy_resource_fingerprint(raw, language, sdk_identity_compat),
                "revision": 1199}
    encoded = json.dumps(previous, indent=2).encode("ascii") + b"\n"
    state.write_bytes(encoded)
    selected, compatible = pin_manifest_revision(raw, state, language=language,
        sdk_identity_compat=sdk_identity_compat, preserve_original=preserve_original)
    assert compatible is True
    assert selected == _expected_complete_revision_snapshot(raw, 1199)
    assert state.read_bytes() == encoded


@pytest.fixture
def revision_parse_counter(monkeypatch):
    from idoly_local import resource_translation_runtime as runtime
    original=runtime.Database;calls=[]
    class CountedDatabase:
        @staticmethod
        def FromString(raw):
            calls.append(raw);return original.FromString(raw)
    monkeypatch.setattr(runtime,"Database",CountedDatabase)
    runtime._REVISION_CACHE.clear()
    yield runtime,calls
    runtime._REVISION_CACHE.clear()


def test_revision_cache_reuses_exact_wire_and_rechecks_committed_state(tmp_path,revision_parse_counter):
    runtime,calls=revision_parse_counter;path=tmp_path/"revision.json"
    raw=database().SerializeToString()+b"\x80\x4b\x7b"
    first=runtime.pin_manifest_revision(raw,path,language="ko",sdk_identity_compat=True)
    saved=path.read_bytes();modified=path.stat().st_mtime_ns
    second=runtime.pin_manifest_revision(raw,path,language="ko",sdk_identity_compat=True)
    assert second==first and len(calls)==1 and path.read_bytes()==saved and path.stat().st_mtime_ns==modified
    assert b"\x80\x4b\x7b" in second[0]
    runtime._REVISION_CACHE.clear()
    assert runtime.pin_manifest_revision(raw,path,language="ko",sdk_identity_compat=True)==first
    assert len(calls)==2


@pytest.mark.parametrize("damage",["revision","language","manifest","invalid-state","symlink","removed-state"])
def test_revision_cache_cannot_reuse_a_stale_or_invalid_state(tmp_path,revision_parse_counter,damage):
    runtime,calls=revision_parse_counter;path=tmp_path/"revision.json";raw=database().SerializeToString()
    first,_=runtime.pin_manifest_revision(raw,path,language="ko")
    before=Database.FromString(first).revision
    language="ko"
    if damage=="revision":
        value=json.loads(path.read_text());value["revision"]+=9;path.write_text(json.dumps(value))
    elif damage=="language":language="en"
    elif damage=="manifest":
        value=database();value.resourceList[0].name="adv_other.txt";raw=value.SerializeToString()
    elif damage=="invalid-state":path.write_text('{}')
    elif damage=="symlink":
        actual=tmp_path/"actual.json";path.rename(actual);path.symlink_to(actual)
    elif damage=="removed-state":path.unlink()
    if damage in ("invalid-state","symlink"):
        with pytest.raises((ValueError,OSError)):runtime.pin_manifest_revision(raw,path,language=language)
        assert len(calls)==1
    else:
        selected,_=runtime.pin_manifest_revision(raw,path,language=language)
        assert len(calls)==2 and path.is_file()
        revision=Database.FromString(selected).revision
        if damage=="revision":assert revision==before+9
        elif damage in ("language","manifest"):assert revision>before
        else:assert revision==database().revision


def test_original_unchanged_revision_cache_does_not_create_state_or_accept_changed_bytes(tmp_path,revision_parse_counter):
    runtime,calls=revision_parse_counter;path=tmp_path/"revision.json";raw=database().SerializeToString()
    assert runtime.pin_manifest_revision(raw,path,language="ja",preserve_original=True)==(raw,False)
    assert runtime.pin_manifest_revision(raw,path,language="ja",preserve_original=True)==(raw,False)
    assert not path.exists() and len(calls)==1
    from google.protobuf.message import DecodeError
    with pytest.raises(DecodeError):runtime.pin_manifest_revision(b"truncated protobuf",path,language="ja",preserve_original=True)
    assert not path.exists() and len(calls)==2


def test_revision_wire_cache_has_a_fixed_entry_and_byte_budget(tmp_path,revision_parse_counter):
    runtime,_=revision_parse_counter;raw=database().SerializeToString()
    for number in range(12):
        runtime.pin_manifest_revision(raw,tmp_path/(str(number)+".json"),language="ko")
        assert len(runtime._REVISION_CACHE)<=runtime._REVISION_CACHE_ENTRIES
        assert sum(len(value[0]) for value in runtime._REVISION_CACHE.values())<=runtime._REVISION_CACHE_BYTES
