#!/usr/bin/env python3
"""Rebuild pinned Korean ADV/text while retaining existing translated images.

Only public, immutable translation input is downloaded. No pixels are generated
or re-encoded; the existing 667 platform image bundles and their proofs survive
byte for byte. Japanese and English resources are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "data/latest-korean-translations-pin.json"
MAX_SOURCE = 192 * 1024 * 1024
CHUNK = 64 * 1024
sys.path.insert(0, str(ROOT / "src"))


def need(ok, code):
    if not ok:
        raise ValueError(code)


def identity(path):
    path = Path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode), "translation_regular_file_required")
    with path.open("rb") as incoming:
        return {"bytes": info.st_size, "sha256": hashlib.file_digest(incoming, "sha256").hexdigest()}


def _row(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def pins():
    raw = PIN.read_bytes()
    need(0 < len(raw) <= 64 * 1024, "translation_pin_bound")
    value = json.loads(raw)
    source = value.get("source", {})
    revision = source.get("revision", "")
    need(value.get("schema") == 1 and source.get("repository") == "https://github.com/CyleAR/ipr-translation-data-ko"
         and re.fullmatch(r"[0-9a-f]{40}", revision) is not None
         and source.get("data_terms") == "NOASSERTION"
         and value["archive"].get("url") == "https://codeload.github.com/CyleAR/ipr-translation-data-ko/zip/" + revision
         and value["archive"].get("prefix") == "ipr-translation-data-ko-" + revision + "/local-files/",
         "translation_source_pin_invalid")
    for row in (value["archive"], *(v["base"] for v in value["platforms"].values()),
                *(v["output"] for v in value["platforms"].values()),
                *(v["original_manifest"] for v in value["platforms"].values())):
        need(type(row.get("bytes")) is int and 0 < row["bytes"] <= MAX_SOURCE
             and isinstance(row.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
             "translation_input_pin_invalid")
    need(set(value["platforms"]) == {"android", "ios"}, "translation_platform_inventory_differs")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch_source(destination, *, pin=None):
    pin = pins() if pin is None else pin
    row = pin["archive"]
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".partial")
    need(not destination.exists() and not destination.is_symlink()
         and not partial.exists() and not partial.is_symlink(), "translation_fresh_source_required")
    owned = None
    try:
        with build_opener(NoRedirect()).open(Request(row["url"], headers={"Accept-Encoding": "identity"}), timeout=90) as source:
            need(source.status == 200 and source.headers.get("Content-Encoding", "identity") == "identity",
                 "translation_source_http_invalid")
            with partial.open("xb") as output:
                opened = os.fstat(output.fileno())
                owned = (opened.st_dev, opened.st_ino)
                count, digest = 0, hashlib.sha256()
                while block := source.read(CHUNK):
                    count += len(block)
                    need(count <= row["bytes"], "translation_source_size_exceeded")
                    digest.update(block)
                    output.write(block)
            need({"bytes": count, "sha256": digest.hexdigest()} == {k: row[k] for k in ("bytes", "sha256")},
                 "translation_source_digest_differs")
        # Exclusive publication also rejects a destination created meanwhile.
        current = partial.lstat()
        need(stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == owned,
             "translation_owned_partial_changed")
        os.link(partial, destination, follow_symlinks=False)
        partial.unlink()
    finally:
        if owned is not None:
            try:
                current = partial.lstat()
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == owned:
                    partial.unlink()
    return {k: row[k] for k in ("bytes", "sha256")}


def _member(archive, name, *, maximum):
    matches = [info for info in archive.infolist() if info.filename == name]
    need(len(matches) == 1, "translation_member_inventory_differs")
    info = matches[0]
    need(not info.flag_bits & 1 and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
         and 0 < info.file_size <= maximum, "translation_member_bound")
    with archive.open(info) as incoming:
        raw = incoming.read(maximum + 1)
    need(len(raw) == info.file_size, "translation_member_size_differs")
    return raw


def _text_inputs(source, prefix, output):
    """Expand only the small catalog inputs; ADV/images remain compressed."""
    chosen = {}
    for info in source.infolist():
        if not info.filename.startswith(prefix):
            continue
        relative = info.filename[len(prefix):]
        if relative not in ("localization.json", "phoneSubtitles.json") and not re.fullmatch(r"genericTrans/[A-Za-z0-9_.-]+\.json", relative):
            continue
        need(relative not in chosen, "translation_duplicate_catalog_input")
        chosen[relative] = info
    need(0 < len(chosen) <= 256 and sum(i.file_size for i in chosen.values()) <= 16 * 1024 * 1024,
         "translation_catalog_input_bound")
    for name in sorted(chosen):
        raw = _member(source, prefix + name, maximum=4 * 1024 * 1024)
        target = output / PurePosixPath(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as outgoing:
            outgoing.write(raw)


def refresh(source_bundle, server_data, source_archive, output, *, platform, pin=None):
    # Match the Android/iOS runtime's complete unknown-field wire serialization.
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    from idoly_local.bundled_translations import validate_translation_bundle
    from idoly_local.resource_translation_build import ZipScriptSource, build_resource_overlay
    from idoly_local.text_translation_build import compile_catalog
    from idoly_local.translation_bundle_build import build_translation_bundle_overlay

    pin = pins() if pin is None else pin
    need(platform in ("android", "ios"), "translation_platform_invalid")
    settings = pin["platforms"][platform]
    source_bundle, server_data, source_archive, output = map(Path, (source_bundle, server_data, source_archive, output))
    need(not output.exists() and not output.is_symlink(), "translation_fresh_output_required")
    need(identity(source_archive) == {k: pin["archive"][k] for k in ("bytes", "sha256")},
         "translation_source_archive_differs")
    base = settings["base"]
    validate_translation_bundle(source_bundle, expected_sha256=base["sha256"], expected_bytes=base["bytes"], platform=platform)
    with ZipFile(server_data) as payload:
        original = _member(payload, settings["original_manifest"]["path"], maximum=8 * 1024 * 1024)
    need(_row(original) == {k: settings["original_manifest"][k] for k in ("bytes", "sha256")},
         "translation_original_manifest_differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".korean-refresh-", dir=output.parent) as temporary:
        work = Path(temporary)
        with ZipFile(source_bundle) as base_archive:
            old = json.loads(_member(base_archive, f"translations/ko/{platform}/manifest.json", maximum=8 * 1024 * 1024))
            path = work / "old-objects.zip"
            with base_archive.open(f"translations/ko/{platform}/objects.zip") as incoming, path.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
        images = {row["name"]: row for row in old["changed_images"]}
        need(len(images) == settings["image_count"] == 667, "translation_preserved_image_inventory_differs")
        with ZipFile(path) as objects, ZipScriptSource(source_archive, pin["archive"]["prefix"] + "resource/adv/",
                expected_sha256=pin["archive"]["sha256"], max_archive_bytes=MAX_SOURCE) as scripts:
            def image(name):
                row = images[name]
                raw = _member(objects, row["local"]["cache_key"] + ".bin", maximum=64 * 1024 * 1024)
                need(_row(raw) == {"bytes": row["local"]["size"], "sha256": row["local"]["sha256"]},
                     "translation_preserved_image_digest_differs")
                return raw, {"original_sha256": row["original"]["sha256"], "output_sha256": row["local"]["sha256"],
                             "output_bytes": len(raw), "png": row["png"], "texture": row["texture"]}
            report = build_resource_overlay(original, work, work / "ko", language="ko",
                revision=settings["revision"], source=pin["source"], read_script=scripts,
                image_names=set(images), image_source=old["image_source"], read_image=image,
                max_archive_bytes=128 * 1024 * 1024)
        need(report["coverage"]["translated"] == pin["adv_count"]
             and report["changed_images"] == old["changed_images"], "translation_coverage_or_image_preservation_differs")
        with ZipFile(source_archive) as source:
            _text_inputs(source, pin["archive"]["prefix"], work / "text-inputs")
        text = compile_catalog(work / "text-inputs", work / "text", language="ko", source=pin["source"])
        bundle = build_translation_bundle_overlay(source_bundle, work / "ko", work / "result.zip", platform=platform,
            version=pin["version"], expected_source_sha256=base["sha256"], expected_source_bytes=base["bytes"],
            text_ko_dir=work / "text")
        need({k: bundle[k] for k in ("bytes", "sha256", "manifest_sha256")} == settings["output"],
             "translation_output_pin_differs")
        need(all(not name.startswith("en/") or row == bundle["index"]["files"][name]
                 for name, row in bundle["preserved_files"].items()), "translation_english_preservation_differs")
        os.link(work / "result.zip", output, follow_symlinks=False)
    return {"schema": 1, "platform": platform, "source": pin["source"],
            "source_archive": {k: pin["archive"][k] for k in ("bytes", "sha256")},
            "bytes": bundle["bytes"], "sha256": bundle["sha256"], "manifest_sha256": bundle["manifest_sha256"],
            "coverage": report["coverage"], "text_coverage": text["coverage"], "image_count": len(images),
            "preserved_image_bytes_verified": True, "new_images_generated": False,
            "preserved_files": bundle["preserved_files"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("build")
    for name in ("base", "server-data", "source", "output", "report"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--platform", choices=("android", "ios"), required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        report = fetch_source(args.output)
    else:
        report = refresh(args.base, args.server_data, args.source, args.output, platform=args.platform)
        with args.report.open("x", encoding="utf-8") as outgoing:
            outgoing.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("bytes", "sha256")}))


if __name__ == "__main__":
    main()
