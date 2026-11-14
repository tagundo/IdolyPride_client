"""Small owned-RAM tests; actual server-key/apksigner proof is kept separately."""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZipInfo

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    raise unittest.SkipTest("Build-only cryptography dependency is unavailable")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("idoly_in_place_v2_test", ROOT / "tools/sign_apk_v2_in_place.py")
signer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer)


def certificate(key):
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral signing unit test")])
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(101).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))


def independent_verify(path):
    """Separate parser/digest path; never calls the signing tool's helpers."""
    raw = path.read_bytes()
    end = raw.rfind(b"PK\x05\x06")
    if end < 0 or len(raw) != end + 22 + struct.unpack_from("<H", raw, end + 20)[0]:
        raise ValueError("EOCD differs")
    central = struct.unpack_from("<I", raw, end + 16)[0]
    if raw[central - 16:central] != b"APK Sig Block 42":
        raise ValueError("Missing block")
    length = struct.unpack_from("<Q", raw, central - 24)[0]
    beginning = central - length - 8
    if struct.unpack_from("<Q", raw, beginning)[0] != length:
        raise ValueError("Block length differs")
    pair_size, pair_id = struct.unpack_from("<QI", raw, beginning + 8)
    if pair_id != 0x7109871A:
        raise ValueError("V2 pair differs")
    value = raw[beginning + 20:beginning + 16 + pair_size]

    def consume(data, at=0):
        count = struct.unpack_from("<I", data, at)[0]
        last = at + 4 + count
        if last > len(data):
            raise ValueError("Truncated signed data")
        return data[at + 4:last], last

    signers, at = consume(value)
    if at != len(value):
        raise ValueError("Signer envelope differs")
    row, at = consume(signers)
    if at != len(signers):
        raise ValueError("More than one signer")
    signed, at = consume(row)
    signatures, at = consume(row, at)
    public, at = consume(row, at)
    digests, offset = consume(signed)
    certs, offset = consume(signed, offset)
    attributes, offset = consume(signed, offset)
    if at != len(row) or offset != len(signed) or attributes:
        raise ValueError("Unexpected signed fields")
    digest_record, at = consume(digests)
    algorithm = struct.unpack_from("<I", digest_record)[0]
    expected_digest, after = consume(digest_record, 4)
    if at != len(digests) or after != len(digest_record):
        raise ValueError("Digest record differs")
    signature_record, at = consume(signatures)
    signature, after = consume(signature_record, 4)
    if at != len(signatures) or after != len(signature_record) or struct.unpack_from("<I", signature_record)[0] != algorithm:
        raise ValueError("Signature record differs")
    cert_der, after = consume(certs)
    if after != len(certs):
        raise ValueError("Certificate count differs")
    cert = x509.load_der_x509_certificate(cert_der)
    key = cert.public_key()
    if key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != public:
        raise ValueError("Public key differs")
    patched = bytearray(raw[end:])
    struct.pack_into("<I", patched, 16, beginning)
    chunk_digests = []
    for section in (raw[:beginning], raw[central:end], patched):
        for position in range(0, len(section), 1048576):
            chunk = section[position:position + 1048576]
            chunk_digests.append(hashlib.sha256(b"\xa5" + struct.pack("<I", len(chunk)) + chunk).digest())
    actual = hashlib.sha256(b"\x5a" + struct.pack("<I", len(chunk_digests)) + b"".join(chunk_digests)).digest()
    if actual != expected_digest:
        raise ValueError("Content digest differs")
    if algorithm == 0x0103:
        key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    elif algorithm == 0x0201:
        key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
    else:
        raise ValueError("Algorithm differs")
    return cert, beginning, central, end


