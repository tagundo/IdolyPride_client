from pathlib import Path
import hashlib
import io
import json
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


def test_home_hierarchy_reference_requires_both_master_rows(tmp_path):
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "HierarchyDetailGrade.json").write_text(json.dumps([
        {"id": "hie-007-003", "hierarchyGradeId": "hie-007"}]))
    (master / "HierarchyGrade.json").write_text(json.dumps([{"id": "hie-007"}]))
    home = SimpleNamespace(hierarchyNotiInfo=SimpleNamespace(currentDetailGradeId="hie-007-003"))
    assert engine._home_hierarchy_reference(home, tmp_path) is True
    home.hierarchyNotiInfo.currentDetailGradeId = ""
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "missing"
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "hie-007-003"
    (master / "HierarchyGrade.json").write_text("[]")
    assert engine._home_hierarchy_reference(home, tmp_path) is False


def _client_schema():
    from idoly_local.schema import Schema
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(descriptor)


def test_home_positions_require_four_distinct_owned_characters_and_original_home1():
    user = _client_schema().response_type("/api.User/Get")()
    for kind, character in enumerate(("char-ktn", "char-ngs", "char-mei", "char-suz"), 1):
        user.characters.add(characterId=character)
        user.homePositions.add(homePositionType=kind, characterId=character)
    assert engine._home_positions_distinct(user) is True
    user.homePositions[3].characterId = "char-ktn"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].characterId = "unowned"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].characterId = "char-suz"
    user.homePositions[0].characterId, user.homePositions[1].characterId = "char-ngs", "char-ktn"
    assert engine._home_positions_distinct(user) is False
    user.homePositions[0].characterId, user.homePositions[1].characterId = "char-ktn", "char-ngs"
    user.homePositions[3].homePositionType = 3
    assert engine._home_positions_distinct(user) is False
    user.homePositions[3].homePositionType = 4
    user.homePositions[3].isCharacterRandom = True
    assert engine._home_positions_distinct(user) is False


@pytest.fixture
def initial_inventory(tmp_path):
    user = _client_schema().response_type("/api.User/Get")()
    user.user.deckSequence = 1
    user.decks.add(number=1, name="Local deck")
    tables = {name: [] for name in ("Reward", "Item", "Card", "CardParameter", "CardRarity",
                                    "CardLevelRelease", "Skill", "Setting", "Character", "Costume", "Hair")}
    resources = []
    for i in range(17):
        character, card, costume, hair, skill = (prefix + str(i) for prefix in ("char-", "card-", "costume-", "hair-", "skill-"))
        resources.extend(({"resourceType": 4, "resourceId": character, "amount": 1},
                          {"resourceType": 2, "resourceId": card, "amount": 1}))
        tables["Character"].append({"id": character})
        tables["Costume"].append({"id": costume, "characterId": character})
        tables["Hair"].append({"id": hair, "characterId": character, "wearableCostumeIds": [costume]})
        tables["Card"].append({"id": card, "characterId": character, "initialRarity": 1,
            "cardParameterId": "parameters", "cardLevelReleaseId": "release",
            "vocalRatioPermil": 404, "danceRatioPermil": 316, "visualRatioPermil": 280,
            "staminaRatioPermil": 1000, "skillId1": skill, "skillId2": "locked-skill"})
        tables["Skill"].append({"id": skill, "levels": [{"level": 1, "requiredCardLevel": 1}]})
        user.characters.add(characterId=character)
        user.costumes.add(costumeId=costume)
        user.hairs.add(hairId=hair)
        # Independently stated expected results: floor(257*ratio/1000), then
        # floor(value*1250/1000); collapsing floors would make vocal 129.
        user.cards.add(cardId=card, obtainedTime=123456, level=1, baseLevel=1, rarity=1, displayType=1,
            vocal=128, baseVocal=128, dance=101, baseDance=101, visual=88, baseVisual=88,
            stamina=1253, baseStamina=1253, mental=100, technique=101,
            skillId1=skill, baseSkillId1=skill, skillLevel1=1, baseSkillLevel1=1,
            photoEquipableCount=1, basePhotoEquipableCount=1)
        if i < 5:
            user.deckPositions.add(number=1, position=i + 1, cardId=card, costumeId=costume, hairId=hair)
    for identity, amount in (("initial-item-a", 200), ("initial-item-b", 400)):
        resources.append({"resourceType": 1, "resourceId": identity, "amount": amount})
        tables["Item"].append({"id": identity})
        user.items.add(itemId=identity, amount=amount)
    tables["Reward"].append({"id": "initial_user_reward", "resources": resources})
    tables["CardParameter"].append({"id": "parameters", "level": 1, "value": "257", "staminaValue": "1003"})
    tables["CardRarity"].append({"rarity": 1, "parameterBonusPermil": 1250})
    tables["CardLevelRelease"].append({"id": "release", "level": 1,
        "targets": [{"type": 1, "number": 1}, {"type": 7, "number": 1}, {"type": 4, "number": 1}]})
    tables["Setting"].append({"cardDefaultMental": 100, "cardDefaultTechnique": 101})
    master = tmp_path / "master-json"
    master.mkdir()
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    return user, tables, tmp_path


def test_initial_inventory_uses_public_reward_exact_parameters_and_five_owned_slots(initial_inventory):
    user, _tables, directory = initial_inventory
    assert engine._initial_inventory_reference(user, directory) == {
        "initial_card_count": 17, "initial_item_count": 2, "default_unit_slot_count": 5}


