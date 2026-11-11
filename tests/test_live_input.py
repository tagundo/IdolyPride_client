"""Prepared first-main inputs use owned current data and never update profiles."""
import base64
import copy
import json
from pathlib import Path
import shutil

from google.protobuf import descriptor_pb2, message_factory
from google.protobuf.json_format import MessageToDict
import pytest

from idoly_local import live_input as module
from idoly_local.card_progression import prepare_enhancement
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from test_card_progression import synthetic_fixture
from test_gameplay import synthetic_schema


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    api = descriptors.file[0]

    def message(file, name, definitions):
        row = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(definitions, 1):
            field = row.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type = 14 if kind == "ChartType" else 11
                field.type_name = "." + file.package + "." + kind

    def fields(kind, names):
        return [(name, kind, False) for name in names.split()]

    character = next(row for row in api.message_type if row.name == "Character")
    for name in ("lightFanAmount", "middleFanAmount", "heavyFanAmount"):
        character.field.add(name=name, number=len(character.field) + 1, type=5, label=1)
    message(api, "AssetRequest", fields(9, "questId buddyDeckName") + fields(5, "deckNumber")
            + [("userBuddyDeckPositions", "RequestedDeckPosition", True)])
    message(api, "CharacterAsset", fields(9, "characterId costumeId hairId"))
    message(api, "AssetResponse", [("characterAssets", "CharacterAsset", True), ("commonResponse", "CommonResponse", False)])
    api.service.add(name="Quest").method.add(name="ListAsset", input_type=".api.AssetRequest", output_type=".api.AssetResponse")
    message(api, "LiveDeckSkill", fields(5, "index skillLevel possessionType") + fields(9, "skillId"))
    message(api, "LiveDeckCard", fields(5, "index level rarity evolutionLevel")
            + fields(9, "cardId displayCharacterId displayCostumeId displayHairId")
            + fields(3, "vocal dance visual stamina mental technique") + [("skills", "LiveDeckSkill", True)])
    message(api, "LiveDeck", fields(9, "deckName") + [("cards", "LiveDeckCard", True)])
    message(api, "LiveUserInfo", fields(5, "index") + fields(9, "userId name") + fields(8, "isNpc")
            + [("userDeck", "LiveDeck", False)])
    master = descriptors.file.add(name="live-input-master.proto", package="master", syntax="proto3")
    enum = master.enum_type.add(name="ChartType")
    for n in range(4):
        enum.value.add(name="ChartType" + str(n), number=n)
    message(master, "Quest", fields(9, "id areaId stageId musicId musicChartPatternId questPressureId clearRewardId "
        "QuestAudienceAdvantageId QuestCharacterAdvantageId liveBonusGroupId viewConditionId unlockConditionId")
        + fields(5, "difficultyLevel maxCapacity mentalThreshold ticketAmount liveSkipType rewardManagerExp rewardCardExp")
        + fields(3, "clearScore"))
    message(master, "Setting", fields(3, "cardDefaultMental cardDefaultTechnique")
            + fields(5, "liveMinimumGuaranteedAudienceAmount"))
    message(master, "MusicChartPattern", fields(9, "id") + fields(5, "number position") + [("type", "ChartType", False)])
    message(master, "QuestPressure", fields(9, "id") + fields(5, "weightPermil"))
    message(master, "QuestAudienceAdvantage", fields(9, "id") + fields(5, "audienceAmount advantagePermil"))
    message(master, "ComboAdvantage", fields(9, "id") + fields(5, "comboCount advantagePermil"))
    message(master, "QuestStaminaConsumption", fields(5, "remainStaminaRatioPercent skillTargetParameterWeightPermil"))
    message(master, "SkillDetail", fields(9, "efficacyId triggerId"))
    message(master, "SkillLevel", fields(5, "level requiredCardLevel stamina probabilityPermil coolTime")
            + fields(9, "triggerId") + [("skillDetails", "SkillDetail", True)])
    message(master, "Skill", fields(9, "id") + fields(5, "categoryType") + [("levels", "SkillLevel", True)])
    message(master, "SkillEfficacy", fields(9, "id skillTargetId") + fields(5, "type"))
    message(master, "SkillTrigger", fields(9, "id") + fields(5, "type"))
    message(master, "SkillTarget", fields(9, "id") + fields(5, "type"))
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("live-input-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path, monkeypatch):
    _, master, rows, card = synthetic_fixture(tmp_path, schema)
    original = rows["Card"][0]
    rows["Card"] = [{**original, "id": "card-" + key, "characterId": "char-" + key, "type": 2} for key in "abcde"]
    rows.update({
        "Character": [{"id": "char-" + key, "characterGroupId": "group-1", "defaultLiveCostumeId": "cos-" + key,
                       "defaultCostumeId": "cos-" + key} for key in "abcde"],
        "Costume": [{"id": "cos-" + key, "characterId": "char-" + key, "defaultHairId": "hair-" + key} for key in "abcde"],
        "Hair": [{"id": "hair-" + key, "characterId": "char-" + key} for key in "abcde"],
        "Area": [{"id": module.MAIN_AREA_ID, "type": 1,
                  "questIds": [module.MAIN_QUEST_ID, "qt-main-1-001-02", "qt-main-1-001-03"]}],
        "Stage": [{"id": "stage-live-house-00-00"}],
        "Quest": [{"id": module.MAIN_QUEST_ID, "areaId": module.MAIN_AREA_ID, "musicId": "music-hsm-006",
                   "musicChartPatternId": "chart-hsm-006-002", "difficultyLevel": 1, "maxCapacity": 100,
                   "mentalThreshold": 47, "questPressureId": "pressure", "QuestAudienceAdvantageId": "audience",
                   "stageId": "stage-live-house-00-00", "clearScore": "3000", "ticketAmount": 0,
                   "liveSkipType": 2, "rewardManagerExp": 50, "rewardCardExp": 40,
                   "clearRewardId": "rd-main-quest-001-01"}],
        "Music": [{"id": identity, "comboAdvantageId": "combo"}
                  for identity in ("music-hsm-006", "music-sun-001", "music-moon-004")],
        "MusicChartPattern": [{"id": identity, "number": n, "type": 1, "position": 0}
            for identity in ("chart-hsm-006-001", "chart-hsm-006-002", "chart-sun-001-001",
                             "chart-sun-001-002", "chart-moon-004-001", "chart-moon-004-002") for n in range(1, 4)],
        "QuestPressure": [{"id": "pressure", "weightPermil": 1}],
        "QuestAudienceAdvantage": [{"id": "audience", "audienceAmount": 0, "advantagePermil": 1000}],
        "ComboAdvantage": [{"id": "combo", "comboCount": 0, "advantagePermil": 1000}],
        "QuestStaminaConsumption": [{"remainStaminaRatioPercent": 100, "skillTargetParameterWeightPermil": 1000}],
        "SkillEfficacy": [{"id": "ef-score_get-1000-chart_dependence", "type": 1, "skillTargetId": ""}],
        "SkillTrigger": [{"id": "tg-beat", "type": 1}],
        "SkillTarget": [{"id": "target-self", "type": 1}],
    })
    for suffix, song, goal, manager_exp, card_exp in (
            ("02", "sun-001", "5400", 65, 57), ("03", "moon-004", "10000", 85, 74)):
        rows["Quest"].append({**rows["Quest"][0], "id": "qt-main-1-001-" + suffix,
            "musicId": "music-" + song, "musicChartPatternId": "chart-" + song + "-002",
            "clearScore": goal, "rewardManagerExp": manager_exp, "rewardCardExp": card_exp,
            "clearRewardId": "rd-main-quest-001-" + suffix})
    rows["Setting"][0]["liveMinimumGuaranteedAudienceAmount"] = 10
    for skill in rows["Skill"]:
        skill["categoryType"] = 2
        skill["levels"][0].update(stamina=10, probabilityPermil=1000, skillDetails=[
            {"efficacyId": "ef-score_get-1000-chart_dependence", "triggerId": ""}])
    for table, data in rows.items():
        (master / (table + ".json")).write_text(json.dumps(data))
    (master / "!version.txt").write_text(module.MASTER_VERSION)
    monkeypatch.setattr(module, "SCHEMA_SHA256", schema.fingerprint)
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name, snapshot.user.managerLevel = "Local manager", 1
    snapshot.userPublic.publicUserId, snapshot.userPublic.serverUserId = "local-public-id", "distinct-server-id"
    snapshot.decks.add(number=1, name="Selected saved unit")
    for index, key in reversed(list(enumerate("abcde", 1))):
        owned = snapshot.cards.add(); owned.CopyFrom(card); owned.cardId = "card-" + key
        snapshot.characters.add(characterId="char-" + key, liveCostumeId="cos-" + key, liveHairId="hair-" + key,
                                lightFanAmount=index, middleFanAmount=index + 1, heavyFanAmount=index + 2)
        snapshot.costumes.add(costumeId="cos-" + key); snapshot.hairs.add(hairId="hair-" + key)
        snapshot.deckPositions.add(number=1, position=index, cardId="card-" + key,
                                   costumeId="cos-" + key, hairId="hair-" + key)
    snapshot.MergeFromString(b"\x80\x4b\x7b")
    return schema, master, rows, snapshot


def prepare(game, **values):
    schema, master, _, snapshot = game
    return module.prepare_main_live(schema, master, snapshot, values.get("quest_id", module.MAIN_QUEST_ID),
                                    values.get("deck_number", 1), values.get("seed", 123456))


def user(game, prepared):
    cls = message_factory.GetMessageClass(game[0].pool.FindMessageTypeByName("api.LiveUserInfo"))
    return cls.FromString(base64.b64decode(prepared["proto"]["UserInfo"][0]))


def rewrite(game, table):
    (game[1] / (table + ".json")).write_text(json.dumps(game[2][table]))


def test_projects_current_owned_slot_order_public_identity_stats_skills_fans_and_no_writes(game):
    before = game[3].SerializeToString()
    result = prepare(game)
    live = user(game, result)
    assert result["input_version"] == 1 and result["seed"] == 123456
    assert (live.index, live.userId, live.name, live.isNpc) == (1, "local-public-id", "Local manager", False)
    assert live.userId != game[3].userPublic.serverUserId and live.userDeck.deckName == "Selected saved unit"
    assert [(row.index, row.cardId) for row in live.userDeck.cards] == [(i, "card-" + key) for i, key in enumerate("abcde", 1)]
    for index, card in enumerate(live.userDeck.cards, 1):
        assert (card.vocal, card.dance, card.visual, card.stamina, card.mental, card.technique) == (93, 74, 64, 935, 100, 100)
        assert [(row.index, row.skillId, row.skillLevel, row.possessionType) for row in card.skills] == [(1, "skill-1", 1, 1)]
        assert result["cards"][index - 1]["light_fans"] == index
    assert game[3].SerializeToString() == before
    assert prepare(game) == result


@pytest.mark.parametrize('quest_id,music_id,chart_id,reference_id,goal', [
    ('qt-main-1-001-01', 'music-hsm-006', 'chart-hsm-006-002', 'chart-hsm-006-001', 3000),
    ('qt-main-1-001-02', 'music-sun-001', 'chart-sun-001-002', 'chart-sun-001-001', 5400),
    ('qt-main-1-001-03', 'music-moon-004', 'chart-moon-004-002', 'chart-moon-004-001', 10000),
])
def test_each_first_area_song_uses_its_own_explicit_reference_chart(game, quest_id, music_id, chart_id, reference_id, goal):
    before = game[3].SerializeToString()
    prepared = prepare(game, quest_id=quest_id)
    cls = message_factory.GetMessageClass(game[0].pool.FindMessageTypeByName('master.MusicChartPattern'))
    for table, expected in (('Chart', chart_id), ('ReferenceChart', reference_id)):
        assert {cls.FromString(base64.b64decode(raw)).id for raw in prepared['proto'][table]} == {expected}
    quest_cls = message_factory.GetMessageClass(game[0].pool.FindMessageTypeByName('master.Quest'))
    quest = quest_cls.FromString(base64.b64decode(prepared['proto']['Quest'][0]))
    assert (prepared['music_id'], quest.id, quest.clearScore) == (music_id, quest_id, goal)
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize('quest_id,reference_id', [
    ('qt-main-1-001-02', 'chart-sun-001-001'), ('qt-main-1-001-03', 'chart-moon-004-001'),
])
def test_missing_song_reference_never_falls_back_to_the_first_song(game, quest_id, reference_id):
    game[2]['MusicChartPattern'] = [row for row in game[2]['MusicChartPattern'] if row['id'] != reference_id]
    rewrite(game, 'MusicChartPattern')
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure):
        prepare(game, quest_id=quest_id)
    assert game[3].SerializeToString() == before


