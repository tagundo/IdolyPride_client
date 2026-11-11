"""Pinned Android Octo manifest protocol and immutable object whitelist.

The original 6.1.1 client requests application212/version205051. The Octo API
uses a separate envelope from the game RPC codec: a random16byte IV followed
by AES256CBC/PKCS7 protobuf. Callers supply SHA256(UTF8(settings.A)) and the
same generic AES callback used by the embedded Java bridge. This module does
not fetch objects, change the manifest revision, or mark downloads complete.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
import re
from types import MappingProxyType
from typing import Callable, Mapping

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_LIST = re.compile(r"/v2/pub/a/212/v/205051/list/(0|[1-9][0-9]{0,9})\Z")
_OBJECT = re.compile(r"/octo/([1-9][0-9]{0,9})/(assetbundle|resources)/"
                     r"([A-Za-z0-9_-]{1,128})/([1-9][0-9]{0,19})\Z")
_ORIGIN = re.compile(r"http://127\.0\.0\.1(?::([1-9][0-9]{0,4}))?/?\Z")
_OBJECT_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MD5 = re.compile(r"[0-9a-fA-F]{32}\Z")
_UPSTREAM_FORMAT = ("https://d2ilil7yh5oi1v.cloudfront.net/"
                    "solis-{v}-{type}/{o}?generation={g}&alt=media")


class OctoManifestError(ValueError):
    """The archive, configuration, or AES backend is unusable."""


class OctoRequestError(ValueError):
    """A request is outside this pinned archive's supported contract."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def _database_type():
    # Independently describe the original Octo Database/Data wire fields.
    # A private pool avoids collisions with the game's unrelated proto classes.
    file = descriptor_pb2.FileDescriptorProto(
        name="idoly-local-octo.proto", package="idoly_local.octo", syntax="proto3")
    data = file.message_type.add(name="Data")
    state = data.enum_type.add(name="State")
    for number, name in enumerate(("NONE", "ADD", "UPDATE", "LATEST", "DELETE")):
        state.value.add(name=name, number=number)
    fields = ((1,"id",5), (2,"filepath",9), (3,"name",9), (4,"size",5),
              (5,"crc",13), (6,"priority",5), (7,"tagid",5), (8,"dependencie",5),
              (9,"state",14), (10,"md5",9), (11,"objectName",9),
              (12,"generation",4), (13,"uploadVersionId",5))
    for number, name, kind in fields:
        field = data.field.add(name=name, number=number, type=kind,
                              label=3 if number in (7,8) else 1)
        if number == 9:
            field.type_name = ".idoly_local.octo.Data.State"
    database = file.message_type.add(name="Database")
    for number, name, kind, repeated in ((1,"revision",5,False),
            (2,"assetBundleList",11,True), (3,"tagname",9,True),
            (4,"resourceList",11,True), (5,"urlFormat",9,False)):
        field = database.field.add(name=name, number=number, type=kind,
                                   label=3 if repeated else 1)
        if kind == 11:
            field.type_name = ".idoly_local.octo.Data"
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("idoly_local.octo.Database"))


Database = _database_type()
AESCallback = Callable[[bool, bytes, bytes, bytes], bytes]


def _key_and_backend(aes_key, aes_cbc):
    if not isinstance(aes_key, bytes) or len(aes_key) != 32:
        raise OctoManifestError("Octo requires a derived32byte AES key")
    if not callable(aes_cbc):
        raise OctoManifestError("Octo requires a generic AES/CBC backend")


def _crypt(aes_cbc, encrypt, key, iv, data):
    try:
        result = aes_cbc(encrypt, key, iv, data)
        if not isinstance(result, (bytes, bytearray, memoryview)) or len(result) != len(data):
            raise ValueError()
        return bytes(result)
    except Exception:
        raise OctoManifestError("Octo AES backend failed") from None


