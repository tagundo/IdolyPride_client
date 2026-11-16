#!/usr/bin/env python3
"""Build the native server with cached Android tools, without Gradle or Go.

Use CPython 3.13, an exact committed source snapshot and a separately validated
source-pinned latest public payload. Existing APKs and account files are never overwritten.
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
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo
import zlib

if __package__:
    from . import repack_android_server_python as pybundle
    from . import latest_server_data_pin as love_payload
else:
    import repack_android_server_python as pybundle
    import latest_server_data_pin as love_payload


PACKAGE = "game.qualiarts.idolypride.localserver"
VERSION, VERSION_CODE = "0.3.32", 49
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
JAVA_FILES = tuple(JAVA_ROOT + name + ".java" for name in ("MainActivity", "ServerService", "CryptoBridge",
    "PresentationSettings", "PlaybackSettings", "PlaybackStorage", "RenderingExperiment",
    "LibrarySettings", "ResourceTransfers"))
RESOURCE_FILES = (RES_ROOT + "values/strings.xml", RES_ROOT + "drawable/ic_server.xml")
SOURCE_FILES = frozenset((*JAVA_FILES, *RESOURCE_FILES, MANIFEST, GRADLE))
EXTRA_TABLES = frozenset(("StoryPart", "PhotoActivity", "PhotoQuestMusic", "PhotoQuestStage", "PhotoExpression",
                          "CompanyGrade", "CompanyTrustLevel", "CompanyEnjoyCharacterLevel",
                          "CompanyEnjoyCharacterLevelSetting", "PhotoPose", "PhotoPoseMotion",
                          "ExcursionPlace", "ExcursionPlaceSetting", "ExcursionGazeReaction", "HomeTalk"))
ADDED_JSON_SHA256 = {
    "StoryPart": "f67cd5069ecb3dec86f6365c2a1f142a39bbc2e6a9bb3bc07123c0cdaeee5332",
    "PhotoActivity": "6dfde902f963cf72c49729555f5c31281bc59c0c1df67c4c2374cf4ef83fe70b",
    "PhotoQuestMusic": "03b3032bbc86a4034aafbd47c651498be5d01b0b4c34e618e9855980831ecb33",
    "PhotoQuestStage": "19812a9fcce1d362978fc39649271c5579d8dd475e6d7f378344e5f10329e6ed",
    "PhotoExpression": "ede48c24a81498d02569d6bc5aae81ae7ceeb36516d78fc601df679c58709ae4",
    "CompanyGrade": "0d9a1ef4426ea4446c8332c5c038d972f298eff7af517233a0d36bb09d42e039",
    "CompanyTrustLevel": "655d926ec7a41fde833745cba3bdf08f4789dbf1aac71e94d07ef532829edbd3",
    "CompanyEnjoyCharacterLevel": "bc0c90e3f9b7fa82c4509aecf68ff16decf234bd66ba345ccc5924bd2f8afe01",
    "CompanyEnjoyCharacterLevelSetting": "5b5097b5ba3dc732e1cf402f60a36ac35ac5a032276d74c93dc165320d522dbc",
    "PhotoPose": "29556759c098ff4c506a86c8de38854de757f497a7c9401ab9e64ca8c42e338f",
    "PhotoPoseMotion": "23671200d842f0e9a336927f58f534a78776fe82b9fdb4e4217f15839e2dc9f2",
    "ExcursionPlace": "863b779b4ed7829cb81e55bc2cccd53f0967473404b8900bdaaa864e8010f065",
    "ExcursionPlaceSetting": "c47007eeb9f60398b5cee4195ec15ef5f9d21df1fcf7280e3cc74b2f725b4371",
    "ExcursionGazeReaction": "5478c9e88c7292a01d6dd1db0e398d3bf03cf2d9ce8cf0bbefdf650d35c0e164",
    "HomeTalk": "63f332a9cf291f32ff4d6b4f65dd0f2a72784f779fd94d250932597ef32dda38",
}
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local import media_master_build as media_master
from idoly_local import bundled_translations as translation_package
from idoly_local.public_payload_transaction import TABLES as LATEST_TABLES
# Older release assets may only be removed, never copied into a server release.
LEGACY_PRESENTATION_ASSETS = frozenset("assets/presentation/" + name for name in
                                      ("manifest.json", "diagnostics.apk", "resources.apk"))
SERVER_PERMISSIONS = frozenset("android.permission." + name for name in
    ("INTERNET", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_DATA_SYNC", "POST_NOTIFICATIONS",
     "MANAGE_EXTERNAL_STORAGE"))
FORBIDDEN_INSTALLER_DEX_TOKENS = (b"PresentationAddonInstaller", b"PresentationInstallActivity",
    b"PresentationStorage", b"Landroid/content/pm/PackageInstaller", b"REQUEST_INSTALL_PACKAGES")
PAYLOAD_MANIFEST = "data/payload-manifest.json"
PAYLOAD_INVENTORY = "tools/server_payload_v0331.json"
SERVER_JSON_ADDITIONS = [{"path": "data/master-json/HomeTalk.json", "bytes": 1068215,
                          "sha256": ADDED_JSON_SHA256["HomeTalk"], "rows": 559}]


def _server_json_additions_match(rows):
    return (isinstance(rows, list) and rows == SERVER_JSON_ADDITIONS
            and all(type(row["bytes"]) is int and type(row["rows"]) is int for row in rows))


BASE_PUBLIC_PAYLOAD = {"bytes": 84637208,
    "sha256": "27522b394b021a4df002a4e34f20e89b5407be7b145aeecce45f5023b5227522"}
NATIVE_NAMES = frozenset("lib/arm64-v8a/" + name for name in (
    "libchaquopy_java.so", "libcrypto_chaquopy.so", "libcrypto_python.so", "libidoly_live.so",
    "libpython3.13.so", "libsqlite3_chaquopy.so", "libsqlite3_python.so", "libssl_chaquopy.so", "libssl_python.so"))
RESOURCE_NAMES = frozenset(("AndroidManifest.xml", "resources.arsc", "res/drawable/ic_server.xml"))
MUTABLE_NAMES = RESOURCE_NAMES | {pybundle.APP, pybundle.BUILD, pybundle.PAYLOAD, "classes2.dex"}
TRANSLATIONS_ASSET = "assets/bundledTranslations.zip"
REMOVED_NAMES = frozenset(("classes3.dex",))
MIB = 1024 * 1024
MAX_APK = 100 * MIB
MAX_APK_STAGING = 200 * MIB
MAX_PAYLOAD = 256 * MIB
MAX_PAYLOAD_MEMBERS = 1024
MAX_SERVER_APK = 384 * MIB
MAX_SERVER_EXPANDED = 384 * MIB
SERVER_APK_METADATA_STAGING = 8 * MIB
MAX_TRANSLATIONS = translation_package.MAX_BUNDLE
MAX_DEX, MAX_JSON, META_LIMIT = MIB, 16 * MIB, 256 * 1024
MIN_HEADROOM, MIN_ROOT_FREE = 1024 * MIB, 150 * MIB
SERVER_STAGE_HEADROOM = 512 * MIB
MAX_CLEAN_INACTIVE_CREDIT = 256 * MIB
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
            limit = (MAX_APK if role == "baseline" else MAX_PAYLOAD if role == "validated-payload"
                     else MAX_TRANSLATIONS if role == "validated-translations"
                     else MAX_SERVER_APK if role.startswith("own-") else 64 * MIB)
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
        if (role not in PUBLIC_INPUT_HASHES and role not in ("validated-payload", "validated-translations")
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


def staging_budget(root, destination, required=None):
    required = MAX_APK_STAGING + 8 * MIB if required is None else required
    if type(required) is not int or not 0 < required <= MAX_SERVER_APK + SERVER_APK_METADATA_STAGING:
        raise ValueError("Invalid versioned server staging budget")
    if Path(root).stat().st_dev == Path(destination).stat().st_dev:
        required += MIN_ROOT_FREE
    if shutil.disk_usage(destination).free < required:
        raise ValueError("Insufficient staging space while preserving the root disk reserve")


def capacity_plan(infos, payload_bytes, replacement_sizes=None, *, translations_bytes=0):
    """Bound one full APK plus small in-place signing metadata before output.

    The baseline remains independently pinned and size-limited. ZIP sizes use
    each retained entry's original compression method, a conservative DEFLATE
    bound, explicit ZIP metadata and 1 MiB for alignment/signature growth.
    """
    if type(payload_bytes) is not int or not 0 < payload_bytes <= MAX_PAYLOAD:
        raise ValueError("Public payload exceeds the versioned size bound")
    if type(translations_bytes) is not int or not 0 <= translations_bytes <= MAX_TRANSLATIONS:
        raise ValueError("Optional translations exceed their size bound")
    if TRANSLATIONS_ASSET in infos:
        raise ValueError("Pinned baseline unexpectedly contains translations")
    sizes = {pybundle.PAYLOAD: payload_bytes, pybundle.APP: pybundle.MAX_APP,
             pybundle.BUILD: META_LIMIT, "classes2.dex": MAX_DEX,
             **{name: MIB for name in RESOURCE_NAMES}}
    if translations_bytes:
        sizes[TRANSLATIONS_ASSET] = translations_bytes
    if replacement_sizes is not None:
        if set(replacement_sizes) != set(sizes):
            raise ValueError("Replacement capacity inventory differs")
        if any(type(size) is not int or size < 0 or size > sizes[name]
               for name, size in replacement_sizes.items()):
            raise ValueError("Replacement exceeds its bounded build input")
        if replacement_sizes[pybundle.PAYLOAD] != payload_bytes:
            raise ValueError("Payload capacity differs from its validated size")
        sizes = replacement_sizes
    if not (set(sizes) - {TRANSLATIONS_ASSET}) <= infos.keys() or infos[pybundle.PAYLOAD].compress_type != 0:
        raise ValueError("Pinned server payload capacity structure differs")
    total, expanded = MIB, 0
    entries = list(infos.items())
    if translations_bytes:
        entries.append((TRANSLATIONS_ASSET, translation_asset_info()))
    for name, info in entries:
        if name in excluded_members(infos):
            continue
        size = sizes.get(name, info.file_size)
        if type(size) is not int or size < 0 or info.compress_type not in (0, 8):
            raise ValueError("Unsupported server ZIP capacity entry")
        expanded += size
        compressed = size if info.compress_type == 0 else size + (size >> 12) + (size >> 14) + (size >> 25) + 64
        # Two names/extras (local and central), comment, descriptor and ZIP64
        # allowance. The archive itself stays far below the ZIP32 size limit.
        total += compressed + 30 + 46 + 24 + 64 + 2 * (len(name.encode("utf-8")) + len(info.extra)) + len(info.comment)
    total += 22 + 65535
    maximum = ((total + MIB - 1) // MIB) * MIB
    if maximum > MAX_SERVER_APK or expanded > MAX_SERVER_EXPANDED:
        raise ValueError("Server APK exceeds the versioned capacity bound")
    return {"schema": 1, "policy": "server-library-single-apk-v2", "payload_bytes": payload_bytes,
            "apk_bytes": maximum, "expanded_bytes": expanded,
            "full_apk_copies": 1, "staging_bytes": maximum + SERVER_APK_METADATA_STAGING}


def _tmpfs(destination):
    """Identify the destination's actual Linux mount, including nested mounts."""
    target = Path(destination).resolve(strict=True)
    with Path("/proc/self/mountinfo").open("rb") as stream:
        raw = stream.read(MIB + 1)
    if len(raw) > MIB:
        raise ValueError("Mount inventory exceeds its bounded read size")
    selected = None
    for line in raw.decode("utf-8", errors="strict").splitlines():
        before, separator, after = line.partition(" - ")
        fields, tail = before.split(), after.split()
        if not separator or len(fields) < 6 or len(tail) < 3:
            raise ValueError("Invalid mount inventory")
        value = re.sub(r"\\(040|011|012|134)", lambda match: chr(int(match[1], 8)), fields[4])
        mount = Path(value)
        if target == mount or target.is_relative_to(mount):
            if selected is None or len(value) > selected[0]:
                selected = (len(value), tail[0])
    if selected is None:
        raise ValueError("Cannot identify the server staging filesystem")
    return selected[1] == "tmpfs"