def test_current_enhanced_level_is_used_and_legacy_initial_rarity_xp_is_not_written(game):
    snapshot = game[3]
    first = snapshot.cards[0]
    enhanced = prepare_enhancement(game[0], game[1], first, 2, manager_level=1).card
    first.CopyFrom(enhanced)
    snapshot.cards[1].rarityTotalExp = 0
    before = snapshot.SerializeToString()
    live = user(game, prepare(game))
    card = next(row for row in live.userDeck.cards if row.cardId == first.cardId)
    assert (card.level, card.vocal, card.dance, card.visual, card.stamina) == (2, 132, 105, 92, 937)
    assert snapshot.SerializeToString() == before and snapshot.cards[1].rarityTotalExp == 0


@pytest.mark.parametrize("values,code", [({"quest_id": "qt-main-other"}, RpcCode.UNIMPLEMENTED),
    ({"deck_number": 0}, RpcCode.INVALID_ARGUMENT), ({"deck_number": 99}, RpcCode.INVALID_ARGUMENT),
    ({"deck_number": True}, RpcCode.INVALID_ARGUMENT), ({"seed": -1}, RpcCode.INVALID_ARGUMENT),
    ({"seed": 1 << 64}, RpcCode.INVALID_ARGUMENT), ({"seed": True}, RpcCode.INVALID_ARGUMENT)])
