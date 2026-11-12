#!/usr/bin/env python3
"""Prepare an unsigned Python-only update of the pinned Android server APK.

Run with CPython 3.13 after source tests and a commit freeze. This tool never
signs, invokes Java/Gradle, reads signing material, or installs an APK. Alignment,
same-certificate signing and actual Android runtime checks are separate steps.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
import hashlib
import importlib.util
import io
import json
import marshal
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import struct
import subprocess
import sys
import tempfile
import time
import types
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo


BASELINE_SHA256 = "4b5783ec12e8aedda706224c75a1f332859bdc7bf6731c87916e39db2522148a"
PAYLOAD_SHA256 = "ed68e0d09ad82b39de5f857b633ec6304ab7eea75e4fefe16f3a7c454c1c9f89"
PYTHON_VERSION = (3, 13)
PYC_MAGIC = bytes.fromhex("f30d0d0a")
APP = "assets/chaquopy/app.imy"
BUILD = "assets/chaquopy/build.json"
PAYLOAD = "assets/ServerData.zip"
SOURCE_ROOTS = ("src/idoly_local/", "android-server/app/src/main/python/")
CHUNK = 256 * 1024
MAX_METADATA = 64 * 1024
MAX_APP = 8 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_SOURCES = 8 * 1024 * 1024
MAX_APK = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBERS = 512
GIT_TIMEOUT = 20
# Offline developer tools are not part of the Android server entry point.
# Source files stay available to desktop/CLI/build tooling; only app.imy omits
# these explicit modules. Any new retained import of one fails the build.
ANDROID_EXCLUDED_MODULES = frozenset("idoly_local." + name for name in (
    "__main__", "cli", "android_package", "client_patch", "native_bootstrap", "ios_patch",
    "ios_presentation", "master_build", "media_master_build", "unity_http", "unity_cache",
    "collect", "event_capture", "firebase_archive", "official_session", "profiles", "server",
    "appearance_qa", "lesson_qa", "main_live_qa", "story_qa", "story_read_qa", "tutorial_qa", "pvp_capture"))
ANDROID_EXCLUDED_MEMBERS = frozenset(name.replace(".", "/") + ".pyc" for name in ANDROID_EXCLUDED_MODULES)


def _module_name(member):
    name = member.removesuffix(".pyc").replace("/", ".")
    return name.removesuffix(".__init__")


def android_runtime_sources(sources):
    """Explicit Android-only exclusions, checked against every retained import.

    All scopes/branches are examined, including function-local imports. Literal
    importlib/__import__ calls and their imported aliases are included. Unknown
    dynamic targets fail closed rather than shipping a missing runtime module.
    """
    result = {member: value for member, value in sources.items() if member not in ANDROID_EXCLUDED_MEMBERS}
    inventory = {_module_name(member) for member in sources}
    for member, (filename, raw) in result.items():
        name = _module_name(member)
        package = name if member.endswith("/__init__.pyc") else name.rpartition(".")[0]
        tree = ast.parse(raw, filename=filename)
        functions, libraries = {"__import__"}, {"importlib"}
        builtin_functions, builtin_libraries = {"__import__"}, {"builtins"}
        references = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    references.add(alias.name)
                    if alias.name == "importlib": libraries.add(alias.asname or alias.name)
                    if alias.name == "builtins": builtin_libraries.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                target = (importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                          if node.level else node.module or "")
                references.add(target)
                for alias in node.names:
                    if alias.name == "*" and (target == "idoly_local" or target.startswith("idoly_local.")):
                        raise ValueError("Android runtime contains an ambiguous wildcard module import")
                    candidate = target + "." + alias.name
                    if candidate in inventory or candidate in ANDROID_EXCLUDED_MODULES:
                        references.add(candidate)
                    if target == "importlib" and alias.name == "import_module":
                        functions.add(alias.asname or alias.name)
                    if target == "builtins" and alias.name == "__import__":
                        functions.add(alias.asname or alias.name)
                        builtin_functions.add(alias.asname or alias.name)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and (node.value.id in libraries and node.attr != "import_module"
                         or node.value.id in builtin_libraries and node.attr != "__import__")):
                raise ValueError("Android runtime contains unsupported dynamic import module access")
            importer = (isinstance(node, ast.Name) and node.id in functions
                        or isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and (node.value.id in libraries and node.attr == "import_module"
                             or node.value.id in builtin_libraries and node.attr == "__import__"))
            if importer:
                parent = parents.get(node)
                if not isinstance(parent, ast.Call) or parent.func is not node:
                    raise ValueError("Android runtime contains an indirect dynamic import function")
            if isinstance(node, ast.Name) and node.id in libraries | builtin_libraries:
                if not isinstance(parents.get(node), ast.Attribute):
                    raise ValueError("Android runtime contains an indirect dynamic import module")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call): continue
            if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                raise ValueError("Android runtime contains dynamic code with unresolved imports")
            direct = isinstance(node.func, ast.Name) and node.func.id in functions
            qualified = (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                         and (node.func.value.id in libraries and node.func.attr == "import_module"
                              or node.func.value.id in builtin_libraries and node.func.attr == "__import__"))
            if not (direct or qualified): continue
            builtin = (direct and node.func.id in builtin_functions
                       or qualified and node.func.attr == "__import__")
            if builtin and (len(node.args) != 1 or node.keywords):
                raise ValueError("Android runtime contains an unsupported dynamic __import__ form")
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                raise ValueError("Android runtime contains an unresolved dynamic module import")
            target = node.args[0].value
            if target.startswith("."):
                package_arg = node.args[1] if len(node.args) > 1 else next(
                    (arg.value for arg in node.keywords if arg.arg == "package"), None)
                if not isinstance(package_arg, ast.Constant) or not isinstance(package_arg.value, str):
                    raise ValueError("Android runtime contains an unresolved relative dynamic import")
                target = importlib.util.resolve_name(target, package_arg.value)
            references.add(target)
        for target in references:
            if any(target == removed or target.startswith(removed + ".") for removed in ANDROID_EXCLUDED_MODULES):
                raise ValueError("Retained Android runtime imports an excluded offline module")
    return result


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(CHUNK):
            result.update(block)
    return result.hexdigest()


def _compiler():
    if (sys.version_info[:2] != PYTHON_VERSION or sys.flags.optimize != 0
            or importlib.util.MAGIC_NUMBER != PYC_MAGIC):
        raise ValueError("Use unoptimized CPython 3.13 with the pinned PYC magic")


def _members(archive, expanded_limit):
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > expanded_limit:
        raise ValueError("Archive metadata or expanded size exceeds the bound")
    seen = set()
    for info in infos:
        name = info.filename
        parts = name.rstrip("/").split("/")
        if (not name or len(name.encode("utf-8")) > 240 or name in seen
                or name.startswith("/") or "\\" in name or "\x00" in name
                or any(p in ("", ".", "..") or ":" in p for p in parts)
                or info.flag_bits & 1 or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                or (info.external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError("Archive contains a duplicate, unsafe or unsupported member")
        seen.add(name)
    return {i.filename: i for i in infos}


def _read(archive, info, limit):
    if info.file_size > limit:
        raise ValueError("Archive member exceeds its bounded read size")
    with archive.open(info) as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.file_size or len(raw) > limit:
        raise ValueError("Archive member size differs")
    return raw


def _hash_members(archive, infos):
    result = {}
    for name, info in infos.items():
        h = hashlib.sha256()
        with archive.open(info) as stream:
            while block := stream.read(CHUNK):
                h.update(block)
        result[name] = h.hexdigest()
    return result


def _git(root, *args, limit):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    process = subprocess.Popen(["git", "-c", "protocol.allow=never", "-C", str(root), *args],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env)
    blocks, size, deadline = [], 0, time.monotonic() + GIT_TIMEOUT
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("Local committed source read timed out")
                block = os.read(process.stdout.fileno(), min(CHUNK, limit + 1 - size))
                if not block:
                    break
                blocks.append(block)
                size += len(block)
                if size > limit:
                    raise ValueError("Committed Python metadata or source exceeds its bound")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining):
            raise ValueError("Cannot read the specified source commit")
        return b"".join(blocks)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def committed_sources(root, commit):
    """Read only regular Python blobs in the two public source roots."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("An exact full source commit is required")
    if _git(root, "cat-file", "-t", commit, limit=32).strip() != b"commit":
        raise ValueError("Source identity must name a commit object")
    tree = _git(root, "ls-tree", "-rz", "--full-tree", commit, "--",
                *SOURCE_ROOTS, limit=MAX_METADATA)
    sources, total = {}, 0
    for record in tree.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_name = record.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            name = encoded_name.decode("utf-8")
        except (ValueError, UnicodeError):
            raise ValueError("Committed source metadata is malformed") from None
        prefix = next((p for p in SOURCE_ROOTS if name.startswith(p)), None)
        if prefix is None or not name.endswith(".py"):
            continue
        relative = name[len(prefix):]
        if (mode not in ("100644", "100755") or kind != "blob"
                or not re.fullmatch(r"[0-9a-f]{40}", oid)
                or any(p in ("", ".", "..", "__pycache__") for p in relative.split("/"))
                or "\\" in relative or ":" in relative
                or not all(p.isidentifier() for p in relative[:-3].split("/"))):
            raise ValueError("Committed Python source must be a safe regular blob")
        member = ("idoly_local/" if prefix == SOURCE_ROOTS[0] else "") + relative[:-3] + ".pyc"
        if member in sources or len(sources) >= MAX_MEMBERS:
            raise ValueError("Committed Python module names collide or exceed the bound")
        raw = _git(root, "cat-file", "blob", oid, limit=MAX_SOURCE)
        total += len(raw)
        if total > MAX_SOURCES:
            raise ValueError("Committed Python source total exceeds the bound")
        sources[member] = (name, raw)
    if "idoly_local/__init__.pyc" not in sources or "android_server_runtime.pyc" not in sources:
        raise ValueError("Committed source is missing the server package or Android bridge")
    return android_runtime_sources(sources)


