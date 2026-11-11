"""Synthetic collection directories import only their own final account state."""
import base64
from datetime import datetime, timezone
import json
import stat

import pytest

from idoly_local import dream_capture, event_capture
from idoly_local.dream_capture import DreamCaptureError
from idoly_local.pvp_capture import build_pvp_catalog, USER, MASTER

from test_pvp import game, schema, NOW
from test_live_assets import game as asset_game


def archive(game, directory, monkeypatch, *, omit=None):
    monkeypatch.setattr(event_capture, "_now", lambda: datetime.fromtimestamp(NOW / 1000, timezone.utc))
    monkeypatch.setattr(dream_capture, "_now_ms", lambda: NOW)
    store = event_capture._Archive(game.schema, directory, "existing-official-session", True)
    records = sorted(game.data["responses"], key=lambda row: row["method"] != MASTER)
    for row in records:
        if row["method"] == omit:
            continue
        store.record(row["method"], base64.b64decode(row["request_b64"]),
                     base64.b64decode(row["response_b64"]),
                     purpose="initial-account-snapshot" if row["method"] == USER else "preservation")
    store.manifest["consistent_snapshot_record"] = store.record(USER, b"",
        game.state.snapshot("player")[0], purpose="final-account-snapshot")
    store.manifest["complete"] = True
    store.flush()
    return directory


def test_archive_conversion_uses_final_snapshot_and_loads_same_owner_runtime(game, tmp_path, monkeypatch):
    directory = archive(game, tmp_path / "capture", monkeypatch)
    output = game.path
    result = build_pvp_catalog(game.schema, directory, output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert result["owner"] == game.data["owner"]
    users = [r for r in result["responses"] if r["method"] == USER]
    assert len(users) == 1 and base64.b64decode(users[0]["response_b64"]) == game.state.snapshot("player")[0]
    raw = game.provider.handle("/api.Pvp/Top", b"")
    top = game.schema.response_type("/api.Pvp/Top").FromString(raw)
    assert top.topResult.pvpSeason.id == game.top.topResult.pvpSeason.id
    assert not top.commonResponse.updatedData.HasField("balance")


@pytest.mark.parametrize("omit", ["/api.Pvp/Top", "/api.Pvp/ListAsset", "/api.Quest/Top"])
def test_partial_event_capture_does_not_replace_previous_catalog(game, tmp_path, monkeypatch, omit):
    directory = archive(game, tmp_path / "capture", monkeypatch, omit=omit)
    before = game.path.read_bytes()
    with pytest.raises(DreamCaptureError):
        build_pvp_catalog(game.schema, directory, game.path)
    assert game.path.read_bytes() == before


def test_tampered_file_and_missing_final_snapshot_are_rejected(game, tmp_path, monkeypatch):
    directory = archive(game, tmp_path / "capture", monkeypatch)
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["consistent_snapshot_record"] = None
    path.write_text(json.dumps(manifest))
    with pytest.raises(DreamCaptureError, match="consistent_snapshot_missing"):
        build_pvp_catalog(game.schema, directory)
    manifest["consistent_snapshot_record"] = len(manifest["records"])
    path.write_text(json.dumps(manifest))
    (directory / "0001.response.pb").write_bytes(b"changed")
    with pytest.raises(DreamCaptureError):
        build_pvp_catalog(game.schema, directory)
