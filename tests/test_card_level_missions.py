"""Persist the original card-level achievement without rewarding/list synthesis."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import card_level_missions as mission
from idoly_local.gameplay import _Catalog, repair_starter_card_level_mission
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_tutorial_progression import (ENHANCE, USER, call, change, current, dump, game,
                                       small_schema as progression_schema)


PATH = "/api.Mission/List"
UNKNOWN = b"\x80\x4b\x7b"
EVIDENCE = Path(__file__).parent / "fixtures/official-card-level-mission.v1.json"


def test_legacy_schema_with_new_master_does_not_gain_or_require_mission_fields(tmp_path):
    source = tmp_path / "legacy.pb"
    progression_schema(source)
    legacy = Schema.from_descriptor_set(source)
    snapshot = legacy.response_type(USER)()
    assert "missions" not in snapshot.DESCRIPTOR.fields_by_name
    snapshot.user.SetInParent()
    snapshot.MergeFromString(UNKNOWN)
    raw = snapshot.SerializeToString()
    master = tmp_path / "master"
    master.mkdir()
    (master / "Mission.json").write_text(json.dumps([
        json.loads(EVIDENCE.read_text())["mission_master"]["card_level_achievement"]]))
    catalog = _Catalog(master)
    assert mission.initialize_mission(snapshot, catalog, 1234) is False
    assert mission.advance_mission(snapshot, catalog, 1234) is None
    assert snapshot.SerializeToString() == raw
    state = State(tmp_path / "legacy.sqlite")
    state.ensure_profile("old")
    state.save_snapshot("old", raw, legacy.fingerprint, starter_version=4)
    before = dump(state)
    assert not repair_starter_card_level_mission(state, legacy, "old", master)
    assert state.starter_version("old") == 4 and dump(state) == before


def small_schema(path):
    progression_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    row = file.message_type.add(name="UserMission")
    for name, number, kind in (("missionId", 1, 9), ("currentThreshold", 2, 3),
                               ("progress", 3, 3), ("statusType", 4, 5), ("lastUpdateTime", 5, 3)):
        row.field.add(name=name, number=number, label=1, type=kind)
    for name in ("UserGetResponse", "UpdatedData"):
        target = next(row for row in file.message_type if row.name == name)
        target.field.add(name="missions", number=max(f.number for f in target.field) + 1,
                         label=3, type=11, type_name=".api.UserMission")
    response = file.message_type.add(name="MissionListResponse")
    response.field.add(name="userMissions", number=1, label=3, type=11, type_name=".api.UserMission")
    response.field.add(name="commonResponse", number=9999, label=1, type=11, type_name=".api.CommonResponse")
    file.service.add(name="Mission").method.add(name="List", input_type=".api.Empty",
                                               output_type=".api.MissionListResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("mission-schema") / "schema.pb")
    source = Path(__file__).parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable; minimal contract still runs")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def mission_game(game):
    provider, state, master, rows, token = game
    rows["Mission"] = [json.loads(EVIDENCE.read_text())["mission_master"]["card_level_achievement"]]
    (master / "Mission.json").write_text(json.dumps(rows["Mission"]))
    change(game, lambda snapshot: mission.initialize_mission(snapshot, provider.catalog, 1234))
    return game


def row(game):
    return next(r for r in current(game).missions if r.missionId == mission.MISSION_ID)


def list_result(game):
    provider, state, master = game[:3]
    service = mission.CardLevelMissions(provider.schema, state, "player", master)
    return provider.schema.response_type(PATH).FromString(service.handle(PATH, b""))


def test_enhancement_matches_captured_progress_and_same_level_retry_has_no_mission_delta(mission_game):
    game = mission_game
    before = current(game)
    assert (row(game).progress, row(game).currentThreshold, row(game).statusType) == (1, 5, 1)
    response = call(game, ENHANCE, cardId="card-a", level=2)
    progress = row(game)
    assert (progress.progress, progress.currentThreshold, progress.statusType) == (2, 5, 1)
    assert progress.lastUpdateTime == current(game).cards[0].lastEnhanceTime > 1234
    assert len(response.commonResponse.updatedData.missions) == 1
    assert response.commonResponse.updatedData.missions[0] == progress
    assert before.user == current(game).user and before.points == current(game).points
    assert current(game).items[0].amount == before.items[0].amount - 40
    committed = dump(game[1])
    repeat = call(game, ENHANCE, cardId="card-a", level=2)
    assert not repeat.commonResponse.updatedData.missions
    assert dump(game[1]) == committed
    restarted = State(game[1].path)
    assert restarted.snapshot("player") == game[1].snapshot("player")
    assert restarted.authenticated(game[4], "player")


def test_progress_uses_highest_owned_level_not_support_level_or_rpc_count(mission_game):
    game = mission_game
    master = game[3]
    master["Card"].append(dict(master["Card"][0], id="card-b"))
    (game[2] / "Card.json").write_text(json.dumps(master["Card"]))
    # No Card master lookup was needed while initializing? It was; explicitly
    # replace its cached rows to model this fixture's second valid owned card.
    game[0].catalog.loaded["Card"] = master["Card"]
    def prepare(snapshot):
        snapshot.cards.add().CopyFrom(snapshot.cards[0])
        snapshot.cards[-1].cardId, snapshot.cards[-1].level = "card-b", 3
        snapshot.cards[-1].baseLevel = 1
        snapshot.user.cardSupportLevel = 99
        snapshot.missions[0].progress = 3
    change(game, prepare)
    response = call(game, ENHANCE, cardId="card-a", level=2)
    assert row(game).progress == 3
    assert row(game).lastUpdateTime == 1234
    assert not response.commonResponse.updatedData.missions


@pytest.mark.parametrize("status", (2, 3, 4))
def test_imported_receipt_and_advanced_threshold_survive_a_new_highwater(mission_game, status):
    game = mission_game
    master = game[3]
    master["Card"].append(dict(master["Card"][0], id="card-b"))
    game[0].catalog.loaded["Card"] = master["Card"]
    def prepare(snapshot):
        snapshot.cards[0].rarityTotalExp = 35  # A valid imported rarity, without starter normalization.
        snapshot.cards.add().CopyFrom(snapshot.cards[0])
        snapshot.cards[-1].cardId, snapshot.cards[-1].level = "card-b", 20
        saved = snapshot.missions[0]
        saved.currentThreshold, saved.progress, saved.statusType = 10, 10, status
        saved.lastUpdateTime = (1 << 62)
        saved.MergeFromString(UNKNOWN)
        snapshot.missions.add(missionId="unrelated", currentThreshold=17, progress=8, statusType=1)
    change(game, prepare)
    with game[1].connect() as db:
        db.execute("UPDATE starter_profiles SET version=0 WHERE profile='player'")
    before = current(game).missions[1].SerializeToString()
    response = call(game, ENHANCE, cardId="card-a", level=2)
    saved = row(game)
    assert (saved.currentThreshold, saved.progress, saved.statusType) == (10, 20, status)
    assert saved.lastUpdateTime == (1 << 62) and UNKNOWN in saved.SerializeToString()
    assert len(response.commonResponse.updatedData.missions) == 1
    assert current(game).missions[1].SerializeToString() == before
    assert game[1].starter_version("player") == 0


def test_imported_missing_achievement_is_never_initialized_by_enhancement(mission_game):
    game = mission_game
    def prepare(snapshot):
        snapshot.cards[0].rarityTotalExp = 35
        snapshot.ClearField("missions")
    change(game, prepare)
    with game[1].connect() as db:
        db.execute("UPDATE starter_profiles SET version=0 WHERE profile='player'")
    response = call(game, ENHANCE, cardId="card-a", level=2)
    assert not current(game).missions and not response.commonResponse.updatedData.missions


def test_same_level_starter_rarity_normalization_never_advances_mission(mission_game):
    game = mission_game
    assert current(game).cards[0].rarityTotalExp == 0
    before = dump(game[1])
    response = call(game, ENHANCE, cardId="card-a", level=1)
    assert not response.commonResponse.updatedData.missions
    assert dump(game[1]) == before


def test_recorded_historical_highwater_never_decreases_to_current_owned_levels(mission_game):
    game = mission_game
    def prepare(snapshot):
        saved = snapshot.missions[0]
        saved.progress, saved.currentThreshold = 42, 50
    change(game, prepare)
    response = call(game, ENHANCE, cardId="card-a", level=2)
    assert (row(game).progress, row(game).currentThreshold, row(game).lastUpdateTime) == (42, 50, 1234)
    assert not response.commonResponse.updatedData.missions


def test_local_boundary_policy_marks_ready_without_advancing_tier_or_granting(mission_game):
    game = mission_game
    # Exercise the boundary helper directly: card enhancement's own parameter,
    # cap and release tests separately govern which target levels are reachable.
    game[0].catalog.loaded["CardLevel"].append({"level": 5})
    before_points = [p.SerializeToString() for p in current(game).points]
    def update(snapshot):
        snapshot.cards[0].level = 5
        changed = mission.advance_mission(snapshot, game[0].catalog, 5678)
        assert changed is not None
    change(game, update)
    assert (row(game).progress, row(game).currentThreshold, row(game).statusType) == (5, 5, 2)
    assert [p.SerializeToString() for p in current(game).points] == before_points


@pytest.mark.parametrize("problem", ("duplicate-saved", "unknown-threshold", "negative-progress",
    "bad-status", "receipt-before-threshold", "duplicate-card", "unknown-card", "invalid-card-level",
    "wrong-type", "conditional", "duplicate-threshold", "bad-inline", "empty-master"))
def test_malformed_mission_or_ownership_rolls_back_card_item_and_mission(mission_game, problem):
    game = mission_game
    def bad(snapshot):
        saved = snapshot.missions[0]
        if problem == "duplicate-saved": snapshot.missions.add().CopyFrom(saved)
        elif problem == "unknown-threshold": saved.currentThreshold = 6
        elif problem == "negative-progress": saved.progress = -1
        elif problem == "bad-status": saved.statusType = 0
        elif problem == "receipt-before-threshold": saved.statusType = 4
        elif problem == "duplicate-card": snapshot.cards.add().CopyFrom(snapshot.cards[0])
        elif problem in ("unknown-card", "invalid-card-level"):
            added = snapshot.cards.add(); added.CopyFrom(snapshot.cards[0])
            added.cardId, added.level = "unknown" if problem == "unknown-card" else "card-b", 999
    change(game, bad)
    if problem == "invalid-card-level":
        game[0].catalog.loaded["Card"].append(dict(game[3]["Card"][0], id="card-b"))
    masters = game[0].catalog.loaded["Mission"]
    if problem == "wrong-type": masters[0]["missionType"] = 12
    elif problem == "conditional": masters[0]["viewConditionId"] = "unsupported"
    elif problem == "duplicate-threshold": masters[0]["progresses"].append(dict(masters[0]["progresses"][0]))
    elif problem == "bad-inline": masters[0]["progresses"][0]["rewardSetId"] = "missing-reward"
    elif problem == "empty-master": game[0].catalog.loaded["Mission"] = []
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, ENHANCE, cardId="card-a", level=2)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_concurrent_same_enhancement_spends_once_and_emits_one_mission_delta(mission_game):
    game = mission_game
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: call(game, ENHANCE, cardId="card-a", level=2), range(2)))
    assert sorted(len(r.commonResponse.updatedData.missions) for r in replies) == [0, 1]
    assert current(game).cards[0].level == 2 and row(game).progress == 2
    assert current(game).items[0].amount == 60


def test_old_payload_without_mission_keeps_enhancement_working(game):
    response = call(game, ENHANCE, cardId="card-a", level=2)
    assert current(game).cards[0].level == 2
    assert not current(game).missions and not response.commonResponse.updatedData.missions
    assert game[1].starter_version("player") == 4
    with pytest.raises(RpcFailure) as error:
        list_result(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION


def test_list_is_a_readonly_projection_of_real_supported_state_not_master_catalog(mission_game):
    game = mission_game
    change(game, lambda snapshot: snapshot.missions.add(missionId="unimplemented", progress=400, statusType=1))
    before = dump(game[1])
    response = list_result(game)
    assert len(response.userMissions) == 1 and response.userMissions[0] == row(game)
    assert response.HasField("commonResponse") and not response.commonResponse.ListFields()
    assert dump(game[1]) == before
    assert list_result(game).SerializeToString() == response.SerializeToString()


@pytest.mark.parametrize("status", (1, 2, 3, 4))
def test_list_preserves_each_valid_status_and_its_exact_current_threshold(mission_game, status):
    game = mission_game
    def prepare(snapshot):
        saved = snapshot.missions[0]
        saved.currentThreshold, saved.progress, saved.statusType = 10, 10, status
        saved.MergeFromString(UNKNOWN)
    change(game, prepare)
    before = dump(game[1])
    listed = list_result(game).userMissions[0]
    assert (listed.currentThreshold, listed.progress, listed.statusType) == (10, 10, status)
    assert UNKNOWN in listed.SerializeToString()
    assert dump(game[1]) == before


@pytest.mark.parametrize("problem", ("duplicate-row", "unknown-threshold", "missing-snapshot", "wrong-schema", "malformed"))
def test_list_rejects_invalid_state_without_initialization(mission_game, problem):
    game = mission_game
    if problem == "duplicate-row": change(game, lambda snapshot: snapshot.missions.add().CopyFrom(snapshot.missions[0]))
    elif problem == "unknown-threshold": change(game, lambda snapshot: setattr(snapshot.missions[0], "currentThreshold", 0))
    else:
        with game[1].connect() as db:
            if problem == "missing-snapshot": db.execute("DELETE FROM snapshots")
            elif problem == "wrong-schema": db.execute("UPDATE snapshots SET schema_sha256='other'")
            else: db.execute("UPDATE snapshots SET response=?", (b"\x0a\x80",))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: list_result(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_list_malformed_request_is_rejected_and_claim_route_is_not_handled(mission_game):
    game = mission_game
    service = mission.CardLevelMissions(game[0].schema, game[1], "player", game[2])
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: service.handle(PATH, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert service.handle("/api.Mission/Receive", b"") is None
    assert dump(game[1]) == before
