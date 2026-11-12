"""Precompute Localify master text into ordinary client SQLCipher packs.

Build-only: no game hooks, network access, account storage or frame callbacks.
Japanese rows remain the fallback; only explicitly allowed string leaves change.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

POLICY = "local-master-text-v1"
LANGUAGES = ("ja", "ko", "en")
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PART = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[([0-9]{1,6})\])?\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
# Audited terminal fields in the actual Localify translation rules. IDs, asset
# references, order/conditions, numeric fields and arbitrary strings are absent.
TEXT_FIELDS = frozenset((
    "age", "appealText", "arranger", "birthday", "branchCautionText", "branchFirstText",
    "catchphrase", "characterArrivalText", "choiceText", "composer", "cv", "dailyRewardName",
    "description", "displayConditionDescription", "dreamAreaName", "eventName", "evolveMessage",
    "excursionFirstText", "favorite", "firstName", "functionMaintenanceMessage",
    "functionMaintenanceTitle", "groupName", "guageName", "hometown", "howToGet", "idiom",
    "longDescription", "lyricist", "managerCallText", "managerText", "name", "obtainMessage",
    "placeName", "precaution", "profile", "shortDescription", "shortProfile", "singer", "text",
    "texts", "theme", "title", "tutorialAdvSubTitle", "tutorialAdvTitle", "unfavorite",
    "unlockDescription", "word", "zodiacSign"))
_COVER_IDS = frozenset(("music-liz-009-unit", "music-sun-005-moon", "music-thrx-001-unit", "music-tri-005-unit"))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate translation JSON key")
        result[key] = value
    return result


def read_translation(path, *, provenance=False):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_DOCUMENT_BYTES:
        raise ValueError("Translation input must be a bounded regular JSON file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Translation JSON grew beyond its size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid translation JSON") from error
    digest = hashlib.sha256(raw).hexdigest()
    if provenance:
        return value, {"bytes": len(raw), "sha256": digest,
                       "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    return value, digest


def _field(descriptor, name):
    return next((field for field in descriptor.fields
                 if field.name == name or field.json_name == name), None)


def _path(descriptor, text, *, rule=False):
    from google.protobuf.descriptor import FieldDescriptor
    parts = []
    segments = text.split(".")
    for index, segment in enumerate(segments):
        match = _PART.fullmatch(segment)
        field = _field(descriptor, match[1]) if match else None
        if field is None:
            raise ValueError("Translation refers to an unknown protobuf field")
        position = int(match[2]) if match[2] is not None else None
        if position is not None and not field.is_repeated:
            raise ValueError("Translation index requires an existing repeated field")
        if not rule and field.is_repeated and position is None:
            raise ValueError("Translation requires an explicit repeated-field index")
        parts.append((field, position))
        if index != len(segments)-1:
            if field.message_type is None or field.message_type.GetOptions().map_entry:
                raise ValueError("Translation traversal requires an ordinary protobuf message")
            descriptor = field.message_type
        elif field.type != FieldDescriptor.TYPE_STRING or field.name not in TEXT_FIELDS:
            raise ValueError("Translation target is outside the human-text allowlist")
    return parts


def _rule_key(parts):
    return tuple(field.name for field, _index in parts)


def _row_key(row, fields):
    values = []
    for field in fields:
        value = row.get(field.name, row.get(field.json_name))
        if type(value) not in (str, int) or "|" in str(value):
            raise ValueError("Ambiguous translation primary key")
        values.append(str(value))
    return "|".join(values)


def _replace(row, parts, translated):
    current = row
    for index, (field, position) in enumerate(parts):
        key = field.name if field.name in current else field.json_name
        if field.is_repeated:
            values = current.get(key)
            if not isinstance(values, list) or position >= len(values):
                return False
            if index == len(parts)-1:
                if not isinstance(values[position], str):
                    raise ValueError("Original text field is not a string")
                changed = values[position] != translated
                values[position] = translated
                return changed
            current = values[position]
        elif index == len(parts)-1:
            if not isinstance(current.get(key, ""), str):
                raise ValueError("Original text field is not a string")
            changed = current.get(key, "") != translated
            current[key] = translated
            return changed
        else:
            current = current.get(key)
        if not isinstance(current, dict):
            return False
    return False


def translate_rows(schema, table, rows, document, *, media_mode=False):
    """Translate explicit protobuf text leaves without changing source rows.

    Unknown IDs and missing nested indices fall back to Japanese. Malformed
    rules, non-text fields and data keys outside the declared rules fail closed.
    """
    from .master_build import _annotated_tables
    if (type(media_mode) is not bool or not isinstance(rows, list)
            or not isinstance(document, dict) or set(document) != {"rule", "data"}
            or not isinstance(document["rule"], list) or not document["rule"]
            or not isinstance(document["data"], dict)):
        raise ValueError("Expected a Localify master translation document")
    inventory = _annotated_tables(schema)
    if table not in inventory:
        raise ValueError("Translation table is absent from the master schema")
    descriptor, primary = inventory[table]
    rules, keys = {}, None
    for rule in document["rule"]:
        if not isinstance(rule, str) or len(rule) > 512 or "|" not in rule:
            raise ValueError("Invalid translation rule")
        names = rule.split("|")
        fields = [_field(descriptor, name) for name in names[:-1]]
        if (any(field is None for field in fields) or len(fields) != len(set(names[:-1]))
                or {field.name for field in fields} != {field.name for field in primary}):
            raise ValueError("Translation primary keys differ from the annotated master keys")
        if keys is not None and [field.name for field in keys] != [field.name for field in fields]:
            raise ValueError("Inconsistent translation primary-key order")
        keys = fields
        path = _path(descriptor, names[-1], rule=True)
        identity = _rule_key(path)
        if identity in rules:
            raise ValueError("Duplicate translation rule")
        rules[identity] = path
    output = copy.deepcopy(rows)
    indexed = {}
    for row in output:
        if not isinstance(row, dict):
            raise ValueError("Original master row must be an object")
        identity = _row_key(row, keys)
        if identity in indexed:
            raise ValueError("Original master primary keys are not unique")
        indexed[identity] = row
    applied = missing = empty = unchanged = 0
    cover_names = {}
    for key, translated in document["data"].items():
        if (not isinstance(key, str) or len(key) > 2048 or not isinstance(translated, str)
                or len(translated.encode("utf-8")) > 65536 or "\x00" in translated):
            raise ValueError("Invalid translation text entry")
        pieces = key.split("|")
        if len(pieces) != len(keys)+1:
            raise ValueError("Translation entry has an ambiguous primary key")
        parts = _path(descriptor, pieces[-1])
        if _rule_key(parts) not in rules:
            raise ValueError("Translation entry has no matching declared text rule")
        identity = "|".join(pieces[:-1])
        row = indexed.get(identity)
        if row is None:
            missing += 1
            continue
        if not translated:
            empty += 1
            continue
        if media_mode and table == "PhotoQuestMusic" and identity in _COVER_IDS:
            if pieces[-1] == "name":
                continue  # Preserve the existing distinct cover label.
            if pieces[-1] == "description":
                cover_names[identity] = translated.strip()
        if _replace(row, parts, translated):
            applied += 1
        else:
            unchanged += 1
    for identity, name in cover_names.items():
        if name and indexed[identity].get("name") != name:
            indexed[identity]["name"] = name
            applied += 1
    return output, {"rows": len(rows), "entries": len(document["data"]), "changed_fields": applied,
                    "missing_rows": missing, "empty_fallback": empty, "unchanged_or_missing_path": unchanged}


def read_master_rows(schema, driver, pack_root, pack):
    """Read one explicit public pack, validating its SQL/protobuf roundtrip."""
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict, ParseDict
    table, filename = pack.get("type"), pack.get("fileName")
    if (not isinstance(table, str) or not _NAME.fullmatch(table) or not isinstance(filename, str)
            or filename in (".", "..") or any(c in filename for c in ("/", "\\", "\0"))
            or not isinstance(pack.get("cryptoKey"), str) or not _HASH.fullmatch(pack["cryptoKey"])
            or type(pack.get("fileSize")) is not int or not 0 < pack["fileSize"] <= 64*1024*1024):
        raise ValueError("Invalid public master pack metadata")
    root = Path(pack_root).resolve(strict=True)
    path = root / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size != pack["fileSize"]:
        raise ValueError("Public master pack is missing or differs in size")
    message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
    connection = driver.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute(f'PRAGMA key="x\'{pack["cryptoKey"]}\'"')
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Public master SQLCipher integrity check failed")
        rows = []
        for (raw,) in connection.execute('SELECT data FROM "' + table + '" ORDER BY rowid'):
            parsed = message.FromString(bytes(raw))
            row = MessageToDict(parsed, preserving_proto_field_name=True,
                                use_integers_for_enums=True, always_print_fields_with_no_presence=True)
            if ParseDict(row, message()).SerializeToString(deterministic=True) != parsed.SerializeToString(deterministic=True):
                raise ValueError("Public master has non-roundtrippable protobuf fields")
            rows.append(row)
        return rows
    finally:
        connection.close()


def build_translation_master_overlay(schema, base_tag, pack_root, translation_dir, output, *, language, source,
                                     media_mode=False, reuse_overlay=None):
    """Rebuild only translated tables and retain every unrelated tag entry.

    ``source`` records the actual public repository/revision and data terms.
    Caller can copy the generated files into the shared HTTP master directory.
    Nothing mutates the Japanese/backend catalog or existing media policy packs.
    """
    from google.protobuf.json_format import ParseDict
    from .master_build import _annotated_tables, _sqlcipher_driver, build_master_packs
    if language not in ("ko", "en") or type(media_mode) is not bool:
        raise ValueError("Only explicit Korean/English build overlays are supported")
    if (not isinstance(source, dict) or not isinstance(source.get("repository"), str)
            or not source["repository"].startswith("https://github.com/")
            or not isinstance(source.get("revision"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", source["revision"])
            or not isinstance(source.get("license"), str)):
        raise ValueError("Pinned public translation provenance is required")
    base = copy.deepcopy(base_tag if isinstance(base_tag, dict) else json.loads(Path(base_tag).read_text()))
    ParseDict(base, schema.response_type("/api.Master/Get")().masterTag)
    if (set(base) != {"version", "masterTagPacks"} or not base["version"]
            or len(base["masterTagPacks"]) != 202):
        raise ValueError("Complete original MasterTag is required")
    packs = {pack["type"]: pack for pack in base["masterTagPacks"]}
    if (len(packs) != len(base["masterTagPacks"])
            or len({pack["fileName"] for pack in packs.values()}) != len(packs)):
        raise ValueError("MasterTag has duplicate table entries")
    output, translations = Path(output), Path(translation_dir)
    if output.exists() or not translations.is_dir():
        raise ValueError("Choose an unused output and existing translation directory")
    files = sorted(translations.glob("*.json"))
    if len(files) > 202 or sum(file.stat().st_size for file in files) > 64*1024*1024:
        raise ValueError("Translation source exceeds the bounded master catalog")
    source_files = source.get("files")
    if not isinstance(source_files, dict) or set(source_files) != {file.name for file in files}:
        raise ValueError("Exact pinned translation file inventory is required")
    public_source = {key: source[key] for key in ("repository", "revision", "license")}
    if "license_note" in source:
        if not isinstance(source["license_note"], str) or len(source["license_note"]) > 1024:
            raise ValueError("Invalid public data license note")
        public_source["license_note"] = source["license_note"]
    inventory = _annotated_tables(schema)
    driver, _cipher = _sqlcipher_driver()
    coverage, replacements = {}, {}
    reused = {}
    if reuse_overlay is not None:
        reuse_overlay = Path(reuse_overlay)
        prior = json.loads((reuse_overlay / "coverage.json").read_text())
        if (prior.get("language") != language or prior.get("schema_sha256") != schema.fingerprint
                or prior.get("source_files") != source_files or prior.get("source") != public_source):
            raise ValueError("Reusable language packs have different source provenance")
        reused = {pack["type"]: pack for pack in json.loads(
            (reuse_overlay / "master-tag.json").read_text())["masterTagPacks"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".master-language-", dir=output.parent) as temporary:
        work = Path(temporary)
        ready = work / "ready"
        (ready / "assets/master").mkdir(parents=True)
        for file in files:
            table = file.stem
            document, measured = read_translation(file, provenance=True)
            translation_sha = measured["sha256"]
            expected = source_files[file.name]
            if (not isinstance(expected, dict) or set(expected) != {"bytes", "sha256", "git_blob_sha1"}
                    or type(expected["bytes"]) is not int or expected != measured):
                raise ValueError("Translation source differs from its pinned public file inventory")
            if table not in packs or table not in inventory:
                coverage[table] = {"status": "missing_original_table", "translation_sha256": translation_sha}
                continue
            rows = read_master_rows(schema, driver, pack_root, packs[table])
            try:
                translated, counts = translate_rows(schema, table, rows, document, media_mode=media_mode)
            except ValueError:
                # Unsupported schema/rule variants retain the complete original
                # pack; never silently perform a partial unsafe field rewrite.
                coverage[table] = {"status": "unsupported_rule", "translation_sha256": translation_sha}
                continue
            coverage[table] = {"status": "translated" if counts["changed_fields"] else "unchanged",
                               "translation_sha256": translation_sha, **counts}
            if not counts["changed_fields"]:
                continue
            catalog = work / "json"
            raw = json.dumps(translated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            rows_sha = hashlib.sha256(raw).hexdigest()
            name = f"local-language-{language}-{rows_sha[:24]}-{table}.db"
            prior_pack = reused.get(table)
            if prior_pack is not None and prior_pack["fileName"] == name:
                if read_master_rows(schema, driver, reuse_overlay / "assets/master", prior_pack) != translated:
                    raise ValueError("Reusable language pack differs from its exact translated rows")
                prior_path = reuse_overlay / "assets/master" / name
                try:
                    os.link(prior_path, ready / "assets/master" / name)
                except OSError:
                    with prior_path.open("rb") as incoming, (ready / "assets/master" / name).open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing, length=65536)
                replacements[table] = copy.deepcopy(prior_pack)
                coverage[table]["reused_pack"] = True
                coverage[table]["rows_sha256"] = rows_sha
                with prior_path.open("rb") as stream:
                    coverage[table]["pack_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                continue
            catalog.mkdir()
            (catalog / (table + ".json")).write_bytes(raw)
            built = work / "built"
            build_master_packs(schema, catalog, built, tables=[table])
            replacement = json.loads((built / "master-tag.json").read_text())["masterTagPacks"][0]
            if read_master_rows(schema, driver, built / "assets/master", replacement) != translated:
                raise ValueError("Translated SQLCipher/protobuf rows differ after rebuilding")
            generated = built / "assets/master" / replacement["fileName"]
            with generated.open("rb") as stream:
                coverage[table]["pack_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            coverage[table]["rows_sha256"] = rows_sha
            generated.rename(ready / "assets/master" / name)
            replacement.update(fileName=name, downloadUrl="http://127.0.0.1:8080/master/" + name)
            replacements[table] = replacement
            (catalog / (table + ".json")).unlink()
            catalog.rmdir()
            # Only these builder-owned small per-table stages are removed.
            shutil.rmtree(built)
        merged = copy.deepcopy(base)
        identity = {"policy": POLICY, "schema": schema.fingerprint, "language": language,
                    "source": public_source, "source_files": source_files,
                    "base_version": base["version"], "replacements": replacements}
        merged["version"] = "local-language-" + language + "-" + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        merged["masterTagPacks"] = [replacements.get(pack["type"], pack) for pack in base["masterTagPacks"]]
        ParseDict(merged, schema.response_type("/api.Master/Get")().masterTag)
        result = {"schema": 1, "policy": POLICY, "language": language, "media_mode": media_mode,
                  "source": public_source, "source_files": source_files,
                  "source_tag_sha256": hashlib.sha256(json.dumps(base, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                  "schema_sha256": schema.fingerprint, "source_version": base["version"],
                  "version": merged["version"], "pack_count": len(packs), "changed_pack_count": len(replacements),
                  "tables": coverage, "device_verified": False,
                  "limitations": ["Untranslated rows/fields retain Japanese", "ADV dialogue and asset-localized UI are not master data"]}
        (ready / "master-tag.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
        (ready / "coverage.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        if output.exists():
            raise ValueError("Translation output appeared while building")
        ready.rename(output)
    return result
