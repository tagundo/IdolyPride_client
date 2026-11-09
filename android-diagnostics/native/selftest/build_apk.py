#!/usr/bin/env python3
"""Build a synthetic-only ARM64 instruction interceptor fixture without Gradle."""
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


HERE = Path(__file__).resolve().parent
PACKAGE = "game.qualiarts.idolypride.phase_selftest"
AAR_SHA256 = "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output, *, shadowhook_aar, ndk, build_tools, android_jar, javac):
    output = Path(output).resolve()
    if output.suffix != ".apk" or output.exists() or output.with_suffix(".apk.evidence.json").exists():
        raise ValueError("Choose a new self-test .apk output")
    aar, ndk, tools, android_jar, javac = map(lambda value: Path(value).resolve(),
                                            (shadowhook_aar, ndk, build_tools, android_jar, javac))
    if digest(aar) != AAR_SHA256:
        raise ValueError("Self-test requires the pinned ShadowHook 2.0.1 AAR")
    if "Pkg.Revision = 26.3.11579264" not in (ndk / "source.properties").read_text():
        raise ValueError("Self-test requires Android NDK 26.3.11579264")
    hosts = sorted((ndk / "toolchains/llvm/prebuilt").glob("*"))
    if len(hosts) != 1:
        raise ValueError("Expected one NDK host toolchain")
    clang = hosts[0] / "bin/aarch64-linux-android28-clang++"
    keytool = javac.with_name("keytool")
    sources = [HERE / name for name in ("SelfTestActivity.java", "selftest.cpp", "checkpoint.S", "AndroidManifest.xml")]
    for path in [javac, keytool, clang, android_jar, *sources,
                 *(tools / name for name in ("aapt2", "d8", "zipalign", "apksigner"))]:
        if not path.is_file():
            raise ValueError("Missing self-test source or tool: " + str(path))
    output.parent.mkdir(parents=True, exist_ok=True)
    source_hashes = {path.name: digest(path) for path in sources}
    logs = []

    def run(arguments):
        result = subprocess.run([str(value) for value in arguments], capture_output=True, text=True, timeout=180)
        logs.append(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(Path(str(arguments[0])).name + " failed: " + result.stderr[-2500:])
        return result.stdout

    with tempfile.TemporaryDirectory(prefix=".arm64-selftest-", dir=output.parent) as temporary:
        work = Path(temporary)
        include, libraries = work / "include", work / "lib/arm64-v8a"
        include.mkdir()
        libraries.mkdir(parents=True)
        with ZipFile(aar) as archive:
            (include / "shadowhook.h").write_bytes(archive.read("prefab/modules/shadowhook/include/shadowhook.h"))
            for name in ("libshadowhook.so", "libshadowhook_nothing.so"):
                (libraries / name).write_bytes(archive.read("jni/arm64-v8a/" + name))
        native = libraries / "libidoly_phase_selftest.so"
        run([clang, "-shared", "-fPIC", "-O2", "-std=c++17", "-fno-exceptions", "-fno-rtti",
             "-fvisibility=hidden", "-nostdlib++", "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384",
             "-Wl,-z,common-page-size=16384", "-I" + str(include), HERE / "selftest.cpp", HERE / "checkpoint.S",
             "-L" + str(libraries), "-lshadowhook", "-o", native])
        dynamic = run([hosts[0] / "bin/llvm-readelf", "-d", native])
        if "libc++_shared" in dynamic or "libshadowhook.so" not in dynamic:
            raise ValueError("Unexpected self-test native dependencies")
        classes, dex = work / "classes", work / "dex"
        classes.mkdir()
        dex.mkdir()
        run([javac, "--release", "8", "-encoding", "UTF-8", "-classpath", android_jar,
             "-d", classes, HERE / "SelfTestActivity.java"])
        run([tools / "d8", "--release", "--min-api", "28", "--lib", android_jar, "--output", dex,
             *sorted(classes.rglob("*.class"))])
        unsigned, aligned, signed = (work / name for name in ("unsigned.apk", "aligned.apk", "signed.apk"))
        run([tools / "aapt2", "link", "-o", unsigned, "--manifest", HERE / "AndroidManifest.xml",
             "-I", android_jar, "--min-sdk-version", "28", "--target-sdk-version", "34",
             "--version-code", "1", "--version-name", "1.0"])
        with ZipFile(unsigned, "a", compression=ZIP_DEFLATED) as archive:
            archive.write(dex / "classes.dex", "classes.dex")
            for library in sorted(libraries.glob("*.so")):
                archive.write(library, "lib/arm64-v8a/" + library.name)
        run([tools / "zipalign", "-f", "16384", unsigned, aligned])
        # This ephemeral synthetic-only key protects no account or game data.
        key = work / "synthetic.p12"
        run([keytool, "-genkeypair", "-keystore", key, "-storetype", "PKCS12", "-alias", "synthetic",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650", "-dname", "CN=Synthetic Self Test",
             "-storepass", "android", "-keypass", "android"])
        run([tools / "apksigner", "sign", "--ks", key, "--ks-key-alias", "synthetic",
             "--ks-pass", "pass:android", "--out", signed, aligned])
        run([tools / "apksigner", "verify", "--verbose", signed])
        run([tools / "zipalign", "-c", "16384", signed])
        badging = run([tools / "aapt2", "dump", "badging", signed])
        if "package: name='" + PACKAGE + "'" not in badging or "native-code: 'arm64-v8a'" not in badging:
            raise ValueError("Self-test package or ABI inventory mismatch")
        if any(digest(HERE / name) != value for name, value in source_hashes.items()):
            raise ValueError("Self-test source changed during build")
        report = {"schema": 1, "package": PACKAGE, "synthetic_only": True, "game_included": False,
                  "runtime_verified": False, "abi": "arm64-v8a", "ndk": "26.3.11579264",
                  "shadowhook_version": "2.0.1", "shadowhook_aar_sha256": AAR_SHA256,
                  "source_sha256": source_hashes, "output_sha256": digest(signed),
                  "output_bytes": signed.stat().st_size,
                  "native_sha256": {path.name: digest(path) for path in sorted(libraries.glob("*.so"))}}
        with output.open("xb") as target, signed.open("rb") as source:
            shutil.copyfileobj(source, target)
        output.with_suffix(".apk.evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        output.with_suffix(".apk.build.log").write_text("\n".join(logs))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shadowhook-aar", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--android-jar", type=Path, required=True)
    parser.add_argument("--javac", type=Path)
    args = parser.parse_args()
    javac = args.javac or shutil.which("javac") or Path(os.environ.get("JAVA_HOME", "/nonexistent")) / "bin/javac"
    print(json.dumps(build(args.output, shadowhook_aar=args.shadowhook_aar, ndk=args.ndk,
                           build_tools=args.build_tools, android_jar=args.android_jar, javac=javac), indent=2))


if __name__ == "__main__":
    main()
