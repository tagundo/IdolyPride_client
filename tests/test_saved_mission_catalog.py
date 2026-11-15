"""Persisted mission menus use actual memberships and never manufacture activity."""
import json
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool

import grpc
import pytest

from idoly_local import card_level_missions as mission
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_card_level_missions import (PATH, UNKNOWN, USER, change, current, dump, game,
                                     list_result, mission_game, schema)
from test_story_application import connected


def definition(identity="saved-daily", *, category=1, reward="rd_auto;stone;;10", **extra):
    return {"id": identity, "categoryType": category, "missionType": 1,
            "progresses": [{"threshold": "3", "rewardSetId": reward},
                           {"threshold": "8", "rewardSetId": "rd_auto;stone;;20"}],
            **extra}


def write_master(game, rows, rewards=None):
    (game[2] / "Mission.json").write_text(json.dumps(rows))
    if rewards is not None:
        (game[2] / "Reward.json").write_text(json.dumps(rewards))


def import_missions(game, rows):
    snapshot = current(game)
    snapshot.ClearField("missions")
    for index, values in enumerate(rows):
        saved = snapshot.missions.add(**values)
        saved.lastUpdateTime = 1234 + index
        saved.MergeFromString(UNKNOWN)
    snapshot.MergeFromString(UNKNOWN)
    game[1].save_snapshot("player", snapshot.SerializeToString(), game[0].schema.fingerprint)
    return current(game)


@pytest.fixture
def saved_catalog(mission_game):
    game = mission_game
    definitions = [
        definition("saved-daily", category=1),
        definition("saved-weekly", category=2),
        definition("saved-normal", category=3),
        definition("saved-conditional", category=3, viewConditionId="existing-active-condition"),
        definition("saved-photo", category=6),
        definition("saved-event", category=3, eventMissionId="actual-saved-event",
                   viewConditionId="event-view-condition"),
        definition("saved-company", category=3, companyEnjoyCharacterId="saved-company-character"),
    ]
    write_master(game, definitions)
    rows = [{"missionId": master["id"], "currentThreshold": 3,
             "progress": 1 if index == 0 else 5, "statusType": (index % 4) + 1}
            for index, master in enumerate(definitions)]
    rows.append({"missionId": "historic-unavailable", "currentThreshold": 99,
                 "progress": 101, "statusType": 4})
    import_missions(game, rows)
    return game


def test_saved_ordinary_tabs_are_projected_and_scoped_membership_is_kept_in_user(saved_catalog):
    game = saved_catalog
    saved = current(game)
    assert not game[1].authenticated(game[4], "player")  # Explicit import invalidates the old session.
    token, identity = game[1].login("player")
    before = dump(game[1])
    assert all(row.missionId != mission.MISSION_ID for row in saved.missions)
    response = list_result(game)
    assert list(response.userMissions) == list(saved.missions[:4])
    assert all(UNKNOWN in row.SerializeToString() for row in response.userMissions)
    assert response.HasField("commonResponse") and not response.commonResponse.ListFields()
    assert game[1].starter_version("player") == 0
    assert dump(game[1]) == before
    assert current(game).missions[-1].missionId == "historic-unavailable"
    assert game[1].authenticated(token, "player") and game[1].profile("player") == identity


def test_repeated_reads_restart_and_account_boundaries_preserve_exact_state(saved_catalog):
    game = saved_catalog
    expected = list_result(game).SerializeToString()
    snapshot = game[1].snapshot("player")
    before = dump(game[1])
    for _ in range(3):
        assert list_result(game).SerializeToString() == expected
        assert game[1].snapshot("player") == snapshot
    restarted = State(game[1].path)
    service = mission.CardLevelMissions(game[0].schema, restarted, "player", game[2])
    assert service.handle(PATH, b"") == expected and dump(restarted) == before
    other = current(game)
    other.ClearField("missions")
    other.missions.add(missionId="saved-weekly", currentThreshold=8, progress=12,
                       statusType=4, lastUpdateTime=100000)
    restarted.ensure_profile("other")
    restarted.save_snapshot("other", other.SerializeToString(), game[0].schema.fingerprint)
    independent = mission.CardLevelMissions(game[0].schema, restarted, "other", game[2])
    listed = game[0].schema.response_type(PATH).FromString(independent.handle(PATH, b""))
    assert len(listed.userMissions) == 1 and listed.userMissions[0] == other.missions[0]
    assert service.handle(PATH, b"") == expected


