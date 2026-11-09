#!/usr/bin/env python3
"""Build local SQLCipher master packs from JSON using exact client descriptors."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Support direct invocation before the project is installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.master_build import build_master_packs
from idoly_local.schema import Schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-dir", required=True, type=Path, help="Source JSON master repository")
    parser.add_argument("--schema", required=True, type=Path, help="Exact-client FileDescriptorSet .pb")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; existing data is preserved")
    parser.add_argument("--table", action="append", help="Build only selected tables for a prototype (repeatable)")
    args = parser.parse_args()
    try:
        schema = Schema.from_descriptor_set(args.schema)
        report = build_master_packs(schema, args.master_dir, args.output, tables=args.table)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Master build failed: {exc}\n")
    print(f"Built {report['table_count']} SQLCipher 4 packs / {report['row_count']} rows; "
          f"applied {report['alias_field_count']} verified legacy field aliases.")
    print(args.output / "master-tag.json")
    print("Client consumption remains unverified on device.")


if __name__ == "__main__":
    main()