@pytest.mark.parametrize("changed", ("card-missing", "collapsed-stat-floors", "wrong-base-stat", "locked-skill",
    "wrong-base-skill", "ability-released", "wrong-photo-slots", "no-obtained-time", "wrong-item-amount",
    "expired-item", "extra-item", "duplicate-unit-card", "missing-unit-slot", "duplicate-unit-slot",
    "unowned-unit-card", "wrong-costume-owner", "wrong-hair-owner", "hair-not-wearable", "unowned-character"))
def test_initial_inventory_rejects_bad_grants_parameters_or_default_unit(initial_inventory, changed):
    user, tables, directory = initial_inventory
    if changed == "card-missing":
        del user.cards[-1]
    elif changed == "collapsed-stat-floors":
        user.cards[0].vocal = user.cards[0].baseVocal = 129
    elif changed == "wrong-base-stat":
        user.cards[0].baseStamina += 1
    elif changed == "locked-skill":
        user.cards[0].skillId2 = "locked-skill"
        user.cards[0].skillLevel2 = 1
    elif changed == "wrong-base-skill":
        user.cards[0].baseSkillLevel1 = 0
    elif changed == "ability-released":
        user.cards[0].liveAbilityLevel = 1
    elif changed == "wrong-photo-slots":
        user.cards[0].photoEquipableCount = 2
    elif changed == "no-obtained-time":
        user.cards[0].obtainedTime = 0
    elif changed == "wrong-item-amount":
        user.items[0].amount += 1
    elif changed == "expired-item":
        user.items[0].expiredTime = 123
    elif changed == "extra-item":
        user.items.add(itemId="gift-item", amount=1)
    elif changed == "duplicate-unit-card":
        user.deckPositions[4].cardId = user.deckPositions[0].cardId
    elif changed == "missing-unit-slot":
        del user.deckPositions[-1]
    elif changed == "duplicate-unit-slot":
        user.deckPositions[-1].position = 4
    elif changed == "unowned-unit-card":
        user.deckPositions[0].cardId = "unowned-card"
    elif changed == "unowned-character":
        del user.characters[-1]
    else:
        table = "Costume" if changed == "wrong-costume-owner" else "Hair"
        if changed == "hair-not-wearable":
            tables[table][0]["wearableCostumeIds"] = []
        else:
            tables[table][0]["characterId"] = "char-1"
        (directory / ("master-json/" + table + ".json")).write_text(json.dumps(tables[table]))
    with pytest.raises(RuntimeError):
        engine._initial_inventory_reference(user, directory)


def _live_asset_response():
    response = _client_schema().response_type("/api.Quest/ListAsset")()
    response.commonResponse.SetInParent()
    for number in range(5):
        response.characterAssets.add(characterId="char-" + str(number),
            costumeId="costume-" + str(number), hairId="hair-" + str(number))
    return response


def test_live_assets_require_exact_ordered_owned_appearances_without_mutation(initial_inventory):
    user, _tables, directory = initial_inventory
    saved = user.SerializeToString(deterministic=True)
    response = _live_asset_response()
    assert engine._quest_list_asset_reference(response, user, directory) == 5
    assert user.SerializeToString(deterministic=True) == saved
    # Stored protobuf row order is not slot order; the RPC follows positions 1..5.
    positions = [type(row).FromString(row.SerializeToString()) for row in user.deckPositions]
    del user.deckPositions[:]
    user.deckPositions.extend(reversed(positions))
    assert engine._quest_list_asset_reference(response, user, directory) == 5


@pytest.mark.parametrize("allowed,denied", (([], []), ([], ["costume-other"]),
                                           (["costume-other"], ["costume-another"])))
def test_live_assets_accept_native_unrestricted_or_nonmatching_deny_hair(initial_inventory, allowed, denied):
    user, tables, directory = initial_inventory
    tables["Hair"][0].update(wearableCostumeIds=allowed, notWearableCostumeIds=denied)
    (directory / "master-json/Hair.json").write_text(json.dumps(tables["Hair"]))
    assert engine._quest_list_asset_reference(_live_asset_response(), user, directory) == 5


@pytest.mark.parametrize("changed", ("missing", "extra", "order", "character", "costume", "hair",
                                    "missing-common", "common-mutation", "unknown-field"))
def test_live_assets_reject_inexact_response_or_mutation_payload(initial_inventory, changed):
    user, _tables, directory = initial_inventory
    response = _live_asset_response()
    if changed == "missing":
        del response.characterAssets[-1]
    elif changed == "extra":
        response.characterAssets.add(characterId="char-5", costumeId="costume-5", hairId="hair-5")
    elif changed == "order":
        first = type(response.characterAssets[0]).FromString(response.characterAssets[0].SerializeToString())
        response.characterAssets[0].CopyFrom(response.characterAssets[1])
        response.characterAssets[1].CopyFrom(first)
    elif changed in ("character", "costume", "hair"):
        setattr(response.characterAssets[0], changed + "Id", changed + "-1")
    elif changed == "missing-common":
        response.ClearField("commonResponse")
    elif changed == "common-mutation":
        response.commonResponse.updatedData.SetInParent()
    else:
        response.MergeFromString(b"\xa0\x06\x01")  # Unexpected field 100 must not pass an exact response check.
    with pytest.raises(RuntimeError):
        engine._quest_list_asset_reference(response, user, directory)


