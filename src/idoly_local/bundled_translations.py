"""Install prebuilt language assets off the game path, with atomic selection.

The selected cache root contains ``translations/.versions/<bundle SHA>/``.
Only a small per-platform pointer changes after all bytes have been verified.
Original data, Japanese resources and the ordinary Octo cache are untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tempfile
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile


CHUNK = 64 * 1024
MAX_BUNDLE = 128 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 384 * 1024 * 1024
MAX_INDEX = 256 * 1024
MAX_RESOURCE_MANIFEST = 8 * 1024 * 1024
MAX_FILES = 32
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PLATFORMS = ("android", "ios")
_POINTER_FIELDS = {"schema", "version", "platform", "archive_sha256", "archive_bytes", "manifest_sha256"}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate language package key")
        result[key] = value
    return result


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("Invalid language package metadata file")
        raw = stream.read(limit + 1)
        if len(raw) != before.st_size or _stamp(before) != _stamp(os.fstat(stream.fileno())):
            raise ValueError("Language package metadata changed")
        return raw


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("Invalid language package metadata") from None


def _platform(value):
    if value not in _PLATFORMS:
        raise ValueError("Unknown language package platform")
    return value


def _version(value):
    if (not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 256
            or any(ord(char) < 32 for char in value)):
        raise ValueError("Invalid language package version")
    return value


def _relative(name, platform):
    if not isinstance(name, str) or "\\" in name or "\0" in name:
        raise ValueError("Unsafe language package path")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Unsafe language package path")
    parts = path.parts
    valid = (len(parts) == 3 and parts[0] in ("ko", "en") and parts[1] == platform
             and parts[2] in ("manifest.pb", "manifest.json", "objects.zip"))
    valid = valid or (len(parts) == 2 and parts[0] in ("ko", "en")
                      and parts[1] in ("text.json", "text-manifest.json"))
    if not valid:
        raise ValueError("Language package path is outside its declared platform")
    return path


def _index(raw, platform):
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != {"schema", "version", "platform", "files"}
            or type(value["schema"]) is not int or value["schema"] != 1 or value["platform"] != platform
            or not isinstance(value["files"], dict) or not 1 <= len(value["files"]) <= MAX_FILES):
        raise ValueError("Language package identity differs")
    _version(value["version"])
    total, groups, text = 0, {}, {}
    for name, record in value["files"].items():
        path = _relative(name, platform)
        if (not isinstance(record, dict) or set(record) != {"bytes", "sha256"}
                or type(record["bytes"]) is not int or not 0 < record["bytes"] <= MAX_FILE
                or not isinstance(record["sha256"], str) or not _HEX.fullmatch(record["sha256"])):
            raise ValueError("Language package file identity differs")
        total += record["bytes"]
        (groups if len(path.parts) == 3 else text).setdefault(path.parts[0], set()).add(path.name)
    if (total > MAX_TOTAL or not groups
            or any(names != {"manifest.pb", "manifest.json", "objects.zip"} for names in groups.values())
            or any(names != {"text.json", "text-manifest.json"} for names in text.values())):
        raise ValueError("Language package is incomplete or exceeds its limit")
    return value


def _pointer(value, platform):
    if (not isinstance(value, dict) or set(value) != _POINTER_FIELDS
            or type(value["schema"]) is not int or value["schema"] != 1 or value["platform"] != platform
            or not isinstance(value["archive_sha256"], str) or not _HEX.fullmatch(value["archive_sha256"])
            or not isinstance(value["manifest_sha256"], str) or not _HEX.fullmatch(value["manifest_sha256"])
            or type(value["archive_bytes"]) is not int or not 0 < value["archive_bytes"] <= MAX_BUNDLE):
        raise ValueError("Invalid selected language package")
    _version(value["version"])
    return value


def read_translation_metadata(path, *, platform):
    """Read the optional app resource's explicit outer archive pin."""
    platform = _platform(platform)
    value = _json(_read(path, 4096))
    if (not isinstance(value, dict) or set(value) != {"schema", "platform", "sha256", "bytes"}
            or type(value["schema"]) is not int or value["schema"] != 1 or value["platform"] != platform
            or not isinstance(value["sha256"], str) or not _HEX.fullmatch(value["sha256"])
            or type(value["bytes"]) is not int or not 0 < value["bytes"] <= MAX_BUNDLE):
        raise ValueError("Bundled language metadata differs")
    return value


def _directory(path, *, create=False):
    if path.is_symlink():
        raise ValueError("Language package directory is a symbolic link")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and not path.is_dir():
        raise ValueError("Language package directory is not a directory")
    return path


def _target(directory, relative):
    path = directory
    for part in relative.parts[:-1]:
        path = _directory(path / part)
    target = path / relative.name
    if not target.resolve().is_relative_to(directory.resolve()) or target.is_symlink():
        raise ValueError("Language package destination escaped its directory")
    return target


