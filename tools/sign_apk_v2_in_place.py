#!/usr/bin/env python3
"""Sign one owned RAM APK without making a second complete APK copy.

The existing entry data is read in 1 MiB chunks. Only the bounded central
directory/EOCD tail moves, to make room for an APK Signature Scheme v2 block.
This build tool installs nothing and never changes an input keystore.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile

MIB = 1024 * 1024
MAX_APK = 384 * MIB
MAX_TAIL = 2 * MIB
MAX_KEYSTORE = 128 * 1024
MAGIC = b"APK Sig Block 42"
V2_ID = 0x7109871A
DEFAULT_KEYTOOL = Path("/workspace/.setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin/keytool")


class SigningError(ValueError):
    """Fixed, credential-free failure reasons."""


def need(ok, reason):
    if not ok:
        raise SigningError(reason)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


def read_regular(path, maximum, *, private=False):
    path = Path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
         "Bounded regular input required")
    need(not private or not info.st_mode & 0o077, "Private input permissions differ")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        need(identity(os.fstat(fd)) == identity(info), "Input changed while opening")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        need(len(raw) == info.st_size and identity(path.lstat()) == identity(info),
             "Input changed while reading")
        return raw, identity(info)
    finally:
        os.close(fd)


def load_key(keystore, password, alias, keytool=DEFAULT_KEYTOOL):
    """Read PKCS12 directly, or convert JKS in a private short-lived RAM file."""
    from cryptography.hazmat.primitives.serialization import pkcs12

    keystore = Path(keystore)
    raw, stamp = read_regular(keystore, MAX_KEYSTORE, private=True)
    need(isinstance(password, bytes) and 0 < len(password) <= 1024 and b"\0" not in password,
         "Invalid signing password input")
    if raw[:4] != b"\xfe\xed\xfe\xed":
        try:
            key, cert, _extra = pkcs12.load_key_and_certificates(raw, password)
        except (ValueError, TypeError):
            raise SigningError("Private keystore could not be opened") from None
    else:
        need(isinstance(alias, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", alias),
             "Invalid keystore alias")
        keytool = Path(keytool)
        need(keytool.is_absolute() and keytool.is_file(), "Explicit keytool is unavailable")
        with tempfile.TemporaryDirectory(prefix="idoly-v2-key-", dir="/dev/shm") as temp:
            os.chmod(temp, 0o700)
            converted = Path(temp) / "signer.p12"
            env = dict(os.environ)
            for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"):
                env.pop(name, None)
            env["IDOLY_V2_SIGNING_PASSWORD"] = password.decode("utf-8")
            source_fd = os.open(keystore, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            command = [str(keytool), "-J-Xmx32m", "-J-XX:+UseSerialGC", "-importkeystore",
                       "-srckeystore", "/proc/self/fd/" + str(source_fd), "-srcstoretype", "JKS", "-srcalias", alias,
                       "-srcstorepass:env", "IDOLY_V2_SIGNING_PASSWORD",
                       "-srckeypass:env", "IDOLY_V2_SIGNING_PASSWORD",
                       "-destkeystore", str(converted), "-deststoretype", "PKCS12",
                       "-deststorepass:env", "IDOLY_V2_SIGNING_PASSWORD",
                       "-destkeypass:env", "IDOLY_V2_SIGNING_PASSWORD", "-noprompt"]
            try:
                need(identity(os.fstat(source_fd)) == stamp, "Input keystore changed before conversion")
                result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=30, pass_fds=(source_fd,))
                need(result.returncode == 0 and len(result.stdout) <= 65536
                     and len(result.stderr) <= 65536, "Private keystore conversion failed")
                converted.chmod(0o600)
                exported, _ = read_regular(converted, MAX_KEYSTORE, private=True)
                key, cert, _extra = pkcs12.load_key_and_certificates(exported, password)
            except (ValueError, TypeError, subprocess.TimeoutExpired):
                raise SigningError("Private keystore conversion failed") from None
            finally:
                env.pop("IDOLY_V2_SIGNING_PASSWORD", None)
                os.close(source_fd)
    need(identity(keystore.lstat()) == stamp, "Input keystore changed")
    need(key is not None and cert is not None, "Private key and certificate are required")
    return key, cert


def lp(raw):
    need(len(raw) <= 0xFFFFFFFF, "Signature record exceeds its bound")
    return struct.pack("<I", len(raw)) + raw


def zip_tail(fd, size):
    """Require exactly one ordinary single-disk EOCD and bounded full CD tail."""
    low = max(0, size - 65557)
    tail = os.pread(fd, size - low, low)
    candidates = []
    for at in range(max(0, len(tail) - 21)):
        if tail[at:at + 4] == b"PK\x05\x06" and at + 22 <= len(tail):
            comment = struct.unpack_from("<H", tail, at + 20)[0]
            if at + 22 + comment == len(tail):
                candidates.append(at)
    need(len(candidates) == 1, "Unambiguous EOCD required")
    at = candidates[0]
    eocd = tail[at:]
    disk, cd_disk, on_disk, count, cd_size, cd_at = struct.unpack_from("<4H2I", eocd, 4)
    eocd_at = low + at
    need(disk == cd_disk == 0 and 0 < on_disk == count < 0xFFFF,
         "Single-disk ordinary ZIP required")
    need(cd_size != 0xFFFFFFFF and cd_at != 0xFFFFFFFF
         and cd_at + cd_size == eocd_at and cd_size + len(eocd) <= MAX_TAIL,
         "Central directory exceeds its bound")
    need(eocd_at < 20 or os.pread(fd, 4, eocd_at - 20) != b"PK\x06\x07",
         "Archive-level ZIP64 is not supported")
    need(cd_at < 16 or os.pread(fd, 16, cd_at - 16) != MAGIC,
         "APK already has a signing block")
    central = os.pread(fd, cd_size, cd_at)
    need(len(central) == cd_size and len(os.pread(fd, len(eocd), eocd_at)) == len(eocd),
         "ZIP tail was truncated")
    position = 0
    for _index in range(count):
        need(position + 46 <= len(central) and central[position:position + 4] == b"PK\x01\x02",
             "Invalid central directory entry")
        name_size, extra_size, comment_size, start_disk = struct.unpack_from("<4H", central, position + 28)
        compressed = struct.unpack_from("<I", central, position + 20)[0]
        local = struct.unpack_from("<I", central, position + 42)[0]
        need(start_disk == 0 and compressed != 0xFFFFFFFF and local != 0xFFFFFFFF
             and position + 46 + name_size + extra_size + comment_size <= len(central)
             and local + 30 <= cd_at, "Invalid entry extent")
        header = os.pread(fd, 30, local)
        need(len(header) == 30 and header[:4] == b"PK\x03\x04", "Invalid local header")
        local_name, local_extra = struct.unpack_from("<HH", header, 26)
        need(local + 30 + local_name + local_extra + compressed <= cd_at,
             "Entry data overlaps central directory")
        position += 46 + name_size + extra_size + comment_size
    need(position == len(central), "Central directory entry count differs")
    return cd_at, central, eocd


def content_digest(fd, cd_at, central, eocd):
    """APK v2 section-separated 1 MiB SHA256 chunk digest."""
    chunks = []
    prefix_sha = hashlib.sha256()
    position = 0
    while position < cd_at:
        length = min(MIB, cd_at - position)
        raw = os.pread(fd, length, position)
        need(len(raw) == length, "Entry prefix was truncated")
        position += len(raw)
        prefix_sha.update(raw)
        chunks.append(hashlib.sha256(b"\xa5" + struct.pack("<I", len(raw)) + raw).digest())
    for section in (central, eocd):
        for at in range(0, len(section), MIB):
            raw = section[at:at + MIB]
            chunks.append(hashlib.sha256(b"\xa5" + struct.pack("<I", len(raw)) + raw).digest())
    digest = hashlib.sha256(b"\x5a" + struct.pack("<I", len(chunks)) + b"".join(chunks)).digest()
    return digest, prefix_sha.hexdigest(), len(chunks)


def signing_block(digest, key, cert):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    public = key.public_key().public_bytes(serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    need(public == cert.public_key().public_bytes(serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo), "Certificate public key differs")
    if isinstance(key, rsa.RSAPrivateKey):
        need(key.key_size >= 2048, "RSA signing key is too small")
        algorithm = 0x0103
        sign = lambda data: key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        need(isinstance(key.curve, ec.SECP256R1), "Unsupported EC signing curve")
        algorithm = 0x0201
        sign = lambda data: key.sign(data, ec.ECDSA(hashes.SHA256()))
    else:
        raise SigningError("Unsupported private key type")
    certificate = cert.public_bytes(serialization.Encoding.DER)
    signed = lp(lp(struct.pack("<I", algorithm) + lp(digest))) + lp(lp(certificate)) + lp(b"")
    signatures = lp(struct.pack("<I", algorithm) + lp(sign(signed)))
    signer = lp(signed) + lp(signatures) + lp(public)
    value = lp(lp(signer))
    pair = struct.pack("<QI", 4 + len(value), V2_ID) + value
    size = len(pair) + 24
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + MAGIC
    need(len(block) <= 65536, "Signing block exceeds its bound")
    return block, hashlib.sha256(certificate).hexdigest(), algorithm


def sign_apk_in_place(apk, key, cert, *, expected_certificate_sha256):
    apk = Path(apk)
    need(apk.is_absolute() and apk.parent.resolve(strict=True).is_relative_to(Path("/dev/shm")),
         "Owned RAM APK required")
    info = apk.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
         and info.st_nlink == 1 and 0 < info.st_size <= MAX_APK,
         "Single-link bounded APK required")
    fd = os.open(apk, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        need(identity(os.fstat(fd)) == identity(info), "APK changed while opening")
        cd_at, central, eocd = zip_tail(fd, info.st_size)
        digest, prefix_sha, count = content_digest(fd, cd_at, central, eocd)
        block, cert_sha, algorithm = signing_block(digest, key, cert)
        need(re.fullmatch(r"[0-9a-f]{64}", expected_certificate_sha256 or "")
             and cert_sha == expected_certificate_sha256, "Signing certificate differs")
        need(identity(os.fstat(fd)) == identity(info) and identity(apk.lstat()) == identity(info),
             "APK changed before signing")
        patched = bytearray(eocd)
        struct.pack_into("<I", patched, 16, cd_at + len(block))
        tail = block + central + patched
        need(len(tail) <= MAX_TAIL + 65536 and info.st_size + len(block) <= MAX_APK,
             "Signed APK exceeds its capacity")
        position = 0
        while position < len(tail):
            written = os.pwrite(fd, tail[position:], cd_at + position)
            need(written > 0, "Signing tail write failed")
            position += written
        os.ftruncate(fd, info.st_size + len(block))
        os.fsync(fd)
        need(os.fstat(fd).st_ino == info.st_ino and os.fstat(fd).st_dev == info.st_dev
             and os.fstat(fd).st_nlink == 1, "APK inode changed while signing")
        check = hashlib.sha256()
        position = 0
        while position < cd_at:
            raw = os.pread(fd, min(MIB, cd_at - position), position)
            need(raw, "Signed APK prefix was truncated")
            check.update(raw); position += len(raw)
        need(check.hexdigest() == prefix_sha, "Signing changed original entry bytes")
        output = hashlib.sha256()
        position = 0
        size = os.fstat(fd).st_size
        while position < size:
            raw = os.pread(fd, min(MIB, size - position), position)
            need(raw, "Signed APK was truncated")
            output.update(raw); position += len(raw)
        return {"status": "PASS_IN_PLACE_APK_V2_SIGNED", "apk_bytes": size,
                "apk_sha256": output.hexdigest(), "certificate_sha256": cert_sha,
                "signature_algorithm": algorithm, "signing_block_bytes": len(block),
                "chunk_bytes": MIB, "digest_chunks": count, "central_directory_bytes": len(central),
                "entry_prefix_sha256": prefix_sha, "original_entry_data_unchanged": True,
                "second_complete_APK_copy_created": False}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    keys = parser.add_mutually_exclusive_group(required=True)
    keys.add_argument("--keystore", type=Path)
    keys.add_argument("--keystore-env")
    parser.add_argument("--key-alias", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--password-file", type=Path)
    group.add_argument("--password-env")
    parser.add_argument("--expected-certificate-sha256", required=True)
    parser.add_argument("--keytool", type=Path, default=DEFAULT_KEYTOOL)
    args = parser.parse_args()
    os.umask(0o077)
    if args.keystore_env is not None:
        need(re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", args.keystore_env),
             "Invalid keystore environment reference")
        args.keystore = Path(os.environ[args.keystore_env])
    if args.password_file is not None:
        password, _ = read_regular(args.password_file, 1024, private=True)
        password = password.rstrip(b"\r\n")
    else:
        need(re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", args.password_env or ""),
             "Invalid password environment reference")
        password = os.environ[args.password_env].encode("utf-8")
    key, cert = load_key(args.keystore, password, args.key_alias, args.keytool)
    result = sign_apk_in_place(args.apk, key, cert,
        expected_certificate_sha256=args.expected_certificate_sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (SigningError, OSError, KeyError, ValueError) as error:
        raise SystemExit("In-place APK signing failed: " +
                         (str(error) if isinstance(error, SigningError) else type(error).__name__)) from None