@pytest.mark.parametrize("changed", ("missing-slot", "duplicate-slot", "unowned-card", "unowned-character",
                                    "unowned-costume", "unowned-hair", "wrong-costume-owner",
                                    "wrong-hair-owner", "incompatible-hair", "denied-hair", "empty-costume", "empty-hair"))
def test_live_asset_reference_rejects_invalid_or_sparse_seeded_unit(initial_inventory, changed):
    user, tables, directory = initial_inventory
    if changed == "missing-slot":
        del user.deckPositions[-1]
    elif changed == "duplicate-slot":
        user.deckPositions[-1].position = 4
    elif changed.startswith("unowned-"):
        collection = {"card": user.cards, "character": user.characters,
                      "costume": user.costumes, "hair": user.hairs}[changed.removeprefix("unowned-")]
        del collection[0]
    elif changed in ("empty-costume", "empty-hair"):
        setattr(user.deckPositions[0], changed.removeprefix("empty-") + "Id", "")
    else:
        table = "Costume" if changed == "wrong-costume-owner" else "Hair"
        if changed in ("incompatible-hair", "denied-hair"):
            tables[table][0]["wearableCostumeIds"] = ["costume-1"]
            if changed == "denied-hair":
                tables[table][0]["notWearableCostumeIds"] = ["costume-0"]
        else:
            tables[table][0]["characterId"] = "char-1"
        (directory / ("master-json/" + table + ".json")).write_text(json.dumps(tables[table]))
    with pytest.raises(RuntimeError):
        engine._quest_list_asset_reference(_live_asset_response(), user, directory)


@pytest.mark.parametrize("captured,expected_count", (((0, 1, 2, 5, 6, 7), 8), ((0, 1, 5, 6, 7, 8), 9)))
def test_tutorial_assets_append_recorded_six_in_order_with_full_triple_dedup(initial_inventory, captured, expected_count):
    user, _tables, directory = initial_inventory
    replay = _client_schema().response_type("/api.Tutorial/StartQuest")()
    deck = replay.result.userInfos.add().userDeck
    for index, character in enumerate(captured[:5], 1):
        deck.cards.add(index=index, displayCharacterId="char-" + str(character),
            displayCostumeId="costume-" + str(character), displayHairId="hair-" + str(character))
    character = captured[-1]
    deck.extraCharacterInfos.add(position=6, characterId="char-" + str(character),
        costumeId="costume-" + str(character), hairId="hair-" + str(character))
    assets = _live_asset_response()
    for character in captured:
        if character >= 5:
            assets.characterAssets.add(characterId="char-" + str(character),
                costumeId="costume-" + str(character), hairId="hair-" + str(character))
    assert engine._quest_list_asset_reference(assets, user, directory, replay) == expected_count
    del assets.characterAssets[-1]
    with pytest.raises(RuntimeError):
        engine._quest_list_asset_reference(assets, user, directory, replay)


@pytest.fixture
def tutorial_replays(initial_inventory):
    user, tables, directory = initial_inventory
    schema = _client_schema()
    originals = Path(__file__).resolve().parents[2] / "data/public-tutorial"
    if not all((originals / ("tutorial-" + kind + ".pb")).is_file() for kind in ("short", "full")):
        pytest.skip("Optional pinned public tutorial fixtures are unavailable")
    public = directory / "public-tutorial"
    public.mkdir()
    canonical = {}
    for kind in ("short", "full"):
        raw = (originals / ("tutorial-" + kind + ".pb")).read_bytes()
        (public / ("tutorial-" + kind + ".pb")).write_bytes(raw)
        canonical[kind] = schema.response_type("/api.Tutorial/StartQuest").FromString(raw)
    tables.update({"Quest": [{"id": "qt-tutorial-" + kind, "areaId": "area-tutorial", "musicId": "demo-music",
                               "stageId": "demo-stage", "musicChartPatternId": "demo-pattern"} for kind in canonical],
        "Area": [{"id": "area-tutorial", "type": 101}], "Music": [{"id": "demo-music"}],
        "Stage": [{"id": "demo-stage"}], "Emblem": [{"id": "emb-001"}, {"id": "emb-local"}],
        "SkillEfficacy": [{"id": "demo-efficacy", "skillTargetId": "demo-target"}],
        "SkillTrigger": [{"id": "demo-trigger"}], "SkillTarget": [{"id": "demo-target"}]})
    tables["Setting"][0].update(tutorialShortQuestId="qt-tutorial-short", tutorialFullQuestId="qt-tutorial-full")
    chart_keys = {(chart.number, chart.chartType) for replay in canonical.values() for chart in replay.result.charts}
    tables["MusicChartPattern"] = [{"id": "demo-pattern", "number": number, "type": kind}
                                    for number, kind in sorted(chart_keys)]
    for replay in canonical.values():
        for character, costume, hair in engine._tutorial_appearances(replay):
            for name, row in (("Character", {"id": character}),
                              ("Costume", {"id": costume, "characterId": character}),
                              ("Hair", {"id": hair, "characterId": character, "wearableCostumeIds": [costume]})):
                if not any(saved["id"] == row["id"] for saved in tables[name]):
                    tables[name].append(row)
        for card in replay.result.userInfos[0].userDeck.cards:
            if not any(row["id"] == card.cardId for row in tables["Card"]):
                tables["Card"].append({"id": card.cardId, "characterId": card.displayCharacterId,
                    **{"skillId" + str(i): skill.skillId for i, skill in enumerate(card.skills, 1)}})
            if not any(row.cardId == card.cardId for row in user.cards):
                user.cards.add(cardId=card.cardId, **{field: getattr(card, field) for field in
                    ("level", "rarity", "vocal", "dance", "visual", "stamina", "mental", "technique",
                     "skillLevel1", "skillLevel2", "skillLevel3", "skillLevel4")})
            for skill in card.skills:
                if not any(row["id"] == skill.skillId for row in tables["Skill"]):
                    tables["Skill"].append({"id": skill.skillId, "levels": [{"level": skill.skillLevel,
                        "triggerId": "demo-trigger", "skillDetails": [{"efficacyId": "demo-efficacy"}]}]})
    for name, rows in tables.items():
        (directory / "master-json" / (name + ".json")).write_text(json.dumps(rows))
    user.userPublic.publicUserId, user.user.name, user.user.emblemId = "local-public-id", "Local demo", "emb-local"
    return user, canonical, tables, directory


