from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import io
import json
import stat
import struct
import threading
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

import pytest

from idoly_local import resource_archive as module
from idoly_local.octo_cache import OctoCache, OctoCacheError, OctoCacheMiss
from idoly_local.octo_manifest import OctoObject
from idoly_local.resource_archive import (ResourceArchiveError, VerifiedResourceArchive,
                                         cache_member, write_archive)


MANIFEST = b"\x08\x01"  # A public revision header; catalog validation is the caller's job.
BODY = b"original encrypted CDN bytes\x00\xff"


def record(body=BODY, name="object_one"):
    return OctoObject("assetbundle", 202050, name, 1234, len(body),
        hashlib.md5(body, usedforsecurity=False).hexdigest(), "public bundle name")


@contextmanager
def open_body(_record):
    yield io.BytesIO(BODY)


def exported(*, platform="android", records=None, opener=open_body, output=None, event=None, on_file=None, kind="all"):
    records = [record()] if records is None else records
    output = io.BytesIO() if output is None else output
    summary = write_archive(output, platform=platform, manifest_bytes=MANIFEST, revision=1,
        application_version=205051 if platform == "android" else 105051, records=records,
        open_verified=opener, cancel_event=event or threading.Event(), on_file=on_file, kind=kind)
    return output, summary


def contents(stream):
    with ZipFile(io.BytesIO(stream.getvalue())) as archive:
        return {info.filename: archive.read(info.filename) for info in archive.infolist()}


def rewrite(files, *, transform=None, compression=ZIP_STORED):
    result = io.BytesIO()
    with ZipFile(result, "w", compression=compression) as archive:
        for name, body in files.items():
            info = ZipInfo(name)
            info.compress_type = compression
            if transform is not None:
                transform(info)
            archive.writestr(info, body)
    result.seek(0)
    return result


def inspect(source, *, platform="android", records=None, manifest=MANIFEST):
    return VerifiedResourceArchive(source, platform=platform, manifest_bytes=manifest,
                                  records=[record()] if records is None else records)


@pytest.mark.parametrize("platform,public,cache", [("android", "public-octo", "octo-cache"),
                                                 ("ios", "public-octo-ios", "octo-cache-ios")])
def test_roundtrip_is_portable_original_bytes_without_keys_accounts_or_caller_closure(platform, public, cache):
    stream, summary = exported(platform=platform)
    item = record(); name = cache_member(platform, item)
    assert name == cache + "/" + item.cache_key[:2] + "/" + item.cache_key + ".bin"
    assert summary == {"written_files": 1, "written_bytes": len(BODY), "missing_files": 0}
    data = contents(stream)
    assert set(data) == {name, public + "/manifest.pb", "portable-manifest.json"}
    assert data[name] == BODY and data[public + "/manifest.pb"] == MANIFEST
    portable = json.loads(data["portable-manifest.json"])
    assert portable["manifest_sha256"] == hashlib.sha256(MANIFEST).hexdigest()
    assert set(portable) == module._PORTABLE_FIELDS
    assert not any(word in data for word in ("settings.json", "state.db", "user", "aes_key_hex", "client_key"))
    with ZipFile(io.BytesIO(stream.getvalue())) as archive:
        assert all(info.compress_type == ZIP_STORED and info.flag_bits & 8 for info in archive.infolist())
    stream.seek(7)
    with inspect(stream, platform=platform) as archive:
        assert archive.objects == (item,)
        with archive.open_record(item) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(BODY))
            assert response.geturl() == item.upstream_url
            assert response.read(0) == b"" and response.read() == BODY and response.read() == b""
    assert stream.tell() == 7 and not stream.closed


def test_only_missing_cache_enter_is_skipped_and_missing_objects_cannot_fetch():
    first, second = record(), record(name="object_two")
    callbacks = []
    @contextmanager
    def opener(item):
        if item == second:
            raise OctoCacheMiss()
        yield io.BytesIO(BODY)
    stream, summary = exported(records=[first, second], opener=opener, on_file=callbacks.append)
    assert summary == {"written_files": 1, "written_bytes": len(BODY), "missing_files": 1}
    assert callbacks == [first]
    with inspect(stream, records=[first, second]) as archive:
        assert archive.objects == (first,)
        with pytest.raises(ResourceArchiveError):
            archive.fetch(second.upstream_url, timeout=1)