@pytest.mark.parametrize("status", (1, 2, 3, 4))
def test_advanced_tier_and_each_status_are_returned_without_claim_or_reset(saved_catalog, status):
    game = saved_catalog
    change(game, lambda snapshot: (
        setattr(snapshot.missions[0], "currentThreshold", 8),
        setattr(snapshot.missions[0], "progress", 17),
        setattr(snapshot.missions[0], "statusType", status),
        setattr(snapshot.missions[0], "lastUpdateTime", 1 << 62)))
    before = dump(game[1])
    row = list_result(game).userMissions[0]
    assert (row.currentThreshold, row.progress, row.statusType, row.lastUpdateTime) == (8, 17, status, 1 << 62)
    assert dump(game[1]) == before


@pytest.mark.parametrize("status", (2, 3, 4))
def test_non_card_mission_claim_status_is_preserved_without_guessing_eligibility(saved_catalog, status):
    game = saved_catalog
    # A display projection is not a claim validator or a recurring-period reset.
    # Preserve the server/imported status even when its progress alone cannot
    # explain eligibility; only the established card-level policy is stricter.
    change(game, lambda snapshot: (
        setattr(snapshot.missions[0], "progress", 1),
        setattr(snapshot.missions[0], "statusType", status)))
    before = dump(game[1])
    saved = current(game).missions[0]
    assert list_result(game).userMissions[0] == saved
    assert dump(game[1]) == before


def test_named_master_reward_resolves_without_granting_anything(mission_game):
    game = mission_game
    write_master(game, [definition(reward="real-saved-reward")],
                 [{"id": "real-saved-reward",
                   "resources": [{"resourceType": 15, "resourceId": "", "amount": 25}]}])
    import_missions(game, [{"missionId": "saved-daily", "currentThreshold": 3,
                           "progress": 5, "statusType": 2}])
    before = dump(game[1])
    assert list_result(game).userMissions[0] == current(game).missions[0]
    assert dump(game[1]) == before


def test_original_client_resource_enum_supports_inline_item_display(mission_game):
    game = mission_game
    enums = [enum for file in game[0].schema.files for enum in file.enum_types_by_name.values()
             if enum.name == "ResourceType"]
    types = mission._resource_types(game[0].schema)
    if not enums:
        assert types == {"stone": 15}
        pytest.skip("Legacy minimal schema intentionally has no ResourceType enum")
    assert len(enums) == 1
    assert types["item"] == 1 and types["stone"] == 15
    assert "resource_type_item" not in types and "resource_type_stone" not in types
    write_master(game, [definition(reward="rd_auto;item;item-card_enhance;10")])
    import_missions(game, [{"missionId": "saved-daily", "currentThreshold": 3,
                           "progress": 5, "statusType": 2}])
    before = dump(game[1])
    assert list_result(game).userMissions[0] == current(game).missions[0]
    assert dump(game[1]) == before


@pytest.mark.parametrize("prefix", ("", "ResourceType_"))
def test_resource_display_keys_match_native_member_names_for_bare_and_recovered_enum(prefix):
    file = descriptor_pb2.FileDescriptorProto(name="resource-display.proto", package="display")
    enum = file.enum_type.add(name="ResourceType")
    for name, number in (("Unknown", 0), ("Item", 1), ("Gold", 8), ("ManagerExp", 14), ("Stone", 15)):
        enum.value.add(name=prefix + name, number=number)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    schema = SimpleNamespace(files=[pool.FindFileByName(file.name)])
    assert mission._resource_types(schema) == {
        "item": 1, "gold": 8, "manager_exp": 14, "stone": 15}


def test_resource_display_key_normalization_rejects_ambiguous_enum_aliases():
    file = descriptor_pb2.FileDescriptorProto(name="ambiguous-resource.proto", package="display")
    enum = file.enum_type.add(name="ResourceType")
    enum.value.add(name="ResourceType_Item", number=1)
    enum.value.add(name="Item", number=2)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    schema = SimpleNamespace(files=[pool.FindFileByName(file.name)])
    with pytest.raises(RpcFailure) as failure:
        mission._resource_types(schema)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION


