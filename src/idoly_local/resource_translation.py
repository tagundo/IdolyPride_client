"""Load an immutable, coherently manifested language resource archive.

Only the server's verified-cache seed path should consume ``open_source``.
It returns local prepared data, never an upstream URL or an SDK hash override.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import threading
from types import MappingProxyType
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .octo_manifest import Database, OctoObject

MAX_MANIFEST = 8 * 1024 * 1024
MAX_OBJECT = 2 * 1024 * 1024
MAX_IMAGE_OBJECT = 64 * 1024 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _read(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("Invalid prepared language resource file")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise ValueError("Prepared language resource size changed")
    return raw


def _source(value):
    return (isinstance(value, dict) and isinstance(value.get("repository"), str)
            and bool(value["repository"]) and isinstance(value.get("revision"), str)
            and re.fullmatch(r"[0-9a-f]{40}", value["revision"]) is not None)


def _image_changes(report):
    coverage = report.get("image_coverage")
    changes = report.get("changed_images")
    if (not _source(report.get("image_source")) or not isinstance(coverage, dict)
            or set(coverage) != {"candidates", "translated", "missing", "unchanged_original"}
            or any(type(value) is not int or value < 0 for value in coverage.values())
            or not 0 <= coverage["candidates"] <= 4096
            or coverage["candidates"] != coverage["translated"] + coverage["missing"] + coverage["unchanged_original"]
            or not isinstance(changes, list) or len(changes) != coverage["translated"]):
        raise ValueError("Prepared language image coverage or source differs")
    indexed = {}
    for row in changes:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                or not re.fullmatch(r"img_[a-z0-9_-]{1,160}", row["name"])
                or row["name"] in indexed):
            raise ValueError("Prepared language image identity differs")
        original, local, png, texture = (row.get(key) for key in ("original", "local", "png", "texture"))
        if (not all(isinstance(value, dict) for value in (original, local, png, texture))
                or any(not isinstance(value.get("sha256"), str) or not _HEX64.fullmatch(value["sha256"])
                       for value in (original, local, png))
                or type(png.get("bytes")) is not int or not 0 < png["bytes"] <= 16 * 1024 * 1024
                or texture.get("name") != row["name"]
                or any(type(value.get(dimension)) is not int or not 0 < value[dimension] <= 16384
                       for value in (png, texture) for dimension in ("width", "height"))):
            raise ValueError("Prepared language image provenance differs")
        encoding = texture.get("encoding")
        formats = {"RGBA32-lossless": 4, "ASTC4x4-medium": 48, "ASTC6x6-medium": 50}
        if (not isinstance(encoding, str) or encoding not in formats
                or any(type(texture.get(field)) is not int or texture[field] != formats[encoding]
                       for field in ("format_before", "format_after"))):
            raise ValueError("Prepared language image GPU format differs")
        lossless = encoding == "RGBA32-lossless"
        if texture.get("readback_pixel_exact") is not lossless:
            raise ValueError("Prepared language image readback proof differs")
        if not lossless and (
                any(not isinstance(texture.get(key), str) or not _HEX64.fullmatch(texture[key])
                    for key in ("source_RGBA_sha256", "decoded_RGBA_sha256"))
                or type(texture.get("quality")) is not int or texture["quality"] != 60
                or type(texture.get("threads")) is not int or texture["threads"] != 1):
            raise ValueError("Prepared language ASTC image proof differs")
        indexed[row["name"]] = row
    return indexed


class ResourceTranslation:
    """Validate all manifest edits before making any translated object visible."""

    def __init__(self, directory, original_manifest, *, language):
        if language not in ("ko", "en") or not isinstance(original_manifest, bytes):
            raise ValueError("Unknown language resource source")
        self._lock, self._archive = threading.Lock(), None
        self._records, self._entries = {}, {}
        object_aliases = {}
        self.language = language
        directory = Path(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Prepared language directory is unavailable")
        report = json.loads(_read(directory / "manifest.json", MAX_MANIFEST).decode("utf-8"))
        translated = _read(directory / "manifest.pb", MAX_MANIFEST)
        if (not isinstance(report, dict) or type(report.get("schema")) is not int
                or report["schema"] not in (1, 2) or report.get("language") != language
                or report.get("original_manifest_sha256") != hashlib.sha256(original_manifest).hexdigest()
                or report.get("manifest_sha256") != hashlib.sha256(translated).hexdigest()
                or not isinstance(report.get("objects"), dict) or len(report["objects"]) > 8192):
            raise ValueError("Prepared language manifest identity differs")
        coverage, source = report.get("coverage"), report.get("source")
        if (not isinstance(coverage, dict)
                or set(coverage) != {"adv_resources", "translated", "missing", "unchanged_original"}
                or any(type(value) is not int or value < 0 for value in coverage.values())
                or coverage["adv_resources"] != coverage["translated"] + coverage["missing"] + coverage["unchanged_original"]
                or not isinstance(source, dict) or not isinstance(source.get("repository"), str)
                or not source["repository"] or not isinstance(source.get("revision"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", source["revision"])):
            raise ValueError("Prepared language coverage or source differs")
        images = _image_changes(report) if report["schema"] == 2 else {}
        original, modified = Database.FromString(original_manifest), Database.FromString(translated)
        if (report.get("base_revision") != original.revision or report.get("revision") != modified.revision
                or not original.revision < modified.revision <= 2**31 - 1
                or len(original.resourceList) != len(modified.resourceList)
                or len(original.assetBundleList) != len(modified.assetBundleList)):
            raise ValueError("Prepared language manifest revision differs")
        # Reverse the temporary parsed copy in place after snapshotting each
        # immutable object record. Keeping a third complete 54k-object database
        # alive only to compare it would add unnecessary preparation memory.
        modified.revision = original.revision
        changed_images = set()
        groups = (("resources", original.resourceList, modified.resourceList),)
        if report["schema"] == 2:
            groups += (("assetbundle", original.assetBundleList, modified.assetBundleList),)
        for kind, old_rows, new_rows in groups:
            for old, new in zip(old_rows, new_rows):
                if old == new:
                    continue
                image = images.get(old.name) if kind == "assetbundle" else None
                allowed = (image is not None if kind == "assetbundle"
                           else re.fullmatch(r"adv_[a-z0-9_-]{1,160}\.txt", old.name))
                maximum = MAX_IMAGE_OBJECT if kind == "assetbundle" else MAX_OBJECT
                if (not allowed
                        or old.state == 4 or new.name != old.name or new.id != old.id
                        or new.state != 2 or new.crc != 0 or not 0 < new.size <= maximum
                        or not new.objectName.startswith("local_" + language + "_")):
                    raise ValueError("Prepared language resource changed an undeclared record")
                record = OctoObject(kind, new.uploadVersionId, new.objectName,
                                    new.generation, new.size, new.md5, new.name)
                filename = record.cache_key + ".bin"
                expected = report["objects"].get(filename)
                if (not isinstance(expected, dict) or expected.get("bytes") != new.size
                        or expected.get("md5") != new.md5 or not isinstance(expected.get("sha256"), str)
                        or not _HEX64.fullmatch(expected["sha256"])
                        or new.objectName != "local_" + language + "_" + expected["sha256"][:28]
                            + "_" + hashlib.sha256(new.name.encode("utf-8")).hexdigest()[:12]
                        or new.generation != (int(expected["sha256"][40:56], 16) or 1)):
                    raise ValueError("Prepared language object identity differs")
                if kind == "assetbundle":
                    before = {"size": old.size, "md5": old.md5, "object_name": old.objectName,
                              "generation": old.generation, "upload_version": old.uploadVersionId}
                    after = {"cache_key": record.cache_key, "size": new.size, "md5": new.md5,
                             "sha256": expected["sha256"], "object_name": new.objectName, "generation": new.generation}
                    if (any(image["original"].get(key) != value for key, value in before.items())
                            or image["local"] != after or expected.get("name") != old.name
                            or expected.get("kind") != "assetbundle"):
                        raise ValueError("Prepared language image manifest identity differs")
                    changed_images.add(old.name)
                # Existing SDK metadata can retain the original objectName while
                # adopting the translated generation. Resolve that exact observed
                # combination to the same verified local record, without changing
                # its cache key, content hash, or the canonical manifest identity.
                alias = (kind, old.uploadVersionId, old.objectName, new.generation)
                if alias in object_aliases:
                    raise ValueError("Prepared language object alias differs")
                object_aliases[alias] = record
                # Reverse exactly the six authorized data-integrity fields. Proto
                # equality below also checks all other scalars, repeated fields,
                # asset bundles, tag lists and unknown protobuf fields.
                for field in ("objectName", "generation", "size", "md5", "crc", "state"):
                    setattr(new, field, getattr(old, field))
                self._records[record.cache_key] = record
                self._entries[filename] = expected
        if (modified != original or set(self._entries) != set(report["objects"])
                or changed_images != set(images)):
            raise ValueError("Prepared language manifest changed an unrelated field")
        archive_path = directory / "objects.zip"
        if archive_path.is_symlink() or not archive_path.is_file() or not 0 < archive_path.stat().st_size <= MAX_ARCHIVE:
            raise ValueError("Prepared language archive is unavailable")
        archive = ZipFile(archive_path)
        try:
            infos = archive.infolist()
            if (len(infos) != len(self._entries) or len({info.filename for info in infos}) != len(infos)
                    or {info.filename for info in infos} != set(self._entries)):
                raise ValueError("Prepared language object index differs")
            for info in infos:
                if (info.file_size != self._entries[info.filename]["bytes"] or info.flag_bits & 1
                        or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                        or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
                    raise ValueError("Prepared language object entry differs")
        except BaseException:
            archive.close(); raise
        self._archive, self.manifest, self.report = archive, translated, report
        self.object_aliases = MappingProxyType(object_aliases)

    def open_source(self, record):
        """Open a named local seed; cache still checks complete size and MD5."""
        expected = self._records.get(record.cache_key)
        if expected is None:
            if record.object_name.startswith(("local_ko_", "local_en_")):
                raise ValueError("Unprepared local language object")
            return None
        if record != expected:
            raise ValueError("Language resource cache identity differs")
        with self._lock:
            if self._archive is None:
                raise ValueError("Language resource archive is closed")
            return self._archive.open(record.cache_key + ".bin")

    def close(self):
        with self._lock:
            if self._archive is not None:
                self._archive.close(); self._archive = None
