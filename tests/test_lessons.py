"""Ordinary idle lessons: real time intervals, atomic claims, no tutorial grant."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.internal.encoder import _VarintBytes
import pytest

from idoly_local import lessons as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_tutorial_progression import game as progression_game
from test_tutorial_progression import small_schema as progression_small_schema


PATH = "/api.Activity/ReceiveLessonReward"
AREA = "area-main-001"
WINDOW = 12 * 60 * 60 * 1000


def small_schema(path):
    progression_small_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    progress = next(row for row in file.message_type if row.name == "LessonProgress")
    for name in (*module._RATE_FIELDS, *module._AMOUNT_FIELDS, "dailyPromoteCount"):
        progress.field.add(name=name, number=len(progress.field) + 1, label=1, type=5)
    response = file.message_type.add(name="ActivityReceiveResponse")
    for number, name, target, repeated in ((1, "rewards", "Reward", True),
        (2, "progress", "LessonProgress", False), (3, "campaignEffects", "Empty", True),
        (4, "campaignDropRewards", "Reward", True), (5, "commonResponse", "CommonResponse", False)):
        response.field.add(name=name, number=number, label=3 if repeated else 1, type=11, type_name=".api." + target)
    file.service.add(name="Activity").method.add(name="ReceiveLessonReward", input_type=".api.Empty",
                                                 output_type=".api.ActivityReceiveResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("lesson-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(progression_game, monkeypatch):
    _, state, master, rows, token = progression_game
    rows["Setting"][0]["secondsPerActivityLessonStep"] = 10
    rows["Area"] = [{"id": AREA, "type": 1, "order": 1, "questIds": ["quest-1"]},
                    {"id": "area-main-002", "type": 1, "order": 2, "questIds": ["quest-2"]}]
    for table in ("Setting", "Area"):
        (master / (table + ".json")).write_text(json.dumps(rows[table]))
    schema = progression_game[0].schema
    def finish(raw):
        snapshot = schema.response_type("/api.User/Get").FromString(raw)
        snapshot.tutorials[0].step = 150
        snapshot.user.managerExp, snapshot.user.managerLevel = 50, 2
        snapshot.user.lastLoginTime = 1000  # Never an ordinary lesson anchor.
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", schema.fingerprint, finish)
    clock = [1800000000000]
    monkeypatch.setattr(module, "_now_ms", lambda: clock[0])
    return module.OrdinaryLessons(schema, state, "player", master), state, master, rows, token, clock


def snapshot(game):
    return game[0].schema.response_type("/api.User/Get").FromString(game[1].snapshot("player")[0])


def change(game, callback):
    provider, state, *_ = game
    def update(raw):
        current = provider.schema.response_type("/api.User/Get").FromString(raw)
        callback(current)
        return current.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, update)


def receive(game):
    return game[0].schema.response_type(PATH).FromString(game[0].handle(PATH, b""))


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def amounts(response):
    return [(row.resourceType, row.resourceId, row.amount) for row in response.rewards]


def test_first_access_starts_now_without_historical_login_backfill(game):
    provider, state, *_ = game
    original = state.snapshot("player")
    result = provider.progress(AREA)
    assert tuple(getattr(result, name) for name in module._RATE_FIELDS) == (5, 8, 3)
    assert tuple(getattr(result, name) for name in module._AMOUNT_FIELDS) == (0, 0, 0)
    assert result.lastReceiveTime == game[5][0] and result.maxRewardTime - result.lastReceiveTime == WINDOW
    assert state.snapshot("player") == original and state.lesson_progress("player") is not None
    assert not receive(game).rewards and state.authenticated(game[4], "player")


def test_tutorial_preview_is_unsaved_and_ordinary_receive_does_not_grant_fixed_reward(game):
    change(game, lambda current: setattr(current.tutorials[0], "step", 140))
    before = dump(game[1])
    preview = game[0].progress(AREA)
    assert preview.lastReceiveTime == game[5][0] and preview.rewardGoldAmount == 0
    assert game[1].lesson_progress("player") is None and dump(game[1]) == before
    with pytest.raises(RpcFailure) as error:
        receive(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before
    game[5][0] += 100000
    change(game, lambda current: setattr(current.tutorials[0], "step", 150))
    assert game[0].progress(AREA).lastReceiveTime == game[5][0]


def test_home_pending_does_not_grant_or_reset_and_claim_adds_base_only_deltas(game):
    provider, state, *_ = game
    first = provider.progress(AREA)
    before_snapshot, before_clock = state.snapshot("player"), state.lesson_progress("player")
    game[5][0] += 100001
    pending = provider.progress(AREA)
    assert (pending.rewardGoldAmount, pending.rewardManagerExpAmount, pending.rewardCardEnhanceItemAmount) == (50, 80, 30)
    assert state.snapshot("player") == before_snapshot and state.lesson_progress("player") == before_clock
    response = receive(game)
    assert amounts(response) == [(8, "", 50), (14, "", 80), (1, "item-card_enhance", 30)]
    current = snapshot(game)
    assert (current.points[0].amount, current.totalCount.pointGoldAmount, current.items[0].amount) == (57, 55, 130)
    assert (current.user.managerExp, current.user.managerLevel, current.user.cardSupportLevel) == (130, 3, 7)
    assert current.items[1].amount == 42 and current.tutorials[0].step == 150
    assert response.progress.lastReceiveTime == first.lastReceiveTime + 100000
    assert response.progress.maxRewardTime - response.progress.lastReceiveTime == WINDOW
    assert not response.campaignEffects and not response.campaignDropRewards
    assert response.progress.rewardManagerExpAmount == 0


def test_substep_remainder_is_preserved_and_immediate_retry_echoes_current_totals(game):
    first = game[0].progress(AREA)
    game[5][0] += 9999
    before = dump(game[1])
    assert not receive(game).rewards and dump(game[1]) == before
    game[5][0] += 1
    assert amounts(receive(game)) == [(8, "", 5), (14, "", 8), (1, "item-card_enhance", 3)]
    game[5][0] += 5000
    change(game, lambda current: setattr(current.items[0], "amount", 9))
    response = receive(game)
    assert not response.rewards and response.commonResponse.updatedData.items[0].amount == 9
    assert response.progress.lastReceiveTime == first.lastReceiveTime + 10000
    game[5][0] += 5000
    assert receive(game).rewards[0].amount == 5


def test_cap_discards_excess_elapsed_time_instead_of_allowing_repeated_windows(game):
    first = game[0].progress(AREA)
    game[5][0] += 5 * WINDOW + 31234
    pending = game[0].progress(AREA)
    assert (pending.rewardGoldAmount, pending.rewardManagerExpAmount, pending.rewardCardEnhanceItemAmount) == (21600, 34560, 12960)
    response = receive(game)
    assert [row.amount for row in response.rewards] == [21600, 34560, 12960]
    assert response.progress.lastReceiveTime == first.lastReceiveTime + 5 * WINDOW + 30000
    assert not receive(game).rewards
    game[5][0] += 8766
    assert receive(game).rewards[0].amount == 5


def test_clock_rollback_grants_nothing_and_never_moves_the_anchor_back(game):
    first = game[0].progress(AREA)
    stored = game[1].lesson_progress("player")
    game[5][0] -= 20000
    assert game[0].progress(AREA).rewardGoldAmount == 0
    assert not receive(game).rewards and game[1].lesson_progress("player") == stored
    game[5][0] = first.lastReceiveTime + 10000
    assert receive(game).rewards[0].amount == 5


def test_concurrent_claims_award_one_elapsed_interval_and_survive_restart(game):
    game[0].progress(AREA)
    game[5][0] += 10000
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: receive(game), range(2)))
    assert sorted(len(response.rewards) for response in responses) == [0, 3]
    assert snapshot(game).items[0].amount == 103
    reopened = State(game[1].path)
    provider = module.OrdinaryLessons(game[0].schema, reopened, "player", game[2])
    assert not provider.schema.response_type(PATH).FromString(provider.handle(PATH, b"")).rewards
    assert reopened.authenticated(game[4], "player")


@pytest.mark.parametrize("failure", ("gold-limit", "item-limit", "manager", "gold-overflow", "duplicate-item"))
def test_claim_failure_rolls_back_resources_and_clock(game, failure):
    game[0].progress(AREA)
    if failure in ("gold-limit", "item-limit"):
        key = "goldLimit" if failure == "gold-limit" else "itemLimit"
        # Cached Setting was loaded by the first Home preview.
        game[0].catalog.loaded["Setting"][0][key] = "1"
    elif failure == "manager":
        change(game, lambda current: setattr(current.user, "managerLevel", 1))
    elif failure == "gold-overflow":
        change(game, lambda current: setattr(current.totalCount, "pointGoldAmount", (1 << 63) - 1))
    else:
        change(game, lambda current: current.items.add(itemId="item-card_enhance", amount=1))
    game[5][0] += 10000
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        receive(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_unsupported_area_is_explicit_and_never_reprices_an_existing_clock(game):
    game[0].progress(AREA)
    before = dump(game[1])
    with pytest.raises(RpcFailure):
        game[0].progress("area-main-002")
    assert dump(game[1]) == before
    change(game, lambda current: current.areas.add(areaId=AREA, clearQuestCount=1))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        receive(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_unknown_snapshot_and_clock_fields_survive_preview_and_claim(game):
    game[0].progress(AREA)
    user_unknown = _VarintBytes(60000 << 3) + _VarintBytes(17)
    clock_unknown = _VarintBytes(60001 << 3) + _VarintBytes(19)
    game[1].mutate_lesson_snapshot("player", game[0].schema.fingerprint,
        lambda raw, clock: (raw + user_unknown, clock + clock_unknown))
    game[5][0] += 10000
    game[0].progress(AREA)
    receive(game)
    assert user_unknown in game[1].snapshot("player")[0]
    assert clock_unknown in game[1].lesson_progress("player")[0]
    assert game[1].authenticated(game[4], "player")


def test_existing_empty_clock_is_invalid_not_missing_and_import_starts_fresh(game):
    provider, state, *_ = game
    state.mutate_lesson_snapshot("player", provider.schema.fingerprint, lambda raw, _: (raw, b""))
    before = dump(state)
    with pytest.raises(RpcFailure):
        provider.progress(AREA)
    assert dump(state) == before and state.lesson_progress("player")[0] == b""
    state.save_snapshot("player", state.snapshot("player")[0], provider.schema.fingerprint)
    game[5][0] += WINDOW
    fresh = provider.progress(AREA)
    assert fresh.lastReceiveTime == game[5][0] and not receive(game).rewards


def test_disabled_unsupported_and_malformed_requests_are_not_fake_success(game):
    assert module.OrdinaryLessons(None, None, "none").handle(PATH, b"") is None
    assert game[0].handle("/api.Activity/PromoteLesson", b"") is None
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(PATH, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before
