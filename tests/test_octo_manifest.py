from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import unittest

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from idoly_local.octo_manifest import (
    Database, OctoManifest, OctoManifestError, OctoRequestError, decrypt_manifest,
)


KEY = hashlib.sha256(b"synthetic application A").digest()
HEADERS = {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic-key"}
ORIGINAL_URL = ("https://d2ilil7yh5oi1v.cloudfront.net/"
                "solis-{v}-{type}/{o}?generation={g}&alt=media")
LOCAL_URL = "http://127.0.0.1:8080/octo/{v}/{type}/{o}/{g}"


def aes(encrypt, key, iv, data):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


def fixture():
    database = Database(revision=1087, urlFormat=ORIGINAL_URL, tagname=["shader", "home"])
    one = database.assetBundleList.add(id=1, filepath="original/path", name="actor-shader",
        size=7, crc=123456, priority=2, tagid=[1], state=2,
        md5=hashlib.md5(b"bundle1").hexdigest(), objectName="Asset_1", generation=1711343248828371,
        uploadVersionId=202050)
    database.assetBundleList.add(id=2, name="actor-body", size=7, crc=77,
        dependencie=[1], state=2, md5=hashlib.md5(b"bundle2").hexdigest(), objectName="Asset-2",
        generation=1711343248828372, uploadVersionId=202050)
    database.resourceList.add(id=1, name="story.txt", size=5, state=2, crc=456,
        md5=hashlib.md5(b"story").hexdigest(), objectName="Res001", generation=1711343248828373,
        uploadVersionId=202050)
    # Unknown data fields must survive the URL rewrite along with known fields.
    one.MergeFromString(b"\x9a\x06\x06opaque")  # field99, length-delimited
    database.MergeFromString(b"\xa0\x06\x7b")  # field100, varint123
    return database


def archive(database=None, **kwargs):
    args = dict(aes_key=KEY, client_key="synthetic-key", base_url="http://127.0.0.1:8080", aes_cbc=aes)
    args.update(kwargs)
    plain = (database if database is not None else fixture()).SerializeToString(deterministic=True)
    return OctoManifest(plain, **args)


def response(archive, revision=0, headers=None):
    return archive.manifest_response(f"/v2/pub/a/212/v/205051/list/{revision}",
                                     HEADERS if headers is None else headers)


def independent_decode(wire):
    # This decoder intentionally does not use the module's decrypt function.
    plain = unpad(AES.new(KEY, AES.MODE_CBC, wire[:16]).decrypt(wire[16:]), 16)
    return Database.FromString(plain)


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128); value >>= 7
    return bytes(out) + bytes((value,))


def bytes_field(number, payload):
    return varint(number*8+2) + varint(len(payload)) + payload