def _localized_replay(canonical, user):
    response = type(canonical)()
    response.CopyFrom(canonical)
    info = response.result.userInfos[0]
    info.userId, info.name, info.emblemId = user.userPublic.publicUserId, user.user.name, user.user.emblemId
    return response


@pytest.mark.parametrize("kind,charts,score", (("short", 158, 8813), ("full", 156, 10717)))
def test_tutorial_replay_keeps_whole_official_record_except_three_local_identity_fields(tutorial_replays, kind, charts, score):
    user, canonical, _tables, directory = tutorial_replays
    response = _localized_replay(canonical[kind], user)
    assert engine._tutorial_replay_reference(response, user, directory, kind) == {
        "tutorial_replay_" + kind + "_charts": charts, "tutorial_replay_" + kind + "_score": score}
    user.user.emblemId = "invalid-local-emblem"
    response.result.userInfos[0].emblemId = canonical[kind].result.userInfos[0].emblemId
    assert engine._tutorial_replay_reference(response, user, directory, kind)


@pytest.mark.parametrize("changed", ("score", "missing-chart", "chart-order", "rank", "card-stat", "missing-extra",
                                    "user-id", "name", "emblem", "detail", "detail-available", "common", "unknown"))
def test_tutorial_replay_rejects_record_identity_privacy_or_mutation_changes(tutorial_replays, changed):
    user, canonical, _tables, directory = tutorial_replays
    response = _localized_replay(canonical["short"], user)
    info = response.result.userInfos[0]
    if changed == "score": info.userResult.score += 1
    elif changed == "missing-chart": del response.result.charts[-1]
    elif changed == "chart-order": response.result.charts[0].number += 1
    elif changed == "rank": response.rankPatterns[0].thresholdScore += 1
    elif changed == "card-stat": info.userDeck.cards[0].stamina += 1
    elif changed == "missing-extra": del info.userDeck.extraCharacterInfos[:]
    elif changed == "user-id": info.userId = "different-private-id"
    elif changed == "name": info.name = "other name"
    elif changed == "emblem": info.emblemId = "invalid-emblem"
    elif changed == "detail": response.result.detailLogId = "private-detail"
    elif changed == "detail-available": response.result.isDisplayDetailAvailable = True
    elif changed == "common": response.commonResponse.updatedData.SetInParent()
    else: response.MergeFromString(b"\xa0\x06\x01")
    with pytest.raises(RuntimeError):
        engine._tutorial_replay_reference(response, user, directory, "short")


@pytest.mark.parametrize("table,field,value", (("Quest", "musicId", "missing"), ("Quest", "stageId", "missing"),
    ("Quest", "musicChartPatternId", "missing"), ("SkillEfficacy", "skillTargetId", "missing"),
    ("Costume", "characterId", "wrong")))
def test_tutorial_replay_rejects_broken_public_master_references(tutorial_replays, table, field, value):
    user, canonical, tables, directory = tutorial_replays
    row = tables[table][0] if table != "Costume" else next(row for row in tables[table] if row["id"] == "cos-skr-schl-00")
    row[field] = value
    (directory / "master-json" / (table + ".json")).write_text(json.dumps(tables[table]))
    with pytest.raises(RuntimeError):
        engine._tutorial_replay_reference(_localized_replay(canonical["short"], user), user, directory, "short")


def test_tutorial_replay_accepts_untargeted_score_efficacy(tutorial_replays):
    user, canonical, tables, directory = tutorial_replays
    tables["SkillEfficacy"][0]["skillTargetId"] = ""
    (directory / "master-json/SkillEfficacy.json").write_text(json.dumps(tables["SkillEfficacy"]))
    assert engine._tutorial_replay_reference(_localized_replay(canonical["short"], user), user, directory, "short")


def test_tutorial_fixture_rejects_unpinned_bytes(tutorial_replays):
    user, canonical, _tables, directory = tutorial_replays
    path = directory / "public-tutorial/tutorial-short.pb"
    path.write_bytes(path.read_bytes() + b"\xa0\x06\x01")
    with pytest.raises(RuntimeError, match="pinned"):
        engine._tutorial_replay_reference(_localized_replay(canonical["short"], user), user, directory, "short")


