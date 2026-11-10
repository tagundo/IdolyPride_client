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


TABLES = ("Character", "CharacterActivityLevel", "Costume", "Hair", "Card", "Area", "AreaGroup", "Quest", "Setting", "Tutorial", "CardParameter", "CardRarity", "Accessory", "HierarchyDetailGrade", "HierarchyGrade", "Reward", "Item", "CardLevelRelease", "Skill", "Music", "MusicChartPattern", "Emblem", "SkillEfficacy", "SkillTrigger", "SkillTarget", "Stage", "ManagerLevel", "CardLevel", "Consumption", "Message", "MessageGroup", "EventStory", "ExtraStoryPart", "ExtraStory", "Story")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_payload(data_dir: Path, output: Path) -> dict:
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict, ParseDict
    from sqlcipher3 import dbapi2 as sqlcipher

    data_dir, output = Path(data_dir).resolve(), Path(output).resolve()
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
    if not set(TABLES).issubset(packs):
        raise ValueError("Required starter master tables are missing")
    files = [(descriptor, "data/protocol/idolypride-6.1.1.pb")]
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
        for table in TABLES:
            pack = packs[table]
            if not re.fullmatch(r"[0-9a-fA-F]{64}", pack.cryptoKey):
                raise ValueError("Unsupported master encryption key format")
            connection = sqlcipher.connect((root / pack.fileName).as_uri() + "?mode=ro", uri=True)
            try:
                connection.execute(f'PRAGMA key="x\'{pack.cryptoKey}\'"')
                rows = connection.execute(f'SELECT data FROM "{table}" ORDER BY rowid').fetchall()
                message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
                values = [MessageToDict(message.FromString(bytes(row[0])), preserving_proto_field_name=True,
                                       use_integers_for_enums=True, always_print_fields_with_no_presence=True)
                          for row in rows]
            finally:
                connection.close()
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
    args = parser.parse_args()
    print(json.dumps(build_payload(args.data_dir, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