class OctoManifestProtocolTests(unittest.TestCase):
    def test_cold_archive_changes_only_url_preserving_unknown_fields(self):
        source = fixture()
        original = source.SerializeToString(deterministic=True)
        server = archive(source)
        result = independent_decode(response(server))
        expected = fixture(); expected.urlFormat = LOCAL_URL
        self.assertEqual(result, expected)
        self.assertEqual(source.SerializeToString(deterministic=True), original)
        result.ClearField("urlFormat"); source.ClearField("urlFormat")
        self.assertEqual(result.SerializeToString(deterministic=True), source.SerializeToString(deterministic=True))
        self.assertEqual(server.revision, 1087)
        self.assertEqual(len(server.objects), 3)

    def test_original_raw_wire_preserved_including_order_unknowns_and_unpacked_integers(self):
        source = fixture()
        first = source.assetBundleList[0].SerializeToString(deterministic=True)
        first += b"\x38\x02\x40\x02"  # Unpacked tagid2/dependencie2; original packed entries stay.
        before = (bytes_field(2, first) + b"\xd1\x05" + b"12345678"
                  + b"\x08" + varint(1087))
        after = (bytes_field(4, source.resourceList[0].SerializeToString(deterministic=True))
                 + bytes_field(3, b"home")
                 + bytes_field(2, source.assetBundleList[1].SerializeToString(deterministic=True))
                 + b"\xdd\x05ABCD"  # Unknown fixed32.
                 + b"\xe0\x05\x82\x00")  # Unknown varint with a valid overlong representation.
        for url_tag in (b"\x2a", b"\xaa\x00"):
            with self.subTest(url_tag=url_tag):
                raw = before + url_tag + varint(len(ORIGINAL_URL)) + ORIGINAL_URL.encode() + after
                server = OctoManifest(raw, aes_key=KEY, client_key="synthetic-key",
                                      base_url="http://127.0.0.1:8080", aes_cbc=aes)
                encrypted = response(server)
                decoded_wire = unpad(AES.new(KEY, AES.MODE_CBC, encrypted[:16]).decrypt(encrypted[16:]), 16)
                self.assertEqual(decoded_wire, before + url_tag + varint(len(LOCAL_URL)) + LOCAL_URL.encode() + after)
                expected = Database.FromString(raw); expected.urlFormat = LOCAL_URL
                self.assertEqual(Database.FromString(decoded_wire), expected)
                self.assertEqual(list(expected.assetBundleList[0].tagid), [1,2])

    def test_missing_duplicate_or_wrong_wire_url_field_is_rejected(self):
        source = fixture()
        raw = source.SerializeToString(deterministic=True)
        source.ClearField("urlFormat")
        for value in (source.SerializeToString(), raw + bytes_field(5, ORIGINAL_URL.encode()),
                      raw + b"\x28\x01", raw + bytes_field(5, b"https://different.invalid")):
            with self.subTest(raw_length=len(value)), self.assertRaisesRegex(OctoManifestError, "URL field"):
                OctoManifest(value, aes_key=KEY, client_key="synthetic-key",
                             base_url="http://127.0.0.1:8080", aes_cbc=aes)

    def test_top_level_wire_bounds_overflow_and_groups_fail_before_parsing(self):
        for raw in (b"\x00", b"\x80"*11, b"\x80"*9+b"\x02",
                    b"\x2a\x80", b"\x2a\x7fshort", b"\x09short",
                    b"\x0dabc", b"\x33\x34", b"\x34", b"\x0e", b"\x0f"):
            with self.subTest(raw=raw), self.assertRaisesRegex(OctoManifestError, "protobuf"):
                OctoManifest(raw, aes_key=KEY, client_key="synthetic-key",
                             base_url="http://127.0.0.1:8080", aes_cbc=aes)

    def test_current_revision_is_real_empty_delta(self):
        result = independent_decode(response(archive(), 1087))
        self.assertEqual(result, Database(revision=1087, urlFormat=LOCAL_URL))
        self.assertFalse(result.assetBundleList)
        self.assertFalse(result.resourceList)

    def test_old_and_future_revisions_are_explicitly_unavailable(self):
        server = archive()
        for revision in (1, 1086, 1088, 2**31-1):
            with self.subTest(revision=revision), self.assertRaises(OctoRequestError) as caught:
                response(server, revision)
            self.assertEqual(caught.exception.status, 409)

    def test_wrong_app_version_and_noncanonical_routes_do_not_match(self):
        for path in ("/v2/pub/a/214/v/205051/list/0", "/v2/pub/a/212/v/205050/list/0",
                     "/v2/pub/a/212/v/205051/list/00", "/v2/pub/a/212/v/205051/list/-1",
                     "/v2/pub/a/212/v/205051/list/+0", "/v2/pub/a/212/v/205051/list/0?x=1",
                     "https://api.octo-cloud.com/v2/pub/a/212/v/205051/list/0",
                     "/v2/pub/a/212/v/205051/list/%30", "/v2/pub/a/212/v/205051/list/0/"):
            with self.subTest(path=path), self.assertRaises(OctoRequestError) as caught:
                archive().manifest_response(path, HEADERS)
            self.assertEqual(caught.exception.status, 404)

    def test_application_headers_required_without_echoing_supplied_values(self):
        for headers in ({}, {"X-OCTO-KEY":"wrong-private-value", "Accept":HEADERS["Accept"]},
                        {"X-OCTO-KEY":"synthetic-key", "Accept":"application/x-protobuf"},
                        {"X-OCTO-KEY":"synthetic-key", "Accept":"x-octo-app/214"},
                        {"X-OCTO-KEY":"synthetic-key", "Accept":HEADERS["Accept"]+"\r\n"},
                        {"X-OCTO-KEY":"synthetic-key", "Accept":None},
                        {"X-OCTO-KEY":"synthetic-key", "x-octo-key":"synthetic-key", "Accept":HEADERS["Accept"]}):
            with self.subTest(headers=headers), self.assertRaises(OctoRequestError) as caught:
                response(archive(), headers=headers)
            self.assertEqual(caught.exception.status, 403)
            self.assertNotIn("wrong-private-value", str(caught.exception))

    def test_http_header_names_and_mime_tokens_are_case_insensitive(self):
        wire = response(archive(), headers={"x-octo-key":"synthetic-key",
            "aCcEpT":" APPLICATION/X-PROTOBUF, X-OCTO-APP/212 "})
        self.assertEqual(independent_decode(wire).revision, 1087)

    def test_fresh_iv_and_generic_aes_callback(self):
        calls = []
        def bridge(encrypt, key, iv, data):
            calls.append((encrypt, key, iv, len(data)))
            return aes(encrypt, key, iv, data)
        server = archive(aes_cbc=bridge)
        first, second = response(server), response(server)
        self.assertNotEqual(first[:16], second[:16])
        self.assertEqual(independent_decode(first), independent_decode(second))
        self.assertEqual(calls[0][:3], (True, KEY, first[:16]))
        self.assertEqual(calls[0][3] % 16, 0)
        plain = decrypt_manifest(first, aes_key=KEY, aes_cbc=bridge)
        self.assertEqual(Database.FromString(plain), independent_decode(first))
        self.assertFalse(calls[-1][0])

    def test_backend_failures_never_echo_secrets_or_accept_bad_lengths(self):
        def fail(*_):
            raise RuntimeError("private-backend-key-value")
        for backend in (fail, lambda *_: b"", lambda *_: 16, lambda *_: None):
            with self.subTest(backend=backend), self.assertRaises(OctoManifestError) as caught:
                response(archive(aes_cbc=backend))
            self.assertNotIn("private-backend-key-value", str(caught.exception))

    def test_invalid_encrypted_lengths_and_padding_fail(self):
        for wire in (b"", b"x"*16, b"x"*31, b"x"*33):
            with self.subTest(length=len(wire)), self.assertRaises(OctoManifestError):
                decrypt_manifest(wire, aes_key=KEY, aes_cbc=aes)
        for padded in (b"x"*16, b"x"*15+b"\0", b"x"*14+b"\1\2"):
            wire = b"i"*16 + AES.new(KEY, AES.MODE_CBC, b"i"*16).encrypt(padded)
            with self.subTest(padding=padded[-2:]), self.assertRaisesRegex(OctoManifestError, "padding"):
                decrypt_manifest(wire, aes_key=KEY, aes_cbc=aes)

    def test_strict_loopback_origin_only(self):
        for base in ("https://127.0.0.1:8080", "http://localhost:8080", "http://127.0.0.2:8080",
                     "http://127.0.0.1:0", "http://127.0.0.1:08080", "http://127.0.0.1:65536",
                     "http://name:password@127.0.0.1:8080", "http://127.0.0.1:8080/path",
                     "http://127.0.0.1:8080?key=x", "http://127.0.0.1:8080#fragment"):
            with self.subTest(base=base), self.assertRaisesRegex(OctoManifestError, "origin"):
                archive(base_url=base)
        self.assertEqual(archive(base_url="http://127.0.0.1:8080/").local_url_format, LOCAL_URL)

    def test_invalid_key_backend_and_manifest_fail(self):
        for kwargs in ({"aes_key":b"x"*16}, {"aes_key":"x"*32}, {"aes_cbc":None},
                       {"client_key":""}, {"client_key":"secret\nheader"}, {"client_key":"비밀"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(OctoManifestError):
                archive(**kwargs)
        for plain in (b"", b"\xff", b"\0"):
            with self.subTest(plain=plain), self.assertRaises(OctoManifestError):
                OctoManifest(plain, aes_key=KEY, client_key="synthetic-key", base_url="http://127.0.0.1", aes_cbc=aes)


class OctoWhitelistTests(unittest.TestCase):
    def test_canonical_record_contains_fixed_origin_and_immutable_identity(self):
        server = archive()
        item = server.lookup_object("/octo/202050/assetbundle/Asset_1/1711343248828371")
        self.assertEqual(item.identity, ("assetbundle",202050,"Asset_1",1711343248828371))
        self.assertEqual(item.upstream_url, "https://d2ilil7yh5oi1v.cloudfront.net/"
                         "solis-202050-assetbundle/Asset_1?generation=1711343248828371&alt=media")
        self.assertEqual(item.cache_key, hashlib.sha256(
            b"assetbundle\n202050\nAsset_1\n1711343248828371").hexdigest())
        with self.assertRaises(FrozenInstanceError):
            item.size = 99
        with self.assertRaises(TypeError):
            server.objects[item.identity] = item
        resource = server.lookup_object("/octo/202050/resources/Res001/1711343248828373")
        self.assertIn("solis-202050-resources/", resource.upstream_url)

    def test_arbitrary_url_and_unknown_content_never_resolve(self):
        server = archive()
        for path in ("/octo/202050/assetbundle/Asset_1/1711343248828372",
                     "/octo/202051/assetbundle/Asset_1/1711343248828371",
                     "/octo/202050/resources/Asset_1/1711343248828371",
                     "/octo/0202050/assetbundle/Asset_1/1711343248828371",
                     "/octo/202050/ab/Asset_1/1711343248828371",
                     "/octo/202050/assetbundle/../1711343248828371",
                     "/octo/202050/assetbundle/%41sset_1/1711343248828371",
                     "/octo/202050/assetbundle/Asset_1/01711343248828371",
                     "/octo/202050/assetbundle/Asset_1/1711343248828371?url=https://private.invalid",
                     "https://private.invalid/octo/202050/assetbundle/Asset_1/1711343248828371"):
            with self.subTest(path=path), self.assertRaises(OctoRequestError) as caught:
                server.lookup_object(path)
            self.assertEqual(caught.exception.status, 404)

    def test_conflicting_manifest_identities_rejected(self):
        changes = (lambda db: setattr(db.assetBundleList[1], "id", 1),
                   lambda db: setattr(db.assetBundleList[1], "name", "actor-shader"),
                   lambda db: (setattr(db.assetBundleList[1], "objectName", "Asset_1"),
                               setattr(db.assetBundleList[1], "generation", 1711343248828371)))
        for change in changes:
            database = fixture(); change(database)
            with self.subTest(change=change), self.assertRaisesRegex(OctoManifestError, "identit"):
                archive(database)

    def test_malformed_active_metadata_and_arbitrary_upstream_rejected(self):
        for field, value in (("md5","not-md5"), ("objectName","../secret"),
                             ("objectName","x?url=private"), ("generation",0),
                             ("uploadVersionId",0), ("size",0), ("state",99)):
            database = fixture(); setattr(database.assetBundleList[0], field, value)
            with self.subTest(field=field), self.assertRaisesRegex(OctoManifestError, "metadata"):
                archive(database)
        database = fixture(); database.urlFormat = "https://private.invalid/{o}"
        with self.assertRaisesRegex(OctoManifestError, "URL"):
            archive(database)

    def test_incomplete_delta_cannot_be_used_as_complete_archive(self):
        database = fixture(); database.ClearField("resourceList")
        with self.assertRaisesRegex(OctoManifestError, "complete"):
            archive(database)

    def test_deleted_content_preserved_in_manifest_but_not_download_whitelist(self):
        database = fixture(); database.assetBundleList[0].state = 4
        server = archive(database)
        decoded = independent_decode(response(server))
        self.assertEqual(decoded.assetBundleList[0].state, 4)
        self.assertEqual(len(server.objects), 2)
        with self.assertRaises(OctoRequestError):
            server.lookup_object("/octo/202050/assetbundle/Asset_1/1711343248828371")


if __name__ == "__main__":
    unittest.main()
