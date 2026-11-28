"""Pinned original Love masters plus explicitly inferred compatibility routes.

Only build_love_catalog prepares data; runtime loading reads a bounded JSON and
hashes its original master inputs once per changed file identity. No online call,
account mutation, schedule change, reward grant or original ADV text is here.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import threading

MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
RAW_DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
REFERENCE_SHA256 = "3f1f8e30a499c630a23dfca8e9216e165a2086d3c031b52aba39dc76d05438ec"
ADV_PROOF_SHA256 = "1000ef777c5a95212a48be4d7294f741c1d41bb24ac132589b1711a07bcfded6"
REFERENCE_COMMIT = "9b67c06939403d7035e1795745f791340a775868"
LOVE_MASTER_PINS = {
    "LoveHomeAction": ("cb612a848f5a4c9b43b0060e7322231cf98ad3f2a2fa100960260ce387761cbf", 243),
    "LoveLevel": ("309f5f809020a191fca77975f5643f196b0671e8abfc6f70e80db100e28fcbec", 57),
    "LoveStoryEpisode": ("bb314a8f62fbf65b516b536de6bcf0a14d4962a42c19405faab517cad1d55834", 72),
    "LoveColor": ("56c8eec7a3a6db9a9d46e6a30b4fd79f573984fb82e82b793e0f9d21a2a34125", 1),
}
LOVE_TABLES = tuple(LOVE_MASTER_PINS)
SOURCE_TABLES = LOVE_TABLES + ("Story", "Setting", "Item", "Character", "Costume", "Area", "Condition", "EventMission")
EVENT_IDS = ("love-23-0514", "love-23-1114", "love-24-0517", "love-24-1114", "love-26-0313", "love-extra-25-0426")
SOURCE_GRADE = "original_master_and_reference_capture_claim"
INFERENCE_STATUS = "reference_routes_inferred"
MAX_CATALOG = 512 * 1024
_CACHE, _LOCK = {}, threading.RLock()


class LoveCatalogError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _need(value, code="love_catalog_invalid"):
    if not value:
        raise LoveCatalogError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result)
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except LoveCatalogError:
        raise
    except Exception:
        raise LoveCatalogError("love_catalog_invalid") from None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _read(path, maximum):
    try:
        info = path.lstat()
        _need(path.is_file() and not path.is_symlink() and 0 < info.st_size <= maximum,
              "love_catalog_unavailable")
        raw = path.read_bytes()
        _need(len(raw) == info.st_size)
        return raw
    except LoveCatalogError:
        raise
    except Exception:
        raise LoveCatalogError("love_catalog_unavailable") from None


def _hash(path):
    try:
        _need(path.is_file() and not path.is_symlink(), "love_catalog_unavailable")
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except LoveCatalogError:
        raise
    except Exception:
        raise LoveCatalogError("love_catalog_unavailable") from None


def _integer(value, maximum=2**53-1):
    if type(value) is str:
        _need(re.fullmatch(r"0|[1-9][0-9]{0,15}", value) is not None)
        value = int(value)
    _need(type(value) is int and 0 <= value <= maximum)
    return value


def _load_source(path, expected, maximum):
    raw = _read(Path(path), maximum)
    _need(hashlib.sha256(raw).hexdigest() == expected, "love_catalog_source_changed")
    value = _json(raw)
    _need(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1)
    return value


def validate_love_master(table, version, pack_sha256, rows):
    pin = LOVE_MASTER_PINS.get(table)
    _need(pin is not None and version == MASTER_VERSION and pack_sha256 == pin[0]
          and type(rows) is list and len(rows) == pin[1], "love_catalog_master_changed")
    _need(all(type(row) is dict and row.get("loveId") in EVENT_IDS for row in rows))
    identities = [(row.get("loveId"), row.get("level")) if table == "LoveLevel" else
                  row.get("loveId") if table == "LoveColor" else row.get("id") for row in rows]
    _need(all(value is not None for value in identities) and len(set(identities)) == len(identities))


def _reference(reference_path, proof_path):
    reference = _load_source(reference_path, REFERENCE_SHA256, 128 * 1024)
    proof = _load_source(proof_path, ADV_PROOF_SHA256, 12 * 1024)
    _need(reference["reference"]["commit"] == REFERENCE_COMMIT
          and set(reference["events"]) == set(EVENT_IDS)
          and reference["policy"]["routes"] == "inferred_reference_not_official_capture"
          and reference["policy"]["score_bonus_grants"] is False)
    _need(proof["master_version"] == MASTER_VERSION and proof["story_count"] == 72
          and proof["unique_asset_count"] == 69 and proof["available_asset_count"] == 68
          and len(proof["assets"]) == 68 and proof["missing_asset_ids"] == ["love_2411_04_02"])
    return reference, proof


def build_love_catalog(schema, master_dir, *, pack_proofs, reference_path=None, proof_path=None):
    """Build only from verified public original packs, in the CI payload stage."""
    master_dir = Path(master_dir)
    _need(schema.fingerprint == SCHEMA_SHA256, "love_catalog_schema_changed")
    version = _read(master_dir / "!version.txt", 4096).decode("ascii").strip()
    _need(version == MASTER_VERSION, "love_catalog_master_changed")
    repository = Path(__file__).resolve().parents[2]
    reference, proof = _reference(reference_path or repository / "data/love-reference.json",
                                  proof_path or repository / "data/love-adv-proof.json")
    tables = {}
    for table in SOURCE_TABLES:
        rows = _json(_read(master_dir / (table + ".json"), 64 * 1024 * 1024))
        _need(type(rows) is list and len(rows) <= 100000 and all(type(row) is dict for row in rows))
        tables[table] = rows
        if table in LOVE_TABLES:
            validate_love_master(table, version, pack_proofs.get(table), rows)
    setting = tables["Setting"]
    _need(len(setting) == 1 and _integer(setting[0]["loveSaveSlotNum"]) == 5
          and _integer(setting[0]["secondsPerLoveLessonStep"]) == 10)
    ids = {}
    for table in ("Story", "Item", "Character", "Costume", "Area", "Condition", "EventMission"):
        ids[table] = {row.get("id"): row for row in tables[table]}
        _need(None not in ids[table] and len(ids[table]) == len(tables[table]))
    story_mapping, events = {}, {}
    for event_id in EVENT_IDS:
        source = reference["events"][event_id]
        catalog, route = source["catalog"], source["route"]
        event = dict(catalog)
        _need(event["loveId"] == event_id and event["unlockConditionId"] in ids["Condition"])
        for key in ("storyReadItemId", "promoteItemId", "presentItemId"):
            if event.get(key):
                _need(event[key] in ids["Item"])
        for key in ("eventMissionIds", "limitedEventMissionIds"):
            _need(all(value in ids["EventMission"] for value in event.get(key, [])))
        mains = event.get("mainCharacters") or [{"characterId": event["characterId"],
            "costumeId": event["costumeId"], "assetId": event["characterAssetId"], "color": event["color"]}]
        _need(type(mains) is list and 1 <= len(mains) <= 16)
        _need(all(row.get("characterId") in ids["Character"] and row.get("costumeId") in ids["Costume"] for row in mains))
        event["mainCharacters"] = mains
        event["saveSlotCount"], event["lessonStepSeconds"] = 5, 10
        event.setdefault("titleAssetId", setting[0]["loveTitleAssetId"])
        event["levels"] = [row for row in tables["LoveLevel"] if row["loveId"] == event_id]
        event["homeActions"] = [row for row in tables["LoveHomeAction"] if row["loveId"] == event_id]
        colors = [row for row in tables["LoveColor"] if row["loveId"] == event_id]
        event["colorDefinition"] = colors[0] if colors else None
        event["routes"], event["endings"], event["endingConditions"] = route["episodes"], route["endings"], route["endingConditions"]
        event["episodes"] = {}
        for row in tables["LoveStoryEpisode"]:
            if row["loveId"] != event_id:
                continue
            episode = dict(row)
            story = ids["Story"].get(row["storyId"])
            _need(story is not None and story.get("rewardId") == "" and len(story.get("advAssetIds", [])) == 1)
            asset = story["advAssetIds"][0]
            story_mapping[story["id"]] = asset
            episode["storyAssetId"], episode["story"] = asset, story
            observed, routed = proof["assets"].get(asset), route["episodes"].get(row["id"])
            available = observed is not None and routed is not None
            if available:
                _need([group["count"] for group in routed.get("groups", [])] == observed["choices"],
                      "love_catalog_adv_changed")
            else:
                _need(asset in proof["missing_asset_ids"] and row["id"] == "love-event-story-love-24-1114-004-bad")
            episode["advEvidence"] = {"available": available, "assetId": asset,
                "source_sha256": observed["sha256"] if observed else None,
                "choiceCounts": observed["choices"] if observed else None,
                "conditionCounts": observed["conditions"] if observed else None,
                "reason_code": None if available else "adv_evidence_unavailable"}
            event["episodes"][row["id"]] = episode
        _need(event["levels"] and event["episodes"])
        event["source_grade"], event["inference_status"] = SOURCE_GRADE, INFERENCE_STATUS
        events[event_id] = event
    _need(len(story_mapping) == 72 and hashlib.sha256(_canonical(story_mapping)).hexdigest() == proof["story_mapping_sha256"],
          "love_catalog_adv_changed")
    record = {"schema": 1, "schema_sha256": schema.fingerprint, "master_version": version,
        "reference_sha256": REFERENCE_SHA256, "adv_proof_sha256": ADV_PROOF_SHA256,
        "primary_packs": {name: {"sha256": pin[0], "rows": pin[1]} for name, pin in LOVE_MASTER_PINS.items()},
        "source_files": {table + ".json": _hash(master_dir / (table + ".json")) for table in SOURCE_TABLES},
        "policy": {"inference_status": INFERENCE_STATUS, "official_weights_verified": False, "score_bonus_grants": False,
            "finish_stone_grant": False, "original_end_times_known": False,
            "missing_adv_asset_ids": proof["missing_asset_ids"], "user_schedules_are_local_overrides": True},
        "events": events}
    record["ruleset_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
    _need(len(_canonical(record)) <= MAX_CATALOG)
    return record


def _identity(path):
    try:
        info = path.lstat()
        _need(path.is_file() and not path.is_symlink(), "love_catalog_unavailable")
        return (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    except LoveCatalogError:
        raise
    except Exception:
        raise LoveCatalogError("love_catalog_unavailable") from None


def _load_record(master_dir, catalog_path=None):
    directory = Path(master_dir).resolve()
    path = Path(catalog_path) if catalog_path is not None else directory / "LoveCatalog.json"
    paths = [path, directory / "!version.txt", *(directory / (name + ".json") for name in SOURCE_TABLES)]
    key = tuple(_identity(value) for value in paths)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    record = _json(_read(path, MAX_CATALOG))
    _need(type(record) is dict and type(record.get("schema")) is int and record["schema"] == 1)
    _need(record.get("schema_sha256") == SCHEMA_SHA256 and record.get("master_version") == MASTER_VERSION
          and record.get("reference_sha256") == REFERENCE_SHA256 and record.get("adv_proof_sha256") == ADV_PROOF_SHA256)
    _need(_read(directory / "!version.txt", 4096).decode("ascii").strip() == MASTER_VERSION)
    value = dict(record)
    claimed = value.pop("ruleset_sha256", None)
    _need(type(claimed) is str and hashlib.sha256(_canonical(value)).hexdigest() == claimed,
          "love_catalog_ruleset_changed")
    expected_packs = {name: {"sha256": pin[0], "rows": pin[1]} for name, pin in LOVE_MASTER_PINS.items()}
    _need(record.get("primary_packs") == expected_packs and set(record.get("source_files", {})) ==
          {table + ".json" for table in SOURCE_TABLES})
    for name, expected in record["source_files"].items():
        _need(_hash(directory / name) == expected, "love_catalog_master_changed")
    events = record.get("events")
    _need(type(events) is dict and set(events) == set(EVENT_IDS))
    _need(sum(len(event.get("episodes", {})) for event in events.values()) == 72
          and sum(len(event.get("levels", [])) for event in events.values()) == 57)
    for event_id, event in events.items():
        _need(type(event) is dict and event.get("loveId") == event_id
              and event.get("source_grade") == SOURCE_GRADE and event.get("inference_status") == INFERENCE_STATUS)
    _need(key == tuple(_identity(value) for value in paths), "love_catalog_source_changed")
    with _LOCK:
        _CACHE.clear()
        _CACHE[key] = record
    return record


def load_love_catalog(schema, master_dir, catalog_path=None):
    try:
        _need(schema.fingerprint == SCHEMA_SHA256, "love_catalog_schema_changed")
        return _json(_canonical(_load_record(master_dir, catalog_path)))
    except LoveCatalogError:
        raise
    except Exception:
        raise LoveCatalogError("love_catalog_invalid") from None


def event_catalog(data_dir):
    """Small safe settings projection. An absent catalog never breaks polling."""
    unavailable = {"schema": 1, "available": False, "events": [], "ruleset_sha256": None,
                   "reason_code": "love_catalog_unavailable"}
    try:
        record = _load_record(Path(data_dir) / "master-json")
        rows = []
        for event_id, event in sorted(record["events"].items()):
            title = " ".join((event["name"] + " " + event.get("description", "")).split())
            _need(title and title.isprintable() and len(title.encode("utf-8")) <= 1024)
            rows.append({"id": event_id, "title": title, "supported": True,
                "source_grade": SOURCE_GRADE, "inference_status": INFERENCE_STATUS,
                "original_start_time_ms": _integer(event["startTime"]),
                "original_end_time_ms": None, "original_duration_ms": None})
        return {"schema": 1, "available": True, "events": rows, "ruleset_sha256": record["ruleset_sha256"],
                "reason_code": None}
    except Exception:
        return unavailable