def _constant_key(value):
    """Compare values and numeric bits, not marshal's reference/intern flags."""
    kind = type(value)
    if kind in (type(None), type(Ellipsis), bool, int, str, bytes):
        return kind, value
    if kind is float:
        return kind, struct.pack(">d", value)
    if kind is complex:
        return kind, struct.pack(">dd", value.real, value.imag)
    if kind is tuple:
        return kind, tuple(_constant_key(item) for item in value)
    if kind is frozenset:
        return kind, frozenset(Counter(_constant_key(item) for item in value).items())
    raise ValueError("Unsupported Python code constant type")


def _code_matches(actual, expected):
    if not isinstance(actual, types.CodeType) or not isinstance(expected, types.CodeType):
        return False
    fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
              "co_stacksize", "co_flags", "co_code", "co_names", "co_varnames",
              "co_freevars", "co_cellvars", "co_filename", "co_name", "co_qualname",
              "co_firstlineno", "co_linetable", "co_exceptiontable")
    return (all(getattr(actual, f) == getattr(expected, f) for f in fields)
            and len(actual.co_consts) == len(expected.co_consts)
            and all(_code_matches(a, b) if isinstance(a, types.CodeType) or isinstance(b, types.CodeType)
                    else _constant_key(a) == _constant_key(b)
                    for a, b in zip(actual.co_consts, expected.co_consts)))


