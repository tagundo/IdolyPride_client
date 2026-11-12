"""Narrow original-row deltas and offline SQLCipher/protobuf roundtrips."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local import media_master_build as overlay


def original_rows():
    costumes = []
    for identity in sorted(overlay.COSTUME_IDS):
        body = identity[4:]
        costumes.append({"id": identity, "characterId": "char-" + body.split("-", 1)[0],
            "costumeTypeId": "mizg", "bodyAssetId": body, "defaultHairId": "hair-" + body,
            "isDisableAdmin": False, "isUserUnavailable": True, "name": "original bath"})
    for identity in sorted(overlay.ADMIN_COSTUME_IDS):
        body = identity[4:]
        costumes.append({"id": identity, "characterId": "char-" + body.split("-", 1)[0],
            "costumeTypeId": "idol", "bodyAssetId": body, "defaultHairId": "hair-" + body,
            "isDisableAdmin": True, "isUserUnavailable": False, "name": "original rabbit"})
    hairs = []
    for identity in sorted(overlay.ADMIN_HAIR_IDS):
        asset = identity[5:]
        owner = asset.split("-", 1)[0]
        hairs.append({"id": identity, "characterId": "char-" + owner, "hairAssetId": asset,
            "faceAssetId": owner + "-base-00", "fittingCostumeId": "cos-kor-casl-00"
            if identity == "hair-kor-hair-00" else "cos-" + asset,
            "isDisableAdmin": True, "canUseCostumeIds": ["preserve-compatibility"]})
    hairs.append({"id": "hidden-other-hair", "characterId": "char-other", "hairAssetId": "other",
        "faceAssetId": "other-base", "fittingCostumeId": "other", "isDisableAdmin": True,
        "canUseCostumeIds": []})
    costumes.append({"id": "ordinary", "characterId": "char-ai", "costumeTypeId": "casl",
        "bodyAssetId": "ordinary", "defaultHairId": "hair-ordinary", "isDisableAdmin": False,
        "isUserUnavailable": False, "name": "ordinary"})
    costumes.append({"id": "hidden-SD", "characterId": "char-ai", "costumeTypeId": "sd-police",
        "bodyAssetId": "sd", "defaultHairId": "hair-sd", "isDisableAdmin": True,
        "isUserUnavailable": True, "name": "remain hidden"})
    return {"PhotoActivity": [{"id": "activity", "costumeTypeIds": ["mizg"],
                "forceCostumeTypeId": "mizg", "deniedCharacterIds": ["npc"], "poseAssetId": "pose-work",
                "viewConditionId": "original-view", "unlockConditionId": "original-unlock"}],
            "PhotoExpression": [{"id": "expression", "costumeTypeIds": ["idol"],
                "forceCostumeTypeId": "idol", "deniedCharacterIds": ["other"], "poseAssetId": "pose-stage",
                "viewConditionId": "original-view", "unlockConditionId": "original-unlock"}],
            "Costume": costumes, "Hair": hairs,
            "PhotoQuestMusic": [{"id": identity, "assetId": "asset-" + identity, "name": "shared original name",
                "description": "  original cover " + identity + " \t", "singer": "original three singers", "order": index,
                "viewConditionId": "original-possession", "unlockConditionId": "original-possession"}
                for index, identity in enumerate([*sorted(overlay.COVER_LABEL_IDS), "non-cover-original"])]}


def original_tag():
    names = [*overlay.TABLES, "CostumeType", *["Other%03d" % n for n in range(196)]]
    return {"version": "synthetic-original", "masterTagPacks": [
        {"type": name, "fileName": "original-" + name + ".db", "fileSize": 4096,
         "cryptoKey": "a" * 64, "downloadUrl": "https://public.invalid/" + name} for name in names]}


def media_tag(base, rows, proofs, fingerprint="a" * 64):
    version, keys, _sources, _patched = overlay._identities(fingerprint, base, rows)
    result = copy.deepcopy(base)
    result["version"] = version
    for index, row in enumerate(result["masterTagPacks"]):
        table = row["type"]
        if table in overlay.TABLES:
            name = overlay.PACK_NAMES[table]
            result["masterTagPacks"][index] = {"type": table, "fileName": name,
                "fileSize": proofs[name]["bytes"], "cryptoKey": keys[table],
                "downloadUrl": "http://127.0.0.1:8080/master/" + name}
    return result


def test_only_approved_photo_conditions_types_and_appearance_flags_change_without_mutating_sources():
    rows = original_rows()
    snapshot = copy.deepcopy(rows)
    for table in overlay.TABLES:
        changed = overlay.expanded_rows(table, rows[table])
        for before, after in zip(rows[table], changed, strict=True):
            expected = copy.deepcopy(before)
            if table == "Costume":
                if before["id"] in overlay.COSTUME_IDS:
                    expected["isUserUnavailable"] = False
                if before["id"] in overlay.ADMIN_COSTUME_IDS:
                    expected["isDisableAdmin"] = False
            elif table == "Hair":
                if before["id"] in overlay.ADMIN_HAIR_IDS:
                    expected["isDisableAdmin"] = False
            else:
                expected.update(viewConditionId="", unlockConditionId="")
                if table != "PhotoQuestMusic":
                    expected["costumeTypeIds"] = list(overlay.TYPE_IDS)
                elif before["id"] in overlay.COVER_LABEL_IDS:
                    expected["name"] = before["description"].rstrip()
            assert after == expected
    assert rows == snapshot
    assert len(overlay.TYPE_IDS) == 19 and "mizg-all-ng" in overlay.TYPE_IDS


@pytest.mark.parametrize("change", ["missing", "available", "body", "admin", "duplicate"])
def test_bath_costume_exception_cannot_expand_to_wrong_or_missing_original_rows(change):
    rows = original_rows()["Costume"]
    if change == "missing": rows.pop(0)
    elif change == "available": rows[0]["isUserUnavailable"] = False
    elif change == "body": rows[0]["bodyAssetId"] = "invented"
    elif change == "admin": rows[0]["isDisableAdmin"] = True
    else: rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(ValueError): overlay.expanded_rows("Costume", rows)


def test_type_inventory_rejects_unknown_costumes_and_never_invents_a_type():
    rows = original_rows()["Costume"]
    types = [{"id": value} for value in overlay.TYPE_IDS]
    assert overlay.costume_type_ids(rows, types) == overlay.TYPE_IDS
    for malformed in (types[:-1], types + [{"id": "new"}], [{"id": []}]):
        with pytest.raises(ValueError): overlay.costume_type_ids(rows, malformed)
    rows[0]["costumeTypeId"] = "unknown"
    with pytest.raises(ValueError): overlay.costume_type_ids(rows, types)


def test_reordered_source_keys_keep_version_source_bytes_and_local_keys_identical():
    rows, tag = original_rows(), original_tag()
    reordered = {table: [{key: row[key] for key in reversed(row)} for row in values]
                 for table, values in rows.items()}
    assert overlay._identities("a" * 64, tag, rows) == overlay._identities("a" * 64, tag, reordered)


@pytest.mark.parametrize("table", ["PhotoActivity", "PhotoExpression", "PhotoQuestMusic"])
def test_visibility_conditions_must_be_real_strings_before_clearing_them(table):
    rows = original_rows()[table]
    rows[0]["viewConditionId"] = True
    with pytest.raises(ValueError, match="conditions"):
        overlay.expanded_rows(table, rows)


def test_only_four_explicit_cover_labels_use_descriptions_with_trailing_whitespace_removed():
    rows = original_rows()["PhotoQuestMusic"]
    before = copy.deepcopy(rows)
    changed = overlay.expanded_rows("PhotoQuestMusic", rows)
    for original, current in zip(rows, changed, strict=True):
        assert current["description"] == original["description"]
        assert current["name"] == (original["description"].rstrip()
            if original["id"] in overlay.COVER_LABEL_IDS else original["name"])
        assert {k: v for k, v in current.items() if k not in ("name", "viewConditionId", "unlockConditionId")} == {
            k: v for k, v in original.items() if k not in ("name", "viewConditionId", "unlockConditionId")}
    assert rows == before and changed[0]["name"].startswith("  ")


@pytest.mark.parametrize("change", ["missing-row", "empty-description"])
def test_cover_label_exceptions_reject_incomplete_or_missing_original_data(change):
    rows = original_rows()["PhotoQuestMusic"]
    if change == "missing-row": rows.pop(0)
    else: rows[0]["description"] = " \t"
    with pytest.raises(ValueError): overlay.expanded_rows("PhotoQuestMusic", rows)


@pytest.mark.parametrize("change", ["unrelated", "order", "version", "key", "filename", "size", "extra", "missing"])
def test_merged_master_tag_rejects_unrelated_changes_and_bad_replacement_provenance(change):
    rows, base = original_rows(), original_tag()
    proofs = {name: {"bytes": 4096, "sha256": "b" * 64} for name in overlay.PACK_NAMES.values()}
    tag = media_tag(base, rows, proofs)
    if change == "unrelated": tag["masterTagPacks"][-1]["downloadUrl"] += "changed"
    elif change == "order": tag["masterTagPacks"].reverse()
    elif change == "version": tag["version"] += "changed"
    elif change == "key": tag["masterTagPacks"][0]["cryptoKey"] = "0" * 64
    elif change == "filename": tag["masterTagPacks"][0]["fileName"] = "../escape"
    elif change == "size": tag["masterTagPacks"][0]["fileSize"] += 4096
    elif change == "extra": tag["provenance"] = {}
    else: tag["masterTagPacks"].pop()
    with pytest.raises(ValueError): overlay.validate_media_master_tag(base, tag, "a" * 64, rows, proofs)


def test_public_pack_path_is_checked_before_a_symlink_or_oversized_input_can_be_read(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"public but outside archive")
    (root / "link").symlink_to(outside)
    for name, size in (("link", outside.stat().st_size), ("missing", 2 * 1024 * 1024)):
        with pytest.raises((ValueError, FileNotFoundError)):
            overlay._pack_path(root, {"type": "CostumeType", "fileName": name, "fileSize": size})


def _schema():
    from google.protobuf import descriptor_pb2, message_factory
    from test_master_packs import _synthetic_schema
    original = _synthetic_schema()
    pool = original.pool
    options = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.protobuf.MessageOptions"))
    field_options = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.protobuf.FieldOptions"))
    tables = descriptor_pb2.FileDescriptorProto(name="media_master.proto", package="master", syntax="proto3")
    tables.dependency.append("test_master_options.proto")
    definitions = {"CostumeType": [("id", 9, False), ("name", 9, False)],
        "PhotoActivity": [("id", 9, False), ("costumeTypeIds", 9, True), ("forceCostumeTypeId", 9, False),
                          ("deniedCharacterIds", 9, True), ("poseAssetId", 9, False),
                          ("viewConditionId", 9, False), ("unlockConditionId", 9, False)],
        "PhotoExpression": [("id", 9, False), ("costumeTypeIds", 9, True), ("forceCostumeTypeId", 9, False),
                            ("deniedCharacterIds", 9, True), ("poseAssetId", 9, False),
                            ("viewConditionId", 9, False), ("unlockConditionId", 9, False)],
        "Costume": [("id", 9, False), ("characterId", 9, False), ("costumeTypeId", 9, False),
                    ("bodyAssetId", 9, False), ("defaultHairId", 9, False), ("isDisableAdmin", 8, False),
                    ("isUserUnavailable", 8, False), ("name", 9, False)],
        "Hair": [("id", 9, False), ("characterId", 9, False), ("hairAssetId", 9, False),
                 ("faceAssetId", 9, False), ("fittingCostumeId", 9, False), ("isDisableAdmin", 8, False),
                 ("canUseCostumeIds", 9, True)],
        "PhotoQuestMusic": [("id", 9, False), ("assetId", 9, False), ("name", 9, False),
                            ("description", 9, False), ("singer", 9, False), ("order", 5, False),
                            ("viewConditionId", 9, False), ("unlockConditionId", 9, False)]}
    for name, fields in definitions.items():
        message = tables.message_type.add(name=name)
        annotation = options(); annotation.Extensions[pool.FindExtensionByName("master.table")] = True
        message.options.ParseFromString(annotation.SerializeToString())
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = message.field.add(name=name, number=number, type=kind, label=3 if repeated else 1)
            if name == "id":
                annotation = field_options(); annotation.Extensions[pool.FindExtensionByName("master.pk")] = True
                field.options.ParseFromString(annotation.SerializeToString())
    table_file = pool.AddSerializedFile(tables.SerializeToString())
    api = descriptor_pb2.FileDescriptorProto(name="media_api.proto", package="api", syntax="proto3")
    pack = api.message_type.add(name="MasterTagPack")
    for number, name in enumerate(("type", "fileName", "fileSize", "cryptoKey", "downloadUrl"), 1):
        pack.field.add(name=name, number=number, type=5 if name == "fileSize" else 9, label=1)
    tag = api.message_type.add(name="MasterTag")
    tag.field.add(name="version", number=1, type=9, label=1)
    tag.field.add(name="masterTagPacks", number=2, type=11, type_name=".api.MasterTagPack", label=3)
    response = api.message_type.add(name="MasterGetResponse")
    response.field.add(name="masterTag", number=1, type=11, type_name=".api.MasterTag", label=1)
    api_file = pool.AddSerializedFile(api.SerializeToString())
    return SimpleNamespace(pool=pool, files=[*original.files, table_file, api_file],
        fingerprint=hashlib.sha256(tables.SerializeToString()).hexdigest(),
        response_type=lambda _: message_factory.GetMessageClass(pool.FindMessageTypeByName("api.MasterGetResponse")))


@pytest.fixture
def built_original(tmp_path, monkeypatch):
    from idoly_local.master_build import build_master_packs
    pytest.importorskip("sqlcipher3")
    schema = _schema()
    catalog = tmp_path / "json"
    catalog.mkdir()
    rows = original_rows()
    for table, values in rows.items(): (catalog / (table + ".json")).write_text(json.dumps(values))
    (catalog / "CostumeType.json").write_text(json.dumps([{"id": value, "name": value} for value in overlay.TYPE_IDS]))
    original = tmp_path / "original"
    build_master_packs(schema, catalog, original, tables=[*overlay.TABLES, "CostumeType"])
    tag = overlay.read_json(original / "master-tag.json")
    fillers = original_tag()["masterTagPacks"][len(overlay.TABLES) + 1:]
    tag["masterTagPacks"].extend(fillers)
    assert len(tag["masterTagPacks"]) == 202
    (original / "master-tag.json").write_text(json.dumps(tag))
    pack = next(row for row in tag["masterTagPacks"] if row["type"] == "CostumeType")
    path = original / "assets/master" / pack["fileName"]
    monkeypatch.setattr(overlay, "COSTUME_TYPE_PACK_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(overlay, "COSTUME_TYPE_PACK_BYTES", path.stat().st_size)
    return schema, catalog, original, tag


def test_five_encrypted_packs_roundtrip_and_leave_original_files_and_197_entries_unchanged(built_original, tmp_path):
    schema, catalog, original, tag = built_original
    source_hashes = {str(path.relative_to(original)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in original.rglob("*") if path.is_file()}
    destination = tmp_path / "media"
    report = overlay.build_media_master_overlay(schema, original / "master-tag.json",
        original / "assets/master", catalog, destination)
    media = overlay.read_json(destination / overlay.TAG_NAME)
    assert report["protobuf_row_roundtrip_verified"] is True and report["device_ingestion_verified"] is False
    assert len(report["packs"]) == 5 and report["replaced_pack_count"] == 5
    assert {path.name for path in (destination / "assets/master").iterdir()} == set(overlay.PACK_NAMES.values())
    for before, after in zip(tag["masterTagPacks"], media["masterTagPacks"], strict=True):
        if before["type"] not in overlay.TABLES: assert before == after
    assert source_hashes == {str(path.relative_to(original)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in original.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="already exists"):
        overlay.build_media_master_overlay(schema, original / "master-tag.json", original / "assets/master",
                                          catalog, destination)


def test_unknown_original_protobuf_fields_fail_before_media_output_is_published(built_original, tmp_path):
    from sqlcipher3 import dbapi2
    schema, catalog, original, tag = built_original
    pack = next(row for row in tag["masterTagPacks"] if row["type"] == "PhotoExpression")
    connection = dbapi2.connect(str(original / "assets/master" / pack["fileName"]))
    try:
        connection.execute(f'PRAGMA key="x\'{pack["cryptoKey"]}\'"')
        blob = bytes(connection.execute('SELECT data FROM "PhotoExpression"').fetchone()[0])
        connection.execute('UPDATE "PhotoExpression" SET data=?', (blob + b"\xf8\x07\x01",))
        connection.commit()
    finally: connection.close()
    destination = tmp_path / "media"
    with pytest.raises(ValueError, match="unknown or non-roundtrippable"):
        overlay.build_media_master_overlay(schema, original / "master-tag.json", original / "assets/master",
                                          catalog, destination)
    assert not destination.exists()
