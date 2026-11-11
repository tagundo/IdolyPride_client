#!/usr/bin/env python3
"""Build the native server with cached Android tools, without Gradle or Go.

Use CPython 3.13, an exact committed source snapshot and a separately validated
45-table public payload. Existing APKs and account files are never overwritten.
All Java processes are sequential, bounded and run with a single CPU/worker.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile
import zlib

if __package__:
    from . import repack_android_server_python as pybundle
else:
    import repack_android_server_python as pybundle


PACKAGE = "game.qualiarts.idolypride.localserver"
VERSION, VERSION_CODE = "0.3.6", 25
CERTIFICATE = "ff5b25120ac58f5b82861320925448663a5ac3f812e93736cad1de6a6ac29e51"
CHAQUOPY_SHA256 = "04eed6260e65634ac1c2031d2ca8fdf90d58da226b2f070132a66c6e3af9e39b"
PUBLIC_INPUT_HASHES = {
    "baseline": pybundle.BASELINE_SHA256,
    "chaquopy-jar": CHAQUOPY_SHA256,
    "android-jar": "6cea1df3efb77103ac3e2beb9bf4718964b0e0869ab16d39d29d5cbae1c147ad",
    "d8-jar": "d43c8a94c9b1f1da1a7cc49c32b81e8cee1708b37ee8b530a81a0688222b42c0",
    "signer-jar": "eefdd6aed9db9fb849e4c98a50d8741e19d1b674ba6547220bcb9c3ed152123a",
}
ANDROID = "{http://schemas.android.com/apk/res/android}"
JAVA_SOURCE_ROOT = "android-server/app/src/main/java/"
JAVA_ROOT = JAVA_SOURCE_ROOT + PACKAGE.replace(".", "/") + "/"
RES_ROOT = "android-server/app/src/main/res/"
MANIFEST = "android-server/app/src/main/AndroidManifest.xml"
GRADLE = "android-server/app/build.gradle.kts"
JAVA_FILES = tuple(JAVA_ROOT + name + ".java" for name in ("MainActivity", "ServerService", "CryptoBridge"))
RESOURCE_FILES = (RES_ROOT + "values/strings.xml", RES_ROOT + "drawable/ic_server.xml")
SOURCE_FILES = frozenset((*JAVA_FILES, *RESOURCE_FILES, MANIFEST, GRADLE))
EXTRA_TABLES = frozenset(("StoryPart", "PhotoActivity", "PhotoQuestMusic", "PhotoQuestStage", "PhotoExpression"))
PAYLOAD_MANIFEST = "data/payload-manifest.json"
NATIVE_NAMES = frozenset("lib/arm64-v8a/" + name for name in (
    "libchaquopy_java.so", "libcrypto_chaquopy.so", "libcrypto_python.so", "libidoly_live.so",
    "libpython3.13.so", "libsqlite3_chaquopy.so", "libsqlite3_python.so", "libssl_chaquopy.so", "libssl_python.so"))
RESOURCE_NAMES = frozenset(("AndroidManifest.xml", "resources.arsc", "res/drawable/ic_server.xml"))
MUTABLE_NAMES = RESOURCE_NAMES | {pybundle.APP, pybundle.BUILD, pybundle.PAYLOAD, "classes2.dex"}
REMOVED_NAMES = frozenset(("classes3.dex",))
MIB = 1024 * 1024
MAX_APK = 100 * MIB
MAX_APK_STAGING = 200 * MIB
MAX_DEX, MAX_JSON, META_LIMIT = MIB, 16 * MIB, 256 * 1024
MIN_HEADROOM, MIN_ROOT_FREE = 1024 * MIB, 150 * MIB
MAX_CLEAN_INACTIVE_CREDIT = 128 * MIB
JAVA_FLAGS = ("-Xmx128m", "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=32m",
              "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1")
CGROUP = Path("/sys/fs/cgroup")


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class PublicCacheAdvice:
    """Drop only verified public inputs or this build's three closed APKs.

    This is a best-effort clean-page hint, never a substitute for the memory
    guard. Key/password paths and arbitrary discovered files are not inputs.
    """
    def __init__(self):
        self._entries, self._work = {}, None
        self.events = []

    def own_directory(self, directory):
        directory = Path(directory)
        info = directory.lstat()
        if self._work is not None or not stat.S_ISDIR(info.st_mode) or directory.is_symlink():
            raise ValueError("Expected one new owned build directory")
        self._work = (directory, info.st_dev, info.st_ino)

    def _open(self, path, expected=None):
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or (expected is not None and _file_identity(before) != expected):
            raise ValueError("Cache-advice file is not a stable regular file")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        fd = os.open(path, flags)
        try:
            if _file_identity(os.fstat(fd)) != _file_identity(before):
                raise ValueError("Cache-advice file changed while opening")
        except BaseException:
            os.close(fd)
            raise
        return fd, _file_identity(before)

    def _stable(self, path, fd, expected):
        if (_file_identity(os.fstat(fd)) != expected or _file_identity(path.lstat()) != expected):
            raise ValueError("Cache-advice file changed during the operation")

    def _register(self, role, path, expected_sha256):
        path = Path(path).absolute()
        fd, identity = self._open(path)
        try:
            limit = MAX_APK if role in ("baseline", "validated-payload") or role.startswith("own-") else 64 * MIB
            if not 0 < identity[3] <= limit or role.startswith("own-") and os.fstat(fd).st_nlink != 1:
                raise ValueError("Cache-advice input size or owned-file identity differs")
            digest = hashlib.sha256()
            while block := os.read(fd, pybundle.CHUNK):
                digest.update(block)
            self._stable(path, fd, identity)
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise ValueError("Public cache-advice input hash differs")
            self._entries[path] = (role, identity, digest.hexdigest())
        finally:
            os.close(fd)
        self._advise(path)

    def public(self, role, path, expected_sha256):
        if (role not in PUBLIC_INPUT_HASHES and role != "validated-payload"
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or role in PUBLIC_INPUT_HASHES and PUBLIC_INPUT_HASHES[role] != expected_sha256):
            raise ValueError("Only explicitly pinned public inputs may receive cache advice")
        self._register(role, path, expected_sha256)

    def completed_apk(self, name):
        if self._work is None or name not in ("unsigned.apk", "aligned.apk", "signed.apk"):
            raise ValueError("Cache advice is restricted to this build's completed APKs")
        directory, device, inode = self._work
        current = directory.lstat()
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
            raise ValueError("Owned build directory changed")
        self._register("own-" + name, directory / name, None)

    def _advise(self, path):
        role, expected, _digest = self._entries[path]
        try:
            fd, identity = self._open(path, expected)
        except FileNotFoundError:
            if role.startswith("own-"):
                return
            raise ValueError("A pinned public input disappeared") from None
        result = "unsupported"
        try:
            try:
                hint = getattr(os, "posix_fadvise", None)
                dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
                if hint is not None and dontneed is not None:
                    os.fsync(fd)
                    hint(fd, 0, 0, dontneed)
                    result = "advised"
            except OSError:
                # Unsupported hints and filesystem limitations do not relax the
                # subsequent strict resource check or change the file content.
                pass
            self._stable(path, fd, identity)
        finally:
            os.close(fd)
        self.events.append({"role": role, "path": str(path), "bytes": identity[3], "result": result})

    def advise(self):
        for path in tuple(self._entries):
            self._advise(path)


def _regular(path, *, private=False):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (private and info.st_mode & 0o077):
        raise ValueError("Expected an existing regular input with appropriate permissions")
    return path.resolve(strict=True)


def staging_budget(root, destination):
    required = MAX_APK_STAGING + 8 * MIB
    if Path(root).stat().st_dev == Path(destination).stat().st_dev:
        required += MIN_ROOT_FREE
    if shutil.disk_usage(destination).free < required:
        raise ValueError("Insufficient staging space while preserving the root disk reserve")


def read_password(path):
    size = path.stat().st_size
    if not 0 < size <= 4096:
        raise ValueError("Signing password file format differs")
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) != size or b"\0" in raw:
        raise ValueError("Signing password file format differs")
    return raw.decode("utf-8").rstrip("\r\n")


def _memory_budget():
    maximum = (CGROUP / "memory.max").read_text().strip()
    current = (CGROUP / "memory.current").read_text().strip()
    if (not re.fullmatch(r"[0-9]+", maximum) or int(maximum) == 0
            or not re.fullmatch(r"[0-9]+", current)):
        raise ValueError("A finite cgroup memory limit is required")
    credit = 0
    try:
        raw = (CGROUP / "memory.stat").read_text()
        if len(raw) > 64 * 1024:
            raise ValueError("Unexpected cgroup memory statistics")
        values = {}
        for line in raw.splitlines():
            fields = line.split()
            if (len(fields) != 2 or fields[0] in values
                    or not re.fullmatch(r"[0-9]+", fields[1])):
                raise ValueError("Unexpected cgroup memory statistics")
            values[fields[0]] = int(fields[1])
        clean_file = max(0, values["file"] - values["shmem"]
                         - values["file_dirty"] - values["file_writeback"])
        credit = min(MAX_CLEAN_INACTIVE_CREDIT, values["inactive_file"], clean_file)
    except (OSError, UnicodeError, KeyError, ValueError):
        # Missing or malformed statistics never add to direct headroom.
        pass
    direct = int(maximum) - int(current)
    return {"memory_current": int(current), "memory_max": int(maximum),
            "memory_direct_headroom": direct, "memory_clean_inactive_credit": credit,
            "memory_effective_headroom": direct + credit}


def _resource_guard(root):
    budget = _memory_budget()
    if (budget["memory_direct_headroom"] < MIN_HEADROOM - MAX_CLEAN_INACTIVE_CREDIT
            or budget["memory_effective_headroom"] < MIN_HEADROOM):
        raise ValueError("Defer build until at least 1 GiB cgroup headroom is available")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            name = (entry / "comm").read_text().strip()
            status = (entry / "status").read_text()
        except OSError:
            continue
        if name in ("java", "javac") and not re.search(r"^State:\s+Z\b", status, re.MULTILINE):
            raise ValueError("Another Java process is active")
    if shutil.disk_usage(root).free < MIN_ROOT_FREE:
        raise ValueError("Preserve at least 150 MiB root disk reserve")
    events = dict(line.split() for line in (CGROUP / "memory.events").read_text().splitlines())
    return {**budget, "oom_kill": events.get("oom_kill")}


def _run(command, *, root, env, timeout=180, cache=None):
    """Bound both pipe reads and process lifetime; never print command/output."""
    if cache is not None:
        cache.advise()
    _resource_guard(root)
    process = subprocess.Popen(["/usr/bin/nice", "-n", "19", *map(str, command)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env, start_new_session=True)
    blocks, size, deadline = [], 0, time.monotonic() + timeout
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("Offline Android tool timed out")
                block = os.read(process.stdout.fileno(), min(65536, MIB + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > MIB:
                    raise ValueError("Offline Android tool output exceeded its bound")
                blocks.append(block)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining):
            raise ValueError("Offline Android tool failed; diagnostic output withheld")
        return b"".join(blocks)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        process.stdout.close()


def source_blobs(root, commit):
    """Read only the fixed public Java/resource/build inputs from the commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("An exact full source commit is required")
    listing = pybundle._git(root, "ls-tree", "-rz", "--full-tree", commit, "--",
                            JAVA_SOURCE_ROOT, RES_ROOT, MANIFEST, GRADLE, limit=META_LIMIT)
    result = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, encoded_name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split()
        name = encoded_name.decode("utf-8")
        if (name not in SOURCE_FILES or name in result or mode not in ("100644", "100755")
                or kind != "blob" or not re.fullmatch(r"[0-9a-f]{40}", oid)):
            raise ValueError("Committed launcher source inventory differs")
        result[name] = pybundle._git(root, "cat-file", "blob", oid, limit=MIB)
    if result.keys() != SOURCE_FILES:
        raise ValueError("Committed launcher source inventory is incomplete")
    gradle = result[GRADLE].decode("utf-8")
    for prop, value in (("serverVersionCode", str(VERSION_CODE)), ("serverVersionName", VERSION)):
        if len(re.findall(r'gradleProperty\("' + prop + r'"\)\.orElse\("' + re.escape(value) + r'"\)', gradle)) != 1:
            raise ValueError("Source version defaults must match the manual build identity")
    return result