def compile_app(original, sources, epoch):
    """Compile and audit every committed source with uniform exact PYC headers."""
    if type(epoch) is not int or not 0 <= epoch <= 0xFFFFFFFF:
        raise ValueError("PYC epoch must fit its unsigned timestamp field")
    sources = android_runtime_sources(sources)
    output, rows = io.BytesIO(), []
    with ZipFile(io.BytesIO(original)) as before:
        infos = _members(before, MAX_APP)
        if any(not n.endswith(("/", ".pyc")) for n in infos):
            raise ValueError("Baseline app archive contains unexpected non-PYC files")
        if {n for n in infos if n.endswith(".pyc")} - sources.keys() - ANDROID_EXCLUDED_MEMBERS:
            raise ValueError("Source commit would omit an existing Python module")
        compiled = {}
        for member, (source, raw) in sorted(sources.items()):
            filename = PurePosixPath(source).name
            code = compile(raw, filename, "exec", dont_inherit=True, optimize=0)
            old = _read(before, infos[member], MAX_SOURCE * 2) if member in infos else None
            if old is not None:
                if len(old) < 16 or old[:4] != PYC_MAGIC or old[4:8] != b"\0" * 4:
                    raise ValueError("Baseline PYC header differs from the pinned format")
                previous = marshal.loads(old[16:])
                if not isinstance(previous, types.CodeType) or previous.co_filename != filename:
                    raise ValueError("Baseline PYC filename or code object differs")
            compiled[member] = (PYC_MAGIC + struct.pack("<III", 0, epoch, len(raw))
                                + marshal.dumps(code))
        with ZipFile(output, "w") as after:
            for name, info in infos.items():
                if name in ANDROID_EXCLUDED_MEMBERS:
                    continue
                after.writestr(copy.copy(info), b"" if name.endswith("/") else compiled.pop(name))
            for name, raw in sorted(compiled.items()):
                info = ZipInfo(name, (1980, 2, 1, 0, 0, 0))
                info.compress_type, info.external_attr = ZIP_STORED, 0o100644 << 16
                after.writestr(info, raw)
    app = output.getvalue()
    if len(app) > MAX_APP:
        raise ValueError("Compiled app archive exceeds the bound")
    with ZipFile(io.BytesIO(app)) as archive:
        infos = _members(archive, MAX_APP)
        if {n for n in infos if not n.endswith("/")} != sources.keys():
            raise ValueError("Compiled Python inventory differs from source")
        for member, (source, raw) in sorted(sources.items()):
            pyc = _read(archive, infos[member], MAX_SOURCE * 2)
            code = marshal.loads(pyc[16:])
            expected = compile(raw, PurePosixPath(source).name, "exec", dont_inherit=True, optimize=0)
            if (pyc[:16] != PYC_MAGIC + struct.pack("<III", 0, epoch, len(raw))
                    or not _code_matches(code, expected)):
                raise ValueError("Packaged Python code does not match committed source")
            rows.append({"source": source, "source_sha256": hashlib.sha256(raw).hexdigest(),
                         "member": member, "pyc_sha256": hashlib.sha256(pyc).hexdigest(),
                         "code_object_matches_source": True})
    return app, rows


