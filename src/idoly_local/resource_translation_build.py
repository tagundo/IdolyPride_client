"""Prebuild translated Octo text objects and matching SDK manifests.

Original resource identities and files are immutable. A translated text object
receives its own identity, size and digest before it can enter an SDK manifest.
This producer never replaces a response behind an unchanged original MD5.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .octo_manifest import Database, OctoObject

MAX_SCRIPT = 2 * 1024 * 1024
MAX_MANIFEST = 8 * 1024 * 1024
NAME = re.compile(r"adv_[a-z0-9_-]{1,160}\.txt\Z")


class ZipScriptSource:
    """Pinned compressed source reader; never expands unrelated master files."""

    def __init__(self, path, prefix, *, expected_sha256, max_archive_bytes=64 * 1024 * 1024):
        path = Path(path)
        if (type(max_archive_bytes) is not int or not 1 <= max_archive_bytes <= 192 * 1024 * 1024
                or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= max_archive_bytes
                or not isinstance(prefix, str) or not prefix.endswith("/") or prefix.startswith("/")
                or "\\" in prefix or any(part in ("", ".", "..") for part in prefix[:-1].split("/"))
                or not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
            raise ValueError("Invalid pinned compressed translation source")
        digest = hashlib.sha256()
        with path.open("rb") as incoming:
            while True:
                block = incoming.read(64 * 1024)
                if not block:
                    break
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("Compressed translation source identity differs")
        archive = ZipFile(path)
        try:
            infos = archive.infolist()
            if len(infos) > 20000 or sum(info.file_size for info in infos) > 1024 * 1024 * 1024:
                raise ValueError("Compressed translation source index exceeds its bound")
            selected = [info for info in infos if info.filename.startswith(prefix)
                        and NAME.fullmatch(info.filename[len(prefix):])]
            entries = {info.filename[len(prefix):]: info for info in selected}
            if len(entries) != len(selected) or len(entries) > 8192:
                raise ValueError("Duplicate or excessive compressed ADV entries")
            for info in selected:
                if (not 0 < info.file_size <= MAX_SCRIPT or info.flag_bits & 1
                        or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
                    raise ValueError("Compressed ADV entry exceeds its bound")
        except BaseException:
            archive.close(); raise
        self.archive, self.entries = archive, entries

    def __call__(self, name):
        info = self.entries.get(name)
        if info is None:
            return None
        with self.archive.open(info) as incoming:
            raw = incoming.read(MAX_SCRIPT + 1)
        if len(raw) != info.file_size:
            raise ValueError("Compressed ADV entry size differs")
        return raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.archive.close()


def build_resource_overlay(original, translations, output, *, language, revision, source,
                           max_archive_bytes=40 * 1024 * 1024, checkpoint=None, read_script=None,
                           image_names=None, image_source=None, read_image=None):
    """Compile only named ADV resources present in the original platform list.

    The result is suitable for ``Downloads/IdolyPride/translations/<language>``.
    Its compressed object archive need not be expanded in the server data area.
    Runtime cache import still verifies each object's manifest size and MD5.
    Optional image inputs are prebuilt, platform-specific encoded bundles.
    ``read_image(name)`` returns ``(bytes, cdn_image_translation proof)`` or None.
    Supplying images produces schema2; existing ADV-only calls remain schema1.
    """
    if language not in ("ko", "en") or not isinstance(original, bytes) or not 0 < len(original) <= MAX_MANIFEST:
        raise ValueError("Invalid resource translation language or manifest")
    if (not isinstance(source, dict) or not source.get("repository")
            or not re.fullmatch(r"[0-9a-f]{40}", source.get("revision", ""))):
        raise ValueError("A pinned resource translation source is required")
    if (type(max_archive_bytes) is not int or not 1 <= max_archive_bytes <= 256 * 1024 * 1024
            or checkpoint is not None and not callable(checkpoint)
            or read_script is not None and not callable(read_script)):
        raise ValueError("Invalid resource translation producer bounds")
    database = Database.FromString(original)
    with_images = any(value is not None for value in (image_names, image_source, read_image))
    if with_images:
        if (not isinstance(image_names, (tuple, list, set, frozenset)) or len(image_names) > 4096
                or len(set(image_names)) != len(image_names)
                or any(not isinstance(name, str) or not re.fullmatch(r"img_[a-z0-9_-]{1,160}", name)
                       for name in image_names)
                or not isinstance(image_source, dict) or not image_source.get("repository")
                or not re.fullmatch(r"[0-9a-f]{40}", image_source.get("revision", ""))
                or not callable(read_image)):
            raise ValueError("Pinned image names, source and binary reader are required")
        image_names = frozenset(image_names)
        available_images = {row.name for row in database.assetBundleList if row.state != 4}
        if not image_names <= available_images:
            raise ValueError("Prepared image name is absent from the original platform manifest")
    base_revision = database.revision
    if type(revision) is not int or not base_revision < revision <= 2**31 - 1:
        raise ValueError("Translated resource revision must advance")
    translations, output = Path(translations), Path(output)
    if read_script is None and (translations.is_symlink() or not translations.is_dir()):
        raise ValueError("Translation script directory is missing")
    output.mkdir(parents=True, exist_ok=True)
    changed, missing, resources, unchanged = [], 0, 0, 0
    changed_images, missing_images, unchanged_images = [], 0, 0
    objects = {}
    with ZipFile(output / "objects.zip", "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for row in database.resourceList:
            if row.state == 4 or not NAME.fullmatch(row.name):
                continue
            resources += 1
            if checkpoint is not None:
                checkpoint()
            if read_script is not None:
                raw = read_script(row.name)
                if raw is None:
                    missing += 1; continue
                if not isinstance(raw, bytes):
                    raise ValueError("Translation source reader must return bytes")
            else:
                path = translations / row.name
                if not path.exists():
                    missing += 1; continue
                if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_SCRIPT:
                    raise ValueError("Translation script is not a bounded regular file")
                with path.open("rb") as incoming:
                    raw = incoming.read(MAX_SCRIPT + 1)
                    # Avoid retaining hundreds of MiB of public source cache.
                    if hasattr(os, "posix_fadvise"):
                        try:
                            os.posix_fadvise(incoming.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                        except OSError:
                            pass
            if not 0 < len(raw) <= MAX_SCRIPT or b"\0" in raw:
                raise ValueError("Invalid translation script")
            raw.decode("utf-8-sig")
            digest = hashlib.sha256(raw).hexdigest()
            md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
            if row.size == len(raw) and row.md5.lower() == md5:
                unchanged += 1
                continue
            before = {"size": row.size, "md5": row.md5, "object_name": row.objectName,
                      "generation": row.generation, "upload_version": row.uploadVersionId}
            # This namespace cannot collide with a public CDN object identity.
            # Its source archive is mandatory; a miss must never fetch it from
            # the public CDN under this deliberately local object name.
            name_digest = hashlib.sha256(row.name.encode("utf-8")).hexdigest()[:12]
            row.objectName = "local_" + language + "_" + digest[:28] + "_" + name_digest
            row.generation = int(digest[40:56], 16) or 1
            row.size, row.md5, row.crc, row.state = len(raw), md5, 0, 2
            record = OctoObject("resources", row.uploadVersionId, row.objectName,
                                row.generation, row.size, row.md5, row.name)
            filename = record.cache_key + ".bin"
            if filename not in objects:
                info = ZipInfo(filename, (1980, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw, compresslevel=6)
                if archive.fp.tell() > max_archive_bytes:
                    raise ValueError("Prepared language archive exceeds its producer bound")
                objects[filename] = {"name": row.name, "bytes": len(raw), "md5": md5, "sha256": digest}
            changed.append({"name": row.name, "original": before, "local": {
                "cache_key": record.cache_key, "size": row.size, "md5": row.md5,
                "sha256": digest, "object_name": row.objectName, "generation": row.generation}})
        if with_images:
            for row in database.assetBundleList:
                if row.state == 4 or row.name not in image_names:
                    continue
                if checkpoint is not None:
                    checkpoint()
                result = read_image(row.name)
                if result is None:
                    missing_images += 1
                    continue
                if (not isinstance(result, tuple) or len(result) != 2
                        or not isinstance(result[0], bytes) or not 0 < len(result[0]) <= 64 * 1024 * 1024
                        or not isinstance(result[1], dict)):
                    raise ValueError("Invalid prebuilt image bundle result")
                raw, proof = result
                digest = hashlib.sha256(raw).hexdigest()
                md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
                if (not re.fullmatch(r"[0-9a-f]{64}", proof.get("original_sha256", ""))
                        or proof.get("output_sha256") != digest or proof.get("output_bytes") != len(raw)
                        or not isinstance(proof.get("png"), dict) or not isinstance(proof.get("texture"), dict)):
                    raise ValueError("Prebuilt image proof differs from its actual bundle bytes")
                if row.size == len(raw) and row.md5.lower() == md5:
                    unchanged_images += 1
                    continue
                before = {"size": row.size, "md5": row.md5, "object_name": row.objectName,
                          "generation": row.generation, "upload_version": row.uploadVersionId,
                          "sha256": proof["original_sha256"]}
                row.objectName = "local_" + language + "_" + digest[:28] + "_" + hashlib.sha256(
                    row.name.encode("utf-8")).hexdigest()[:12]
                row.generation = int(digest[40:56], 16) or 1
                row.size, row.md5, row.crc, row.state = len(raw), md5, 0, 2
                record = OctoObject("assetbundle", row.uploadVersionId, row.objectName,
                                    row.generation, row.size, row.md5, row.name)
                filename = record.cache_key + ".bin"
                info = ZipInfo(filename, (1980, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw, compresslevel=6)
                if archive.fp.tell() > max_archive_bytes:
                    raise ValueError("Prepared language archive exceeds its producer bound")
                objects[filename] = {"name": row.name, "kind": "assetbundle", "bytes": len(raw),
                                     "md5": md5, "sha256": digest}
                changed_images.append({"name": row.name, "original": before,
                    "local": {"cache_key": record.cache_key, "size": row.size, "md5": row.md5,
                              "sha256": digest, "object_name": row.objectName, "generation": row.generation},
                    "png": proof["png"], "texture": proof["texture"]})
    if (output / "objects.zip").stat().st_size > max_archive_bytes:
        raise ValueError("Prepared language archive exceeds its producer bound")
    database.revision = revision
    translated = database.SerializeToString(deterministic=True)
    # Roundtrip proves the package does not merely carry a sidecar manifest.
    check = Database.FromString(translated)
    if check.revision != revision or len(check.resourceList) != len(database.resourceList):
        raise ValueError("Translated manifest roundtrip failed")
    (output / "manifest.pb").write_bytes(translated)
    report = {"schema": 2 if with_images else 1, "language": language, "source": source,
              "base_revision": base_revision, "revision": revision,
              "original_manifest_sha256": hashlib.sha256(original).hexdigest(),
              "manifest_sha256": hashlib.sha256(translated).hexdigest(),
              "coverage": {"adv_resources": resources, "translated": len(changed), "missing": missing,
                           "unchanged_original": unchanged},
              "objects": objects, "changed": changed, "fallback": "original_japanese"}
    if with_images:
        report.update(image_source=image_source, changed_images=changed_images,
            image_coverage={"candidates": len(image_names), "translated": len(changed_images),
                            "missing": missing_images, "unchanged_original": unchanged_images})
    (output / "manifest.json").write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    if with_images:
        # The runtime's independent declaration/manifest checks must accept the
        # complete merged ADV+image layer before a package producer publishes it.
        from .resource_translation import ResourceTranslation
        checked_layer = ResourceTranslation(output, original, language=language)
        checked_layer.close()
    return report