def tool_sources(root, commit):
    """Bind the executing builder and reused compiler helper to the freeze."""
    result = {}
    for name, loaded in (("tools/build_android_server_manual.py", Path(__file__)),
                         ("tools/repack_android_server_python.py", Path(pybundle.__file__))):
        if loaded.resolve() != (root / name).resolve():
            raise ValueError("Run the builder and compiler helper from the frozen source repository")
        raw = pybundle._git(root, "cat-file", "blob", commit + ":" + name, limit=MIB)
        expected = hashlib.sha256(raw).hexdigest()
        if pybundle.digest(loaded) != expected:
            raise ValueError("Build tool worktree differs from the frozen source")
        result[name] = expected
    return result


def validate_epoch(raw, expected):
    if (type(raw) is not bytes or type(expected) is not int
            or re.fullmatch(rb"[0-9]+", raw) is None or int(raw) != expected):
        raise ValueError("Epoch must match the frozen source commit time")


def manifest_xml(raw):
    if b"<!" in raw:
        raise ValueError("Manifest declarations/entities are not accepted")
    tree = ET.fromstring(raw)
    if tree.tag != "manifest" or tree.get("package", PACKAGE) != PACKAGE:
        raise ValueError("Unexpected manifest package")
    tree.set("package", PACKAGE)
    tree.set(ANDROID + "versionCode", str(VERSION_CODE))
    tree.set(ANDROID + "versionName", VERSION)
    sdk = tree.findall("uses-sdk")
    if len(sdk) > 1:
        raise ValueError("Ambiguous SDK manifest")
    if not sdk:
        sdk = [ET.Element("uses-sdk")]
        tree.insert(0, sdk[0])
    sdk[0].set(ANDROID + "minSdkVersion", "26")
    sdk[0].set(ANDROID + "targetSdkVersion", "34")
    applications = tree.findall("application")
    if len(applications) != 1:
        raise ValueError("Expected one application")
    app = applications[0]
    app.set(ANDROID + "debuggable", "true")
    app.set(ANDROID + "extractNativeLibs", "true")
    if app.get(ANDROID + "allowBackup") != "false":
        raise ValueError("Server data backup policy differs")
    components = {(child.tag, child.get(ANDROID + "name")) for child in app}
    if len(app) != 2 or components != {("activity", ".MainActivity"), ("service", ".ServerService")}:
        raise ValueError("Server component inventory differs")
    for child in app:
        child.set(ANDROID + "name", PACKAGE + child.get(ANDROID + "name"))
    ET.register_namespace("android", ANDROID[1:-1])
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def build_config(payload_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
        raise ValueError("An explicit payload SHA-256 is required")
    return ("package " + PACKAGE + ";\npublic final class BuildConfig {\n"
            ' public static final boolean DEBUG = Boolean.parseBoolean("true");\n'
            ' public static final String APPLICATION_ID = "' + PACKAGE + '";\n'
            ' public static final String BUILD_TYPE = "debug";\n'
            f' public static final int VERSION_CODE = {VERSION_CODE};\n'
            f' public static final String VERSION_NAME = "{VERSION}";\n'
            f' public static final String SERVER_DATA_SHA256 = "{payload_sha256}";\n'
            "}\n").encode()


def dex_classes(raw):
    """Read bounded class definitions, not arbitrary strings/references."""
    if (len(raw) < 112 or len(raw) > MAX_DEX or raw[:8] != b"dex\n038\0"
            or struct.unpack_from("<III", raw, 32) != (len(raw), 112, 0x12345678)
            or hashlib.sha1(raw[32:]).digest() != raw[12:32]
            or zlib.adler32(raw[12:]) & 0xffffffff != struct.unpack_from("<I", raw, 8)[0]):
        raise ValueError("DEX format, version or checksum differs")
    def table(at, width):
        count, offset = struct.unpack_from("<II", raw, at)
        if count > 65535 or offset % 4 or offset + count * width > len(raw) or (count and offset < 112):
            raise ValueError("DEX table is outside its bounds")
        return count, offset
    strings, string_offset = table(56, 4)
    types, type_offset = table(64, 4)
    count, class_offset = table(96, 32)
    result = set()
    for index in range(count):
        type_index = struct.unpack_from("<I", raw, class_offset + index * 32)[0]
        if type_index >= types:
            raise ValueError("DEX class type is invalid")
        string_index = struct.unpack_from("<I", raw, type_offset + type_index * 4)[0]
        if string_index >= strings:
            raise ValueError("DEX class name is invalid")
        offset = struct.unpack_from("<I", raw, string_offset + string_index * 4)[0]
        length = 0
        for shift in range(0, 35, 7):
            if offset >= len(raw):
                raise ValueError("DEX class name is truncated")
            value = raw[offset]
            offset += 1
            length |= (value & 127) << shift
            if not value & 128:
                break
        else:
            raise ValueError("DEX class name length is malformed")
        end = raw.find(b"\0", offset, min(len(raw), offset + 512))
        name = raw[offset:end].decode("ascii") if end >= 0 else ""
        if (len(name) != length or not re.fullmatch(r"L[A-Za-z0-9_$/]+;", name) or name in result):
            raise ValueError("DEX class names are malformed or duplicated")
        result.add(name)
    return result


def dependency_classes(jar, baseline_dex):
    if pybundle.digest(jar) != CHAQUOPY_SHA256:
        raise ValueError("Expected the exact original public Chaquopy 17 runtime JAR")
    with ZipFile(jar) as archive:
        infos = pybundle._members(archive, 2 * MIB)
        names = {"L" + name[:-6] + ";" for name in infos if name.endswith(".class")}
    if len(names) != 27 or names != dex_classes(baseline_dex):
        raise ValueError("Chaquopy JAR and preserved dependency DEX classes differ")
    return names


def validate_payload(payload, expected_sha256, baseline_archive):
    """Only extend the pinned public payload by its five named JSON tables."""
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or payload.stat().st_size > MAX_APK or pybundle.digest(payload) != expected_sha256):
        raise ValueError("Validated public payload hash differs")
    with baseline_archive.open(pybundle.PAYLOAD) as stream, ZipFile(stream) as old, ZipFile(payload) as new:
        old_infos = pybundle._members(old, pybundle.MAX_EXPANDED)
        infos = pybundle._members(new, pybundle.MAX_EXPANDED)
        added = {"data/master-json/" + name + ".json" for name in EXTRA_TABLES}
        if set(infos) != set(old_infos) | added or added & set(old_infos):
            raise ValueError("Payload may add only the five named public JSON tables")
        old_hashes = pybundle._hash_members(old, old_infos)
        hashes = pybundle._hash_members(new, infos)
        if any(hashes[name] != digest for name, digest in old_hashes.items() if name != PAYLOAD_MANIFEST):
            raise ValueError("Payload changed an existing public input")
        report = json.loads(pybundle._read(new, infos[PAYLOAD_MANIFEST], META_LIMIT), object_pairs_hook=pybundle._json_object)
        old_report = json.loads(pybundle._read(old, old_infos[PAYLOAD_MANIFEST], META_LIMIT), object_pairs_hook=pybundle._json_object)
        if (not isinstance(report, dict) or {k: v for k, v in report.items() if k not in ("tables", "files")}
                != {k: v for k, v in old_report.items() if k not in ("tables", "files")}):
            raise ValueError("Payload provenance changed outside tables/files")
        tables = {name[len("data/master-json/"):-5] for name in infos
                  if name.startswith("data/master-json/") and name.endswith(".json")}
        if len(tables) != 45 or not isinstance(report.get("tables"), dict) or set(report["tables"]) != tables:
            raise ValueError("Payload must contain exactly 45 public JSON tables")
        for table in tables:
            rows = json.loads(pybundle._read(new, infos["data/master-json/" + table + ".json"], MAX_JSON),
                              object_pairs_hook=pybundle._json_object)
            if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                    or type(report["tables"][table]) is not int or report["tables"][table] != len(rows)
                    or (table in EXTRA_TABLES and not rows)):
                raise ValueError("Public table counts or row structure differ")
        files = report.get("files")
        expected = {name: {"path": name, "bytes": info.file_size, "sha256": hashes[name]}
                    for name, info in infos.items() if name != PAYLOAD_MANIFEST}
        if (not isinstance(files, list) or len(files) != len(expected)
                or any(not isinstance(row, dict) or not isinstance(row.get("path"), str) for row in files)
                or {row.get("path") for row in files} != set(expected)
                or any(row != expected[row["path"]] for row in files)):
            raise ValueError("Payload file provenance differs from actual bytes")
        return {"sha256": expected_sha256, "bytes": payload.stat().st_size,
                "tables": report["tables"], "members": len(infos)}


