#!/usr/bin/env python3
"""Build a Java-only emulator probe using the unchanged production diagnostics.

This fixture has the diagnostics game's identity and must only be installed on
a disposable emulator. It contains no original game binaries or native code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent
DIAGNOSTICS = ROOT / "android-diagnostics"
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
PROVIDER = "game.qualiarts.idolypride.diagnostics.DiagnosticsProvider"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output, build_tools, android_jar, javac):
    output = Path(output).resolve()
    evidence = output.with_suffix(output.suffix + ".evidence.json")
    if output.suffix != ".apk" or output.exists() or evidence.exists():
        raise ValueError("Choose a new .apk output path")
    build_tools, android_jar, javac = Path(build_tools).resolve(), Path(android_jar).resolve(), Path(javac).resolve()
    production = sorted((DIAGNOSTICS / "src").rglob("*.java"))
    if [path.name for path in production] != ["DiagnosticsProvider.java", "LogSanitizer.java"]:
        raise ValueError("Unexpected production diagnostic Java source inventory")
    sources = [*production, FIXTURE / "ProbeActivity.java"]
    manifest = FIXTURE / "AndroidManifest.xml"
    key = DIAGNOSTICS / "local-diagnostics-development.keystore"
    for path in [javac, android_jar, key, manifest, *sources,
                 *(build_tools / tool for tool in ("aapt2", "d8", "zipalign", "apksigner"))]:
        if not path.is_file():
            raise ValueError("Required probe build tool or source is missing: " + str(path))
    original_hashes = {str(path.relative_to(ROOT)): digest(path) for path in [*sources, manifest]}
    output.parent.mkdir(parents=True, exist_ok=True)
    logs = []

    def run(arguments):
        process = subprocess.run([str(arg) for arg in arguments], capture_output=True, text=True, timeout=180)
        logs.append(process.stdout + process.stderr)
        if process.returncode:
            raise RuntimeError(Path(str(arguments[0])).name + " failed: " + process.stderr[-3000:])
        return process.stdout

    with tempfile.TemporaryDirectory(prefix=".diagnostic-probe-", dir=output.parent) as temporary:
        work = Path(temporary)
        classes, dex = work / "classes", work / "dex"
        classes.mkdir()
        dex.mkdir()
        run([javac, "--release", "8", "-encoding", "UTF-8", "-classpath", android_jar,
             "-d", classes, *sources])
        run([build_tools / "d8", "--release", "--min-api", "28", "--lib", android_jar,
             "--output", dex, *sorted(classes.rglob("*.class"))])
        if sorted(path.name for path in dex.iterdir()) != ["classes.dex"]:
            raise ValueError("Probe must compile into one DEX")
        unsigned, aligned, signed = (work / name for name in ("unsigned.apk", "aligned.apk", "signed.apk"))
        run([build_tools / "aapt2", "link", "-o", unsigned, "--manifest", manifest,
             "-I", android_jar, "--min-sdk-version", "28", "--target-sdk-version", "34",
             "--version-code", "1", "--version-name", "1.0"])
        with ZipFile(unsigned, "a", compression=ZIP_DEFLATED) as archive:
            archive.write(dex / "classes.dex", "classes.dex")
        # No native libraries: standard 4-byte ZIP alignment works on SDK 34.
        run([build_tools / "zipalign", "-f", "4", unsigned, aligned])
        run([build_tools / "apksigner", "sign", "--ks", key, "--ks-key-alias", "idoly-diagnostics-public",
             "--ks-pass", "pass:android", "--out", signed, aligned])
        signature = run([build_tools / "apksigner", "verify", "--verbose", "--print-certs", signed])
        run([build_tools / "zipalign", "-c", "4", signed])
        badging = run([build_tools / "aapt2", "dump", "badging", signed])
        xml = run([build_tools / "aapt2", "dump", "xmltree", signed, "--file", "AndroidManifest.xml"])
        if "package: name='" + PACKAGE + "'" not in badging or PROVIDER not in xml or PACKAGE + ".bootstrap" not in xml:
            raise ValueError("Probe package or production provider did not survive packaging")
        with ZipFile(signed) as archive:
            names = archive.namelist()
            if archive.testzip() is not None or "classes.dex" not in names or any(name.startswith("lib/") for name in names):
                raise ValueError("Invalid probe APK or unexpected native libraries")
        if any(digest(ROOT / name) != sha for name, sha in original_hashes.items()):
            raise ValueError("Probe source changed while building")
        report = {"schema": 1, "package": PACKAGE, "probe_only": True, "original_game_included": False,
                  "native_libraries": [], "production_sources_unchanged": True,
                  "source_sha256": original_hashes, "output_sha256": digest(signed),
                  "output_bytes": signed.stat().st_size,
                  "signer": [line for line in signature.splitlines() if "certificate SHA-256 digest:" in line]}
        with output.open("xb") as target, signed.open("rb") as source:
            shutil.copyfileobj(source, target)
        evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        output.with_suffix(output.suffix + ".build.log").write_text("\n".join(logs), encoding="utf-8")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    parser.add_argument("--javac", type=Path)
    args = parser.parse_args()
    javac = args.javac or shutil.which("javac") or Path(os.environ.get("JAVA_HOME", "/nonexistent")) / "bin/javac"
    print(json.dumps(build(args.output, args.build_tools, args.android_jar, javac), indent=2))


if __name__ == "__main__":
    main()
