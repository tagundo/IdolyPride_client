#!/usr/bin/env python3
"""Prepare pinned language data and coherent per-platform ADV resource overlays.

This is a build operation. It performs no download and installs no game hooks.
The output belongs under translations/<language>/<platform> in a prepared data
archive or the selected Downloads/IdolyPride translation library.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.resource_translation_build import ZipScriptSource, build_resource_overlay
from idoly_local.text_translation_build import compile_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True,
                        help="Pinned translation local-files directory")
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--language", choices=("ja", "ko", "en"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-manifest", type=Path)
    parser.add_argument("--resource-revision", type=int)
    parser.add_argument("--platform", choices=("android", "ios"))
    parser.add_argument("--adv-source-zip", type=Path,
                        help="Read named scripts from a pinned ZIP without expanding the repository")
    parser.add_argument("--adv-zip-prefix")
    parser.add_argument("--adv-archive-sha256")
    arguments = parser.parse_args()
    choices = (arguments.original_manifest, arguments.resource_revision, arguments.platform)
    if any(value is not None for value in choices) and not all(value is not None for value in choices):
        parser.error("ADV output requires original-manifest, resource-revision and platform together")
    if arguments.language == "ja" and any(value is not None for value in choices):
        parser.error("Japanese uses original resources")
    if any((arguments.adv_source_zip, arguments.adv_zip_prefix, arguments.adv_archive_sha256)) and not all(
            (arguments.adv_source_zip, arguments.adv_zip_prefix, arguments.adv_archive_sha256, arguments.original_manifest)):
        parser.error("Compressed ADV input requires ZIP, prefix, archive SHA-256 and resource overlay settings")
    source = json.loads(arguments.source_manifest.read_text(encoding="utf-8"))
    result = compile_catalog(arguments.source_dir, arguments.output / arguments.language,
                             language=arguments.language, source=source)
    summary = {"language": arguments.language, "prepared_text_coverage": result["coverage"],
               "runtime_ui_translation_connected": False}
    if arguments.original_manifest is not None:
        if arguments.adv_source_zip:
            source["archive_sha256"] = arguments.adv_archive_sha256
        reader = (ZipScriptSource(arguments.adv_source_zip, arguments.adv_zip_prefix,
                                 expected_sha256=arguments.adv_archive_sha256)
                  if arguments.adv_source_zip else nullcontext(None))
        with reader as read_script:
            overlay = build_resource_overlay(arguments.original_manifest.read_bytes(),
                arguments.source_dir / "resource/adv", arguments.output / arguments.language / arguments.platform,
                language=arguments.language, revision=arguments.resource_revision, source=source,
                read_script=read_script)
        summary["adv_resource_coverage"] = overlay["coverage"]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
