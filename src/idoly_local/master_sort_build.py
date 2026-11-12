"""Offline per-table menu sort packs and a cheap, read-only runtime tag composer.

Only `order` changes. Original release dates, titles, IDs, ownership and public
visibility policy remain intact. SQLCipher is imported only by the host builder.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .media_settings import MV_SORTS, OUTFIT_SORTS, validate_settings
from .master_sort import compose_sort_tag, _pack, _tag


POLICY = "menu-sort-v1"
MANIFEST = "sort-manifest.json"
CHOICES = {"PhotoQuestMusic": MV_SORTS, "Costume": OUTFIT_SORTS}
_PACK_FIELDS = {"type", "fileName", "fileSize", "cryptoKey", "downloadUrl"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected original menu rows")
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or row["id"] in ids or type(row.get("order")) is not int
                or not -(2**31) <= row["order"] < 2**31):
            raise ValueError("Invalid or duplicate original menu row")
        ids.add(row["id"])


def _date(row, field):
    value = row.get(field)
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        result = int(value)
    else:
        raise ValueError("Original menu release date is unavailable or malformed")
    if not 0 <= result <= 2**63 - 1:
        raise ValueError("Original menu release date is out of range")
    return result


def sort_rows(table, rows, selection, *, music_rows=None):
    """Rank the chosen display order for the audited ascending master comparator.

    MV recent/old use original Music.releaseTime. Costume recent/old use its
    original releaseDate. Equal dates/titles keep original order, then ID.
    Localized name is already supplied by the caller before title sorting.
    """
    if table not in CHOICES or selection not in CHOICES[table]:
        raise ValueError("Unknown menu sort selection")
    _rows(rows)
    if selection == "original":
        return copy.deepcopy(rows)
    dates = {}
    if selection in ("recent", "old"):
        if table == "PhotoQuestMusic":
            if not isinstance(music_rows, list) or any(not isinstance(row, dict) for row in music_rows):
                raise ValueError("Original Music rows are required for MV release ordering")
            music_ids = [row.get("id") for row in music_rows]
            if (any(not isinstance(key, str) or not key for key in music_ids)
                    or len(set(music_ids)) != len(music_ids)):
                raise ValueError("Original Music identities are malformed")
            musics = dict(zip(music_ids, music_rows, strict=True))
            if any(row["id"] not in musics for row in rows):
                raise ValueError("Original photo music identity has no unique Music definition")
            dates = {row["id"]: _date(musics[row["id"]], "releaseTime") for row in rows}
        else:
            dates = {row["id"]: _date(row, "releaseDate") for row in rows}
    if selection == "title" and any(not isinstance(row.get("name"), str) for row in rows):
        raise ValueError("Localized original menu titles are required")

    def key(row):
        tie = (row["order"], row["id"])
        if selection == "recent":
            return (-dates[row["id"]], *tie)
        if selection == "old":
            return (dates[row["id"]], *tie)
        if selection == "title":
            return (row["name"].casefold(), *tie)
        return (row["id"],)

    ranks = {row["id"]: rank for rank, row in enumerate(sorted(rows, key=key), 1)}
    result = copy.deepcopy(rows)
    for row in result:
        row["order"] = ranks[row["id"]]
    return result





def build_sort_master_overlays(schema, base_tag, rows_by_table, output, *, language, source):
    """Host-only nine packs, after translation and normal/media row preparation.

    Caller merges assets/master into its shared public pack directory and places
    sort-manifest.json next to that language/mode's base MasterTag. No complete
    combination tags or copies of the full master catalog are produced here.
    """
    from .master_build import build_master_packs

    _tag(base_tag)
    if language not in ("ja", "ko", "en") or source not in ("normal", "media"):
        raise ValueError("Invalid menu sort language or source")
    if not isinstance(rows_by_table, dict) or rows_by_table.keys() != {"Music", *CHOICES}:
        raise ValueError("Expected only original Music and the two translated menu tables")
    variants = {table: {choice: sort_rows(table, rows_by_table[table], choice,
                    music_rows=rows_by_table["Music"]) for choice in sorted(choices)}
                for table, choices in CHOICES.items()}
    output = Path(output)
    if output.exists():
        raise ValueError("Menu sort output exists; previous data was preserved")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "policy": POLICY, "language": language, "source": source,
                "base_version": base_tag["version"], "variants": {}}
    with tempfile.TemporaryDirectory(prefix=".menu-sort-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        packs = stage / "assets" / "master"
        packs.mkdir(parents=True)
        for table, choices in variants.items():
            manifest["variants"][table] = {}
            for choice, rows in choices.items():
                work = Path(temporary) / (table + "-" + choice)
                source_dir, built = work / "source", work / "built"
                source_dir.mkdir(parents=True)
                raw = _canonical(rows)
                (source_dir / (table + ".json")).write_bytes(raw)
                build_master_packs(schema, source_dir, built, tables=[table])
                tag = json.loads((built / "master-tag.json").read_text(encoding="utf-8"))
                entry = _pack(tag["masterTagPacks"][0], table)
                original = built / "assets" / "master" / entry["fileName"]
                filename = f"{POLICY}-{language}-{source}-{table}-{choice}-{_hash(raw)[:24]}.db"
                destination = packs / filename
                shutil.copyfile(original, destination)
                entry.update(fileName=filename, downloadUrl="http://127.0.0.1:8080/master/" + filename)
                manifest["variants"][table][choice] = {"pack": entry, "sha256": _hash(destination.read_bytes())}
        (stage / MANIFEST).write_bytes(_canonical(manifest) + b"\n")
        compose_sort_tag(base_tag, manifest, {"schema": 1, "revision": 0, "hide_video_mv": False,
                                            "mv_sort": "recent", "outfit_sort": "original"})
        if output.exists():
            raise ValueError("Menu sort output appeared during build; existing data was preserved")
        stage.rename(output)
    return manifest
