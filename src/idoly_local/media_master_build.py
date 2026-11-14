"""Build a separate public gallery master overlay; ordinary archives stay intact.

The small JSON contract validator uses only the standard library so the cached
Python 3.13 APK builder can repeat it. SQLCipher/protobuf imports are build-only.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .media_outfit_policy import (COSTUME_IDS, ADMIN_COSTUME_IDS, ADMIN_HAIR_IDS,
    is_audited_work_costume, is_audited_admin_costume, is_audited_admin_hair)


POLICY = "media-outfits-v3"
TABLES = ("PhotoActivity", "PhotoExpression", "Costume", "Hair", "PhotoQuestMusic", "PhotoQuestStage",
          "EventStory", "Setting")
# Keep in step with media_profile.MEDIA_AUDIENCE_CANDIDATES without importing
# its protobuf/runtime dependencies into this stdlib-only contract validator.
MEDIA_AUDIENCE_CANDIDATES = 1000
TAG_NAME = "media-master-tag.json"
TAG_MEMBER = "data/original-master/" + TAG_NAME
PACK_NAMES = {table: POLICY + "-" + table + ".db" for table in TABLES}
PACK_MEMBERS = {table: "data/original-master/assets/master/" + name for table, name in PACK_NAMES.items()}
PAYLOAD_MEMBERS = frozenset((TAG_MEMBER, *PACK_MEMBERS.values()))
TYPE_IDS = ("casl", "gene", "hruh", "idol", "idol-miku", "idol-miku-mizg", "kion", "mizg",
            "mizg-all-ng", "mizg-water-ng", "pajm", "schl", "sd-ambassador", "sd-police", "snro",
            "trbl", "trbl-mizg", "trng", "waso")
COVER_LABEL_IDS = frozenset(("music-liz-009-unit", "music-sun-005-moon", "music-thrx-001-unit",
                             "music-tri-005-unit"))
COSTUME_TYPE_PACK_SHA256 = "42bca0dec00f714e5c3510066a33d465f1d1afcca035eeea9fd315e0c1aa224e"
COSTUME_TYPE_PACK_BYTES = 12288
PACK_COUNT = 202
_PACK_FIELDS = frozenset(("type", "fileName", "fileSize", "cryptoKey", "downloadUrl"))
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate public master JSON key")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_object)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def costume_type_ids(costumes, types):
    if not isinstance(types, list) or any(not isinstance(row, dict) for row in types):
        raise ValueError("Original CostumeType rows are required")
    ids = [row.get("id") for row in types]
    if (any(not isinstance(value, str) for value in ids)
            or len(ids) != len(set(TYPE_IDS)) or set(ids) != set(TYPE_IDS)):
        raise ValueError("Original CostumeType inventory differs from the audited 19 types")
    if not isinstance(costumes, list) or not costumes:
        raise ValueError("Original Costume rows are required")
    used = [row.get("costumeTypeId") if isinstance(row, dict) else None for row in costumes]
    if any(not isinstance(value, str) or value not in TYPE_IDS for value in used):
        raise ValueError("A Costume references an unknown original CostumeType")
    return TYPE_IDS


def expanded_rows(table, rows):
    if table not in TABLES or not isinstance(rows, list) or not rows:
        raise ValueError("Both original photo master tables are required")
    if table == "Setting" and len(rows) != 1:
        raise ValueError("Exactly one original media Setting row is required")
    ids = set()
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids:
            raise ValueError("Original photo master IDs must be nonempty and unique")
        ids.add(row["id"])
        if table == "Setting":
            minimum = row.get("liveMinimumGuaranteedAudienceAmount")
            if type(minimum) is not int or not 0 <= minimum <= 2**31 - 1:
                raise ValueError("Original minimum audience setting is malformed")
            # Normal characters use the raw UserCharacter candidate amount.
            # Mana and collaborators instead use the fan-derived average,
            # clamped by this setting (10 in original 6.1.1). Media fans remain
            # real/unchanged; raise only this separate gallery master minimum.
            changed = copy.deepcopy(row)
            changed["liveMinimumGuaranteedAudienceAmount"] = max(minimum, MEDIA_AUDIENCE_CANDIDATES)
            result.append(changed)
            continue
        if table == "EventStory":
            # ListEvent eligibility does not override the client's master-side
            # visibility checks. The gallery keeps the actual event/episode,
            # thumbnail and Story/ADV references, changing only these gates.
            if not isinstance(row.get("viewConditionId"), str):
                raise ValueError("Original event story visibility condition is malformed")
            episodes = row.get("episodes")
            if not isinstance(episodes, list):
                raise ValueError("Original event story episodes are malformed")
            numbers = set()
            for episode in episodes:
                if (not isinstance(episode, dict) or type(episode.get("episode")) is not int
                        or episode["episode"] <= 0 or episode["episode"] in numbers
                        or not isinstance(episode.get("storyId"), str) or not episode["storyId"]
                        or any(not isinstance(episode.get(name), str)
                               for name in ("viewConditionId", "unlockConditionId"))):
                    raise ValueError("Original event story episode references or conditions are malformed")
                numbers.add(episode["episode"])
            changed = copy.deepcopy(row)
            changed["viewConditionId"] = ""
            for episode in changed["episodes"]:
                episode.update(viewConditionId="", unlockConditionId="")
            result.append(changed)
            continue
        if table in ("Costume", "Hair"):
            if type(row.get("isDisableAdmin")) is not bool:
                raise ValueError("Original master admin flag is malformed")
            if table == "Costume" and type(row.get("isUserUnavailable")) is not bool:
                raise ValueError("Original Costume availability flag is malformed")
            changed = copy.deepcopy(row)
            if table == "Costume" and row["id"] in COSTUME_IDS:
                if row["isUserUnavailable"] is not True or not is_audited_work_costume(row):
                    raise ValueError("An audited bath Costume is not originally unavailable")
                changed["isUserUnavailable"] = False
            admin_ids = ADMIN_COSTUME_IDS if table == "Costume" else ADMIN_HAIR_IDS
            audited = is_audited_admin_costume if table == "Costume" else is_audited_admin_hair
            if row["id"] in admin_ids:
                if row["isDisableAdmin"] is not True or not audited(row):
                    raise ValueError("An audited admin appearance does not match its original row")
                changed["isDisableAdmin"] = False
            result.append(changed)
            continue
        if any(not isinstance(row.get(name), str) for name in ("viewConditionId", "unlockConditionId")):
            raise ValueError("Original photo visibility conditions are malformed")
        if table in ("PhotoQuestMusic", "PhotoQuestStage"):
            changed = copy.deepcopy(row)
            changed.update(viewConditionId="", unlockConditionId="")
            if table == "PhotoQuestMusic" and row["id"] in COVER_LABEL_IDS:
                description = row.get("description")
                if not isinstance(description, str) or not description.rstrip():
                    raise ValueError("An audited cover song must have its original description")
                # The original cell reads only Name. Preserve Description and
                # all leading/internal whitespace, trimming trailing whitespace
                # only in these four media labels (notably music-tri-005-unit).
                changed["name"] = description.rstrip()
            result.append(changed)
            continue
        allowed = row.get("costumeTypeIds")
        force = row.get("forceCostumeTypeId")
        if (not isinstance(allowed, list) or not allowed or any(value not in TYPE_IDS for value in allowed)
                or len(allowed) != len(set(allowed)) or not isinstance(force, str)
                or force and force not in TYPE_IDS):
            raise ValueError("Original photo costume constraints are malformed")
        changed = copy.deepcopy(row)
        changed["costumeTypeIds"] = list(TYPE_IDS)
        changed.update(viewConditionId="", unlockConditionId="")
        result.append(changed)
    if table == "Costume" and (len(COSTUME_IDS) != 21 or not set(COSTUME_IDS).issubset(ids)):
        raise ValueError("The exact 21 audited bath Costumes must be present")
    if table == "Costume" and (len(ADMIN_COSTUME_IDS) != 18 or not set(ADMIN_COSTUME_IDS).issubset(ids)):
        raise ValueError("The exact 18 audited admin Costumes must be present")
    if table == "Hair" and (len(ADMIN_HAIR_IDS) != 19 or not set(ADMIN_HAIR_IDS).issubset(ids)):
        raise ValueError("The exact 19 audited admin Hairs must be present")
    if table == "PhotoQuestMusic" and not COVER_LABEL_IDS.issubset(ids):
        raise ValueError("The exact four audited cover song rows must be present")
    return result


def _tag_packs(tag):
    if (not isinstance(tag, dict) or set(tag) != {"version", "masterTagPacks"}
            or not isinstance(tag["version"], str) or not tag["version"]
            or not isinstance(tag["masterTagPacks"], list) or len(tag["masterTagPacks"]) != PACK_COUNT):
        raise ValueError("Expected the complete original 202-pack MasterTag")
    result, names = {}, set()
    for row in tag["masterTagPacks"]:
        if (not isinstance(row, dict) or set(row) != _PACK_FIELDS
                or not isinstance(row["type"], str) or not row["type"] or row["type"] in result
                or not isinstance(row["fileName"], str) or not row["fileName"]
                or row["fileName"] in (".", "..") or any(c in row["fileName"] for c in ("/", "\\", "\0"))
                or row["fileName"] in names or type(row["fileSize"]) is not int or row["fileSize"] <= 0
                or not isinstance(row["cryptoKey"], str) or not _HEX.fullmatch(row["cryptoKey"])
                or not isinstance(row["downloadUrl"], str)):
            raise ValueError("Invalid or ambiguous original master pack metadata")
        result[row["type"]] = row
        names.add(row["fileName"])
    if not set(TABLES).issubset(result):
        raise ValueError("Original photo master packs are missing")
    return result


def _identities(schema_sha256, original_tag, rows):
    if not isinstance(schema_sha256, str) or not _HEX.fullmatch(schema_sha256):
        raise ValueError("A verified public schema fingerprint is required")
    _tag_packs(original_tag)
    if set(rows) != set(TABLES):
        raise ValueError("Expected the exact photo and Costume JSON tables")
    patched = {table: expanded_rows(table, rows[table]) for table in TABLES}
    # Match master_build's exact canonical source bytes and deterministic keys.
    sources = {table: json.dumps(patched[table], ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
               for table in TABLES}
    identity = {"builder_version": 2, "schema_sha256": schema_sha256,
                "tables": [{"table": table, "source_sha256": _hash(sources[table])} for table in sorted(TABLES)]}
    builder_hash = _hash(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    keys = {table: _hash(b"idoly-local-master-key-v1\0" + bytes.fromhex(builder_hash) + table.encode())
            for table in TABLES}
    policy = {"policy": POLICY, "schema_sha256": schema_sha256,
              "original_tag_sha256": _hash(canonical(original_tag)), "costume_type_ids": TYPE_IDS,
              "bath_costume_ids": sorted(COSTUME_IDS),
              "admin_costume_ids": sorted(ADMIN_COSTUME_IDS), "admin_hair_ids": sorted(ADMIN_HAIR_IDS),
              "cover_label_ids": sorted(COVER_LABEL_IDS), "cover_label_rule": "description.rstrip()",
              "minimum_visual_audience": MEDIA_AUDIENCE_CANDIDATES,
              "source_tables": {table: _hash(canonical(rows[table])) for table in TABLES},
              "patched_tables": {table: _hash(canonical(patched[table])) for table in TABLES}}
    return "local-media-outfits-v1-" + _hash(canonical(policy)), keys, sources, patched


def validate_media_master_tag(original_tag, media_tag, schema_sha256, rows, packs):
    """Check the replacements against original data and actual byte hashes.

    ``packs`` maps each new plain filename to its measured bytes/SHA256. The
    producer separately performs strict protobuf and SQLCipher row roundtrips.
    """
    original, media = _tag_packs(original_tag), _tag_packs(media_tag)
    version, keys, _sources, _patched = _identities(schema_sha256, original_tag, rows)
    if (media_tag["version"] != version or list(original) != list(media)
            or set(packs) != set(PACK_NAMES.values())):
        raise ValueError("Media MasterTag policy, version or inventory differs")
    for table, before in original.items():
        after = media[table]
        if table not in TABLES:
            if after != before:
                raise ValueError("Media overlay changed an unrelated original master pack")
            continue
        name = PACK_NAMES[table]
        proof = packs[name]
        if (not isinstance(proof, dict) or set(proof) != {"bytes", "sha256"}
                or type(proof["bytes"]) is not int or not 0 < proof["bytes"] <= 1024 * 1024
                or proof["bytes"] % 4096 or not isinstance(proof["sha256"], str)
                or not _HEX.fullmatch(proof["sha256"])):
            raise ValueError("Media pack byte provenance is invalid")
        expected = {"type": table, "fileName": name, "fileSize": proof["bytes"], "cryptoKey": keys[table],
                    "downloadUrl": "http://127.0.0.1:8080/master/" + name}
        if after != expected or name in {row["fileName"] for row in original.values()}:
            raise ValueError("Media pack metadata does not match its explicit replacement")
    return {"policy": POLICY, "version": version, "tables": list(TABLES), "costume_types": len(TYPE_IDS),
            "original_pack_count": len(original), "replaced_pack_count": len(TABLES)}


def _pack_path(root, pack):
    root = Path(root).resolve(strict=True)
    path = (root / pack["fileName"]).resolve(strict=True)
    if (pack["type"] not in (*TABLES, "CostumeType") or not path.is_relative_to(root)
            or not path.is_file() or not 0 < pack["fileSize"] <= 1024 * 1024
            or path.stat().st_size != pack["fileSize"]):
        raise ValueError("A public photo master pack is missing, oversized or outside its archive")
    return path


def _file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _decode(schema, driver, root, pack):
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict, ParseDict
    path = _pack_path(root, pack)
    message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + pack["type"]))
    connection = driver.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute(f'PRAGMA key="x\'{pack["cryptoKey"]}\'"')
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("A public master pack failed its integrity check")
        rows = []
        for (raw,) in connection.execute('SELECT data FROM "' + pack["type"] + '" ORDER BY rowid'):
            parsed = message.FromString(bytes(raw))
            row = MessageToDict(parsed, preserving_proto_field_name=True,
                                use_integers_for_enums=True, always_print_fields_with_no_presence=True)
            if (ParseDict(row, message()).SerializeToString(deterministic=True)
                    != parsed.SerializeToString(deterministic=True)):
                raise ValueError("Original photo master has unknown or non-roundtrippable protobuf fields")
            rows.append(row)
        return rows
    finally:
        connection.close()


def build_media_master_overlay(schema, original_tag, original_pack_root, original_json_root, output):
    """Build the gallery packs; never alter the original tag/JSON/archive."""
    from google.protobuf import message_factory
    from google.protobuf.json_format import ParseDict
    from .master_build import build_master_packs, _sqlcipher_driver

    original_tag, original_pack_root = Path(original_tag), Path(original_pack_root)
    output = Path(output)
    if output.exists():
        raise ValueError("Media master output already exists")
    base = read_json(original_tag)
    inventory = _tag_packs(base)
    ParseDict(base, schema.response_type("/api.Master/Get")().masterTag)
    driver, _cipher = _sqlcipher_driver()
    type_pack = inventory.get("CostumeType")
    if (type_pack is None or type_pack["fileSize"] != COSTUME_TYPE_PACK_BYTES
            or _file_hash(_pack_path(original_pack_root, type_pack)) != COSTUME_TYPE_PACK_SHA256):
        raise ValueError("Original CostumeType pack differs from the audited archive")
    types = _decode(schema, driver, original_pack_root, type_pack)
    costume_type_ids(read_json(Path(original_json_root) / "Costume.json"), types)
    rows = {table: read_json(Path(original_json_root) / (table + ".json")) for table in TABLES}
    for table in TABLES:
        if rows[table] != _decode(schema, driver, original_pack_root, inventory[table]):
            raise ValueError("Photo JSON does not match its original protobuf pack")
    version, _keys, sources, patched = _identities(schema.fingerprint, base, rows)
    # Prove that only the allowed field changes, including
    # unchanged force/default/denied-character and all other protobuf fields.
    for table in TABLES:
        message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
        for before, after in zip(rows[table], patched[table], strict=True):
            left, right = ParseDict(before, message()), ParseDict(after, message())
            if table == "EventStory":
                left.ClearField("viewConditionId")
                right.ClearField("viewConditionId")
                for original, gallery in zip(left.episodes, right.episodes, strict=True):
                    for name in ("viewConditionId", "unlockConditionId"):
                        original.ClearField(name)
                        gallery.ClearField(name)
                if left.SerializeToString(deterministic=True) != right.SerializeToString(deterministic=True):
                    raise ValueError("Media overlay changed an event story field outside its explicit allowlist")
                continue
            fields = (("liveMinimumGuaranteedAudienceAmount",) if table == "Setting" else
                      ("isUserUnavailable", "isDisableAdmin") if table == "Costume" else
                      ("isDisableAdmin",) if table == "Hair" else
                      ("viewConditionId", "unlockConditionId", "name") if table == "PhotoQuestMusic" else
                      ("viewConditionId", "unlockConditionId") if table == "PhotoQuestStage" else
                      ("costumeTypeIds", "viewConditionId", "unlockConditionId"))
            for field in fields:
                left.ClearField(field)
                right.ClearField(field)
            if left.SerializeToString(deterministic=True) != right.SerializeToString(deterministic=True):
                raise ValueError("Media overlay changed a field outside its explicit allowlist")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".media-master-", dir=output.parent) as temporary:
        work = Path(temporary)
        catalog = work / "json"
        catalog.mkdir()
        for table, raw in sources.items():
            (catalog / (table + ".json")).write_bytes(raw)
        built = work / "built"
        report = build_master_packs(schema, catalog, built, tables=list(TABLES))
        if report["builder_version"] != 2:
            raise ValueError("Media master key derivation differs from the audited builder")
        generated = read_json(built / "master-tag.json")
        replacements = {row["type"]: row for row in generated["masterTagPacks"]}
        merged = copy.deepcopy(base)
        merged["version"] = version
        proofs = {}
        for index, entry in enumerate(merged["masterTagPacks"]):
            table = entry["type"]
            if table not in TABLES:
                continue
            replacement = copy.deepcopy(replacements[table])
            source = built / "assets/master" / replacement["fileName"]
            name = PACK_NAMES[table]
            destination = source.with_name(name)
            source.rename(destination)
            replacement.update(fileName=name, downloadUrl="http://127.0.0.1:8080/master/" + name)
            if _decode(schema, driver, destination.parent, replacement) != patched[table]:
                raise ValueError("Generated media master protobuf rows differ after SQLCipher roundtrip")
            proofs[name] = {"bytes": destination.stat().st_size, "sha256": _hash(destination.read_bytes())}
            merged["masterTagPacks"][index] = replacement
        verified = validate_media_master_tag(base, merged, schema.fingerprint, rows, proofs)
        ParseDict(merged, schema.response_type("/api.Master/Get")().masterTag)
        (built / "master-tag.json").unlink()
        (built / "build-report.json").unlink()
        (built / TAG_NAME).write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            raise ValueError("Media master output appeared while building")
        built.rename(output)
    return {**verified, "packs": proofs, "schema_sha256": schema.fingerprint,
            "source_tag_sha256": _hash(original_tag.read_bytes()),
            "protobuf_row_roundtrip_verified": True, "device_ingestion_verified": False}
