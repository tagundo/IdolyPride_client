"""Prepare pinned UI/subtitle input for offline language asset producers.

This build-only module installs no hooks or runtime translation endpoints.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

LANGUAGES = {"ja": 0, "ko": 1, "en": 2}
MAX_PACK = 4 * 1024 * 1024
MAX_SCRIPT = 2 * 1024 * 1024
MAX_SCRIPTS = 8192
SCRIPT_NAME = re.compile(r"adv_[a-z0-9_-]{1,160}\.txt\Z")


def _object(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("Duplicate translation key")
        row[key] = value
    return row


def _text(value, limit):
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Translation text must be a NUL-free string")
    encoded = value.encode("utf-8")
    if not 0 < len(encoded) <= limit:
        raise ValueError("Translation text exceeds its bound")
    return encoded


def _load(path, inputs):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_PACK:
        raise ValueError("Translation source is not a bounded regular file")
    raw = path.read_bytes()
    if len(raw) > MAX_PACK:
        raise ValueError("Translation source exceeds its bound")
    inputs.append({"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object)


def _leaves(table):
    """Localify permits nested groups mixed with ungrouped direct entries."""
    if not isinstance(table, dict):
        raise ValueError("Translation table must be an object")
    for key, value in table.items():
        if isinstance(value, dict):
            yield from _leaves(value)
        elif isinstance(value, str):
            yield key, value
        else:
            raise ValueError("Translation leaf must be text")


def compile_catalog(source_dir, output_dir, *, language, source):
    """Compile available UI/generic/phone files; absent data remains Japanese."""
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    if language not in LANGUAGES or not isinstance(source, dict):
        raise ValueError("A language and source provenance are required")
    if language != "ja" and (not source.get("repository") or not re.fullmatch(r"[0-9a-f]{40}", source.get("revision", ""))):
        raise ValueError("Translation source must identify an immutable revision")
    entries, inputs, conflicts = [], [], set()
    counts = {"ui_keys": 0, "generic_strings": 0, "split_patterns": 0,
              "phone_clips": 0, "phone_lines": 0, "conflicting_generic_strings": 0}
    if language != "ja":
        path = source_dir / "localization.json"
        if path.is_file():
            ui = _load(path, inputs)
            if not isinstance(ui, dict):
                raise ValueError("UI translation table must be an object")
            for key, value in _leaves(ui):
                if value:
                    entries.append((1, key, value, 0)); counts["ui_keys"] += 1
        generic = {}
        for path in sorted((source_dir / "genericTrans").glob("*.json")):
            table = _load(path, inputs)
            if not isinstance(table, dict):
                raise ValueError("Generic translation table must be an object")
            for key, value in _leaves(table):
                if not value:
                    continue
                _text(key, 4096); _text(value, 16384)
                if key in generic and generic[key] != value:
                    conflicts.add(key)
                generic[key] = value
        for key, value in sorted(generic.items()):
            if key in conflicts:
                continue
            if "[__split__]" in key or "[__split__]" in value:
                if key.count("[__split__]") != 1 or value.count("[__split__]") != 1:
                    raise ValueError("A split translation needs one placeholder")
                entries.append((4, key, value, 0)); counts["split_patterns"] += 1
            else:
                entries.append((2, key, value, 0)); counts["generic_strings"] += 1
        counts["conflicting_generic_strings"] = len(conflicts)
        path = source_dir / "phoneSubtitles.json"
        if path.is_file():
            clips = _load(path, inputs)
            if not isinstance(clips, dict):
                raise ValueError("Phone subtitle table must be an object")
            for clip, lines in clips.items():
                if not isinstance(lines, list):
                    raise ValueError("Phone subtitle clip must contain lines")
                # Original data uses line number to order equal timestamps. The
                # last line at one instant is the visible one in the game.
                timed = {}
                for line in lines:
                    if (not isinstance(line, dict) or type(line.get("time")) not in (int, float)
                            or type(line.get("line")) is not int or not 0 <= line["time"] <= 86400):
                        raise ValueError("Invalid phone subtitle line")
                for line in sorted(lines, key=lambda row: (row["time"], row["line"])):
                    if line.get("text"):
                        timed[round(line["time"] * 1000)] = line["text"].replace("\\n", "\n")
                for timestamp, text in timed.items():
                    entries.append((3, clip, text, timestamp)); counts["phone_lines"] += 1
                counts["phone_clips"] += bool(timed)
    catalog = {"schema": 1, "language": language, "ui": {}, "generic": {}, "split": {}, "phone": {}}
    for kind, key, value, milliseconds in entries:
        _text(key, 4096); _text(value, 16384)
        if kind == 3:
            catalog["phone"].setdefault(key, []).append({"milliseconds": milliseconds, "text": value})
        else:
            catalog[{1: "ui", 2: "generic", 4: "split"}[kind]][key] = value
    pack = (json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(pack) > MAX_PACK:
        raise ValueError("Prepared translation input exceeds its bound")
    report = {"schema": 1, "language": language, "source": source, "inputs": inputs,
              "coverage": counts, "fallback": "original_japanese",
              "pack": {"name": "text.json", "bytes": len(pack), "sha256": hashlib.sha256(pack).hexdigest()}}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "text.json").write_bytes(pack)
    (output_dir / "text-manifest.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return report


def compile_adv(source_dir, output_dir, *, source):
    """Create an indexed archive without retaining all scripts in memory."""
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    if not source.get("repository") or not re.fullmatch(r"[0-9a-f]{40}", source.get("revision", "")):
        raise ValueError("ADV source must identify an immutable revision")
    paths = sorted(source_dir.glob("adv_*.txt"))
    if len(paths) > MAX_SCRIPTS:
        raise ValueError("Too many ADV scripts")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    with ZipFile(output_dir / "adv.zip", "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in paths:
            if (path.is_symlink() or not SCRIPT_NAME.fullmatch(path.name)
                    or not path.is_file() or not 0 < path.stat().st_size <= MAX_SCRIPT):
                raise ValueError("Invalid ADV script filename")
            raw = path.read_bytes()
            if not 0 < len(raw) <= MAX_SCRIPT or b"\0" in raw:
                raise ValueError("Invalid ADV script length")
            raw.decode("utf-8-sig")
            info = ZipInfo(path.name, (1980, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw, compresslevel=6)
            files[path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {"schema": 1, "source": source, "files": files, "fallback": "original_japanese"}
    (output_dir / "adv-manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return manifest
