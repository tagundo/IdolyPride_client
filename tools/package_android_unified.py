#!/usr/bin/env python3
"""Build an internal, same-UID Android server/game integration candidate.

This deliberately requires --prototype. API 30 public resource loaders
are used for the server's separate 0x7e table; Android 9/10 and selectable Unity
Data selection still needs device verification. No account data or official service is read.
The installed game's 0x7f table, SDK code and Data stay intact. The optional
source-bound presentation addon is the only native member that may be replaced.
Run with CPython 3.13 to compile the current server Python sources.
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
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

if __package__:
    from . import repack_android_server_python as pybundle
else:
    import repack_android_server_python as pybundle

PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
SERVER_PACKAGE = "game.qualiarts.idolypride.localserver"
ORIGINAL_ACTIVITY = "com.google.firebase.MessagingUnityPlayerActivity"
GAME_ACTIVITY = SERVER_PACKAGE + ".UnifiedGameActivity"
MENU_ACTIVITY = SERVER_PACKAGE + ".MainActivity"
COMPONENT_FACTORY = SERVER_PACKAGE + ".UnifiedComponentFactory"
SERVICE = SERVER_PACKAGE + ".ServerService"
ANDROID = "{http://schemas.android.com/apk/res/android}"
JAVA_ROOT = "android-server/app/src/main/java/"
UNIFIED_JAVA_ROOT = "android-unified/src/main/java/"
RES_ROOT = "android-server/app/src/main/res/"
SERVER_MANIFEST = "android-server/app/src/main/AndroidManifest.xml"
MARKER = "assets/idoly-unified.json"
RESOURCES_ASSET = "assets/idoly-unified/server-resources.apk"
OWN_BRIDGE = "lib/arm64-v8a/libidoly_presentation.so"
CLIENT_SHA256 = "f2b4555f2b56f5f388104a2e13a8cf0d50e3ffef3fca05d85281658d5a7366ae"
SERVER_SHA256 = "fc75a864d0b9306883439916c4a8df272ec7e8ff8d53dfa09e5ce594888b75b2"
CHAQUOPY_SHA256 = "04eed6260e65634ac1c2031d2ca8fdf90d58da226b2f070132a66c6e3af9e39b"
EDITOR_SHA256 = "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"
CERTIFICATE = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
SERVER_ASSETS = {
    "assets/ServerData.zip": (198675046, "3ea45bd9fba07d35cf366d50e8bc7604aeb67ea0aa1cd55f751474a75724dbce"),
    "assets/bundledTranslations.zip": (125709184, "22c166ffc3bbbc9e38739cea21fbfd7a87436a166ed56cdb7ee650acfc222dec"),
    "assets/startupTranslations.zip": (10397063, "4782b361a388c367c5700c5de196b591286a7677dd4a64f5479f2247c5c48d5a"),
}
MIB = 1024 * 1024
CHUNK = 256 * 1024
MAX_APK = 768 * MIB
MAX_EXPANDED = 1536 * MIB
JAVA_FLAGS = ("-Xmx512m", "-XX:MaxMetaspaceSize=256m", "-XX:ReservedCodeCacheSize=64m",
              "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1")
ET.register_namespace("android", ANDROID[1:-1])
WINDOW_CONFIG_CHANGES = ("orientation", "screenLayout", "screenSize", "smallestScreenSize", "density", "colorMode")


def allow_window_resizing(node):
    """Opt into real window bounds, including cover/inner-display transitions."""
    node.set(ANDROID + "resizeableActivity", "true")
    for name in ("maxAspectRatio", "minAspectRatio"):
        node.attrib.pop(ANDROID + name, None)
    for metadata in list(node.findall("meta-data")):
        if metadata.get(ANDROID + "name") == "android.max_aspect":
            node.remove(metadata)


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def regular(path, maximum=MAX_APK):
    path = Path(path).absolute()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
        raise ValueError("Expected a bounded regular input file")
    return path


def signature_member(name):
    upper = name.upper()
    return upper == "META-INF/MANIFEST.MF" or (upper.startswith("META-INF/")
        and upper.count("/") == 1 and upper.endswith((".SF", ".RSA", ".DSA", ".EC")))


def inventory(archive):
    infos = archive.infolist()
    if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_EXPANDED:
        raise ValueError("APK inventory exceeds bounds")
    seen, folded = {}, set()
    for info in infos:
        name, mode = info.filename, info.external_attr >> 16
        parts = name.rstrip("/").split("/")
        if (not name or len(name.encode()) > 512 or name in seen or name.casefold() in folded
                or name.startswith("/") or "\\" in name or "\0" in name
                or any(p in ("", ".", "..") or ":" in p for p in parts)
                or stat.S_ISLNK(mode) or info.flag_bits & 1
                or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                or info.file_size > 384 * MIB):
            raise ValueError("Unsafe, duplicate or unsupported APK member")
        seen[name] = info
        folded.add(name.casefold())
    return seen


def read(archive, name, maximum):
    info = archive.getinfo(name)
    if info.file_size > maximum:
        raise ValueError("APK member exceeds read bound")
    with archive.open(info) as source:
        raw = source.read(maximum + 1)
    if len(raw) != info.file_size:
        raise ValueError("APK member changed size")
    return raw


def member_hash(archive, name):
    with archive.open(name) as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def dex_classes(raw):
    """Return class definitions, rather than strings mentioning a class."""
    if (not 112 <= len(raw) <= 32 * MIB or raw[:8] not in
            (b"dex\n035\0", b"dex\n037\0", b"dex\n038\0", b"dex\n039\0")
            or struct.unpack_from("<III", raw, 32) != (len(raw), 112, 0x12345678)
            or hashlib.sha1(raw[32:]).digest() != raw[12:32]
            or zlib.adler32(raw[12:]) & 0xffffffff != struct.unpack_from("<I", raw, 8)[0]):
        raise ValueError("DEX header or checksum differs")
    def table(at, width, maximum):
        count, offset = struct.unpack_from("<II", raw, at)
        if (count > maximum or offset % 4 or offset + count * width > len(raw)
                or count and offset < 112):
            raise ValueError("DEX table outside bounds")
        return count, offset
    strings, string_offset = table(56, 4, 1000000)
    types, type_offset = table(64, 4, 65535)
    count, class_offset = table(96, 32, 65535)
    result = set()
    for index in range(count):
        type_index = struct.unpack_from("<I", raw, class_offset + index * 32)[0]
        if type_index >= types:
            raise ValueError("Invalid DEX class type")
        string_index = struct.unpack_from("<I", raw, type_offset + type_index * 4)[0]
        if string_index >= strings:
            raise ValueError("Invalid DEX class name")
        offset = struct.unpack_from("<I", raw, string_offset + string_index * 4)[0]
        length = 0
        for shift in range(0, 35, 7):
            if offset >= len(raw):
                raise ValueError("Truncated DEX class name")
            value = raw[offset]
            offset += 1
            length |= (value & 127) << shift
            if not value & 128:
                break
        else:
            raise ValueError("Malformed DEX length")
        end = raw.find(b"\0", offset, min(len(raw), offset + 512))
        name = raw[offset:end].decode("ascii") if end >= 0 else ""
        if len(name) != length or not re.fullmatch(r"L[A-Za-z0-9_$/-]+;", name) or name in result:
            raise ValueError("Malformed or duplicate DEX definition")
        result.add(name)
    return result


def next_dex_name(names):
    numbers = []
    for name in names:
        if match := re.fullmatch(r"classes([0-9]+)?\.dex", name):
            number = int(match[1] or 1)
            if match[1] is not None and (number < 2 or str(number) != match[1]):
                raise ValueError("Invalid DEX index")
            numbers.append(number)
    if not numbers or sorted(numbers) != list(range(1, max(numbers) + 1)):
        raise ValueError("Base APK has noncontiguous DEX indices")
    return "classes" + str(max(numbers) + 1) + ".dex"


def transform_manifest(raw):
    """Keep SDK declarations and the old Unity component as an intent alias."""
    if len(raw) > 512 * 1024 or b"<!" in raw:
        raise ValueError("Unexpected manifest XML")
    tree = ET.fromstring(raw)
    if (tree.tag != "manifest" or tree.get("package") != PACKAGE
            or tree.get(ANDROID + "versionCode") != "414"
            or tree.get(ANDROID + "versionName") != "6.1.1"):
        raise ValueError("Unexpected original package/version")
    apps, sdks = tree.findall("application"), tree.findall("uses-sdk")
    if len(apps) != 1 or len(sdks) != 1 or sdks[0].get(ANDROID + "minSdkVersion") != "28":
        raise ValueError("Unexpected original application/SDK structure")
    app = apps[0]
    if app.get(ANDROID + "name") is not None or app.get(ANDROID + "process") is not None:
        raise ValueError("Unexpected custom game application/process")
    if app.get(ANDROID + "appComponentFactory") != "androidx.core.app.CoreComponentFactory":
        raise ValueError("Unexpected original app component factory")
    app.set(ANDROID + "appComponentFactory", COMPONENT_FACTORY)
    if any(node.get(ANDROID + "process") is not None for node in app):
        raise ValueError("Unexpected game component process")
    games = [node for node in app.findall("activity") if node.get(ANDROID + "name") == ORIGINAL_ACTIVITY]
    existing = {node.get(ANDROID + "name") for node in app}
    if len(games) != 1 or {MENU_ACTIVITY, GAME_ACTIVITY, SERVICE} & existing:
        raise ValueError("Unity activity missing or unified components already present")
    game = games[0]
    launchers = [f for node in app for f in node.findall("intent-filter")
                 if any(c.get(ANDROID + "name") == "android.intent.category.LAUNCHER" for c in f.findall("category"))]
    if len(launchers) != 1 or launchers[0] not in list(game):
        raise ValueError("Expected the one original game launcher")
    if game.get(ANDROID + "exported") != "true" or game.get(ANDROID + "launchMode") != "singleTask":
        raise ValueError("Unexpected Unity lifecycle attributes")
    # Target is real Activity: all Unity lifecycle/meta-data attributes remain here.
    game.set(ANDROID + "name", GAME_ACTIVITY)
    game.set(ANDROID + "exported", "false")
    # The stock game explicitly disables resize both here and on application.
    # Android 16's large-screen override exempts game-category apps, so both
    # declarations must opt in. Keep all original Unity configuration handlers.
    allow_window_resizing(app)
    allow_window_resizing(game)
    changes = game.get(ANDROID + "configChanges", "").split("|")
    changes = [value for value in changes if value]
    for value in WINDOW_CONFIG_CHANGES:
        if value not in changes:
            changes.append(value)
    game.set(ANDROID + "configChanges", "|".join(changes))
    alias_attrs = {ANDROID + "name": ORIGINAL_ACTIVITY, ANDROID + "targetActivity": MENU_ACTIVITY,
                   ANDROID + "exported": "true"}
    if game.get(ANDROID + "permission") is not None:
        alias_attrs[ANDROID + "permission"] = game.get(ANDROID + "permission")
    alias = ET.Element("activity-alias", alias_attrs)
    for intent in list(game.findall("intent-filter")):
        game.remove(intent)
        if intent is not launchers[0]:
            alias.append(intent)
    menu = ET.SubElement(app, "activity", {ANDROID + "name": MENU_ACTIVITY,
        ANDROID + "exported": "true", ANDROID + "resizeableActivity": "true",
        ANDROID + "theme": "@android:style/Theme.Material.Light.NoActionBar"})
    intent = ET.SubElement(menu, "intent-filter")
    ET.SubElement(intent, "action", {ANDROID + "name": "android.intent.action.MAIN"})
    ET.SubElement(intent, "category", {ANDROID + "name": "android.intent.category.LAUNCHER"})
    # An alias target must precede the alias. SDK deep links/notifications enter
    # the same server-first preparation path as an ordinary app-icon launch.
    app.append(alias)
    ET.SubElement(app, "service", {ANDROID + "name": SERVICE, ANDROID + "exported": "false",
        ANDROID + "foregroundServiceType": "dataSync"})
    permissions = {p.get(ANDROID + "name") for p in tree.findall("uses-permission")}
    for value in ("android.permission.FOREGROUND_SERVICE", "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
                  "android.permission.POST_NOTIFICATIONS", "android.permission.MANAGE_EXTERNAL_STORAGE"):
        if value not in permissions:
            tree.insert(list(tree).index(app), ET.Element("uses-permission", {ANDROID + "name": value}))
    # Native Chaquopy libraries are found through applicationInfo.nativeLibraryDir.
    app.set(ANDROID + "extractNativeLibs", "true")
    sdks[0].set(ANDROID + "minSdkVersion", "30")
    ET.indent(tree)
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def windowing_policy(raw):
    """Read the compiled manifest back instead of trusting the input XML flags."""
    tree = ET.fromstring(raw)
    app = tree.find("application")
    if app is None or app.get(ANDROID + "resizeableActivity") != "true":
        raise ValueError("Application window resizing is not enabled")
    activities = {n.get(ANDROID + "name"): n for n in app.findall("activity")}
    game, menu = activities.get(GAME_ACTIVITY), activities.get(MENU_ACTIVITY)
    if game is None or menu is None or any(n.get(ANDROID + "resizeableActivity") != "true" for n in (game, menu)):
        raise ValueError("Game/menu window resizing is not enabled")
    changes = sorted(set(game.get(ANDROID + "configChanges", "").split("|")))
    if not set(WINDOW_CONFIG_CHANGES) <= set(changes):
        raise ValueError("Fold configuration handling is missing")
    for node in (app, game):
        if any(node.get(ANDROID + key) is not None for key in ("minAspectRatio", "maxAspectRatio")):
            raise ValueError("Window aspect ratio remains restricted")
        if any(n.get(ANDROID + "name") == "android.max_aspect" for n in node.findall("meta-data")):
            raise ValueError("Legacy window aspect ratio remains restricted")
    if menu.get(ANDROID + "configChanges") is not None:
        raise ValueError("Native menu must recreate its responsive layout")
    return {"application_resizable": True, "game_resizable": True, "menu_resizable": True,
            "game_config_changes": changes, "game_orientation": game.get(ANDROID + "screenOrientation"),
            "menu_configuration_handling": "recreate_with_saved_state", "aspect_ratio_restricted": False}


def server_members(infos):
    """Only runtime assets/native dependencies enter the original client."""
    result = set()
    for name in infos:
        if name.startswith("assets/") or name.startswith("lib/arm64-v8a/"):
            if name.startswith("assets/presentation/"):
                raise ValueError("Server contains legacy installer assets")
            result.add(name)
        elif name.startswith("lib/"):
            raise ValueError("Prototype server ABI differs")
    if not set(SERVER_ASSETS) | {pybundle.APP, pybundle.BUILD} <= result:
        raise ValueError("Server runtime assets missing")
    return result


def validate_merge(client_names, server_names, additions):
    """Never overwrite a game's existing member except its manifest."""
    game = set(client_names) - {n for n in client_names if signature_member(n)}
    names = set(server_names)
    if game & names or game & set(additions) or names & set(additions):
        raise ValueError("Unified package member collision")
    if MARKER not in additions or RESOURCES_ASSET not in additions:
        raise ValueError("Unified package marker/resource pack missing")


