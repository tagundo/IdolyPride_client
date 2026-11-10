#!/usr/bin/env python3
"""Verify the attributed sources and build the isolated local-rules C ABI."""
from pathlib import Path
import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATCH = ROOT / "runtime-patches/go1.27.3"
MIDR_ANCHOR = b'\tif ARM64.HasCPUID {\n'
MIDR_REPLACEMENT = b'\tif ARM64.HasCPUID && os != "android" {\n'


def verify_runtime_patch():
    """Keep the small BSD Go runtime change auditable without a Go SDK."""
    manifest = json.loads((RUNTIME_PATCH / "manifest.json").read_text())
    expected = {"schema": 1, "go_version": "go1.27.3", "target": "android/arm64",
                "toolchain_file": "src/internal/cpu/cpu_arm64_hwcap.go",
                "original_file": "original/cpu_arm64_hwcap.go.txt",
                "patched_file": "patched/cpu_arm64_hwcap.go.txt", "diff_file": "android-midr.patch",
                "license_file": "third-party-licenses/Go-LICENSE", "sdk_modified_in_place": False}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Go Android runtime patch has an unsupported version or scope")
    original = (RUNTIME_PATCH / manifest["original_file"]).read_bytes()
    patched = (RUNTIME_PATCH / manifest["patched_file"]).read_bytes()
    if original.count(MIDR_ANCHOR) != 1:
        raise ValueError("Go Android MIDR source must contain exactly one original guard")
    if patched != original.replace(MIDR_ANCHOR, MIDR_REPLACEMENT):
        raise ValueError("Go Android runtime patch must change only the MIDR guard")
    diff = "".join(difflib.unified_diff(original.decode().splitlines(True), patched.decode().splitlines(True),
                    fromfile="a/" + manifest["toolchain_file"], tofile="b/" + manifest["toolchain_file"])).encode()
    if (RUNTIME_PATCH / manifest["diff_file"]).read_bytes() != diff:
        raise ValueError("Go Android runtime patch diff does not match its sources")
    for key, raw in (("original", original), ("patched", patched), ("diff", diff),
                     ("license", (ROOT / manifest["license_file"]).read_bytes())):
        if hashlib.sha256(raw).hexdigest() != manifest.get(key + "_sha256"):
            raise ValueError("Go Android runtime patch " + key + " differs from its SHA-256 pin")
    return manifest, original, patched


def runtime_overlay(target, go, version, env, cache):
    """Overlay the exact Go source only for the Android ARM64 build."""
    if target != "android":
        return [], {"applied": False}
    if not re.fullmatch(r"go version go1\.27\.3 \S+", version):
        raise ValueError("Android ARM64 MIDR overlay requires exact Go 1.27.3")
    manifest, original, patched = verify_runtime_patch()
    goroot = Path(run([go, "env", "GOROOT"], env).strip()).resolve(strict=True)
    source = goroot / manifest["toolchain_file"]
    if source.read_bytes() != original:
        raise ValueError("Installed Go Android MIDR source differs from its original SHA-256 pin")
    if hashlib.sha256((goroot / "LICENSE").read_bytes()).hexdigest() != manifest["license_sha256"]:
        raise ValueError("Installed Go toolchain license differs from its SHA-256 pin")
    destination = (Path(cache) / "runtime-overlay/go1.27.3").resolve()
    if destination.is_relative_to(goroot):
        raise ValueError("Go runtime overlay output must stay outside the installed SDK")
    destination.mkdir(parents=True, exist_ok=True)
    replacement = destination / "cpu_arm64_hwcap.go.overlay"
    replacement.write_bytes(patched)
    overlay = destination / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {str(source): str(replacement)}}, indent=2) + "\n")
    # Preserve the exact source/patch/license receipt alongside the generated
    # overlay. The installed GOROOT is only read, never patched in place.
    for relative in ("manifest.json", "android-midr.patch"):
        shutil.copy2(RUNTIME_PATCH / relative, destination / relative)
    return ["-overlay", str(overlay)], {"applied": True, "target": manifest["target"],
        "go_version": manifest["go_version"], "toolchain_file": manifest["toolchain_file"],
        "original_sha256": manifest["original_sha256"], "patched_sha256": manifest["patched_sha256"],
        "diff_sha256": manifest["diff_sha256"], "license_file": manifest["license_file"],
        "license_sha256": manifest["license_sha256"], "reason": manifest["reason"],
        "sdk_modified_in_place": False, "hwcap_assignments_changed": False,
        "scope": "optional_android_cpu_model_tuning_only"}


