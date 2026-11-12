#!/usr/bin/env python3
"""Build a small same-certificate feature split, never rebuild the game APK.

Installation requires PackageInstaller MODE_INHERIT_EXISTING. Opening this APK
as a standalone app is not supported. Existing game files are read, never edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import shutil
import struct
import subprocess
import tempfile
import time
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPLIT = "idoly_presentation"
VERSION_CODE = 414
LIBRARY = "lib/arm64-v8a/libidoly_presentation.so"
MARKER = "assets/idoly-presentation.json"
BOOTSTRAP = "lib/arm64-v8a/libil2cpp.so"
BOOTSTRAP_SHA256 = "4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3"
MAX_ADDON = 1024 * 1024
SHADOW_AAR_SHA256 = "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"
SHADOW_HASHES = {
    "lib/arm64-v8a/libshadowhook.so": "fc84287eac46e3bade2f7e07e3c9efdca005822e21191d6db5b8cb222d53e8a0",
    "lib/arm64-v8a/libshadowhook_nothing.so": "f2cc6a6f94d7361be915daafff1d25b7b3af34972e7308ac540982cfd608bd32",
}
PROFILES = {
    "diagnostics": {"package": "game.qualiarts.idolypride.local.diagnostics",
        "certificate": "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc",
        "alias": "idoly-diagnostics-public", "bundle_shadowhook": False},
    "resources": {"package": "game.qualiarts.idolypride.local.resources",
        "certificate": "3c56abcfd37697c4a1436849391a2002793df18082d2843130a7e99292a5bd6c",
        "alias": "idoly-local", "bundle_shadowhook": True},
}
JAVA_FLAGS = ("-Xmx128m", "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=32m",
              "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1")
# JDK 21 otherwise emits unnamed synthetic MethodParameters which cached D8
# 8.2.2 cannot read. Preserve names; do not rewrite runtime executor behavior.
JAVAC_ARGUMENTS = ("--release", "8", "-parameters", "-encoding", "UTF-8")
LICENSE_PREFIX = "assets/idoly-presentation-licenses/"
RUNTIME_NOTICE = "NDK-RUNTIME-NOTICES.txt"
LICENSE_HASHES = {
    RUNTIME_NOTICE: "3372aab78c50872abbb69c9b3929e08a40e5fe911b43618e5405170b63ae72b1",
    "SHADOWHOOK-LICENSE": "63204388d1ac7b371e03223fb4910a04fdb41cd67d4f0e0a030d5249d811d7eb",
    "THIRD-PARTY-NOTICES.txt": "114b489514680bf58611ac6ce36877fea7fc9927ed0c51f630928a6c07a02b95",
}


def license_hashes(profile):
    if profile not in PROFILES: raise ValueError("Unsupported feature profile")
    return {LICENSE_PREFIX + name: value for name, value in LICENSE_HASHES.items()
            if name == RUNTIME_NOTICE or PROFILES[profile]["bundle_shadowhook"]}


def license_members(profile):
    result = {}
    for member, expected in license_hashes(profile).items():
        name = member.removeprefix(LICENSE_PREFIX)
        source = HERE / "licenses" / name if name == RUNTIME_NOTICE else ROOT / "android-diagnostics/native" / name
        raw = source.read_bytes()
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("A pinned presentation dependency notice differs")
        result[member] = raw
    return result


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def member_hash(archive, name):
    entries = [info for info in archive.infolist() if info.filename == name]
    if len(entries) != 1 or entries[0].is_dir() or not 0 < entries[0].file_size <= 180 * 1024 * 1024:
        raise ValueError("A required base native library is missing or ambiguous")
    with archive.open(entries[0]) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_elf(path):
    path = Path(path)
    if not 64 <= path.stat().st_size <= MAX_ADDON:
        raise ValueError("Presentation library must be a bounded ARM64 ELF")
    raw = path.read_bytes()
    if (len(raw) > MAX_ADDON or len(raw) < 64 or raw[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", raw, 18)[0] != 183):
        raise ValueError("Presentation library must be a bounded ARM64 ELF")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    width, count = struct.unpack_from("<HH", raw, 54)
    if width != 56 or not 0 < count < 128 or offset + width * count > len(raw):
        raise ValueError("Invalid presentation ELF program table")
    loads = []
    for at in range(count):
        kind, _flags, file, address, _physical, size, _memory, align = struct.unpack_from("<II6Q", raw, offset + at * width)
        if kind == 1:
            if align < 16384 or file % 16384 != address % 16384 or file + size > len(raw):
                raise ValueError("Presentation ELF requires 16 KiB load alignment")
            loads.append(align)
    if not loads:
        raise ValueError("Presentation ELF has no load segments")
    return loads


def manifest(profile):
    if profile not in PROFILES:
        raise ValueError("Choose a supported existing game profile")
    raw = (HERE / "AndroidManifest.template").read_text(encoding="utf-8")
    if raw.count("@PACKAGE@") != 2:
        raise ValueError("Feature manifest template differs")
    return raw.replace("@PACKAGE@", PROFILES[profile]["package"])


def _run(command, env, *, timeout=45):
    start = time.monotonic()
    process = subprocess.Popen(["/usr/bin/nice", "-n", "19", *map(str, command)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    blocks, size, deadline = [], 0, start + timeout
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("Offline feature tool timed out; output withheld")
                block = os.read(process.stdout.fileno(), min(65536, 1024 * 1024 + 1 - size))
                if not block: break
                blocks.append(block); size += len(block)
                if size > 1024 * 1024: raise ValueError("Offline feature tool output exceeded its bound")
        if process.wait(timeout=max(.01, deadline - time.monotonic())):
            raise ValueError("Offline feature tool failed; tool output withheld")
        return b"".join(blocks).decode("utf-8"), round(time.monotonic() - start, 3)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL); process.wait()
        process.stdout.close()


def signature(signer, path, certificate, env, *, existing_base=False):
    output, _ = _run([*signer, "verify", "--verbose", "--print-certs", path], env)
    found = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$", output, re.M)
    v2 = "Verified using v2 scheme (APK Signature Scheme v2): true" in output
    v3 = "Verified using v3 scheme (APK Signature Scheme v3): true" in output
    if found != [certificate] or not (v2 or existing_base and v3):
        raise ValueError("Feature/base signing certificate does not match the supported profile")
    return output


def required_base_members(profile):
    if profile not in PROFILES: raise ValueError("Unsupported feature profile")
    return {BOOTSTRAP: BOOTSTRAP_SHA256, **(SHADOW_HASHES if profile == "diagnostics" else {})}


def validate_bundle_manifest(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "bridge_version", "split_id", "profiles"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or type(value["bridge_version"]) is not int or value["bridge_version"] != 1
            or value["split_id"] != SPLIT or not isinstance(value["profiles"], list)
            or not 1 <= len(value["profiles"]) <= 2):
        raise ValueError("Invalid presentation bundle manifest")
    seen = set()
    for row in value["profiles"]:
        if (not isinstance(row, dict) or set(row) != {"id", "target_package", "base_version_code", "certificate_sha256",
                "asset", "apk_sha256", "apk_bytes", "required_base_members"}
                or not isinstance(row["id"], str) or row["id"] not in PROFILES or row["id"] in seen):
            raise ValueError("Invalid or duplicate presentation profile")
        name = row["id"]; expected = PROFILES[name]; seen.add(name)
        if (row["target_package"] != expected["package"] or type(row["base_version_code"]) is not int
                or row["base_version_code"] != VERSION_CODE or row["certificate_sha256"] != expected["certificate"]
                or row["asset"] != "presentation/" + name + ".apk"
                or not isinstance(row["apk_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["apk_sha256"])
                or type(row["apk_bytes"]) is not int or not 0 < row["apk_bytes"] <= MAX_ADDON
                or row["required_base_members"] != required_base_members(name)):
            raise ValueError("Presentation profile identity, asset or base requirements differ")
    return value


def bundle_manifest(reports):
    """Only fixed profile names/assets and measured signed output enter the server."""
    if not 1 <= len(reports) <= 2:
        raise ValueError("Expected one or two supported signed feature profiles")
    profiles, seen = [], set()
    for report in reports:
        name = report.get("profile")
        if name not in PROFILES or name in seen:
            raise ValueError("Unsupported or duplicate feature profile")
        expected = PROFILES[name]
        if (report.get("target_package") != expected["package"] or report.get("base_version_code") != VERSION_CODE
                or report.get("certificate_sha256") != expected["certificate"] or report.get("split_id") != SPLIT
                or report.get("signature_and_alignment_verified") is not True
                or type(report.get("addon_bytes")) is not int or not 0 < report["addon_bytes"] <= MAX_ADDON
                or not re.fullmatch(r"[0-9a-f]{64}", report.get("addon_apk_sha256", ""))):
            raise ValueError("Feature provenance differs from the fixed bundle contract")
        seen.add(name)
        profiles.append({"id": name, "target_package": expected["package"], "base_version_code": VERSION_CODE,
            "certificate_sha256": expected["certificate"], "asset": "presentation/" + name + ".apk",
            "apk_sha256": report["addon_apk_sha256"], "apk_bytes": report["addon_bytes"],
            "required_base_members": report["required_base_members"]})
    return validate_bundle_manifest({"schema": 1, "bridge_version": 1, "split_id": SPLIT,
            "profiles": sorted(profiles, key=lambda row: row["id"])})


def shadow_libraries(aar):
    if digest(aar) != SHADOW_AAR_SHA256:
        raise ValueError("The pinned public ShadowHook 2.0.1 AAR differs")
    with ZipFile(aar) as archive:
        return {"lib/arm64-v8a/" + name: archive.read("jni/arm64-v8a/" + name)
                for name in ("libshadowhook.so", "libshadowhook_nothing.so")}


def check_base_members(archive, profile):
    if profile not in PROFILES: raise ValueError("Unsupported feature profile")
    if any(member_hash(archive, name) != value for name, value in required_base_members(profile).items()):
        raise ValueError("Existing base native version or ShadowHook dependency is unsupported")
    names = set(archive.namelist())
    if LIBRARY in names or PROFILES[profile]["bundle_shadowhook"] and names.intersection(SHADOW_HASHES):
        raise ValueError("Base already contains a conflicting presentation or ShadowHook library")


def build(args):
    os.umask(0o077)
    profile = PROFILES[args.profile]
    base, library, output = Path(args.base_apk), Path(args.native_library), Path(args.output)
    receipt = output.with_suffix(".provenance.json")
    if output.exists() or receipt.exists() or output.suffix != ".apk" or output.resolve() in (base.resolve(), library.resolve()):
        raise ValueError("Choose unused addon APK/provenance paths")
    if not base.is_file() or base.is_symlink() or not library.is_file() or library.is_symlink():
        raise ValueError("Expected stable regular public build inputs")
    source_hash = digest(base)
    native_hash = digest(library)
    alignment = check_elf(library)
    jdk, sdk, android = Path(args.jdk_bin), Path(args.build_tools), Path(args.android_jar)
    signer = [jdk / "java", *JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS", "GRADLE_OPTS"):
        env.pop(name, None)
    signature(signer, base, profile["certificate"], env, existing_base=True)
    badging, _ = _run([sdk / "aapt2", "dump", "badging", base], env)
    if ("package: name='" + profile["package"] + "'" not in badging or "versionCode='414'" not in badging
            or "versionName='6.1.1'" not in badging or "native-code: 'arm64-v8a'" not in badging):
        raise ValueError("Existing game identity/version/ABI is unsupported")
    dependencies = shadow_libraries(Path(args.shadowhook_aar))
    if {name: hashlib.sha256(raw).hexdigest() for name, raw in dependencies.items()} != SHADOW_HASHES:
        raise ValueError("ShadowHook native members differ from the audited dependency")
    required = required_base_members(args.profile)
    with ZipFile(base) as archive:
        check_base_members(archive, args.profile)
    dynamic, _ = _run([Path(args.readelf), "-d", library], env)
    needed = re.findall(r"Shared library: \[([^\]]+)\]", dynamic)
    if "libshadowhook.so" not in needed or set(needed) - {"libshadowhook.so", "libc.so", "libdl.so", "libm.so", "liblog.so"}:
        raise ValueError("Presentation native dependencies differ from the bounded bridge contract")
    symbols, _ = _run([Path(args.readelf), "--dyn-syms", "--wide", library], env)
    if any("Java_game_qualiarts_idolypride_presentation_NativePresentation_" + name not in symbols
           for name in ("start", "configure", "status")):
        raise ValueError("Presentation JNI exports do not match Java")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".presentation-addon-", dir=output.parent) as temporary:
        work = Path(temporary)
        source = HERE / "java"
        java_sources = sorted(source.rglob("*.java"))
        if {path.name for path in java_sources} != {"PresentationProvider.java", "PresentationClient.java", "NativePresentation.java"}:
            raise ValueError("Presentation Java source inventory differs")
        (work / "AndroidManifest.xml").write_text(manifest(args.profile), encoding="utf-8")
        (work / "classes").mkdir(); (work / "dex").mkdir()
        _run([sdk / "aapt2", "link", "--manifest", work / "AndroidManifest.xml", "-I", android,
              "-o", work / "manifest.apk"], env)
        _run([jdk / "javac", *["-J" + flag for flag in JAVA_FLAGS], *JAVAC_ARGUMENTS, "-classpath", android,
              "-d", work / "classes", *java_sources], env)
        _run([jdk / "java", *JAVA_FLAGS, "-cp", sdk / "lib/d8.jar", "com.android.tools.r8.D8", "--release",
              "--min-api", "28", "--lib", android, "--output", work / "dex", *sorted((work / "classes").rglob("*.class"))], env)
        if sorted(path.name for path in (work / "dex").iterdir()) != ["classes.dex"]:
            raise ValueError("Feature must contain exactly one new own DEX")
        marker = {"schema": 1, "bridge_version": 1, "profile": args.profile,
                  "target_package": profile["package"], "split_id": SPLIT,
                  "base_version_code": VERSION_CODE, "certificate_sha256": profile["certificate"],
                  "required_base_members": required, "native_library_sha256": native_hash,
                  "configuration_origin": "http://127.0.0.1:8080", "installation_mode": "MODE_INHERIT_EXISTING"}
        members = {"classes.dex": (work / "dex/classes.dex").read_bytes(), LIBRARY: library.read_bytes(),
                   MARKER: (json.dumps(marker, sort_keys=True, indent=2) + "\n").encode()}
        members.update(license_members(args.profile))
        if profile["bundle_shadowhook"]:
            members.update(dependencies)
        with ZipFile(work / "manifest.apk") as archive:
            members["AndroidManifest.xml"] = archive.read("AndroidManifest.xml")
        unsigned, signed = work / "unsigned.apk", work / "signed.apk"
        with ZipFile(unsigned, "x") as archive:
            for name, raw in members.items():
                info = ZipInfo(name); info.compress_type = ZIP_STORED if name.endswith(".so") else ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        _run([sdk / "zipalign", "-f", "16384", unsigned, signed], env)
        unsigned.unlink()
        key = Path(args.keystore)
        if not key.is_file() or key.is_symlink(): raise ValueError("Existing matching signing key is required")
        password = Path(args.password_file)
        if not password.is_file() or password.is_symlink() or password.stat().st_mode & 0o077:
            raise ValueError("Existing private password file is required; no signing key is generated")
        _run([*signer, "sign", "--ks", key, "--ks-key-alias", profile["alias"], "--ks-pass", "file:" + str(password),
              "--min-sdk-version", "28", "--v1-signing-enabled", "false", "--v2-signing-enabled", "true",
              "--v3-signing-enabled", "false", "--v4-signing-enabled", "false", signed], env)
        signature(signer, signed, profile["certificate"], env)
        _run([sdk / "zipalign", "-c", "16384", signed], env)
        feature_badging, _ = _run([sdk / "aapt2", "dump", "badging", signed], env)
        tree, _ = _run([sdk / "aapt2", "dump", "xmltree", "--file", "AndroidManifest.xml", signed], env)
        if ("split='" + SPLIT + "'" not in feature_badging or "versionCode='414'" not in feature_badging
                or "name='" + profile["package"] + "'" not in feature_badging
                or "sdkVersion:'28'" not in feature_badging or "targetSdkVersion:'34'" not in feature_badging
                or not re.search(r":isFeatureSplit\([^)]*\)=true\b", tree)
                or not re.search(r":hasCode\([^)]*\)=true\b", tree) or "PresentationProvider" not in tree
                or not re.search(r":exported\([^)]*\)=false\b", tree)
                or re.search(r":exported[^\n]*=true", tree)):
            raise ValueError("Built feature identity/provider metadata differs")
        with ZipFile(signed) as archive:
            actual = {info.filename: member_hash(archive, info.filename) for info in archive.infolist()}
        if actual != {name: hashlib.sha256(raw).hexdigest() for name, raw in members.items()} or signed.stat().st_size > MAX_ADDON:
            raise ValueError("Feature APK members changed or exceed the 1 MiB bound")
        if digest(base) != source_hash or digest(library) != native_hash:
            raise ValueError("An existing build input changed")
        report = {**marker, "base_apk_sha256": source_hash, "addon_apk_sha256": digest(signed), "addon_bytes": signed.stat().st_size,
                  "member_sha256": actual, "native_load_alignments": alignment,
                  "source_sha256": {str(path.relative_to(HERE)): digest(path) for path in [*java_sources, HERE / "AndroidManifest.template", Path(__file__)]},
                  "base_unchanged": True, "signature_and_alignment_verified": True, "installed": False,
                  "seconds": round(time.monotonic() - started, 3),
                  "child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
        staged = work / "provenance.json"; staged.write_text(json.dumps(report, indent=2) + "\n")
        os.link(staged, receipt)
        try: os.link(signed, output)
        except BaseException: receipt.unlink(); raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    for name in ("base-apk", "native-library", "output", "jdk-bin", "build-tools", "android-jar",
                 "shadowhook-aar", "readelf", "keystore", "password-file"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try: result = build(args)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit("Feature build failed; existing inputs preserved and tool output withheld") from None
    print(json.dumps({key: result[key] for key in ("target_package", "addon_apk_sha256", "addon_bytes", "certificate_sha256")}, indent=2))


if __name__ == "__main__": main()
