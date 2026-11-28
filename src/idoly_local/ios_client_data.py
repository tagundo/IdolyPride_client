"""Prepare one pretranslated Unity Data bundle before the game is initialized.

The signed app is input only. Common files are copied into an owned cache;
language bundles may hard-link that cache, never the signed app's files.
Nothing in this module runs on a rendering frame or translates runtime text.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import threading
import uuid
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

POLICY = "ios-prebuilt-client-data-v1"
BUNDLE_ID = "local.idoly.client-data"
LANGUAGES = ("ja", "ko", "en")
OVERLAYS = frozenset(("Data/resources.assets", "Data/Managed/Metadata/global-metadata.dat"))
CHUNK = 65536
MAX_PACKAGE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024
MAX_MANIFEST = 256 * 1024
MARKER = ".idoly-client-data.json"
_LOCK = threading.RLock()


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "Duplicate client-data manifest key")
        result[key] = value
    return result


def _json(raw):
    _need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_MANIFEST, "Client-data JSON exceeds its bound")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite client-data value")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Malformed client-data JSON") from None
    _need(type(value) is dict, "Client-data JSON must be an object")
    return value


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _path(value):
    _need(type(value) is str and 0 < len(value.encode("utf-8")) <= 1024
          and "\\" not in value and "\0" not in value, "Invalid client-data path")
    path = PurePosixPath(value)
    _need(not path.is_absolute() and str(path) == value and len(path.parts) >= 2
          and path.parts[0] == "Data" and all(part not in (".", "..", "") for part in path.parts),
          "Client-data path escaped Data")
    return path


def _regular(path, maximum):
    before = Path(path).lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "Invalid client-data file")
    return before


def _plain(path, root):
    path, root = Path(path), Path(root)
    parts = path.relative_to(root).parts
    current = root
    _need(not current.is_symlink() and current.is_dir(), "Invalid client-data root")
    for part in parts[:-1]:
        current /= part
        info = current.lstat()
        _need(stat.S_ISDIR(info.st_mode), "Client-data parent must be a plain directory")
    return path


def _file_hash(path, maximum=MAX_FILE):
    before = _regular(path, maximum)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
              == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns),
              "Client-data file changed while opening")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while block := stream.read(CHUNK):
                digest.update(block)
        after = os.fstat(fd)
        _need((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
              "Client-data file changed while reading")
        return digest.hexdigest(), before.st_size
    finally:
        os.close(fd)


def _read(path, maximum):
    _regular(path, maximum)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(maximum + 1)
    _need(len(raw) <= maximum, "Client-data file exceeds its bound")
    return raw


def _spec(value, *, overlay=False, language=None):
    _need(type(value) is dict, "Invalid client-data record")
    keys = {"bytes", "sha256", "source"} if overlay else {"bytes", "sha256"}
    if overlay and value.get("source") == "archive":
        keys.add("member")
    _need(value.keys() == keys and type(value["bytes"]) is int
          and 0 <= value["bytes"] <= MAX_FILE and _digest(value["sha256"]), "Invalid client-data record")
    if overlay:
        _need(value["source"] in (("base", "archive") if language == "ko" else ("archive",)),
              "Invalid client-data language source")


def validate_manifest(value):
    _need(type(value) is dict and value.keys() == {"schema", "policy", "bundle_id", "common", "languages", "source"}
          and type(value["schema"]) is int and value["schema"] == 1
          and value["policy"] == POLICY and value["bundle_id"] == BUNDLE_ID,
          "Invalid client-data manifest identity")
    common, languages = value["common"], value["languages"]
    _need(type(common) is dict and 0 < len(common) <= 1024
          and type(languages) is dict and languages.keys() == set(LANGUAGES), "Invalid client-data inventory")
    total = 0
    for name, row in common.items():
        _path(name); _need(name not in OVERLAYS, "Common client-data overlaps a language file")
        _spec(row); total += row["bytes"]
    for language, files in languages.items():
        _need(type(files) is dict and files.keys() == OVERLAYS, "Missing client-data language files")
        for name, row in files.items():
            _spec(row, overlay=True, language=language)
            if row["source"] == "archive":
                _need(language != "ko" or name == "Data/resources.assets",
                      "Only Korean resources may be refreshed from the archive")
                _need(row["member"] == language + "/" + name, "Invalid language archive member")
        _need(total + sum(row["bytes"] for row in files.values()) <= MAX_EXPANDED,
              "Expanded client-data exceeds its bound")
    source = value["source"]
    _need(type(source) is dict and source.keys() == {"stock_ipa_sha256", "base_ipa_sha256", "english_ui_sha256"}
          and all(_digest(v) for v in source.values()), "Invalid client-data source proof")
    return value


def _inventory(archive, manifest):
    wanted = {"manifest.json": None}
    for language in LANGUAGES:
        for row in manifest["languages"][language].values():
            if row["source"] == "archive":
                wanted[row["member"]] = row
    infos = archive.infolist()
    _need(len(infos) == len(wanted) and {i.filename for i in infos} == wanted.keys(),
          "Client-data archive inventory differs")
    _need(sum(i.file_size for i in infos) <= MAX_EXPANDED, "Client-data archive exceeds expanded bound")
    for info in infos:
        _need(not info.flag_bits & 1 and info.compress_type in (ZIP_DEFLATED, ZIP_STORED)
              and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG), "Invalid client-data archive entry")
        if wanted[info.filename] is not None:
            _need(info.file_size == wanted[info.filename]["bytes"], "Client-data archive size differs")


def _write(path, raw):
    with Path(path).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _copy(stream, path, row):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    with Path(path).open("xb") as destination:
        while block := stream.read(CHUNK):
            count += len(block)
            _need(count <= row["bytes"], "Client-data source is too long")
            digest.update(block); destination.write(block)
        destination.flush(); os.fsync(destination.fileno())
    _need(count == row["bytes"] and digest.hexdigest() == row["sha256"], "Client-data source hash differs")


def _copy_file(source, destination, row, root):
    source = _plain(source, root)
    before = _regular(source, MAX_FILE)
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as incoming:
        opened = os.fstat(incoming.fileno())
        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
              == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns), "Client-data source changed")
        _copy(incoming, destination, row)
        after = os.fstat(incoming.fileno())
        _need((opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "Client-data source changed")


def _marker(package_sha, kind, files):
    return {"schema": 1, "policy": POLICY, "package_sha256": package_sha, "kind": kind, "files": files}


def info_plist(language):
    _need(language in LANGUAGES, "Unknown client-data language")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            f'<key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>'
            '<key>CFBundlePackageType</key><string>BNDL</string>'
            '<key>CFBundleName</key><string>IdolyClientData</string>'
            f'<key>IdolyClientLanguage</key><string>{language}</string>'
            '</dict></plist>\n').encode()


def _verify_tree(directory, rows, marker, *, language=None):
    _need(not directory.is_symlink() and directory.is_dir(), "Invalid prepared client-data directory")
    _need(_json(_read(directory / MARKER, MAX_MANIFEST)) == marker, "Prepared client-data marker differs")
    expected = set(rows) | {MARKER}
    if language:
        _need(_read(directory / "Info.plist", 4096) == info_plist(language), "Prepared client-data bundle identity differs")
        expected.add("Info.plist")
    observed = set()
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in directories:
            _need(not (Path(current) / name).is_symlink(), "Prepared client-data contains a symbolic directory")
        for name in files:
            item = Path(current) / name
            _need(not item.is_symlink(), "Prepared client-data contains a symbolic file")
            observed.add(item.relative_to(directory).as_posix())
    _need(observed == expected, "Prepared client-data inventory differs")
    for name, row in rows.items():
        digest, size = _file_hash(_plain(directory / name, directory))
        _need(size == row["bytes"] and digest == row["sha256"], "Prepared client-data hash differs")


def _owned(directory):
    try:
        marker = _json(_read(directory / MARKER, MAX_MANIFEST))
        return type(marker.get("schema")) is int and marker["schema"] == 1 and marker.get("policy") == POLICY
    except (OSError, ValueError):
        return False


def _publish(stage, target):
    if target.exists() or target.is_symlink():
        _need(not target.is_symlink() and target.is_dir() and _owned(target),
              "Unrecognized client-data directory was preserved")
        retired = target.with_name(target.name + ".retired-" + uuid.uuid4().hex)
        target.rename(retired)  # Preserve damaged prior data; never delete user files.
        try:
            stage.rename(target)
        except BaseException:
            if not target.exists():
                retired.rename(target)
            raise
    else:
        stage.rename(target)


def prepare_client_data(app_bundle_dir, data_dir, language):
    """Return a verified resource-only NSBundle, without loading Unity or code."""
    _need(type(language) is str and language in LANGUAGES, "Unknown client-data language")
    with _LOCK:
        app = Path(app_bundle_dir).resolve(strict=True)
        data = Path(data_dir).resolve(strict=True)
        _need(app.is_dir() and data.is_dir(), "Client-data roots must exist")
        package = _plain(app / "LocalServer/client-languages.zip", app)
        descriptor = _json(_read(_plain(app / "LocalServer/client-languages.json", app), 4096))
        _need(descriptor.keys() == {"schema", "bytes", "sha256"}
              and type(descriptor["schema"]) is int and descriptor["schema"] == 1
              and type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] <= MAX_PACKAGE
              and _digest(descriptor["sha256"]), "Invalid client-data package descriptor")
        package_sha, package_size = _file_hash(package, MAX_PACKAGE)
        _need((package_sha, package_size) == (descriptor["sha256"], descriptor["bytes"]),
              "Client-data package hash differs")
        root = data / "client-data"
        if not root.exists():
            root.mkdir(mode=0o700)
        _need(not root.is_symlink() and root.is_dir(), "Invalid client-data destination")
        with ZipFile(package) as archive:
            info = archive.getinfo("manifest.json")
            _need(0 < info.file_size <= MAX_MANIFEST, "Client-data manifest exceeds its bound")
            manifest = validate_manifest(_json(archive.read(info)))
            _inventory(archive, manifest)
            rows = {**manifest["common"], **manifest["languages"][language]}
            marker = _marker(package_sha, language, len(rows))
            target = root / (language + ".bundle")
            try:
                _verify_tree(target, rows, marker, language=language)
                return {"schema": 1, "language": language, "bundle_id": BUNDLE_ID,
                        "bundle_path": str(target), "reused": True, "files": len(rows)}
            except (OSError, ValueError):
                if target.exists() or target.is_symlink():
                    _need(not target.is_symlink() and target.is_dir() and _owned(target),
                          "Unrecognized client-data directory was preserved")
            common = root / (".common-" + package_sha[:16])
            common_marker = _marker(package_sha, "common", len(manifest["common"]))
            try:
                _verify_tree(common, manifest["common"], common_marker)
            except (OSError, ValueError):
                stage = Path(tempfile.mkdtemp(prefix=".prepare-common-", dir=root))
                try:
                    for name, row in manifest["common"].items():
                        _copy_file(app / name, stage / name, row, app)
                    _write(stage / MARKER, (json.dumps(common_marker, sort_keys=True) + "\n").encode())
                    _verify_tree(stage, manifest["common"], common_marker)
                    _publish(stage, common)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
            stage = Path(tempfile.mkdtemp(prefix=".prepare-language-", dir=root))
            try:
                for name, row in manifest["common"].items():
                    destination = stage / name; destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(_plain(common / name, common), destination, follow_symlinks=False)
                    except (AttributeError, NotImplementedError, OSError):
                        _copy_file(common / name, destination, row, common)
                for name, row in manifest["languages"][language].items():
                    if row["source"] == "base":
                        _copy_file(app / name, stage / name, row, app)
                    else:
                        with archive.open(row["member"]) as incoming:
                            _copy(incoming, stage / name, row)
                _write(stage / "Info.plist", info_plist(language))
                _write(stage / MARKER, (json.dumps(marker, sort_keys=True) + "\n").encode())
                _verify_tree(stage, rows, marker, language=language)
                _publish(stage, target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return {"schema": 1, "language": language, "bundle_id": BUNDLE_ID,
                "bundle_path": str(target), "reused": False, "files": len(rows)}
