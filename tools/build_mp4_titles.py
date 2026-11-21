#!/usr/bin/env python3
"""Reproduce bounded MP4 display titles from the audited public server payload.

Build host only. SQLCipher and original pack keys never enter the generated
module; the mobile runtime receives only public timeline names and titles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BYTES = 198675046
SOURCE_SHA256 = "3ea45bd9fba07d35cf366d50e8bc7604aeb67ea0aa1cd55f751474a75724dbce"
MUSIC_JSON_SHA256 = "25e4dcb4a4317ebd2fc66b83bc1425aa9a08f6b3a57f3e59324739d67c1ddd93"
PACKS = {
    "en": {"file_bytes": 278528, "file_name": "local-language-en-e1c2022aceb4b9681163b01e-Music.db", "sha256": "b86ad6c92f1b958dadb79595e83a5b43e50cb6632f8f9742a73e9cc0c25aee2f"},
    "ja": {"file_bytes": 278528, "file_name": "f98f00dd53905361bac1557131cd134adcd091e16cc949a4c12c359f64a046ca", "sha256": "d2fa0afb96fe526f13bf55a470e8ece52d4cdc80b21de0947abd179b5260b879"},
    "ko": {"file_bytes": 282624, "file_name": "local-language-ko-852ab15982d9f6e0b9e538e8-Music.db", "sha256": "72d38eec466688521c650909fd1c61bfa71b616eed5d98fd366f31337b82c600"},
}
MAX_CATALOG_BYTES = 48 * 1024


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _member(archive, name, limit):
    rows = [info for info in archive.infolist() if info.filename == name]
    _need(len(rows) == 1 and not rows[0].is_dir() and 0 < rows[0].file_size <= limit, "Missing or oversized audited input member")
    with archive.open(rows[0]) as incoming:
        raw = incoming.read(limit + 1)
    _need(len(raw) == rows[0].file_size, "Audited input member changed size")
    return raw


def _title(value):
    return (isinstance(value, str) and 0 < len(value) <= 192 and len(value.encode("utf-8")) <= 768
            and not any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f or 0xd800 <= ord(c) <= 0xdfff
                        or c in "\u2028\u2029" for c in value))


def _render(catalog):
    _need(len(json.dumps(catalog, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")) <= MAX_CATALOG_BYTES,
          "MP4 title catalog exceeds native configuration budget")
    provenance = {"packs": PACKS, "policy": "three-dimensional-music-timeline-title-v1",
                  "source_music_json_sha256": MUSIC_JSON_SHA256, "source_sha256": SOURCE_SHA256, "timeline_count": 77}
    return ('''# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generated public MV display titles. Rebuild with tools/build_mp4_titles.py.

Build-only SQLCipher inputs are pinned below; mobile runtime imports no decoder.
Translated titles are presentation data and never identify an export job.
"""

SOURCE_PROVENANCE = ''' + json.dumps(provenance, ensure_ascii=True, sort_keys=True, indent=4)
            + "\n\n_CATALOG = " + json.dumps(catalog, ensure_ascii=True, sort_keys=True, indent=4) + '''


def title_catalog():
    """Return fresh, bounded public display maps for the current interface locale."""
    return {language: dict(titles) for language, titles in _CATALOG.items()}
''').encode("utf-8")


def build(server_data):
    descriptor = os.open(Path(server_data), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == SOURCE_BYTES,
              "Expected the pinned bounded ServerData.zip")
        _need(hashlib.file_digest(stream, "sha256").hexdigest() == SOURCE_SHA256, "ServerData.zip SHA-256 differs from audited source")
        _need(_stamp(before) == _stamp(os.fstat(stream.fileno())), "ServerData.zip changed during verification")
        stream.seek(0)
        # Imports remain build-only; the generated runtime module has no codec dependency.
        from idoly_local.schema import Schema
        from idoly_local.master_build import _sqlcipher_driver
        from idoly_local.master_translation_build import read_master_rows
        driver, _ = _sqlcipher_driver()
        with ZipFile(stream) as archive, tempfile.TemporaryDirectory(prefix="idoly-mp4-titles-") as temporary:
            work = Path(temporary); assets = work / "assets"; assets.mkdir()
            raw = _member(archive, "data/master-json/Music.json", 1024 * 1024)
            _need(hashlib.sha256(raw).hexdigest() == MUSIC_JSON_SHA256, "Original Music JSON SHA-256 differs")
            base_rows = json.loads(raw)
            _need(isinstance(base_rows, list) and len(base_rows) == 130, "Original Music inventory differs")
            definitions = {row["id"]: row for row in base_rows}
            _need(len(definitions) == len(base_rows), "Duplicate original Music ID")
            protocol = work / "schema.pb"
            protocol.write_bytes(_member(archive, "data/protocol/idolypride-6.1.1.pb", 4 * 1024 * 1024))
            schema = Schema.from_descriptor_set(protocol)
            catalog = {}
            for language, pin in sorted(PACKS.items()):
                prefix = "" if language == "ja" else "languages/" + language + "/"
                tag = json.loads(_member(archive, "data/original-master/" + prefix + "master-tag.json", 256 * 1024))
                packs = [pack for pack in tag["masterTagPacks"] if pack.get("type") == "Music"]
                _need(len(packs) == 1 and packs[0]["fileName"] == pin["file_name"] and packs[0]["fileSize"] == pin["file_bytes"], "Selected Music pack differs")
                payload = _member(archive, "data/original-master/assets/master/" + pin["file_name"], 1024 * 1024)
                _need(len(payload) == pin["file_bytes"] and hashlib.sha256(payload).hexdigest() == pin["sha256"], "Music pack SHA-256 differs")
                (assets / pin["file_name"]).write_bytes(payload)
                rows = read_master_rows(schema, driver, assets, packs[0])
                _need(len(rows) == len(definitions) and {row["id"] for row in rows} == definitions.keys(), "Localized Music inventory differs")
                titles = {}
                for row in rows:
                    original = definitions[row["id"]]
                    _need(row.get("assetId") == original.get("assetId") and row.get("is3dAvailable") == original.get("is3dAvailable"), "Localized pack changed MV identity")
                    if row.get("is3dAvailable") is not True:
                        continue
                    asset = row.get("assetId"); title = row.get("name")
                    _need(isinstance(asset, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,183}", asset) and _title(title), "Invalid public MV title")
                    timeline = "tln_live_" + asset
                    _need(timeline not in titles, "Ambiguous 3D timeline title")
                    titles[timeline] = title
                _need(len(titles) == 77, "Audited 3D MV count differs")
                catalog[language] = titles
        _need(_stamp(before) == _stamp(os.fstat(stream.fileno())), "ServerData.zip changed while reading")
    return _render(catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    raw = build(arguments.server_data)
    # Do not overwrite an existing source or follow an output symlink.
    with arguments.output.open("xb") as output:
        output.write(raw)
    print(json.dumps({"module_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "timelines": 77,
                      "server_data_sha256": SOURCE_SHA256}, sort_keys=True))


if __name__ == "__main__":
    main()