def _verify_file(path, record, output=None):
    digest, count = hashlib.sha256(), 0
    with path as incoming:
        while block := incoming.read(CHUNK):
            count += len(block)
            if count > record["bytes"]:
                raise ValueError("Language package file exceeds its declared size")
            digest.update(block)
            if output is not None:
                output.write(block)
    if count != record["bytes"] or digest.hexdigest() != record["sha256"]:
        raise ValueError("Language package file failed its digest check")


def _verified_version(directory, pointer, platform, *, contents=False):
    _directory(directory)
    if not directory.is_dir():
        raise ValueError("Selected language package is missing")
    saved = _pointer(_json(_read(directory / "version.json", 4096)), platform)
    if saved != pointer:
        raise ValueError("Selected language package version differs")
    raw = _read(directory / "translation-package.json", MAX_INDEX)
    if hashlib.sha256(raw).hexdigest() != pointer["manifest_sha256"]:
        raise ValueError("Selected language package manifest differs")
    index = _index(raw, platform)
    if index["version"] != pointer["version"]:
        raise ValueError("Selected language package version differs")
    for name, record in index["files"].items():
        target = _target(directory, _relative(name, platform))
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != record["bytes"]:
            raise ValueError("Selected language package file differs")
        if contents:
            descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            _verify_file(os.fdopen(descriptor, "rb"), record)
    return index


def resolve_translation_root(cache_root, *, platform=None):
    """Resolve one platform once at runtime preparation; invalid pointers fail.

    A missing pointer preserves compatibility with manually prepared direct
    ``translations/<language>/<platform>`` directories.
    """
    try:
        platform = _platform(platform)
        root = _directory(Path(cache_root))
        translations = _directory(root / "translations")
        selected = translations / ("current-" + platform + ".json")
        if not os.path.lexists(selected):
            return translations
        pointer = _pointer(_json(_read(selected, 4096)), platform)
        versions = _directory(translations / ".versions")
        directory = versions / pointer["archive_sha256"]
        _verified_version(directory, pointer, platform)
        return directory
    except OSError:
        raise ValueError("Selected language package is unavailable") from None


def _bounded_directory(stream):
    """Reject oversized ZIP metadata before ZipFile allocates its directory."""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or at + 22 > len(tail):
        raise ValueError("Language package ZIP directory is missing")
    signature, disk, start_disk, on_disk, count, length, offset, comment = struct.unpack_from("<4s4H2IH", tail, at)
    absolute = size - len(tail) + at
    if (disk or start_disk or on_disk != count or not 1 <= count <= MAX_FILES + 1
            or not 0 < length <= MAX_INDEX or offset + length != absolute
            or at + 22 + comment != len(tail)):
        raise ValueError("Language package ZIP directory exceeds its boundary")
    stream.seek(0)


@contextmanager
def _raw_bundle(source, expected_sha256, expected_bytes, platform):
    platform = _platform(platform)
    if (not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256)
            or type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_BUNDLE):
        raise ValueError("Explicit language package SHA and size are required")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_bytes:
            raise ValueError("Language package ZIP size differs")
        digest, count = hashlib.sha256(), 0
        while block := stream.read(CHUNK):
            count += len(block)
            if count > expected_bytes:
                raise ValueError("Language package ZIP grew while reading")
            digest.update(block)
        if (count != expected_bytes or digest.hexdigest() != expected_sha256
                or _stamp(before) != _stamp(os.fstat(stream.fileno()))):
            raise ValueError("Language package ZIP failed its digest check")
        _bounded_directory(stream)
        with ZipFile(stream) as archive:
            infos = archive.infolist()
            if len({info.filename for info in infos}) != len(infos):
                raise ValueError("Language package ZIP contains duplicate entries")
            lookup = {info.filename: info for info in infos}
            info = lookup.get("translation-package.json")
            if info is None or not 0 < info.file_size <= MAX_INDEX:
                raise ValueError("Language package index is missing")
            for entry in infos:
                if (entry.is_dir() or entry.flag_bits & 1 or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                        or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
                    raise ValueError("Language package contains an unsupported entry")
            with archive.open(info) as incoming:
                raw = incoming.read(MAX_INDEX + 1)
            if len(raw) != info.file_size:
                raise ValueError("Language package index exceeds its boundary")
            index = _index(raw, platform)
            if set(lookup) != {"translation-package.json", *("translations/" + name for name in index["files"])}:
                raise ValueError("Language package ZIP inventory differs")
            if any(lookup["translations/" + name].file_size != row["bytes"] for name, row in index["files"].items()):
                raise ValueError("Language package ZIP file size differs")
            yield archive, index, raw
        if _stamp(before) != _stamp(os.fstat(stream.fileno())):
            raise ValueError("Language package ZIP changed during installation")


@contextmanager
def _bundle(source, expected_sha256, expected_bytes, platform):
    try:
        with _raw_bundle(source, expected_sha256, expected_bytes, platform) as opened:
            yield opened
    except (BadZipFile, UnicodeError, zlib.error) as error:
        raise ValueError("Bundled language package is invalid") from error


def validate_translation_bundle(source, *, expected_sha256, expected_bytes, platform):
    """Boundedly verify the exact optional producer input; never install files."""
    with _bundle(source, expected_sha256, expected_bytes, platform) as (archive, index, raw):
        for name, record in index["files"].items():
            _verify_file(archive.open("translations/" + name), record)
        coverage, sources = {}, {}
        for name, record in index["files"].items():
            if len(PurePosixPath(name).parts) != 3 or not name.endswith("/manifest.json"):
                continue
            if record["bytes"] > MAX_RESOURCE_MANIFEST:
                raise ValueError("Prepared resource manifest exceeds its boundary")
            with archive.open("translations/" + name) as incoming:
                raw_report = incoming.read(MAX_RESOURCE_MANIFEST + 1)
            if len(raw_report) != record["bytes"]:
                raise ValueError("Prepared resource manifest size differs")
            report = _json(raw_report)
            language = PurePosixPath(name).parts[0]
            counts = report.get("coverage") if isinstance(report, dict) else None
            source_info = report.get("source") if isinstance(report, dict) else None
            if (not isinstance(report, dict) or type(report.get("schema")) is not int or report["schema"] != 1
                    or report.get("language") != language
                    or not isinstance(counts, dict)
                    or not {"adv_resources", "translated", "missing", "unchanged_original"}.issubset(counts)
                    or any(type(count) is not int or count < 0 for count in counts.values())
                    or counts["adv_resources"] != counts["translated"] + counts["missing"] + counts["unchanged_original"]
                    or not isinstance(source_info, dict) or not isinstance(source_info.get("repository"), str)
                    or not source_info["repository"] or not isinstance(source_info.get("revision"), str)
                    or not re.fullmatch(r"[0-9a-f]{40}", source_info["revision"])):
                raise ValueError("Prepared resource coverage/source identity differs")
            coverage[language], sources[language] = counts, source_info
        return {"schema": 1, "platform": platform, "version": index["version"],
                "sha256": expected_sha256, "bytes": expected_bytes,
                "manifest_sha256": hashlib.sha256(raw).hexdigest(), "files": len(index["files"]),
                "coverage": coverage, "sources": sources}


def _write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o600)


