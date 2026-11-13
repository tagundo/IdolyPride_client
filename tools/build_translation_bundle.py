#!/usr/bin/env python3
"""Package prepared KO/EN resource overlays for one server platform."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.translation_bundle_build import build_translation_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("android", "ios"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--text-root", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_translation_bundle(arguments.prepared, arguments.output, platform=arguments.platform,
                                     version=arguments.version, text_root=arguments.text_root)
    arguments.receipt.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("platform", "version", "bytes", "sha256")}))


if __name__ == "__main__":
    main()
