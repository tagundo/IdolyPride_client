#!/usr/bin/env python3
"""Create an emulator-only APK using the game's verified software AES exports.

This is not the production local client. Inputs are preserved; the output gets
an ephemeral QA signature and must only be installed in disposable test data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qa-native-aes"))
from qa_fast_aes import patch_library, verify_vectors
from qa_iap import patch_initializer, verify_abi

SOURCE_SHA256 = "28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b"
LIBRARY = "lib/arm64-v8a/libFastAES.so"
IL2CPP = "lib/arm64-v8a/libil2cpp.so"
MARKER = "assets/idoly-qa-only-software-aes.json"


def signature_member(name):
    upper = name.upper()
    return upper == "META-INF/MANIFEST.MF" or (upper.startswith("META-INF/") and upper.count("/") == 1
        and upper.endswith((".SF", ".RSA", ".DSA", ".EC")))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(command, environment=None):
    result = subprocess.run([str(value) for value in command], capture_output=True, text=True, env=environment)
    if result.returncode:
        raise ValueError("QA packaging command failed: " + str(command[0]) + "\n" + (result.stderr or result.stdout)[-1600:])
    return result.stdout


def package(source, output, build_tools, *, expected_source_sha256=SOURCE_SHA256, java=None,
            emulator_no_store=False):
    source, output, build_tools = Path(source).resolve(), Path(output).resolve(), Path(build_tools).resolve()
    if output.exists() or source == output:
        raise ValueError("Use a new QA output filename; source and existing outputs are preserved")
    if digest(source) != expected_source_sha256:
        raise ValueError("Source APK SHA-256 differs from the explicitly selected QA input")
    java = Path(java or shutil.which("java") or "").resolve()
    keytool = java.with_name("keytool")
    if not java.is_file() or not keytool.is_file():
        raise ValueError("A JDK with java and keytool is required")
    for tool in ("zipalign", "apksigner"):
        if not (build_tools / tool).is_file():
            raise ValueError("Missing Android build tool: " + tool)
    with ZipFile(source) as zipped:
        if zipped.namelist().count(LIBRARY) != 1 or MARKER in zipped.namelist():
            raise ValueError("Expected exactly one original FastAES library and no QA marker")
        original = zipped.read(LIBRARY)
        if emulator_no_store and zipped.namelist().count(IL2CPP) != 1:
            raise ValueError("Expected exactly one audited IL2CPP library for opt-in IAP QA")
        native = zipped.read(IL2CPP) if emulator_no_store else None
    patched, report = patch_library(original)
    report["verification"] = verify_vectors(original, patched)
    replacements = {LIBRARY: patched}
    if emulator_no_store:
        patched_native, iap_report = patch_initializer(native)
        iap_report["verification"] = verify_abi(native, patched_native)
        replacements[IL2CPP] = patched_native
        report["iap_qa"] = iap_report
    report["qa_adaptations"] = ["software AES dispatch"] + (["no-store managed initializer"] if emulator_no_store else [])
    report.update(source_apk_sha256=expected_source_sha256,
                  production_client_modified=False,
                  signature="ephemeral QA key; disposable emulator installation only")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="idoly-qa-aes-", dir=output.parent) as directory:
        stage = Path(directory)
        unsigned, aligned, signed = (stage / name for name in ("unsigned.apk", "aligned.apk", "signed.apk"))
        with ZipFile(source) as incoming, ZipFile(unsigned, "w", allowZip64=True) as outgoing:
            for item in incoming.infolist():
                if signature_member(item.filename):
                    continue
                if item.filename in replacements:
                    outgoing.writestr(item, replacements[item.filename])
                else:
                    with incoming.open(item) as src, outgoing.open(item, "w") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            outgoing.writestr(MARKER, json.dumps(report, indent=2))
        # SDK34 supports arbitrary alignment but predates the newer -P flag.
        # Align every stored member to 16 KiB, including uncompressed .so files.
        run([build_tools / "zipalign", "-f", "16384", unsigned, aligned])
        environment = os.environ.copy()
        environment["IDOLY_QA_AES_PASSWORD"] = secrets.token_urlsafe(32)
        key = stage / "ephemeral-qa.p12"
        run([keytool, "-genkeypair", "-keystore", key, "-storetype", "PKCS12", "-alias", "qa-only",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "30", "-dname", "CN=Idoly emulator software AES QA only",
             "-storepass:env", "IDOLY_QA_AES_PASSWORD", "-keypass:env", "IDOLY_QA_AES_PASSWORD"], environment)
        run([build_tools / "apksigner", "sign", "--ks", key, "--ks-key-alias", "qa-only",
             "--ks-pass", "env:IDOLY_QA_AES_PASSWORD", "--key-pass", "env:IDOLY_QA_AES_PASSWORD",
             "--out", signed, aligned], environment)
        report["signature_verification"] = run([build_tools / "apksigner", "verify", "--print-certs", signed]).strip()
        run([build_tools / "zipalign", "-c", "16384", signed])
        with ZipFile(source) as incoming, ZipFile(signed) as final:
            if final.testzip() is not None or any(final.read(name) != value for name, value in replacements.items()):
                raise ValueError("QA output ZIP or patched library verification failed")
            changed = []
            for item in final.infolist():
                if item.filename == MARKER or signature_member(item.filename):
                    continue
                if final.read(item) != incoming.read(item.filename):
                    changed.append(item.filename)
            if set(changed) != set(replacements):
                raise ValueError("Unexpected APK content changed outside the explicitly selected QA libraries")
        signed.rename(output)
    report.update(output_apk=str(output), output_apk_sha256=digest(output), output_bytes=output.stat().st_size,
                  changed_apk_members=[*replacements, MARKER])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--java")
    parser.add_argument("--emulator-no-store", action="store_true",
                        help="QA ONLY: return the genuine managed success result from the store initializer; no purchases/grants")
    parser.add_argument("--expected-source-sha256", default=SOURCE_SHA256,
                        help="Explicit checksum for a separately generated diagnostic input; defaults to pinned r2")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = package(args.source, args.output, args.build_tools,
                     expected_source_sha256=args.expected_source_sha256, java=args.java,
                     emulator_no_store=args.emulator_no_store)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded)
    print(encoded)


if __name__ == "__main__":
    main()