def check_runtime_overlay(flags, report):
    """Check the source bytes again after Go has completed the build."""
    if not report["applied"]:
        return
    replacements = json.loads(Path(flags[1]).read_text())["Replace"]
    if len(replacements) != 1:
        raise ValueError("Go Android runtime overlay must replace exactly one source")
    source, replacement = next(iter(replacements.items()))
    for path, pin in ((source, "original_sha256"), (replacement, "patched_sha256")):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != report[pin]:
            raise ValueError("Go runtime source or overlay changed during compilation")
    report["sdk_and_overlay_source_reverified_after_build"] = True


def verify_sources():
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    for entry in manifest["copied_files"]:
        path = (ROOT / entry["file"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Upstream manifest path leaves the module")
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Upstream source differs from its pin: " + entry["file"])
    if hashlib.sha256((ROOT / "cmd/livebridge/bridge.go").read_bytes()).hexdigest() != manifest["adapter_sha256"]:
        raise ValueError("C ABI adapter differs from its verified pin")
    verify_runtime_patch()
    return manifest


def run(argv, env):
    result = subprocess.run([str(value) for value in argv], cwd=ROOT, env=env,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout


def target_settings(target, ndk=None, *, system=None, machine=None):
    """Choose a compiler target; Apple execution is never inferred from Linux."""
    if target == "macos":
        system = platform.system() if system is None else system
        machine = platform.machine() if machine is None else machine
        if system != "Darwin" or machine != "arm64":
            raise ValueError("macos requires a native Apple Silicon Darwin/arm64 host")
        return {"GOOS": "darwin", "GOARCH": "arm64", "CC": "clang", "CXX": "clang++",
                "MACOSX_DEPLOYMENT_TARGET": "13.0"}, "libidoly_live.dylib"
    if target in ("android", "android-x86_64"):
        if ndk is None:
            raise ValueError("--ndk is required for Android")
        ndk = Path(ndk).resolve()
        if "Pkg.Revision = 26.3.11579264" not in (ndk / "source.properties").read_text():
            raise ValueError("This proof is pinned to NDK 26.3.11579264")
        compiler = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
        arch, triple = (("arm64", "aarch64") if target == "android" else ("amd64", "x86_64"))
        return {"GOOS": "android", "GOARCH": arch, "CC": str(compiler / (triple + "-linux-android26-clang")),
                "CXX": str(compiler / (triple + "-linux-android26-clang++"))}, "libidoly_live.so"
    if target == "linux":
        return {"GOOS": "linux", "GOARCH": "amd64", "CC": "cc", "CXX": "c++"}, "libidoly_live.so"
    raise ValueError("Unsupported build target")


def check_macos_library(raw):
    # Require a thin ARM64 MH_DYLIB. A Darwin label or filename is not enough.
    if (len(raw) < 32 or raw[:4] != b"\xcf\xfa\xed\xfe"
            or struct.unpack_from("<I", raw, 4)[0] != 0x0100000C
            or struct.unpack_from("<I", raw, 12)[0] != 6):
        raise ValueError("macos output must be a thin ARM64 Mach-O dynamic library")


def check_android_library(raw, target):
    """Check the actual output architecture and every 16-KiB load segment."""
    machine = {"android": 183, "android-x86_64": 62}.get(target)
    if (machine is None or len(raw) < 64 or raw[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<HH", raw, 16) != (3, machine)):
        raise ValueError("Android output must be the selected 64-bit ELF dynamic library")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    size, count = struct.unpack_from("<HH", raw, 54)
    if size < 56 or not count or offset + size * count > len(raw):
        raise ValueError("Android ELF program headers are incomplete")
    alignments = []
    for index in range(count):
        kind, _flags, file_offset, address, _physical, file_size, _memory, alignment = struct.unpack_from(
            "<IIQQQQQQ", raw, offset + index * size)
        if kind != 1:  # PT_LOAD
            continue
        if (alignment < 16384 or alignment & (alignment - 1)
                or (address - file_offset) % alignment or file_offset + file_size > len(raw)):
            raise ValueError("Android ELF load segments must support 16-KiB pages")
        alignments.append(alignment)
    if not alignments:
        raise ValueError("Android ELF has no load segments")
    return alignments


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--go", default=os.environ.get("IDOLY_GO_BINARY", "go"),
                        help="Go compiler path or name; beware unrelated /usr/bin/go programs")
    parser.add_argument("--target", choices=("linux", "android", "android-x86_64", "macos"), default="linux")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--ndk", type=Path)
    args = parser.parse_args(argv)
    manifest = verify_sources()
    if args.verify_only:
        print(json.dumps({"upstream_commit": manifest["upstream_commit"],
                          "upstream_files_plus_license_verified": len(manifest["copied_files"]),
                          "adapter_verified": True}))
        return
    try:
        target_env, library_name = target_settings(args.target, args.ndk)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    output = (args.output or ROOT / "build" / args.target).resolve()
    cache = (args.cache or ROOT / "build/cache").resolve()
    # The default output/cache are ignored. Prevent accidental overwrites of
    # the vendored source when a caller chooses another in-module directory.
    for directory in (output, cache):
        if directory == ROOT or (directory.is_relative_to(ROOT)
                                 and directory.relative_to(ROOT).parts[0] not in ("build", "dist", "cache")):
            parser.error("In-module outputs must stay in build/, dist/ or cache/")
    go = shutil.which(args.go)
    if go is None:
        parser.error("Go compiler not found; pass --go /path/to/bin/go")
    env = os.environ.copy()
    env.update({"GOCACHE": str(cache / "buildcache"), "GOMODCACHE": str(cache / "modcache"),
                "GOPATH": str(cache / "gopath"), "GOTMPDIR": str(cache / "tmp"), "CGO_ENABLED": "1"})
    for name in ("buildcache", "modcache", "gopath", "tmp"):
        (cache / name).mkdir(parents=True, exist_ok=True)
    try:
        version = run([go, "version"], env).strip()
    except (RuntimeError, OSError) as error:
        parser.error("Selected program is not a usable Go compiler; pass --go /path/to/bin/go. " + str(error))
    if not re.fullmatch(r"go version go\d+\.\d+(?:\.\d+)? \S+", version):
        parser.error("Selected program is not the Go compiler; /usr/bin/go may be a board-game program")
    env.update(target_env)
    overlay_flags, overlay_report = runtime_overlay(args.target, go, version, env, cache)
    output.mkdir(parents=True, exist_ok=True)
    library = output / library_name
    linker_flags = "-s -w"
    if args.target in ("android", "android-x86_64"):
        linker_flags += " -extldflags=-Wl,-z,max-page-size=16384"
    elif args.target == "macos":
        linker_flags += " -extldflags=-Wl,-install_name,@rpath/libidoly_live.dylib"
    run([go, "build", *overlay_flags, "-mod=readonly", "-buildvcs=false", "-trimpath", "-buildmode=c-shared",
         "-ldflags=" + linker_flags, "-o", library, "./cmd/livebridge"], env)
    dependencies = run([go, "list", *overlay_flags, "-mod=readonly", "-deps", "./cmd/livebridge"], env).splitlines()
    check_runtime_overlay(overlay_flags, overlay_report)
    forbidden = [name for name in dependencies if any(value in name for value in
                 ("mongo", "grpc", "gofiber", "sqlcipher", "/db/", "/server/"))]
    if forbidden:
        raise ValueError("Unexpected server/DB dependency: " + ", ".join(forbidden))
    if args.target == "macos":
        check_macos_library(library.read_bytes())
        install_names = run(["otool", "-D", library], env).splitlines()
        if "@rpath/libidoly_live.dylib" not in [line.strip() for line in install_names]:
            raise ValueError("macos dynamic library must use a relocatable @rpath install name")
        run(["codesign", "--force", "--sign", "-", "--timestamp=none", library], env)
        run(["codesign", "--verify", "--strict", "--verbose=2", library], env)
    raw = library.read_bytes()
    report = {"target": args.target, "go_version": version, "upstream_commit": manifest["upstream_commit"],
              "abi_version": 1, "ruleset": "live-v5", "local_rules_only": True,
              "build_host": {"system": platform.system(), "machine": platform.machine()},
              "library_bytes": len(raw), "library_sha256": hashlib.sha256(raw).hexdigest(),
              "no_db_or_server_dependencies": True, "dependencies": dependencies,
              "toolchain_overlay": overlay_report,
              "official_score_equivalence": False}
    if args.target in ("android", "android-x86_64"):
        alignments = check_android_library(raw, args.target)
        report.update(ndk_revision="26.3.11579264", android_min_api=26,
                      linker_max_page_size=16384, device_execution_tested=False,
                      android_abi="arm64-v8a" if args.target == "android" else "x86_64",
                      architecture="arm64" if args.target == "android" else "x86_64",
                      elf_load_segment_alignment=alignments, elf_16k_load_alignment_verified=True)
    if args.target == "macos":
        report.update(architecture="arm64", macos_deployment_target="13.0",
                      install_name="@rpath/libidoly_live.dylib",
                      ad_hoc_codesign_verified=True, library_execution_tested=False,
                      full_simulation_tested=False)
    (output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "dependencies"}))


if __name__ == "__main__":
    main()