@pytest.mark.parametrize("kind", ["assetbundle", "resources"])
def test_kind_filtered_export_roundtrips_against_the_full_catalog_and_rejects_other_kind(kind):
    first = record()
    second = replace(record(name="resource_two"), kind="resources")
    full = [first, second]
    chosen = first if kind == "assetbundle" else second
    other = second if kind == "assetbundle" else first
    stream, summary = exported(records=[chosen], kind=kind)
    assert summary["written_files"] == 1 and summary["missing_files"] == 0
    with inspect(stream, records=full) as archive:
        assert archive.objects == (chosen,) and archive.kind == kind
        with archive.fetch(chosen.upstream_url, timeout=1) as response:
            assert response.read() == BODY
        with pytest.raises(ResourceArchiveError):
            archive.fetch(other.upstream_url, timeout=1)
    files = contents(stream)
    files[cache_member("android", other)] = BODY
    with pytest.raises(ResourceArchiveError):
        with inspect(rewrite(files), records=full):
            pass
    with pytest.raises(ResourceArchiveError) as caught:
        exported(records=full, kind=kind)
    assert caught.value.code == "archive_catalog"


@pytest.mark.parametrize("failure", ["size-short", "size-long", "digest", "source-error", "exit-miss"])
def test_bad_cache_source_is_not_silently_skipped_or_finalized(failure):
    @contextmanager
    def opener(_item):
        if failure == "source-error":
            raise OSError("private adapter detail")
        value = BODY[:-1] if failure == "size-short" else BODY + b"x" if failure == "size-long" else b"x" * len(BODY) if failure == "digest" else BODY
        yield io.BytesIO(value)
        if failure == "exit-miss":
            raise OctoCacheMiss()
    output = io.BytesIO(); callbacks = []
    with pytest.raises(ResourceArchiveError) as caught:
        exported(opener=opener, output=output, on_file=callbacks.append)
    assert "private" not in str(caught.value) and not callbacks and not output.closed
    with pytest.raises(BadZipFile):
        ZipFile(io.BytesIO(output.getvalue()))


class Nonseeking:
    def __init__(self, *, partial=None, event=None, cancel_after=None, zero=False):
        self.data, self.partial, self.event, self.cancel_after, self.zero = bytearray(), partial, event, cancel_after, zero
        self.requests, self.closed = [], False
    def write(self, raw):
        self.requests.append(len(raw))
        assert len(raw) <= module.CHUNK
        if self.zero:
            return 0
        count = min(len(raw), self.partial) if self.partial else len(raw)
        self.data.extend(raw[:count])
        if self.event is not None and len(self.data) >= self.cancel_after:
            self.event.set()
        return count
    def flush(self):
        pass
    def close(self):
        self.closed = True


def test_nonseeking_export_handles_short_writes_and_chunk_limits():
    body = b"x" * (module.CHUNK * 3 + 17)
    item = record(body)
    class Strict(io.BytesIO):
        def read(self, count=-1):
            assert 0 < count <= module.CHUNK
            return super().read(count)
    @contextmanager
    def opener(_item):
        yield Strict(body)
    output = Nonseeking(partial=97)
    _, summary = exported(records=[item], opener=opener, output=output)
    assert summary["written_bytes"] == len(body) and not output.closed
    with inspect(io.BytesIO(output.data), records=[item]) as archive:
        with archive.fetch(item.upstream_url, timeout=1) as response:
            chunks = list(iter(lambda: response.read(module.CHUNK), b""))
    assert b"".join(chunks) == body


