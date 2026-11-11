"""The explicit media Photography gate changes one real area aggregate only."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local.gameplay import Gameplay, _Catalog
from idoly_local.media_access import (MASTER_VERSION, PHOTOGRAPHY_AREA_ID,
                                      apply_media_access, prepare_media_access)
from idoly_local.rpc import RpcCode, RpcFailure
from test_media_profile import schema, UNKNOWN


@pytest.fixture
def master(tmp_path):
    root = tmp_path / "master-json"
    root.mkdir()
    ids = ["gate-quest-a", "gate-quest-b", "gate-quest-c"]
    rows = {"Area": [
        {"id": "area-main-001", "type": 1, "order": 1, "questIds": ["earlier-quest"]},
        {"id": PHOTOGRAPHY_AREA_ID, "type": 1, "order": 2, "questIds": ids},
        {"id": "area-main-003", "type": 1, "order": 3, "questIds": ["later-quest"]},
    ], "Quest": [{"id": identity, "areaId": PHOTOGRAPHY_AREA_ID} for identity in ids]}
    for table, values in rows.items():
        (root / (table + ".json")).write_text(json.dumps(values))
    (root / "!version.txt").write_text(MASTER_VERSION)
    return root, rows


@pytest.fixture
def snapshot(schema):
    value = schema.response_type("/api.User/Get")()
    value.user.name, value.user.managerLevel, value.user.managerExp = "Media viewer", 1, 0
    value.userPublic.serverUserId, value.userPublic.publicUserId = "media-server", "media-public"
    value.balance.freeBalance, value.balance.paidBalance = 15, 3
    value.points.add(pointType=1, amount=44)
    value.items.add(itemId="keep-item", amount=7)
    value.areas.add(areaId="area-main-001", clearQuestCount=1, dailyClearCount=2, lastClearedTime=123)
    value.quests.add(questId="keep-result", lastClearedTime=999, highestScore=456,
                     highestRank=23).MergeFromString(UNKNOWN)
    value.tutorials.add(tutorialType=2, step=1)
    value.MergeFromString(UNKNOWN)
    return value


def rewrite(master, table, change):
    rows = deepcopy(master[1][table])
    change(rows)
    (master[0] / (table + ".json")).write_text(json.dumps(rows))


def test_new_gate_adds_only_target_aggregate_without_fake_results_or_other_progress(master, snapshot):
    plan = prepare_media_access(master[0])
    assert plan.area_id == PHOTOGRAPHY_AREA_ID and plan.required_clear_count == 3
    before = snapshot.SerializeToString()
    ordinary = type(snapshot).FromString(before)
    expected = type(snapshot).FromString(before)
    expected.areas.add(areaId=PHOTOGRAPHY_AREA_ID, clearQuestCount=3)
    assert apply_media_access(snapshot, plan)
    assert snapshot.SerializeToString() == expected.SerializeToString()
    added = snapshot.areas[-1]
    assert {field.name for field, _ in added.ListFields()} == {"areaId", "clearQuestCount"}
    assert not added.lastClearedTime and not added.dailyClearCount
    assert len(snapshot.quests) == 1 and snapshot.quests[0] == ordinary.quests[0]
    assert ordinary.SerializeToString() == before
    after = snapshot.SerializeToString()
    assert not apply_media_access(snapshot, plan) and snapshot.SerializeToString() == after


def test_existing_target_preserves_unknown_daily_and_time_fields(master, snapshot):
    target = snapshot.areas.add(areaId=PHOTOGRAPHY_AREA_ID, clearQuestCount=1,
                                dailyClearCount=8, lastClearedTime=12345)
    target.MergeFromString(UNKNOWN)
    expected = type(snapshot)()
    expected.CopyFrom(snapshot)
    expected.areas[-1].clearQuestCount = 3
    assert apply_media_access(snapshot, prepare_media_access(master[0]))
    assert snapshot.SerializeToString() == expected.SerializeToString()
    assert UNKNOWN in snapshot.areas[-1].SerializeToString()


@pytest.mark.parametrize("count", (3, 7))
def test_complete_or_more_advanced_existing_aggregate_is_not_lowered_or_rewritten(master, snapshot, count):
    snapshot.areas.add(areaId=PHOTOGRAPHY_AREA_ID, clearQuestCount=count).MergeFromString(UNKNOWN)
    before = snapshot.SerializeToString()
    assert not apply_media_access(snapshot, prepare_media_access(master[0]))
    assert snapshot.SerializeToString() == before


def test_quest_count_is_derived_from_valid_master_references_instead_of_hardcoded(master, snapshot):
    rewrite(master, "Area", lambda rows: rows[1]["questIds"].pop())
    plan = prepare_media_access(master[0])
    assert plan.required_clear_count == 2
    assert apply_media_access(snapshot, plan)
    assert snapshot.areas[-1].clearQuestCount == 2


def test_home_frontier_side_effect_is_explicit_for_media_lesson_integration(master, snapshot):
    game = SimpleNamespace(catalog=_Catalog(master[0]))
    assert Gameplay._current_area(game, snapshot) == "area-main-002"
    apply_media_access(snapshot, prepare_media_access(master[0]))
    assert Gameplay._current_area(game, snapshot) == "area-main-003"


@pytest.mark.parametrize("kind", ("no-user", "duplicate-target", "duplicate-other", "empty-area", "negative"))
def test_malformed_snapshot_is_not_partly_repaired(master, snapshot, kind):
    if kind == "no-user":
        snapshot.ClearField("user")
    elif kind == "duplicate-target":
        snapshot.areas.add(areaId=PHOTOGRAPHY_AREA_ID)
        snapshot.areas.add(areaId=PHOTOGRAPHY_AREA_ID)
    elif kind == "duplicate-other":
        snapshot.areas.add().CopyFrom(snapshot.areas[0])
    elif kind == "empty-area":
        snapshot.areas.add()
    else:
        snapshot.areas.add(areaId=PHOTOGRAPHY_AREA_ID, clearQuestCount=-1)
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure) as denied:
        apply_media_access(snapshot, prepare_media_access(master[0]))
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("kind", ("wrong-version", "missing-target", "wrong-type", "empty-quests",
                                  "duplicate-quest", "missing-quest", "foreign-quest"))
def test_invalid_master_cannot_grant_an_invented_or_unverified_area(master, kind):
    if kind == "wrong-version":
        (master[0] / "!version.txt").write_text("different-master")
    elif kind == "missing-target":
        rewrite(master, "Area", lambda rows: rows.pop(1))
    elif kind == "wrong-type":
        rewrite(master, "Area", lambda rows: rows[1].update(type=2))
    elif kind == "empty-quests":
        rewrite(master, "Area", lambda rows: rows[1].update(questIds=[]))
    elif kind == "duplicate-quest":
        rewrite(master, "Area", lambda rows: rows[1]["questIds"].append("gate-quest-a"))
    elif kind == "missing-quest":
        rewrite(master, "Quest", lambda rows: rows.pop())
    else:
        rewrite(master, "Quest", lambda rows: rows[0].update(areaId="another-private-area"))
    with pytest.raises(RpcFailure) as denied:
        prepare_media_access(master[0])
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert "another-private-area" not in denied.value.details


def test_actual_public_master_has_the_exact_three_photography_prerequisite_quests():
    root = Path(__file__).resolve().parents[1] / "data/master-json"
    if not (root / "Area.json").is_file() or not (root / "Quest.json").is_file():
        pytest.skip("Actual public decoded masters are not installed")
    plan = prepare_media_access(root)
    assert plan.quest_ids == ("qt-main-1-002-01", "qt-main-1-002-02", "qt-main-1-002-03")
    assert plan.required_clear_count == 3
