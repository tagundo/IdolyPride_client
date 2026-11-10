"""Atomic local reward deltas and early enhancement, without captured accounts."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.internal.encoder import _VarintBytes
import pytest

from idoly_local import tutorial_progression as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


LESSON = "/api.Tutorial/ReceiveLessonReward"
ENHANCE = "/api.Card/Enhance"
USER = "/api.User/Get"


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    next(row for row in file.message_type if row.name == "Card").name = "OwnedCard"
    for row in file.message_type:
        for field in row.field:
            if field.type_name == ".api.Card":
                field.type_name = ".api.OwnedCard"

    def extend(name, fields):
        message = next(row for row in file.message_type if row.name == name)
        for field_name, kind in fields:
            message.field.add(name=field_name, number=len(message.field) + 1, label=1, type=kind)

    extend("Manager", (("managerExp", 3), ("cardSupportLevel", 5)))
    extend("TotalCount", (("pointGoldAmount", 3),))

    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind

    message("Point", [("pointType", 5, False), ("amount", 3, False)])
    for name in ("UserGetResponse", "UpdatedData"):
        target = next(row for row in file.message_type if row.name == name)
        target.field.add(name="points", number=len(target.field) + 1, label=3, type=11, type_name=".api.Point")
    message("Reward", [("resourceType", 5, False), ("resourceId", 9, False), ("amount", 3, False)])
    message("LessonResponse", [("rewards", "Reward", True), ("commonResponse", "CommonResponse", False)])
    message("EnhanceRequest", [("cardId", 9, False), ("level", 5, False)])
    next(row for row in file.service if row.name == "Tutorial").method.add(
        name="ReceiveLessonReward", input_type=".api.Empty", output_type=".api.LessonResponse")
    file.service.add(name="Card").method.add(name="Enhance", input_type=".api.EnhanceRequest", output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("progression-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    rows = {
        "Setting": [{"cardDefaultMental": 100, "cardDefaultTechnique": 100,
            "tutorialActivityLessonPromoteMinutes": 10, "tutorialActivityLessonRewardGoldPerMinute": 100,
            "tutorialActivityLessonRewardManagerExpPerMinute": 5,
            "tutorialActivityLessonRewardCardEnhanceItemPerMinute": 100,
            "goldLimit": "99999999999", "itemLimit": "99999999999"}],
        "ManagerLevel": [{"level": 1, "requiredExp": "0", "maxCardLevel": 10},
                         {"level": 2, "requiredExp": "50", "maxCardLevel": 12},
                         {"level": 3, "requiredExp": "115", "maxCardLevel": 14}],
        "Item": [{"id": "item-card_enhance", "type": 1, "value": 1}],
        "Consumption": [{"id": "consumption_1", "resources": [{"resourceType": 1,
            "resourceIds": ["item-card_enhance"], "amount": 1, "subResourceIds": []}]}],
        "CardLevel": [{"level": 1, "requiredExp": "0"}, {"level": 2, "requiredExp": "40"},
                      {"level": 3, "requiredExp": "100"}, {"level": 20, "requiredExp": "6000"}],
        "Card": [{"id": "card-a", "characterId": "char-a", "initialRarity": 3,
            "cardParameterId": "parameter-a", "cardLevelReleaseId": "release-a", "vocalRatioPermil": 400,
            "danceRatioPermil": 320, "visualRatioPermil": 280, "staminaRatioPermil": 1000,
            "skillId1": "skill-a", "skillId2": "skill-locked", "skillId3": "", "skillId4": "",
            "liveAbilityId": "", "activityAbilityId": "", "cardEvolutionLevelGroupId": ""}],
        "CardParameter": [{"id": "parameter-a", "level": 1, "value": "213", "staminaValue": "850"},
                          {"id": "parameter-a", "level": 2, "value": "300", "staminaValue": "852"},
                          {"id": "parameter-a", "level": 3, "value": "400", "staminaValue": "854"}],
        "CardRarity": [{"rarity": 3, "requiredExp": "35", "parameterBonusPermil": 1100, "levelLimit": 60}],
        "CardLevelRelease": [{"id": "release-a", "level": 1, "targets": [{"type": 1, "number": 1},
            {"type": 4, "number": 1}, {"type": 7, "number": 2}]},
            {"id": "release-a", "level": 20, "targets": [{"type": 1, "number": 2}]}],
        "Skill": [{"id": "skill-a", "levels": [{"level": 1, "requiredCardLevel": 1}]},
                  {"id": "skill-locked", "levels": [{"level": 1, "requiredCardLevel": 20}]}],
    }
    for name, value in rows.items():
        (master / (name + ".json")).write_text(json.dumps(value))
    state = State(tmp_path / "profiles.sqlite")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type(USER)()
    snapshot.user.name, snapshot.user.managerLevel = "Local manager", 1
    snapshot.user.cardSupportLevel = 7  # Unrelated metadata must survive the reward.
    snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId = identity["server_id"], identity["public_id"]
    snapshot.tutorials.add(tutorialType=1, step=100)
    snapshot.tutorials.add(tutorialType=2, step=1)
    snapshot.items.add(itemId="item-card_enhance", amount=100)
    snapshot.items.add(itemId="unrelated-item", amount=42)
    snapshot.points.add(pointType=1, amount=7)
    snapshot.totalCount.pointGoldAmount = 5
    snapshot.cards.add(cardId="card-a", level=1, baseLevel=1, rarity=3, obtainedTime=123,
        vocal=93, dance=74, visual=64, stamina=935, mental=100, technique=100,
        baseVocal=93, baseDance=74, baseVisual=64, baseStamina=935,
        skillId1="skill-a", baseSkillId1="skill-a", skillLevel1=1, baseSkillLevel1=1,
        photoEquipableCount=2, basePhotoEquipableCount=2)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    token, _ = state.login("player")
    return module.TutorialProgression(schema, state, "player", master), state, master, rows, token


def current(game):
    provider, state, *_ = game
    return provider.schema.response_type(USER).FromString(state.snapshot("player")[0])


def call(game, path, **kwargs):
    provider = game[0]
    request = provider.schema.request_type(path)(**kwargs)
    return provider.schema.response_type(path).FromString(provider.handle(path, request.SerializeToString()))


def change(game, callback):
    provider, state, *_ = game
    def update(raw):
        snapshot = provider.schema.response_type(USER).FromString(raw)
        callback(snapshot)
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, update)


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def test_lesson_adds_only_earned_deltas_and_receipt_survives_reopen(game):
    response = call(game, LESSON)
    assert [(r.resourceType, r.resourceId, r.amount) for r in response.rewards] == [
        (8, "", 1000), (14, "", 50), (1, "item-card_enhance", 1000)]
    snapshot = current(game)
    assert (snapshot.user.managerExp, snapshot.user.managerLevel, snapshot.user.cardSupportLevel) == (50, 2, 7)
    assert snapshot.items[0].amount == 1100 and snapshot.items[1].amount == 42
    assert snapshot.points[0].amount == 1007 and snapshot.totalCount.pointGoldAmount == 1005
    assert [row.step for row in snapshot.tutorials] == [110, 1]
    assert [row.itemId for row in response.commonResponse.updatedData.items] == ["item-card_enhance"]
    state = State(game[1].path)
    provider = module.TutorialProgression(game[0].schema, state, "player", game[2])
    before = dump(state)
    repeated = provider.schema.response_type(LESSON).FromString(provider.handle(LESSON, b""))
    assert not repeated.rewards and dump(state) == before
    assert state.authenticated(game[4], "player")


def test_lesson_concurrent_requests_award_once_and_retry_uses_current_totals(game):
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: call(game, LESSON), range(2)))
    assert sorted(len(response.rewards) for response in responses) == [0, 3]
    change(game, lambda snapshot: setattr(snapshot.items[0], "amount", 17))
    repeated = call(game, LESSON)
    assert not repeated.rewards
    assert repeated.commonResponse.updatedData.items[0].amount == 17
    assert current(game).points[0].amount == 1007


@pytest.mark.parametrize("step", (0, 10, 99, 101, 109))
def test_lesson_rejects_wrong_checkpoint_without_partial_writes(game, step):
    change(game, lambda snapshot: setattr(snapshot.tutorials[0], "step", step))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, LESSON)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


@pytest.mark.parametrize("mutation", ("limit", "bad-manager", "duplicate-item", "negative-gold"))
def test_lesson_validation_failure_rolls_back_every_delta(game, mutation):
    if mutation == "limit":
        game[3]["Setting"][0]["itemLimit"] = "100"
        (game[2] / "Setting.json").write_text(json.dumps(game[3]["Setting"]))
    elif mutation == "bad-manager":
        change(game, lambda snapshot: setattr(snapshot.user, "managerLevel", 3))
    elif mutation == "duplicate-item":
        change(game, lambda snapshot: snapshot.items.add(itemId="item-card_enhance", amount=1))
    else:
        change(game, lambda snapshot: setattr(snapshot.points[0], "amount", -1))
    before = dump(game[1])
    with pytest.raises(RpcFailure):
        call(game, LESSON)
    assert dump(game[1]) == before


def test_unknown_protobuf_fields_sessions_and_imported_identity_survive(game):
    unknown = _VarintBytes(60000 << 3) + _VarintBytes(17)
    provider, state, *_ = game
    raw, fingerprint = state.snapshot("player")
    state.save_snapshot("player", raw + unknown, fingerprint)  # Explicit import, not a starter grant.
    token, identity = state.login("player")
    call(game, LESSON)
    assert unknown in state.snapshot("player")[0]
    assert state.authenticated(token, "player")
    assert state.profile("player") == identity and state.starter_version("player") == 0


def test_enhancement_charges_exact_experience_once_and_preserves_ownership(game):
    call(game, LESSON)
    change(game, lambda snapshot: setattr(snapshot.tutorials[0], "step", 120))
    response = call(game, ENHANCE, cardId="card-a", level=2)
    card = response.commonResponse.updatedData.cards[0]
    assert (card.level, card.baseLevel, card.totalExp, card.rarity, card.rarityTotalExp) == (2, 2, 40, 3, 35)
    assert (card.vocal, card.dance, card.visual, card.stamina) == (132, 105, 92, 937)
    assert card.obtainedTime == 123 and card.lastEnhanceTime > 0
    assert card.skillId1 == "skill-a" and not card.skillId2
    assert (card.skillLevel2, card.baseSkillLevel2, card.liveAbilityLevel, card.baseLiveAbilityLevel) == (1, 1, 1, 1)
    assert current(game).items[0].amount == 1060
    before = dump(game[1])
    repeat = call(game, ENHANCE, cardId="card-a", level=2)
    assert repeat.commonResponse.updatedData.cards[0] == card and dump(game[1]) == before
    assert game[1].authenticated(game[4], "player")


@pytest.mark.parametrize("kwargs", ({"cardId": "missing", "level": 2}, {"cardId": "card-a", "level": 0},
                                    {"cardId": "", "level": 2}))
def test_enhancement_invalid_request_leaves_database_unchanged(game, kwargs):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, ENHANCE, **kwargs)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


def test_enhancement_insufficient_material_rolls_back_card_and_timestamp(game):
    call(game, LESSON)
    change(game, lambda snapshot: setattr(snapshot.items[0], "amount", 39))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, ENHANCE, cardId="card-a", level=2)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_concurrent_enhancement_charges_once_and_keeps_unknown_card_fields(game):
    call(game, LESSON)
    unknown = _VarintBytes(60001 << 3) + _VarintBytes(19)
    def add_unknown(snapshot):
        card = snapshot.cards[0]
        card.ParseFromString(card.SerializeToString() + unknown)
    change(game, add_unknown)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: call(game, ENHANCE, cardId="card-a", level=2), range(2)))
    assert current(game).items[0].amount == 1060
    assert unknown in current(game).cards[0].SerializeToString()
    assert responses[0] == responses[1]


def test_imported_zero_rarity_experience_is_not_silently_reinterpreted(game):
    call(game, LESSON)
    state, schema = game[1], game[0].schema
    state.save_snapshot("player", state.snapshot("player")[0], schema.fingerprint)
    before = dump(state)
    with pytest.raises(RpcFailure):
        call(game, ENHANCE, cardId="card-a", level=2)
    assert dump(state) == before


def test_disabled_handler_is_lazy_and_malformed_request_is_invalid(game):
    assert module.TutorialProgression(None, None, "none").handle(LESSON, b"") is None
    assert game[0].handle("/api.Quest/Start", b"") is None
    for path in (LESSON, ENHANCE):
        with pytest.raises(RpcFailure) as error:
            game[0].handle(path, b"\x0a\x80")
        assert error.value.code == RpcCode.INVALID_ARGUMENT