def source_snapshot(root, commit, allow_working):
    """Fixed source roots only; bind every compiled input in the build report."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected full source commit")
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], timeout=10).decode().strip()
    if actual != commit:
        raise ValueError("Source commit differs from current checkout")
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], timeout=10)
    if status and not allow_working:
        raise ValueError("Source checkout must be clean unless explicitly building a working-tree prototype")
    blobs, py_sources = {}, {}
    roots = ((JAVA_ROOT, ".java"), (UNIFIED_JAVA_ROOT, ".java"), (RES_ROOT, ".xml"), ("src/idoly_local/", ".py"),
             ("android-server/app/src/main/python/", ".py"))
    for prefix, suffix in roots:
        for path in sorted((root / prefix).rglob("*" + suffix)):
            regular(path, 2 * MIB)
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("Source file leaves the fixed checkout")
            name, raw = path.relative_to(root).as_posix(), path.read_bytes()
            blobs[name] = raw
            if suffix == ".py":
                relative = path.relative_to(root / prefix).as_posix().removesuffix(".py") + ".pyc"
                member = ("idoly_local/" if prefix == "src/idoly_local/" else "") + relative
                if member in py_sources:
                    raise ValueError("Python source namespace collision")
                py_sources[member] = (name, raw)
    for name in (SERVER_MANIFEST, "android-server/app/build.gradle.kts",
                 "tools/package_android_unified.py", "tools/build_android_language_data.py"):
        blobs[name] = regular(root / name, MIB).read_bytes()
    if len(blobs) > 1024 or sum(map(len, blobs.values())) > 16 * MIB:
        raise ValueError("Source snapshot exceeds bounds")
    return blobs, py_sources, bool(status)


def build_config(asset_info):
    gradle_version = '2026.11.20.1-unified-preview'
    fields = ['package ' + SERVER_PACKAGE + ';', 'public final class BuildConfig {',
        'public static final boolean DEBUG = false;',
        'public static final String APPLICATION_ID = "' + PACKAGE + '";',
        'public static final String BUILD_TYPE = "release";',
        'public static final int VERSION_CODE = 55;',
        'public static final String VERSION_NAME = "' + gradle_version + '";']
    for prefix, member in (("SERVER_DATA", "assets/ServerData.zip"),
            ("BUNDLED_TRANSLATIONS", "assets/bundledTranslations.zip"),
            ("STARTUP_TRANSLATIONS", "assets/startupTranslations.zip")):
        size, digest = asset_info[member]
        fields.extend((f'public static final String {prefix}_SHA256 = "{digest}";',
                       f'public static final long {prefix}_BYTES = {size}L;'))
    return ("\n".join(fields) + "\n}\n").encode()


def validate_native_bridge(library, receipt_path, root, commit):
    """Only the independently owned addon may change; never Unity/IL2CPP/SDKs."""
    library, receipt_path = regular(library, 8 * MIB), regular(receipt_path, MIB)
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt.get("schema") != 1 or receipt.get("source_commit") != commit
            or receipt.get("abi") != "arm64-v8a" or receipt.get("bytes") != library.stat().st_size
            or receipt.get("sha256") != sha256(library)
            or receipt.get("source_unchanged_during_build") is not True):
        raise ValueError("Native addon build receipt identity differs")
    sources = receipt.get("source_sha256")
    if (not isinstance(sources, dict) or not 2 <= len(sources) <= 64
            or "client-presentation/native/bridge.cpp" not in sources
            or "client-presentation/native/profile.json" not in sources):
        raise ValueError("Native addon source receipt is incomplete")
    for name, digest in sources.items():
        if (not isinstance(name, str) or not (name.startswith("client-presentation/native/")
                or name == "android-diagnostics/native/build_native.py")
                or any(part in ("", ".", "..") for part in name.split("/"))
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Native addon source receipt path is invalid")
        path = regular(root / name, 2 * MIB)
        if not path.resolve(strict=True).is_relative_to(root) or sha256(path) != digest:
            raise ValueError("Native addon source differs from current snapshot")
    raw = library.read_bytes()
    if (len(raw) < 64 or raw[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<HHI", raw, 16) != (3, 183, 1)):
        raise ValueError("Native addon is not an arm64 shared ELF")
    offset = struct.unpack_from("<Q", raw, 32)[0]
    width, count = struct.unpack_from("<HH", raw, 54)
    if width != 56 or not 1 <= count <= 64 or offset + count * width > len(raw):
        raise ValueError("Native addon program headers are invalid")
    loads = 0
    for index in range(count):
        at = offset + index * width
        if struct.unpack_from("<I", raw, at)[0] == 1:
            file_offset, virtual = struct.unpack_from("<QQ", raw, at + 8)
            alignment = struct.unpack_from("<Q", raw, at + 48)[0]
            if alignment < 16384 or alignment & (alignment - 1) or (virtual - file_offset) % 16384:
                raise ValueError("Native addon load segment is not16KiB compatible")
            loads += 1
    if not loads:
        raise ValueError("Native addon has no loadable segments")
    return raw, receipt


def _oom_count():
    path = Path("/sys/fs/cgroup/memory.events")
    return dict(line.split() for line in path.read_text().splitlines()).get("oom_kill", "0") if path.exists() else "0"


def preflight(parent, baseline_oom):
    available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    cgroup = Path("/sys/fs/cgroup")
    if (cgroup / "memory.max").exists():
        maximum = (cgroup / "memory.max").read_text().strip()
        if maximum != "max":
            available = min(available, int(maximum) - int((cgroup / "memory.current").read_text()))
    if shutil.disk_usage(parent).free < 4 * 1024 * MIB or available < 2 * 1024 * MIB:
        raise ValueError("Build needs 4 GiB free disk and 2 GiB available memory")
    if _oom_count() != baseline_oom:
        raise ValueError("OOM kill count changed during build")


def run(command, env, *, timeout=180):
    # Logs are bounded and kept private: SDK tools can emit whole resource trees.
    with tempfile.TemporaryFile() as log:
        process = subprocess.run([str(x) for x in command], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout)
        log.seek(0, os.SEEK_END)
        length = log.tell()
        log.seek(max(0, length - 8192))
        tail = log.read().decode("utf-8", "replace")
    if process.returncode:
        raise ValueError("Build command failed: " + Path(str(command[0])).name + "\n" + tail)
    return tail


def build_resources(work, blobs, tools, env):
    source, generated = work / "source", work / "generated"
    for name, raw in blobs.items():
        if name.startswith((JAVA_ROOT, UNIFIED_JAVA_ROOT, RES_ROOT)):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    generated.mkdir()
    manifest = work / "server-manifest.xml"
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="'
        + SERVER_PACKAGE + '"><uses-sdk android:minSdkVersion="30" android:targetSdkVersion="34"/>'
        '<application android:label="@string/app_name"/></manifest>')
    compiled, resources = work / "server-compiled.zip", work / "server-resources.apk"
    run([tools["aapt2"], "compile", "--dir", source / RES_ROOT, "-o", compiled], env)
    run([tools["aapt2"], "link", "-I", tools["android"], "--manifest", manifest, "--java", generated,
         "--non-final-ids", "--package-id", "0x7e", "--allow-reserved-package-id", "--min-sdk-version", "30",
         "--target-sdk-version", "34", "-o", resources, compiled], env)
    r = generated / SERVER_PACKAGE.replace(".", "/") / "R.java"
    text = r.read_text()
    ids = re.findall(r"=\s*(0x[0-9a-fA-F]+);", text)
    if not ids or any(int(value, 16) >> 24 != 0x7e for value in ids):
        raise ValueError("Server R IDs are not isolated in package0x7e")
    if resources.stat().st_size > 4 * MIB:
        raise ValueError("Server resource sidecar exceeds runtime bound")
    return resources, generated, r


def compile_server(work, blobs, tools, env, generated, r_source):
    config = generated / "BuildConfig.java"
    config.write_bytes(build_config(SERVER_ASSETS))
    classes, stubs, dex = work / "classes", work / "stubs", work / "dex"
    for path in (classes, stubs, dex):
        path.mkdir()
    # Compile-only API shape. Never include this stub in the final DEX.
    stub = work / "MessagingUnityPlayerActivity.java"
    stub.write_text('package com.google.firebase; public class MessagingUnityPlayerActivity '
        'extends android.app.Activity { public MessagingUnityPlayerActivity() {} '
        '@Override protected void onCreate(android.os.Bundle b) { super.onCreate(b); } }')
    factory_stub = work / "CoreComponentFactory.java"
    factory_stub.write_text('package androidx.core.app; public class CoreComponentFactory '
        'extends android.app.AppComponentFactory { public CoreComponentFactory() {} }')
    flags = ["-J" + flag for flag in JAVA_FLAGS]
    run([tools["javac"], *flags, "--release", "17", "-classpath", tools["android"], "-d", stubs,
         stub, factory_stub], env)
    java_sources = [work / "source" / name for name in sorted(blobs)
                   if name.startswith((JAVA_ROOT, UNIFIED_JAVA_ROOT)) and name.endswith(".java")]
    if not any(path.name == "UnifiedGameActivity.java" for path in java_sources):
        raise ValueError("Unified wrapper source is missing")
    classpath = os.pathsep.join(map(str, (tools["android"], tools["chaquopy"], stubs)))
    run([tools["javac"], *flags, "--release", "17", "-parameters", "-encoding", "UTF-8", "-classpath", classpath,
         "-d", classes, *java_sources, config, r_source], env)
    class_files = sorted(classes.rglob("*.class"))
    own = {"L" + p.relative_to(classes).as_posix()[:-6] + ";" for p in class_files}
    if not own or any(not name.startswith("L" + SERVER_PACKAGE.replace(".", "/") + "/") for name in own):
        raise ValueError("Unexpected compiled Java namespace")
    run([tools["java"], *JAVA_FLAGS, "-cp", tools["d8"], "com.android.tools.r8.D8", "--release",
         "--min-api", "30", "--lib", tools["android"], "--classpath", stubs,
         "--output", dex, *class_files, tools["chaquopy"]], env)
    if {p.name for p in dex.iterdir()} != {"classes.dex"}:
        raise ValueError("Unexpected fresh server DEX count")
    raw = (dex / "classes.dex").read_bytes()
    definitions = dex_classes(raw)
    if not own <= definitions or any(not name.startswith(("L" + SERVER_PACKAGE.replace(".", "/") + "/",
            "Lcom/chaquo/python/")) for name in definitions):
        raise ValueError("Unexpected D8 class definitions or packaged compile-only stub")
    return raw, definitions


def rebuild_manifest(work, client, tools, env):
    small, decoded, rebuilt = work / "resource-input.apk", work / "decoded", work / "manifest-rebuilt.apk"
    with ZipFile(client) as incoming, ZipFile(small, "x") as outgoing:
        for info in incoming.infolist():
            if info.filename in ("AndroidManifest.xml", "resources.arsc") or info.filename.startswith("res/"):
                with incoming.open(info) as source, outgoing.open(copy.copy(info), "w") as target:
                    shutil.copyfileobj(source, target, CHUNK)
    run([tools["java"], *JAVA_FLAGS, "-jar", tools["editor"], "d", "-dex", "-t", "xml",
         "-i", small, "-o", decoded], env)
    manifest = decoded / "AndroidManifest.xml"
    manifest.write_bytes(transform_manifest(manifest.read_bytes()))
    expected_windowing = windowing_policy(manifest.read_bytes())
    run([tools["java"], *JAVA_FLAGS, "-jar", tools["editor"], "b", "-i", decoded, "-o", rebuilt], env)
    readback = work / "manifest-readback"
    run([tools["java"], *JAVA_FLAGS, "-jar", tools["editor"], "d", "-dex", "-t", "xml",
         "-i", rebuilt, "-o", readback], env)
    actual_windowing = windowing_policy((readback / "AndroidManifest.xml").read_bytes())
    if actual_windowing != expected_windowing:
        raise ValueError("Compiled windowing policy differs from source")
    with ZipFile(rebuilt) as source:
        return read(source, "AndroidManifest.xml", MIB), actual_windowing


class RawZipWriter:
    """Stream original compressed spans without an extract/recompress cycle.

    Unity Data span hashes bind compressed bytes, including their original
    compression parameters. ZIP offsets/headers may change for alignment.
    """
    def __init__(self, path):
        self.stream = Path(path).open("xb")
        self.directory = []
        self.names = set()

    def __enter__(self):
        return self

    def _header(self, name, method, crc, compressed, plain, mode):
        encoded = name.encode("utf-8")
        flags = 0x800 if not name.isascii() else 0
        offset = self.stream.tell()
        alignment = 16384 if method == ZIP_STORED and name.startswith("lib/") and name.endswith(".so") else 4
        padding = (-(offset + 30 + len(encoded) + 4)) % alignment if method == ZIP_STORED else 0
        extra = struct.pack("<HH", 0xd935, padding) + bytes(padding) if method == ZIP_STORED else b""
        if (name in self.names or len(encoded) > 512 or len(self.names) >= 10000
                or not 0 <= compressed <= 384 * MIB or not 0 <= plain <= 384 * MIB
                or offset + compressed > MAX_APK):
            raise ValueError("Raw APK member exceeds bounds or collides")
        self.names.add(name)
        self.stream.write(struct.pack("<I5H3I2H", 0x04034b50, 20, flags, method,
            0, 33, crc, compressed, plain, len(encoded), len(extra)) + encoded + extra)
        self.directory.append(struct.pack("<I6H3I5H2I", 0x02014b50, 0x0314, 20,
            flags, method, 0, 33, crc, compressed, plain, len(encoded), 0, 0,
            0, 0, mode, offset) + encoded)

    def raw(self, archive, info):
        source = archive.fp
        source.seek(info.header_offset)
        header = source.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise ValueError("Original APK local ZIP header missing")
        _, _, flags, method, _, _, crc, compressed, plain, nlen, extra = struct.unpack("<4s5H3I2H", header)
        raw_name = source.read(nlen)
        encoding = "utf-8" if flags & 0x800 else "cp437"
        if (raw_name.decode(encoding) != info.filename or flags != info.flag_bits
                or method != info.compress_type or flags & 1
                or not flags & 8 and (crc, compressed, plain) != (info.CRC, info.compress_size, info.file_size)):
            raise ValueError("Original APK local/central metadata differs")
        source.seek(extra, os.SEEK_CUR)
        if source.tell() + info.compress_size > archive.start_dir:
            raise ValueError("Original compressed ZIP span exceeds file data")
        self._header(info.filename, info.compress_type, info.CRC,
                     info.compress_size, info.file_size, info.external_attr)
        remaining = info.compress_size
        while remaining:
            block = source.read(min(CHUNK, remaining))
            if not block:
                raise ValueError("Truncated original compressed ZIP span")
            self.stream.write(block)
            remaining -= len(block)

    def bytes(self, name, value):
        self._header(name, ZIP_STORED, zlib.crc32(value) & 0xffffffff,
                     len(value), len(value), 0o100644 << 16)
        self.stream.write(value)

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                start = self.stream.tell()
                for row in self.directory:
                    self.stream.write(row)
                length = self.stream.tell() - start
                self.stream.write(struct.pack("<I4H2IH", 0x06054b50, 0, 0,
                    len(self.directory), len(self.directory), length, start, 0))
                self.stream.flush()
                os.fsync(self.stream.fileno())
        finally:
            self.stream.close()


def merge_apk(client, server, target, manifest, dex_name, dex, resources, app, build,
              language_archive, data_descriptor, native_bridge=None):
    before = {}
    additions = {dex_name: dex, MARKER: None, RESOURCES_ASSET: resources.read_bytes()}
    marker = {"schema": 1, "prototype": True, "package": PACKAGE, "min_sdk": 30,
        "process_mode": "same", "launcher": MENU_ACTIVITY, "game_activity": GAME_ACTIVITY,
        "original_game_activity": ORIGINAL_ACTIVITY, "languages": ["ko", "ja", "en"], "default_language": "ko",
        "resource_pack": {"asset": RESOURCES_ASSET.removeprefix("assets/"), "bytes": resources.stat().st_size,
                          "sha256": sha256(resources), "package_id": 126}, "data_pack": data_descriptor}
    additions[MARKER] = (json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n").encode()
    with ZipFile(client) as game, ZipFile(server) as host, ZipFile(language_archive) as languages, \
            RawZipWriter(target) as output:
        game_infos, host_infos = inventory(game), inventory(host)
        language_infos = inventory(languages)
        selected = server_members(host_infos)
        validate_merge(game_infos, selected, additions)
        if set(language_infos) & (set(game_infos) | selected | set(additions)):
            raise ValueError("Language object store collides with APK members")
        for name, info in game_infos.items():
            if signature_member(name):
                continue
            before[name] = member_hash(game, name)
            if name == "AndroidManifest.xml":
                output.bytes(name, manifest)
            elif name == OWN_BRIDGE and native_bridge is not None:
                output.bytes(name, native_bridge)
            else:
                output.raw(game, info)
        for name in sorted(selected):
            value = app if name == pybundle.APP else build if name == pybundle.BUILD else None
            if value is not None:
                output.bytes(name, value)
            else:
                output.raw(host, host_infos[name])
        for name, value in additions.items():
            output.bytes(name, value)
        for name in sorted(language_infos):
            output.raw(languages, language_infos[name])
    return before, marker


def verify_preservation(candidate, before, dex_name, definitions, native_bridge=None):
    with ZipFile(candidate) as archive:
        inventory(archive)
        changed = [name for name, digest in before.items() if member_hash(archive, name) != digest]
        expected_changes = {"AndroidManifest.xml"} | ({OWN_BRIDGE} if native_bridge is not None else set())
        if set(changed) != expected_changes:
            raise ValueError("An original game/SDK/resource member changed unexpectedly")
        if native_bridge is not None and member_hash(archive, OWN_BRIDGE) != hashlib.sha256(native_bridge).hexdigest():
            raise ValueError("Final source-bound native addon differs")
        if dex_classes(read(archive, dex_name, 32 * MIB)) != definitions:
            raise ValueError("Final server DEX definitions differ")
        native_count, extracted_native_count = 0, 0
        for info in archive.infolist():
            if not (info.filename.startswith("lib/") and info.filename.endswith(".so")):
                continue
            if info.compress_type == ZIP_DEFLATED:
                # Retained original native members are compressed. Android's
                # extractNativeLibs=true puts them in nativeLibraryDir; their
                # compressed APK offsets are not mapped as ELF pages.
                extracted_native_count += 1
                continue
            archive.fp.seek(info.header_offset + 26)
            name_size, extra_size = struct.unpack("<HH", archive.fp.read(4))
            if info.compress_type != ZIP_STORED or (info.header_offset + 30 + name_size + extra_size) % 16384:
                raise ValueError("Final native library is not stored/16KiB aligned")
            native_count += 1
    return {"original_members": len(before), "changed_original_members": changed,
        "resources_arsc_unchanged": True, "original_dex_and_sdk_native_unchanged": True,
        "owned_presentation_addon_replaced": native_bridge is not None,
        "native_libraries_16k_aligned": native_count,
        "compressed_native_libraries_extracted": extracted_native_count,
        "preserved_members_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()}


def build(args):
    pybundle._compiler()
    if not args.prototype:
        raise ValueError("Explicit --prototype acknowledgement is required")
    root = Path(args.source_root).resolve(strict=True)
    output = Path(args.output).absolute()
    report_path = output.with_suffix(".provenance.json")
    if (not output.parent.is_dir() or not re.fullmatch(r"IdolyPride-Unified-\d{4}\.\d{2}\.\d{2}(?:\.[1-9]\d*)?-prototype\.apk", output.name)
            or any(os.path.lexists(p) for p in (output, report_path))):
        raise ValueError("Choose new dated prototype output/report paths")
    baseline_oom, started = _oom_count(), time.monotonic()
    preflight(output.parent, baseline_oom)
    client, server = regular(args.client_apk), regular(args.server_apk)
    if sha256(client) != CLIENT_SHA256 or sha256(server) != SERVER_SHA256:
        raise ValueError("Pinned public APK input hash differs")
    sdk = Path(args.build_tools).resolve(strict=True)
    jdk = Path(args.jdk_bin).resolve(strict=True)
    tools = {"java": jdk / "java", "javac": jdk / "javac", "keytool": jdk / "keytool",
        "android": regular(args.android_jar, 64 * MIB), "chaquopy": regular(args.chaquopy_jar, MIB),
        "editor": regular(args.apkeditor, 16 * MIB), "aapt2": sdk / "aapt2", "zipalign": sdk / "zipalign",
        "d8": sdk / "lib/d8.jar", "signer": sdk / "lib/apksigner.jar"}
    if sha256(tools["chaquopy"]) != CHAQUOPY_SHA256 or sha256(tools["editor"]) != EDITOR_SHA256:
        raise ValueError("Pinned Java input hash differs")
    tools = {key: regular(value, 128 * MIB) for key, value in tools.items()}
    key, password = regular(args.keystore, MIB), regular(args.password_file, 1024)
    if password.stat().st_mode & 0o077:
        raise ValueError("Password file must be private")
    env = dict(os.environ)
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS", "GRADLE_OPTS"):
        env.pop(name, None)
    cert = subprocess.check_output([str(tools["keytool"]), "-J-Xmx128m", "-exportcert", "-keystore", str(key),
        "-alias", args.alias, "-storepass:file", str(password)], env=env, stderr=subprocess.DEVNULL, timeout=30)
    if hashlib.sha256(cert).hexdigest() != CERTIFICATE:
        raise ValueError("Signing certificate differs from installed diagnostic client")
    blobs, sources, dirty = source_snapshot(root, args.source_commit, args.allow_working_tree)
    if bool(args.native_bridge) != bool(args.native_receipt):
        raise ValueError("Native addon and its source receipt must be supplied together")
    native_bridge, native_receipt = (validate_native_bridge(args.native_bridge, args.native_receipt, root,
        args.source_commit) if args.native_bridge else (None, None))
    with tempfile.TemporaryDirectory(prefix=".unified-apk-", dir=output.parent) as temporary:
        work = Path(temporary)
        if __package__:
            from . import build_android_language_data as language_data
        else:
            import build_android_language_data as language_data
        language_archive = work / "language-data.zip"
        data_descriptor = language_data.build_archive({"ko": client,
            "ja": regular(args.client_ja_apk), "en": regular(args.client_en_apk)}, language_archive)
        resources, generated, r = build_resources(work, blobs, tools, env)
        dex, definitions = compile_server(work, blobs, tools, env, generated, r)
        with ZipFile(client) as archive:
            infos = inventory(archive)
            dex_name, old_classes = next_dex_name(infos), set()
            for name in infos:
                if re.fullmatch(r"classes\d*\.dex", name):
                    current = dex_classes(read(archive, name, 32 * MIB))
                    if old_classes & current:
                        raise ValueError("Original DEX classes overlap")
                    old_classes.update(current)
            if old_classes & definitions:
                raise ValueError("Original game and fresh server class definitions overlap")
        with ZipFile(server) as archive:
            for name, (size, digest) in SERVER_ASSETS.items():
                if archive.getinfo(name).file_size != size or member_hash(archive, name) != digest:
                    raise ValueError("Pinned bundled server data asset differs")
            original = read(archive, pybundle.APP, 8 * MIB)
            original_build = read(archive, pybundle.BUILD, 64 * 1024)
            epoch = int(subprocess.check_output(["git", "-C", str(root), "show", "-s", "--format=%ct", args.source_commit], timeout=10))
            app, python_rows = pybundle.compile_app(original, sources, epoch)
            old_app_sha = hashlib.sha1(original).hexdigest().encode()
            if original_build.count(old_app_sha) != 1:
                raise ValueError("Chaquopy app integrity declaration differs")
            build_json = original_build.replace(old_app_sha, hashlib.sha1(app).hexdigest().encode())
        manifest, windowing = rebuild_manifest(work, client, tools, env)
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        before, marker = merge_apk(client, server, unsigned, manifest, dex_name, dex, resources, app, build_json,
                                   language_archive, data_descriptor, native_bridge)
        preflight(output.parent, baseline_oom)
        # SDK34 zipalign lacks -P16. The raw writer has already aligned every
        # stored native member to16KiB; ordinary 4-byte alignment preserves it.
        run([tools["zipalign"], "-f", "4", unsigned, aligned], env)
        run([tools["java"], *JAVA_FLAGS, "-jar", tools["signer"], "sign", "--ks", key,
             "--ks-key-alias", args.alias, "--ks-pass", "file:" + str(password),
             "--v4-signing-enabled", "false", aligned], env)
        verification = run([tools["java"], *JAVA_FLAGS, "-jar", tools["signer"], "verify", "--verbose",
                            "--print-certs", aligned], env)
        if "Signer #1 certificate SHA-256 digest: " + CERTIFICATE not in verification:
            raise ValueError("Signed candidate certificate differs")
        run([tools["zipalign"], "-c", "4", aligned], env)
        preservation = verify_preservation(aligned, before, dex_name, definitions, native_bridge)
        with ZipFile(aligned) as final_apk:
            if read(final_apk, "AndroidManifest.xml", MIB) != manifest:
                raise ValueError("Final compiled manifest differs from verified windowing policy")
        if language_data.validate_data_archive(aligned, client, embedded=True) != data_descriptor:
            raise ValueError("Final language object store differs")
        badging = run([tools["aapt2"], "dump", "badging", aligned], env)
        if (f"package: name='{PACKAGE}' versionCode='414'" not in badging or "sdkVersion:'30'" not in badging
                or f"launchable-activity: name='{MENU_ACTIVITY}'" not in badging):
            raise ValueError("Final manifest identity/launcher differs")
        final_blobs, _, _ = source_snapshot(root, args.source_commit, args.allow_working_tree)
        if final_blobs != blobs:
            raise ValueError("Compiled source snapshot changed during build")
        if native_receipt is not None:
            if validate_native_bridge(args.native_bridge, args.native_receipt, root, args.source_commit) != (native_bridge, native_receipt):
                raise ValueError("Native addon source receipt changed during build")
        if sha256(client) != CLIENT_SHA256 or sha256(server) != SERVER_SHA256:
            raise ValueError("Public APK inputs changed during build")
        preflight(output.parent, baseline_oom)
        report = {"schema": 1, "prototype": True, "release_eligible": False,
            "source_commit": args.source_commit, "working_tree_snapshot": dirty,
            "compiled_source_unchanged_during_build": True, "public_apk_inputs_unchanged": True,
            "source_files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                             for name, raw in sorted(blobs.items())],
            "inputs": {"client_sha256": CLIENT_SHA256, "language_clients": language_data.PINS,
                       "server_sha256": SERVER_SHA256,
                       "chaquopy_jar_sha256": CHAQUOPY_SHA256},
            "tools": {name: sha256(path) for name, path in tools.items()}, "marker": marker,
            "windowing": windowing,
            "native_addon_build": native_receipt,
            "python_sources": python_rows, "added_dex": dex_name, "server_class_count": len(definitions),
            "preservation": preservation, "signed_certificate_sha256": CERTIFICATE,
            "apk_bytes": aligned.stat().st_size, "apk_sha256": sha256(aligned),
            "runtime_validation": {"install_and_launch": False, "gameplay": False,
                "language_switching": False, "shared_resource_direct_reading": False,
                "multi_window": False, "fold_display_transition": False},
            "release_gates": ["Android9/10 compatibility", "three language Unity Data selection on device",
                "real arm64 install/server/game runtime", "same-process native library compatibility",
                "client direct resource reads without duplicate cache"],
            "elapsed_seconds": round(time.monotonic() - started, 3), "oom_kill_delta": 0}
        report["resource_usage"] = {
            "builder_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "largest_child_peak_rss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
            "java_heap_limit_bytes": 512 * MIB, "minimum_free_disk_bytes": 4 * 1024 * MIB,
            "minimum_available_memory_bytes": 2 * 1024 * MIB,
        }
        staged_report = work / "report.json"
        staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        # Exclusive publication; an existing installation/download is never replaced.
        os.link(aligned, output)
        try:
            os.link(staged_report, report_path)
        except BaseException:
            output.unlink()
            raise
    return {"apk": str(output), "report": str(report_path), "sha256": report["apk_sha256"],
            "bytes": report["apk_bytes"], "release_eligible": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "source-commit", "client-apk", "client-ja-apk", "client-en-apk",
                 "server-apk", "chaquopy-jar", "apkeditor",
                 "android-jar", "build-tools", "jdk-bin", "keystore", "password-file", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--alias", default="idoly-diagnostics-public")
    parser.add_argument("--prototype", action="store_true")
    parser.add_argument("--allow-working-tree", action="store_true")
    parser.add_argument("--native-bridge")
    parser.add_argument("--native-receipt")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args), ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as failure:
        raise SystemExit(str(failure)) from None


if __name__ == "__main__":
    main()
