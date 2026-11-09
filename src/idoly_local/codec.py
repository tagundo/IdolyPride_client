"""IDOLY PRIDE's encrypted protobuf envelope.

Independently implemented from the public wire-format reference in
Vilebbit/SolisClient's ``marshaller.py``. The envelope carries .NET ticks,
AES-CBC ciphertext and an optional gzip flag; it provides no integrity tag.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import time
import zlib

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None


_SEED = b"AJRnFaOnOj"
_KEY = hashlib.md5(_SEED).digest()
_UNIX_EPOCH_TICKS = 621355968000000000
_TICK_BYTES = 8
_HEADER_BYTES = 4 + _TICK_BYTES
MAX_DECOMPRESSED_SIZE = 16 * 1024 * 1024
_cipher_backend = None


class CodecError(ValueError):
    """The payload or encrypted envelope is malformed or exceeds its limit."""


def configure_aes(callback=None):
    """Select an embedded platform AES/CBC/NoPadding implementation.

    Android supplies javax.crypto through its Python bridge. The wire format,
    key derivation and PKCS#7 remain shared with the desktop implementation.
    """
    global _cipher_backend
    if callback is not None and not callable(callback):
        raise ValueError("AES backend must be callable")
    _cipher_backend = callback


def _crypt(encrypt: bool, data: bytes, iv: bytes) -> bytes:
    if _cipher_backend is not None:
        result = bytes(_cipher_backend(encrypt, _KEY, iv, data))
        if len(result) != len(data):
            raise CodecError("AES backend changed the block-aligned data length")
        return result
    if AES is None:
        raise CodecError("An AES backend must be configured before starting the embedded server")
    cipher = AES.new(_KEY, AES.MODE_CBC, iv)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


def _pad(payload: bytes) -> bytes:
    count = 16 - len(payload) % 16
    return payload + bytes((count,)) * count


def _unpad(payload: bytes) -> bytes:
    if not payload or not 1 <= payload[-1] <= 16 or payload[-payload[-1]:] != bytes((payload[-1],)) * payload[-1]:
        raise ValueError("Invalid PKCS#7 padding")
    return payload[:-payload[-1]]


def encode(payload: bytes, *, ticks: int | None = None) -> bytes:
    """Wrap protobuf bytes in an uncompressed encrypted envelope.

    An empty protobuf remains an empty transport body, as in SolisClient.
    ``ticks`` can fix the uint64 .NET tick header for reproducible captures.
    """
    if not isinstance(payload, bytes):
        raise CodecError("payload must be bytes")
    if not payload:
        return b""
    if ticks is None:
        ticks = _UNIX_EPOCH_TICKS + time.time_ns() // 100
    if isinstance(ticks, bool) or not isinstance(ticks, int) or not 0 <= ticks < 2**64:
        raise CodecError("ticks must be an unsigned 64-bit integer")
    tick_bytes = ticks.to_bytes(_TICK_BYTES, "little")
    iv = hashlib.md5(_SEED + tick_bytes).digest()
    ciphertext = _crypt(True, _pad(payload), iv)
    return b"\x0a\x00\x00\x08" + tick_bytes + ciphertext


def decode(raw: bytes) -> bytes:
    """Decrypt an envelope, validating its header, padding and gzip stream.

    Decompressed data is limited to 16 MiB, including concatenated gzip members.
    Invalid input raises :class:`CodecError`, a :class:`ValueError` subclass.
    """
    if not isinstance(raw, bytes):
        raise CodecError("envelope must be bytes")
    if not raw:
        return b""
    if len(raw) < 4:
        raise CodecError("truncated envelope header: expected at least 4 bytes")
    key_length = raw[3]
    # Requests normally use eight .NET tick bytes. The official server uses
    # variable-length random key material; DataSize counts the flag/key-length
    # bytes and key, excluding the two-byte DataSize field itself.
    if key_length == 0 or int.from_bytes(raw[:2], "little") != key_length + 2:
        raise CodecError("invalid envelope header size")
    header_bytes = 4 + key_length
    if len(raw) < header_bytes:
        raise CodecError("truncated envelope header key")
    if raw[2] not in (0, 1):
        raise CodecError("invalid compression flag: expected 0 or 1")
    body = raw[header_bytes:]
    if not body or len(body) % 16:
        raise CodecError("ciphertext must contain complete 16-byte AES blocks")
    key_material = raw[4:header_bytes]
    iv = hashlib.md5(_SEED + key_material).digest()
    decrypted = _crypt(False, body, iv)
    try:
        payload = _unpad(decrypted)
    except ValueError as exc:
        raise CodecError("invalid ciphertext PKCS#7 padding") from exc
    if raw[2] == 0:
        return payload
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
            result = stream.read(MAX_DECOMPRESSED_SIZE + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise CodecError("invalid or truncated gzip payload") from exc
    if len(result) > MAX_DECOMPRESSED_SIZE:
        raise CodecError("gzip payload exceeds the 16 MiB decompression limit")
    return result
