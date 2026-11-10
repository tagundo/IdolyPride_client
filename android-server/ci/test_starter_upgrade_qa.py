"""Exercise native QA's private fixture round trip without an adb target."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from idoly_local.gameplay import (repair_starter_home_positions, repair_starter_inventory,
                                 repair_starter_roster, repair_starter_card_level_mission, seed_starter_profile)
from idoly_local.schema import Schema
from idoly_local.state import State


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_gameplay import initial_inventory_rows
SPEC = spec_from_file_location("starter_native_qa", Path(__file__).with_name("qa_emulator.py"))
qa = module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


@pytest.fixture
def fixture(tmp_path):
    descriptor = ROOT / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Recovered client descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    master = tmp_path / "master"
    master.mkdir()
    rows = {"Setting": [{"id": 1, "tutorialPhotoShootingCharacterIds": list(qa.PHOTO_CHARACTERS)}],
        "Character": [], "Costume": [], "Hair": [],
        "CharacterActivityLevel": [{"level": 1, "maxStamina": 800}],
        "Area": [{"id": "area-1", "type": 1, "order": 1, "areaGroupId": "group-1", "questIds": ["quest-1"]},
                 {"id": "area-tutorial", "type": 101, "areaGroupId": "area-main-group-999", "questIds": ["qt-tutorial-full", "qt-tutorial-short"]},
                 {"id": "area-contest-001", "type": 2, "questIds": ["contest-" + str(i) for i in range(23)]}],
        "AreaGroup": [{"id": "group-1", "order": 1, "areaIds": ["area-1"]},
                      {"id": "area-main-group-999", "order": 999, "areaIds": ["area-tutorial"]}],
        "Quest": [{"id": "quest-1", "areaId": "area-1"},
                  {"id": "qt-tutorial-full", "areaId": "area-tutorial"}, {"id": "qt-tutorial-short", "areaId": "area-tutorial"},
                  *({"id": "contest-" + str(i), "areaId": "area-contest-001"} for i in range(23))],
        "HierarchyGrade": [{"id": "hie-007"}],
        "HierarchyDetailGrade": [{"id": "hie-007-003", "hierarchyGradeId": "hie-007",
                                  "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0}]}
    rows["Setting"][0].update(cardDefaultMental=100, cardDefaultTechnique=100)
    rows.update(initial_inventory_rows(sorted(qa.STARTER_CHARACTERS)))
    for key in sorted(qa.STARTER_CHARACTERS):
        rows["Character"].append({"id": key, "type": 1, "defaultCostumeId": "cos-" + key,
                                  "defaultLiveCostumeId": "live-" + key})
        for prefix in ("cos-", "live-"):
            costume = prefix + key
            rows["Costume"].append({"id": costume, "characterId": key, "defaultHairId": "hair-" + costume})
            rows["Hair"].append({"id": "hair-" + costume, "characterId": key, "wearableCostumeIds": [costume]})
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    path = tmp_path / "original.db"
    state = State(path)
    seed_starter_profile(state, schema, "sandbox", master)
    def progress(payload):
        user = schema.response_type("/api.User/Get").FromString(payload)
        user.user.name = "Preserved manager"
        user.user.isReviewed = True
        user.user.lastLoginTime = 1794234000001
        user.totalCount.loginCount = 7
        user.tutorials[0].step = 10
        return user.SerializeToString()
    settings = schema.request_type("/api.Home/Login")().settingInfo
    settings.soundBgm = 37
    state.mutate_snapshot("sandbox", schema.fingerprint, progress, setting_info=settings.SerializeToString())
    token, _ = state.login("sandbox")
    # Copy a committed nonempty WAL, just as a force-stopped process can leave.
    hold = sqlite3.connect(path)
    settings.soundVoice = 61
    hold.execute("UPDATE profile_settings SET response=?", (settings.SerializeToString(),))
    hold.commit()
    files = {qa.PRIVATE_DATABASE: path.read_bytes(),
             qa.PRIVATE_DATABASE + "-wal": path.with_name(path.name + "-wal").read_bytes()}
    assert files[qa.PRIVATE_DATABASE + "-wal"]
    hold.close()
    user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
    return schema, master, token, files, user


def _with_card_mission(fixture, tmp_path, *, unknown=True):
    schema, master, token, files, _user = fixture
    evidence = ROOT / "tests/fixtures/official-card-level-mission.v1.json"
    (master / "Mission.json").write_text(json.dumps([
        json.loads(evidence.read_text())["mission_master"]["card_level_achievement"]]))
    (master / "CardLevel.json").write_text(json.dumps([{"level": 1}]))
    path = tmp_path / "mission.db"
    path.write_bytes(files[qa.PRIVATE_DATABASE])
    if files.get(qa.PRIVATE_DATABASE + "-wal"):
        path.with_name(path.name + "-wal").write_bytes(files[qa.PRIVATE_DATABASE + "-wal"])
    state = State(path)
    assert repair_starter_card_level_mission(state, schema, "sandbox", master)
    def unknown_fields(raw):
        user = schema.response_type("/api.User/Get").FromString(raw)
        user.missions[0].MergeFromString(qa.QA_UNKNOWN_PB)
        other = user.missions.add(missionId="qa-unrelated-mission", currentThreshold=7,
                                  progress=3, statusType=1, lastUpdateTime=222)
        other.MergeFromString(qa.QA_UNKNOWN_PB)
        return user.SerializeToString()
    if unknown:
        state.mutate_snapshot("sandbox", schema.fingerprint, unknown_fields)
    user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return schema, master, token, {qa.PRIVATE_DATABASE: path.read_bytes()}, user


class Device:
    command = ["fixture-adb", "-s", "emulator-5554"]

    def __init__(self, files):
        self.files = files

    def adb(self, *args, **kwargs):
        if args == ("shell", "getprop", "ro.kernel.qemu"):
            return "1\n"
        if args[:3] == ("shell", "pidof", "-s"):
            return ""
        if args[:4] == ("exec-out", "run-as", qa.PACKAGE, "cat"):
            return self.files.get(args[4], b"")
        if args[:5] == ("shell", "run-as", qa.PACKAGE, "rm", "-f"):
            for name in args[5:]:
                self.files.pop(name, None)
            return ""
        raise AssertionError("Unexpected fixture adb command")

    def run(self, command, **kwargs):
        if command[-3:-1] == ["test", "-s"]:
            return SimpleNamespace(returncode=0 if self.files.get(command[-1]) else 1)
        assert command[-2:] == ["dd", "of=" + qa.PRIVATE_DATABASE]
        assert kwargs["capture_output"] is True
        self.files[qa.PRIVATE_DATABASE] = kwargs["input"]
        return SimpleNamespace(returncode=0)


@pytest.mark.parametrize("mission_enabled", (False, True))
def test_both_native_legacy_fixture_cycles_preserve_all_allowed_state(fixture, tmp_path, monkeypatch, mission_enabled):
    if mission_enabled:
        fixture = _with_card_mission(fixture, tmp_path)
    schema, master, token, files, user = fixture
    device = Device(files)
    monkeypatch.setattr(qa, "subprocess", SimpleNamespace(run=device.run))
    home1 = next(row.SerializeToString() for row in user.homePositions if row.homePositionType == 1)
    first_preserved = None
    mission_enabled = (master / "Mission.json").is_file()
    original_missions = [row.SerializeToString() for row in user.missions]
    for legacy_version in ((2, 3) if mission_enabled else (None, 2, 3)):
        legacy_roster = legacy_version is None
        inventory_only = legacy_version == 3
        legacy, preserved = qa.stage_legacy_starter(device, schema, user, master_dir=master,
                                                   legacy_roster=legacy_roster, inventory_only=inventory_only)
        assert len(legacy.characters) == (5 if legacy_roster else 17)
        assert not legacy.cards and not legacy.items and not legacy.deckPositions
        if not inventory_only:
            assert {row.characterId for row in legacy.homePositions} == {"char-ktn"}
        else:
            qa.assert_starter_home_positions(legacy)
        assert next(row.SerializeToString() for row in legacy.homePositions if row.homePositionType == 1) == home1
        if first_preserved is None:
            first_preserved = preserved
        assert preserved == first_preserved
        assert preserved["profile_settings"]  # Nonempty settings are actually covered.
        db_path = tmp_path / ("legacy" + str(legacy_version) + ".db")
        db_path.write_bytes(device.files[qa.PRIVATE_DATABASE])
        state = State(db_path)
        assert state.starter_version("sandbox") == legacy_version
        assert repair_starter_roster(state, schema, "sandbox", master) is legacy_roster
        assert repair_starter_home_positions(state, schema, "sandbox", master) is not inventory_only
        assert repair_starter_inventory(state, schema, "sandbox", master) is True
        assert state.starter_version("sandbox") == 4
        assert repair_starter_card_level_mission(state, schema, "sandbox", master) is mission_enabled
        assert state.starter_version("sandbox") == (5 if mission_enabled else 4)
        assert state.authenticated(token, "sandbox")
        user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
        qa.assert_starter_home_positions(user)
        qa.assert_starter_roster(user)
        qa.assert_initial_inventory(user, master)
        assert [row.SerializeToString() for row in user.missions] == original_missions
        projected = qa._without_initial_inventory(user)
        if legacy_roster:
            projected = qa._legacy_projection(projected)
        if not inventory_only:
            projected = qa._legacy_home_projection(projected)
        assert projected.SerializeToString(deterministic=True) == legacy.SerializeToString(deterministic=True)
        assert user.user.name == "Preserved manager" and user.user.isReviewed
        assert user.totalCount.loginCount == 7 and user.tutorials[0].step == 10
        assert qa.QA_UNKNOWN_PB in user.SerializeToString()
        device.files = {qa.PRIVATE_DATABASE: db_path.read_bytes()}
        qa.verify_upgrade_database(device, first_preserved)
        saved = state.snapshot("sandbox")
        assert not repair_starter_inventory(state, schema, "sandbox", master)
        assert not repair_starter_card_level_mission(state, schema, "sandbox", master)
        assert state.snapshot("sandbox") == saved


def test_quest_qa_checks_catalog_and_does_not_accept_a_fabricated_clear(fixture):
    from idoly_local.quest import Quest
    schema, master, _token, files, user = fixture
    # Open the recovered source DB through State rather than manufacturing responses.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.db"
        path.write_bytes(files[qa.PRIVATE_DATABASE])
        path.with_name("state.db-wal").write_bytes(files[qa.PRIVATE_DATABASE + "-wal"])
        handler = Quest(schema, State(path), "sandbox", master)
        top = schema.response_type("/api.Quest/Top").FromString(handler.handle("/api.Quest/Top", b""))
        main = schema.response_type("/api.Quest/ListMain").FromString(handler.handle("/api.Quest/ListMain", b""))
        assert qa.assert_quest_catalog(top, main, master, user) == "quest-1"
        top.mainAreaGroups[0].areas[0].quests[0].cleared = True
        main.areaGroups[0].areas[0].quests[0].cleared = True
        with pytest.raises(RuntimeError, match="uncleared playable quest"):
            qa.assert_quest_catalog(top, main, master, user)


def test_quest_qa_requires_contest_and_the_snapshot_tutorial_context(fixture):
    from idoly_local.quest import Quest
    import tempfile
    schema, master, _token, files, user = fixture
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.db"
        path.write_bytes(files[qa.PRIVATE_DATABASE])
        path.with_name("state.db-wal").write_bytes(files[qa.PRIVATE_DATABASE + "-wal"])
        state = State(path)
        handler = Quest(schema, state, "sandbox", master)
        def responses():
            return tuple(schema.response_type(method).FromString(handler.handle(method, b""))
                         for method in ("/api.Quest/Top", "/api.Quest/ListMain"))
        top, main = responses()
        top.ClearField("contestArea")
        with pytest.raises(RuntimeError, match="23 real contest quests"):
            qa.assert_quest_catalog(top, main, master, user)
        top, main = responses()
        top.contestArea.quests[0].campaignDropRewardIds.append("fabricated")
        with pytest.raises(RuntimeError, match="23 real contest quests"):
            qa.assert_quest_catalog(top, main, master, user)
        top, main = responses()
        del top.mainAreaGroups[-1]
        del main.areaGroups[-1]
        with pytest.raises(RuntimeError, match="actual bundled main-live catalog"):
            qa.assert_quest_catalog(top, main, master, user)
        def completed(payload):
            snapshot = schema.response_type("/api.User/Get").FromString(payload)
            snapshot.tutorials[0].step = 150
            return snapshot.SerializeToString()
        state.mutate_snapshot("sandbox", schema.fingerprint, completed)
        done = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
        top, main = responses()
        assert qa.assert_quest_catalog(top, main, master, done) == "quest-1"
        assert len(top.mainAreaGroups) == 1 and not qa.tutorial_pending(done)


def _live_assets_response(schema, master, user):
    cards = {row["id"]: row for row in json.loads((master / "Card.json").read_text())}
    response = schema.response_type("/api.Quest/ListAsset")()
    response.commonResponse.SetInParent()
    for position in sorted(user.deckPositions, key=lambda row: row.position):
        response.characterAssets.add(characterId=cards[position.cardId]["characterId"],
                                     costumeId=position.costumeId, hairId=position.hairId)
    return response


def test_live_asset_qa_accepts_five_slot_ordered_owned_appearances(fixture):
    schema, master, _token, _files, user = fixture
    response = _live_assets_response(schema, master, user)
    assert qa.assert_live_assets(response, user, master) == 5


@pytest.mark.parametrize("compatibility", ({}, {"wearableCostumeIds": [], "notWearableCostumeIds": []},
                                           {"notWearableCostumeIds": ["unrelated-costume"]}))
def test_live_asset_qa_accepts_unrestricted_and_nonmatching_blacklist_hair(fixture, compatibility):
    schema, master, _token, _files, user = fixture
    response = _live_assets_response(schema, master, user)
    rows = json.loads((master / "Hair.json").read_text())
    for row in rows:
        if row["id"] == response.characterAssets[0].hairId:
            row.pop("wearableCostumeIds", None)
            row.update(compatibility)
    (master / "Hair.json").write_text(json.dumps(rows))
    assert qa.assert_live_assets(response, user, master) == 5


@pytest.mark.parametrize("changed", ("missing", "duplicate", "wrong_owner", "wrong_costume", "wrong_hair",
                                     "reordered", "state_update", "unowned", "incompatible"))
def test_live_asset_qa_rejects_incomplete_or_unowned_asset_lists(fixture, changed):
    schema, master, _token, _files, user = fixture
    response = _live_assets_response(schema, master, user)
    if changed == "missing":
        del response.characterAssets[-1]
    elif changed == "duplicate":
        response.characterAssets[-1].CopyFrom(response.characterAssets[0])
    elif changed == "wrong_owner":
        response.characterAssets[0].characterId = "unknown-character"
    elif changed == "wrong_costume":
        response.characterAssets[0].costumeId = response.characterAssets[1].costumeId
    elif changed == "wrong_hair":
        response.characterAssets[0].hairId = response.characterAssets[1].hairId
    elif changed == "reordered":
        first = type(response.characterAssets[0])()
        first.CopyFrom(response.characterAssets[0])
        response.characterAssets[0].CopyFrom(response.characterAssets[1])
        response.characterAssets[1].CopyFrom(first)
    elif changed == "state_update":
        response.commonResponse.updatedData.user.name = "Unexpected mutation"
    elif changed == "unowned":
        del user.costumes[:]
    elif changed == "incompatible":
        rows = json.loads((master / "Hair.json").read_text())
        for row in rows:
            if row["id"] == response.characterAssets[0].hairId:
                row["wearableCostumeIds"] = ["unrelated-costume"]
        (master / "Hair.json").write_text(json.dumps(rows))
    with pytest.raises(RuntimeError, match="ListAsset"):
        qa.assert_live_assets(response, user, master)


def _tutorial_case(fixture):
    schema, master, _token, _files, user = fixture
    cards = {row.cardId: row for row in user.cards}
    public_cards = {row["id"]: row for row in json.loads((master / "Card.json").read_text())}
    canonical = schema.response_type("/api.Tutorial/StartQuest")()
    canonical.commonResponse.SetInParent()
    info = canonical.result.userInfos.add(index=1, emblemId="emb-001")
    info.userResult.score = 8813
    for index, position in enumerate(sorted(user.deckPositions, key=lambda row: row.position), 1):
        source = cards[position.cardId]
        card = info.userDeck.cards.add(index=index, cardId=source.cardId,
            displayCharacterId=public_cards[source.cardId]["characterId"],
            displayCostumeId=position.costumeId, displayHairId=position.hairId,
            level=1, rarity=source.rarity, stamina=source.stamina, startStamina=source.stamina,
            vocal=source.vocal, dance=source.dance, visual=source.visual,
            mental=source.mental, technique=source.technique)
        card.skills.add(index=1, skillId=source.skillId1, skillLevel=1)
    extra = next(row for row in user.characters if row.characterId not in qa.PHOTO_CHARACTERS)
    info.userDeck.extraCharacterInfos.add(position=6, characterId=extra.characterId,
        costumeId=extra.liveCostumeId, hairId=extra.liveHairId)
    canonical.result.charts.add(number=1, chartType=1)
    canonical.rankPatterns.add(thresholdScore=6000)
    setting = json.loads((master / "Setting.json").read_text())
    setting[0]["tutorialShortQuestId"] = "qt-tutorial-short"
    (master / "Setting.json").write_text(json.dumps(setting))
    quests = json.loads((master / "Quest.json").read_text())
    for row in quests:
        if row["id"] == "qt-tutorial-short":
            row.update(musicId="music-qa", stageId="stage-qa", musicChartPatternId="chart-qa")
    (master / "Quest.json").write_text(json.dumps(quests))
    skill_rows = json.loads((master / "Skill.json").read_text())
    for row in skill_rows:
        row["levels"][0].update(triggerId="trigger-qa", skillDetails=[{"efficacyId": "efficacy-qa"}])
    for name, rows in {"Music": [{"id": "music-qa"}], "Stage": [{"id": "stage-qa"}],
        "MusicChartPattern": [{"id": "chart-qa", "number": 1, "type": 1}],
        "Emblem": [{"id": "emb-001"}], "Skill": skill_rows,
        "SkillTrigger": [{"id": "trigger-qa"}], "SkillTarget": [{"id": "target-qa"}],
        "SkillEfficacy": [{"id": "efficacy-qa", "skillTargetId": "target-qa"}]}.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    reply = type(canonical)()
    reply.CopyFrom(canonical)
    reply.result.userInfos[0].userId = user.userPublic.publicUserId
    reply.result.userInfos[0].name = user.user.name
    return schema, master, user, canonical, reply


def test_tutorial_qa_compares_complete_record_and_local_display_identity(fixture):
    _schema, master, user, canonical, reply = _tutorial_case(fixture)
    assert qa.assert_tutorial_replay(reply, canonical, user, master, "short") == {
        "tutorial_replay_short_charts": 1, "tutorial_replay_short_score": 8813}
    assets = _live_assets_response(_schema, master, user)
    extra = canonical.result.userInfos[0].userDeck.extraCharacterInfos[0]
    assets.characterAssets.add(characterId=extra.characterId, costumeId=extra.costumeId, hairId=extra.hairId)
    assert qa.assert_live_assets(assets, user, master, replay=canonical) == 6
    del assets.characterAssets[-1]
    with pytest.raises(RuntimeError, match="ListAsset"):
        qa.assert_live_assets(assets, user, master, replay=canonical)


def test_tutorial_qa_permits_master_score_effects_without_an_explicit_target(fixture):
    _schema, master, user, canonical, reply = _tutorial_case(fixture)
    rows = json.loads((master / "SkillEfficacy.json").read_text())
    rows[0]["skillTargetId"] = ""
    (master / "SkillEfficacy.json").write_text(json.dumps(rows))
    assert qa.assert_tutorial_replay(reply, canonical, user, master, "short")["tutorial_replay_short_score"] == 8813


@pytest.mark.parametrize("changed", ("identity", "detail", "detail-available", "numeric", "timeline", "rank", "state-update"))
def test_tutorial_qa_rejects_changes_outside_local_display_identity(fixture, changed):
    _schema, master, user, canonical, reply = _tutorial_case(fixture)
    if changed == "identity":
        reply.result.userInfos[0].userId = "remote-capture-id"
    elif changed == "detail":
        reply.result.detailLogId = "remote-detail-log"
    elif changed == "detail-available":
        reply.result.isDisplayDetailAvailable = True
    elif changed == "numeric":
        reply.result.userInfos[0].userDeck.cards[0].stamina += 1
    elif changed == "timeline":
        reply.result.charts[0].beats.add(cardIndex=1, score=1)
    elif changed == "rank":
        reply.rankPatterns[0].thresholdScore += 1
    else:
        reply.commonResponse.updatedData.user.name = "mutated"
    with pytest.raises(RuntimeError, match="Tutorial reply differs"):
        qa.assert_tutorial_replay(reply, canonical, user, master, "short")


@pytest.mark.parametrize("table,field", (("CardParameter", "value"), ("MusicChartPattern", "type"),
                                        ("SkillTarget", "id"), ("Stage", "id")))
def test_tutorial_qa_rejects_mismatched_public_parameters_and_references(fixture, table, field):
    _schema, master, user, canonical, reply = _tutorial_case(fixture)
    rows = json.loads((master / (table + ".json")).read_text())
    for row in rows:
        row[field] = str(int(row[field]) + 10) if table == "CardParameter" else (
            row[field] + 1 if isinstance(row[field], int) else "unresolved-master-id")
    (master / (table + ".json")).write_text(json.dumps(rows))
    with pytest.raises(RuntimeError, match="Tutorial replay"):
        qa.assert_tutorial_replay(reply, canonical, user, master, "short")


def test_new_payload_historical_unmarked_fixture_allows_only_the_new_supported_mission(
        fixture, tmp_path, monkeypatch):
    schema, master, token, files, user = _with_card_mission(fixture, tmp_path, unknown=False)
    device = Device(files)
    monkeypatch.setattr(qa, "subprocess", SimpleNamespace(run=device.run))
    legacy, preserved = qa.stage_legacy_starter(device, schema, user, master_dir=master)
    assert not legacy.missions
    path = tmp_path / "unmarked.db"
    path.write_bytes(device.files[qa.PRIVATE_DATABASE])
    state = State(path)
    assert repair_starter_roster(state, schema, "sandbox", master)
    assert repair_starter_home_positions(state, schema, "sandbox", master)
    assert repair_starter_inventory(state, schema, "sandbox", master)
    assert state.starter_version("sandbox") == 4
    assert repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert state.starter_version("sandbox") == 5 and state.authenticated(token, "sandbox")
    restored = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
    assert len(restored.missions) == 1
    row = restored.missions[0]
    assert (row.missionId, row.progress, row.currentThreshold, row.statusType) == (
        "ms-normal-card_level_achievement", 1, 5, 1)
    projected = qa.starter_mission_projection(restored, legacy, master)
    assert not projected.missions
    projected = qa._legacy_home_projection(qa._legacy_projection(qa._without_initial_inventory(projected)))
    assert projected.SerializeToString(deterministic=True) == legacy.SerializeToString(deterministic=True)
    device.files = {qa.PRIVATE_DATABASE: path.read_bytes()}
    qa.verify_upgrade_database(device, preserved)
    for name, value in (("progress", 2), ("currentThreshold", 10), ("statusType", 2), ("lastUpdateTime", 0)):
        changed = type(restored)()
        changed.CopyFrom(restored)
        setattr(changed.missions[0], name, value)
        with pytest.raises(RuntimeError, match="unsupported mission delta"):
            qa.starter_mission_projection(changed, legacy, master)
    changed = type(restored)()
    changed.CopyFrom(restored)
    changed.missions[0].MergeFromString(qa.QA_UNKNOWN_PB)
    with pytest.raises(RuntimeError, match="unsupported mission delta"):
        qa.starter_mission_projection(changed, legacy, master)
    changed.missions.add(missionId="unexpected-extra")
    with pytest.raises(RuntimeError, match="existing or unrelated missions"):
        qa.starter_mission_projection(changed, legacy, master)


@pytest.mark.parametrize("marker", (4, 6))
def test_mission_ready_qa_requires_exact_marker_five(fixture, tmp_path, monkeypatch, marker):
    schema, master, _token, files, _user = _with_card_mission(fixture, tmp_path)
    path = tmp_path / "wrong-marker.db"
    path.write_bytes(files[qa.PRIVATE_DATABASE])
    with sqlite3.connect(path) as db:
        preserved = qa._preserved_tables(db)
        db.execute("UPDATE starter_profiles SET version=?", (marker,))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    device = Device({qa.PRIVATE_DATABASE: path.read_bytes()})
    qa.bind_starter_contract(device, schema, master)
    monkeypatch.setattr(qa, "subprocess", SimpleNamespace(run=device.run))
    with pytest.raises(RuntimeError, match="migration marker"):
        qa.verify_upgrade_database(device, preserved)


def test_mission_projection_never_ignores_changed_existing_or_unrelated_rows(fixture, tmp_path):
    schema, master, _token, _files, user = _with_card_mission(fixture, tmp_path)
    identical = qa.starter_mission_projection(user, user, master)
    assert identical.SerializeToString() == user.SerializeToString()
    for index in (0, 1):
        changed = type(user)()
        changed.CopyFrom(user)
        changed.missions[index].lastUpdateTime += 1
        with pytest.raises(RuntimeError, match="existing or unrelated missions"):
            qa.starter_mission_projection(changed, user, master)


@pytest.mark.parametrize("change", ("unknown", "progress"))
def test_unmarked_fixture_never_strips_nonfresh_supported_mission_data(
        fixture, tmp_path, monkeypatch, change):
    schema, master, _token, files, _user = _with_card_mission(fixture, tmp_path, unknown=False)
    path = tmp_path / "nonfresh.db"
    path.write_bytes(files[qa.PRIVATE_DATABASE])
    state = State(path)
    def alter(raw):
        user = schema.response_type("/api.User/Get").FromString(raw)
        if change == "unknown":
            user.missions[0].MergeFromString(qa.QA_UNKNOWN_PB)
        else:
            user.missions[0].progress = 6
            user.missions[0].statusType = 2
        return user.SerializeToString()
    state.mutate_snapshot("sandbox", schema.fingerprint, alter)
    user = schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    original = {qa.PRIVATE_DATABASE: path.read_bytes()}
    device = Device(dict(original))
    monkeypatch.setattr(qa, "subprocess", SimpleNamespace(run=device.run))
    with pytest.raises(RuntimeError, match="unsupported mission delta"):
        qa.stage_legacy_starter(device, schema, user, master_dir=master)
    assert device.files == original
