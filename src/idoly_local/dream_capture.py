"""Validate private event archives and restore captured Dream read responses.

Only supplied files are read. This module never contacts the official service,
generates areas, consumes photos/manuals, reconciles a month or grants rewards.
The returned catalog includes private account data; never ship it in a payload.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure

USER, MASTER, HOME = "/api.User/Get", "/api.Master/Get", "/api.Home/Enter"
TOP, QUEST, MATERIAL = "/api.Dream/Top", "/api.Dream/ListQuest", "/api.Dream/ListMaterialPhoto"
READS = frozenset((TOP, QUEST, MATERIAL))
_DREAM_RECORDS = READS | {USER, MASTER, HOME}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_MESSAGE = 16 * 1024 * 1024
_MAX_CATALOG = 64 * 1024 * 1024
_MAX_ARCHIVE = 256 * 1024 * 1024


class DreamCaptureError(ValueError):
    """Fixed reason codes, without private paths, names or remote details."""
    def __init__(self, code):
        self.code = code
        super().__init__("Dream preservation unavailable: " + code)


def _need(value, code="catalog_invalid"):
    if not value:
        raise DreamCaptureError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _identity(value):
    return type(value) is str and 0 < len(value.encode("utf-8")) <= 256 and all(ord(c) >= 32 for c in value)


def owner_pair(snapshot):
    _need(snapshot.HasField("user") and snapshot.HasField("userPublic"), "owner_missing")
    pair = (snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId)
    _need(all(_identity(value) for value in pair), "owner_missing")
    return pair


def _timestamp(value):
    _need(type(value) is str, "capture_time_invalid")
    try:
        parsed = datetime.fromisoformat(value)
        _need(parsed.tzinfo is not None, "capture_time_invalid")
        stamp = int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise DreamCaptureError("capture_time_invalid") from None
    _need(0 < stamp <= _now_ms(), "capture_time_invalid")
    return stamp


def _read_file(path, limit):
    """Reject symlinks and bound the actual read, not just a size in JSON."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            _need(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "source_file_invalid")
            raw = stream.read(limit + 1)
        _need(len(raw) <= limit, "source_size_invalid")
        return raw
    except OSError:
        raise DreamCaptureError("source_file_unavailable") from None


def _parse(schema, method, raw, *, request=False):
    _need(method in schema.methods, "source_method_invalid")
    try:
        return (schema.request_type(method) if request else schema.response_type(method)).FromString(raw)
    except (DecodeError, ValueError, UnicodeError):
        raise DreamCaptureError("source_protobuf_invalid") from None


def _record(method, request_raw, response_raw):
    return {"method": method, "request_b64": base64.b64encode(request_raw).decode(),
            "request_sha256": _sha(request_raw), "response_b64": base64.b64encode(response_raw).decode(),
            "response_sha256": _sha(response_raw)}


@dataclass(frozen=True, repr=False)
class CapturedRecord:
    index: int
    method: str
    purpose: str
    captured_at_ms: int
    request_raw: bytes
    response_raw: bytes
    request: object
    response: object

    def as_catalog_record(self):
        return _record(self.method, self.request_raw, self.response_raw)


@dataclass(frozen=True, repr=False)
class CaptureDirectory:
    records: tuple
    final_snapshot: object
    owner: tuple
    master_version: str
    captured_at_ms: int
    source_manifest_sha256: str


