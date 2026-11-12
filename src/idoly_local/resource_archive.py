"""Portable, account-free Octo cache archives with bounded ZIP metadata.

Assets are copied as original CDN bytes. This module neither downloads nor
decrypts them; an importing caller supplies its existing atomic OctoCache.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import io
import json
import math
import re
import stat
import struct
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_STORED

from .octo_cache import OctoCacheMiss
from .octo_manifest import OctoObject


CHUNK = 64 * 1024
MAX_RECORDS = 100000
MAX_CENTRAL_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PORTABLE_BYTES = 16 * 1024
_EXTRA_BYTES = 16 * 1024 * 1024
_PLATFORMS = {"android": ("public-octo", "octo-cache", 205051),
              "ios": ("public-octo-ios", "octo-cache-ios", 105051)}
_PORTABLE_FIELDS = frozenset(("schema", "platform", "kind", "application_version", "revision",
    "manifest_sha256", "catalog_files", "catalog_bytes", "written_files", "written_bytes", "missing_files"))
_CODES = frozenset(("archive_catalog", "archive_io", "archive_source", "archive_size", "archive_digest",
    "archive_manifest", "archive_invalid", "archive_bounds", "archive_unsupported", "cancelled"))
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MD5 = re.compile(r"[0-9a-f]{32}\Z")


class ResourceArchiveError(OSError):
    def __init__(self, code="archive_invalid"):
        self.code = code if isinstance(code, str) and code in _CODES else "archive_invalid"
        super().__init__("Resource archive unavailable: " + self.code)


def _platform(platform):
    if not isinstance(platform, str) or platform not in _PLATFORMS:
        raise ResourceArchiveError("archive_catalog")
    return _PLATFORMS[platform]


def _record(record):
    if (not isinstance(record, OctoObject) or record.kind not in ("assetbundle", "resources")
            or type(record.upload_version) is not int or not 1 <= record.upload_version <= 2**31 - 1
            or type(record.generation) is not int or not 1 <= record.generation <= 2**64 - 1
            or type(record.size) is not int or not 1 <= record.size <= 2**31 - 1
            or not isinstance(record.object_name, str) or not _NAME.fullmatch(record.object_name)
            or not isinstance(record.md5, str) or not _MD5.fullmatch(record.md5)):
        raise ResourceArchiveError("archive_catalog")
    return OctoObject(record.kind, record.upload_version, record.object_name, record.generation,
                      record.size, record.md5, record.name)


def cache_member(platform, record):
    """The real cache-relative name, safe to unpack into a data directory."""
    _, cache, _ = _platform(platform)
    key = _record(record).cache_key
    return cache + "/" + key[:2] + "/" + key + ".bin"


def _records(platform, records):
    result = {}
    try:
        for record in records:
            if len(result) >= MAX_RECORDS:
                raise ResourceArchiveError("archive_bounds")
            record = _record(record)
            name = cache_member(platform, record)
            if name in result:
                raise ResourceArchiveError("archive_catalog")
            result[name] = record
    except ResourceArchiveError:
        raise
    except Exception:
        raise ResourceArchiveError("archive_catalog") from None
    return result


def _manifest_revision(raw):
    """Read only top-level wire framing; nested Data messages stay opaque."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_MANIFEST_BYTES:
        raise ResourceArchiveError("archive_manifest")
    def varint(at):
        value = 0
        for shift in range(0, 70, 7):
            if at >= len(raw):
                raise ResourceArchiveError("archive_manifest")
            byte = raw[at]; at += 1
            if shift == 63 and byte > 1:
                raise ResourceArchiveError("archive_manifest")
            value |= (byte & 127) << shift
            if byte < 128:
                return value, at
        raise ResourceArchiveError("archive_manifest")
    at, revision = 0, None
    while at < len(raw):
        key, at = varint(at)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ResourceArchiveError("archive_manifest")
        if wire == 0:
            value, at = varint(at)
            if number == 1:
                if revision is not None or not 1 <= value <= 2**31 - 1:
                    raise ResourceArchiveError("archive_manifest")
                revision = value
        elif wire in (1, 5):
            at += 8 if wire == 1 else 4
        elif wire == 2:
            size, at = varint(at); at += size
        else:
            raise ResourceArchiveError("archive_manifest")
        if at > len(raw) or (number == 1 and wire != 0):
            raise ResourceArchiveError("archive_manifest")
    if revision is None:
        raise ResourceArchiveError("archive_manifest")
    return revision


