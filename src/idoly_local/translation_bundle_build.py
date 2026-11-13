"""Build a bounded platform package of already prepared language resources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .bundled_translations import validate_translation_bundle


def _hash(path):
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as source:
        while True:
            block = source.read(64 * 1024)
            if not block:
                break
            digest.update(block); count += len(block)
    return {"bytes": count, "sha256": digest.hexdigest()}


def build_translation_bundle(prepared, output, *, platform, version, text_root=None,
                             max_bytes=100 * 1024 * 1024, checkpoint=None):
    """Write one Android or iOS package; no raw story extraction or download."""
    if (platform not in ("android", "ios") or not isinstance(version, str) or not version
            or type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024 * 1024
            or checkpoint is not None and not callable(checkpoint)):
        raise ValueError("Invalid language bundle producer settings")
    prepared, output = Path(prepared), Path(output)
    files = {}
    for language in ("ko", "en"):
        for name in ("manifest.pb", "manifest.json", "objects.zip"):
            files[f"{language}/{platform}/{name}"] = prepared / language / platform / name
        if text_root is not None:
            for name in ("text.json", "text-manifest.json"):
                files[f"{language}/{name}"] = Path(text_root) / language / name
    index = {"schema": 1, "version": version, "platform": platform, "files": {}}
    for name, path in files.items():
        if checkpoint is not None:
            checkpoint()
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 128 * 1024 * 1024:
            raise ValueError("Prepared language bundle member is unavailable")
        index["files"][name] = _hash(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    if temporary.exists():
        raise ValueError("A prior incomplete language package requires explicit cleanup")
    try:
        with ZipFile(temporary, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in files.items():
                if checkpoint is not None:
                    checkpoint()
                info = ZipInfo("translations/" + name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_STORED if path.name == "objects.zip" else ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                    digest, count = hashlib.sha256(), 0
                    while True:
                        if checkpoint is not None:
                            checkpoint()
                        block = source.read(64 * 1024)
                        if not block:
                            break
                        target.write(block); digest.update(block); count += len(block)
                        if archive.fp.tell() > max_bytes:
                            raise ValueError("Language bundle exceeds its producer bound")
                if {"bytes": count, "sha256": digest.hexdigest()} != index["files"][name]:
                    raise ValueError("Prepared language input changed while packaging")
            info = ZipInfo("translation-package.json", (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        identity = _hash(temporary)
        if identity["bytes"] > max_bytes:
            raise ValueError("Language bundle exceeds its producer bound")
        verified = validate_translation_bundle(temporary, expected_sha256=identity["sha256"],
                                               expected_bytes=identity["bytes"], platform=platform)
        if output.exists():
            raise ValueError("Language bundle output already exists")
        temporary.rename(output)
        return {"schema": 1, "platform": platform, "version": version,
                "bytes": identity["bytes"], "sha256": identity["sha256"], "index": index,
                "manifest_sha256": verified["manifest_sha256"],
                "coverage": verified["coverage"], "sources": verified["sources"]}
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