def read_capture_directory(schema, directory):
    """Read the collector's bounded archive, with its consistent final User.Get.

    An archive may be incomplete for another event. A missing final snapshot,
    changed owner, invalid file pin or an unbound passive capture is rejected.
    Callers must separately validate completeness of their event's responses.
    """
    directory = Path(directory)
    _need(not directory.is_symlink() and directory.is_dir(), "source_directory_invalid")
    raw_manifest = _read_file(directory / "manifest.json", 1024 * 1024)
    try:
        manifest = json.loads(raw_manifest)
    except (ValueError, UnicodeError):
        raise DreamCaptureError("manifest_invalid") from None
    _need(isinstance(manifest, dict) and type(manifest.get("schema")) is int
          and manifest["schema"] == 1 and manifest.get("schema_sha256") == schema.fingerprint,
          "schema_mismatch")
    _need(type(manifest.get("mode")) is str
          and manifest["mode"] in {"existing-official-session", "observed-response-import"}
          and manifest.get("request_session_metadata_stored") is False, "manifest_invalid")
    created = _timestamp(manifest.get("created_at"))
    rows = manifest.get("records")
    _need(isinstance(rows, list) and 4 <= len(rows) <= 128, "source_count_invalid")
    final_index = manifest.get("consistent_snapshot_record")
    _need(type(final_index) is int and final_index == len(rows), "consistent_snapshot_missing")
    result, total, last_time = [], 0, created
    # Import observed archives may contain historical mutations as calibration
    # records. They are parsed as files only and are never replayed by Dream.
    for index, row in enumerate(rows, 1):
        _need(isinstance(row, dict) and type(row.get("index")) is int and row["index"] == index,
              "source_order_invalid")
        method, purpose = row.get("method"), row.get("purpose")
        _need(type(method) is str and method in schema.methods and type(purpose) is str,
              "source_method_invalid")
        when = _timestamp(row.get("captured_at"))
        _need(when >= last_time, "source_order_invalid")
        last_time = when
        contents = {}
        for kind in ("request", "response", "wire-response"):
            if kind == "wire-response" and kind not in row:
                continue
            metadata = row.get(kind)
            name = f"{index:04d}.{kind}.pb"
            _need(isinstance(metadata, dict) and metadata.get("file") == name
                  and type(metadata.get("bytes")) is int and 0 <= metadata["bytes"]
                  <= (_MAX_MESSAGE + 1024 * 1024 if kind == "wire-response" else
                      65536 if kind == "request" else _MAX_MESSAGE)
                  and type(metadata.get("sha256")) is str and _HASH.fullmatch(metadata["sha256"]),
                  "source_file_invalid")
            raw = _read_file(directory / name, metadata["bytes"])
            _need(len(raw) == metadata["bytes"] and _sha(raw) == metadata["sha256"], "source_pin_mismatch")
            total += len(raw)
            _need(total <= _MAX_ARCHIVE, "source_size_invalid")
            contents[kind] = raw
        result.append(CapturedRecord(index, method, purpose, when, contents["request"], contents["response"],
            _parse(schema, method, contents["request"], request=True),
            _parse(schema, method, contents["response"])))
    final = result[-1]
    _need(final.method == USER and final.purpose == "final-account-snapshot" and not final.request_raw,
          "consistent_snapshot_missing")
    initial = [row for row in result[:-1] if row.method == USER and row.purpose == "initial-account-snapshot"]
    _need(len(initial) == 1 and not initial[0].request_raw, "consistent_snapshot_missing")
    owner = owner_pair(final.response)
    _need(owner_pair(initial[0].response) == owner, "owner_mismatch")
    masters = [row for row in result if row.method == MASTER]
    _need(len(masters) == 1 and not masters[0].request_raw and masters[0].response.HasField("masterTag")
          and bool(masters[0].response.masterTag.version), "master_missing")
    _need(masters[0].index < initial[0].index, "source_order_invalid")
    return CaptureDirectory(tuple(result), final.response, owner, masters[0].response.masterTag.version,
                            final.captured_at_ms, _sha(raw_manifest))


