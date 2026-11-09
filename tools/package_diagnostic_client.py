#!/usr/bin/env python3
"""Build a separate 6.1.1 game with an own-PID, redacted loopback log bridge."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from idoly_local.android_package import (
    ANDROID, LIBRARY_NAME, METADATA_NAME, AndroidPackagingError, _hash, _run,
    _tools, package_android, strip_apk_signatures,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
PROVIDER = "game.qualiarts.idolypride.diagnostics.DiagnosticsProvider"
IDENTITY = "idoly-diagnostics-public"
SOURCES = ROOT / "android-diagnostics"
DEX_NAME = re.compile(r"classes(?P<index>[2-9][0-9]*|1[0-9]+)?\.dex")


def add_provider(decoded: Path) -> str:
    path = decoded / "AndroidManifest.xml"
    manifest = ET.parse(path)
    root = manifest.getroot()
    if root.get("package") != PACKAGE:
        raise AndroidPackagingError("Diagnostics requires its separate, fixed package identity")
    application = root.find("application")
    if application is None or any(item.get(ANDROID + "name") == PROVIDER for item in application):
        raise AndroidPackagingError("Diagnostics manifest is missing its application or already contains the provider")
    ET.SubElement(application, "provider", {
        ANDROID + "name": PROVIDER,
        ANDROID + "authorities": PACKAGE + ".bootstrap",
        ANDROID + "exported": "false",
        ANDROID + "initOrder": "1",
    })
    manifest.write(path, encoding="utf-8", xml_declaration=True)
    dexes = [item for item in (decoded / "dex").iterdir() if DEX_NAME.fullmatch(item.name)]
    if not dexes or not any(item.name == "classes.dex" for item in dexes):
        raise AndroidPackagingError("Decoded client has no preserved primary DEX")
    highest = max(int(DEX_NAME.fullmatch(item.name).group("index") or 1) for item in dexes)
    return f"classes{highest + 1}.dex"


def compile_dex(work: Path, java: str, sdk: Path, android_jar: Path) -> Path:
    javac = Path(java).resolve().with_name("javac")
    if not javac.is_file() or not android_jar.is_file() or not (sdk / "d8").is_file():
        raise AndroidPackagingError("Diagnostics requires javac, SDK d8, and an Android platform android.jar")
    classes, output = work / "diagnostic-classes", work / "diagnostic-dex"
    classes.mkdir()
    output.mkdir()
    sources = sorted((SOURCES / "src").rglob("*.java"))
    if {path.name for path in sources} != {"DiagnosticsProvider.java", "LogSanitizer.java", "NativePhaseProbe.java", "TrafficSampler.java"}:
        raise AndroidPackagingError("Diagnostics Java source inventory did not match")
    _run([javac, "--release", "8", "-encoding", "UTF-8", "-classpath", android_jar,
          "-d", classes, *sources], "Diagnostics Java compilation")
    _run([sdk / "d8", "--release", "--min-api", "28", "--lib", android_jar,
          "--output", output, *sorted(classes.rglob("*.class"))], "Diagnostics DEX compilation")
    if sorted(item.name for item in output.iterdir()) != ["classes.dex"]:
        raise AndroidPackagingError("Diagnostics must compile into exactly one added DEX")
    return output / "classes.dex"


def package(source: Path, output: Path, *, apkeditor=None, build_tools=None, java=None, android_jar=None, ndk=None):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    evidence = output.with_suffix(output.suffix + ".evidence.json")
    if output.exists() or evidence.exists() or output.suffix != ".apk":
        raise AndroidPackagingError("Choose a new .apk output; existing clients are preserved")
    editor, sdk, java = _tools(apkeditor, build_tools, java)
    platform = Path(android_jar) if android_jar else sdk.parent.parent / "platforms/android-34/android.jar"
    key = SOURCES / "local-diagnostics-development.keystore"
    if not key.is_file():
        raise AndroidPackagingError("The intentionally public diagnostics development key is missing")
    environment = dict(os.environ, IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD="android")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".diagnostic-client-", dir=output.parent) as temporary:
        work = Path(temporary)
        spec = importlib.util.spec_from_file_location("idoly_diagnostic_native", SOURCES / "native/build_native.py")
        native_builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native_builder)
        native_output = work / "native"
        native_report = native_builder.build_native(native_output, ndk=ndk)
        dex = compile_dex(work, java, sdk, platform)
        base = work / "separate-local-client.apk"
        # Reuse the existing audited clone/native/metadata pipeline, then add
        # diagnostics only to this new identity. No installed app is rewritten.
        original_env = os.environ.get("IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD")
        os.environ["IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD"] = "android"
        try:
            report = package_android(source, base, package=PACKAGE, label="아이프라 진단",
                apkeditor=editor, build_tools=sdk, java=java, keystore=key, alias=IDENTITY,
                storepass_env="IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD")
        finally:
            if original_env is None: os.environ.pop("IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD", None)
            else: os.environ["IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD"] = original_env
        with ZipFile(base) as archive:
            dex_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest()
                          for name in archive.namelist() if DEX_NAME.fullmatch(name)}
            native_hashes = {name: hashlib.sha256(archive.read(name)).hexdigest()
                             for name in archive.namelist() if name == METADATA_NAME or name.endswith(".so")}
            profile = json.loads((SOURCES / "native/phase-profile.json").read_text())
            if native_hashes[LIBRARY_NAME] != profile["local_bootstrap_native_sha256"]:
                raise AndroidPackagingError("Native diagnostics requires the pinned 6.1.1 offline bootstrap library")
        decoded = work / "decoded"
        _run([java, "-jar", editor, "d", "-dex", "-t", "xml", "-i", base, "-o", decoded], "Diagnostics APK decode")
        added_name = add_provider(decoded)
        shutil.copyfile(dex, decoded / "dex" / added_name)
        added_libraries = {}
        for library in sorted((native_output / "lib/arm64-v8a").glob("*.so")):
            relative = "lib/arm64-v8a/" + library.name
            if relative in native_hashes:
                raise AndroidPackagingError("A native diagnostic library collides with an original game library")
            target = decoded / "root" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(library, target)
            added_libraries[relative] = _hash(library)
        license_path = decoded / "root/assets/idoly-diagnostics-licenses/ShadowHook-MIT.txt"
        license_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCES / "native/SHADOWHOOK-LICENSE", license_path)
        shutil.copyfile(SOURCES / "native/THIRD-PARTY-NOTICES.txt", license_path.with_name("ShadowHook-third-party.txt"))
        provenance_path = decoded / "root/assets/idoly-diagnostics-native.json"
        provenance_path.write_text(json.dumps({"schema": 1, "native": native_report, "profile": profile}, indent=2) + "\n")
        added_assets = {str(path.relative_to(decoded / "root")): _hash(path)
                        for path in (license_path, license_path.with_name("ShadowHook-third-party.txt"), provenance_path)}
        unsigned, cleaned, aligned, signed = (work / name for name in ("rebuilt.apk", "clean.apk", "aligned.apk", "signed.apk"))
        _run([java, "-jar", editor, "b", "-i", decoded, "-o", unsigned], "Diagnostics APK rebuild")
        strip_apk_signatures(unsigned, cleaned)
        _run([sdk / "zipalign", "-f", "16384", cleaned, aligned], "Diagnostics alignment")
        _run([sdk / "apksigner", "sign", "--ks", key, "--ks-key-alias", IDENTITY,
              "--ks-pass", "env:IDOLY_DIAGNOSTIC_PUBLIC_PASSWORD", "--out", signed, aligned], "Diagnostics signing", environment)
        signature = _run([sdk / "apksigner", "verify", "--verbose", "--print-certs", signed], "Diagnostics signature verification")
        _run([sdk / "zipalign", "-c", "16384", signed], "Diagnostics alignment verification")
        badging = _run([sdk / "aapt2", "dump", "badging", signed], "Diagnostics package verification").stdout
        xml = _run([sdk / "aapt2", "dump", "xmltree", signed, "--file", "AndroidManifest.xml"], "Diagnostics provider verification").stdout
        if f"package: name='{PACKAGE}'" not in badging or PROVIDER not in xml or PACKAGE + ".bootstrap" not in xml:
            raise AndroidPackagingError("Diagnostic APK identity or provider did not survive rebuilding")
        with ZipFile(signed) as archive:
            if {name for name in archive.namelist() if DEX_NAME.fullmatch(name)} != set(dex_hashes) | {added_name}:
                raise AndroidPackagingError("Diagnostics changed the original DEX inventory")
            for name, expected in {**dex_hashes, **native_hashes, **added_libraries, **added_assets, added_name: _hash(dex)}.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise AndroidPackagingError("Diagnostics did not preserve an original executable or added DEX")
        if _hash(source) != report["input_sha256"]:
            raise AndroidPackagingError("Original source changed while building diagnostics")
        report.update(output_sha256=_hash(signed), output_bytes=signed.stat().st_size,
            diagnostics={"schema": 1, "provider": PROVIDER, "exported": False,
                "added_dex": added_name, "original_dex_sha256": dex_hashes,
                "endpoint": "http://127.0.0.1:8080/diagnostics/client", "own_pid_only": True,
                "raw_logs_saved": False, "session_minutes": 30,
                "public_development_signing_key": True,
                "native_phase_probe": native_report,
                "native_attribution_assets_sha256": added_assets,
                "source_sha256": {str(p.relative_to(ROOT)): _hash(p) for p in sorted((SOURCES / "src").rglob("*.java"))}},
            signer=[line for line in signature.stdout.splitlines() if "certificate SHA-256 digest:" in line])
        with output.open("xb") as destination, signed.open("rb") as incoming:
            shutil.copyfileobj(incoming, destination, 1024 * 1024)
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apkeditor", type=Path)
    parser.add_argument("--build-tools", type=Path)
    parser.add_argument("--java")
    parser.add_argument("--android-jar", type=Path)
    parser.add_argument("--ndk", type=Path, help="Linux Android NDK 26.3.11579264 for the ARM64 phase probe")
    args = parser.parse_args(argv)
    try:
        report = package(args.source, args.output, apkeditor=args.apkeditor, build_tools=args.build_tools,
                         java=args.java, android_jar=args.android_jar, ndk=args.ndk)
    except (AndroidPackagingError, OSError, ValueError) as error:
        parser.exit(1, f"Diagnostics packaging failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