def test_invalid_or_unsupported_requests_fail_before_snapshot_changes(game, values, code):
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as error:
        prepare(game, **values)
    assert error.value.code == code and game[3].SerializeToString() == before


@pytest.mark.parametrize("field,value", [("supported", True), ("rank", 1), ("evolutionLevel", 1),
    ("skillLevel1", 2), ("vocal", 999999), ("skillId2", "skill-2")])
def test_advanced_or_inconsistent_cards_are_explicitly_rejected(game, field, value):
    setattr(game[3].cards[0], field, value)
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure):
        prepare(game)
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("field", ("photoIds", "part1AccessoryId", "part2AccessoryId"))
def test_equipment_is_not_silently_ignored(game, field):
    position = game[3].deckPositions[0]
    if field == "photoIds":
        position.photoIds.append("photo")
    else:
        setattr(position, field, "accessory")
    with pytest.raises(RpcFailure) as error:
        prepare(game)
    assert error.value.code == RpcCode.UNIMPLEMENTED


@pytest.mark.parametrize("damage", ("missing-card", "duplicate-slot", "wrong-owner", "missing-public", "negative-fans"))
def test_owned_deck_identity_and_appearance_validation(game, damage):
    snapshot = game[3]
    if damage == "missing-card":
        snapshot.deckPositions[0].cardId = "missing"
    elif damage == "duplicate-slot":
        snapshot.deckPositions[0].position = snapshot.deckPositions[1].position
    elif damage == "wrong-owner":
        snapshot.deckPositions[0].costumeId = snapshot.deckPositions[1].costumeId
    elif damage == "missing-public":
        snapshot.userPublic.publicUserId = ""
    else:
        snapshot.characters[0].lightFanAmount = -1
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure):
        prepare(game)
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("damage", ("schema", "version", "missing-table", "area", "chart", "pressure", "audience", "effect", "target", "trigger", "detail",
                                    "pressure-type", "trigger-type", "effect-type", "target-type"))
