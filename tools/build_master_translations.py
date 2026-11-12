#!/usr/bin/env python3
"""Build one pinned ordinary/media language overlay; no download or runtime work."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from idoly_local.master_translation_build import build_translation_master_overlay
from idoly_local.schema import Schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--master-tag", type=Path, required=True)
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--extra-pack-root", type=Path, action="append", default=[],
                        help="Explicit generated media pack directory; original archive remains immutable")
    parser.add_argument("--translations", type=Path, required=True, help="Pinned local-files/masterTrans directory")
    parser.add_argument("--source-manifest", type=Path, required=True, help="Public repository/revision/data terms + exact file hashes")
    parser.add_argument("--language", choices=("ko", "en"), required=True)
    parser.add_argument("--media-mode", action="store_true")
    parser.add_argument("--reuse-overlay", type=Path, help="Reuse row-verified ordinary packs while building media")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_translation_master_overlay(Schema.from_descriptor_set(args.schema), args.master_tag,
        [args.pack_root, *args.extra_pack_root], args.translations, args.output, language=args.language,
        source=json.loads(args.source_manifest.read_text()), media_mode=args.media_mode, reuse_overlay=args.reuse_overlay)
    print(json.dumps({key: report[key] for key in ("language", "media_mode", "pack_count", "changed_pack_count", "version")}, indent=2))


if __name__ == "__main__":
    main()