def test_tutorial_replay_rejects_parameters_different_from_the_verified_owned_card(tutorial_replays):
    user, canonical, _tables, directory = tutorial_replays
    card = next(row for row in user.cards if row.cardId == "card-skr-03-schl-00")
    card.vocal += 1
    with pytest.raises(RuntimeError, match="parameters"):
        engine._tutorial_replay_reference(_localized_replay(canonical["short"], user), user, directory, "short")


def test_whole_database_guard_detects_unrelated_marker_and_currency_writes(tmp_path):
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.executescript("CREATE TABLE profiles(snapshot BLOB); INSERT INTO profiles VALUES(X'0102');"
                                 "CREATE TABLE markers(version INTEGER); INSERT INTO markers VALUES(4);"
                                 "CREATE TABLE currency(amount INTEGER); INSERT INTO currency VALUES(0);")
    before = engine._whole_database_state(tmp_path)
    assert engine._whole_database_state(tmp_path) == before
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.execute("UPDATE markers SET version=5")
    assert engine._whole_database_state(tmp_path) != before
    with sqlite3.connect(tmp_path / "state.db") as connection:
        connection.execute("UPDATE markers SET version=4")
        connection.execute("UPDATE currency SET amount=1")
    assert engine._whole_database_state(tmp_path) != before


@pytest.mark.parametrize("table,column,replacement", (
    ("profiles", "server_id", "changed-server"),
    ("sessions", "expires_at", 4102444800),
    ("profile_settings", "response", b"changed-settings"),
    ("starter_profiles", "version", 3),
))
def test_continuation_guard_allows_gameplay_snapshot_but_detects_preserved_row_changes(
        tmp_path, table, column, replacement):
    from idoly_local.state import State

    state = State(tmp_path / "state.db")
    state.save_snapshot("sandbox", b"initial", "schema", starter_version=4)
    state.login("sandbox")
    state.mutate_snapshot("sandbox", "schema", lambda payload: payload, setting_info=b"original-settings")
    preserved = engine._preserved_database_state(tmp_path)
    state.mutate_snapshot("sandbox", "schema", lambda _payload: b"progressed")
    assert engine._preserved_database_state(tmp_path) == preserved
    with sqlite3.connect(state.path) as connection:
        connection.execute("UPDATE " + table + " SET " + column + "=?", (replacement,))
    assert engine._preserved_database_state(tmp_path) != preserved


@pytest.fixture
def quest_catalog(tmp_path):
    schema = _client_schema()
    master = tmp_path / "master-json"
    master.mkdir()
    rows = {
        "AreaGroup": [{"id": "later", "order": 20, "areaIds": ["a3"]},
                      {"id": "first", "order": 10, "areaIds": ["a2", "a1"]},
                      {"id": "area-main-group-999", "order": 999, "areaIds": ["area-tutorial"]}],
        "Area": [{"id": key, "type": 1, "areaGroupId": "later" if key == "a3" else "first",
                  "questIds": [key + "-q2", key + "-q1"]} for key in ("a1", "a2", "a3")]
                + [{"id": "area-tutorial", "type": 101, "areaGroupId": "area-main-group-999",
                    "questIds": ["qt-tutorial-full", "qt-tutorial-short"]},
                   {"id": "area-contest-001", "type": 2,
                    "questIds": ["contest-q" + str(i) for i in range(23)]}],
        "Quest": [{"id": key + suffix, "areaId": key} for key in ("a1", "a2", "a3")
                  for suffix in ("-q1", "-q2")]
                 + [{"id": key, "areaId": "area-tutorial"} for key in ("qt-tutorial-full", "qt-tutorial-short")]
                 + [{"id": "contest-q" + str(i), "areaId": "area-contest-001"} for i in range(23)],
        "HierarchyDetailGrade": [{"id": "detail", "hierarchyGradeId": "grade"}],
        "HierarchyGrade": [{"id": "grade"}],
    }
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    top = schema.response_type("/api.Quest/Top")()
    top.pvpInfo.SetInParent()
    top.hierarchyNotiInfo.currentDetailGradeId = "detail"
    for group_id, area_ids in (("first", ("a2", "a1")), ("later", ("a3",))):
        group = top.mainAreaGroups.add(areaGroupId=group_id)
        for area_id in area_ids:
            area = group.areas.add(areaId=area_id)
            for suffix in ("-q2", "-q1"):
                area.quests.add(questId=area_id + suffix)
    top.mainAreaGroups[0].areas[0].unlocked = True
    top.mainAreaGroups[0].areas[0].quests[0].isPlayable = True
    tutorial = top.mainAreaGroups.add(areaGroupId="area-main-group-999").areas.add(areaId="area-tutorial", unlocked=True)
    for key in ("qt-tutorial-full", "qt-tutorial-short"):
        tutorial.quests.add(questId=key, isPlayable=True)
    top.contestArea.areaId = "area-contest-001"
    for i in range(23):
        top.contestArea.quests.add(questId="contest-q" + str(i))
    user = schema.response_type("/api.User/Get")()
    user.tutorials.add(tutorialType=1, step=0)
    return schema, top, rows, tmp_path, user


def _matching_main(schema, top):
    main = schema.response_type("/api.Quest/ListMain")()
    main.areaGroups.extend(top.mainAreaGroups)
    return main


def test_quest_catalog_uses_real_group_order_and_explicit_child_references(quest_catalog):
    schema, top, _rows, directory, user = quest_catalog
    assert engine._quest_catalog_reference(top, _matching_main(schema, top), directory, user) == "a2-q2"


