"""Build the hook-free ARM64 Unity UI bridge for synthetic emulator QA only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
NDK_REVISION = "26.3.11579264"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def header(profile, output):
    if (profile["schema"] != 1 or profile["architecture"] != "arm64-v8a"
            or profile["client_version"] != "6.1.1"):
        raise ValueError("Only the pinned Android 6.1.1 runtime profile is supported")
    rows, seen = [], set()
    for row in profile["exports"]:
        name, rva, data = row["name"], int(row["rva"], 16), bytes.fromhex(row["expected16"])
        if not name.startswith("il2cpp_") or not name.replace("_", "").isalnum() or name in seen or rva % 4 or len(data) != 16:
            raise ValueError("Invalid pinned runtime export profile")
        seen.add(name)
        rows.append("{" + json.dumps(name) + "," + hex(rva) + ",{"
                    + ",".join(hex(n) for n in data) + "}},")
    build = bytes.fromhex(profile["elf_build_id"])
    if len(build) != 20:
        raise ValueError("Unexpected runtime build ID")
    output.write_text("#include <stdint.h>\n"
        "static const unsigned char UI_BUILD_ID[] = {" + ",".join(hex(n) for n in build) + "};\n"
        "struct ui_export { const char *name; uintptr_t rva; unsigned char bytes[16]; };\n"
        "static const struct ui_export UI_EXPORTS[] = {\n" + "\n".join(rows) + "\n};\n"
        "#define UI_EXPORT_COUNT (sizeof(UI_EXPORTS)/sizeof(UI_EXPORTS[0]))\n")


def check_elf(path):
    b = Path(path).read_bytes()
    if b[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", b, 18)[0] != 183:
        raise ValueError("UI bridge must be ARM64")
    offset = struct.unpack_from("<Q", b, 32)[0]
    size, count = struct.unpack_from("<HH", b, 54)
    for i in range(count):
        kind, flags, file, address, physical, files, memory, alignment = struct.unpack_from("<II6Q", b, offset + i * size)
        if kind == 1 and (alignment < 16384 or file % 16384 != address % 16384):
            raise ValueError("UI bridge must support 16 KiB pages")


def build_native(output, *, ndk=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or HERE.parents[2] / ".setup/android-sdk")
    ndk = Path(ndk or os.environ.get("ANDROID_NDK_HOME") or sdk / "ndk" / NDK_REVISION)
    properties = dict(line.split("=", 1) for line in (ndk / "source.properties").read_text().splitlines() if "=" in line)
    if next((v.strip() for k, v in properties.items() if k.strip() == "Pkg.Revision"), None) != NDK_REVISION:
        raise ValueError("UI bridge requires pinned NDK " + NDK_REVISION)
    bin_dir = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    compiler = bin_dir / "aarch64-linux-android28-clang"
    if not compiler.is_file():
        raise ValueError("Linux ARM64 NDK compiler not found")
    profile_path = HERE / "runtime-profile.json"
    profile = json.loads(profile_path.read_text())
    header(profile, output / "ui_profile.h")
    target = output / "lib/arm64-v8a/libidoly_qa_ui_bridge.so"
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [str(compiler), "-std=c11", "-O2", "-fPIC", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
        "-I", str(output), "-I", str(HERE), "-shared", str(HERE / "ui_bridge.c"), "-ldl",
        "-Wl,--no-undefined", "-Wl,--build-id=sha1", "-Wl,-z,relro,-z,now", "-Wl,-z,max-page-size=16384",
        "-Wl,-z,common-page-size=16384", "-Wl,-soname,libidoly_qa_ui_bridge.so", "-o", str(target)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    check_elf(target)
    dynamic = subprocess.check_output([str(bin_dir / "llvm-readelf"), "-d", str(target)], text=True)
    if "shadowhook" in dynamic or "libc++" in dynamic:
        raise ValueError("UI bridge must not depend on hook or C++ runtimes")
    report = {"schema": 1, "qa_only": True, "synthetic_profile_only": True,
        "architecture": "arm64-v8a", "minimum_api": 28, "alignment_bytes": 16384,
        "ndk_revision": NDK_REVISION, "hooks": False, "game_code_modified": False,
        "dispatch": "UnityPlayer.queueGLThreadEvent(Runnable) -> UnityMain JNI",
        "native_click": "disabled; use fresh actual UI bounds with Android input",
        "runtime_validation": profile["runtime_validation"],
        "original_native_sha256": profile["original_native_sha256"],
        "bootstrap_native_sha256": profile["bootstrap_native_sha256"],
        "elf_build_id": profile["elf_build_id"], "runtime_profile_sha256": digest(profile_path),
        "limits": {"nodes": 512, "json_bytes": 65535, "array_scan": 8192},
        "read_only_input_telemetry": {
            "scope": "frame_observation and the exact NoticeDialog CloseButton only",
            "gesture": "existing SolisButtonBase._longTapGesture metadata fields; no lazy getter",
            "canvas_alpha": "existing target CanvasRenderer.GetInheritedAlpha; unavailable if absent",
            "canvas_flags": "target and ancestors until ignoreParentGroups; max32 ancestors; multiple groups per transform unavailable",
            "frames": "Time.frameCount/unscaledDeltaTime/timeScale, nullable typed getters",
            "no_readiness_claim": "Does not prove final raycast winner or Android input delivery"},
        "source_sha256": {p.name: digest(p) for p in [HERE / "ui_bridge.c", HERE / "ui_json.h", Path(__file__)]},
        "library_sha256": {target.name: digest(target)}}
    (output / "native-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ndk", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build_native(args.output, ndk=args.ndk), indent=2))
    except subprocess.CalledProcessError as error:
        raise SystemExit("UI bridge build failed: " + (error.stderr or "")[-3000:]) from None


if __name__ == "__main__":
    main()
