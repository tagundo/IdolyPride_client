#!/usr/bin/env python3
"""Offline SDK-free ARM64 AppKit launcher with an unchanged audited Mac runtime.

This Linux cross-build verifies artifacts, not execution on macOS. The native
SwiftUI builder remains macos-server/build_app.py for a real Mac runner.
"""
from __future__ import annotations
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import plistlib
import resource
import shutil
import stat
import struct
import subprocess
import sys
import time
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from runtime_export import export_runtime
from adhoc_verify import verify_adhoc

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "src"))
from certificate_bundle import install_certificate_bundle
from payload import translation_bundle_input
APP = "IdolyPrideLocalServer"
VERSION = "0.3.28"
BUILD_NUMBER = "46"
RUNTIME_SHA = "b661664a8ca99403ee717f4df08056079df9d9bcd1a6b90f82c9a9f7f8a1e25d"
PAYLOAD_SHA = "c94cd2ee7e722e6df67f02f31868422ff5d3bf1657c64a05a61b5059572475d8"
PAYLOAD_BYTES = 191305222
SIGNER_SHA = "dab9a7465f96aba3c81e793775510f745b91a46b6418e89f7317b5d8fc7bcea2"
CGROUP = Path("/sys/fs/cgroup")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release_public_input_cache(path):
    # Only closed build inputs/tools, never the running VM or user state.
    # Keep the conservative direct-headroom gate useful after a large read.
    if hasattr(os, "posix_fadvise"):
        with Path(path).open("rb") as stream:
            os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)


