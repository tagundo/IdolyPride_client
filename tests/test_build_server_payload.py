"""Public Mission master inclusion preserves its audited data, not eligibility."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


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


def test_payload_adds_only_mission_to_existing_canonical_table_contract():
    assert len(payload.TABLES) == len(set(payload.TABLES)) == 40
    assert payload.TABLES[-1] == "Mission"
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
