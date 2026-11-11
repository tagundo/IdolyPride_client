"""Private preservation of already observed or existing-session event responses.

The active allowlist cannot start a battle, generate/reset an area, claim a
reward, sign in, refresh a token, or initialize a day. Dream/Pvp Top are normal
menu visits and can themselves reconcile official state; they require opt-in.
All responses, including account and opponent data, stay in a private archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import grpc
from google.protobuf.message import DecodeError

from . import codec
from .collect import (_application_codes, _atomic_private, _load_metadata,
                      _tls_credentials, _METADATA_KEY, OFFICIAL_TARGET)

MASTER = "/api.Master/Get"
USER = "/api.User/Get"
HOME = "/api.Home/Enter"
QUEST = "/api.Quest/Top"
DREAM_TOP = "/api.Dream/Top"
DREAM_QUEST = "/api.Dream/ListQuest"
DREAM_MATERIAL = "/api.Dream/ListMaterialPhoto"
PVP_TOP = "/api.Pvp/Top"
PVP_OPPONENT = "/api.Pvp/ListOpponent"
PVP_ASSET = "/api.Pvp/ListAsset"
ACTIVE_METHODS = frozenset((MASTER, USER, HOME, QUEST, DREAM_TOP, DREAM_QUEST,
                            DREAM_MATERIAL, PVP_TOP, PVP_OPPONENT, PVP_ASSET))
# These are importable observations, NEVER callable by the active collector.
OBSERVED_METHODS = ACTIVE_METHODS | frozenset((
    "/api.Dream/GenerateArea", "/api.Dream/ResetArea", "/api.Dream/StartQuest",
    "/api.Dream/SkipQuest", "/api.Pvp/Start"))
_FIELDS = {MASTER: {}, USER: {}, HOME: {"skipUpdate": 8}, QUEST: {},
           DREAM_TOP: {}, DREAM_QUEST: {"basePhotoId": 9},
           DREAM_MATERIAL: {"basePhotoId": 9}, PVP_TOP: {},
           PVP_OPPONENT: {"pvpSeasonId": 9},
           PVP_ASSET: {"pvpSeasonId": 9, "opponentId": 9, "deckNumber": 5}}
MAX_RESPONSE = 16 * 1024 * 1024
MAX_WIRE = 17 * 1024 * 1024
MAX_REQUEST = 64 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_RECORDS = 128
_JST = timezone(timedelta(hours=9))


class EventCaptureError(RuntimeError):
    """Fixed error codes only; never expose remote details or credentials."""
    def __init__(self, code):
        self.code = code
        super().__init__("Event preservation stopped: " + code)


def _need(ok, code):
    if not ok:
        raise EventCaptureError(code)


def _now():
    return datetime.now(timezone.utc)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return (isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 256
            and all(ord(c) >= 32 for c in value))


def _credential_values(metadata):
    values = set()
    for key, value in metadata:
        if key != "authorization" and not key.endswith("-token"):
            continue
        values.add(value.encode("ascii"))
        parts = value.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            # Responses may echo the token without the Authorization scheme.
            values.add(parts[1].strip().encode("ascii"))
    return values


def _schema(schema):
    try:
        for method, expected in _FIELDS.items():
            descriptor = schema.method(method)
            fields = descriptor.input_type.fields_by_name
            _need(set(fields) == set(expected) and all(not f.is_repeated and f.type == expected[n]
                  for n, f in fields.items()), "unsupported_request_schema")
    except (ValueError, KeyError, AttributeError, TypeError):
        raise EventCaptureError("unsupported_request_schema") from None


def _parse(schema, method, raw, *, request=False, wire=False):
    _need(type(method) is str and method in OBSERVED_METHODS, "method_not_allowed")
    _need(type(raw) is bytes and len(raw) <= (MAX_WIRE if wire else
          MAX_REQUEST if request else MAX_RESPONSE), "message_size_invalid")
    try:
        plain = codec.decode(raw) if wire else raw
        _need(len(plain) <= (MAX_REQUEST if request else MAX_RESPONSE), "message_size_invalid")
        cls = schema.request_type(method) if request else schema.response_type(method)
        return plain, cls.FromString(plain)
    except (ValueError, DecodeError, KeyError, TypeError, AttributeError):
        raise EventCaptureError("malformed_request" if request else "malformed_response") from None


@dataclass(frozen=True, repr=False)
class ObservedResponse:
    method: str
    response: bytes
    request: bytes | None = None
    response_is_wire: bool = False
    request_is_wire: bool = False


class _Archive:
    def __init__(self, schema, output, mode, visit_menus=False):
        self.output = Path(output)
        _need(not os.path.lexists(self.output), "output_exists")
        try:
            self.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.output.mkdir(mode=0o700)
            self.output.chmod(0o700)
        except OSError:
            raise EventCaptureError("cannot_create_private_output") from None
        self.total = 0
        self.manifest = {"schema": 1, "schema_sha256": schema.fingerprint,
            "created_at": _now().isoformat(), "mode": mode,
            "normal_menu_visits_requested": visit_menus,
            "normal_menu_visits_may_reconcile_account_state": visit_menus,
            "complete": False, "stopped_code": None, "records": [],
            "limitations": [], "consistent_snapshot_record": None,
            "request_session_metadata_stored": False}
        self.flush()

    def flush(self):
        try:
            _atomic_private(self.output / "manifest.json",
                (json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n").encode())
            os.chmod(self.output / "manifest.json", 0o600)
        except OSError:
            raise EventCaptureError("cannot_save_private_archive") from None

    def record(self, method, request, response, wire=None, *, purpose="observed"):
        records = self.manifest["records"]
        _need(len(records) < MAX_RECORDS, "record_limit_reached")
        content = {"request": request, "response": response}
        if wire is not None:
            content["wire-response"] = wire
        _need(self.total + sum(len(v) for v in content.values()) <= MAX_ARCHIVE,
              "archive_size_limit_reached")
        index = len(records) + 1
        row = {"index": index, "method": method, "purpose": purpose,
               "captured_at": _now().isoformat()}
        try:
            for kind, raw in content.items():
                name = f"{index:04d}.{kind}.pb"
                _atomic_private(self.output / name, raw)
                os.chmod(self.output / name, 0o600)
                row[kind] = {"file": name, "bytes": len(raw), "sha256": _sha(raw)}
        except OSError:
            raise EventCaptureError("cannot_save_private_archive") from None
        self.total += sum(len(v) for v in content.values())
        records.append(row)
        self.flush()
        return index

    def summary(self):
        # No identifiers, paths, payloads, metadata, remote text or header values.
        return {"complete": self.manifest["complete"],
                "captured_responses": len(self.manifest["records"]),
                "captured_bytes": self.total,
                "consistent_final_snapshot": self.manifest["consistent_snapshot_record"] is not None,
                "limitation_count": len(self.manifest["limitations"]),
                "stopped_code": self.manifest["stopped_code"],
                "credentials_exported": False}


def import_observed(schema, observations, output):
    """Preserve explicitly supplied prior observations; performs no network IO.

    Mutating RPC responses may be imported for calibration, but are never sent.
    Nonempty-request methods require their original matching request bytes.
    """
    _need(isinstance(observations, (list, tuple)) and 0 < len(observations) <= MAX_RECORDS,
          "observation_count_invalid")
    validated, input_total, archive_total = [], 0, 0
    for observation in observations:
        _need(type(observation) is ObservedResponse, "observation_invalid")
        method = observation.method
        _need(type(method) is str and method in OBSERVED_METHODS, "method_not_allowed")
        _need(type(observation.response_is_wire) is bool and type(observation.request_is_wire) is bool,
              "observation_invalid")
        try:
            fields = schema.method(method).input_type.fields_by_name
        except (ValueError, KeyError, AttributeError):
            raise EventCaptureError("unsupported_request_schema") from None
        raw_request = observation.request
        if raw_request is None:
            _need(not fields, "original_request_required")
            raw_request = b""
        _need(type(raw_request) is bytes and type(observation.response) is bytes, "message_size_invalid")
        input_total += len(raw_request) + len(observation.response)
        _need(input_total <= MAX_ARCHIVE, "archive_size_limit_reached")
        request, _ = _parse(schema, method, raw_request, request=True, wire=observation.request_is_wire)
        response, _ = _parse(schema, method, observation.response, wire=observation.response_is_wire)
        wire = observation.response if observation.response_is_wire else None
        archive_total += len(request) + len(response) + (len(wire) if wire is not None else 0)
        _need(archive_total <= MAX_ARCHIVE, "archive_size_limit_reached")
        validated.append((method, request, response,
                          wire))
    archive = _Archive(schema, output, "observed-response-import")
    try:
        for values in validated:
            archive.record(*values)
        archive.manifest["complete"] = True
        archive.flush()
        return archive.summary()
    except EventCaptureError as error:
        archive.manifest["stopped_code"] = error.code
        archive.flush()
        raise


def _deck_number(user):
    cards = {row.cardId for row in user.cards}
    numbers = [row.number for row in user.decks if row.number > 0]
    if len(numbers) != len(set(numbers)):
        return None
    for number in sorted(numbers):
        positions = [row for row in user.deckPositions if row.number == number]
        if (sorted(row.position for row in positions) == [1, 2, 3, 4, 5]
                and len({row.cardId for row in positions}) == 5
                and all(row.cardId in cards and not getattr(row, "buddyUserId", "") for row in positions)):
            return number
    return None


def collect_events(schema, metadata_file, output, *, visit_menus=False,
                   roots_file=None, timeout=15, deadline_seconds=300,
                   photo_limit=16, opponent_limit=6, target=OFFICIAL_TARGET):
    """File-based entry point; private session metadata is never archived."""
    _need(target == OFFICIAL_TARGET, "official_tls_target_required")
    try:
        metadata = dict(_load_metadata(Path(metadata_file)))
    except RuntimeError:
        raise EventCaptureError("session_metadata_invalid") from None
    return collect_in_memory(schema, metadata, output, visit_menus=visit_menus,
        roots_file=roots_file, timeout=timeout, deadline_seconds=deadline_seconds,
        photo_limit=photo_limit, opponent_limit=opponent_limit, target=target)


def collect_in_memory(schema, metadata, output, *, visit_menus=False,
                      roots_file=None, timeout=15, deadline_seconds=300,
                      photo_limit=16, opponent_limit=6, target=OFFICIAL_TARGET):
    """Collect a bounded fixed allowlist using an existing official session.

    ``visit_menus`` expressly permits normal Dream/Pvp menu visits, which can
    reconcile monthly/season state or grant ordinary menu-login rewards. The
    collector never creates an area, consumes a photo, fights, claims, logs in,
    refreshes, retries, or initializes a day. A final User.Get is saved separately
    after visits to bind later imports to the observed post-visit account state.
    """
    _need(target == OFFICIAL_TARGET, "official_tls_target_required")
    _need(type(visit_menus) is bool and type(timeout) in (int, float) and 0 < timeout <= 30
          and type(deadline_seconds) in (int, float) and 0 < deadline_seconds <= 900,
          "capture_options_invalid")
    _need(type(photo_limit) is int and 0 <= photo_limit <= 32
          and type(opponent_limit) is int and 0 <= opponent_limit <= 20, "capture_options_invalid")
    _schema(schema)
    _need(type(metadata) is dict and 0 < len(metadata) <= 64, "session_metadata_invalid")
    _need(all(type(key) is str and type(value) is str and _METADATA_KEY.fullmatch(key)
              and not key.endswith("-bin") and 0 < len(value) <= 16384
              and all(32 <= ord(char) < 127 for char in value)
              for key, value in metadata.items()), "session_metadata_invalid")
    _need(all(metadata.get(key, "").strip() for key in
              ("x-app-version", "x-auth-token", "x-master-version")), "session_metadata_invalid")
    metadata = list(metadata.items())
    credential_values = _credential_values(metadata)
    _need(not any(key in {"x-app-request-id", "grpc-timeout", "content-type", "te"}
                  for key, _ in metadata), "per_request_metadata_not_allowed")
    expected_master = dict(metadata)["x-master-version"]
    try:
        credentials = _tls_credentials(roots_file)
    except RuntimeError:
        raise EventCaptureError("tls_roots_invalid") from None
    archive = _Archive(schema, output, "existing-official-session", visit_menus)
    began, day = time.monotonic(), _now().astimezone(_JST).date()
    seen, user_calls = set(), 0
    try:
        with grpc.secure_channel(OFFICIAL_TARGET, credentials, options=(
                ("grpc.enable_retries", 0), ("grpc.max_receive_message_length", MAX_WIRE))) as channel:
            def capture(method, *, purpose="preservation", expected_account=None, **fields):
                nonlocal user_calls
                _need(method in ACTIVE_METHODS, "method_not_allowed")
                _need(method not in (DREAM_TOP, PVP_TOP) or visit_menus, "menu_visit_not_enabled")
                _need(_now().astimezone(_JST).date() == day, "day_changed")
                remaining = deadline_seconds - (time.monotonic() - began)
                _need(remaining > 0, "time_limit_reached")
                request = schema.request_type(method)(**fields).SerializeToString()
                identity = method, _sha(request)
                if method == USER:
                    user_calls += 1
                    _need(user_calls <= 2, "duplicate_request")
                else:
                    _need(identity not in seen, "duplicate_request")
                seen.add(identity)
                try:
                    raw, call = channel.unary_unary(method).with_call(codec.encode(request),
                        metadata=metadata, timeout=min(timeout, remaining))
                except grpc.RpcError:
                    raise EventCaptureError("rpc_failed") from None
                # A response can cross the day/deadline even when its request
                # began within the allowed capture window, including User.Get.
                _need(_now().astimezone(_JST).date() == day, "day_changed")
                _need(time.monotonic() - began < deadline_seconds, "time_limit_reached")
                _need(call.code() == grpc.StatusCode.OK, "rpc_failed")
                _need(not _application_codes(call), "application_error")
                for key, value in [*(call.initial_metadata() or ()), *(call.trailing_metadata() or ())]:
                    if key == "x-master-version":
                        _need(value == expected_master, "master_changed")
                plain, response = _parse(schema, method, raw, wire=True)
                _need(not any(secret in plain for secret in credential_values), "credential_reflection_detected")
                if expected_account is not None:
                    _need(method == USER and response.HasField("user") and response.HasField("userPublic")
                          and (response.userPublic.publicUserId, response.userPublic.serverUserId) == expected_account,
                          "account_changed")
                index = archive.record(method, request, plain, raw, purpose=purpose)
                return response, index

            master, _ = capture(MASTER)
            _need(master.HasField("masterTag") and master.masterTag.version == expected_master, "master_changed")
            user, _ = capture(USER, purpose="initial-account-snapshot")
            _need(user.HasField("user") and user.HasField("userPublic") and bool(user.userPublic.publicUserId),
                  "account_snapshot_incomplete")
            capture(HOME, skipUpdate=True)
            capture(QUEST)
            if visit_menus:
                dream, _ = capture(DREAM_TOP, purpose="normal-menu-visit")
                owned = {row.photoId: row for row in user.photos if row.photoId}
                if dream.HasField("commonResponse") and dream.commonResponse.HasField("updatedData"):
                    for photo in dream.commonResponse.updatedData.photos:
                        owned[photo.photoId] = photo
                rows = list(dream.dreamUserPhotos)
                _need(len(rows) <= 10000 and len({row.photoId for row in rows}) == len(rows),
                      "dream_photo_references_invalid")
                _need(all(_identity(row.photoId) and row.photoId in owned and owned[row.photoId].rarity >= 4
                          for row in rows), "dream_photo_references_invalid")
                generated = [row for row in rows if row.generatedTime > 0 or row.maxQuestNumber > 0
                             or owned[row.photoId].isDreamBase]
                if any(photo.isDreamBase and photo.photoId not in {row.photoId for row in rows}
                       for photo in owned.values()):
                    archive.manifest["limitations"].append("dream_base_photo_missing_top")
                previews = [row for row in rows if not row.isDisableGenerateArea
                            and not owned[row.photoId].isDreamBase]
                if len(generated) > photo_limit or len(previews) > photo_limit:
                    archive.manifest["limitations"].append("dream_photo_limit")
                for row in generated[:photo_limit]:
                    capture(DREAM_QUEST, basePhotoId=row.photoId)
                for row in previews[:photo_limit]:
                    capture(DREAM_MATERIAL, basePhotoId=row.photoId)
                if not dream.HasField("seasonInfo") or not dream.seasonInfo.id:
                    archive.manifest["limitations"].append("dream_season_missing")
                pvp, _ = capture(PVP_TOP, purpose="normal-menu-visit")
                if pvp.HasField("topResult") and pvp.topResult.HasField("pvpSeason"):
                    season = pvp.topResult.pvpSeason.id
                    _need(_identity(season), "pvp_season_invalid")
                    opponents, _ = capture(PVP_OPPONENT, pvpSeasonId=season)
                    top_rows = list(pvp.opponentInfos)
                    fetched_rows = list(opponents.opponentInfos)
                    _need(len(top_rows) <= 10000 and len({row.opponentId for row in top_rows}) == len(top_rows)
                          and all(_identity(row.opponentId) for row in top_rows), "pvp_opponents_invalid")
                    # Preserve assets for every distinct observed opponent, not
                    # only the possibly refreshed list from ListOpponent.
                    by_id = {row.opponentId: row for row in top_rows}
                    for row in fetched_rows:
                        if row.opponentId in by_id and row.SerializeToString() != by_id[row.opponentId].SerializeToString():
                            archive.manifest["limitations"].append("pvp_opponent_changed_between_reads")
                        by_id[row.opponentId] = row
                    rows = list(by_id.values())
                    _need(len(fetched_rows) <= 10000 and len({row.opponentId for row in fetched_rows}) == len(fetched_rows)
                          and all(_identity(row.opponentId) for row in rows), "pvp_opponents_invalid")
                    deck = _deck_number(user)
                    if len(rows) > opponent_limit:
                        archive.manifest["limitations"].append("pvp_opponent_limit")
                    if rows and deck is None:
                        archive.manifest["limitations"].append("pvp_saved_deck_missing")
                    if deck is not None:
                        for row in rows[:opponent_limit]:
                            capture(PVP_ASSET, pvpSeasonId=season, opponentId=row.opponentId, deckNumber=deck)
                else:
                    archive.manifest["limitations"].append("pvp_season_missing")
            _final, index = capture(USER, purpose="final-account-snapshot",
                expected_account=(user.userPublic.publicUserId, user.userPublic.serverUserId))
            archive.manifest["consistent_snapshot_record"] = index
            archive.manifest["complete"] = not archive.manifest["limitations"]
            archive.flush()
            return archive.summary()
    except EventCaptureError as error:
        archive.manifest["stopped_code"] = error.code
        archive.flush()
        raise
    except Exception:
        archive.manifest["stopped_code"] = "capture_failed"
        archive.flush()
        raise EventCaptureError("capture_failed") from None