def install_payload(source, destination, *, expected_sha=PAYLOAD_SHA, expected_bytes=PAYLOAD_BYTES):
    """Prefer one inode; cross-filesystem builds make one bounded app copy."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file() or source.stat().st_size != expected_bytes:
        raise ValueError("Pinned payload size or source type differs")
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        created = False
        try:
            with source.open("rb") as incoming, destination.open("xb") as outgoing:
                created = True
                copied = 0
                while block := incoming.read(65536):
                    copied += len(block)
                    if copied > expected_bytes:
                        raise ValueError("Payload changed beyond its byte bound")
                    outgoing.write(block)
                if copied != expected_bytes:
                    raise ValueError("Payload size changed while copying")
                outgoing.flush()
                os.fsync(outgoing.fileno())
            destination.chmod(stat.S_IMODE(source.stat().st_mode))
            if destination.stat().st_size != expected_bytes or digest(destination) != expected_sha:
                raise ValueError("Copied payload fingerprint differs")
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            release_public_input_cache(source)
        return "streamed_copy"
    # The caller validates the public source before installing it; verify the
    # shared inode again so this helper also rejects an unexpected standalone input.
    if digest(destination) != expected_sha:
        destination.unlink()
        raise ValueError("Linked payload fingerprint differs")
    release_public_input_cache(source)
    return "hardlink"


def budget():
    maximum = int((CGROUP / "memory.max").read_text())
    current = int((CGROUP / "memory.current").read_text())
    events = dict(line.split() for line in (CGROUP / "memory.events").read_text().splitlines())
    return {"memory_current": current, "memory_max": maximum,
            "direct_headroom": maximum-current, "oom_kill": int(events["oom_kill"])}


def run(command, evidence, name, *, seconds=30):
    before = budget()
    # Small C/rcodesign processes are separately bounded; Android's larger
    # full-APK guard is deliberately unchanged by this cross-build route.
    if before["direct_headroom"] < 512*1024*1024:
        raise ValueError("Mac bounded tool requires 512 MiB direct headroom")
    def limit():
        os.nice(19)
        resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024,)*2)
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    started = time.monotonic()
    with (evidence / (name+".log")).open("wb") as output:
        subprocess.run([str(item) for item in command], stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=seconds,
                       env=dict(os.environ, MALLOC_ARENA_MAX="2"), preexec_fn=limit)
    release_public_input_cache(command[0])
    after = budget()
    if after["oom_kill"] != before["oom_kill"]:
        raise ValueError("OOM counter changed during bounded Mac tool")
    return {"argv": [str(x) for x in command], "seconds": time.monotonic()-started,
            "before": before, "after": after}


def tree_hashes(root):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink()}


def archive_app(app, archive):
    if archive.exists():
        raise ValueError("Archive output already exists")
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(app.rglob("*")):
            name = str(path.relative_to(app.parent))
            info = ZipInfo(name + ("/" if path.is_dir() and not path.is_symlink() else ""))
            info.create_system = 3
            info.external_attr = path.lstat().st_mode << 16
            info.compress_type = ZIP_DEFLATED
            if path.is_symlink():
                output.writestr(info, os.readlink(path).encode())
            elif path.is_dir():
                output.writestr(info, b"")
            else:
                with path.open("rb") as incoming, output.open(info, "w") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 65536)


def build(args):
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Use CPython 3.12 for original PYZ inspection")
    translations, translation_report = translation_bundle_input(
        getattr(args, "translations", None), getattr(args, "translations_sha256", None),
        getattr(args, "translations_bytes", None))
    for path, expected, size in ((args.runtime, RUNTIME_SHA, None), (args.payload, PAYLOAD_SHA, PAYLOAD_BYTES),
                                 (args.rcodesign, SIGNER_SHA, None)):
        if path.is_symlink() or not path.is_file() or (size is not None and path.stat().st_size != size) or digest(path) != expected:
            raise ValueError("Pinned public input differs: " + path.name)
    if args.app.exists() or args.archive.exists():
        raise ValueError("Choose unused app/archive output")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if commit != args.source_commit:
        raise ValueError("Worktree HEAD differs from frozen source commit")
    # Only tracked production sources are read, with exact bytes checked against
    # the supplied local Git commit before they enter the app.
    source_paths = [*sorted((ROOT/"src/idoly_local").glob("*.py")),
                    ROOT/"macos-server/engine.py", ROOT/"macos-server/payload.py", ROOT/"macos-server/certificate_bundle.py",
                    *sorted((ROOT/"macos-server/certificates").iterdir()),
                    *sorted(HERE.glob("*.c")), *sorted(HERE.glob("*.h")), HERE/"libSystem.tbd", *sorted(HERE.glob("*.py"))]
    sources = {}
    for path in source_paths:
        relative = str(path.relative_to(ROOT))
        frozen = subprocess.check_output(["git", "-c", "protocol.allow=never", "show", commit+":"+relative], cwd=ROOT,
                                         env=dict(os.environ, GIT_NO_LAZY_FETCH="1"), timeout=10)
        if frozen != path.read_bytes():
            raise ValueError("Source differs from frozen commit: " + relative)
        sources[relative] = hashlib.sha256(frozen).hexdigest()
    if shutil.disk_usage(args.archive.parent).free < 260*1024*1024:
        raise ValueError("Mac archive requires 260 MiB disk (including 150 MiB reserve)")
    args.evidence.mkdir(parents=True, exist_ok=True)
    contents = args.app/"Contents"
    resources = contents/"Resources"
    executable = contents/"MacOS"/APP
    executable.parent.mkdir(parents=True)
    resources.mkdir()
    report = {"version": VERSION, "build_number": BUILD_NUMBER, "source_commit": commit,
              "source_sha256": sources, "architecture": "arm64", "minimum_macos": "13.0",
              "ui": "native AppKit (SDK-free C)", "actual_mac_execution": False,
              "actual_gameplay_verified": False, "notarized": False, "signature": "ad-hoc",
              "user_python_required": False, "user_terminal_required": False,
              "input_runtime_archive_sha256": RUNTIME_SHA, "server_data_sha256": PAYLOAD_SHA,
              "translations": translation_report}
    report["runtime"] = export_runtime(args.runtime, resources/"runtime")
    release_public_input_cache(args.runtime)
    report["public_tls_trust"] = install_certificate_bundle(resources/"runtime/_internal", resources/"licenses/tls")
    for path in source_paths:
        if path.suffix != ".py" or path.parent == HERE:
            continue
        target = resources/"code"/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    report["payload_installation"] = install_payload(args.payload, resources/"ServerData.zip")
    if translations is not None:
        report["translations"]["installation"] = install_payload(translations, resources / "bundledTranslations.zip",
            expected_sha=translation_report["sha256"], expected_bytes=translation_report["bytes"])
        (resources / "bundledTranslations.json").write_text(json.dumps({"schema": 1, "platform": "ios",
            "sha256": translation_report["sha256"], "bytes": translation_report["bytes"]}, sort_keys=True) + "\n")
    for source in (ROOT/"LICENSE", ROOT/"NOTICE"):
        if source.is_file():
            target = resources/"licenses"/source.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, target)
    for relative in ("LICENSE", "NOTICE", "third-party-licenses/Go-LICENSE", "third-party-licenses/Protobuf-LICENSE",
                     "third-party-licenses/YAML-LICENSE", "third-party-licenses/YAML-NOTICE"):
        target=resources/"licenses/native-live-engine"/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/"native-live-engine"/relative, target)
    with (contents/"Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleExecutable": APP, "CFBundleIdentifier": "game.idolypride.localserver",
                      "CFBundleName": "IdolyPride Local Server", "CFBundleDisplayName": "아이프라 로컬 서버",
                      "CFBundlePackageType": "APPL", "CFBundleShortVersionString": VERSION, "CFBundleVersion": BUILD_NUMBER,
                      "LSMinimumSystemVersion": "13.0", "LSApplicationCategoryType": "public.app-category.games",
                      "NSHighResolutionCapable": True, "NSPrincipalClass": "NSApplication",
                      "NSDownloadsFolderUsageDescription": "게임 리소스를 Downloads/IdolyPride에 보관하고 게임에 제공합니다."}, stream)
    commands=[]
    objects=[]
    for name in ("main", "python_host", "appkit_ui"):
        obj=args.evidence/(name+".o");objects.append(obj)
        commands.append(run([args.llvm/"clang", "-target", "arm64-apple-macos13.0", "-ffreestanding",
            "-fno-stack-protector", "-fvisibility=hidden", "-O2", "-Wall", "-Wextra", "-Werror",
            "-I", HERE, "-c", HERE/(name+".c"), "-o", obj], args.evidence, "compile-"+name, seconds=10))
    commands.append(run([args.llvm/"ld.lld", "-flavor", "darwin", "-arch", "arm64", "-platform_version", "macos", "13.0", "13.0",
        "-e", "_main", "-pie", "-adhoc_codesign", *objects, HERE/"libSystem.tbd",
        "-rpath", "@executable_path/../Resources/runtime/_internal",
        "-rpath", "@executable_path/../Resources/runtime/_internal/Python.framework/Versions/3.12", "-o", executable],
        args.evidence, "link", seconds=10))
    executable.chmod(0o755)
    report["runtime_before_signing"] = tree_hashes(resources/"runtime")
    (resources/"bundle-provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    commands.append(run([args.rcodesign, "-C", "/dev/null", "sign", "--shallow", "--exclude", "**", "--timestamp-url", "none", args.app],
                        args.evidence, "sign", seconds=90))
    if tree_hashes(resources/"runtime") != report["runtime_before_signing"] or digest(resources/"ServerData.zip") != PAYLOAD_SHA:
        raise ValueError("Outer signing changed an immutable runtime/payload input")
    if translations is not None and (digest(resources / "bundledTranslations.zip") != translation_report["sha256"]
            or digest(translations) != translation_report["sha256"]):
        raise ValueError("Outer signing changed the optional translation input")
    # rcodesign 0.29's verify tries to parse its own empty ad-hoc CMS wrapper as
    # an X.509 signature. Verify the actual ad-hoc page/special-slot hashes.
    report["signature_verification"] = verify_adhoc(executable, info=contents/"Info.plist",
        resources=contents/"_CodeSignature/CodeResources", identifier="game.idolypride.localserver")
    report["commands"] = commands
    report["executable_sha256"] = digest(executable)
    report["executable_bytes"] = executable.stat().st_size
    seal = plistlib.loads((contents/"_CodeSignature/CodeResources").read_bytes())
    sealed = seal.get("files2", {})
    for path in resources.rglob("*"):
        if path.is_symlink():
            relative = str(path.relative_to(contents))
            if sealed.get(relative) != {"symlink": os.readlink(path)}:
                raise ValueError("Resource seal omits or changes a symlink: " + relative)
        elif path.is_file():
            relative = str(path.relative_to(contents))
            entry = sealed.get(relative)
            if not isinstance(entry, dict) or entry.get("hash2") != bytes.fromhex(digest(path)):
                raise ValueError("Resource seal omits or mismatches current resource: " + relative)
    report["resource_seal_exact_file_count"] = sum(p.is_file() and not p.is_symlink() for p in resources.rglob("*"))
    report["code_resources_sha256"] = digest(contents/"_CodeSignature/CodeResources")
    report["runtime_immutable_after_signing"] = True
    report["post_budget"] = budget()
    archive_app(args.app, args.archive)
    report["archive_bytes"] = args.archive.stat().st_size
    report["archive_sha256"] = digest(args.archive)
    report["child_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    (args.evidence/"build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({key: report[key] for key in ("archive_bytes", "archive_sha256", "executable_bytes", "child_peak_rss_kib", "actual_mac_execution")}, indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "payload", "llvm", "rcodesign", "app", "archive", "evidence"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--translations", type=Path, help="Optional separately prepared iOS translation ZIP")
    parser.add_argument("--translations-sha256", help="Explicit optional translation ZIP SHA-256")
    parser.add_argument("--translations-bytes", type=int, help="Exact optional translation ZIP size")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
