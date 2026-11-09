"""Wire-format and malformed-input tests, with optional public-reference checks."""

import gzip
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from idoly_local.codec import CodecError, MAX_DECOMPRESSED_SIZE, decode, encode


TICKS = 638660000001234567


def compressed_envelope(compressed: bytes) -> bytes:
    raw = bytearray(encode(compressed, ticks=TICKS))
    raw[2] = 1
    return bytes(raw)


class CodecTests(unittest.TestCase):
    def test_official_server_variable_length_key_material(self):
        # Anonymous official replies were observed using 18 and 30 ASCII key
        # bytes, while client requests use 8-byte ticks. No captured user data.
        payload = b"\x0a\x03abc"
        for material in (b"0123456789abcdefgh", b"0123456789abcdefghijklmnopqrst", b"x" * 255):
            body = AES.new(hashlib.md5(b"AJRnFaOnOj").digest(), AES.MODE_CBC,
                           hashlib.md5(b"AJRnFaOnOj" + material).digest()).encrypt(pad(payload, 16))
            raw = (len(material) + 2).to_bytes(2, "little") + bytes((0, len(material))) + material + body
            with self.subTest(length=len(material)):
                self.assertEqual(decode(raw), payload)

    def test_empty_transport_stays_empty(self):
        self.assertEqual(encode(b""), b"")
        self.assertEqual(decode(b""), b"")

    def test_binary_payloads_and_aes_boundaries_round_trip(self):
        for payload in (b"\x08\x01\x12\x03abc", bytes(range(256)), *(b"a" * n for n in (1, 15, 16, 17, 31, 32))):
            with self.subTest(length=len(payload)):
                raw = encode(payload, ticks=TICKS)
                self.assertEqual(raw[:4], b"\x0a\x00\x00\x08")
                self.assertEqual(int.from_bytes(raw[4:12], "little"), TICKS)
                self.assertEqual(decode(raw), payload)

    def test_default_ticks_use_dotnet_epoch_and_100_nanosecond_units(self):
        with patch("idoly_local.codec.time.time_ns", return_value=123456789):
            raw = encode(b"protobuf")
        self.assertEqual(int.from_bytes(raw[4:12], "little"), 621355968001234567)

    def test_tick_uint64_boundaries(self):
        for ticks in (0, 2**64 - 1):
            with self.subTest(ticks=ticks):
                self.assertEqual(decode(encode(b"p", ticks=ticks)), b"p")
        for ticks in (-1, 2**64, 1.5, "123", True):
            with self.subTest(ticks=ticks), self.assertRaisesRegex(CodecError, "unsigned 64-bit"):
                encode(b"p", ticks=ticks)

    def test_non_bytes_inputs_have_clear_errors(self):
        for value in (None, "protobuf", bytearray(b"p")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(CodecError, "payload must be bytes"):
                    encode(value)
                with self.assertRaisesRegex(CodecError, "envelope must be bytes"):
                    decode(value)

    def test_truncated_header(self):
        for length in (1, 3, 4, 11):
            with self.subTest(length=length), self.assertRaisesRegex(CodecError, "truncated envelope header"):
                decode(encode(b"p", ticks=TICKS)[:length])

    def test_header_and_compression_flags_are_checked(self):
        for index, value, message in ((0, 9, "invalid envelope header"), (1, 1, "invalid envelope header"), (3, 7, "invalid envelope header"), (2, 2, "invalid compression flag")):
            raw = bytearray(encode(b"p", ticks=TICKS))
            raw[index] = value
            with self.subTest(index=index), self.assertRaisesRegex(CodecError, message):
                decode(bytes(raw))

    def test_missing_or_partial_ciphertext(self):
        raw = encode(b"p", ticks=TICKS)
        for invalid in (raw[:12], raw[:-1], raw + b"x"):
            with self.subTest(length=len(invalid)), self.assertRaisesRegex(CodecError, "complete 16-byte AES blocks"):
                decode(invalid)

    def test_corrupted_padding(self):
        raw = bytearray(encode(b"a" * 16, ticks=TICKS))
        raw[27] ^= 1  # CBC flip makes the last padding byte 0x11.
        with self.assertRaisesRegex(CodecError, "PKCS#7 padding"):
            decode(bytes(raw))

    def test_gzip_payloads_and_concatenated_members(self):
        payload = b"\x08\x01\x12\x03abc" * 100
        self.assertEqual(decode(compressed_envelope(gzip.compress(payload, mtime=0))), payload)
        joined = gzip.compress(b"first", mtime=0) + gzip.compress(b"second", mtime=0)
        self.assertEqual(decode(compressed_envelope(joined)), b"firstsecond")
        self.assertEqual(decode(compressed_envelope(gzip.compress(b"", mtime=0))), b"")

    def test_invalid_and_truncated_gzip(self):
        compressed = gzip.compress(b"protobuf", mtime=0)
        corrupt_crc = compressed[:-8] + bytes([compressed[-8] ^ 1]) + compressed[-7:]
        corrupt_deflate = compressed[:10] + b"\xff" + compressed[-8:]
        for invalid in (b"not gzip", compressed[:5], compressed[:-1], corrupt_crc, corrupt_deflate):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(CodecError, "gzip payload"):
                decode(compressed_envelope(invalid))

    def test_gzip_decompression_limit(self):
        payload = b"x" * MAX_DECOMPRESSED_SIZE
        self.assertEqual(len(decode(compressed_envelope(gzip.compress(payload, mtime=0)))), MAX_DECOMPRESSED_SIZE)
        too_big = gzip.compress(payload, mtime=0) + gzip.compress(b"x", mtime=0)
        with self.assertRaisesRegex(CodecError, "16 MiB decompression limit"):
            decode(compressed_envelope(too_big))


class SolisClientInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference = Path(__file__).resolve().parents[2] / "SolisClient" / "marshaller.py"
        if not reference.is_file():
            raise unittest.SkipTest("SolisClient/marshaller.py sibling checkout is unavailable")
        spec = importlib.util.spec_from_file_location("solis_reference_marshaller", reference)
        cls.marshaller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.marshaller)

    def test_wire_bytes_match_reference_encoder(self):
        for payload in (b"", b"p", b"a" * 16, bytes(range(256))):
            with self.subTest(length=len(payload)), patch.object(self.marshaller, "_get_tick_bytes", return_value=TICKS.to_bytes(8, "little")):
                ours = encode(payload, ticks=TICKS)
                reference = self.marshaller.serialize(payload)
                self.assertEqual(ours, reference)
                self.assertEqual(self.marshaller.deserialize(ours), payload)
                self.assertEqual(decode(reference), payload)

    def test_reference_accepts_gzip_envelope(self):
        payload = b"\x08\x01\x12\x03abc" * 100
        raw = compressed_envelope(gzip.compress(payload, mtime=0))
        self.assertEqual(self.marshaller.deserialize(raw), payload)
        self.assertEqual(decode(raw), payload)


if __name__ == "__main__":
    unittest.main()
