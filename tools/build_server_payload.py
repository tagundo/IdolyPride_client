#!/usr/bin/env python3
"""Bundle public master files and canonical starter tables for the server apps."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from idoly_local.schema import Schema
from idoly_local.catalog import FixtureStore


TABLES = ("Character", "CharacterActivityLevel", "Costume", "Hair", "Card", "Area", "AreaGroup", "Quest", "Setting", "Tutorial", "CardParameter", "CardRarity", "Accessory", "HierarchyDetailGrade", "HierarchyGrade", "Reward", "Item", "CardLevelRelease", "Skill", "Music", "MusicChartPattern", "Emblem", "SkillEfficacy", "SkillTrigger", "SkillTarget", "Stage", "ManagerLevel", "CardLevel", "Consumption", "Message", "MessageGroup", "EventStory", "ExtraStoryPart", "ExtraStory", "Story", "QuestPressure", "QuestAudienceAdvantage", "ComboAdvantage", "QuestStaminaConsumption", "Mission", "StoryPart", "PhotoActivity", "PhotoQuestMusic", "PhotoQuestStage", "PhotoExpression", "CompanyGrade", "CompanyTrustLevel", "CompanyEnjoyCharacterLevel", "CompanyEnjoyCharacterLevelSetting")
MISSION_MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
MISSION_PACK_SHA256 = "9c9cbec8de1ef1d7c9fb89b6b4319bf75ea5875fc9d7b13de877bcb43eaa1647"
MISSION_ROW_COUNT = 7087
CARD_LEVEL_MISSION_ID = "ms-normal-card_level_achievement"
CARD_LEVEL_THRESHOLDS = (5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160)
EVENT_READ_TABLES = ("Condition", "EventMission", "PhotoAbility", "QuestCharacterAdvantage", "LiveBonusGroup")
EVENT_MASTER_PINS = {
    "Condition": ("d4c6ea5b58c95fe7a4d48576f7c5c6df7980605dd532b31a6d37305058103141", 30786),
    "EventMission": ("49b5b944722f31327ce99c9211316bcf789fe589eef3a932fadaa1b11a8153f5", 412),
    "PhotoAbility": ("8534ed8a88a6fe41b014b54181574394cfc91c74f0608fc8acd7a651639da08d", 375),
    "QuestCharacterAdvantage": ("37ba73b53ea42a2bccf105ecadaf89a33506834e62d3e7de00b637835dcf7f12", 89),
    "LiveBonusGroup": ("78e9b9287bd18cce0163f8fa3efc71e7b41512a40c9b4d09ddf2c779c06bb215", 160),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_mission_master(version, pack_sha256, values):
    """Pin public master data only; this does not enable other mission eligibility."""
    if (version != MISSION_MASTER_VERSION or pack_sha256 != MISSION_PACK_SHA256
            or not isinstance(values, list) or len(values) != MISSION_ROW_COUNT):
        raise ValueError("Mission master version, original pack or row count differs from the audited data")
    identities = [row.get("id") if isinstance(row, dict) else None for row in values]
    if any(not isinstance(identity, str) or not identity for identity in identities) or len(set(identities)) != len(identities):
        raise ValueError("Mission master IDs must be nonempty and unique")
    matches = [row for row in values if row["id"] == CARD_LEVEL_MISSION_ID]
    if len(matches) != 1:
        raise ValueError("The audited card-level mission is missing")
    expected = {"id": CARD_LEVEL_MISSION_ID, "categoryType": 3, "missionType": 13,
        "name": "アイドルLv{threshold}到達", "shortDescription": "アイドルLv{threshold}到達",
        "longDescription": "アイドルLvを{threshold}まであげましょう。", "order": 1, "linkType": 11,
        "targetIds": [], "viewConditionId": "", "linkDetail": "", "eventMissionId": "",
        "companyEnjoyCharacterId": "", "companyEnjoyCharacterMissionCategoryType": 0, "companyTrustMissionCategoryType": 0,
        "progresses": [{"threshold": str(level), "rewardSetId": f"rd_auto;stone;;{50 if level <= 40 else 70 if level <= 90 else 100 if level <= 140 else 200}"}
                       for level in CARD_LEVEL_THRESHOLDS]}
    if matches[0] != expected:
        raise ValueError("The audited card-level mission row or its progress tiers differ")


def payload_tables(event_read_masters=False):
    """Include public event read prerequisites only with explicit export."""
    if type(event_read_masters) is not bool:
        raise TypeError("Event read master export must be an explicit boolean")
    return TABLES + EVENT_READ_TABLES if event_read_masters else TABLES


def validate_event_master(table, version, pack_sha256, values):
    """Pin public read prerequisites; no private catalog or eligibility is created."""
    pin = EVENT_MASTER_PINS.get(table)
    if (pin is None or version != MISSION_MASTER_VERSION or pack_sha256 != pin[0]
            or not isinstance(values, list) or len(values) != pin[1]):
        raise ValueError("Event read master table, version, original pack or row count differs")
    identity = "groupId" if table == "LiveBonusGroup" else "id"
    identities = [row.get(identity) if isinstance(row, dict) else None for row in values]
    if any(not isinstance(value, str) or not value for value in identities):
        raise ValueError("Event read master identity is missing or malformed")
    # These tables are looked up as groups by the captured quest readers. Rows
    # may share a group identity; treating them as _Catalog.ids would lose data.
    if table not in ("QuestCharacterAdvantage", "LiveBonusGroup") and len(set(identities)) != len(identities):
        raise ValueError("Event read master identities are ambiguous")


def decode_master_table(schema, sqlcipher, root, pack, table):
    """Decode one explicit public table without reading neighboring account files."""
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict

    if table not in TABLES + EVENT_READ_TABLES or not re.fullmatch(r"[0-9a-fA-F]{64}", pack.cryptoKey):
        raise ValueError("Unsupported master table or encryption key format")
    root = Path(root).resolve()
    source = (root / pack.fileName).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError("Original master pack is outside its archive")
    connection = sqlcipher.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute(f'PRAGMA key="x\'{pack.cryptoKey}\'"')
        connection.execute("PRAGMA query_only=ON")
        message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
        return [MessageToDict(message.FromString(bytes(raw)), preserving_proto_field_name=True,
                              use_integers_for_enums=True, always_print_fields_with_no_presence=True)
                for (raw,) in connection.execute(f'SELECT data FROM "{table}" ORDER BY rowid')]
    finally:
        connection.close()


def octo_public_files(directory: Path):
    """Validate an explicit public SDK catalog, never an account archive."""
    from Crypto.Cipher import AES
    from idoly_local.octo_manifest import OctoManifest
    from idoly_local.octo_runtime import load_octo_archive

    directory = Path(directory).resolve()
    loaded = load_octo_archive(directory)
    if loaded is None:
        raise ValueError("An explicit Octo catalog directory must contain both public files")
    settings, raw = loaded

    def aes_cbc(encrypt, key, iv, data):
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(data) if encrypt else cipher.decrypt(data)

    manifest = OctoManifest(raw, aes_key=bytes.fromhex(settings["aes_key_hex"]),
                            client_key=settings["client_key"], base_url="http://127.0.0.1:8080",
                            aes_cbc=aes_cbc)
    if manifest.revision != settings["revision"]:
        raise ValueError("Public Octo catalog revision differs from its settings")
    files = [(directory / name, "data/public-octo/" + name)
             for name in ("settings.json", "manifest.pb")]
    summary = {"application_id": settings["application_id"],
               "application_version": settings["application_version"],
               "revision": manifest.revision, "objects": len(manifest.objects),
               "manifest_sha256": settings["manifest_sha256"]}
    return files, summary


def build_payload(data_dir: Path, output: Path, *, octo_data: Path | None = None,
                  event_read_masters: bool = False) -> dict:
    from google.protobuf.json_format import ParseDict
    from sqlcipher3 import dbapi2 as sqlcipher

    data_dir, output = Path(data_dir).resolve(), Path(output).resolve()
    selected_tables = payload_tables(event_read_masters)
    if output.exists():
        raise ValueError("Payload output already exists")
    descriptor = data_dir / "protocol/idolypride-6.1.1.pb"
    schema = Schema.from_descriptor_set(descriptor)
    archive = data_dir / "original-master"
    report = json.loads((archive / "archive-report.json").read_text())
    if report.get("complete") is not True:
        raise ValueError("An intact completed original master archive is required")
    response = schema.response_type("/api.Master/Get")()
    ParseDict(json.loads((archive / "master-tag.json").read_text()), response.masterTag)
    packs = {pack.type: pack for pack in response.masterTag.masterTagPacks}
    if not set(selected_tables).issubset(packs):
        raise ValueError("Required starter master tables are missing")
    files = [(descriptor, "data/protocol/idolypride-6.1.1.pb")]
    octo_summary = None
    if octo_data is not None:
        octo_files, octo_summary = octo_public_files(octo_data)
        files.extend(octo_files)
    public = data_dir / "public-fixtures"
    if (public / "manifest.json").is_file():
        store = FixtureStore(public, schema)
        files.append((public / "manifest.json", "data/public-fixtures/manifest.json"))
        for entry in store.manifest["responses"]:
            if entry["method"] not in ("/api.Master/Rule", "/api.Master/GetHelpCategory"):
                raise ValueError("Only public rule/help responses may be bundled in server apps")
            source = (public / entry["file"]).resolve()
            if not source.is_relative_to(public.resolve()):
                raise ValueError("Public response path is outside its fixture directory")
            if not any(name == "data/public-fixtures/" + entry["file"] for _, name in files):
                files.append((source, "data/public-fixtures/" + entry["file"]))
    for name in ("master-tag.json", "response.pb", "archive-report.json"):
        files.append((archive / name, "data/original-master/" + name))
    root = (archive / "assets/master").resolve()
    for pack in packs.values():
        source = (root / pack.fileName).resolve()
        record = report.get("packs", {}).get(pack.type, {})
        if (not source.is_relative_to(root) or not source.is_file() or source.stat().st_size != pack.fileSize
                or record.get("sha256") != digest(source)):
            raise ValueError("An original master pack failed its archive check")
        files.append((source, "data/original-master/assets/master/" + pack.fileName))
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with tempfile.TemporaryDirectory(prefix=".server-payload-", dir=output.parent) as temporary:
        stage = Path(temporary)
        catalog = stage / "master-json"
        catalog.mkdir()
        for table in selected_tables:
            pack = packs[table]
            values = decode_master_table(schema, sqlcipher, root, pack, table)
            if table == "Mission":
                validate_mission_master(response.masterTag.version, digest(root / pack.fileName), values)
            if table in EVENT_READ_TABLES:
                validate_event_master(table, response.masterTag.version, digest(root / pack.fileName), values)
            path = catalog / (table + ".json")
            path.write_text(json.dumps(values, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            files.append((path, "data/master-json/" + path.name))
            counts[table] = len(values)
        version = catalog / "!version.txt"
        version.write_text(response.masterTag.version, encoding="ascii")
        files.append((version, "data/master-json/!version.txt"))
        from idoly_local.tutorial_replay import validate_replays
        replay_root = data_dir / "public-tutorial"
        replay_report = validate_replays(schema, catalog, replay_root)
        for name in ("manifest.json", "tutorial-short.pb", "tutorial-full.pb"):
            source = (replay_root / name).resolve()
            if not source.is_relative_to(replay_root.resolve()) or not source.is_file():
                raise ValueError("Required public tutorial replay is missing or outside its directory")
            files.append((source, "data/public-tutorial/" + name))
        from idoly_local.story_catalog import validate_story_catalog
        story_root = data_dir / "public-story"
        story_report = validate_story_catalog(schema, catalog, story_root)
        for name in ("manifest.json", "story-list-event.pb", "story-list-extra.pb"):
            source = (story_root / name).resolve()
            if not source.is_relative_to(story_root.resolve()) or not source.is_file():
                raise ValueError("Required public story catalog is missing or outside its directory")
            files.append((source, "data/public-story/" + name))
        summary = {"schema": 1, "master_version": response.masterTag.version,
                   "schema_sha256": schema.fingerprint, "tables": counts, "tutorial_replays": replay_report,
                   "story_catalog": story_report,
                   "files": [{"path": name, "bytes": path.stat().st_size, "sha256": digest(path)} for path, name in files]}
        if octo_summary is not None:
            summary["octo_resources"] = octo_summary
        if event_read_masters:
            summary["event_read_master_tables"] = list(EVENT_READ_TABLES)
        payload = stage / "ServerData.zip"
        with ZipFile(payload, "x", compression=ZIP_DEFLATED, compresslevel=6) as zipped:
            for path, name in files:
                zipped.write(path, name)
            zipped.writestr("data/payload-manifest.json", json.dumps(summary, ensure_ascii=False, indent=2))
        with ZipFile(payload) as zipped:
            if zipped.testzip() is not None:
                raise ValueError("Server payload CRC validation failed")
        payload.rename(output)
    return {"file": str(output), "bytes": output.stat().st_size, "sha256": digest(output), "tables": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--octo-data", type=Path,
                        help="Explicit public settings.json and manifest.pb directory; no account files")
    parser.add_argument("--event-read-masters", action="store_true",
                        help="Export five pinned public Dream/VENUS read prerequisite tables; no private catalogs or unlocks")
    args = parser.parse_args()
    print(json.dumps(build_payload(args.data_dir, args.output, octo_data=args.octo_data,
                                   event_read_masters=args.event_read_masters),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