def _exclusive_publish(temporary, target):
    # Hard-link publication fails if another process created the target meanwhile.
    # Leave staging links to TemporaryDirectory cleanup: a subsequent unlink
    # failure must not turn a successful publication into a partial pair.
    os.link(temporary, target)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Chaquopy metadata contains a duplicate JSON key")
        result[key] = value
    return result


def repack(baseline, source_root, source_commit, output, *, epoch, report_path=None):
    _compiler()
    baseline, source_root = Path(baseline).resolve(strict=True), Path(source_root).resolve(strict=True)
    raw_output = Path(output)
    raw_report = Path(report_path) if report_path else raw_output.with_suffix(".provenance.json")
    if any(os.path.lexists(p) for p in (raw_output, raw_report)):
        raise ValueError("Existing output paths, including symlinks, are preserved")
    output = Path(output).resolve()
    report_path = Path(report_path).resolve() if report_path else output.with_suffix(".provenance.json")
    if (output.suffix != ".apk" or output == report_path or baseline in (output, report_path)
            or any(os.path.lexists(p) for p in (output, report_path))
            or not output.parent.is_dir() or not report_path.parent.is_dir()):
        raise ValueError("Choose new APK and provenance paths in existing directories")
    if baseline.stat().st_size > MAX_APK or digest(baseline) != BASELINE_SHA256:
        raise ValueError("Expected the exact pinned v0.3.4 server APK")
    sources = committed_sources(source_root, source_commit)
    with ZipFile(baseline) as incoming:
        before_infos = _members(incoming, MAX_EXPANDED)
        if not {APP, BUILD, PAYLOAD} <= before_infos.keys():
            raise ValueError("Baseline is missing required server assets")
        before_hashes = _hash_members(incoming, before_infos)
        if before_hashes[PAYLOAD] != PAYLOAD_SHA256:
            raise ValueError("Baseline server payload differs from its pinned hash")
        old_app = _read(incoming, before_infos[APP], MAX_APP)
        build_raw = _read(incoming, before_infos[BUILD], MAX_METADATA)
        build = json.loads(build_raw, object_pairs_hook=_json_object)
        old_sha1 = hashlib.sha1(old_app).hexdigest()
        if (not isinstance(build, dict) or build.get("python_version") != "3.13"
                or build.get("extract_packages") != [] or not isinstance(build.get("assets"), dict)
                or build["assets"].get("app.imy") != old_sha1):
            raise ValueError("Baseline Chaquopy version, extraction policy or app digest differs")
        app, modules = compile_app(old_app, sources, epoch)
        new_sha1 = hashlib.sha1(app).hexdigest()
        if new_sha1 == old_sha1 or build_raw.count(old_sha1.encode()) != 1:
            raise ValueError("No Python update or ambiguous Chaquopy app digest")
        new_build = build_raw.replace(old_sha1.encode(), new_sha1.encode())
        expected_build = copy.deepcopy(build)
        expected_build["assets"]["app.imy"] = new_sha1
        if json.loads(new_build) != expected_build:
            raise ValueError("Unexpected Chaquopy metadata change")
        replacements = {APP: app, BUILD: new_build}
        with tempfile.TemporaryDirectory(prefix=".server-python-", dir=output.parent) as temporary:
            stage = Path(temporary) / "unsigned.apk"
            with ZipFile(stage, "x") as outgoing:
                outgoing.comment = incoming.comment
                for name, info in before_infos.items():
                    copied_info = copy.copy(info)
                    if name in replacements:
                        outgoing.writestr(copied_info, replacements[name])
                    else:
                        with incoming.open(info) as src, outgoing.open(copied_info, "w") as dst:
                            while block := src.read(CHUNK):
                                dst.write(block)
                    # zipfile supplies mode0600 when the original attribute is
                    # zero. Restore the exact value before central-directory
                    # emission; AAPT resources legitimately use zero here.
                    copied_info.external_attr = info.external_attr
            with ZipFile(stage) as check:
                after_infos = _members(check, MAX_EXPANDED)
                after_hashes = _hash_members(check, after_infos)
                delta = sorted(n for n in before_hashes if before_hashes[n] != after_hashes.get(n))
                if set(after_hashes) != set(before_hashes) or delta != sorted(replacements):
                    raise ValueError("Unsigned APK changed files outside the two Python assets")
                for name, info in before_infos.items():
                    other = after_infos[name]
                    if any(getattr(info, key) != getattr(other, key) for key in
                           ("date_time", "compress_type", "external_attr", "comment", "extra")):
                        raise ValueError("Unsigned APK changed member metadata")
            if digest(baseline) != BASELINE_SHA256:
                raise ValueError("Baseline changed during packaging")
            receipt = {"schema": 1, "source_commit": source_commit,
                       "source_selection": "exact committed public Python blobs; worktree ignored",
                       "baseline_sha256": BASELINE_SHA256, "baseline_version_name": "0.3.4",
                       "baseline_version_code": 23, "unsigned_apk_sha256": digest(stage),
                       "unsigned_apk_bytes": stage.stat().st_size, "signed": False,
                       "aligned": False, "runtime_verified": False, "payload_sha256": PAYLOAD_SHA256,
                       "changed_apk_members": delta, "all_other_member_bytes_preserved": True,
                       "preserved_member_metadata_fields": ["date_time", "compress_type", "external_attr",
                                                            "comment", "extra"],
                       "app_imy_sha1": new_sha1, "python_version": sys.version.split()[0],
                       "pyc_magic": PYC_MAGIC.hex(), "new_pyc_epoch": epoch, "modules": modules}
            receipt["android_excluded_offline_modules"] = sorted(ANDROID_EXCLUDED_MODULES)
            receipt_stage = Path(temporary) / "provenance.json"
            receipt_stage.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            # Both publication destinations must share this filesystem for atomic hard links.
            if output.parent.stat().st_dev != report_path.parent.stat().st_dev:
                raise ValueError("APK and provenance must use the same filesystem")
            receipt_identity = (receipt_stage.stat().st_dev, receipt_stage.stat().st_ino)
            _exclusive_publish(receipt_stage, report_path)
            try:
                _exclusive_publish(stage, output)
            except BaseException:
                if report_path.exists() and (report_path.stat().st_dev, report_path.stat().st_ino) == receipt_identity:
                    report_path.unlink()
                raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--epoch", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = repack(args.baseline, args.source_root, args.source_commit, args.output,
                        epoch=args.epoch, report_path=args.report)
    except (OSError, ValueError, SyntaxError, EOFError, BadZipFile, subprocess.SubprocessError):
        raise SystemExit("Unsigned server repack failed; no signing or installation was attempted") from None
    print(json.dumps({k: v for k, v in result.items() if k != "modules"}, indent=2))


if __name__ == "__main__":
    main()
