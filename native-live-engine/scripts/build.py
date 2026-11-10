#!/usr/bin/env python3
"""Verify the attributed sources and build the isolated local-rules C ABI."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


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
    output.mkdir(parents=True, exist_ok=True)
    library = output / library_name
    linker_flags = "-s -w"
    if args.target in ("android", "android-x86_64"):
        linker_flags += " -extldflags=-Wl,-z,max-page-size=16384"
    elif args.target == "macos":
        linker_flags += " -extldflags=-Wl,-install_name,@rpath/libidoly_live.dylib"
    run([go, "build", "-mod=readonly", "-buildvcs=false", "-trimpath", "-buildmode=c-shared",
         "-ldflags=" + linker_flags, "-o", library, "./cmd/livebridge"], env)
    dependencies = run([go, "list", "-mod=readonly", "-deps", "./cmd/livebridge"], env).splitlines()
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