def elf_alignment(raw):
    if len(raw) < 64 or raw[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", raw, 18)[0] != 183:
        raise ValueError("Expected an original AArch64 ELF")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    width, count = struct.unpack_from("<HH", raw, 54)
    if width != 56 or not 0 < count < 256 or offset + width * count > len(raw):
        raise ValueError("ELF program headers differ")
    loads = []
    for index in range(count):
        kind, _flags, file_offset, virtual, _physical, _size, _memory, align = struct.unpack_from("<IIQQQQQQ", raw, offset + index * width)
        if kind == 1:
            if align < 16384 or align & (align - 1) or file_offset % align != virtual % align:
                raise ValueError("Original ELF lacks compatible 16 KiB load alignment")
            loads.append(align)
    if not loads:
        raise ValueError("ELF has no load segments")
    return loads


def stream_apk(incoming, infos, target, replacements):
    with ZipFile(target, "x") as outgoing:
        outgoing.comment = incoming.comment
        for name, info in infos.items():
            if name in REMOVED_NAMES:
                continue
            copied = copy.copy(info)
            replacement = replacements.get(name)
            with outgoing.open(copied, "w") as dst:
                if isinstance(replacement, bytes):
                    dst.write(replacement)
                else:
                    src = replacement.open("rb") if isinstance(replacement, Path) else incoming.open(info)
                    with src:
                        shutil.copyfileobj(src, dst, pybundle.CHUNK)
            copied.external_attr = info.external_attr


def audit_apk(path, before, before_infos, replacement_hashes, dependency_names, compiled_names):
    with ZipFile(path) as archive:
        infos = pybundle._members(archive, pybundle.MAX_EXPANDED)
        if set(infos) != set(before) - REMOVED_NAMES:
            raise ValueError("APK member inventory differs")
        hashes = pybundle._hash_members(archive, infos)
        for name in infos:
            expected = replacement_hashes.get(name, before[name])
            if hashes[name] != expected:
                raise ValueError("APK member differs from its approved input")
            if any(getattr(infos[name], key) != getattr(before_infos[name], key)
                   for key in ("date_time", "compress_type", "external_attr", "comment", "extra")):
                raise ValueError("APK member metadata changed")
        if dex_classes(pybundle._read(archive, infos["classes.dex"], MAX_DEX)) != dependency_names:
            raise ValueError("Preserved dependency class inventory differs")
        own = dex_classes(pybundle._read(archive, infos["classes2.dex"], MAX_DEX))
        prefix = "L" + PACKAGE.replace(".", "/") + "/"
        if (not compiled_names <= own or own & dependency_names
                or any(not re.fullmatch(re.escape(prefix) + r"(?:MainActivity|ServerService)\$\$ExternalSyntheticLambda[0-9]+;", name)
                       for name in own - compiled_names)):
            raise ValueError("Own DEX classes differ from compiler inputs/synthetics")
        if {name for name in infos if name.startswith("lib/")} != NATIVE_NAMES:
            raise ValueError("Native library inventory differs")
        elf = {name: elf_alignment(pybundle._read(archive, infos[name], 16 * MIB)) for name in NATIVE_NAMES}
        return {"changed_apk_members": sorted(name for name in infos if hashes[name] != before[name]),
                "removed_apk_members": sorted(REMOVED_NAMES), "own_dex_classes": sorted(own),
                "dependency_dex_classes": sorted(dependency_names), "native_elf_load_alignments": elf,
                "all_other_member_bytes_and_metadata_preserved": True}


def _identity(badging, manifest):
    if (f"package: name='{PACKAGE}' versionCode='{VERSION_CODE}' versionName='{VERSION}'" not in badging
            or "sdkVersion:'26'" not in badging or "targetSdkVersion:'34'" not in badging
            or "native-code: 'arm64-v8a'" not in badging
            or not re.search(r":extractNativeLibs\([^)]*\)=true\b", manifest)
            or not re.search(r":debuggable\([^)]*\)=true\b", manifest)
            or not re.search(r":allowBackup\([^)]*\)=false\b", manifest)):
        raise ValueError("Linked APK identity, SDK or native extraction policy differs")


def build(args):
    pybundle._compiler()
    os.nice(19)
    os.umask(0o077)
    root = Path(args.source_root).resolve(strict=True)
    baseline, payload = _regular(args.baseline), _regular(args.payload)
    jar = _regular(args.chaquopy_jar)
    keystore, password_file = _regular(args.keystore), _regular(args.password_file, private=True)
    output = Path(args.output).absolute()
    report_path = output.with_suffix(".provenance.json")
    if (output.name != "IdolyPride-Local-Server-Android.apk" or not output.parent.is_dir()
            or any(os.path.lexists(path) for path in (output, report_path))):
        raise ValueError("Choose unused standard APK/provenance paths in an existing directory")
    if baseline.stat().st_size > MAX_APK:
        raise ValueError("Expected the exact pinned original v0.3.4 server APK")
    cache = PublicCacheAdvice()
    cache.public("baseline", baseline, pybundle.BASELINE_SHA256)
    staging_budget(root, output.parent)
    cache.advise()
    preflight = _resource_guard(root)
    sources = pybundle.committed_sources(root, args.source_commit)
    native_sources = source_blobs(root, args.source_commit)
    builder_sources = tool_sources(root, args.source_commit)
    epoch = pybundle._git(root, "show", "-s", "--format=%ct", args.source_commit, limit=32).strip()
    validate_epoch(epoch, args.epoch)
    jdk, sdk, android = Path(args.jdk_bin).resolve(strict=True), Path(args.build_tools).resolve(strict=True), _regular(args.android_jar)
    tools = [jdk / "java", jdk / "javac", sdk / "aapt2", sdk / "zipalign", sdk / "lib/d8.jar", sdk / "lib/apksigner.jar", android]
    for tool in tools:
        _regular(tool)
    for role, path in (("android-jar", android), ("d8-jar", sdk / "lib/d8.jar"),
                       ("signer-jar", sdk / "lib/apksigner.jar")):
        cache.public(role, path, PUBLIC_INPUT_HASHES[role])
    tool_hashes = {str(path): PUBLIC_INPUT_HASHES[role] for role, path in (
        ("android-jar", android), ("d8-jar", sdk / "lib/d8.jar"), ("signer-jar", sdk / "lib/apksigner.jar"))}
    tool_hashes.update({str(path): pybundle.digest(path) for path in tools if str(path) not in tool_hashes})
    env = dict(os.environ)
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS", "GRADLE_OPTS"):
        env.pop(name, None)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".manual-server-", dir=output.parent) as temporary, ZipFile(baseline) as incoming:
        work = Path(temporary)
        cache.own_directory(work)
        infos = pybundle._members(incoming, pybundle.MAX_EXPANDED)
        before = pybundle._hash_members(incoming, infos)
        if (before.get(pybundle.PAYLOAD) != pybundle.PAYLOAD_SHA256 or not (MUTABLE_NAMES | REMOVED_NAMES) <= infos.keys()
                or {name for name in infos if name.startswith("lib/")} != NATIVE_NAMES):
            raise ValueError("Pinned baseline structure differs")
        dependencies = dependency_classes(jar, pybundle._read(incoming, infos["classes.dex"], MAX_DEX))
        cache.public("chaquopy-jar", jar, CHAQUOPY_SHA256)
        stable_jar = work / "chaquopy_java-17.0.0.jar"
        shutil.copyfile(jar, stable_jar)
        if pybundle.digest(stable_jar) != CHAQUOPY_SHA256:
            raise ValueError("Runtime JAR changed while snapshotting")
        cache.public("chaquopy-jar", stable_jar, CHAQUOPY_SHA256)
        payload_report = validate_payload(payload, args.payload_sha256, incoming)
        cache.public("validated-payload", payload, args.payload_sha256)
        for name, raw in native_sources.items():
            path = work / "source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        manifest = work / "AndroidManifest.xml"
        manifest.write_bytes(manifest_xml(native_sources[MANIFEST]))
        generated, classes, dex = work / "generated", work / "classes", work / "dex"
        for path in (generated, classes, dex):
            path.mkdir()
        config = generated / "BuildConfig.java"
        config.write_bytes(build_config(args.payload_sha256))
        def run(command):
            return _run(command, root=root, env=env, cache=cache)
        compiled_res, resources = work / "compiled-res.zip", work / "resources.apk"
        run([sdk / "aapt2", "compile", "--dir", work / "source" / RES_ROOT, "-o", compiled_res])
        run([sdk / "aapt2", "link", "-I", android, "--manifest", manifest, "--java", generated,
             "--non-final-ids", "--min-sdk-version", "26", "--target-sdk-version", "34",
             "--version-code", str(VERSION_CODE), "--version-name", VERSION, "-o", resources, compiled_res])
        r_sources = sorted(generated.rglob("R.java"))
        if len(r_sources) != 1 or r_sources[0].relative_to(generated).as_posix() != PACKAGE.replace(".", "/") + "/R.java":
            raise ValueError("aapt2 generated unexpected R source")
        run([jdk / "javac", *("-J" + flag for flag in JAVA_FLAGS), "--release", "17", "-encoding", "UTF-8",
             "-classpath", str(android) + os.pathsep + str(stable_jar), "-d", classes,
             *(work / "source" / name for name in JAVA_FILES), config, r_sources[0]])
        class_files = sorted(classes.rglob("*.class"))
        compiled_names = {"L" + path.relative_to(classes).as_posix()[:-6] + ";" for path in class_files}
        if not class_files or any(not name.startswith("L" + PACKAGE.replace(".", "/") + "/") for name in compiled_names):
            raise ValueError("javac generated classes outside the app package")
        run([jdk / "java", *JAVA_FLAGS, "-cp", sdk / "lib/d8.jar", "com.android.tools.r8.D8", "--release",
             "--min-api", "26", "--lib", android, "--classpath", stable_jar, "--output", dex, *class_files])
        if sorted(path.name for path in dex.iterdir()) != ["classes.dex"]:
            raise ValueError("D8 must produce exactly one own-code DEX")
        app, modules = pybundle.compile_app(pybundle._read(incoming, infos[pybundle.APP], pybundle.MAX_APP), sources, args.epoch)
        old_build = pybundle._read(incoming, infos[pybundle.BUILD], pybundle.MAX_METADATA)
        metadata = json.loads(old_build, object_pairs_hook=pybundle._json_object)
        old_sha1 = hashlib.sha1(pybundle._read(incoming, infos[pybundle.APP], pybundle.MAX_APP)).hexdigest()
        if (metadata.get("python_version") != "3.13" or metadata.get("extract_packages") != []
                or metadata.get("assets", {}).get("app.imy") != old_sha1 or old_build.count(old_sha1.encode()) != 1):
            raise ValueError("Pinned Chaquopy extraction metadata differs")
        new_build = old_build.replace(old_sha1.encode(), hashlib.sha1(app).hexdigest().encode())
        expected_metadata = copy.deepcopy(metadata)
        expected_metadata["assets"]["app.imy"] = hashlib.sha1(app).hexdigest()
        if json.loads(new_build) != expected_metadata:
            raise ValueError("Chaquopy metadata changed outside app.imy SHA-1")
        with ZipFile(resources) as archive:
            resource_infos = pybundle._members(archive, MIB)
            if set(resource_infos) != RESOURCE_NAMES:
                raise ValueError("aapt2 resource member inventory differs")
            replacements = {name: pybundle._read(archive, info, MIB) for name, info in resource_infos.items()}
        own_dex_path = dex / "classes.dex"
        if own_dex_path.stat().st_size > MAX_DEX:
            raise ValueError("D8 output exceeds its bounded read size")
        replacements.update({pybundle.APP: app, pybundle.BUILD: new_build, pybundle.PAYLOAD: payload,
                             "classes2.dex": own_dex_path.read_bytes()})
        replacement_hashes = {name: pybundle.digest(value) if isinstance(value, Path) else hashlib.sha256(value).hexdigest()
                              for name, value in replacements.items()}
        # The supplied validated hash, rather than a second mutable-path read,
        # remains the authority if the payload file changes concurrently.
        replacement_hashes[pybundle.PAYLOAD] = args.payload_sha256
        unsigned, aligned, signed = work / "unsigned.apk", work / "aligned.apk", work / "signed.apk"
        stream_apk(incoming, infos, unsigned, replacements)
        if unsigned.stat().st_size * 2 + MIB > MAX_APK_STAGING:
            raise ValueError("Two APK files would exceed the 200 MiB staging bound")
        audit_apk(unsigned, before, infos, replacement_hashes, dependencies, compiled_names)
        cache.completed_apk("unsigned.apk")
        run([sdk / "zipalign", "-f", "4", unsigned, aligned])
        cache.completed_apk("aligned.apk")
        run([sdk / "zipalign", "-c", "4", aligned])
        unsigned.unlink()
        if aligned.stat().st_size * 2 + MIB > MAX_APK_STAGING:
            raise ValueError("Signing would exceed the two-APK staging bound")
        env["IDOLY_MANUAL_SERVER_PASSWORD"] = read_password(password_file)
        try:
            signer = [jdk / "java", *JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
            run([*signer, "sign", "--ks", keystore, "--ks-key-alias", args.key_alias,
                 "--ks-pass", "env:IDOLY_MANUAL_SERVER_PASSWORD", "--key-pass", "env:IDOLY_MANUAL_SERVER_PASSWORD",
                 "--min-sdk-version", "26", "--v1-signing-enabled", "false", "--v2-signing-enabled", "true",
                 "--v3-signing-enabled", "false", "--v4-signing-enabled", "false", "--out", signed, aligned])
        finally:
            env.pop("IDOLY_MANUAL_SERVER_PASSWORD", None)
        cache.completed_apk("signed.apk")
        signature = run([*signer, "verify", "--verbose", "--print-certs", signed]).decode("utf-8")
        if ("Signer #1 certificate SHA-256 digest: " + CERTIFICATE not in signature
                or "Number of signers: 1" not in signature
                or "Verified using v2 scheme (APK Signature Scheme v2): true" not in signature
                or "Verified using v1 scheme (JAR signing): false" not in signature
                or "Verified using v3 scheme (APK Signature Scheme v3): false" not in signature):
            raise ValueError("APK signature or original server certificate differs")
        run([sdk / "zipalign", "-c", "4", signed])
        badging = run([sdk / "aapt2", "dump", "badging", signed]).decode("utf-8")
        manifest_dump = run([sdk / "aapt2", "dump", "xmltree", "--file", "AndroidManifest.xml", signed]).decode("utf-8")
        _identity(badging, manifest_dump)
        audit = audit_apk(signed, before, infos, replacement_hashes, dependencies, compiled_names)
        if (pybundle.digest(baseline) != pybundle.BASELINE_SHA256 or pybundle.digest(payload) != args.payload_sha256
                or pybundle.digest(stable_jar) != CHAQUOPY_SHA256):
            raise ValueError("A frozen build input changed during packaging")
        signed_sha256 = pybundle.digest(signed)
        cache.advise()
        postflight = _resource_guard(root)
        if postflight["oom_kill"] != preflight["oom_kill"]:
            raise ValueError("An OOM occurred during the build; candidate not published")
        aligned.unlink()
        report = {"schema": 1, "build_method": "cached manual aapt2/javac/D8; no Gradle, Go or downloads",
                  "source_commit": args.source_commit, "epoch": args.epoch, "version_name": VERSION,
                  "version_code": VERSION_CODE, "baseline_sha256": pybundle.BASELINE_SHA256,
                  "apk_sha256": signed_sha256, "apk_bytes": signed.stat().st_size,
                  "signer_sha256": CERTIFICATE, "signature_v2_only": True, "aligned": True,
                  "payload": payload_report, "chaquopy_jar_sha256": CHAQUOPY_SHA256,
                  "generated_r_sha256": pybundle.digest(r_sources[0]), "build_config_sha256": pybundle.digest(config),
                  "public_source_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in native_sources.items()},
                  "builder_source_sha256": builder_sources,
                  "modules": modules, "app_imy_sha1": hashlib.sha1(app).hexdigest(), "audit": audit,
                  "tool_sha256": tool_hashes, "public_cache_advice": cache.events,
                  "java_flags": JAVA_FLAGS, "preflight": preflight, "postflight": postflight,
                  "seconds": time.monotonic() - started,
                  "child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  "self_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "installed": False, "gameplay_verified": False}
        staged_report = work / "provenance.json"
        staged_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        identity = (staged_report.stat().st_dev, staged_report.stat().st_ino)
        pybundle._exclusive_publish(staged_report, report_path)
        try:
            pybundle._exclusive_publish(signed, output)
        except BaseException:
            if report_path.exists() and (report_path.stat().st_dev, report_path.stat().st_ino) == identity:
                report_path.unlink()
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "source-root", "source-commit", "payload", "payload-sha256", "chaquopy-jar",
                 "jdk-bin", "build-tools", "android-jar", "keystore", "password-file", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--epoch", type=int, required=True)
    parser.add_argument("--key-alias", default="idoly-local-server")
    args = parser.parse_args(argv)
    try:
        report = build(args)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, SyntaxError, EOFError,
            BadZipFile, ET.ParseError, subprocess.SubprocessError):
        raise SystemExit("Manual server build failed; existing inputs preserved and tool output withheld") from None
    print(json.dumps({key: report[key] for key in ("source_commit", "apk_sha256", "apk_bytes", "signer_sha256")}, indent=2))


if __name__ == "__main__":
    main()
