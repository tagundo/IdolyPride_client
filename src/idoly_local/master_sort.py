"""Select prepared menu-order packs without opening or generating a database."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import os
import stat
import tempfile

from .media_settings import MV_SORTS, OUTFIT_SORTS, DEFAULTS, validate_settings

POLICY = "menu-sort-v1"
CHOICES = {"PhotoQuestMusic": MV_SORTS, "Costume": OUTFIT_SORTS}
_PACK_FIELDS = {"type", "fileName", "fileSize", "cryptoKey", "downloadUrl"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate prepared catalog field")
            value[key] = item
        return value
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 512 * 1024:
            raise ValueError("Invalid prepared catalog size")
        raw = stream.read(512 * 1024 + 1)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)


def select_sorted_master_tag(master_tag, settings):
    """Compose a small tag once at startup; immutable prepared packs are reused."""
    path = Path(master_tag)
    if path.name not in ("master-tag.json", "media-master-tag.json"):
        raise ValueError("Unknown menu master tag")
    manifest = path.with_name("media-master-sort.json" if path.name.startswith("media-") else "master-sort.json")
    selected = validate_settings(settings)
    if not manifest.exists():
        # Original developer fixtures and older payloads retain their original
        # order. Explicit custom order cannot claim success without its packs.
        if selected["mv_sort"] != DEFAULTS["mv_sort"] or selected["outfit_sort"] != "original":
            raise ValueError("Prepared menu sort catalog is missing")
        return path
    tag = compose_sort_tag(_read(path), _read(manifest), selected)
    destination = path.with_name("active-library-master-tag.json")
    if destination.is_symlink():
        raise ValueError("Active catalog path is not a regular file")
    fd, temporary = tempfile.mkstemp(prefix=".library-tag-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(tag))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _pack(value, table):
    if (not isinstance(value, dict) or value.keys() != _PACK_FIELDS or value["type"] != table
            or not isinstance(value["fileName"], str) or value["fileName"] in ("", ".", "..")
            or any(c in value["fileName"] for c in ("/", "\\", "\0"))
            or type(value["fileSize"]) is not int or value["fileSize"] <= 0
            or not isinstance(value["cryptoKey"], str) or not _SHA.fullmatch(value["cryptoKey"])
            or not isinstance(value["downloadUrl"], str)):
        raise ValueError("Invalid prebuilt menu sort pack")
    return dict(value)


def _tag(value):
    if (not isinstance(value, dict) or value.keys() != {"version", "masterTagPacks"}
            or not isinstance(value["version"], str) or not value["version"]
            or not isinstance(value["masterTagPacks"], list) or not value["masterTagPacks"]):
        raise ValueError("Invalid original menu MasterTag")
    tables = [entry.get("type") if isinstance(entry, dict) else None for entry in value["masterTagPacks"]]
    if any(not isinstance(table, str) or not table for table in tables) or len(set(tables)) != len(tables):
        raise ValueError("Duplicate or invalid original master table")
    if not set(CHOICES).issubset(tables):
        raise ValueError("Original menu master tables are missing")
    for entry in value["masterTagPacks"]:
        _pack(entry, entry["type"])


def compose_sort_tag(base_tag, manifest, settings):
    """Return a new tag replacing two entries; no pack writes or database opens."""
    _tag(base_tag)
    settings = validate_settings(settings)
    if (not isinstance(manifest, dict)
            or manifest.keys() != {"schema", "policy", "language", "source", "base_version", "variants"}
            or type(manifest["schema"]) is not int or manifest["schema"] != 1 or manifest["policy"] != POLICY
            or manifest["language"] not in ("ja", "ko", "en") or manifest["source"] not in ("normal", "media")
            or manifest["base_version"] != base_tag["version"] or not isinstance(manifest["variants"], dict)
            or manifest["variants"].keys() != CHOICES.keys()):
        raise ValueError("Menu sort manifest does not match the selected base")
    selections = {"PhotoQuestMusic": settings["mv_sort"], "Costume": settings["outfit_sort"]}
    chosen = {}
    for table, selection in selections.items():
        variants = manifest["variants"][table]
        if not isinstance(variants, dict) or variants.keys() != CHOICES[table]:
            raise ValueError("Incomplete prebuilt menu sort choices")
        for record in variants.values():
            if (not isinstance(record, dict) or record.keys() != {"pack", "sha256"}
                    or not isinstance(record["sha256"], str) or not _SHA.fullmatch(record["sha256"])):
                raise ValueError("Invalid menu sort proof")
            _pack(record["pack"], table)
        chosen[table] = variants[selection]
    result = copy.deepcopy(base_tag)
    result["masterTagPacks"] = [copy.deepcopy(chosen[row["type"]]["pack"]) if row["type"] in chosen else row
                                for row in result["masterTagPacks"]]
    names = [row["fileName"] for row in result["masterTagPacks"]]
    if len(set(names)) != len(names):
        raise ValueError("A menu sort pack name conflicts with another table")
    result["version"] = POLICY + "-" + _hash(_canonical({"base": base_tag["version"], "chosen": chosen}))
    return result
