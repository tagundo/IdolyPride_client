"""Entirely offline private-archive restoration into an isolated new profile."""
import importlib.util
import json
from pathlib import Path
import stat
from urllib.request import OpenerDirector

import grpc
import pytest

from idoly_local import event_capture
from idoly_local.dream_capture import read_capture_directory
from idoly_local.state import State
from test_dream_capture import captured as dream_capture, schema, CAPTURED
from test_pvp import game as venus_game, asset_game, source_change
from test_pvp_capture import archive as venus_archive


@pytest.fixture
def tool(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/restore_event_capture.py"
    spec = importlib.util.spec_from_file_location("offline_restore_event_capture", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    monkeypatch.setattr(grpc, "secure_channel", lambda *a, **kw: pytest.fail("network opened"))
    monkeypatch.setattr(OpenerDirector, "open", lambda *a, **kw: pytest.fail("HTTP opened"))
    return tool


def contents(directory):
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def private_modes(directory):
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in directory.iterdir():
        assert path.is_file() and not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def no_staging(parent):
    assert not list(parent.glob(".idoly-event-restore-*"))


def test_dream_restores_exact_final_snapshot_stable_ids_and_original_times(tool, dream_capture, tmp_path):
    value = dream_capture
    before = contents(value.directory)
    source = read_capture_directory(value.schema, value.directory)
    output = tmp_path / "restored"
    result = tool.restore_capture(value.schema, value.directory, output, event="dream")
    assert result["status"] == "restored" and result["dream_catalog"] and not result["pvp_catalog"]
    private_modes(output)
    raw = source.records[-1].response_raw
    assert (output / "user-get.pb").read_bytes() == raw
    state = State(output / "state.db")
    assert state.snapshot("preserved") == (raw, value.schema.fingerprint)
    identity = state.profile("preserved")
    assert (identity["server_id"], identity["public_id"]) == source.owner
    with state.connect() as db:
        assert db.execute("SELECT count(*) FROM profiles").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM profile_lesson_progress").fetchone()[0] == 0
        assert db.execute("SELECT version FROM starter_profiles").fetchone()[0] == 0
    catalog = json.loads((output / "dream-private-catalog.json").read_text())
    assert catalog["captured_at_ms"] == value.data["captured_at_ms"] == CAPTURED
    assert catalog["owner"] == value.data["owner"]
    assert catalog["responses"] == value.data["responses"]
    assert contents(value.directory) == before
    assert "PRIVATE MANAGER" not in json.dumps(result)
    assert all(identity[key] not in json.dumps(result) for key in ("server_id", "public_id"))
    assert not (output / "fixtures").exists() and not (output / "pvp-catalog.json").exists()
    no_staging(tmp_path)


def test_venus_restores_its_private_catalog_and_stable_owner(tool, venus_game, tmp_path, monkeypatch):
    value = venus_game
    directory = venus_archive(value, tmp_path / "capture", monkeypatch)
    before = contents(directory)
    output = tmp_path / "restored"
    result = tool.restore_capture(value.schema, directory, output, event="venus", profile="my-account")
    assert result["pvp_catalog"] and not result["dream_catalog"]
    private_modes(output)
    catalog = json.loads((output / "pvp-catalog.json").read_text())
    identity = State(output / "state.db").profile("my-account")
    assert catalog["owner"] == {"server_user_id": identity["server_id"], "public_user_id": identity["public_id"]}
    assert catalog["owner"] == value.data["owner"] and contents(directory) == before
    assert not (output / "dream-private-catalog.json").exists()
    no_staging(tmp_path)


def test_venus_top_only_restores_exact_snapshot_without_creating_appearance_records(tool, venus_game, tmp_path, monkeypatch):
    value = venus_game
    directory = venus_archive(value, tmp_path / "capture", monkeypatch, omit="/api.Pvp/ListAsset")
    before = contents(directory)
    source = read_capture_directory(value.schema, directory)
    output = tmp_path / "restored"
    result = tool.restore_capture(value.schema, directory, output, event="venus", profile="my-account")
    assert result["pvp_catalog"] and not result["credentials_imported"]
    catalog = json.loads((output / "pvp-catalog.json").read_text())
    assert len(catalog["responses"]) == 4
    assert {row["method"] for row in catalog["responses"]} == {
        "/api.User/Get", "/api.Master/Get", "/api.Quest/Top", "/api.Pvp/Top"}
    state = State(output / "state.db")
    assert state.snapshot("my-account") == (source.records[-1].response_raw, value.schema.fingerprint)
    assert (output / "user-get.pb").read_bytes() == source.records[-1].response_raw
    with state.connect() as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert catalog["owner"] == value.data["owner"] and contents(directory) == before
    private_modes(output)
    no_staging(tmp_path)


def test_venus_importer_does_not_drop_a_present_malformed_appearance(tool, venus_game, tmp_path, monkeypatch):
    value = venus_game
    source_change(value, "/api.Pvp/ListAsset", lambda request, response: response.opponentCharacterAssets.pop())
    directory = venus_archive(value, tmp_path / "capture", monkeypatch)
    before = contents(directory)
    output = tmp_path / "restored"
    with pytest.raises(tool.RestoreError, match="venus_catalog_unavailable"):
        tool.restore_capture(value.schema, directory, output, event="venus")
    assert contents(directory) == before and not output.exists()
    no_staging(tmp_path)


def combined_archive(value, directory):
    source = read_capture_directory(value.schema, value.directory)
    archive = event_capture._Archive(value.schema, directory, "existing-official-session", True)
    for row in source.records[:-1]:
        archive.record(row.method, row.request_raw, row.response_raw, purpose=row.purpose)
    top_method, quest_method, asset_method = "/api.Pvp/Top", "/api.Quest/Top", "/api.Pvp/ListAsset"
    top = value.schema.response_type(top_method)()
    season = top.topResult.pvpSeason
    season.id, season.startTime, season.endTime = "synthetic-pvp-season", CAPTURED - 1, CAPTURED + 1
    season.aggregateEndTime, season.nextStartTime = CAPTURED + 2, CAPTURED + 3
    top.topResult.pvpQuest.id = "synthetic-pvp-quest"
    top.topResult.userPvpSeason.point = 1
    top.opponentInfos.add(opponentId="synthetic-opponent")
    quest = value.schema.response_type(quest_method)()
    quest.pvpInfo.latestPvpSeason.CopyFrom(season)
    asset = value.schema.response_type(asset_method)()
    for i in range(5): asset.opponentCharacterAssets.add(characterId="synthetic-" + str(i))
    archive.record(quest_method, b"", quest.SerializeToString())
    archive.record(top_method, b"", top.SerializeToString(), purpose="normal-menu-visit")
    request = value.schema.request_type(asset_method)(pvpSeasonId=season.id,
        opponentId="synthetic-opponent", deckNumber=1).SerializeToString()
    archive.record(asset_method, request, asset.SerializeToString())
    archive.manifest["consistent_snapshot_record"] = archive.record("/api.User/Get", b"",
        source.records[-1].response_raw, purpose="final-account-snapshot")
    archive.manifest["complete"] = True
    archive.flush()
    return directory


def test_both_requires_and_writes_both_catalogs_from_same_capture(tool, dream_capture, tmp_path):
    directory = combined_archive(dream_capture, tmp_path / "combined")
    output = tmp_path / "restored"
    result = tool.restore_capture(dream_capture.schema, directory, output, event="both")
    assert result["dream_catalog"] and result["pvp_catalog"]
    dream = json.loads((output / "dream-private-catalog.json").read_text())
    pvp = json.loads((output / "pvp-catalog.json").read_text())
    for key in ("source_manifest_sha256", "master_version", "owner", "captured_at_ms"):
        assert dream[key] == pvp[key]
    private_modes(output)
    no_staging(tmp_path)


def test_missing_selected_event_keeps_raw_capture_and_creates_no_output(tool, dream_capture, tmp_path):
    value, output = dream_capture, tmp_path / "restored"
    before = contents(value.directory)
    with pytest.raises(tool.RestoreError, match="venus_catalog_unavailable"):
        tool.restore_capture(value.schema, value.directory, output, event="both")
    assert contents(value.directory) == before and not output.exists()
    no_staging(tmp_path)


@pytest.mark.parametrize("kind", ("directory", "file", "symlink", "dangling-symlink"))
def test_existing_output_never_changes_or_reads_source(tool, schema, tmp_path, monkeypatch, kind):
    output = tmp_path / "existing"
    if kind == "directory":
        output.mkdir(); (output / "keep").write_text("private-existing-data")
    elif kind == "file": output.write_text("private-existing-data")
    else:
        target = tmp_path / "target"
        if kind == "symlink": target.mkdir()
        output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(tool, "read_capture_directory", lambda *a: pytest.fail("source read"))
    with pytest.raises(tool.RestoreError, match="output_exists"):
        tool.restore_capture(schema, tmp_path / "absent", output, event="dream")
    assert output.is_symlink() if "symlink" in kind else output.exists()
    if kind == "directory": assert (output / "keep").read_text() == "private-existing-data"
    if kind == "file": assert output.read_text() == "private-existing-data"
    no_staging(tmp_path)


def test_tampered_source_is_rejected_without_repair_or_output(tool, dream_capture, tmp_path):
    path = dream_capture.directory / "0001.response.pb"
    path.write_bytes(b"synthetic-tampered-source")
    before = contents(dream_capture.directory)
    output = tmp_path / "restored"
    with pytest.raises(tool.RestoreError, match="archive_invalid"):
        tool.restore_capture(dream_capture.schema, dream_capture.directory, output, event="dream")
    assert contents(dream_capture.directory) == before and not output.exists()
    no_staging(tmp_path)


def test_import_failure_is_redacted_and_cleans_staging(tool, dream_capture, tmp_path, monkeypatch):
    def fail(*a, **kw): raise RuntimeError("PRIVATE MANAGER PRIVATE_TOKEN PRIVATE_PATH")
    monkeypatch.setattr(tool, "import_profile", fail)
    output = tmp_path / "restored"
    before = contents(dream_capture.directory)
    with pytest.raises(tool.RestoreError, match="snapshot_import_failed") as error:
        tool.restore_capture(dream_capture.schema, dream_capture.directory, output, event="dream")
    assert "PRIVATE" not in str(error.value) and not output.exists()
    assert contents(dream_capture.directory) == before
    no_staging(tmp_path)


def test_destination_appearing_during_publish_is_preserved(tool, dream_capture, tmp_path, monkeypatch):
    original = tool._publish
    def publish(staging, output):
        output.mkdir()
        (output / "keep").write_text("private-existing-data")
        original(staging, output)
    monkeypatch.setattr(tool, "_publish", publish)
    output = tmp_path / "restored"
    with pytest.raises(tool.RestoreError, match="output_publish_failed"):
        tool.restore_capture(dream_capture.schema, dream_capture.directory, output, event="dream")
    assert (output / "keep").read_text() == "private-existing-data"
    no_staging(tmp_path)


def test_partial_publish_failure_removes_only_its_new_files(tool, dream_capture, tmp_path, monkeypatch):
    original, count = tool.os.link, [0]
    def link(*args, **kwargs):
        count[0] += 1
        if count[0] == 2: raise OSError("PRIVATE_TOKEN PRIVATE_PATH")
        return original(*args, **kwargs)
    monkeypatch.setattr(tool.os, "link", link)
    output = tmp_path / "restored"
    with pytest.raises(tool.RestoreError, match="output_publish_failed") as error:
        tool.restore_capture(dream_capture.schema, dream_capture.directory, output, event="dream")
    assert count[0] == 2 and not output.exists() and "PRIVATE" not in str(error.value)
    no_staging(tmp_path)


def test_output_inside_source_is_rejected(tool, dream_capture):
    output = dream_capture.directory / "restored"
    before = contents(dream_capture.directory)
    with pytest.raises(tool.RestoreError, match="output_must_be_separate"):
        tool.restore_capture(dream_capture.schema, dream_capture.directory, output, event="dream")
    assert not output.exists() and contents(dream_capture.directory) == before


def test_cli_points_to_explicit_master_and_private_catalogs(tool, dream_capture, tmp_path, capsys):
    output = tmp_path / "restored with spaces"
    code = tool.main(["--archive", str(dream_capture.directory), "--event", "dream", "--output", str(output)])
    result = capsys.readouterr()
    assert code == 0 and result.err == ""
    value = json.loads(result.out)
    command = value["serve_command"]
    assert "--profile preserved" in command and "--master-dir '<matching-master-json>'" in command
    assert "--dream-catalog" in command and "--pvp-catalog" not in command
    assert "--fixtures" in command and "PRIVATE" not in result.out


def test_cli_hides_unexpected_parser_errors(tool, tmp_path, monkeypatch, capsys):
    def fail(*a): raise RuntimeError("PRIVATE_TOKEN PRIVATE_PATH")
    monkeypatch.setattr(tool.Schema, "from_descriptor_set", fail)
    assert tool.main(["--archive", str(tmp_path), "--event", "dream", "--output", str(tmp_path / "out")]) == 1
    result = capsys.readouterr()
    assert result.err == "" and json.loads(result.out) == {
        "status": "failed", "code": "local_restoration_failed"}


def test_cli_requires_explicit_event_without_echoing_invalid_argument(tool, capsys):
    assert tool.main([]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "arguments_invalid"}
    assert tool.main(["--event", "PRIVATE_INPUT_MUST_NOT_BE_ECHOED"]) == 1
    result = capsys.readouterr()
    assert result.err == "" and json.loads(result.out) == {"status": "failed", "code": "arguments_invalid"}