def _cancel(event):
    if event.is_set():
        raise ResourceArchiveError("cancelled")


class _CheckedWriter:
    """Nonseeking writer; never closes the caller's output or assumes full writes."""
    def __init__(self, output, event):
        self.output, self.event, self.position, self.aborted = output, event, 0, False

    def tell(self):
        return self.position

    def seek(self, *_args):
        raise io.UnsupportedOperation("streaming resource archive")

    def write(self, data):
        if self.aborted:
            raise ResourceArchiveError("archive_io")
        view = memoryview(data)
        total = len(view)
        while view:
            _cancel(self.event)
            piece = view[:CHUNK]
            try:
                written = self.output.write(piece)
            except ResourceArchiveError:
                raise
            except Exception:
                raise ResourceArchiveError("archive_io") from None
            if type(written) is not int or not 0 < written <= len(piece):
                raise ResourceArchiveError("archive_io")
            self.position += written
            view = view[written:]
        return total

    def flush(self):
        # No new archive bytes are published by flush. A cancel arriving after
        # the last EOCD write does not retroactively cancel a completed archive.
        flush = getattr(self.output, "flush", None)
        if flush is not None:
            try:
                flush()
            except Exception:
                raise ResourceArchiveError("archive_io") from None


def _zip_info(name, size):
    info = ZipInfo(name)
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o400) << 16
    info.file_size = size
    return info


def _write_bytes(archive, name, raw, event):
    with archive.open(_zip_info(name, len(raw)), "w", force_zip64=True) as output:
        for start in range(0, len(raw), CHUNK):
            _cancel(event)
            output.write(memoryview(raw)[start:start + CHUNK])