def test_cancelled_or_zero_write_export_leaves_no_finished_zip():
    body = b"x" * (module.CHUNK * 2)
    item = record(body)
    @contextmanager
    def opener(_item):
        yield io.BytesIO(body)
    event = threading.Event(); output = Nonseeking(event=event, cancel_after=1000)
    with pytest.raises(ResourceArchiveError) as caught:
        exported(records=[item], opener=opener, output=output, event=event)
    assert caught.value.code == "cancelled" and not output.closed
    with pytest.raises(BadZipFile):
        ZipFile(io.BytesIO(output.data))
    with pytest.raises(ResourceArchiveError) as caught:
        exported(output=Nonseeking(zero=True))
    assert caught.value.code == "archive_io"


@pytest.mark.parametrize("name", ["../state.db", "/absolute", "octo-cache\\private", "public-octo/settings.json", "account.json"])
def test_import_refuses_unlisted_or_private_paths_before_zipfile_index(monkeypatch, name):
    stream, _ = exported(); files = contents(stream); files[name] = b"private"
    source = rewrite(files)
    monkeypatch.setattr(module, "ZipFile", lambda *a, **kw: pytest.fail("preflight must reject first"))
    with pytest.raises(ResourceArchiveError):
        with inspect(source):
            pass
    assert not source.closed


@pytest.mark.parametrize("change", ["symlink", "compressed", "encrypted", "wrong-size", "duplicate"])
def test_import_refuses_symlinks_encryption_compression_sizes_and_duplicates_before_index(monkeypatch, change):
    stream, _ = exported(); files = contents(stream); member = cache_member("android", record())
    if change == "wrong-size":
        files[member] += b"extra"
    source = rewrite(files, compression=ZIP_DEFLATED if change == "compressed" else ZIP_STORED,
        transform=(lambda info: setattr(info, "external_attr", (stat.S_IFLNK | 0o777) << 16)) if change == "symlink" else None)
    if change == "duplicate":
        with ZipFile(source, "a") as archive, pytest.warns(UserWarning):
            archive.writestr(member, BODY)
        source.seek(0)
    if change == "encrypted":
        raw = bytearray(source.getvalue()); central = raw.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", raw, central + 8)[0]
        struct.pack_into("<H", raw, central + 8, flags | 1); source = io.BytesIO(raw)
    monkeypatch.setattr(module, "ZipFile", lambda *a, **kw: pytest.fail("preflight must reject first"))
    with pytest.raises(ResourceArchiveError):
        with inspect(source):
            pass


@pytest.mark.parametrize("change", ["central-limit", "declared-count", "comment", "multidisk"])
def test_eocd_bounds_and_actual_count_are_checked_before_zipfile(monkeypatch, change):
    stream, _ = exported(); raw = bytearray(stream.getvalue()); at = len(raw) - 22
    if change == "central-limit":
        struct.pack_into("<I", raw, at + 12, module.MAX_CENTRAL_BYTES + 1)
    elif change == "declared-count":
        struct.pack_into("<HH", raw, at + 8, 2, 2)
    elif change == "comment":
        struct.pack_into("<H", raw, at + 20, 1); raw += b"x"
    else:
        struct.pack_into("<H", raw, at + 4, 1)
    monkeypatch.setattr(module, "ZipFile", lambda *a, **kw: pytest.fail("preflight must reject first"))
    with pytest.raises(ResourceArchiveError):
        with inspect(io.BytesIO(raw)):
            pass


def test_small_valid_zip64_footer_is_supported_without_allocating_large_files():
    stream, _ = exported(); raw = stream.getvalue(); footer = struct.unpack("<4s4H2LH", raw[-22:])
    count, size, start = footer[4], footer[5], footer[6]; position = len(raw) - 22
    extended = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, start)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, position, 1)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0xffff, 0xffff, 0xffffffff, 0xffffffff, 0)
    source = io.BytesIO(raw[:-22] + extended + locator + end)
    with inspect(source) as archive:
        with archive.open_record(record()) as response:
            assert response.read() == BODY


