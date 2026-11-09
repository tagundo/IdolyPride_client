#!/usr/bin/env python3
"""Build the small, synthetic-only phone report without changing game sources."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
COMMON_COMMIT = "c814de3b3a7f402813470effff06e002f2976f9d"
COMMON_HASHES = {
    "machine_state_check.cpp": "0fbf72e3980f645e620488f3687a9589ccacf0bc43fb046e088b4afd19da88e8",
    "machine_state_check.h": "1154dc013dc90efd374d9f906efa226e1a286e722bc0dd840a99045f7a57cf91",
    "checkpoint.S": "bf0e8efd9dfff7ed69effdddf3fa9a9379138831cd952dd2357697314ae804b7",
}
ORIGINAL_BUILDER_HASH = "00e220fcaa313cfe002a87e03591299dd3479e30f16f82049082d046a9a52f7a"
PUBLIC_KEY_HASH = "747c4254b69c72b1a93b52e7a1efad09a4de0440ea3f8fd7718c1a06bf9c8dfd"
CERTIFICATE_SHA256 = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
PACKAGE = "game.qualiarts.idolypride.phase_selftest"
ASSET_NAME = "IdolyPride-Native-SelfTest-Android-arm64.apk"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_common(directory):
    directory = Path(directory)
    for name, expected in COMMON_HASHES.items():
        if digest(directory / name) != expected:
            raise ValueError("The phone checker requires the exact published c814 common guard: " + name)


def pinned_file(relative, expected):
    result = subprocess.run(["git", "show", COMMON_COMMIT + ":" + relative], cwd=PROJECT, capture_output=True)
    if result.returncode or hashlib.sha256(result.stdout).hexdigest() != expected:
        raise ValueError("Pinned c814 source is unavailable or changed: " + relative)
    return result.stdout


def run(command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise ValueError("Phone checker build failed: " + result.stderr[-2200:])
    return result.stdout


def build(output, *, shadowhook_aar, ndk, build_tools, android_jar, javac):
    output = Path(output).resolve()
    evidence = output.with_suffix(".apk.evidence.json")
    sums = output.parent / "NativeSelfTest-SHA256SUMS"
    if output.name != ASSET_NAME or any(path.exists() for path in (output, evidence, sums)):
        raise ValueError("Choose a new output directory and the dedicated phone-check APK name")
    native = PROJECT / "android-diagnostics/native"
    common_sources = {name: pinned_file("android-diagnostics/native/" + name, sha)
                      for name, sha in COMMON_HASHES.items()}
    original_builder_bytes = pinned_file("android-diagnostics/native/selftest/build_apk.py", ORIGINAL_BUILDER_HASH)
    key = PROJECT / "android-diagnostics/local-diagnostics-development.keystore"
    if digest(key) != PUBLIC_KEY_HASH:
        raise ValueError("The intentionally public diagnostics development key did not match")
    tools, javac = Path(build_tools).resolve(), Path(javac).resolve()
    manifest = ET.parse(HERE / "AndroidManifest.xml").getroot()
    if manifest.get("package") != PACKAGE or manifest.findall("uses-permission"):
        raise ValueError("The synthetic phone checker must request no permissions")
    source_hashes = {path.name: digest(path) for path in
                     (HERE / "SelfTestActivity.java", HERE / "selftest.cpp", HERE / "AndroidManifest.xml", Path(__file__))}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".native-phone-check-", dir=output.parent) as temporary:
        work = Path(temporary)
        staged, fixture = work / "native", work / "native/selftest"
        fixture.mkdir(parents=True)
        for name, contents in common_sources.items():
            (staged / name).write_bytes(contents)
        verify_common(staged)
        for name in ("SelfTestActivity.java", "selftest.cpp", "AndroidManifest.xml"):
            shutil.copyfile(HERE / name, fixture / name)
        original_builder = work / "pinned_build_apk.py"
        original_builder.write_bytes(original_builder_bytes)
        spec = importlib.util.spec_from_file_location("pinned_native_selftest_builder", original_builder)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.HERE, module.COMMON = fixture, staged
        raw = work / "synthetic.apk"
        original_report = module.build(raw, shadowhook_aar=shadowhook_aar, ndk=ndk,
                                      build_tools=tools, android_jar=android_jar, javac=javac)
        verify_common(staged)
        provenance = {"schema": 1, "report_schema": 2, "synthetic_only": True,
            "game_included": False, "network_permission": False, "runtime_verified": False,
            "common_source_commit": COMMON_COMMIT, "common_source_sha256": COMMON_HASHES,
            "original_builder_sha256": ORIGINAL_BUILDER_HASH,
            "phone_checker_source_sha256": source_hashes,
            "shadowhook_aar_sha256": original_report["shadowhook_aar_sha256"]}
        additions = {
            "assets/native-phone-check-provenance.json": (json.dumps(provenance, indent=2) + "\n").encode(),
            "assets/licenses/ShadowHook-MIT.txt": (native / "SHADOWHOOK-LICENSE").read_bytes(),
            "assets/licenses/ShadowHook-third-party.txt": (native / "THIRD-PARTY-NOTICES.txt").read_bytes(),
        }
        cleaned, aligned, signed = (work / name for name in ("clean.apk", "aligned.apk", "signed.apk"))
        with ZipFile(raw) as source, ZipFile(cleaned, "w") as target:
            for entry in source.infolist():
                name = entry.filename.upper()
                if name == "META-INF/MANIFEST.MF" or (name.startswith("META-INF/") and name.endswith((".SF", ".RSA", ".DSA", ".EC"))):
                    continue
                target.writestr(entry, source.read(entry))
            for name, contents in additions.items():
                target.writestr(ZipInfo(name, (1980, 1, 1, 0, 0, 0)), contents, compress_type=ZIP_DEFLATED)
        run([tools / "zipalign", "-f", "16384", cleaned, aligned])
        run([tools / "apksigner", "sign", "--ks", key, "--ks-key-alias", "idoly-diagnostics-public",
             "--ks-pass", "pass:android", "--key-pass", "pass:android", "--out", signed, aligned])
        signature = run([tools / "apksigner", "verify", "--verbose", "--print-certs", signed])
        if "certificate SHA-256 digest: " + CERTIFICATE_SHA256 not in signature:
            raise ValueError("Phone checker was signed with an unexpected certificate")
        run([tools / "zipalign", "-c", "16384", signed])
        badging = run([tools / "aapt2", "dump", "badging", signed])
        if f"package: name='{PACKAGE}'" not in badging or "native-code: 'arm64-v8a'" not in badging or "uses-permission:" in badging:
            raise ValueError("Phone checker package, ABI or permission inventory differs")
        with ZipFile(signed) as archive:
            names = set(archive.namelist())
            expected = {"lib/arm64-v8a/" + name: sha for name, sha in original_report["native_sha256"].items()}
            for name, sha in expected.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                    raise ValueError("Signing changed a compiled synthetic library")
            if {name for name in names if name.endswith(".so")} != set(expected):
                raise ValueError("Phone checker contains unexpected native code")
            if any(name.startswith("assets/bin/") for name in names):
                raise ValueError("Phone checker must not contain game assets")
            for name, contents in additions.items():
                if archive.read(name) != contents:
                    raise ValueError("Phone checker attribution or provenance was not retained")
        if any(digest(HERE / name) != sha for name, sha in source_hashes.items()):
            raise ValueError("Phone checker sources changed during the build")
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, capture_output=True, text=True).stdout.strip()
        report = {**provenance, "builder_checkout_commit": revision,
            "output_bytes": signed.stat().st_size, "output_sha256": digest(signed),
            "package": PACKAGE, "version_code": 1, "stable_public_development_key": True,
            "certificate_sha256": CERTIFICATE_SHA256, "signature_verified": True,
            "alignment_bytes": 16384, "native_sha256": original_report["native_sha256"]}
        with output.open("xb") as outgoing, signed.open("rb") as incoming:
            shutil.copyfileobj(incoming, outgoing)
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        with sums.open("x", encoding="ascii") as stream:
            for path in (output, evidence):
                stream.write(digest(path) + "  " + path.name + "\n")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shadowhook-aar", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    parser.add_argument("--javac", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output, shadowhook_aar=args.shadowhook_aar, ndk=args.ndk,
                           build_tools=args.build_tools, android_jar=args.android_jar, javac=args.javac), indent=2))


if __name__ == "__main__":
    main()
