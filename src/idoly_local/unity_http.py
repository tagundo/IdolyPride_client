"""One pinned Unity PlayerSettings transport-policy change for local HTTP.

Unity 2022.3's InsecureHttpOption is NotAllowed=0, DevelopmentOnly=1,
AlwaysAllowed=2. Android's existing network security policy still permits plain
HTTP only for 127.0.0.1. No TLS trust, SDK code or initialization flag is changed.

Two independent UnityPy type-tree audits identified PlayerSettings/pathID1,
class129, object149296..150156, with its final int at150152. Both audits proved
the original object round-trip byte-exact and changing this field alters one
byte only. A full-file fingerprint binds this fixed offset to that exact input.
"""
from __future__ import annotations

import hashlib
import struct


MEMBER = "assets/bin/Data/globalgamemanagers"
ORIGINAL_SHA256 = "7fb7ed1fbcdeb0c6be8ad458e0df695e5f8ef29e8d31606efd150afadcf6c2b7"
PATCHED_SHA256 = "21c7da3b2fb6e0775301667d6a809918144ce5939f0e99908a467ce29ac337d1"
FILE_BYTES = 21043436
OBJECT_START = 149296
OBJECT_BYTES = 860
FIELD_OFFSET = 150152
NOT_ALLOWED = 0
ALWAYS_ALLOWED = 2
ENUM_SOURCE = "https://raw.githubusercontent.com/Unity-Technologies/UnityCsReference/2022.3/Editor/Mono/PlayerSettings.bindings.cs"
ENUM_SOURCE_SHA256 = "7b545e944dac68029e6fede7f28bbeb5db0a68eb48510e09a667cb9c12d89ff9"


def validate_shape(data: bytes) -> int:
    if len(data) != FILE_BYTES:
        raise ValueError("Unity settings size differs from the pinned 6.1.1 input")
    if (struct.unpack_from(">I", data, 8)[0] != 22 or data[16] != 0
            or struct.unpack_from(">Q", data, 24)[0] != len(data)
            or struct.unpack_from(">Q", data, 32)[0] != OBJECT_START
            or data[48:60] != b"2022.3.57f1\0"
            or FIELD_OFFSET != OBJECT_START + OBJECT_BYTES - 4):
        raise ValueError("Unity SerializedFile version, endian, Unity version or object layout differs")
    return struct.unpack_from("<i", data, FIELD_OFFSET)[0]


def patch_player_http(data: bytes) -> tuple[bytes, dict]:
    previous = validate_shape(data)
    if previous != NOT_ALLOWED:
        raise ValueError("Expected the original Unity HTTP policy NotAllowed")
    if hashlib.sha256(data).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Unity settings fingerprint differs; fixed-offset patch refused")
    mutable = bytearray(data)
    struct.pack_into("<i", mutable, FIELD_OFFSET, ALWAYS_ALLOWED)
    result = bytes(mutable)
    if (result[:FIELD_OFFSET] != data[:FIELD_OFFSET]
            or result[FIELD_OFFSET + 4:] != data[FIELD_OFFSET + 4:]
            or result[FIELD_OFFSET:FIELD_OFFSET + 4] != b"\x02\0\0\0"
            or hashlib.sha256(result).hexdigest() != PATCHED_SHA256):
        raise ValueError("Unity HTTP patch changed bytes outside the one audited policy field")
    return result, {"member": MEMBER, "unity_version": "2022.3.57f1", "serialized_file_version": 22,
        "class_id": 129, "path_id": 1, "object_start": OBJECT_START, "object_bytes": OBJECT_BYTES,
        "field": "insecureHttpOption", "field_type": "int32 little-endian", "field_offset": FIELD_OFFSET,
        "previous_value": previous, "value": ALWAYS_ALLOWED, "value_name": "AlwaysAllowed",
        "changed_byte_count": 1, "input_sha256": ORIGINAL_SHA256, "output_sha256": PATCHED_SHA256,
        "enum_source": ENUM_SOURCE, "enum_source_sha256": ENUM_SOURCE_SHA256,
        "android_cleartext_hosts_unchanged": ["127.0.0.1"],
        "sdk_initialization_success_flags_or_tls_validation_changed": False}
