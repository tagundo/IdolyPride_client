#!/usr/bin/env python3
"""Compile one pinned Korean master refresh; freeze encrypted bytes with proof.

Use the locked project environment: uv run --locked --extra master python ...
Raw SQLCipher compilations have random salts. Only applying this frozen overlay
has an exact output identity; the compiler proves deterministic semantic rows.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import korean_server_data_pin as frozen


def load(path):
    return frozen.latest()._json(Path(path).read_bytes())


def rows_hash(rows):
    return hashlib.sha256(frozen.canonical(rows)).hexdigest()


def text_changes(before, after):
    """Independent recursive preservation audit: only string text leaves vary."""
    from idoly_local.master_translation_build import TEXT_FIELDS
    changed = {}
    def walk(old, new, path=()):
        if old == new:
            return
        if type(old) is dict and type(new) is dict:
            frozen.need(old.keys() == new.keys(), "korean_row_structure_changed")
            for key in old:
                walk(old[key], new[key], (*path, key))
        elif type(old) is list and type(new) is list:
            frozen.need(len(old) == len(new), "korean_row_count_changed")
            for index, (left, right) in enumerate(zip(old, new, strict=True)):
                walk(left, right, (*path, index))
        else:
            field = next((part for part in reversed(path) if type(part) is str), None)
            frozen.need(type(old) is str and type(new) is str and field in TEXT_FIELDS,
                        "korean_nontext_field_changed")
            changed[field] = changed.get(field, 0) + 1
    walk(before, after)
    return changed


def compile_refresh(base, source_archive, work, output, overlay, pin_path):
    from idoly_local.schema import Schema
    from idoly_local.master_build import _sqlcipher_driver
    from idoly_local.master_translation_build import (
        build_translation_master_overlay, read_master_rows, read_translation, translate_rows)
    from idoly_local.master_sort_build import build_sort_master_overlays, sort_rows
    helper = frozen.latest()
    original = helper.verify_payload(base)
    frozen.need(frozen.file_pin(source_archive) == frozen.SOURCE_ARCHIVE, "korean_source_archive_differs")
    for path in (work, output, overlay, pin_path):
        frozen.need(not path.exists() and not path.is_symlink(), "korean_fresh_compile_path_required")
    work.mkdir(parents=True)
    public = work / "public"
    with ZipFile(base) as archive:
        frozen.archive_rows(archive)
        # The complete base has already passed the strict source-frozen verifier.
        archive.extractall(public)
    data = public / "data"
    pool = data / "original-master/assets/master"
    schema = Schema.from_descriptor_set(data / "protocol/idolypride-6.1.1.pb")
    driver, cipher = _sqlcipher_driver()
    translations = work / "masterTrans"
    translations.mkdir()
    source_files = {}
    prefix = f"ipr-translation-data-ko-{frozen.REVISION}/local-files/masterTrans/"
    with ZipFile(source_archive) as archive:
        candidates = [info for info in archive.infolist() if info.filename.startswith(prefix) and not info.is_dir()]
        frozen.need(len(candidates) == 90 and len({info.filename for info in candidates}) == 90,
                    "korean_source_inventory_differs")
        for info in candidates:
            name = info.filename.removeprefix(prefix)
            frozen.need("/" not in name and info.file_size <= 8*frozen.MIB, "korean_source_member_invalid")
            (translations / name).write_bytes(archive.read(info))
            _document, measured = read_translation(translations / name, provenance=True)
            source_files[name] = measured
    source = {"repository": frozen.REPOSITORY, "revision": frozen.REVISION,
              "license": "NOASSERTION", "license_note":
              "No root LICENSE in this pinned upstream data repository; Hoshimi-localify module GPL-3.0 is separate.",
              "files": source_files}
    public_source = {key: value for key, value in source.items() if key != "files"}
    old_coverage = load(data / "original-master/languages/ko/coverage.json")
    changed_source = sorted(name for name in source_files if source_files[name] != old_coverage["source_files"].get(name))
    frozen.need(changed_source, "korean_changed_source_inventory_differs")
    proof = {"schema": 1, "status": "PASS", "master_version": helper.MASTER_VERSION,
             "schema_sha256": schema.fingerprint, "sqlcipher_version": cipher,
             "raw_compile_repeat_byte_identity_claim": False, "sqlcipher_bytes_frozen": True,
             "changed_source_files": changed_source, "modes": {}}
    locales, generated = {}, {}
    def merge(stage):
        for path in (stage / "assets/master").iterdir():
            target = pool / path.name
            if target.exists():
                frozen.need(frozen.file_pin(target) == frozen.file_pin(path), "korean_generated_pack_collision")
            else:
                shutil.copyfile(path, target)
                generated["data/original-master/assets/master/" + path.name] = target
    previous_normal = load(data / "original-master/languages/ko/master-tag.json")
    for mode in ("normal", "media"):
        stem = "" if mode == "normal" else "media-"
        base_tag = load(data / "original-master" / (stem + "master-tag.json"))
        base_packs = {pack["type"]: pack for pack in base_tag["masterTagPacks"]}
        old_tag = load(data / "original-master/languages/ko" / (stem + "master-tag.json"))
        # Prior packs are only candidates. The builder validates expected row
        # identity and re-reads every candidate before retaining its exact bytes.
        reuse = work / ("reuse-" + mode)
        (reuse / "assets/master").mkdir(parents=True)
        for path in pool.iterdir():
            (reuse / "assets/master" / path.name).hardlink_to(path)
        if mode == "media":
            normal = load(work / "language-normal/master-tag.json")
            old_normal = {pack["type"]: pack for pack in previous_normal["masterTagPacks"]}
            latest_normal = {pack["type"]: pack for pack in normal["masterTagPacks"]}
            old_tag["masterTagPacks"] = [latest_normal[pack["type"]] if pack == old_normal[pack["type"]]
                                         else pack for pack in old_tag["masterTagPacks"]]
        (reuse / "master-tag.json").write_bytes(frozen.canonical(old_tag))
        (reuse / "coverage.json").write_bytes(frozen.canonical({"language": "ko", "schema_sha256": schema.fingerprint,
                                                               "source": public_source, "source_files": source_files}))
        stage = work / ("language-" + mode)
        report = build_translation_master_overlay(schema, base_tag, pool, translations, stage,
            language="ko", source=source, media_mode=mode == "media", reuse_overlay=reuse)
        merge(stage)
        tag = load(stage / "master-tag.json")
        packs = {pack["type"]: pack for pack in tag["masterTagPacks"]}
        evidence = {"readback_verified": True, "untranslated_pack_entries_preserved": True,
                    "translated_tables": 0, "tables": {}, "sort_variants": 9, "sorts": {}}
        translated_rows = {}
        for table, pack in packs.items():
            status = report["tables"].get(table, {}).get("status")
            if status != "translated":
                frozen.need(pack == base_packs[table], "korean_untranslated_pack_changed")
                continue
            before = read_master_rows(schema, driver, pool, base_packs[table])
            document, _ = read_translation(translations / (table + ".json"))
            expected, counts = translate_rows(schema, table, before, document, media_mode=mode == "media")
            readback = read_master_rows(schema, driver, pool, pack)
            frozen.need(readback == expected, "korean_translation_readback_differs")
            changed = text_changes(before, readback)
            evidence["tables"][table] = {"rows": len(expected), "expected_rows_sha256": rows_hash(expected),
                "readback_rows_sha256": rows_hash(readback), "changed_text_fields": changed,
                "nontext_fields_preserved": True, "translation_sha256": source_files[table + ".json"]["sha256"],
                "changed_fields": counts["changed_fields"]}
            translated_rows[table] = readback
        evidence["translated_tables"] = len(evidence["tables"])
        rows = {table: translated_rows.get(table) or read_master_rows(schema, driver, pool, packs[table])
                for table in ("Music", "Costume", "PhotoQuestMusic")}
        sorts = work / ("sort-" + mode)
        sort = build_sort_master_overlays(schema, tag, rows, sorts, language="ko", source=mode)
        # Retain existing sort pack bytes when their semantic identity is the
        # same, after verifying old encrypted rows against the new expectation.
        old_sort = load(data / "original-master/languages/ko" / (stem + "master-sort.json"))
        for table, choices in sort["variants"].items():
            for choice, variant in choices.items():
                expected = sort_rows(table, rows[table], choice, music_rows=rows["Music"])
                prior = old_sort["variants"][table][choice]
                if prior["pack"]["fileName"] == variant["pack"]["fileName"]:
                    frozen.need(read_master_rows(schema, driver, pool, prior["pack"]) == expected,
                                "korean_prior_sort_readback_differs")
                    variant.update(deepcopy(prior))
                    (sorts / "assets/master" / variant["pack"]["fileName"]).unlink()
                readback = read_master_rows(schema, driver, [pool, sorts / "assets/master"], variant["pack"])
                frozen.need(readback == expected, "korean_sort_readback_differs")
                frozen.need([{k: v for k, v in row.items() if k != "order"} for row in readback]
                            == [{k: v for k, v in row.items() if k != "order"} for row in rows[table]],
                            "korean_sort_nonorder_fields_changed")
                evidence["sorts"][table + ":" + choice] = {"rows": len(readback),
                    "expected_rows_sha256": rows_hash(expected), "readback_rows_sha256": rows_hash(readback),
                    "nonorder_fields_preserved": True}
        merge(sorts)
        directory = data / "original-master/languages/ko"
        for origin, target in ((stage / "master-tag.json", stem + "master-tag.json"),
                               (stage / "coverage.json", "coverage.json" if mode == "normal" else "media-coverage.json")):
            shutil.copyfile(origin, directory / target)
        (directory / (stem + "master-sort.json")).write_bytes(frozen.canonical(sort) + b"\n")
        locales[mode] = {"tag_version": tag["version"], "tag_sha256": frozen.digest(directory / (stem + "master-tag.json")),
            "pack_count": 202, "table_names": sorted(packs),
            "sort_manifest_sha256": frozen.digest(directory / (stem + "master-sort.json"))}
        proof["modes"][mode] = evidence
    for name in frozen.METADATA:
        generated[name] = public / name
    overlay.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_zip(overlay, generated, lambda name: generated[name].read_bytes())
    with ZipFile(overlay) as archive:
        overlay_rows = frozen.archive_rows(archive, overlay=True)
    inventory = {row["path"]: row for row in original["members"]}
    inventory.update({row["path"]: row for row in overlay_rows})
    members = [inventory[name] for name in sorted(inventory)]
    result = deepcopy(original)
    result.update(members=members, entries=len(members)+1, member_names=sorted([*inventory, frozen.MANIFEST]),
                  member_inventory_sha256=rows_hash(members))
    pin = {"schema": 1, "policy": frozen.POLICY, "base_payload": helper.output_pin(),
           "source": {**public_source, "files": source_files, "archive": frozen.SOURCE_ARCHIVE},
           "source_components": frozen.source_hashes(), "overlay": {**frozen.file_pin(overlay), "members": overlay_rows},
           "output": result, "preservation": frozen.preservation(original["members"], members),
           "semantic_proof": proof, "locales": locales}
    with ZipFile(base) as archive, ZipFile(overlay) as frozen_overlay:
        manifest = frozen.refreshed_manifest(helper._member(archive, frozen.MANIFEST), pin)
        result["payload_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        frozen.write_composed_payload(output, result["member_names"], archive, frozen_overlay, manifest)
    result.update(frozen.file_pin(output))
    pin_path.parent.mkdir(parents=True, exist_ok=True)
    pin_path.write_bytes(frozen.canonical(pin) + b"\n")
    return pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "source-archive", "work", "output", "overlay", "pin"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    pin = compile_refresh(args.base, args.source_archive, args.work, args.output, args.overlay, args.pin)
    print(json.dumps({"status": "PASS", "output": pin["output"]["sha256"], "overlay_bytes": pin["overlay"]["bytes"],
                      "added_packs": len(pin["preservation"]["added_paths"]), "source_revision": frozen.REVISION}))


if __name__ == "__main__":
    main()