@pytest.mark.parametrize("change", ["raw-manifest", "sha", "count", "extra-key", "boolean-count"])
def test_public_manifest_and_portable_metadata_must_match_the_current_catalog(change):
    stream, _ = exported(); files = contents(stream); portable = json.loads(files["portable-manifest.json"])
    if change == "raw-manifest":
        files["public-octo/manifest.pb"] = b"\x08\x02"
    elif change == "sha":
        portable["manifest_sha256"] = "0" * 64
    elif change == "count":
        portable["written_files"] = 0
    elif change == "extra-key":
        portable["aes_key_hex"] = "never accepted"
    else:
        portable["written_files"] = True
    files["portable-manifest.json"] = json.dumps(portable).encode()
    with pytest.raises(ResourceArchiveError) as caught:
        with inspect(rewrite(files)):
            pass
    assert caught.value.code == "archive_manifest"


def test_streamed_import_uses_atomic_verified_cache_without_network_and_reuses_completion(tmp_path):
    stream, _ = exported(); calls = []
    with inspect(stream) as archive:
        def fetch(url, *, timeout):
            calls.append(url)
            return archive.fetch(url, timeout=timeout)
        cache = OctoCache(tmp_path, fetcher=fetch)
        for _ in range(2):
            with cache.open_verified(record()) as source:
                assert source.read() == BODY
        assert calls == [record().upstream_url]
        with pytest.raises(ResourceArchiveError):
            archive.fetch("https://untrusted.invalid/private", timeout=1)
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("change", ["md5", "crc"])
def test_corrupt_object_never_becomes_a_completed_cache_file(tmp_path, change):
    stream, _ = exported(); member = cache_member("android", record())
    if change == "md5":
        files = contents(stream); files[member] = b"x" * len(BODY); source = rewrite(files)
    else:
        raw = bytearray(stream.getvalue())
        with ZipFile(io.BytesIO(raw)) as archive:
            offset = archive.getinfo(member).header_offset
        name_size, extra_size = struct.unpack_from("<HH", raw, offset + 26)
        raw[offset + 30 + name_size + extra_size] ^= 1
        source = io.BytesIO(raw)
    with inspect(source) as archive:
        with pytest.raises(ResourceArchiveError) as caught:
            with archive.open_record(record()) as response:
                response.read()
        assert caught.value.code == "archive_digest"
        cache = OctoCache(tmp_path, fetcher=archive.fetch)
        with pytest.raises(OctoCacheError):
            with cache.open_verified(record()):
                pass
    assert not list(tmp_path.rglob("*.bin")) and not list(tmp_path.rglob("*.part"))


def test_nonseekable_import_and_invalid_catalog_metadata_have_fixed_errors():
    class Source(io.BytesIO):
        def seekable(self):
            return False
    with pytest.raises(ResourceArchiveError) as caught:
        with inspect(Source(b"private")):
            pass
    assert caught.value.code == "archive_unsupported" and "private" not in str(caught.value)
    for item in (replace(record(), object_name="../private"), replace(record(), size=0),
                 replace(record(), md5="UPPER"), replace(record(), generation=True)):
        with pytest.raises(ResourceArchiveError):
            cache_member("android", item)
    with pytest.raises(ResourceArchiveError):
        inspect(io.BytesIO(), records=[record(), record()])


def test_bad_catalog_iterators_and_spoofed_record_properties_cannot_escape_the_boundary():
    def broken():
        raise RuntimeError("private catalog detail")
        yield record()
    for records in (None, broken()):
        with pytest.raises(ResourceArchiveError) as caught:
            VerifiedResourceArchive(io.BytesIO(), platform="android", manifest_bytes=MANIFEST, records=records)
        assert caught.value.code == "archive_catalog" and "private" not in str(caught.value)
    class Spoofed(OctoObject):
        @property
        def cache_key(self):
            return "../../private"
    value = record()
    spoofed = Spoofed(value.kind, value.upload_version, value.object_name,
                      value.generation, value.size, value.md5, value.name)
    assert cache_member("android", spoofed) == cache_member("android", value)
    assert ResourceArchiveError([]).code == "archive_invalid"