@pytest.mark.parametrize("problem", (
    "duplicate-saved", "empty-saved-id", "bad-status", "negative-progress", "negative-time",
    "unknown-threshold", "missing-thresholds", "nonobject-threshold",
    "duplicate-threshold", "noncanonical-threshold", "zero-threshold", "empty-reward",
    "malformed-inline", "unknown-inline-type", "noninteger-amount", "overflow-amount",
    "missing-named-reward", "empty-reward-resources", "unknown-named-resource",
))
def test_invalid_known_row_never_leaks_a_partial_catalog_or_changes_save(saved_catalog, problem):
    game = saved_catalog
    rows = json.loads((game[2] / "Mission.json").read_text())
    if problem in {"duplicate-saved", "empty-saved-id", "bad-status", "negative-progress",
                   "negative-time", "unknown-threshold"}:
        def corrupt(snapshot):
            row = snapshot.missions[1]
            if problem == "duplicate-saved": snapshot.missions.add().CopyFrom(row)
            elif problem == "empty-saved-id": row.missionId = ""
            elif problem == "bad-status": row.statusType = 0
            elif problem == "negative-progress": row.progress = -1
            elif problem == "negative-time": row.lastUpdateTime = -1
            else: row.currentThreshold = 7
        change(game, corrupt)
    elif problem == "missing-thresholds": rows[1]["progresses"] = []
    elif problem == "nonobject-threshold": rows[1]["progresses"] = [True]
    elif problem == "duplicate-threshold": rows[1]["progresses"].append(dict(rows[1]["progresses"][0]))
    elif problem == "noncanonical-threshold": rows[1]["progresses"][0]["threshold"] = "03"
    elif problem == "zero-threshold": rows[1]["progresses"][0]["threshold"] = 0
    else:
        values = {"empty-reward": "", "malformed-inline": "rd_auto;stone;;10;extra",
                  "unknown-inline-type": "rd_auto;imaginary;;10",
                  "noninteger-amount": "rd_auto;stone;;no",
                  "overflow-amount": "rd_auto;stone;;2147483648"}
        rows[1]["progresses"][0]["rewardSetId"] = values.get(problem, "named")
    resources = [] if problem == "empty-reward-resources" else [
        {"resourceType": 999999 if problem == "unknown-named-resource" else 15, "amount": 1}]
    write_master(game, rows, [] if problem == "missing-named-reward" else [{"id": "named", "resources": resources}])
    before = dump(game[1])
    with pytest.raises(RpcFailure) as failure:
        list_result(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


@pytest.mark.parametrize("kind", ("empty", "photo", "event", "company", "company-enjoy", "company-trust"))
def test_empty_ordinary_tab_is_a_real_read_without_repurposing_scoped_missions(mission_game, kind):
    game = mission_game
    master = definition()
    if kind == "photo": master["categoryType"] = 6
    elif kind == "event": master["eventMissionId"] = "scoped-event"
    elif kind == "company": master["companyEnjoyCharacterId"] = "scoped-character"
    elif kind == "company-enjoy": master["companyEnjoyCharacterMissionCategoryType"] = 1
    elif kind == "company-trust": master["companyTrustMissionCategoryType"] = 1
    write_master(game, [master])
    values = [] if kind == "empty" else [
        {"missionId": master["id"], "currentThreshold": 3, "progress": 5, "statusType": 2}]
    import_missions(game, values)
    before = dump(game[1])
    response = list_result(game)
    assert not response.userMissions and response.HasField("commonResponse")
    assert dump(game[1]) == before


def test_unknown_historical_only_rows_are_preserved_without_fabricating_activity(mission_game):
    game = mission_game
    import_missions(game, [{"missionId": "retired-mission", "currentThreshold": 3,
                           "progress": 5, "statusType": 4}])
    before = dump(game[1])
    with pytest.raises(RpcFailure) as failure:
        list_result(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_encrypted_read_lists_saved_categories_and_user_snapshot_keeps_historical_rows(saved_catalog, tmp_path):
    game = saved_catalog
    token, _ = game[1].login("player")
    before = dump(game[1])
    with connected(game, tmp_path / "fixtures", token=token) as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(PATH, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        listed = game[0].schema.response_type(PATH).FromString(invoke(PATH))
        saved = game[0].schema.response_type(USER).FromString(invoke(USER))
        assert list(listed.userMissions) == list(saved.missions[:4])
        assert saved.missions[-1].missionId == "historic-unavailable"
        assert dump(game[1]) == before
