#!/usr/bin/env python3
"""Redirect only the pinned Android client's Octo origin, retaining its signer.

No SDK, native instructions, Android resources, package identity or saved data
are changed. The normal release and disposable emulator QA inputs have distinct
signing identities; an output must retain the input's verified certificate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from urllib.parse import urlsplit
from zipfile import ZipFile

from idoly_local.client_patch import literal_rows


METADATA = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
ORIGINAL_ORIGIN = b"https://api.octo-cloud.com/"
LITERAL_INDEX = 30209
DEFAULT_ORIGIN = "http://127.0.0.1:8080/"
METADATA_SHA256 = "681390058fdfbb1f54d3d0f09b9d66ad03312696e07caee4890d3cb1e1a898c0"
PROFILES = {
    "2be12648e8fb416de07ea882278f38f9c4a4fb3798d210d7dc8d4423cef1127a": {
        "name": "normal-local-emulator-ui-qa-v2", "qa_only": True,
        "signer": "d94173bdb64bfb6fc75deca8cfa66bb8284a71f47cd800e1bb347abe6ee93259",
    },
    "28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b": {
        "name": "published-normal-local", "qa_only": False,
        "signer": "86fbcf5674eb086f74a95756d68a8db52e203b418d3874b440ecabdf259d6a81",
    },
}


def normalize_origin(origin: str) -> str:
    try:
        parsed = urlsplit(origin)
        valid = (isinstance(origin, str) and origin.isascii()
                 and all(32 < ord(c) < 127 for c in origin)
                 and parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                 and parsed.username is None and parsed.password is None
                 and parsed.port is not None and 1 <= parsed.port <= 65535
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and "\\" not in origin)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("Octo origin must be an HTTP origin on 127.0.0.1 with an explicit port")
    return origin.rstrip("/") + "/"


def patch_octo_metadata(metadata: bytes, origin: str = DEFAULT_ORIGIN) -> tuple[bytes, dict]:
    replacement = normalize_origin(origin).encode("ascii")
    header, rows = literal_rows(metadata)
    selected = [row for row in rows if row[3] == ORIGINAL_ORIGIN]
    if len(selected) != 1 or selected[0][0] != LITERAL_INDEX:
        raise ValueError("Expected the one original Octo origin at literal 30209")
    row = selected[0]
    if len(replacement) > len(row[3]):
        raise ValueError("Octo origin exceeds the original literal allocation")
    start, end = row[2], row[2] + len(row[3])
    if any(other[0] != row[0] and max(start, other[2]) < min(end, other[2] + len(other[3]))
           for other in rows):
        raise ValueError("Octo origin overlaps another metadata literal")
    changed = bytearray(metadata)
    struct.pack_into("<I", changed, row[1], len(replacement))
    absolute = header[4] + start
    changed[absolute:absolute + len(row[3])] = replacement.ljust(len(row[3]), b"\0")
    result = bytes(changed)
    after_header, after_rows = literal_rows(result)
    if (after_header != header or len(result) != len(metadata) or len(after_rows) != len(rows)
            or any(after[3] != (replacement if before[0] == row[0] else before[3])
                   for before, after in zip(rows, after_rows))):
        raise ValueError("Octo patch changed another literal or metadata section")
    allowed = set(range(row[1], row[1] + 4)) | set(range(absolute, absolute + len(row[3])))
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(metadata, result))):
        raise ValueError("Octo patch changed bytes outside the one literal")
    return result, {
        "origin": replacement.decode(), "literal_index": row[0], "literal_row_offset": row[1],
        "literal_data_offset": absolute, "metadata_bytes": len(metadata),
        "input_sha256": hashlib.sha256(metadata).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "changed_byte_count": sum(a != b for a, b in zip(metadata, result)),
        "all_other_literals_and_sections_unchanged": True,
    }


def signature_member(name: str) -> bool:
    upper = name.upper()
    return upper == "META-INF/MANIFEST.MF" or (
        upper.startswith("META-INF/") and upper.count("/") == 1
        and upper.endswith((".SF", ".RSA", ".DSA", ".EC")))


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def member_hashes(archive: ZipFile) -> dict:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("APK contains duplicate ZIP members")
    result = {}
    for info in archive.infolist():
        if not signature_member(info.filename):
            with archive.open(info) as stream:
                result[info.filename] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def repack(source: Path, target: Path, metadata: bytes) -> None:
    with ZipFile(source) as incoming, ZipFile(target, "x", allowZip64=True) as outgoing:
        for info in incoming.infolist():
            if signature_member(info.filename):
                continue
            if info.filename == METADATA:
                outgoing.writestr(copy.copy(info), metadata)
            else:
                with incoming.open(info) as src, outgoing.open(copy.copy(info), "w") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)


def _run(command, stage: str, environment: dict):
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True, env=environment)
    if result.returncode:
        # Signing tool diagnostics and environment values never reach reports.
        raise ValueError(f"{stage} failed (exit {result.returncode})")
    return result


def verify_signer(signer_command, source: Path, expected: str, environment: dict) -> None:
    result = _run([*signer_command, "verify", "--verbose", "--print-certs", source],
                  "APK cryptographic verification", environment)
    certificates = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})$",
                              result.stdout, re.MULTILINE)
    if certificates != [expected]:
        raise ValueError("APK signing certificate differs from the pinned input profile")


def package(source: Path, output: Path, *, origin=DEFAULT_ORIGIN, keystore: Path, alias: str,
            storepass_env="IDOLY_CLIENT_KEYSTORE_PASSWORD", keypass_env=None,
            build_tools: Path, java: Path, report_path: Path | None = None) -> dict:
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    report_path = Path(report_path).resolve() if report_path else output.with_suffix(".evidence.json")
    if (source == output or output.suffix != ".apk" or output.exists() or report_path.exists()
            or report_path in (source, output)):
        raise ValueError("Choose new APK and report paths; existing files are preserved")
    original_hash = file_hash(source)
    profile = PROFILES.get(original_hash)
    if profile is None:
        raise ValueError("Source APK is not one of the pinned normal-local inputs")
    key = Path(keystore).resolve(strict=True)
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError("Signing key must be a caller-managed private regular file")
    environment = dict(os.environ)
    keypass_env = keypass_env or storepass_env
    if not alias or not all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", x)
                            for x in (storepass_env, keypass_env)):
        raise ValueError("Signing alias and valid password environment names are required")
    if not environment.get(storepass_env) or not environment.get(keypass_env):
        raise ValueError("Required signing password environment variable is unset")
    sdk = Path(build_tools).resolve(strict=True)
    signer = [Path(java).resolve(strict=True), "-Xmx128m", "-jar", sdk / "lib/apksigner.jar"]
    for tool in (sdk / "zipalign", sdk / "lib/apksigner.jar"):
        if not tool.is_file():
            raise ValueError("Required Android build tool is missing")
    verify_signer(signer, source, profile["signer"], environment)
    with ZipFile(source) as archive:
        before = member_hashes(archive)
        metadata = archive.read(METADATA)
    if hashlib.sha256(metadata).hexdigest() != METADATA_SHA256:
        raise ValueError("Pinned input metadata differs")
    patched, metadata_report = patch_octo_metadata(metadata, origin)
    del metadata
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".idoly-octo-", dir=output.parent) as temporary:
        work = Path(temporary)
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        repack(source, unsigned, patched)
        del patched
        _run([sdk / "zipalign", "-f", "16384", unsigned, aligned], "APK alignment", environment)
        unsigned.unlink()  # Keep at most two APK-sized scratch files, including signer's temp file.
        _run([*signer, "sign", "--ks", key, "--ks-key-alias", alias,
              "--ks-pass", "env:" + storepass_env, "--key-pass", "env:" + keypass_env,
              "--v4-signing-enabled", "false", aligned], "APK signing", environment)
        verify_signer(signer, aligned, profile["signer"], environment)
        _run([sdk / "zipalign", "-c", "16384", aligned], "APK alignment verification", environment)
        with ZipFile(aligned) as archive:
            after = member_hashes(archive)
        expected = {**before, METADATA: metadata_report["output_sha256"]}
        if after != expected or file_hash(source) != original_hash:
            raise ValueError("APK changed beyond Octo metadata/signatures or source changed during build")
        report = {"schema": 1, "input_profile": profile["name"], "qa_only": profile["qa_only"],
                  "input_apk_sha256": original_hash, "output_apk_sha256": file_hash(aligned),
                  "output_bytes": aligned.stat().st_size, "package": "game.qualiarts.idolypride.local",
                  "signer_sha256": profile["signer"], "same_input_signer_verified": True,
                  "metadata": metadata_report, "changed_non_signature_members": [METADATA],
                  "all_other_member_bytes_preserved": True,
                  "preserved_native_and_dex_sha256": {k: v for k, v in before.items()
                                                     if k.startswith("lib/") or re.fullmatch(r"classes\d*\.dex", k)},
                  "sdk_callbacks_flags_clocks_and_saved_data_changed": False,
                  "vm_install_performed": False, "public_release_created": False}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        # Publish without overwrite; hard-link is atomic and avoids another APK copy.
        os.link(aligned, output)
        try:
            with report_path.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
        except BaseException:
            output.unlink()
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--storepass-env", default="IDOLY_CLIENT_KEYSTORE_PASSWORD")
    parser.add_argument("--keypass-env")
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = package(args.source, args.output, origin=args.origin, keystore=args.keystore,
                         alias=args.alias, storepass_env=args.storepass_env, keypass_env=args.keypass_env,
                         build_tools=args.build_tools, java=args.java, report_path=args.report)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Octo origin patch failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