def _decode(value, digest):
    _need(type(value) is str and len(value) <= ((_MAX_MESSAGE + 2) // 3) * 4
          and type(digest) is str and _HASH.fullmatch(digest))
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise DreamCaptureError("catalog_invalid") from None
    _need(len(raw) <= _MAX_MESSAGE and base64.b64encode(raw).decode() == value)
    _need(_sha(raw) == digest, "source_pin_mismatch")
    return raw


def _photos(snapshot):
    rows = {}
    for row in snapshot.photos:
        _need(_identity(row.photoId) and row.photoId not in rows and row.rarity >= 0 and row.level >= 0,
              "owned_photos_invalid")
        rows[row.photoId] = row
    return rows


def _photo_signature(photo):
    # Lock/favorite/recipe and enhancement state affect material eligibility.
    # Preserve field order and unknown fields rather than guessing their role.
    return photo.SerializeToString(deterministic=True)


def _nonnegative(message):
    for field, value in message.ListFields():
        for item in value if field.is_repeated else (value,):
            if field.message_type is not None:
                _nonnegative(item)
            elif field.enum_type is not None:
                _need(item in field.enum_type.values_by_number, "definition_invalid")
            elif field.type in (field.TYPE_INT32, field.TYPE_INT64):
                _need(item >= 0, "definition_invalid")


def validate_dream_catalog(schema, data, *, master_version=None, snapshot=None, now_ms=None):
    """Validate pinned owner/season and each base-photo-bound read response."""
    _need(isinstance(data, dict) and type(data.get("schema")) is int and data["schema"] == 1)
    _need(data.get("schema_sha256") == schema.fingerprint, "schema_mismatch")
    version = data.get("master_version")
    _need(type(version) is str and bool(version) and (master_version is None or version == master_version),
          "master_mismatch")
    captured = data.get("captured_at_ms")
    now_ms = _now_ms() if now_ms is None else now_ms
    _need(type(now_ms) is int and type(captured) is int and 0 < captured <= now_ms, "capture_time_invalid")
    pin = data.get("source_manifest_sha256")
    _need(type(pin) is str and _HASH.fullmatch(pin), "source_pin_mismatch")
    rows = data.get("responses")
    _need(isinstance(rows, list) and 4 <= len(rows) <= 128)
    parsed = {}
    for row in rows:
        _need(isinstance(row, dict) and type(row.get("method")) is str and row["method"] in _DREAM_RECORDS)
        method = row["method"]
        req_raw = _decode(row.get("request_b64"), row.get("request_sha256"))
        res_raw = _decode(row.get("response_b64"), row.get("response_sha256"))
        req, res = _parse(schema, method, req_raw, request=True), _parse(schema, method, res_raw)
        if method in {USER, MASTER, TOP}:
            _need(req_raw == b"", "request_binding_invalid")
            key = method
        elif method == HOME:
            _need(req.skipUpdate and req_raw == schema.request_type(HOME)(skipUpdate=True).SerializeToString(),
                  "request_binding_invalid")
            key = method
        else:
            _need(_identity(req.basePhotoId) and req_raw ==
                  schema.request_type(method)(basePhotoId=req.basePhotoId).SerializeToString(), "request_binding_invalid")
            key = (method, req.basePhotoId)
        _need(key not in parsed, "duplicate_source")
        parsed[key] = (req, res)
    _need(all(method in parsed for method in (USER, MASTER, HOME, TOP)), "definition_missing")
    saved = parsed[USER][1]
    owner = owner_pair(saved)
    _need(data.get("owner") == {"server_user_id": owner[0], "public_user_id": owner[1]}, "owner_mismatch")
    master = parsed[MASTER][1]
    _need(master.HasField("masterTag") and master.masterTag.version == version, "master_mismatch")
    home_response, top = parsed[HOME][1], parsed[TOP][1]
    _need(home_response.HasField("eventInfo") and home_response.eventInfo.HasField("dreamInfo")
          and top.HasField("seasonInfo"), "definition_missing")
    home, season = home_response.eventInfo.dreamInfo, top.seasonInfo
    _need(_identity(season.id) and bool(season.name) and 0 < season.startTime <= captured <= season.endTime
          and season.endTime >= season.startTime, "season_invalid")
    _need(all(getattr(home, key) == getattr(season, key) for key in
              ("startTime", "endTime", "generateAreaItemId", "assetId"))
          and bool(home.unlockConditionId) and bool(season.generateAreaItemId), "season_mismatch")
    owned = _photos(saved)
    current = _photos(snapshot) if snapshot is not None else owned
    if snapshot is not None:
        _need(owner_pair(snapshot) == owner, "owner_mismatch")
        _need(set(current) == set(owned) and all(_photo_signature(current[key]) == _photo_signature(row)
              for key, row in owned.items()), "owned_photo_changed")
        _need(snapshot.HasField("profile") == saved.HasField("profile"), "owned_photo_changed")
        if saved.HasField("profile"):
            _need(snapshot.profile.favoritePhotoId == saved.profile.favoritePhotoId, "owned_photo_changed")
    top_rows = {}
    for row in top.dreamUserPhotos:
        _need(_identity(row.photoId) and row.photoId not in top_rows and row.photoId in owned
              and owned[row.photoId].rarity >= 4, "photo_reference_invalid")
        _need(row.photoId in current and _photo_signature(current[row.photoId]) == _photo_signature(owned[row.photoId]),
              "owned_photo_changed")
        _nonnegative(row)
        _need(row.generatedTime <= captured and row.lastChallengedTime <= captured
              and row.clearQuestNumber <= row.maxQuestNumber
              and row.currentGrowthPermil <= row.maxGrowthPermil, "area_progress_invalid")
        generated = bool(row.generatedTime or row.maxQuestNumber or owned[row.photoId].isDreamBase)
        _need(not generated or (owned[row.photoId].isDreamBase and row.generatedTime > 0
              and row.maxQuestNumber > 0 and (QUEST, row.photoId) in parsed), "generated_area_missing")
        top_rows[row.photoId] = row
    _need(all(not row.isDreamBase or key in top_rows for key, row in current.items()), "generated_area_missing")
    for key, (_, response) in parsed.items():
        if not isinstance(key, tuple):
            continue
        method, base = key
        _need(base in top_rows, "photo_reference_invalid")
        if method == QUEST:
            parent = top_rows[base]
            _need(owned[base].isDreamBase and response.maxQuestNumber == parent.maxQuestNumber
                  and response.clearQuestNumber == parent.clearQuestNumber, "area_progress_invalid")
            numbers = [row.questNumber for row in response.questInfos]
            _need(len(numbers) == response.maxQuestNumber
                  and all(number == index for index, number in enumerate(numbers, 1)), "quest_definition_invalid")
            for row in response.questInfos:
                _nonnegative(row)
        else:
            ids = set()
            for row in response.userMaterialPhotos:
                _need(_identity(row.photoId) and row.photoId != base and row.photoId not in ids
                      and row.photoId in owned and row.photoId in current and owned[row.photoId].rarity >= 4
                      and not owned[row.photoId].isDreamBase
                      and _photo_signature(current[row.photoId]) == _photo_signature(owned[row.photoId]),
                      "material_reference_invalid")
                _nonnegative(row)
                ids.add(row.photoId)
    return parsed


def build_dream_catalog(schema, capture_directory, output_path=None):
    """Convert an archive to a private Dream catalog; no network/account writes.

    With no output_path, return its JSON-ready dict. With a path, atomically
    write it with mode 0600 as well. Errors contain fixed codes only.
    """
    source = read_capture_directory(schema, capture_directory)
    selected = [row for row in source.records if row.method in _DREAM_RECORDS
                and (row.method != USER or row.purpose == "final-account-snapshot")]
    result = {"schema": 1, "schema_sha256": schema.fingerprint, "master_version": source.master_version,
              "captured_at_ms": source.captured_at_ms,
              "source_manifest_sha256": source.source_manifest_sha256,
              "owner": {"server_user_id": source.owner[0], "public_user_id": source.owner[1]},
              "responses": [row.as_catalog_record() for row in selected]}
    validate_dream_catalog(schema, result)
    if output_path is not None:
        output_path = Path(output_path)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(prefix=".dream-private-", dir=output_path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
                os.chmod(name, 0o600)
                os.replace(name, output_path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        except OSError:
            raise DreamCaptureError("output_unavailable") from None
    return result


def load_dream_catalog(schema, path, *, master_version, snapshot, now_ms):
    """Runtime loader: convert private parsing errors to safe RPC failures."""
    try:
        raw = _read_file(path, _MAX_CATALOG)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise DreamCaptureError("catalog_invalid") from None
        return validate_dream_catalog(schema, data, master_version=master_version, snapshot=snapshot, now_ms=now_ms)
    except DreamCaptureError as error:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Dream private capture unavailable: " + error.code) from None


def sanitized_response(response):
    """Replay information only, without transaction updates/deletions or gifts."""
    result = type(response)()
    result.CopyFrom(response)
    result.DiscardUnknownFields()
    result.ClearField("commonResponse")
    result.commonResponse.SetInParent()
    if "loginRewardResults" in result.DESCRIPTOR.fields_by_name:
        result.ClearField("loginRewardResults")
        result.ClearField("dokanInfos")
        result.seasonInfo.ClearField("eventMissionInfo")
        for row in result.dreamUserPhotos:
            row.isDisableGenerateArea = True
    if "questInfos" in result.DESCRIPTOR.fields_by_name:
        for row in result.questInfos:
            row.isPlayable = False
            row.isSkipAvailable = False
    return result