def test_master_dependencies_and_pins_fail_closed(game, monkeypatch, damage):
    rows = game[2]
    table = None
    if damage == "schema":
        monkeypatch.setattr(module, "SCHEMA_SHA256", "wrong")
    elif damage == "version":
        (game[1] / "!version.txt").write_text("wrong")
    elif damage == "missing-table":
        (game[1] / "QuestStaminaConsumption.json").unlink()
    elif damage == "area":
        rows["Area"][0]["questIds"] = []; table = "Area"
    elif damage == "chart":
        rows["MusicChartPattern"][0]["type"] = 999; table = "MusicChartPattern"
    elif damage == "pressure":
        rows["QuestPressure"][0]["weightPermil"] = 0; table = "QuestPressure"
    elif damage == "audience":
        rows["QuestAudienceAdvantage"][0]["id"] = "wrong"; table = "QuestAudienceAdvantage"
    elif damage == "effect":
        rows["SkillEfficacy"][0]["id"] = "wrong"; table = "SkillEfficacy"
    elif damage == "target":
        rows["SkillEfficacy"][0]["skillTargetId"] = "wrong"; table = "SkillEfficacy"
    elif damage == "trigger":
        rows["Skill"][0]["levels"][0]["triggerId"] = "wrong"; table = "Skill"
    elif damage == "pressure-type":
        rows["Quest"][0]["questPressureId"] = {}; table = "Quest"
    elif damage == "trigger-type":
        rows["Skill"][0]["levels"][0]["triggerId"] = {"bad": 1}; table = "Skill"
    elif damage == "effect-type":
        rows["Skill"][0]["levels"][0]["skillDetails"][0]["efficacyId"] = []; table = "Skill"
    elif damage == "target-type":
        rows["SkillEfficacy"][0]["skillTargetId"] = {"bad": 1}; table = "SkillEfficacy"
    else:
        rows["Skill"][0]["levels"][0]["skillDetails"] = ["bad"]; table = "Skill"
    if table:
        rewrite(game, table)
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure):
        prepare(game)
    assert game[3].SerializeToString() == before


