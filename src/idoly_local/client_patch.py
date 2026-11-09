"""Patch the API origin in an IL2CPP metadata string-literal table.

The replacement is appended to the literal-data section. Later sections move by
an eight-byte multiple, preserving their alignment and relative row indexes.
Game bytes outside the header, selected literal rows and inserted data survive.
"""

from __future__ import annotations

import hashlib
import struct
from urllib.parse import urlsplit


OFFICIAL_API = b"https://api.game-idolypride.jp"
DEFAULT_ENDPOINT = "http://127.0.0.1:50051"
HEADER_WORDS = 64
HEADER_SIZE = HEADER_WORDS * 4


def validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in endpoint):
        raise ValueError("Endpoint must be an ASCII HTTP(S) origin without spaces")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid endpoint host or port") from None
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or "\\" in endpoint or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Endpoint must be an HTTP(S) origin without credentials, path, query or fragment")
    return endpoint.rstrip("/")


def literal_rows(metadata: bytes):
    """Read v31 metadata literal rows, retaining indexes and data locations."""
    if len(metadata) < HEADER_SIZE:
        raise ValueError("Truncated IL2CPP metadata header")
    header = list(struct.unpack_from("<64I", metadata))
    if header[:2] != [0xFAB11BAF, 31] or header[2] != HEADER_SIZE:
        raise ValueError("Only IL2CPP metadata version 31 with a 256-byte header is supported")
    table, count, data, size = header[2:6]
    if count % 8 or table + count > data or data + size > len(metadata):
        raise ValueError("Invalid metadata literal-table boundaries")
    rows = []
    for number, offset in enumerate(range(table, table + count, 8)):
        length, index = struct.unpack_from("<II", metadata, offset)
        if index + length > size:
            raise ValueError("Metadata literal points outside the literal-data section")
        rows.append((number, offset, index, metadata[data + index:data + index + length]))
    return header, rows


def patch_metadata(metadata: bytes, endpoint: str = DEFAULT_ENDPOINT) -> tuple[bytes, dict]:
    endpoint = validate_endpoint(endpoint)
    header, rows = literal_rows(metadata)
    selected = [row for row in rows if row[3] == OFFICIAL_API]
    if not selected:
        raise ValueError("The original API endpoint literal was not found; use an unmodified supported client")
    replacement = endpoint.encode("ascii")
    data_end = header[4] + header[5]
    insertion = replacement + b"\0" * (-len(replacement) % 8)
    mutable = bytearray(metadata)
    for _, offset, _, _ in selected:
        struct.pack_into("<II", mutable, offset, len(replacement), header[5])
    patched = mutable[:data_end] + insertion + mutable[data_end:]
    updated = header.copy()
    for index in range(2, HEADER_WORDS, 2):
        if updated[index] >= data_end:
            updated[index] += len(insertion)
    updated[5] += len(insertion)
    if any(word > 0xFFFFFFFF for word in updated):
        raise ValueError("Patched metadata offsets exceed the format's uint32 range")
    struct.pack_into("<64I", patched, 0, *updated)
    result = bytes(patched)
    _, verified = literal_rows(result)
    for number, _, _, _ in selected:
        if verified[number][3] != replacement:
            raise ValueError("Endpoint replacement verification failed")
    return result, {
        "metadata_version": 31,
        "endpoint": endpoint,
        "literal_indexes": [row[0] for row in selected],
        "inserted_bytes": len(insertion),
        "input_sha256": hashlib.sha256(metadata).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
    }