class InPlaceV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.rsa_cert = certificate(cls.rsa)
        cls.ec = ec.generate_private_key(ec.SECP256R1())
        cls.ec_cert = certificate(cls.ec)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="idoly-inplace-test-", dir="/dev/shm")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def apk(self, *, comment=b"", large=False, force_zip64=True):
        path = self.directory / "candidate.apk"
        with ZipFile(path, "x") as archive:
            archive.comment = comment
            with archive.open(ZipInfo("classes.dex"), "w", force_zip64=force_zip64) as stream:
                stream.write(b"prefix" + (b"a" * (1048576 + 37) if large else b"small"))
            archive.writestr("assets/example.txt", b"preserve these exact entry bytes")
        return path

    def sign(self, path, *, key=None, cert=None, expected=None):
        key, cert = key or self.rsa, cert or self.rsa_cert
        expected = expected or hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        return signer.sign_apk_in_place(path, key, cert, expected_certificate_sha256=expected)

    def test_rsa_roundtrip_preserves_inode_and_all_entry_bytes_including_local_zip64(self):
        path = self.apk(comment=b"valid comment", large=True)
        before = path.stat()
        with ZipFile(path) as archive:
            entries = {info.filename: archive.read(info) for info in archive.infolist()}
        report = self.sign(path)
        verified, *_ = independent_verify(path)
        self.assertEqual(verified.fingerprint(hashes.SHA256()), self.rsa_cert.fingerprint(hashes.SHA256()))
        self.assertEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(path.stat().st_size, before.st_size + report["signing_block_bytes"])
        self.assertEqual(report["signature_algorithm"], 0x0103)
        self.assertFalse(report["second_complete_APK_copy_created"])
        with ZipFile(path) as archive:
            self.assertEqual({info.filename: archive.read(info) for info in archive.infolist()}, entries)
            self.assertEqual(archive.comment, b"valid comment")

    def test_ec_roundtrip(self):
        path = self.apk()
        report = self.sign(path, key=self.ec, cert=self.ec_cert)
        independent_verify(path)
        self.assertEqual(report["signature_algorithm"], 0x0201)

    def test_content_central_directory_and_comment_tampering_are_detected(self):
        path = self.apk(comment=b"comment", large=True)
        self.sign(path)
        raw = path.read_bytes()
        _, beginning, central, end = independent_verify(path)
        with ZipFile(path) as archive:
            info = archive.getinfo("classes.dex")
        name, extra = struct.unpack_from("<HH", raw, info.header_offset + 26)
        positions = [info.header_offset + 30 + name + extra + 2, central + 16, end + 22]
        self.assertLess(positions[0], beginning)
        for position in positions:
            with self.subTest(position=position):
                changed = bytearray(raw); changed[position] ^= 1; path.write_bytes(changed)
                with self.assertRaises(ValueError):
                    independent_verify(path)

    def test_wrong_certificate_rejected_without_mutation(self):
        path = self.apk(); before = path.read_bytes()
        with self.assertRaisesRegex(signer.SigningError, "certificate differs"):
            self.sign(path, expected="0" * 64)
        self.assertEqual(path.read_bytes(), before)

    def test_second_signing_is_rejected_without_mutation(self):
        path = self.apk(); self.sign(path); before = path.read_bytes()
        with self.assertRaisesRegex(signer.SigningError, "already has"):
            self.sign(path)
        self.assertEqual(path.read_bytes(), before)

    def test_symlink_and_hardlink_rejected_without_mutation(self):
        path = self.apk(); before = path.read_bytes(); link = self.directory / "link.apk"
        link.symlink_to(path)
        with self.assertRaises(signer.SigningError):
            self.sign(link)
        link.unlink(); os.link(path, link)
        with self.assertRaisesRegex(signer.SigningError, "Single-link"):
            self.sign(path)
        self.assertEqual(path.read_bytes(), before)

    def test_trailing_bytes_and_ambiguous_eocd_rejected_without_mutation(self):
        path = self.apk(); raw = path.read_bytes()
        for tail in (b"trailing", None):
            with self.subTest(tail=tail):
                if tail is not None:
                    candidate = raw + tail
                else:
                    outer = bytearray(raw)
                    struct.pack_into("<H", outer, len(outer) - 2, 22)
                    candidate = outer + raw[-22:]
                path.write_bytes(candidate)
                with self.assertRaisesRegex(signer.SigningError, "EOCD"):
                    self.sign(path)
                self.assertEqual(path.read_bytes(), candidate)

    def test_large_central_directory_rejected_before_mutation(self):
        path = self.directory / "large-tail.apk"
        with ZipFile(path, "x") as archive:
            for index in range(33):
                info = ZipInfo(str(index)); info.comment = b"x" * 65535
                archive.writestr(info, b"a")
        before = path.read_bytes()
        with self.assertRaisesRegex(signer.SigningError, "Central directory"):
            self.sign(path)
        self.assertEqual(path.read_bytes(), before)

    def test_archive_zip64_and_multidisk_rejected(self):
        path = self.apk(); raw = path.read_bytes()
        for offset, fmt, value in ((len(raw) - 18, "<H", 1), (len(raw) - 6, "<I", 0xFFFFFFFF)):
            with self.subTest(offset=offset):
                changed = bytearray(raw); struct.pack_into(fmt, changed, offset, value); path.write_bytes(changed)
                with self.assertRaises(signer.SigningError):
                    self.sign(path)
                self.assertEqual(path.read_bytes(), changed)

    def test_pkcs12_loading_preserves_source_and_rejects_wrong_password(self):
        path = self.directory / "unit.p12"
        raw = pkcs12.serialize_key_and_certificates(b"unit", self.rsa, self.rsa_cert, None,
            serialization.BestAvailableEncryption(b"unit-test-only"))
        path.write_bytes(raw); path.chmod(0o600)
        key, cert = signer.load_key(path, b"unit-test-only", "unit")
        self.assertEqual(key.public_key().public_numbers(), self.rsa.public_key().public_numbers())
        self.assertEqual(cert.fingerprint(hashes.SHA256()), self.rsa_cert.fingerprint(hashes.SHA256()))
        with self.assertRaises(signer.SigningError):
            signer.load_key(path, b"wrong", "unit")
        self.assertEqual(path.read_bytes(), raw)

    def test_cli_environment_references_sign_without_disclosing_credentials(self):
        path = self.apk()
        private = self.directory / "private-test-key.p12"
        password = "ephemeral-unit-password-only"
        raw = pkcs12.serialize_key_and_certificates(b"unit", self.rsa, self.rsa_cert, None,
            serialization.BestAvailableEncryption(password.encode()))
        private.write_bytes(raw); private.chmod(0o600)
        expected = self.rsa_cert.fingerprint(hashes.SHA256()).hex()
        env = dict(os.environ, IDOLY_TEST_KEYSTORE=str(private), IDOLY_TEST_PASSWORD=password)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/sign_apk_v2_in_place.py"),
            "--apk", str(path), "--keystore-env", "IDOLY_TEST_KEYSTORE",
            "--password-env", "IDOLY_TEST_PASSWORD", "--key-alias", "unit",
            "--expected-certificate-sha256", expected], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=30)
        report = json.loads(result.stdout)
        self.assertEqual(report["certificate_sha256"], expected)
        for secret in (password.encode(), str(private).encode()):
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(private.read_bytes(), raw)
        independent_verify(path)

    @unittest.skipUnless(signer.DEFAULT_KEYTOOL.is_file(), "Cached keytool unavailable")
    def test_jks_conversion_uses_owned_private_temporary_and_preserves_source(self):
        p12 = self.directory / "input.p12"
        p12.write_bytes(pkcs12.serialize_key_and_certificates(b"unit", self.rsa, self.rsa_cert, None,
            serialization.BestAvailableEncryption(b"unit-test-only")))
        jks = self.directory / "input.jks"
        env = dict(os.environ, IDOLY_TEST_KEY_PASSWORD="unit-test-only")
        subprocess.run([str(signer.DEFAULT_KEYTOOL), "-J-Xmx32m", "-J-XX:+UseSerialGC", "-importkeystore",
            "-srckeystore", str(p12), "-srcstoretype", "PKCS12", "-srcstorepass:env", "IDOLY_TEST_KEY_PASSWORD",
            "-destkeystore", str(jks), "-deststoretype", "JKS", "-deststorepass:env", "IDOLY_TEST_KEY_PASSWORD",
            "-destkeypass:env", "IDOLY_TEST_KEY_PASSWORD", "-noprompt"], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
        jks.chmod(0o600); before = jks.read_bytes()
        key, cert = signer.load_key(jks, b"unit-test-only", "unit")
        self.assertEqual(key.public_key().public_numbers(), self.rsa.public_key().public_numbers())
        self.assertEqual(cert.fingerprint(hashes.SHA256()), self.rsa_cert.fingerprint(hashes.SHA256()))
        self.assertEqual(jks.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