def write_archive(output, *, platform, manifest_bytes, revision, application_version,
                  records, open_verified, cancel_event, on_file=None, kind="all"):
    """Write a ZIP64 stream of already cached, reverified objects only.

    Missing cache entries are omitted. Any other error poisons the writer before
    ZIP finalization, so cancellation or invalid source bytes cannot yield a
    completed archive. Publication of its final EOCD is the completion boundary.
    """
    public, _, version = _platform(platform)
    if (type(revision) is not int or revision != _manifest_revision(manifest_bytes)
            or type(application_version) is not int or application_version != version
            or not callable(open_verified) or not callable(getattr(cancel_event, "is_set", None))
            or (on_file is not None and not callable(on_file))):
        raise ResourceArchiveError("archive_catalog")
    catalog = _records(platform, records)
    if (not isinstance(kind, str) or kind not in ("all", "assetbundle", "resources")
            or (kind != "all" and any(record.kind != kind for record in catalog.values()))):
        raise ResourceArchiveError("archive_catalog")
    writer = _CheckedWriter(output, cancel_event)
    archive = None
    written_files = written_bytes = missing_files = 0
    try:
        _cancel(cancel_event)
        archive = ZipFile(writer, "w", compression=ZIP_STORED, allowZip64=True)
        _write_bytes(archive, public + "/manifest.pb", manifest_bytes, cancel_event)
        for name, record in catalog.items():
            _cancel(cancel_event)
            with ExitStack() as stack:
                try:
                    source = stack.enter_context(open_verified(record))
                except OctoCacheMiss:
                    missing_files += 1
                    continue
                digest, count = hashlib.md5(usedforsecurity=False), 0
                with archive.open(_zip_info(name, record.size), "w", force_zip64=True) as target:
                    while True:
                        _cancel(cancel_event)
                        block = source.read(min(CHUNK, record.size - count + 1))
                        if not isinstance(block, (bytes, bytearray, memoryview)):
                            raise ResourceArchiveError("archive_source")
                        _cancel(cancel_event)
                        if not block:
                            break
                        count += len(block)
                        if count > record.size:
                            raise ResourceArchiveError("archive_size")
                        target.write(block); digest.update(block)
                    if count != record.size:
                        raise ResourceArchiveError("archive_size")
                    if digest.hexdigest() != record.md5:
                        raise ResourceArchiveError("archive_digest")
            written_files += 1; written_bytes += count
            if on_file is not None:
                try:
                    on_file(record)
                except Exception:
                    pass  # Observers do not own archive completion.
        summary = {"written_files": written_files, "written_bytes": written_bytes,
                   "missing_files": missing_files}
        portable = {"schema": 1, "platform": platform, "kind": kind, "application_version": version,
                    "revision": revision, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "catalog_files": len(catalog), "catalog_bytes": sum(r.size for r in catalog.values()),
                    **summary}
        raw = (json.dumps(portable, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        _write_bytes(archive, "portable-manifest.json", raw, cancel_event)
        _cancel(cancel_event)
        archive.close(); archive = None
        return summary
    except BaseException as error:
        writer.aborted = True
        if archive is not None:
            try:
                archive.close()
            except Exception:
                pass
        if isinstance(error, (ResourceArchiveError, KeyboardInterrupt, SystemExit)):
            raise
        raise ResourceArchiveError("archive_source" if isinstance(error, OSError) else "archive_io") from None


def _read_exact(source, count):
    if not 0 <= count <= MAX_CENTRAL_BYTES + 128:
        raise ResourceArchiveError("archive_bounds")
    result = bytearray()
    while len(result) < count:
        block = source.read(min(CHUNK, count - len(result)))
        if not isinstance(block, bytes) or not block or len(block) > count - len(result):
            raise ResourceArchiveError("archive_invalid")
        result.extend(block)
    return bytes(result)


def _zip64_values(extra, size, compressed, offset, disk):
    found, at = None, 0
    while at < len(extra):
        if at + 4 > len(extra):
            raise ResourceArchiveError("archive_invalid")
        kind, length = struct.unpack_from("<HH", extra, at); at += 4
        if kind != 1 or found is not None or at + length > len(extra):
            raise ResourceArchiveError("archive_unsupported")
        found = extra[at:at + length]; at += length
    values, at = [size, compressed, offset, disk], 0
    for index, sentinel in enumerate((0xffffffff, 0xffffffff, 0xffffffff, 0xffff)):
        if values[index] == sentinel:
            width, code = (4, "I") if index == 3 else (8, "Q")
            if found is None or at + width > len(found):
                raise ResourceArchiveError("archive_invalid")
            values[index] = struct.unpack_from("<" + code, found, at)[0]; at += width
    if found is not None and at != len(found):
        raise ResourceArchiveError("archive_unsupported")
    return values


class _ZipSnapshot:
    """Freeze bounded central/footer metadata before ZipFile allocates its index."""
    def __init__(self, source, size, start, metadata):
        self.source, self.size, self.start, self.metadata, self.position = source, size, start, metadata, 0

    def tell(self):
        return self.position

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if whence not in (0, 1, 2) or not 0 <= position <= self.size:
            raise ResourceArchiveError("archive_invalid")
        self.position = position
        return position

    def read(self, count=-1):
        if count < 0:
            count = self.size - self.position
        count = min(count, self.size - self.position)
        if count > MAX_CENTRAL_BYTES + 128:
            raise ResourceArchiveError("archive_bounds")
        if self.position >= self.start:
            begin = self.position - self.start
            result = self.metadata[begin:begin + count]
        else:
            size = min(count, self.start - self.position)
            self.source.seek(self.position)
            result = _read_exact(self.source, size)
            if size < count:
                result += self.metadata[:count - size]
        self.position += len(result)
        return result


def _preflight(source, catalog, manifest_name, manifest_size):
    """Reject oversized/misleading central indexes before opening ZipFile."""
    if not callable(getattr(source, "seekable", None)) or not source.seekable():
        raise ResourceArchiveError("archive_unsupported")
    source.seek(0, 2); size = source.tell()
    if type(size) is not int or not 22 <= size <= 2**63 - 1:
        raise ResourceArchiveError("archive_invalid")
    source.seek(size - 22)
    end = struct.unpack("<4s4H2LH", _read_exact(source, 22))
    if end[0] != b"PK\x05\x06" or end[1] != 0 or end[2] != 0 or end[7] != 0:
        raise ResourceArchiveError("archive_unsupported")
    entries, central_size, start, footer = end[4], end[5], end[6], size - 22
    source.seek(max(0, size - 42))
    locator = _read_exact(source, min(20, size - 22)) if size >= 42 else b""
    if locator[:4] == b"PK\x06\x07":
        _, disk, zip64_at, disks = struct.unpack("<4sLQL", locator)
        if disk != 0 or disks != 1 or zip64_at + 56 != size - 42:
            raise ResourceArchiveError("archive_invalid")
        source.seek(zip64_at)
        extended = struct.unpack("<4sQ2H2L4Q", _read_exact(source, 56))
        if (extended[0] != b"PK\x06\x06" or extended[1] != 44 or extended[4:6] != (0, 0)
                or extended[6] != extended[7]):
            raise ResourceArchiveError("archive_unsupported")
        entries, central_size, start, footer = extended[7], extended[8], extended[9], zip64_at
        for ordinary, actual, sentinel in ((end[3], entries, 0xffff), (end[4], entries, 0xffff),
                                          (end[5], central_size, 0xffffffff), (end[6], start, 0xffffffff)):
            if ordinary != sentinel and ordinary != actual:
                raise ResourceArchiveError("archive_invalid")
    elif end[3] != entries or central_size == 0xffffffff or start == 0xffffffff:
        raise ResourceArchiveError("archive_invalid")
    if (not 2 <= entries <= MAX_RECORDS + 2 or not 1 <= central_size <= MAX_CENTRAL_BYTES
            or start < 0 or start + central_size != footer):
        raise ResourceArchiveError("archive_bounds")
    source.seek(start)
    metadata = _read_exact(source, size - start)
    at, actual, expanded, names, offsets = 0, 0, 0, {}, set()
    for _ in range(entries):
        if at + 46 > central_size:
            raise ResourceArchiveError("archive_invalid")
        row = struct.unpack_from("<4s6H3L5H2L", metadata, at)
        if row[0] != b"PK\x01\x02":
            raise ResourceArchiveError("archive_invalid")
        flags, method, crc, compressed, unpacked = row[3], row[4], row[7], row[8], row[9]
        name_size, extra_size, comment_size, disk, external, offset = row[10], row[11], row[12], row[13], row[15], row[16]
        length = 46 + name_size + extra_size + comment_size
        if not 1 <= name_size <= 256 or at + length > central_size or comment_size != 0:
            raise ResourceArchiveError("archive_bounds")
        raw_name = metadata[at + 46:at + 46 + name_size]
        try:
            name = raw_name.decode("ascii")
        except UnicodeError:
            raise ResourceArchiveError("archive_invalid") from None
        if ("\0" in name or name in names or flags & ~(8 | 0x800) or method != ZIP_STORED
                or stat.S_IFMT(external >> 16) not in (0, stat.S_IFREG)):
            raise ResourceArchiveError("archive_unsupported")
        extra = metadata[at + 46 + name_size:at + 46 + name_size + extra_size]
        unpacked, compressed, offset, disk = _zip64_values(extra, unpacked, compressed, offset, disk)
        if disk != 0 or offset >= start or offset in offsets or compressed != unpacked:
            raise ResourceArchiveError("archive_invalid")
        if name == manifest_name:
            expected = manifest_size
        elif name == "portable-manifest.json":
            expected = unpacked if 1 <= unpacked <= MAX_PORTABLE_BYTES else -1
        elif name in catalog:
            expected = catalog[name].size
        else:
            raise ResourceArchiveError("archive_invalid")
        if unpacked != expected:
            raise ResourceArchiveError("archive_size")
        expanded += unpacked; actual += 1
        names[name] = (unpacked, crc, offset, flags, external)
        offsets.add(offset); at += length
    if (at != central_size or actual != entries or manifest_name not in names
            or "portable-manifest.json" not in names or min(offsets) != 0
            or expanded > sum(record.size for record in catalog.values()) + _EXTRA_BYTES):
        raise ResourceArchiveError("archive_invalid")
    return _ZipSnapshot(source, size, start, metadata), names


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ResourceArchiveError("archive_manifest")
        result[key] = value
    return result


class _ArchiveResponse:
    status = 200

    def __init__(self, owner, record, stream):
        self.owner, self.record, self.stream = owner, record, stream
        self.headers = {"Content-Length": str(record.size), "Content-Encoding": "identity"}
        self.count, self.digest, self.closed = 0, hashlib.md5(usedforsecurity=False), False

    def geturl(self):
        return self.record.upstream_url

    def read(self, count=-1):
        if self.closed or self.owner._closed:
            raise ResourceArchiveError("archive_io")
        try:
            if count == 0:
                return b""
            block = self.stream.read(CHUNK if count < 0 else min(count, CHUNK))
            self.count += len(block); self.digest.update(block)
            if self.count > self.record.size:
                raise ResourceArchiveError("archive_size")
            if self.count == self.record.size and self.digest.hexdigest() != self.record.md5:
                raise ResourceArchiveError("archive_digest")
            if not block and self.count != self.record.size:
                raise ResourceArchiveError("archive_size")
            return block
        except BadZipFile:
            raise ResourceArchiveError("archive_digest") from None
        except ResourceArchiveError:
            raise
        except Exception:
            raise ResourceArchiveError("archive_io") from None

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.stream.close()
            except Exception:
                raise ResourceArchiveError("archive_io") from None


class VerifiedResourceArchive:
    """A bounded metadata snapshot and whitelist-only, offline cache fetcher.

    Enter validates structure and public manifests. Object bytes are checked as
    they are read and again by the caller's atomic OctoCache before publication.
    """
    def __init__(self, source, *, platform, manifest_bytes, records):
        public, _, self.version = _platform(platform)
        self.revision = _manifest_revision(manifest_bytes)
        self.catalog = _records(platform, records)
        self.source, self.platform, self.manifest = source, platform, manifest_bytes
        self.manifest_name = public + "/manifest.pb"
        self.objects, self._closed, self._archive, self._position = (), True, None, None

    def __enter__(self):
        if self._archive is not None:
            raise ResourceArchiveError("archive_io")
        try:
            self._position = self.source.tell()
            snapshot, entries = _preflight(self.source, self.catalog, self.manifest_name, len(self.manifest))
            self._archive = ZipFile(snapshot, "r", allowZip64=True)
            infos = self._archive.infolist()
            if len(infos) != len(entries) or {info.filename for info in infos} != entries.keys():
                raise ResourceArchiveError("archive_invalid")
            for info in infos:
                size, crc, offset, flags, external = entries[info.filename]
                if ((info.file_size, info.compress_size, info.CRC, info.header_offset, info.flag_bits, info.external_attr)
                        != (size, size, crc, offset, flags, external) or info.compress_type != ZIP_STORED):
                    raise ResourceArchiveError("archive_invalid")
            if self._archive.read(self.manifest_name) != self.manifest:
                raise ResourceArchiveError("archive_manifest")
            portable = json.loads(self._archive.read("portable-manifest.json").decode("ascii"),
                                  object_pairs_hook=_json_object)
            if (not isinstance(portable, dict) or not isinstance(portable.get("kind"), str)
                    or portable["kind"] not in ("all", "assetbundle", "resources")):
                raise ResourceArchiveError("archive_manifest")
            kind = portable["kind"]
            selected = {name: record for name, record in self.catalog.items()
                        if kind == "all" or record.kind == kind}
            if set(entries) - {self.manifest_name, "portable-manifest.json"} - selected.keys():
                raise ResourceArchiveError("archive_invalid")
            present = tuple(record for name, record in selected.items() if name in entries)
            expected = {"schema": 1, "platform": self.platform, "kind": kind, "application_version": self.version,
                "revision": self.revision, "manifest_sha256": hashlib.sha256(self.manifest).hexdigest(),
                "catalog_files": len(selected), "catalog_bytes": sum(r.size for r in selected.values()),
                "written_files": len(present), "written_bytes": sum(r.size for r in present),
                "missing_files": len(selected) - len(present)}
            if (not isinstance(portable, dict) or set(portable) != _PORTABLE_FIELDS or portable != expected
                    or any(type(portable[key]) is not int for key in _PORTABLE_FIELDS - {"platform", "kind", "manifest_sha256"})):
                raise ResourceArchiveError("archive_manifest")
            self.kind = kind
            self.objects, self._closed = present, False
            self._present = {name for name in self.catalog if name in entries}
            self._urls = {record.upstream_url: record for record in present}
            return self
        except BaseException as error:
            self.__exit__(None, None, None)
            if isinstance(error, (ResourceArchiveError, KeyboardInterrupt, SystemExit)):
                raise
            raise ResourceArchiveError("archive_invalid") from None

    def __exit__(self, *_args):
        self._closed = True
        if self._archive is not None:
            self._archive.close(); self._archive = None
        if self._position is not None:
            try:
                self.source.seek(self._position)
            except Exception:
                pass

    @contextmanager
    def open_record(self, record):
        name = cache_member(self.platform, record)
        expected = self.catalog.get(name)
        if (self._closed or expected is None or name not in self._present
                or (record.identity, record.size, record.md5) != (expected.identity, expected.size, expected.md5)):
            raise ResourceArchiveError("archive_invalid")
        response = None
        try:
            response = _ArchiveResponse(self, expected, self._archive.open(name))
            yield response
        except ResourceArchiveError:
            raise
        except BadZipFile:
            raise ResourceArchiveError("archive_digest") from None
        except Exception:
            raise ResourceArchiveError("archive_io") from None
        finally:
            if response is not None:
                response.close()

    def fetch(self, url, *, timeout):
        if (self._closed or not isinstance(url, str) or url not in self._urls
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ResourceArchiveError("archive_invalid")
        return self.open_record(self._urls[url])
