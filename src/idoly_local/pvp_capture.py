"""Convert an account-bound private archive to VENUS read data, entirely offline."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .dream_capture import DreamCaptureError, read_capture_directory

USER, MASTER, QUEST = "/api.User/Get", "/api.Master/Get", "/api.Quest/Top"
TOP, OPPONENTS, ASSET = "/api.Pvp/Top", "/api.Pvp/ListOpponent", "/api.Pvp/ListAsset"
_RECORDS = frozenset((USER, MASTER, QUEST, TOP, OPPONENTS, ASSET))


def _need(value, code):
    if not value:
        raise DreamCaptureError(code)


def build_pvp_catalog(schema, capture_directory, output_path=None):
    """Keep the final snapshot and exact captured season/opponent requests.

    The runtime additionally validates every battle master and opponent style
    against the installed master. Conversion does not import a local profile,
    run a battle, reconcile a season or grant any captured response delta.
    """
    source = read_capture_directory(schema, capture_directory)
    selected = [row for row in source.records if row.method in _RECORDS
                and (row.method != USER or row.purpose == "final-account-snapshot")]
    seen, singleton = set(), {}
    for row in selected:
        if row.method in (USER, MASTER, QUEST, TOP):
            _need(not row.request_raw, "pvp_request_invalid")
            key = row.method
            singleton[key] = row
        elif row.method == ASSET:
            _need(bool(row.request.opponentId) and row.request.deckNumber > 0, "pvp_request_invalid")
            key = (ASSET, row.request.opponentId)
        else:
            key = row.method
        _need(key not in seen, "pvp_duplicate_source")
        seen.add(key)
    _need(all(method in singleton for method in (USER, MASTER, QUEST, TOP)), "pvp_definition_missing")
    top = singleton[TOP].response
    _need(top.HasField("topResult") and top.topResult.HasField("pvpSeason")
          and top.topResult.HasField("pvpQuest") and top.topResult.HasField("userPvpSeason"),
          "pvp_definition_missing")
    season = top.topResult.pvpSeason
    _need(bool(season.id) and 0 < season.startTime <= source.captured_at_ms <= season.endTime
          and season.endTime <= season.aggregateEndTime and season.endTime < season.nextStartTime,
          "pvp_capture_outside_season")
    header = singleton[QUEST].response
    _need(header.HasField("pvpInfo") and header.pvpInfo.HasField("latestPvpSeason"),
          "pvp_header_missing")
    _need(header.pvpInfo.latestPvpSeason.SerializeToString() == season.SerializeToString(),
          "pvp_season_mismatch")
    opponents = {}
    for row in [singleton[TOP], *[r for r in selected if r.method == OPPONENTS]]:
        batch = set()
        for opponent in row.response.opponentInfos:
            _need(bool(opponent.opponentId) and opponent.opponentId not in batch,
                  "pvp_opponent_invalid")
            batch.add(opponent.opponentId)
            raw = opponent.SerializeToString()
            _need(opponent.opponentId not in opponents or opponents[opponent.opponentId] == raw,
                  "pvp_opponent_source_mismatch")
            opponents[opponent.opponentId] = raw
    _need(bool(top.opponentInfos), "pvp_opponent_missing")
    asset_ids = set()
    for row in selected:
        if row.method in (ASSET, OPPONENTS):
            _need(row.request.pvpSeasonId == season.id, "pvp_season_mismatch")
        if row.method == ASSET:
            _need(row.request.opponentId in opponents and len(row.response.opponentCharacterAssets) == 5,
                  "pvp_opponent_appearance_missing")
            asset_ids.add(row.request.opponentId)
    _need(asset_ids == opponents.keys(), "pvp_opponent_appearance_missing")
    result = {"schema": 1, "schema_sha256": schema.fingerprint, "master_version": source.master_version,
              "captured_at_ms": source.captured_at_ms,
              "source_manifest_sha256": source.source_manifest_sha256,
              "owner": {"server_user_id": source.owner[0], "public_user_id": source.owner[1]},
              "responses": [row.as_catalog_record() for row in selected]}
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    _need(len(encoded) <= 32 * 1024 * 1024, "pvp_catalog_too_large")
    if output_path is not None:
        output = Path(output_path)
        try:
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(prefix=".pvp-private-", dir=output.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                os.chmod(name, 0o600)
                os.replace(name, output)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        except OSError:
            raise DreamCaptureError("output_unavailable") from None
    return result