def _read_varint(raw: bytes, offset: int) -> tuple[int, int]:
    """Read a bounded uint64 without normalizing its original representation."""
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(raw):
            raise OctoManifestError("Truncated top-level Octo protobuf varint")
        byte = raw[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise OctoManifestError("Overflowing top-level Octo protobuf varint")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise OctoManifestError("Overflowing top-level Octo protobuf varint")


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _rewrite_url_field(raw: bytes, replacement: str) -> bytes:
    """Replace only field5's length and value in the ORIGINAL protobuf wire.

    Data submessages stay opaque. This retains field order, unknown bytes,
    packed/unpacked integer representation, and even other valid noncanonical
    varints. A second field5 is rejected instead of applying last-value-wins.
    Deprecated top-level groups are deliberately unsupported in this archive.
    """
    offset = 0
    url_span = None
    while offset < len(raw):
        tag, offset = _read_varint(raw, offset)
        number, kind = tag >> 3, tag & 7
        if not 1 <= number <= 2**29-1:
            raise OctoManifestError("Invalid top-level Octo protobuf field number")
        if number == 5 and (kind != 2 or url_span is not None):
            raise OctoManifestError("Octo protobuf requires exactly one length-delimited URL field")
        if kind == 0:
            _, offset = _read_varint(raw, offset)
        elif kind in (1, 5):
            offset += 8 if kind == 1 else 4
            if offset > len(raw):
                raise OctoManifestError("Truncated top-level Octo protobuf fixed field")
        elif kind == 2:
            length_start = offset
            length, value_start = _read_varint(raw, offset)
            if length > len(raw) - value_start:
                raise OctoManifestError("Truncated top-level Octo protobuf bytes field")
            offset = value_start + length
            if number == 5:
                if raw[value_start:offset] != _UPSTREAM_FORMAT.encode("ascii"):
                    raise OctoManifestError("Octo original URL field differs")
                url_span = length_start, offset
        elif kind in (3, 4):
            raise OctoManifestError("Top-level Octo protobuf groups are unsupported")
        else:
            raise OctoManifestError("Invalid top-level Octo protobuf wire type")
    if url_span is None:
        raise OctoManifestError("Octo protobuf requires exactly one URL field")
    start, end = url_span
    value = replacement.encode("ascii")
    return raw[:start] + _varint(len(value)) + value + raw[end:]


def decrypt_manifest(raw: bytes, *, aes_key: bytes, aes_cbc: AESCallback) -> bytes:
    """Decode an original API envelope; no game RPC tick/header format applies."""
    _key_and_backend(aes_key, aes_cbc)
    if (not isinstance(raw, bytes) or not 32 <= len(raw) <= MAX_MANIFEST_BYTES + 32
            or (len(raw) - 16) % 16):
        raise OctoManifestError("Invalid encrypted Octo manifest length")
    padded = _crypt(aes_cbc, False, aes_key, raw[:16], raw[16:])
    count = padded[-1]
    if not 1 <= count <= 16 or padded[-count:] != bytes((count,)) * count:
        raise OctoManifestError("Invalid Octo manifest padding")
    if len(padded) - count > MAX_MANIFEST_BYTES:
        raise OctoManifestError("Decrypted Octo manifest exceeds its size limit")
    return padded[:-count]


@dataclass(frozen=True)
class OctoObject:
    kind: str
    upload_version: int
    object_name: str
    generation: int
    size: int
    md5: str
    name: str

    @property
    def identity(self) -> tuple[str, int, str, int]:
        return self.kind, self.upload_version, self.object_name, self.generation

    @property
    def upstream_url(self) -> str:
        # Values enter this record only after manifest/path validation. Never
        # interpolate a request hostname, URL, query string, or manifest origin.
        return _UPSTREAM_FORMAT.format(v=self.upload_version, type=self.kind,
                                       o=self.object_name, g=self.generation)

    @property
    def cache_key(self) -> str:
        value = f"{self.kind}\n{self.upload_version}\n{self.object_name}\n{self.generation}"
        return hashlib.sha256(value.encode("ascii")).hexdigest()


class OctoManifest:
    def __init__(self, plain_protobuf: bytes, *, aes_key: bytes, client_key: str,
                 base_url: str, aes_cbc: AESCallback):
        _key_and_backend(aes_key, aes_cbc)
        if (not isinstance(client_key, str) or not client_key
                or len(client_key) > 4096 or not client_key.isascii()
                or any(ord(c) < 33 or ord(c) > 126 for c in client_key)):
            raise OctoManifestError("Invalid Octo application key configuration")
        match = _ORIGIN.fullmatch(base_url) if isinstance(base_url, str) else None
        if not match or (match[1] is not None and int(match[1]) > 65535):
            raise OctoManifestError("Octo local URL must be an HTTP127.0.0.1 origin")
        if (not isinstance(plain_protobuf, bytes)
                or not 1 <= len(plain_protobuf) <= MAX_MANIFEST_BYTES):
            raise OctoManifestError("Invalid Octo manifest size")
        local_url_format = base_url.rstrip("/") + "/octo/{v}/{type}/{o}/{g}"
        rewritten_wire = _rewrite_url_field(plain_protobuf, local_url_format)
        try:
            database = Database.FromString(plain_protobuf)
        except DecodeError:
            raise OctoManifestError("Invalid Octo manifest protobuf") from None
        if not 1 <= database.revision <= 2**31-1 or database.urlFormat != _UPSTREAM_FORMAT:
            raise OctoManifestError("Octo manifest revision or original URL format differs")
        if not database.assetBundleList or not database.resourceList:
            raise OctoManifestError("A complete Octo manifest archive is required")
        if len(database.assetBundleList) + len(database.resourceList) > 100000:
            raise OctoManifestError("Octo manifest has too many records")
        records = {}
        for kind, rows in (("assetbundle", database.assetBundleList),
                           ("resources", database.resourceList)):
            ids, names = set(), set()
            for row in rows:
                if row.id <= 0 or row.id in ids or not row.name or row.name in names:
                    raise OctoManifestError("Octo manifest has invalid or duplicate record identities")
                ids.add(row.id); names.add(row.name)
                if row.state == 4:
                    continue  # Preserve deletion records but never serve their content.
                if (row.state not in (1,2,3) or not 1 <= row.size <= 2**31-1
                        or not _MD5.fullmatch(row.md5) or not _OBJECT_NAME.fullmatch(row.objectName)
                        or not 1 <= row.generation <= 2**64-1
                        or not 1 <= row.uploadVersionId <= 2**31-1):
                    raise OctoManifestError("Octo manifest contains unsupported object metadata")
                record = OctoObject(kind, row.uploadVersionId, row.objectName, row.generation,
                                    row.size, row.md5.lower(), row.name)
                if record.identity in records:
                    raise OctoManifestError("Octo manifest contains duplicate content identities")
                records[record.identity] = record
        self.revision = database.revision
        self.local_url_format = local_url_format
        self._full = rewritten_wire
        self._unchanged = Database(revision=self.revision, urlFormat=self.local_url_format).SerializeToString(
            deterministic=True)
        self.objects = MappingProxyType(records)
        self._key, self._client_key, self._aes = aes_key, client_key, aes_cbc

    def manifest_response(self, path: str, headers: Mapping[str, str]) -> bytes:
        """Return a full revision0 or same-revision delta in the original envelope.

        Older nonzero deltas are unavailable; a409 avoids inventing historical
        manifest changes or rolling back a newer cached revision.
        """
        match = _LIST.fullmatch(path) if isinstance(path, str) else None
        if not match:
            raise OctoRequestError(404, "Unsupported Octo manifest route")
        try:
            pairs = [(str(k).lower(), v) for k, v in headers.items()]
            keys = [v for k, v in pairs if k == "x-octo-key"]
            accepts = [v for k, v in pairs if k == "accept"]
            valid_key = (len(keys) == 1 and isinstance(keys[0], str)
                         and keys[0].isascii() and hmac.compare_digest(keys[0], self._client_key))
            valid_accept_text = (len(accepts) == 1 and isinstance(accepts[0], str)
                                 and accepts[0].isascii() and len(accepts[0]) <= 4096
                                 and not any(ord(c) < 32 or ord(c) == 127 for c in accepts[0]))
            accepted = {v.strip().lower() for v in accepts[0].split(",")} if valid_accept_text else set()
            valid_accept = {"application/x-protobuf", "x-octo-app/212"}.issubset(accepted)
        except (AttributeError, TypeError, ValueError):
            valid_key = valid_accept = False
        if not valid_key or not valid_accept:
            raise OctoRequestError(403, "Octo application headers differ")
        revision = int(match[1])
        if revision not in (0, self.revision):
            raise OctoRequestError(409, "Requested Octo revision is not archived")
        plain = self._full if revision == 0 else self._unchanged
        count = 16 - len(plain) % 16
        iv = os.urandom(16)
        return iv + _crypt(self._aes, True, self._key, iv, plain + bytes((count,)) * count)

    def lookup_object(self, path: str) -> OctoObject:
        match = _OBJECT.fullmatch(path) if isinstance(path, str) else None
        if match:
            version, kind, name, generation = match.groups()
            record = self.objects.get((kind, int(version), name, int(generation)))
            if record is not None:
                return record
        raise OctoRequestError(404, "Octo object is not in the archived whitelist")