@pytest.mark.parametrize("changed", ("different-list", "group-order", "area-order", "quest-order",
                                    "missing-pvp", "missing-hierarchy", "locked-first", "cleared-first",
                                    "wrong-area-parent", "wrong-quest-parent", "missing-main-area"))
def test_quest_catalog_rejects_mismatched_references_or_unusable_first_quest(quest_catalog, changed):
    schema, top, rows, directory, user = quest_catalog
    if changed == "group-order":
        copy = type(top)()
        copy.CopyFrom(top)
        del top.mainAreaGroups[:]
        top.mainAreaGroups.extend(reversed(copy.mainAreaGroups))
    elif changed in ("area-order", "quest-order"):
        container = top.mainAreaGroups[0].areas if changed == "area-order" else top.mainAreaGroups[0].areas[0].quests
        copies = [type(row)().FromString(row.SerializeToString()) for row in container]
        del container[:]
        container.extend(reversed(copies))
    elif changed == "missing-pvp":
        top.ClearField("pvpInfo")
    elif changed == "missing-hierarchy":
        top.hierarchyNotiInfo.currentDetailGradeId = "missing"
    elif changed == "locked-first":
        top.mainAreaGroups[0].areas[0].quests[0].isPlayable = False
    elif changed == "cleared-first":
        top.mainAreaGroups[0].areas[0].quests[0].cleared = True
    elif changed == "wrong-area-parent":
        rows["Area"][1]["areaGroupId"] = "later"
        (directory / "master-json/Area.json").write_text(json.dumps(rows["Area"]))
    elif changed == "wrong-quest-parent":
        rows["Quest"][3]["areaId"] = "a1"
        (directory / "master-json/Quest.json").write_text(json.dumps(rows["Quest"]))
    elif changed == "missing-main-area":
        rows["Area"].append({"id": "unlisted-main", "type": 1, "areaGroupId": "first", "questIds": ["hidden-q"]})
        (directory / "master-json/Area.json").write_text(json.dumps(rows["Area"]))
    main = _matching_main(schema, top)
    if changed == "different-list":
        main.areaGroups[0].areas[0].quests[0].highestScore = 10
    with pytest.raises(RuntimeError):
        engine._quest_catalog_reference(top, main, directory, user)


@pytest.mark.parametrize("step", (None, 0, 149, 150, 151))
def test_quest_catalog_tutorial_group_follows_actual_game_start_step(quest_catalog, step):
    schema, top, _rows, directory, user = quest_catalog
    if step is None:
        del user.tutorials[:]
    else:
        user.tutorials[0].step = step
    if step is not None and step >= 150:
        del top.mainAreaGroups[-1]
    assert engine._quest_catalog_reference(top, _matching_main(schema, top), directory, user) == "a2-q2"


@pytest.mark.parametrize("changed", ("missing-contest", "empty-contest", "wrong-contest-id", "contest-unlocked",
                                    "contest-playable", "contest-quota", "contest-campaign", "contest-order", "contest-parent",
                                    "missing-tutorial", "completed-tutorial-present", "tutorial-locked",
                                    "tutorial-unplayable", "tutorial-alternative-missing", "tutorial-campaign",
                                    "ambiguous-tutorial"))
def test_quest_catalog_rejects_incomplete_contest_or_wrong_tutorial_context(quest_catalog, changed):
    schema, top, rows, directory, user = quest_catalog
    if changed == "missing-contest":
        top.ClearField("contestArea")
    elif changed == "empty-contest":
        del top.contestArea.quests[:]
    elif changed == "wrong-contest-id":
        top.contestArea.areaId = "unknown"
    elif changed == "contest-unlocked":
        top.contestArea.unlocked = True
    elif changed == "contest-playable":
        top.contestArea.quests[0].isPlayable = True
    elif changed == "contest-quota":
        top.contestArea.quests[0].playableCount = 1
    elif changed == "contest-campaign":
        top.contestArea.quests[0].campaignDropRewardIds.append("unsupported")
    elif changed == "contest-order":
        top.contestArea.quests[0].questId = "contest-q1"
    elif changed == "contest-parent":
        rows["Quest"][-1]["areaId"] = "a1"
        (directory / "master-json/Quest.json").write_text(json.dumps(rows["Quest"]))
    elif changed == "missing-tutorial":
        del top.mainAreaGroups[-1]
    elif changed == "completed-tutorial-present":
        user.tutorials[0].step = 150
    elif changed == "tutorial-locked":
        top.mainAreaGroups[-1].areas[0].unlocked = False
    elif changed == "tutorial-unplayable":
        top.mainAreaGroups[-1].areas[0].quests[1].isPlayable = False
    elif changed == "tutorial-alternative-missing":
        del top.mainAreaGroups[-1].areas[0].quests[1]
    elif changed == "tutorial-campaign":
        top.mainAreaGroups[-1].areas[0].quests[0].campaignDropRewardIds.append("unsupported")
    elif changed == "ambiguous-tutorial":
        user.tutorials.add(tutorialType=1, step=150)
    with pytest.raises(RuntimeError):
        engine._quest_catalog_reference(top, _matching_main(schema, top), directory, user)


class Runtime:
    def __init__(self):
        self.running = True
        self.stops = 0

    def status(self):
        return {"running": self.running, "profile": "sandbox", "grpc_address": "127.0.0.1:50051",
                "asset_url": "http://127.0.0.1:8080", "logs": ["not repeated in status"]}

    def stop(self):
        self.running = False
        self.stops += 1