def _allocation_guard(root, destination, future_bytes):
    """Reserve future server tmpfs bytes above its strict direct 512MiB floor."""
    if type(future_bytes) is not int or not 0 < future_bytes <= MAX_SERVER_APK + SERVER_APK_METADATA_STAGING:
        raise ValueError("Invalid future staging capacity")
    staging_budget(root, destination, future_bytes)
    budget = _server_stage_guard(root)
    growth = future_bytes if _tmpfs(destination) else 0
    projected = budget["memory_direct_headroom"] - growth
    if projected < SERVER_STAGE_HEADROOM:
        raise ValueError("Defer build until projected staging preserves the direct 512 MiB memory reserve")
    return {**budget, "future_staging_bytes": future_bytes, "future_tmpfs_bytes": growth,
            "projected_direct_headroom": projected, "ongoing_direct_floor": SERVER_STAGE_HEADROOM}


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


def _resource_guard(root, *, direct_floor=None):
    budget = _memory_budget()
    if direct_floor is not None:
        if direct_floor != SERVER_STAGE_HEADROOM or type(direct_floor) is not int:
            raise ValueError("Unsupported explicit server direct-memory floor")
        if budget["memory_direct_headroom"] < direct_floor:
            raise ValueError("Defer server stage until 512 MiB direct cgroup headroom is available")
    elif (budget["memory_direct_headroom"] < MIN_HEADROOM - MAX_CLEAN_INACTIVE_CREDIT
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


def _server_stage_guard(root, *, entry=False):
    budget = _resource_guard(root, direct_floor=SERVER_STAGE_HEADROOM)
    if entry and budget["memory_direct_headroom"] < MIN_HEADROOM:
        raise ValueError("Server build entry requires 1 GiB direct cgroup headroom")
    if budget["oom_kill"] != "2":
        raise ValueError("Server stage OOM baseline differs")
    return {**budget, "clean_credit_applied_to_guard": False}


def _run(command, *, root, env, timeout=180, cache=None, guard=None):
    """Bound both pipe reads and process lifetime; never print command/output."""
    if cache is not None:
        cache.advise()
    (_resource_guard if guard is None else guard)(root)
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
                         ("tools/repack_android_server_python.py", Path(pybundle.__file__)),
                         ("tools/sign_apk_v2_in_place.py", Path(__file__).with_name("sign_apk_v2_in_place.py")),
                         (PAYLOAD_INVENTORY, Path(__file__).with_name(Path(PAYLOAD_INVENTORY).name)),
                         ("src/idoly_local/media_master_build.py", Path(media_master.__file__)),
                         ("src/idoly_local/media_outfit_policy.py", Path(media_master.__file__).with_name("media_outfit_policy.py")),
                         ("src/idoly_local/bundled_translations.py", Path(translation_package.__file__))):
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
    app.set(ANDROID + "debuggable", "false")
    app.set(ANDROID + "extractNativeLibs", "true")
    if app.get(ANDROID + "allowBackup") != "false":
        raise ValueError("Server data backup policy differs")
    components = {(child.tag, child.get(ANDROID + "name")) for child in app}
    if len(app) != 2 or components != {("activity", ".MainActivity"), ("service", ".ServerService")}:
        raise ValueError("Server component inventory differs")
    permissions = [item.get(ANDROID + "name") for item in tree.findall("uses-permission")]
    if len(permissions) != len(SERVER_PERMISSIONS) or set(permissions) != SERVER_PERMISSIONS:
        raise ValueError("Server permission inventory differs; client installation is not supported")
    if tree.findall("uses-permission-sdk-23"):
        raise ValueError("Additional SDK-specific permissions are not supported")
    for child in app:
        expected = "true" if child.tag == "activity" else "false"
        if child.get(ANDROID + "exported") != expected:
            raise ValueError("Server component export policy differs")
    for child in app:
        child.set(ANDROID + "name", PACKAGE + child.get(ANDROID + "name"))
    ET.register_namespace("android", ANDROID[1:-1])
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def build_config(payload_sha256, translations_sha256="", translations_bytes=0, *, payload_bytes=0):
    if type(payload_bytes) is not int or not 0 <= payload_bytes <= MAX_PAYLOAD:
        raise ValueError("Explicit payload size is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
        raise ValueError("An explicit payload SHA-256 is required")
    if (type(translations_bytes) is not int or not 0 <= translations_bytes <= MAX_TRANSLATIONS
            or not isinstance(translations_sha256, str)
            or bool(translations_bytes) != bool(translations_sha256)
            or translations_sha256 and not re.fullmatch(r"[0-9a-f]{64}", translations_sha256)):
        raise ValueError("Explicit optional translations SHA and bytes must be supplied together")
    return ("package " + PACKAGE + ";\npublic final class BuildConfig {\n"
            ' public static final boolean DEBUG = Boolean.parseBoolean("false");\n'
            ' public static final String APPLICATION_ID = "' + PACKAGE + '";\n'
            ' public static final String BUILD_TYPE = "release";\n'
            f' public static final int VERSION_CODE = {VERSION_CODE};\n'
            f' public static final String VERSION_NAME = "{VERSION}";\n'
            f' public static final String SERVER_DATA_SHA256 = "{payload_sha256}";\n'
            f' public static final long SERVER_DATA_BYTES = {payload_bytes}L;\n'
            f' public static final String BUNDLED_TRANSLATIONS_SHA256 = "{translations_sha256}";\n'
            f' public static final long BUNDLED_TRANSLATIONS_BYTES = {translations_bytes}L;\n'
            "}\n").encode()


def dex_classes(raw, *, versions=(b"dex\n038\0",)):
    """Read bounded class definitions, not arbitrary strings/references."""
    if (len(raw) < 112 or len(raw) > MAX_DEX or raw[:8] not in versions
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
        if (len(name) != length or not re.fullmatch(r"L[A-Za-z0-9_$/-]+;", name) or name in result):
            raise ValueError("DEX class names are malformed or duplicated")
        result.add(name)
    return result


def own_synthetic(name, compiled_names):
    """Only known D8 forms derived from a real own javac class may be added."""
    if not name.startswith("L" + PACKAGE.replace(".", "/") + "/"):
        return False
    if name.endswith("-IA;"):
        # D8's init-class helper, observed for the private nested Attempt class.
        return name[:-4] + ";" in compiled_names
    match = re.fullmatch(r"(.+)\$\$ExternalSynthetic(?:Lambda|ApiModelOutline)[0-9]+;", name)
    return match is not None and match.group(1) + ";" in compiled_names


def dependency_classes(jar, baseline_dex):
    if pybundle.digest(jar) != CHAQUOPY_SHA256:
        raise ValueError("Expected the exact original public Chaquopy 17 runtime JAR")
    with ZipFile(jar) as archive:
        infos = pybundle._members(archive, 2 * MIB)
        names = {"L" + name[:-6] + ";" for name in infos if name.endswith(".class")}
    if len(names) != 27 or names != dex_classes(baseline_dex):
        raise ValueError("Chaquopy JAR and preserved dependency DEX classes differ")
    return names


def payload_directory_bounds(path):
    """Reject oversized ZIP directory allocations before constructing ZipFile."""
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if not 22 <= size <= MAX_PAYLOAD:
            raise ValueError("Public payload exceeds the versioned size bound")
        length = min(size, 22 + 65535)
        stream.seek(size - length)
        tail = stream.read(length)
        position = tail.rfind(b"PK\x05\x06")
        if position < 0 or position + 22 > len(tail):
            raise ValueError("Public payload has no complete ZIP directory")
        (_sig, disk, directory_disk, disk_count, count, directory_bytes,
         offset, comment) = struct.unpack_from("<4s4H2LH", tail, position)
        end = size - length + position
        if position + 22 + comment != len(tail) or disk or directory_disk or disk_count != count:
            raise ValueError("Public payload ZIP directory is invalid")
        if count == 65535 or directory_bytes == 0xffffffff or offset == 0xffffffff:
            if end < 20:
                raise ValueError("Public payload ZIP64 locator is invalid")
            stream.seek(end - 20)
            raw = stream.read(20)
            signature, locator_disk, record_offset, disks = struct.unpack("<4sLQL", raw)
            if signature != b"PK\x06\x07" or locator_disk or disks != 1 or record_offset + 56 > end - 20:
                raise ValueError("Public payload ZIP64 locator is invalid")
            stream.seek(record_offset)
            raw = stream.read(56)
            signature, width, _made, _needed, disk, directory_disk, disk_count, count, directory_bytes, offset = struct.unpack("<4sQ2H2L4Q", raw)
            if (signature != b"PK\x06\x06" or width < 44 or record_offset + 12 + width != end - 20
                    or disk or directory_disk or disk_count != count):
                raise ValueError("Public payload ZIP64 directory is invalid")
            end = record_offset
        if (not 0 < count <= MAX_PAYLOAD_MEMBERS or not count * 46 <= directory_bytes <= 2 * MIB
                or offset < 0 or offset + directory_bytes != end):
            raise ValueError("Public payload ZIP directory exceeds its allocation bound")
        stream.seek(offset)
        seen = 0
        while stream.tell() < end:
            fixed = stream.read(46)
            if len(fixed) != 46 or fixed[:4] != b"PK\x01\x02":
                raise ValueError("Public payload ZIP directory member is invalid")
            name_bytes, extra_bytes, comment_bytes, disk = struct.unpack_from("<4H", fixed, 28)
            seen += 1
            if (seen > count or disk or not 0 < name_bytes <= 240
                    or stream.tell() + name_bytes + extra_bytes + comment_bytes > end):
                raise ValueError("Public payload ZIP directory exceeds its allocation bound")
            stream.seek(name_bytes + extra_bytes + comment_bytes, os.SEEK_CUR)
        if seen != count or stream.tell() != end:
            raise ValueError("Public payload ZIP directory member count differs")
        return {"members": count, "central_directory_bytes": directory_bytes}


def load_payload_inventory(path=None):
    """Read the frozen catalogs and single authoritative HomeTalk addition."""
    path = _regular(Path(__file__).with_name(Path(PAYLOAD_INVENTORY).name) if path is None else path)
    if not 0 < path.stat().st_size <= META_LIMIT:
        raise ValueError("Versioned public catalog inventory exceeds its size bound")
    with path.open("rb") as stream:
        raw = stream.read(META_LIMIT + 1)
    if len(raw) > META_LIMIT:
        raise ValueError("Versioned public catalog inventory exceeds its size bound")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pybundle._json_object)
    keys = {"schema", "policy", "base_payload", "component_commit", "component_sources",
            "additions", "ios_public_files", "prebuilt_catalogs", "server_json_additions"}
    if (not isinstance(value, dict) or value.keys() != keys or type(value["schema"]) is not int
            or value["schema"] != 1 or value["policy"] != "precomputed-language-sort-v1"
            or value["base_payload"] != BASE_PUBLIC_PAYLOAD
            or not isinstance(value["component_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["component_commit"])
            or not isinstance(value["component_sources"], dict) or not value["component_sources"]
            or any(not isinstance(name, str) or not re.fullmatch(r"src/idoly_local/[a-z_]+\.py", name)
                   or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                   for name, digest in value["component_sources"].items())):
        raise ValueError("Versioned public catalog inventory identity differs")
    if not _server_json_additions_match(value["server_json_additions"]):
        raise ValueError("Versioned HomeTalk JSON inventory differs")
    additions, ios = value["additions"], value["ios_public_files"]
    if not isinstance(additions, list) or len(additions) != 262 or not isinstance(ios, list) or len(ios) != 2:
        raise ValueError("Versioned public catalog inventory count differs")
    metadata = {"data/original-master/" + name for name in ("master-sort.json", "media-master-sort.json")}
    metadata.update("data/original-master/languages/" + locale + "/" + name
        for locale in ("ko", "en") for name in ("master-tag.json", "media-master-tag.json", "coverage.json",
            "media-coverage.json", "master-sort.json", "media-master-sort.json"))
    rows = {}
    for row in additions + ios:
        if (not isinstance(row, dict) or row.keys() != {"path", "bytes", "sha256"}
                or not isinstance(row["path"], str) or row["path"] in rows
                or type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_JSON
                or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("Versioned public catalog file inventory differs")
        rows[row["path"]] = row
    if ({row["path"] for row in ios} != {"data/public-octo-ios/settings.json", "data/public-octo-ios/manifest.pb"}
            or {row["path"] for row in additions if row["path"].endswith(".json")} != metadata
            or any(row["path"] not in metadata and not re.fullmatch(
                r"data/original-master/assets/master/[A-Za-z0-9_-]+\.db", row["path"]) for row in additions)):
        raise ValueError("Versioned public catalog contains an unapproved path")
    proof = value["prebuilt_catalogs"]
    proof_keys = {"schema", "policy", "base_payload", "component_commit", "component_sources", "catalog_inventory_sha256",
                  "added_members", "sources", "coverage", "sorts", "ios_catalog_identity", "device_verified", "scope"}
    canonical = json.dumps(additions, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if (not isinstance(proof, dict) or proof.keys() != proof_keys or type(proof["schema"]) is not int or proof["schema"] != 1
            or proof["policy"] != value["policy"] or proof["base_payload"] != value["base_payload"]
            or proof["component_commit"] != value["component_commit"] or proof["component_sources"] != value["component_sources"]
            or type(proof["added_members"]) is not int or proof["added_members"] != len(additions)
            or proof["catalog_inventory_sha256"] != hashlib.sha256(canonical).hexdigest()
            or proof["device_verified"] is not False):
        raise ValueError("Versioned public catalog provenance differs")
    return value


def validate_payload(payload, expected_sha256, baseline_archive, *, catalog_inventory=None):
    """Admit only the exact prepared native payload; no legacy/hash override path."""
    pin = love_payload.load_pin()
    approved = love_payload.output_pin()
    if (type(expected_sha256) is not str or expected_sha256 != approved["sha256"]
            or payload.stat().st_size != approved["bytes"]):
        raise ValueError("Prepared latest payload pin differs")
    directory = payload_directory_bounds(payload)
    verified = love_payload.verify_payload(payload)
    names = pin["output"]["master_json_table_names"]
    if (pin["output"]["master_json_tables"] != 64 or len(names) != 64 or set(names) != LATEST_TABLES
            or verified.get("master_json_tables") != 64 or verified.get("master_json_table_names") != names):
        raise ValueError("Prepared latest payload must contain the exact 64 pinned JSON names")
    with ZipFile(payload) as archive:
        infos = pybundle._members(archive, pybundle.MAX_EXPANDED, member_limit=MAX_PAYLOAD_MEMBERS)
        actual = sorted(name[len("data/master-json/"):-5] for name in infos
                        if name.startswith("data/master-json/") and name.endswith(".json"))
        if actual != names:
            raise ValueError("Prepared latest payload JSON namespace differs")
        report = json.loads(pybundle._read(archive, infos[PAYLOAD_MANIFEST], META_LIMIT), object_pairs_hook=pybundle._json_object)
        tables = report.get("tables")
        if (type(tables) is not dict or set(tables) != set(names)-{"LoveCatalog"}
                or any(type(count) is not int or count < 0 for count in tables.values())):
            raise ValueError("Prepared latest payload raw table counts differ")
        if catalog_inventory is not None and report.get("prebuilt_catalogs") != catalog_inventory.get("prebuilt_catalogs"):
            raise ValueError("Payload versioned public catalog provenance differs")
    return {"sha256": approved["sha256"], "bytes": approved["bytes"], "tables": tables,
            "master_json_table_names": names, "members": verified["entries"], "directory": directory,
            "prebuilt_catalogs": report.get("prebuilt_catalogs"),
            "server_data_provenance": pin["upgrade_proof"]}


def _validate_legacy_base_structure(payload, expected_sha256, baseline_archive, *, catalog_inventory=None):
    """Preserve original public data and optionally add the frozen library catalog."""
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or payload.stat().st_size > MAX_PAYLOAD or pybundle.digest(payload) != expected_sha256):
        raise ValueError("Validated public payload hash differs")
    directory = payload_directory_bounds(payload)
    with baseline_archive.open(pybundle.PAYLOAD) as stream, ZipFile(stream) as old, ZipFile(payload) as new:
        old_infos = pybundle._members(old, pybundle.MAX_EXPANDED)
        infos = pybundle._members(new, pybundle.MAX_EXPANDED, member_limit=MAX_PAYLOAD_MEMBERS)
        added = {"data/master-json/" + name + ".json" for name in EXTRA_TABLES} | media_master.PAYLOAD_MEMBERS
        catalog_files = {} if catalog_inventory is None else {
            row["path"]: row for row in catalog_inventory["additions"] + catalog_inventory["ios_public_files"]}
        if set(catalog_files) & (set(old_infos) | added):
            raise ValueError("Versioned public catalogs overlap original payload members")
        added |= catalog_files.keys()
        if set(infos) != set(old_infos) | added or added & set(old_infos):
            raise ValueError("Payload may add only the fifteen named JSON tables and explicit media master files")
        old_hashes = pybundle._hash_members(old, old_infos)
        hashes = pybundle._hash_members(new, infos)
        if any(infos[name].file_size != row["bytes"] or hashes[name] != row["sha256"]
               for name, row in catalog_files.items()):
            raise ValueError("Versioned public catalog bytes differ from the source-frozen inventory")
        if catalog_inventory is not None:
            if not _server_json_additions_match(catalog_inventory.get("server_json_additions")):
                raise ValueError("Versioned HomeTalk JSON inventory differs")
            for row in SERVER_JSON_ADDITIONS:
                if infos[row["path"]].file_size != row["bytes"] or hashes[row["path"]] != row["sha256"]:
                    raise ValueError("HomeTalk JSON differs from its authoritative original projection")
        if any(hashes[name] != digest for name, digest in old_hashes.items() if name != PAYLOAD_MANIFEST):
            raise ValueError("Payload changed an existing public input")
        if any(hashes["data/master-json/" + table + ".json"] != digest
               for table, digest in ADDED_JSON_SHA256.items()):
            raise ValueError("An existing public media/company JSON table changed")
        report = json.loads(pybundle._read(new, infos[PAYLOAD_MANIFEST], META_LIMIT), object_pairs_hook=pybundle._json_object)
        old_report = json.loads(pybundle._read(old, old_infos[PAYLOAD_MANIFEST], META_LIMIT), object_pairs_hook=pybundle._json_object)
        if (not isinstance(report, dict) or {k: v for k, v in report.items() if k not in ("tables", "files", "prebuilt_catalogs")}
                != {k: v for k, v in old_report.items() if k not in ("tables", "files")}):
            raise ValueError("Payload provenance changed outside tables/files")
        if ((catalog_inventory is None and "prebuilt_catalogs" in report)
                or (catalog_inventory is not None and report.get("prebuilt_catalogs") != catalog_inventory["prebuilt_catalogs"])):
            raise ValueError("Payload versioned public catalog provenance differs")
        tables = {name[len("data/master-json/"):-5] for name in infos
                  if name.startswith("data/master-json/") and name.endswith(".json")}
        if len(tables) != 55 or not isinstance(report.get("tables"), dict) or set(report["tables"]) != tables:
            raise ValueError("Payload must contain exactly 55 public JSON tables")
        for table in tables:
            rows = json.loads(pybundle._read(new, infos["data/master-json/" + table + ".json"], MAX_JSON),
                              object_pairs_hook=pybundle._json_object)
            if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                    or type(report["tables"][table]) is not int or report["tables"][table] != len(rows)
                    or (table in EXTRA_TABLES and not rows)):
                raise ValueError("Public table counts or row structure differ")
        if report["tables"]["HomeTalk"] != SERVER_JSON_ADDITIONS[0]["rows"]:
            raise ValueError("HomeTalk row count differs from its authoritative original projection")
        files = report.get("files")
        expected = {name: {"path": name, "bytes": info.file_size, "sha256": hashes[name]}
                    for name, info in infos.items() if name != PAYLOAD_MANIFEST}
        if (not isinstance(files, list) or len(files) != len(expected)
                or any(not isinstance(row, dict) or not isinstance(row.get("path"), str) for row in files)
                or {row.get("path") for row in files} != set(expected)
                or any(row != expected[row["path"]] for row in files)):
            raise ValueError("Payload file provenance differs from actual bytes")
        original_tag = json.loads(pybundle._read(new, infos["data/original-master/master-tag.json"], META_LIMIT),
                                  object_pairs_hook=pybundle._json_object)
        media_tag = json.loads(pybundle._read(new, infos[media_master.TAG_MEMBER], META_LIMIT),
                               object_pairs_hook=pybundle._json_object)
        original_packs = media_master._tag_packs(original_tag)
        type_pack = original_packs.get("CostumeType")
        if (type_pack is None or hashes.get("data/original-master/assets/master/" + type_pack["fileName"])
                != media_master.COSTUME_TYPE_PACK_SHA256):
            raise ValueError("Original CostumeType pack differs from the audited inventory")
        rows = {table: json.loads(pybundle._read(new, infos["data/master-json/" + table + ".json"], MAX_JSON),
                                 object_pairs_hook=pybundle._json_object) for table in media_master.TABLES}
        overlay_packs = {name: {"bytes": infos[media_master.PACK_MEMBERS[table]].file_size,
                                "sha256": hashes[media_master.PACK_MEMBERS[table]]}
                         for table, name in media_master.PACK_NAMES.items()}
        overlay = media_master.validate_media_master_tag(original_tag, media_tag, report["schema_sha256"], rows,
                                                         overlay_packs)
        return {"sha256": expected_sha256, "bytes": payload.stat().st_size,
                "tables": report["tables"], "members": len(infos), "media_master_overlay": overlay,
                "directory": directory, "prebuilt_catalogs": report.get("prebuilt_catalogs")}


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


def excluded_members(infos):
    """Allow only the known old app DEX and old optional client assets to leave."""
    return REMOVED_NAMES | (LEGACY_PRESENTATION_ASSETS & infos.keys())


def _server_archive_members(infos):
    if any(name.startswith("assets/presentation/") or name.endswith(".apk") for name in infos):
        raise ValueError("Server APK must not embed client APKs or presentation installer assets")


def translation_asset_info():
    info = ZipInfo(TRANSLATIONS_ASSET, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = ZIP_STORED
    info.external_attr = 0o100600 << 16
    return info


def _stored_local_extra(info, offset, *, zip64):
    """Append a local-only alignment field; central-directory extras stay exact."""
    encoded, _flags = info._encodeFilenameFlags()
    start = offset + 30 + len(encoded) + len(info.extra) + (20 if zip64 else 0)
    if start % 4 == 0:
        return info.extra
    padding = (-(start + 6)) % 4
    return info.extra + struct.pack("<HHH", 0xD935, 2 + padding, 4) + b"\0" * padding


def stream_apk(incoming, infos, target, replacements):
    added = set(replacements) - set(infos)
    if added - {TRANSLATIONS_ASSET} or set(replacements) & excluded_members(infos):
        raise ValueError("Only existing approved server members may be replaced")
    retained = {name: info for name, info in infos.items() if name not in excluded_members(infos)}
    _server_archive_members(retained)
    with ZipFile(target, "x") as outgoing:
        outgoing.comment = incoming.comment
        entries = list(retained.items()) + [(name, translation_asset_info()) for name in sorted(added)]
        for name, info in entries:
            copied = copy.copy(info)
            replacement = replacements.get(name)
            copied.file_size = (len(replacement) if isinstance(replacement, bytes) else
                                replacement.stat().st_size if isinstance(replacement, Path) else info.file_size)
            if type(copied.file_size) is not int or not 0 <= copied.file_size <= MAX_SERVER_EXPANDED:
                raise ValueError("Streamed server member exceeds its ordinary ZIP size bound")
            if copied.compress_type == ZIP_STORED:
                copied.extra = _stored_local_extra(copied, outgoing.fp.tell(), zip64=False)
            with outgoing.open(copied, "w", force_zip64=False) as dst:
                if isinstance(replacement, bytes):
                    dst.write(replacement)
                else:
                    src = replacement.open("rb") if isinstance(replacement, Path) else incoming.open(info)
                    with src:
                        shutil.copyfileobj(src, dst, pybundle.CHUNK)
            copied.external_attr = info.external_attr
            copied.extra = info.extra


def audit_apk(path, before, before_infos, replacement_hashes, dependency_names, compiled_names):
    with ZipFile(path) as archive:
        infos = pybundle._members(archive, MAX_SERVER_EXPANDED)
        _server_archive_members(infos)
        removed = excluded_members(before_infos)
        added = set(replacement_hashes) - set(before)
        if added - {TRANSLATIONS_ASSET} or set(infos) != (set(before) - removed) | added:
            raise ValueError("APK member inventory differs")
        hashes = pybundle._hash_members(archive, infos)
        for name in infos:
            expected = replacement_hashes[name] if name in replacement_hashes else before[name]
            if hashes[name] != expected:
                raise ValueError("APK member differs from its approved input")
            expected_info = translation_asset_info() if name in added else before_infos[name]
            if any(getattr(infos[name], key) != getattr(expected_info, key)
                   for key in ("date_time", "compress_type", "external_attr", "comment", "extra")):
                raise ValueError("APK member metadata changed")
        if dex_classes(pybundle._read(archive, infos["classes.dex"], MAX_DEX)) != dependency_names:
            raise ValueError("Preserved dependency class inventory differs")
        own_raw = pybundle._read(archive, infos["classes2.dex"], MAX_DEX)
        if any(token in own_raw for token in FORBIDDEN_INSTALLER_DEX_TOKENS):
            raise ValueError("Server own DEX still contains removed client installer code")
        own = dex_classes(own_raw)
        if (not compiled_names <= own or own & dependency_names
                or any(not own_synthetic(name, compiled_names) for name in own - compiled_names)):
            raise ValueError("Own DEX classes differ from compiler inputs/synthetics")
        if {name for name in infos if name.startswith("lib/")} != NATIVE_NAMES:
            raise ValueError("Native library inventory differs")
        elf = {name: elf_alignment(pybundle._read(archive, infos[name], 16 * MIB)) for name in NATIVE_NAMES}
        return {"changed_apk_members": sorted(name for name in infos if name in before and hashes[name] != before[name]),
                "added_apk_members": sorted(added), "removed_apk_members": sorted(set(before) & removed),
                "own_dex_classes": sorted(own), "client_installer_code_absent": True,
                "embedded_client_apks_absent": True,
                "dependency_dex_classes": sorted(dependency_names), "native_elf_load_alignments": elf,
                "all_other_member_bytes_and_metadata_preserved": True}


def _identity(badging, manifest):
    if (f"package: name='{PACKAGE}' versionCode='{VERSION_CODE}' versionName='{VERSION}'" not in badging
            or "sdkVersion:'26'" not in badging or "targetSdkVersion:'34'" not in badging
            or "native-code: 'arm64-v8a'" not in badging
            or not re.search(r":extractNativeLibs\([^)]*\)=true\b", manifest)
            or not re.search(r":debuggable\([^)]*\)=false\b", manifest)
            or not re.search(r":allowBackup\([^)]*\)=false\b", manifest)):
        raise ValueError("Linked APK identity, SDK or native extraction policy differs")
    permissions = re.findall(r"^uses-permission: name='([^']+)'", badging, re.M)
    if (len(permissions) != len(SERVER_PERMISSIONS) or set(permissions) != SERVER_PERMISSIONS
            or "REQUEST_INSTALL_PACKAGES" in manifest or "PresentationInstallActivity" in manifest):
        raise ValueError("Linked server APK retains an unexpected permission or installer component")


def build(args):
    pybundle._compiler()
    os.nice(19)
    os.umask(0o077)
    root = Path(args.source_root).resolve(strict=True)
    baseline, payload = _regular(args.baseline), _regular(args.payload)
    optional_values = tuple(getattr(args, name, None) for name in
                            ("translations", "translations_sha256", "translations_bytes"))
    translations = None
    translations_sha256, translations_bytes = "", 0
    if any(value is not None for value in optional_values):
        if (any(value is None for value in optional_values) or not isinstance(optional_values[1], str)
                or not re.fullmatch(r"[0-9a-f]{64}", optional_values[1])
                or type(optional_values[2]) is not int or not 0 < optional_values[2] <= MAX_TRANSLATIONS):
            raise ValueError("Optional translations require explicit path, SHA and bytes together")
        translations = _regular(optional_values[0])
        translations_sha256, translations_bytes = optional_values[1:]
        if translations.stat().st_size != translations_bytes:
            raise ValueError("Optional translation ZIP size differs")
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
    cache.advise()
    preflight = _server_stage_guard(root, entry=True)
    sources = pybundle.committed_sources(root, args.source_commit)
    native_sources = source_blobs(root, args.source_commit)
    builder_sources = tool_sources(root, args.source_commit)
    epoch = pybundle._git(root, "show", "-s", "--format=%ct", args.source_commit, limit=32).strip()
    validate_epoch(epoch, args.epoch)
    jdk, sdk, android = Path(args.jdk_bin).resolve(strict=True), Path(args.build_tools).resolve(strict=True), _regular(args.android_jar)
    in_place_signer = _regular(Path(__file__).with_name("sign_apk_v2_in_place.py"))
    signer_python = _regular(Path("/usr/bin/python3").resolve(strict=True))
    tools = [jdk / "java", jdk / "javac", jdk / "keytool", sdk / "aapt2", sdk / "zipalign",
             sdk / "lib/d8.jar", sdk / "lib/apksigner.jar", android, signer_python, in_place_signer]
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
        planned_capacity = capacity_plan(infos, payload.stat().st_size, translations_bytes=translations_bytes)
        capacity_preflight = _allocation_guard(root, output.parent, planned_capacity["staging_bytes"])
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
        payload_report = validate_payload(payload, args.payload_sha256, incoming,
                                          catalog_inventory=load_payload_inventory())
        cache.public("validated-payload", payload, args.payload_sha256)
        translation_report = {"included": False}
        if translations is not None:
            translation_report = {"included": True, **translation_package.validate_translation_bundle(
                translations, expected_sha256=translations_sha256, expected_bytes=translations_bytes,
                platform="android")}
            cache.public("validated-translations", translations, translations_sha256)
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
        config.write_bytes(build_config(args.payload_sha256, translations_sha256, translations_bytes, payload_bytes=payload.stat().st_size))
        def run(command):
            return _run(command, root=root, env=env, cache=cache, guard=_server_stage_guard)
        compiled_res, resources = work / "compiled-res.zip", work / "resources.apk"
        run([sdk / "aapt2", "compile", "--dir", work / "source" / RES_ROOT, "-o", compiled_res])
        run([sdk / "aapt2", "link", "-I", android, "--manifest", manifest, "--java", generated,
             "--non-final-ids", "--min-sdk-version", "26", "--target-sdk-version", "34",
             "--version-code", str(VERSION_CODE), "--version-name", VERSION, "-o", resources, compiled_res])
        r_sources = sorted(generated.rglob("R.java"))
        if len(r_sources) != 1 or r_sources[0].relative_to(generated).as_posix() != PACKAGE.replace(".", "/") + "/R.java":
            raise ValueError("aapt2 generated unexpected R source")
        run([jdk / "javac", *("-J" + flag for flag in JAVA_FLAGS), "--release", "17", "-parameters", "-encoding", "UTF-8",
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
        if translations is not None:
            replacements[TRANSLATIONS_ASSET] = translations
        replacement_hashes = {name: pybundle.digest(value) if isinstance(value, Path) else hashlib.sha256(value).hexdigest()
                              for name, value in replacements.items()}
        # The supplied validated hash, rather than a second mutable-path read,
        # remains the authority if the payload file changes concurrently.
        replacement_hashes[pybundle.PAYLOAD] = args.payload_sha256
        if translations is not None:
            replacement_hashes[TRANSLATIONS_ASSET] = translations_sha256
        unsigned, aligned, signed = work / "unsigned.apk", work / "aligned.apk", work / "signed.apk"
        actual_capacity = capacity_plan(infos, payload_report["bytes"], {
            name: value.stat().st_size if isinstance(value, Path) else len(value)
            for name, value in replacements.items()}, translations_bytes=translations_bytes)
        maximum = actual_capacity["apk_bytes"]
        cache.advise()
        _allocation_guard(root, output.parent, maximum + SERVER_APK_METADATA_STAGING)
        stream_apk(incoming, infos, unsigned, replacements)
        if not 0 < unsigned.stat().st_size <= maximum:
            raise ValueError("Unsigned server APK exceeded its calculated capacity")
        audit_apk(unsigned, before, infos, replacement_hashes, dependencies, compiled_names)
        cache.completed_apk("unsigned.apk")
        cache.advise()
        unsigned.rename(aligned)
        if not 0 < aligned.stat().st_size <= maximum:
            raise ValueError("Aligned server APK exceeded its calculated capacity")
        cache.completed_apk("aligned.apk")
        run([sdk / "zipalign", "-c", "4", aligned])
        cache.advise()
        _allocation_guard(root, output.parent, SERVER_APK_METADATA_STAGING)
        aligned.rename(signed)
        env["IDOLY_MANUAL_SERVER_PASSWORD"] = read_password(password_file)
        env["IDOLY_MANUAL_SERVER_KEYSTORE"] = str(keystore)
        try:
            signer = [jdk / "java", *JAVA_FLAGS, "-jar", sdk / "lib/apksigner.jar"]
            run([signer_python, "-B", in_place_signer, "--apk", signed,
                 "--keystore-env", "IDOLY_MANUAL_SERVER_KEYSTORE", "--key-alias", args.key_alias,
                 "--password-env", "IDOLY_MANUAL_SERVER_PASSWORD", "--keytool", jdk / "keytool",
                 "--expected-certificate-sha256", CERTIFICATE])
        finally:
            env.pop("IDOLY_MANUAL_SERVER_PASSWORD", None)
            env.pop("IDOLY_MANUAL_SERVER_KEYSTORE", None)
        if not 0 < signed.stat().st_size <= maximum:
            raise ValueError("Signed server APK exceeded its calculated capacity")
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
                or pybundle.digest(stable_jar) != CHAQUOPY_SHA256
                or pybundle.digest(in_place_signer) != builder_sources["tools/sign_apk_v2_in_place.py"]
                or translations is not None and pybundle.digest(translations) != translations_sha256):
            raise ValueError("A frozen build input changed during packaging")
        signed_sha256 = pybundle.digest(signed)
        cache.advise()
        postflight = _server_stage_guard(root)
        if postflight["oom_kill"] != preflight["oom_kill"]:
            raise ValueError("An OOM occurred during the build; candidate not published")
        report = {"schema": 1, "build_method": "cached manual aapt2/javac/D8; no Gradle, Go or downloads",
                  "source_commit": args.source_commit, "epoch": args.epoch, "version_name": VERSION,
                  "version_code": VERSION_CODE, "baseline_sha256": pybundle.BASELINE_SHA256,
                  "apk_sha256": signed_sha256, "apk_bytes": signed.stat().st_size,
                  "signer_sha256": CERTIFICATE, "signature_v2_only": True, "aligned": True,
                  "payload": payload_report, "translations": translation_report,
                  "chaquopy_jar_sha256": CHAQUOPY_SHA256,
                  "client_distribution": "separate_apk_only", "debuggable": False,
                  "generated_r_sha256": pybundle.digest(r_sources[0]), "build_config_sha256": pybundle.digest(config),
                  "public_source_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in native_sources.items()},
                  "builder_source_sha256": builder_sources,
                  "modules": modules, "app_imy_sha1": hashlib.sha1(app).hexdigest(), "audit": audit,
                  "tool_sha256": tool_hashes, "public_cache_advice": cache.events,
                  "java_flags": JAVA_FLAGS, "preflight": preflight, "postflight": postflight,
                  "server_memory_profile": {"entry_direct_bytes": MIN_HEADROOM,
                                            "ongoing_direct_bytes": SERVER_STAGE_HEADROOM,
                                            "clean_credit_applied": False},
                  "capacity": {"planned": planned_capacity, "actual": actual_capacity,
                               "preflight": capacity_preflight},
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
    parser.add_argument("--translations", help="Optional separately prepared Android translation ZIP")
    parser.add_argument("--translations-sha256", help="Explicit SHA-256 of the optional translation ZIP")
    parser.add_argument("--translations-bytes", type=int, help="Exact size of the optional translation ZIP")
    args = parser.parse_args(argv)
    try:
        report = build(args)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, SyntaxError, EOFError,
            BadZipFile, ET.ParseError, subprocess.SubprocessError):
        raise SystemExit("Manual server build failed; existing inputs preserved and tool output withheld") from None
    print(json.dumps({key: report[key] for key in ("source_commit", "apk_sha256", "apk_bytes", "signer_sha256")}, indent=2))


if __name__ == "__main__":
    main()
