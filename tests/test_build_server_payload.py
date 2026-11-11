"""Public Mission master inclusion preserves its audited data, not eligibility."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from test_octo_runtime import write_archive


spec = importlib.util.spec_from_file_location("payload_builder", Path(__file__).resolve().parents[1] / "tools/build_server_payload.py")
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


@pytest.fixture
def missions():
    evidence = json.loads((Path(__file__).parent / "fixtures/official-card-level-mission.v1.json").read_text())
    master = evidence["mission_master"]
    values = [{"id": f"other-mission-{index}"} for index in range(master["rows"] - 1)]
    values.insert(7, deepcopy(master["card_level_achievement"]))
    return master, values


def test_payload_includes_canonical_tables_and_media_scene_definitions():
    assert len(payload.TABLES) == len(set(payload.TABLES)) == 45
    assert payload.TABLES[39] == "Mission"
    assert payload.TABLES[40:] == ("StoryPart", "PhotoActivity", "PhotoQuestMusic", "PhotoQuestStage", "PhotoExpression")
    assert "Condition" not in payload.TABLES


def test_pinned_external_evidence_matches_payload_contract_without_mutating_rows(missions):
    master, rows = missions
    before = deepcopy(rows)
    payload.validate_mission_master(master["master_version"], master["pack_sha256"], rows)
    assert rows == before


@pytest.mark.parametrize("changed", ("version", "pack", "count", "duplicate", "empty-id", "missing",
    "category", "type", "condition", "targets", "threshold", "reward", "tier-order"))
def test_mission_payload_rejects_wrong_data_or_card_level_contract(missions, changed):
    master, rows = missions
    version, pack = master["master_version"], master["pack_sha256"]
    row = next(row for row in rows if row["id"] == payload.CARD_LEVEL_MISSION_ID)
    if changed == "version":
        version = "0" * 64
    elif changed == "pack":
        pack = "0" * 64
    elif changed == "count":
        rows.pop()
    elif changed == "duplicate":
        rows[-1]["id"] = rows[0]["id"]
    elif changed == "empty-id":
        rows[-1]["id"] = ""
    elif changed == "missing":
        row["id"] = "unrecognized-card-level-mission"
    elif changed == "category":
        row["categoryType"] = 1
    elif changed == "type":
        row["missionType"] = 14
    elif changed == "condition":
        row["viewConditionId"] = "unimplemented-condition"
    elif changed == "targets":
        row["targetIds"] = ["specific-card"]
    elif changed == "threshold":
        row["progresses"][0]["threshold"] = "6"
    elif changed == "reward":
        row["progresses"][0]["rewardSetId"] = "rd_auto;stone;;500"
    elif changed == "tier-order":
        row["progresses"].reverse()
    with pytest.raises(ValueError):
        payload.validate_mission_master(version, pack, rows)


def test_octo_payload_selects_exact_public_pair_without_reading_private_neighbors(tmp_path, monkeypatch):
    public = tmp_path / 'catalog'
    write_archive(public)
    private = [public/'firebase-user.archive', public/'state.db', public/'private/user.pb']
    for path in private:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'private-synthetic-account-data-never-read')
    allowed = {public/'settings.json', public/'manifest.pb'}
    seen = set()
    def guard(original):
        def checked(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = Path(os.fsdecode(path)).absolute()
                if candidate.is_relative_to(public):
                    assert candidate in allowed, 'Payload builder tried to read a private neighboring file'
                    seen.add(candidate)
            return original(path, *args, **kwargs)
        return checked
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', guard(builtins.open))
        patch.setattr(io, 'open', guard(io.open))
        patch.setattr(os, 'open', guard(os.open))
        files, summary = payload.octo_public_files(public)
    assert {source for source, _ in files} == allowed
    assert {target for _, target in files} == {'data/public-octo/settings.json', 'data/public-octo/manifest.pb'}
    assert seen == allowed
    assert summary['revision'] == 1087 and summary['objects'] == 2
    archive = tmp_path/'public-only.zip'
    with ZipFile(archive, 'w') as output:
        for source, target in files:
            output.write(source, target)
    with ZipFile(archive) as output:
        assert set(output.namelist()) == {'data/public-octo/settings.json', 'data/public-octo/manifest.pb'}
        assert all(b'private-synthetic-account' not in output.read(name) for name in output.namelist())


@pytest.mark.parametrize('changed', ['missing', 'partial', 'settings-version', 'digest', 'protobuf', 'revision'])
def test_octo_payload_rejects_invalid_explicit_catalog_without_outputs_or_input_changes(tmp_path, changed):
    public = tmp_path/'catalog'
    settings, _ = write_archive(public)
    if changed == 'missing':
        for file in public.iterdir(): file.unlink()
    elif changed == 'partial':
        (public/'manifest.pb').unlink()
    elif changed == 'settings-version':
        settings['application_version'] += 1
        (public/'settings.json').write_text(json.dumps(settings))
    elif changed == 'digest':
        (public/'manifest.pb').write_bytes(b'different original bytes')
    elif changed == 'protobuf':
        malformed = b'\xff'
        (public/'manifest.pb').write_bytes(malformed)
        settings['manifest_sha256'] = hashlib.sha256(malformed).hexdigest()
        (public/'settings.json').write_text(json.dumps(settings))
    else:
        write_archive(public, revision=1088)
    before = {p.name: p.read_bytes() for p in public.iterdir()}
    with pytest.raises(ValueError):
        payload.octo_public_files(public)
    assert {p.name: p.read_bytes() for p in public.iterdir()} == before
    assert set(tmp_path.iterdir()) == {public}