def wait_until(check):
    deadline = time.monotonic() + 3
    while not check() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert check()


def test_native_control_start_stop_does_not_duplicate_runtime_or_logs(tmp_path, monkeypatch):
    events, runtimes = [], []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        runtime = Runtime()
        runtimes.append(runtime)
        kwargs["log_callback"]("server ready")
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda event, **data: events.append((event, data)))
    controller.start()
    wait_until(lambda: controller.runtime is not None)
    controller.start()
    assert len(runtimes) == 1
    assert controller.status()["running"] is True
    assert "logs" not in controller.status()
    controller.stop()
    assert runtimes[0].stops == 1
    assert controller.status()["running"] is False
    controller.close()
    assert runtimes[0].stops == 1
    assert any(event == "log" and data["message"] == "server ready" for event, data in events)


def test_quit_during_startup_cancels_owned_runtime_without_late_start(tmp_path, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    runtime = Runtime()
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        entered.set()
        assert finish.wait(timeout=3)
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.start()
    assert entered.wait(timeout=3)
    controller.stop()
    finish.set()
    wait_until(lambda: controller.worker is None)
    assert runtime.stops == 1
    assert controller.runtime is None
    assert controller.status()["running"] is False
    controller.close()


def test_stop_failure_retains_owned_runtime_for_retry(tmp_path):
    class RetryRuntime(Runtime):
        def stop(self):
            self.stops += 1
            self.running = False
            if self.stops == 1:
                raise RuntimeError("retry cleanup")

    runtime = RetryRuntime()
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.runtime = runtime
    assert controller.stop()["can_stop"] is True
    assert controller.runtime is runtime
    assert controller.stop()["can_stop"] is False
    assert controller.runtime is None
    assert runtime.stops == 2


@pytest.mark.parametrize("mode", (None, False, True))
@pytest.mark.parametrize("media_mode", (None, False, True))
@pytest.mark.parametrize("download_missing", (None, False, True))
def test_native_controller_keeps_live_and_media_modes_independent_and_default_off(
        tmp_path, monkeypatch, mode, media_mode, download_missing):
    calls = []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        calls.append(kwargs)
        return Runtime()

    import idoly_local
    runtime_module = SimpleNamespace(start=start)
    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", runtime_module)
    monkeypatch.setattr(idoly_local, "app_runtime", runtime_module, raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    try:
        options = {} if media_mode is None else {"media_mode": media_mode}
        if download_missing is not None:
            options["download_missing_resources"] = download_missing
        controller.start(**options) if mode is None else controller.start(mode, **options)
        wait_until(lambda: controller.runtime is not None)
        assert len(calls) == 1
        assert calls[0].get("experimental_main_live", False) is (mode is True)
        assert calls[0]["media_mode"] is (media_mode is True)
        assert calls[0]["download_missing_resources"] is (download_missing is not False)
        assert calls[0]["resource_platform"] == "ios"
        if mode is not True:
            assert "experimental_main_live" not in calls[0]
    finally:
        controller.close()


@pytest.mark.parametrize("mode", (None, 0, 1, "true", "false", [], {}))
@pytest.mark.parametrize("option", ("experimental_main_live", "media_mode", "download_missing_resources"))
def test_native_controller_rejects_non_boolean_modes_before_start(tmp_path, monkeypatch, mode, option):
    def forbidden(*args):
        raise AssertionError("Invalid opt-in must not prepare payloads")

    monkeypatch.setattr(engine, "install_payload", forbidden)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="explicit boolean"):
        controller.start(**{option: mode})
    assert controller.worker is None and controller.runtime is None


def test_native_json_control_keeps_default_off_and_rejects_non_boolean_opt_in(tmp_path, monkeypatch):
    starts, errors, closed = [], [], []

    class Control:
        def __init__(self, *args):
            pass

        def start(self, *args):
            starts.append(args)

        def status(self):
            pass

        def close(self):
            closed.append(True)

    commands = [{"action": "start"}, {"action": "start", "experimental_main_live": False},
                {"action": "start", "experimental_main_live": True},
                {"action": "start", "media_mode": False}, {"action": "start", "media_mode": True},
                {"action": "start", "experimental_main_live": True, "media_mode": True},
                {"action": "start", "download_missing_resources": False}]
    commands.extend({"action": "start", "experimental_main_live": value}
                    for value in (None, 0, 1, "true", [], {}))
    commands.extend({"action": "start", "media_mode": value}
                    for value in (None, 0, 1, "true", [], {}))
    commands.extend({"action": "start", "download_missing_resources": value}
                    for value in (None, 0, 1, "true", [], {}))
    commands.append({"action": "quit"})
    monkeypatch.setattr(engine, "Controller", Control)
    monkeypatch.setattr(engine.signal, "signal", lambda *args: None)
    monkeypatch.setattr(engine, "emit", lambda event, **data: errors.append((event, data)))
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(map(json.dumps, commands))))
    assert engine.main(["--data-dir", str(tmp_path), "--server-data", str(tmp_path / "ServerData.zip")]) == 0
    assert starts == [(False, False, True), (False, False, True), (True, False, True),
                      (False, False, True), (False, True, True), (True, True, True), (False, False, False)]
    assert len(errors) == 18 and all(event == "error" for event, _ in errors)
    assert closed == [True]


