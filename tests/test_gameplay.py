from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.gameplay import Gameplay, seed_starter_profile
from idoly_local.profiles import new_profile
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


def synthetic_schema(path):
    """Independent small test contract keeps core tests runnable in fresh clones."""
    file = descriptor_pb2.FileDescriptorProto(name="gameplay-test.proto", package="api", syntax="proto3")
    for name, values in {"TutorialType": [0, 1, 2, 23], "HomePositionType": [0, 1, 2, 3, 4],
                         "DeckEditType": [0, 1, 2, 3, 4]}.items():
        enum = file.enum_type.add(name=name)
        for value in values:
            enum.value.add(name=name + str(value), number=value)

    def message(name, fields):
        result = file.message_type.add(name=name)
        for number, (field_name, kind, repeated) in enumerate(fields, 1):
            field = result.field.add(name=field_name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type = 14 if kind in ("TutorialType", "HomePositionType", "DeckEditType") else 11
                field.type_name = ".api." + kind
        return result

    def fields(*items):
        return [(name, kind, False) for name, kind in items]

    message("Empty", [])
    message("Manager", fields(("name", 9), ("managerLevel", 5), ("gameStartTime", 3),
                              ("lastLoginTime", 3), ("deckSequence", 3), ("isReviewed", 8), ("tutorialClearedTime", 3)))
    message("Public", fields(("serverUserId", 9), ("publicUserId", 9)))
    message("TotalCount", fields(("loginCount", 3)))
    message("Profile", [("favoriteCharacterIds", 9, True)])
    message("Character", fields(("characterId", 9), ("favoriteCostumeId", 9), ("liveCostumeId", 9),
                                ("favoriteHairId", 9), ("liveHairId", 9), ("activityLevel", 5),
                                ("activityStamina", 5), ("staminaUpdatedTime", 3)))
    message("Costume", fields(("costumeId", 9), ("checked", 8), ("obtainedTime", 3)))
    message("Hair", fields(("hairId", 9), ("checked", 8)))
    message("Card", fields(("cardId", 9), ("photoEquipableCount", 5)))
    message("LocalDeck", fields(("number", 5), ("name", 9)))
    position_fields = fields(("position", 5), ("cardId", 9), ("part1AccessoryId", 9),
                             ("part2AccessoryId", 9), ("costumeId", 9), ("hairId", 9)) + [("photoIds", 9, True)]
    message("DeckPosition", fields(("number", 5)) + position_fields)
    message("RequestedDeckPosition", position_fields + fields(("buddyUserId", 9)))
    message("Photo", fields(("photoId", 9)))
    message("Accessory", fields(("accessoryId", 9), ("amount", 3)))
    message("Area", fields(("areaId", 9), ("clearQuestCount", 5), ("lastClearedTime", 3)))
    message("TutorialState", fields(("tutorialType", "TutorialType"), ("step", 3)))
    message("HomePosition", fields(("homePositionType", "HomePositionType"), ("characterId", 9),
                                   ("isCharacterRandom", 8), ("isCostumeRandom", 8)))
    snapshot_fields = fields(("user", "Manager"), ("userPublic", "Public"), ("totalCount", "TotalCount"),
                             ("profile", "Profile"), ("balance", "Empty"))
    snapshot_fields += [(name, kind, True) for name, kind in (
        ("characters", "Character"), ("costumes", "Costume"), ("hairs", "Hair"), ("cards", "Card"),
        ("decks", "LocalDeck"), ("deckPositions", "DeckPosition"), ("photos", "Photo"), ("accessories", "Accessory"),
        ("areas", "Area"), ("tutorials", "TutorialState"), ("homePositions", "HomePosition"))]
    message("UserGetResponse", snapshot_fields)
    message("UpdatedData", snapshot_fields)
    message("DeletedData", [("decks", "LocalDeck", True), ("deckPositions", "DeckPosition", True)])
    message("CommonResponse", fields(("updatedData", "UpdatedData"), ("deletedData", "DeletedData")))
    message("DeckSaveRequest", fields(("number", 5), ("name", 9), ("deckEditType", "DeckEditType"),
                                       ("questId", 9)) + [("userDeckPositions", "RequestedDeckPosition", True)])
    message("DeckDeleteRequest", fields(("number", 5)))
    message("SettingInfo", fields(("soundBgm", 5), ("frameRate", 5), ("nightMode", 8)))
    message("HomeLoginRequest", fields(("settingInfo", "SettingInfo")))
    message("HomeLoginResponse", fields(("paidJpy", "Empty"), ("commonResponse", "CommonResponse")))
    message("HomeEnterRequest", fields(("skipUpdate", 8)))
    message("LessonProgress", fields(("currentAreaId", 9), ("lastReceiveTime", 3), ("maxRewardTime", 3)))
    message("LessonInfo", fields(("lessonProgress", "LessonProgress")))
    home_fields = fields(("currentMainAreaId", 9), ("lessonProgress", "LessonProgress"), ("lessonInfo", "LessonInfo"),
                          ("commonResponse", "CommonResponse"))
    home_fields += fields(*[(name, "Empty") for name in ("fanEventInfo", "promotionInfo", "refreshInfo", "bannerInfo",
                          "eventInfo", "pvpInfo", "hierarchyNotiInfo", "notiStoneShopItem", "notiNormalShopItem",
                          "notiShowcaseShopItem", "leagueInfo", "loveInfo", "companyInfo", "homeFishHeavenInfo", "payslip")])
    message("HomeEnterResponse", home_fields)
    message("ActionResponse", fields(("commonResponse", "CommonResponse")))
    message("CharacterPosition", fields(("type", "HomePositionType"), ("characterId", 9),
                                        ("isCharacterRandom", 8), ("isCostumeRandom", 8)))
    message("PositionRequest", [("positions", "CharacterPosition", True)])
    message("InitRequest", fields(("name", 9)))
    message("ProgressRequest", fields(("type", "TutorialType"), ("step", 5)))
    message("VersionRequest", fields(("token1", 9), ("token2", 9)))
    message("VersionResponse", fields(("version", 9)))
    message("DokanResponse", [("dokanInfos", "Empty", True), ("isNeedReCall", 8, False), ("commonResponse", "CommonResponse", False)])
    message("NoticeResponse", [("notices", "Empty", True), ("malfunctionNotices", "Empty", True),
                               ("prNotices", "Empty", True), ("noticeHasNext", 8, False),
                               ("commonResponse", "CommonResponse", False)])
    routes = {
        "System": [("Check", "Empty", "Empty")], "User": [("Get", "Empty", "UserGetResponse")],
        "Home": [("Login", "HomeLoginRequest", "HomeLoginResponse"), ("Enter", "HomeEnterRequest", "HomeEnterResponse"),
                 ("SetReview", "Empty", "ActionResponse"), ("SetCharacterPosition", "PositionRequest", "ActionResponse")],
        "Tutorial": [("Init", "InitRequest", "ActionResponse"), ("Progress", "ProgressRequest", "ActionResponse"),
                     ("Skip", "Empty", "ActionResponse")],
        "Master": [("GetVersion", "VersionRequest", "VersionResponse")],
        "Dokan": [("List", "Empty", "DokanResponse")], "Notice": [("List", "Empty", "NoticeResponse")],
        "Deck": [("Save", "DeckSaveRequest", "ActionResponse"), ("Delete", "DeckDeleteRequest", "ActionResponse")],
    }
    for name, methods in routes.items():
        service = file.service.add(name=name)
        for name, request, response in methods:
            service.method.add(name=name, input_type=".api." + request, output_type=".api." + response)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("synthetic", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "synthetic":
        return synthetic_schema(tmp_path_factory.mktemp("gameplay-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def master_dir(tmp_path):
    directory = tmp_path / "master"
    directory.mkdir()
    rows = {
        "Setting": [{"id": 1, "tutorialPhotoShootingCharacterIds": ["char-a", "char-b"]}],
        "Character": [{"id": "char-" + key, "defaultCostumeId": "costume-" + key,
                       "defaultLiveCostumeId": "costume-" + key} for key in ("a", "b")],
        "Costume": [{"id": "costume-" + key, "characterId": "char-" + key, "defaultHairId": "hair-" + key}
                    for key in ("a", "b")],
        "Hair": [{"id": "hair-" + key, "characterId": "char-" + key} for key in ("a", "b")],
        "Area": [{"id": "area-main-001", "type": 1, "order": 1, "questIds": ["quest-1"]},
                 {"id": "area-main-002", "type": 1, "order": 2, "questIds": ["quest-2"]},
                 {"id": "contest", "type": 2, "order": 999, "questIds": []}],
        "Quest": [{"id": "quest-1", "areaId": "area-main-001"}, {"id": "quest-2", "areaId": "area-main-002"}],
        "CharacterActivityLevel": [{"level": 1, "maxStamina": 800}],
        "Tutorial": [{"type": 1, "stepInfo": [{"step": step} for step in (10, 100, 110, 120, 130, 140, 150)]},
                     {"type": 2, "stepInfo": [{"step": 1}]}],
        "Card": [{"id": "card-" + key, "characterId": "char-" + key} for key in ("a", "b")],
        "Accessory": [{"id": "ac-a", "categoryType": 1}, {"id": "ac-b", "categoryType": 2}],
    }
    for name, value in rows.items():
        (directory / (name + ".json")).write_text(json.dumps(value))
    (directory / "!version.txt").write_text("fixture-master-v1\n")
    return directory


@pytest.fixture
def game(tmp_path, schema, master_dir):
    state = State(tmp_path / "state.db")
    seed_starter_profile(state, schema, "sandbox", master_dir, manager_name="Local manager")
    return Gameplay(schema, state, "sandbox", master_dir)


def call(game, path, **values):
    request = game.schema.request_type(path)(**values)
    payload = game.handle(path, request.SerializeToString())
    assert payload is not None
    return game.schema.response_type(path).FromString(payload)


def snapshot(game):
    return game.schema.response_type("/api.User/Get").FromString(game.state.snapshot(game.profile)[0])


def prepare_deck_inventory(game):
    def update(payload):
        user = game.schema.response_type("/api.User/Get").FromString(payload)
        for key in ("a", "b"):
            user.cards.add(cardId="card-" + key, photoEquipableCount=1)
            user.photos.add(photoId="photo-" + key)
            user.accessories.add(accessoryId="ac-" + key, amount=1)
        user.decks.add(number=2, name="untouched")
        return user.SerializeToString()
    game.state.mutate_snapshot(game.profile, game.schema.fingerprint, update)


def test_deck_save_persists_owned_references_and_reports_removed_positions(game):
    prepare_deck_inventory(game)
    token, _ = game.state.login(game.profile)
    response = call(game, "/api.Deck/Save", number=1, name="saved", deckEditType=1, questId="quest-1",
                    userDeckPositions=[{"position": 1, "cardId": "card-a", "costumeId": "costume-a", "hairId": "hair-a",
                                        "photoIds": ["photo-a"], "part1AccessoryId": "ac-a", "part2AccessoryId": "ac-b"},
                                       {"position": 2, "cardId": "card-b"}])
    assert next(row.name for row in response.commonResponse.updatedData.decks if row.number == 1) == "saved"
    assert len(snapshot(game).deckPositions) == 2
    assert snapshot(game).deckPositions[0].photoIds == ["photo-a"]
    assert game.state.authenticated(token, game.profile)
    assert State(game.state.path).snapshot(game.profile) == game.state.snapshot(game.profile)
    response = call(game, "/api.Deck/Save", number=1, name="trimmed", deckEditType=1,
                    userDeckPositions=[{"position": 1, "cardId": "card-a"}])
    assert [(row.number, row.position) for row in response.commonResponse.deletedData.deckPositions] == [(1, 2)]
    assert not snapshot(game).deckPositions[0].photoIds
    assert next(row.name for row in snapshot(game).decks if row.number == 2) == "untouched"


@pytest.mark.parametrize("position", [
    {"position": -1, "cardId": "card-a"},
    {"position": 1, "cardId": "missing"},
    {"position": 1, "cardId": "card-a", "costumeId": "costume-b"},
    {"position": 1, "cardId": "card-a", "hairId": "hair-b"},
    {"position": 1, "cardId": "card-a", "part1AccessoryId": "ac-b"},
    {"position": 1, "cardId": "card-a", "part1AccessoryId": "unowned"},
    {"position": 1, "cardId": "card-a", "photoIds": ["missing"]},
    {"position": 1, "cardId": "card-a", "photoIds": ["photo-a", "photo-b"]},
])
def test_deck_invalid_reference_rolls_back_entire_snapshot(game, position):
    prepare_deck_inventory(game)
    before = game.state.snapshot(game.profile)
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Deck/Save", number=1, name="must not persist", deckEditType=1,
             userDeckPositions=[position])
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game.state.snapshot(game.profile) == before


def test_deck_unsupported_modes_buddies_and_creation_preserve_state(game):
    prepare_deck_inventory(game)
    before = game.state.snapshot(game.profile)
    for values in ({"number": 1, "deckEditType": 2}, {"number": 3, "deckEditType": 1},
                   {"number": 1, "deckEditType": 1, "userDeckPositions": [{"position": 1, "buddyUserId": "other"}]}):
        with pytest.raises(RpcFailure) as error:
            call(game, "/api.Deck/Save", **values)
        assert error.value.code == RpcCode.UNIMPLEMENTED
        assert game.state.snapshot(game.profile) == before


@pytest.mark.parametrize("positions", [
    [{"position": 1, "cardId": "card-a"}, {"position": 1, "cardId": "card-b"}],
    [{"position": 1, "cardId": "card-a"}, {"position": 2, "cardId": "card-a"}],
    [{"position": 1, "cardId": "card-a", "photoIds": ["photo-a"]},
     {"position": 2, "cardId": "card-b", "photoIds": ["photo-a"]}],
    [{"position": 1, "cardId": "card-a", "part1AccessoryId": "ac-a"},
     {"position": 2, "cardId": "card-b", "part1AccessoryId": "ac-a"}],
    [{"position": 0, "cardId": "card-a"}], [{"position": 6, "cardId": "card-a"}],
])
def test_deck_duplicate_inventory_and_out_of_range_slots_rollback(game, positions):
    prepare_deck_inventory(game)
    before = game.state.snapshot(game.profile)
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Deck/Save", number=1, deckEditType=1, userDeckPositions=positions)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game.state.snapshot(game.profile) == before


def test_deck_delete_reports_deleted_data_and_preserves_other_deck(game):
    prepare_deck_inventory(game)
    call(game, "/api.Deck/Save", number=1, name="first", deckEditType=1,
         userDeckPositions=[{"position": 1, "cardId": "card-a"}])
    response = call(game, "/api.Deck/Delete", number=1)
    assert [row.number for row in response.commonResponse.deletedData.decks] == [1]
    assert [(row.number, row.position) for row in response.commonResponse.deletedData.deckPositions] == [(1, 1)]
    assert [row.number for row in snapshot(game).decks] == [2]
    assert not snapshot(game).deckPositions
    before = game.state.snapshot(game.profile)
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Deck/Delete", number=1)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game.state.snapshot(game.profile) == before


def test_starter_is_master_backed_new_only_and_persists_identity(game):
    user = snapshot(game)
    assert user.user.name == "Local manager"
    assert user.user.managerLevel == 1
    assert user.user.gameStartTime > 1000000000000
    assert {row.characterId for row in user.characters} == {"char-a", "char-b"}
    assert {row.costumeId for row in user.costumes} == {"costume-a", "costume-b"}
    assert {row.hairId for row in user.hairs} == {"hair-a", "hair-b"}
    assert all(row.activityStamina == 800 for row in user.characters)
    assert all(row.characterId == "char-a" for row in user.homePositions)
    assert not user.cards
    assert user.tutorials[0].step == 0
    before = game.state.snapshot(game.profile)
    identity = game.state.profile(game.profile)
    token, _ = game.state.login(game.profile)
    with pytest.raises(RpcFailure) as error:
        seed_starter_profile(game.state, game.schema, game.profile, game.catalog.directory)
    assert error.value.code == RpcCode.ALREADY_EXISTS
    assert game.state.snapshot(game.profile) == before
    assert game.state.profile(game.profile) == identity
    assert game.state.authenticated(token, game.profile)
    assert State(game.state.path).snapshot(game.profile) == before


@pytest.mark.parametrize("table,key,value", [("Costume", "characterId", "wrong-owner"),
                                            ("Hair", "characterId", "wrong-owner"),
                                            ("Quest", "areaId", "wrong-area")])
def test_invalid_starter_references_never_leave_a_partial_profile(tmp_path, schema, master_dir, table, key, value):
    path = master_dir / (table + ".json")
    rows = json.loads(path.read_text())
    rows[0][key] = value
    path.write_text(json.dumps(rows))
    state = State(tmp_path / "state.db")
    with pytest.raises(RpcFailure) as error:
        seed_starter_profile(state, schema, "new", master_dir)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert state.snapshot("new") is None
    assert state.profile("new") is None


def test_login_saves_settings_atomically_counts_jst_days_and_preserves_unknown_fields(game, monkeypatch):
    sentinel = b"\x80\x4b\x7b"  # Unknown field 1200 survives normal gameplay writes.
    before, fingerprint = game.state.snapshot(game.profile)
    game.state.save_snapshot(game.profile, before + sentinel, fingerprint)
    token, _ = game.state.login(game.profile)
    instant = int(datetime(2026, 11, 9, 14, 59, tzinfo=timezone.utc).timestamp() * 1000)
    monkeypatch.setattr("idoly_local.gameplay._now_ms", lambda: instant)
    response = call(game, "/api.Home/Login", settingInfo={"soundBgm": 50, "frameRate": 60, "nightMode": True})
    assert response.commonResponse.updatedData.user.lastLoginTime == instant
    assert snapshot(game).totalCount.loginCount == 1
    setting = game.schema.request_type("/api.Home/Login")().settingInfo
    saved, saved_fingerprint = State(game.state.path).settings(game.profile)
    setting.ParseFromString(saved)
    assert setting.soundBgm == 50
    assert setting.frameRate == 60
    assert saved_fingerprint == game.schema.fingerprint
    call(game, "/api.Home/Login")
    assert snapshot(game).totalCount.loginCount == 1
    assert game.state.settings(game.profile)[0] == saved
    instant += 60000  # 15:00 UTC crosses midnight JST while UTC date stays equal.
    call(game, "/api.Home/Login")
    assert snapshot(game).totalCount.loginCount == 2
    assert game.state.snapshot(game.profile)[0].endswith(sentinel)
    assert game.state.authenticated(token, game.profile)


def test_parallel_game_actions_do_not_lose_other_snapshot_changes(game):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, game, "/api.Home/SetReview"),
                   pool.submit(call, game, "/api.Tutorial/Progress", type=1, step=100)]
        for result in futures:
            result.result()
    user = snapshot(game)
    assert user.user.isReviewed
    assert next(row.step for row in user.tutorials if row.tutorialType == 1) == 100


def test_home_enter_uses_main_area_and_present_containers_without_rewards_or_mutation(game):
    before = game.state.snapshot(game.profile)
    response = call(game, "/api.Home/Enter", skipUpdate=True)
    assert response.currentMainAreaId == "area-main-001"
    assert response.lessonProgress.currentAreaId == "area-main-001"
    assert response.lessonInfo.lessonProgress == response.lessonProgress
    for name in ("fanEventInfo", "promotionInfo", "refreshInfo", "bannerInfo", "eventInfo"):
        assert response.HasField(name)
    assert not response.HasField("payslip")
    assert game.state.snapshot(game.profile) == before
    def completed(payload):
        user = game.schema.response_type("/api.User/Get").FromString(payload)
        user.areas[0].clearQuestCount = 1
        return user.SerializeToString()
    game.state.mutate_snapshot(game.profile, game.schema.fingerprint, completed)
    assert call(game, "/api.Home/Enter").currentMainAreaId == "area-main-002"


def test_explicit_empty_local_catalogs_and_master_version(game):
    assert not call(game, "/api.Dokan/List").dokanInfos
    notices = call(game, "/api.Notice/List")
    assert not notices.notices and not notices.malfunctionNotices and not notices.prNotices
    assert not notices.noticeHasNext
    assert call(game, "/api.Master/GetVersion", token1="local", token2="local").version == "fixture-master-v1"


def test_character_positions_validate_ownership_and_rollback_whole_request(game):
    response = call(game, "/api.Home/SetCharacterPosition", positions=[{"type": 1, "characterId": "char-b"}])
    assert next(row.characterId for row in response.commonResponse.updatedData.homePositions if row.homePositionType == 1) == "char-b"
    before = game.state.snapshot(game.profile)
    for positions in ([{"type": 1, "characterId": "char-a"}, {"type": 2, "characterId": "unowned"}],
                      [{"type": 1, "characterId": "char-a"}, {"type": 1, "characterId": "char-b"}],
                      [{"type": 0, "characterId": "char-a"}]):
        with pytest.raises(RpcFailure) as error:
            call(game, "/api.Home/SetCharacterPosition", positions=positions)
        assert error.value.code == RpcCode.INVALID_ARGUMENT
        assert game.state.snapshot(game.profile) == before


def test_tutorial_name_monotonic_progress_and_skip_only_change_main_tutorial(game):
    call(game, "/api.Tutorial/Init", name="새 이름")
    assert snapshot(game).user.name == "새 이름"
    call(game, "/api.Tutorial/Progress", type=2, step=1)
    call(game, "/api.Tutorial/Progress", type=1, step=110)
    call(game, "/api.Tutorial/Progress", type=1, step=100)
    assert next(row.step for row in snapshot(game).tutorials if row.tutorialType == 1) == 110
    before_cards = list(snapshot(game).cards)
    result = call(game, "/api.Tutorial/Skip")
    tutorials = {row.tutorialType: row.step for row in result.commonResponse.updatedData.tutorials}
    assert tutorials == {1: 150, 2: 1}
    assert result.commonResponse.updatedData.user.tutorialClearedTime > 1000000000000
    assert list(snapshot(game).cards) == before_cards
    assert not snapshot(game).user.tutorialClearedTime == 0


@pytest.mark.parametrize("values", [{"type": 0, "step": 1}, {"type": 999, "step": 1},
                                    {"type": 1, "step": -1}, {"type": 1, "step": 42}])
def test_invalid_tutorial_progress_does_not_modify_snapshot(game, values):
    before = game.state.snapshot(game.profile)
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Tutorial/Progress", **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game.state.snapshot(game.profile) == before


def test_malformed_request_schema_mismatch_and_unsupported_battle_fail_explicitly(game):
    with pytest.raises(RpcFailure) as error:
        game.handle("/api.Tutorial/Init", b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    before = game.state.snapshot(game.profile)
    assert game.handle("/api.Tutorial/StartQuest", b"") is None
    assert game.handle("/api.Quest/Start", b"") is None
    assert game.state.snapshot(game.profile) == before
    payload, _ = before
    game.state.save_snapshot(game.profile, payload, "different-schema")
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Home/SetReview")
    assert error.value.code == RpcCode.FAILED_PRECONDITION


def test_missing_home_catalog_is_explicit_for_minimal_profile(tmp_path, schema):
    state = State(tmp_path / "state.db")
    new_profile(state, schema, "minimal", "Minimal")
    game = Gameplay(schema, state, "minimal")
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Home/Enter")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    # Imported UserArea order cannot identify whether an area is main/daily/
    # contest; an arbitrary first row must not become currentMainAreaId.
    def with_contest(payload):
        user = schema.response_type("/api.User/Get").FromString(payload)
        user.areas.add(areaId="contest")
        return user.SerializeToString()
    state.mutate_snapshot("minimal", schema.fingerprint, with_contest)
    with pytest.raises(RpcFailure) as error:
        call(game, "/api.Home/Enter")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert game.handle("/api.Master/GetVersion", b"") is None


def test_real_master_references_when_local_sources_are_available(tmp_path, schema):
    directory = Path("/workspace/ipr-master-diff")
    if not directory.is_dir():
        pytest.skip("Optional public master checkout is unavailable")
    state = State(tmp_path / "state.db")
    payload = seed_starter_profile(state, schema, "actual-master", directory)
    user = schema.response_type("/api.User/Get").FromString(payload)
    assert len(user.characters) == 5
    costumes = {row["id"]: row for row in json.loads((directory / "Costume.json").read_text())}
    hairs = {row["id"]: row for row in json.loads((directory / "Hair.json").read_text())}
    for character in user.characters:
        assert costumes[character.favoriteCostumeId]["characterId"] == character.characterId
        assert hairs[character.favoriteHairId]["characterId"] == character.characterId
    response = call(Gameplay(schema, state, "actual-master", directory), "/api.Home/Enter")
    assert response.currentMainAreaId == "area-main-001"
