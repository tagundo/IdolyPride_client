"""Mixed object identities observed in diagnostics21 must serve checked text.

Payloads below are test text; the two request paths/fingerprints are taken from
the diagnostic and the independently pinned original/translated catalogs.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import http.client
import io
import threading

import pytest

from idoly_local.assets import create_asset_server
from idoly_local.octo_cache import OctoCache
from idoly_local.octo_http import OctoGateway
from idoly_local.octo_manifest import Database, OctoManifest, OctoManifestError, OctoObject, OctoRequestError
from idoly_local.resource_translation import ResourceTranslation
from idoly_local.resource_translation_build import build_resource_overlay

URL = "https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media"
OBSERVED = (
    ("adv_event_2510_01_01.txt", "oRlhqS", 16444311832531005964,
     "local_ko_8eee3e57ea9b253bff4bfac34186_fcb5fcdd50dd", "25d1a14e7fffa4db"),
    ("adv_main_01_01_02.txt", "mmJTyX", 9409560276416915797,
     "local_ko_b9be7afaa175df8d980420d38a7e_abc5e9cdb431", "6c10406869023b10"),
)


def manifest(raw, aliases=None):
    return OctoManifest(raw, aes_key=bytes(32), client_key="synthetic-alias-check",
        base_url="http://127.0.0.1:8080", aes_cbc=lambda _encrypt, _key, _iv, value: value,
        object_aliases=aliases)


def fixture():
    db = Database(revision=1089, urlFormat=URL)
    db.assetBundleList.add(id=1, name="stage", size=3, md5=hashlib.md5(b"old").hexdigest(),
        objectName="stage", generation=1, uploadVersionId=202050, state=2)
    aliases, payloads = {}, {}
    for number, (name, old_name, generation, new_name, fingerprint) in enumerate(OBSERVED, 1):
        payload = ("[title title=테스트]\n" + name).encode()
        db.resourceList.add(id=number, name=name, size=len(payload),
            md5=hashlib.md5(payload).hexdigest(), objectName=new_name, generation=generation,
            uploadVersionId=202050, state=2)
        record = OctoObject("resources", 202050, new_name, generation, len(payload),
                            hashlib.md5(payload).hexdigest(), name)
        aliases[("resources", 202050, old_name, generation)] = record
        payloads[record.cache_key] = payload
        path = f"/octo/202050/resources/{old_name}/{generation}"
        assert hashlib.sha256(path.encode()).hexdigest()[:16] == fingerprint
    return db.SerializeToString(), aliases, payloads


@contextmanager
def serving(tmp_path, aliases, payloads, raw, *, corrupt=False):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Translated aliases must never contact the CDN")
    def local_source(record):
        return io.BytesIO(b"corrupt" if corrupt else payloads[record.cache_key])
    cache = OctoCache(tmp_path / "cache", fetcher=forbidden, allow_download=False,
                      local_source=local_source)
    gateway = OctoGateway(manifest(raw, aliases), cache)
    public = tmp_path / "public"; public.mkdir()
    server = create_asset_server("127.0.0.1", 0, public, octo=gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def request(path, *, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()
    try:
        yield request, cache, calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3); gateway.close()


def test_observed_paths_resolve_to_canonical_objects_without_changing_catalog():
    raw, aliases, _ = fixture(); before = manifest(raw); after = manifest(raw, aliases)
    assert len(after.objects) == 3 and after.objects == before.objects
    for identity, record in aliases.items():
        path = "/octo/{1}/{0}/{2}/{3}".format(*identity)
        with pytest.raises(OctoRequestError) as failure:
            before.lookup_object(path)
        assert failure.value.status == 404
        resolved = after.lookup_object(path)
        assert resolved is after.objects[record.identity] and resolved == record
        assert resolved.object_name != identity[2]
    aliases.clear()
    # Caller mutation after validation must not revoke or redirect an alias.
    assert after.lookup_object("/octo/202050/resources/oRlhqS/16444311832531005964").name == OBSERVED[0][0]


def test_observed_mixed_paths_get_head_and_range_use_verified_offline_bytes(tmp_path):
    raw, aliases, payloads = fixture()
    with serving(tmp_path, aliases, payloads, raw) as (request, cache, calls):
        for identity, record in aliases.items():
            path = "/octo/{1}/{0}/{2}/{3}".format(*identity)
            status, headers, body = request(path)
            assert status == 200 and body == payloads[record.cache_key]
            assert headers["ETag"] == '"' + record.md5 + '"'
            assert int(headers["Content-Length"]) == record.size
            status, headers, body = request(path, method="HEAD")
            assert status == 200 and body == b"" and int(headers["Content-Length"]) == record.size
            status, headers, body = request(path, headers={"Range": "bytes=2-7"})
            assert status == 206 and body == payloads[record.cache_key][2:8]
            assert headers["Content-Range"] == f"bytes 2-7/{record.size}"
            with cache.open_verified(record) as stored:
                assert hashlib.md5(stored.read()).hexdigest() == record.md5
        assert not calls and len(list(cache.root.rglob("*.bin"))) == 2


@pytest.mark.parametrize("path", [
    "/octo/202050/resources/oRlhqS/16444311832531005963",
    "/octo/202051/resources/oRlhqS/16444311832531005964",
    "/octo/202050/assetbundle/oRlhqS/16444311832531005964",
    "/octo/202050/resources/unknown/16444311832531005964",
    "/octo/202050/resources/%6fRlhqS/16444311832531005964",
    "/octo/202050/resources/oRlhqS/16444311832531005964?ignored=1",
    "/octo/202050/resources/oRlhqS/-2002432241178545652",
])
def test_aliases_do_not_widen_unknown_or_noncanonical_paths(path):
    raw, aliases, _ = fixture()
    with pytest.raises(OctoRequestError) as failure:
        manifest(raw, aliases).lookup_object(path)
    assert failure.value.status == 404


def test_aliases_do_not_bypass_local_content_verification(tmp_path):
    raw, aliases, payloads = fixture()
    with serving(tmp_path, aliases, payloads, raw, corrupt=True) as (request, cache, calls):
        status, _headers, _body = request("/octo/202050/resources/oRlhqS/16444311832531005964")
        assert status == 502 and not calls
        assert not list(cache.root.rglob("*.bin")) and not list(cache.root.rglob("*.part"))


def test_alias_targets_and_shape_are_checked_against_primary_whitelist():
    raw, aliases, _ = fixture(); identity, target = next(iter(aliases.items()))
    bad = [
        [], {identity: replace(target, md5="a" * 32)}, {identity: replace(target, size=target.size + 1)},
        {identity: replace(target, object_name="remote")}, {identity: replace(target, kind="assetbundle")},
        {identity: replace(target, object_name=[])},
        {target.identity: target},
        {("resources", True, identity[2], identity[3]): target},
        {("resources", 202051, identity[2], identity[3]): target},
        {("resources", 202050, identity[2], identity[3] - 1): target},
        {("resources", 202050, "../object", identity[3]): target},
        {("resources", 202050, "object", 2**64): target},
        {("resources", 202050, "object_" + str(i), identity[3]): target for i in range(8193)},
    ]
    for value in bad:
        with pytest.raises(OctoManifestError, match="alias"):
            manifest(raw, value)


def test_translation_layer_derives_immutable_aliases_only_for_verified_changed_rows(tmp_path):
    db = Database(revision=1087, urlFormat=URL)
    db.assetBundleList.add(id=1, name="stage", size=3, md5="a" * 32, objectName="stage",
        generation=1, uploadVersionId=202050, state=3)
    for number, name in enumerate(("adv_main_01_01_02.txt", "adv_untranslated_01.txt"), 1):
        db.resourceList.add(id=number, name=name, size=3, md5="b" * 32,
            objectName="original_" + str(number), generation=1, uploadVersionId=202050, state=3)
    raw = db.SerializeToString(); source = tmp_path / "source"; source.mkdir()
    text = "[title title=번역]\n테스트 대사".encode()
    (source / "adv_main_01_01_02.txt").write_bytes(text)
    build_resource_overlay(raw, source, tmp_path / "prepared", language="ko", revision=1088,
        source={"repository": "https://example.invalid/text", "revision": "a" * 40})
    layer = ResourceTranslation(tmp_path / "prepared", raw, language="ko")
    try:
        assert len(layer.object_aliases) == 1
        identity, target = next(iter(layer.object_aliases.items()))
        assert identity == ("resources", 202050, "original_1", target.generation)
        resolved = manifest(layer.manifest, layer.object_aliases).lookup_object(
            "/octo/{1}/{0}/{2}/{3}".format(*identity))
        with layer.open_source(resolved) as stream:
            assert stream.read() == text
        with pytest.raises(TypeError):
            layer.object_aliases[identity] = replace(target, size=1)
        assert db.SerializeToString() == raw
    finally:
        layer.close()