def test_chart_number_strings_sort_numerically_without_changing_master_or_snapshot(game):
    rows = game[2]["MusicChartPattern"]
    rows.extend([{**rows[0], "number": "10"}, {**rows[0], "number": 4}])
    rows[0]["number"] = "1"
    rewrite(game, "MusicChartPattern")
    before = game[3].SerializeToString()
    prepared = prepare(game)
    cls = message_factory.GetMessageClass(game[0].pool.FindMessageTypeByName("master.MusicChartPattern"))
    reference = [cls.FromString(base64.b64decode(value)).number for value in prepared["proto"]["ReferenceChart"]]
    assert reference == [1, 2, 3, 4, 10]
    assert rows[0]["number"] == "1" and game[3].SerializeToString() == before


@pytest.fixture(scope="module")
def actual_resources(tmp_path_factory):
    """Optional public-only inputs for the real producer -> native boundary."""
    from idoly_local.gameplay import seed_starter_profile
    from idoly_local.state import State

    project = Path(__file__).resolve().parents[1]
    descriptor = project / "data/protocol/idolypride-6.1.1.pb"
    source = project / "data/master-json"
    if not source.is_dir():
        source = Path("/workspace/scratch/server0214-master-json")
    stock = Path("/workspace/scratch/solis-live-validation/stock-main-input.json")
    if not descriptor.is_file() or not source.is_dir() or not stock.is_file():
        pytest.skip("Optional public master/client/stock artifacts are unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    root = tmp_path_factory.mktemp("actual-live-input")
    master = root / "master"
    shutil.copytree(source, master)
    bundle = json.loads(stock.read_text())
    for table in ("QuestPressure", "QuestAudienceAdvantage", "ComboAdvantage", "QuestStaminaConsumption"):
        cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
        rows = [MessageToDict(cls.FromString(base64.b64decode(encoded)), preserving_proto_field_name=True,
                              use_integers_for_enums=True, always_print_fields_with_no_presence=True)
                for encoded in bundle["proto"][table]]
        (master / (table + ".json")).write_text(json.dumps(rows))
    state = State(root / "state.sqlite")
    seed_starter_profile(state, schema, "local", master, manager_name="Local calculation test")
    snapshot = schema.response_type("/api.User/Get").FromString(state.snapshot("local")[0])
    snapshot.userPublic.publicUserId, snapshot.userPublic.serverUserId = "local-public-test", "different-server-test"
    return schema, master, snapshot.SerializeToString()


def test_actual_canonical_first_quest_projects_expected_owned_roster(actual_resources):
    schema, master, raw = actual_resources
    snapshot = schema.response_type("/api.User/Get").FromString(raw)
    prepared = module.prepare_main_live(schema, master, snapshot, module.MAIN_QUEST_ID, 1, 123456)
    cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveUserInfo"))
    live = cls.FromString(base64.b64decode(prepared["proto"]["UserInfo"][0]))
    assert live.userId == "local-public-test" and live.userId != snapshot.userPublic.serverUserId
    assert [card.cardId for card in live.userDeck.cards] == [
        "card-" + key + "-03-schl-00" for key in ("ktn", "ngs", "mei", "suz", "ski")]
    assert [entry["character_id"] for entry in prepared["cards"]] == [
        "char-" + key for key in ("ktn", "ngs", "mei", "suz", "ski")]
    assert len(prepared["proto"]["Chart"]) == 284
    assert len(prepared["proto"]["SkillEfficacy"]) == 8
    assert snapshot.SerializeToString() == raw


def test_actual_prepared_snapshot_runs_native_local_rules_and_zero_control(actual_resources):
    from idoly_local.live_engine import NativeLiveEngine

    candidates = [Path("/workspace/shared/artifacts/live-native-bridge/linux/libidoly_live.so"),
                  Path(__file__).resolve().parents[1] / "native-live-engine/build/linux/libidoly_live.so"]
    library = next((path for path in candidates if path.is_file()), None)
    if library is None:
        pytest.skip("Optional native Linux library is unavailable")
    schema, master, raw = actual_resources
    snapshot = schema.response_type("/api.User/Get").FromString(raw)
    prepared = module.prepare_main_live(schema, master, snapshot, module.MAIN_QUEST_ID, 1, 123456)
    engine = NativeLiveEngine(library)
    cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveResult"))
    output = engine.simulate(prepared)
    result = cls.FromString(output)
    assert result.cleared and result.userInfos[0].userResult.score == 4781
    assert result.userInfos[0].userId == snapshot.userPublic.publicUserId
    assert len(result.charts) == 183 and sum(len(row.beats) for row in result.charts) == 855
    assert output == engine.simulate(prepared)
    zero = copy.deepcopy(prepared)
    user_cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveUserInfo"))
    user = user_cls.FromString(base64.b64decode(zero["proto"]["UserInfo"][0]))
    for card in user.userDeck.cards:
        card.vocal = card.dance = card.visual = 0
    zero["proto"]["UserInfo"][0] = base64.b64encode(user.SerializeToString()).decode()
    failed = cls.FromString(engine.simulate(zero))
    assert not failed.cleared and failed.userInfos[0].userResult.score == 0
    assert snapshot.SerializeToString() == raw