def install_translation_bundle(source, cache_root, *, expected_sha256, expected_bytes, platform, log=None,
                               validate_prepared=None):
    """Stage verified files then atomically select a complete platform version."""
    platform = _platform(platform)
    root = _directory(Path(cache_root), create=True)
    translations = _directory(root / "translations", create=True)
    versions = _directory(translations / ".versions", create=True)
    temporary, pointer_temp = None, None
    try:
        with _bundle(source, expected_sha256, expected_bytes, platform) as (archive, index, raw):
            pointer = {"schema": 1, "version": index["version"], "platform": platform,
                       "archive_sha256": expected_sha256, "archive_bytes": expected_bytes,
                       "manifest_sha256": hashlib.sha256(raw).hexdigest()}
            target = versions / expected_sha256
            reused = target.exists()
            if reused:
                _verified_version(target, pointer, platform, contents=True)
            else:
                temporary = Path(tempfile.mkdtemp(dir=versions, prefix=".install-"))
                for name, record in index["files"].items():
                    relative = _relative(name, platform)
                    destination = temporary.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with destination.open("xb") as output:
                        _verify_file(archive.open("translations/" + name), record, output)
                        output.flush()
                        os.fsync(output.fileno())
                    destination.chmod(0o600)
                with (temporary / "translation-package.json").open("xb") as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
                (temporary / "translation-package.json").chmod(0o600)
                _write_json(temporary / "version.json", pointer)
                # Another completed installer of the same immutable version
                # may win. Never overwrite any of its files or other versions.
                try:
                    os.rename(temporary, target)
                    temporary = None
                except OSError as error:
                    if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                        raise
                    _verified_version(target, pointer, platform, contents=True)
            _verified_version(target, pointer, platform)
            if validate_prepared is not None:
                validate_prepared(target)
        selected = translations / ("current-" + platform + ".json")
        if selected.is_symlink() or (selected.exists() and not selected.is_file()):
            raise ValueError("Language package selection is not a regular file")
        descriptor, name = tempfile.mkstemp(dir=translations, prefix=".current-")
        pointer_temp = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            output.write((json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(pointer_temp, selected); pointer_temp = None
        result = {"state": "unchanged" if reused else "installed", "platform": platform,
                  "version": index["version"], "archive_sha256": expected_sha256,
                  "archive_bytes": expected_bytes, "files": len(index["files"])}
        if log:
            try:
                log("준비된 번역 자료를 확인했습니다. " + platform)
            except Exception:
                pass  # Publication is complete; an observer cannot undo it.
        return result
    except (BadZipFile, UnicodeError, zlib.error) as error:
        raise ValueError("Bundled language package is invalid") from error
    finally:
        if pointer_temp is not None:
            pointer_temp.unlink(missing_ok=True)
        if temporary is not None:
            shutil.rmtree(temporary)