@pytest.fixture
def main_live_database(tmp_path):
    """A settled native DB with two distinct opaque replay receipts."""
    schema = _client_schema()
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Original native manager"
    snapshot.MergeFromString(b"\x80\x4b\x7b")
    bodies = [schema.response_type("/api.Quest/Start")(questId="qt-main-1-001-01", highestScore=score)
              .SerializeToString(deterministic=True) for score in (4000, 5000)]
    digest = lambda payload: hashlib.sha256(payload).hexdigest()
    identities = ["9000000000000000301", "9000000000000000302"]
    started = [1794234000000, 1794234000001]
    receipt = {"request_ids": identities, "started_times": started, "request_sha256": "a" * 64,
               "schema_sha256": schema.fingerprint, "master_version": "original-master", "ruleset": "live-v5",
               "snapshot_sha256": digest(snapshot.SerializeToString(deterministic=True)),
               "first_response_sha256": digest(bodies[0]), "replay_response_sha256": digest(bodies[1])}
    clock = (b"unchanged raw clock\x00", schema.fingerprint)
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE snapshots(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE profile_lesson_progress(profile TEXT,response BLOB,schema_sha256 TEXT)")
        db.execute("CREATE TABLE main_live_attempts(profile TEXT,request_id TEXT,request_sha256 TEXT,path TEXT,"
                   "schema_sha256 TEXT,master_version TEXT,ruleset TEXT,seed TEXT,started_time INTEGER,response BLOB)")
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("sandbox", snapshot.SerializeToString(), schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES(?,?,?)", ("sandbox", *clock))
        for index, (identity, stamp, body) in enumerate(zip(identities, started, bodies)):
            seed = "0" if not index else str((1 << 64) - 1)
            db.execute("INSERT INTO main_live_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
                       ("sandbox", identity, receipt["request_sha256"], "/api.Quest/Start", schema.fingerprint,
                        receipt["master_version"], "live-v5", seed, stamp, body))
        # A different profile's incompatible data must never become the QA receipt.
        db.execute("INSERT INTO main_live_attempts(profile,request_id) VALUES('other-profile','unrelated')")
    return tmp_path, schema, receipt, clock


def test_native_main_live_database_keeps_exact_both_cached_responses_and_uint64_text(main_live_database):
    directory, schema, receipt, clock = main_live_database
    rows = engine._main_live_database(directory, schema, receipt, clock)
    assert len(rows) == 2
    assert [row[7] for row in rows] == ["0", str((1 << 64) - 1)]
    assert engine._main_live_database(directory, schema, receipt, clock, rows) == rows


@pytest.mark.parametrize("damage", ("snapshot", "snapshot-schema", "clock", "clock-schema", "missing-snapshot",
                                    "missing-clock", "missing-attempt", "seed", "time", "response", "context", "extra-column"))
def test_native_main_live_database_cannot_emit_success_for_lost_or_changed_state(main_live_database, damage):
    directory, schema, receipt, clock = main_live_database
    with sqlite3.connect(directory / "state.db") as db:
        if damage == "snapshot":
            db.execute("UPDATE snapshots SET response=x'0a00' WHERE profile='sandbox'")
        elif damage == "snapshot-schema":
            db.execute("UPDATE snapshots SET schema_sha256='changed' WHERE profile='sandbox'")
        elif damage == "clock":
            db.execute("UPDATE profile_lesson_progress SET response=x'00' WHERE profile='sandbox'")
        elif damage == "clock-schema":
            db.execute("UPDATE profile_lesson_progress SET schema_sha256='changed' WHERE profile='sandbox'")
        elif damage == "missing-snapshot":
            db.execute("DELETE FROM snapshots WHERE profile='sandbox'")
        elif damage == "missing-clock":
            db.execute("DELETE FROM profile_lesson_progress WHERE profile='sandbox'")
        elif damage == "missing-attempt":
            db.execute("DELETE FROM main_live_attempts WHERE request_id=?", (receipt["request_ids"][0],))
        elif damage == "seed":
            db.execute("UPDATE main_live_attempts SET seed='01' WHERE profile='sandbox'")
        elif damage == "time":
            db.execute("UPDATE main_live_attempts SET started_time=started_time+1 WHERE profile='sandbox'")
        elif damage == "response":
            db.execute("UPDATE main_live_attempts SET response=x'0a00' WHERE profile='sandbox'")
        elif damage == "context":
            db.execute("UPDATE main_live_attempts SET ruleset='unknown' WHERE profile='sandbox'")
        else:
            db.execute("ALTER TABLE main_live_attempts ADD COLUMN unexpected TEXT")
    with pytest.raises(RuntimeError):
        engine._main_live_database(directory, schema, receipt, clock)


def test_native_main_live_restart_rejects_a_rerolled_but_still_canonical_seed(main_live_database):
    directory, schema, receipt, clock = main_live_database
    rows = engine._main_live_database(directory, schema, receipt, clock)
    with sqlite3.connect(directory / "state.db") as db:
        db.execute("UPDATE main_live_attempts SET seed='1' WHERE request_id=?", (receipt["request_ids"][0],))
    # The receipt accepts any valid uint64 seed; the restart boundary must preserve the original too.
    assert engine._main_live_database(directory, schema, receipt, clock) != rows
    with pytest.raises(RuntimeError, match="seeds, timestamps or exact responses changed"):
        engine._main_live_database(directory, schema, receipt, clock, rows)
