"""Local public profile lookup and one-time birthday registration contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import json

from google.protobuf import descriptor_pb2
import grpc
import pytest

from idoly_local.catalog import import_response
from idoly_local.gameplay import _Catalog
from idoly_local.profile_directory import ProfileDirectory
from idoly_local.profile_names import ProfileNames
from idoly_local.profile_preferences import ProfilePreferences
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, UNKNOWN, dump, game, protected, small_schema as name_schema
from test_profile_preferences import connected


FIND = "/api.Profile/FindUser"
BIRTHDAY = "/api.Profile/UpdateBirthday"


def small_schema(path):
    name_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    def add(message, fields):
        for name, number, kind in fields:
            if name not in {field.name for field in message.field}:
                message.field.add(name=name, number=number, label=1, type=kind)
    manager = next(m for m in file.message_type if m.name == "Manager")
    add(manager, (("managerExp", 100, 3), ("divisionId", 101, 9), ("guildId", 102, 9), ("emblemId", 103, 9)))
    profile = next(m for m in file.message_type if m.name == "SavedProfile")
    add(profile, (("favoriteCardId", 2, 9), ("favoritePhotoId", 3, 9), ("message", 4, 9),
        ("birthMonth", 5, 3), ("birthDay", 6, 3), ("backgroundType", 7, 5), ("layoutType", 8, 5),
        ("decorationId", 10, 9), ("informationType", 11, 5), ("colorType", 12, 5),
        ("favoriteCardDisplayType", 13, 5)))
    photo = next(m for m in file.message_type if m.name == "Photo")
    add(photo, (("assetId", 2, 9), ("imageType", 3, 5)))
    card_info = file.message_type.add(name="FavoriteCardInfo")
    add(card_info, (("cardId", 1, 9), ("rarity", 2, 5), ("displayType", 3, 5), ("evolutionLevel", 4, 5)))
    photo_info = file.message_type.add(name="FavoritePhotoInfo")
    add(photo_info, (("photoId", 1, 9), ("assetId", 2, 9), ("imageType", 3, 5)))
    request = file.message_type.add(name="ProfileFindUserRequest")
    add(request, (("userId", 1, 9),))
    response = file.message_type.add(name="ProfileFindUserResponse")
    add(response, (("userId", 1, 9), ("name", 2, 9), ("managerExp", 3, 3), ("managerLevel", 4, 5),
        ("divisionId", 5, 9), ("guildId", 6, 9), ("emblemId", 7, 9), ("message", 11, 9),
        ("birthMonth", 12, 5), ("birthDay", 13, 5), ("backgroundType", 14, 5), ("layoutType", 15, 5),
        ("hierarchyCurrentDetailGradeId", 16, 9), ("hierarchyCurrentRank", 17, 5),
        ("decorationId", 18, 9), ("informationType", 19, 5), ("colorType", 20, 5)))
    response.field.add(name="favoriteCharacterIds", number=10, label=3, type=9)
    for name, number, type_name in (("favoriteCard", 8, "FavoriteCardInfo"),
                                   ("favoritePhoto", 9, "FavoritePhotoInfo"), ("commonResponse", 9999, "CommonResponse")):
        response.field.add(name=name, number=number, label=1, type=11, type_name=".api."+type_name)
    request = file.message_type.add(name="ProfileUpdateBirthdayRequest")
    add(request, (("month", 1, 5), ("day", 2, 5)))
    response = file.message_type.add(name="ProfileUpdateBirthdayResponse")
    for name, number, type_name in (("birthdayAdvInfo", 1, "Empty"), ("birthdayRemindInfo", 2, "Empty"),
                                   ("commonResponse", 9999, "CommonResponse")):
        response.field.add(name=name, number=number, label=1, type=11, type_name=".api."+type_name)
    service = next(service for service in file.service if service.name == "Profile")
    for name in ("FindUser", "UpdateBirthday"):
        service.method.add(name=name, input_type=".api.Profile"+name+"Request", output_type=".api.Profile"+name+"Response")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-directory-schema")/"schema.pb")
    source = Path(__file__).resolve().parents[1]/"data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Recovered original 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def directory(game, tmp_path):
    schema, state = game[0].schema, game[1]
    master = tmp_path/"master"; master.mkdir()
    tables = {
        "Card": [{"id": "kept-card", "initialRarity": 5}],
        "CardImage": [{"cardId": "kept-card", "displayType": 2, "imageType": 2}],
        "HierarchyGrade": [{"id": "grade-low"}, {"id": "grade-high"}],
        "HierarchyDetailGrade": [
            {"id": "detail-low", "hierarchyGradeId": "grade-low", "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0},
            {"id": "detail-high", "hierarchyGradeId": "grade-high", "requiredHierarchyPoint": "100", "requiredHierarchyRank": 0}],
    }
    for table, rows in tables.items():
        (master/(table+".json")).write_text(json.dumps(rows))
    def prepare(raw):
        value = schema.response_type(USER).FromString(raw)
        value.user.managerExp = 1234
        value.user.divisionId, value.user.guildId, value.user.emblemId = "kept-division", "kept-guild", "kept-emblem"
        value.profile.message = "kept introduction"
        value.profile.birthMonth, value.profile.birthDay = 0, 0
        value.profile.backgroundType, value.profile.layoutType = 1, 2
        value.profile.informationType, value.profile.colorType = 3, 4
        value.profile.decorationId = "kept-decoration"
        value.profile.MergeFromString(UNKNOWN)
        value.cards[0].rarity, value.cards[0].displayType = 5, 2
        value.hierarchy.bestDetailGradeId = "detail-low"
        value.hierarchy.currentFixedPoint, value.hierarchy.currentVariablePoint = 60, 40
        value.photos.add(photoId="kept-photo", assetId="kept-photo-asset", imageType=2).MergeFromString(UNKNOWN)
        return value.SerializeToString()
    state.mutate_snapshot("player", schema.fingerprint, prepare)
    return ProfileDirectory(schema, state, "player", _Catalog(master), ProfilePreferences(schema, state, "player", master))


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def call(directory, path, **values):
    raw = directory.schema.request_type(path)(**values).SerializeToString()
    return directory.schema.response_type(path).FromString(directory.handle(path, raw))


def change(game, **values):
    def update(raw):
        value = game[0].schema.response_type(USER).FromString(raw)
        for name, item in values.items():
            target, field = name.split("__")
            setattr(getattr(value, target), field, item)
        return value.SerializeToString()
    game[1].mutate_snapshot("player", game[0].schema.fingerprint, update)


def test_request_and_ack_ABI_matches_original_contract(schema):
    assert [(f.name, f.number, f.type) for f in schema.request_type(BIRTHDAY)().DESCRIPTOR.fields] == [
        ("month", 1, 5), ("day", 2, 5)]
    assert [(f.name, f.number, f.type) for f in schema.request_type(FIND)().DESCRIPTOR.fields] == [("userId", 1, 9)]
    assert schema.response_type(BIRTHDAY)().DESCRIPTOR.fields_by_name["commonResponse"].number == 9999
    assert schema.response_type(FIND)().DESCRIPTOR.fields_by_name["favoriteCard"].number == 8
    profile = schema.response_type(USER)().profile
    assert [(profile.DESCRIPTOR.fields_by_name[n].number, profile.DESCRIPTOR.fields_by_name[n].type)
            for n in ("birthMonth", "birthDay")] == [(5, 3), (6, 3)]


@pytest.mark.parametrize("month,day", ((1, 1), (2, 29), (4, 30), (12, 31)))
def test_initial_birthday_registration_returns_full_profile_and_survives_retry_restart(game, directory, month, day):
    expected, kept = snapshot(game), protected(game[1])
    expected.profile.birthMonth, expected.profile.birthDay = month, day
    result = call(directory, BIRTHDAY, month=month, day=day)
    assert game[1].snapshot("player")[0] == expected.SerializeToString()
    assert result.commonResponse.updatedData.profile == expected.profile
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"profile"}
    assert not result.commonResponse.HasField("deletedData")
    assert not result.HasField("birthdayAdvInfo") and not result.HasField("birthdayRemindInfo")
    assert protected(game[1]) == kept
    before = dump(game[1])
    assert call(directory, BIRTHDAY, month=month, day=day) == result
    restart = ProfileDirectory(directory.schema, State(game[1].path), "player", directory.catalog, directory.preferences)
    assert call(restart, BIRTHDAY, month=month, day=day) == result
    assert dump(game[1]) == before
    assert game[1].authenticated(game[2], "player") and game[1].authenticated(game[3], "other")


@pytest.mark.parametrize("month,day", ((0, 0), (0, 1), (1, 0), (-1, 1), (13, 1), (1, 32), (2, 30), (4, 31), (2147483647, 1)))
def test_invalid_calendar_dates_do_not_write_or_create_rewards(game, directory, month, day):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(directory, BIRTHDAY, month=month, day=day)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


def test_existing_other_birthday_is_retained(game, directory):
    change(game, profile__birthMonth=5, profile__birthDay=6)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(directory, BIRTHDAY, month=2, day=29)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_identical_birthday_preserves_noncanonical_wire_without_snapshot_SQL_update(game, directory, monkeypatch):
    call(directory, BIRTHDAY, month=2, day=29)
    raw = UNKNOWN + game[1].snapshot("player")[0]
    with game[1].connect() as db:
        db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    assert snapshot(game).SerializeToString() != raw
    before, statements, connect = dump(game[1]), [], game[1].connect
    @contextmanager
    def traced():
        with connect() as db:
            db.set_trace_callback(statements.append); yield db
    monkeypatch.setattr(game[1], "connect", traced)
    result = call(directory, BIRTHDAY, month=2, day=29)
    assert result.commonResponse.updatedData.profile == snapshot(game).profile
    assert game[1].snapshot("player")[0] == raw and dump(game[1]) == before
    assert not any(sql.upper().startswith("UPDATE SNAPSHOTS") for sql in statements)


@pytest.mark.parametrize("case", ("missing", "fingerprint", "malformed", "no_user", "no_profile", "invalid_birthday"))
def test_invalid_saved_state_is_not_repaired_by_registration_or_lookup(game, directory, case):
    with game[1].connect() as db:
        if case == "missing": db.execute("DELETE FROM snapshots WHERE profile='player'")
        elif case == "fingerprint": db.execute("UPDATE snapshots SET schema_sha256='other' WHERE profile='player'")
        else:
            value = snapshot(game)
            if case == "malformed": raw = b"\x80"
            else:
                if case == "no_user": value.ClearField("user")
                elif case == "no_profile": value.ClearField("profile")
                else: value.profile.birthMonth, value.profile.birthDay = 4, 31
                raw = value.SerializeToString()
            db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    before = dump(game[1])
    for path, values in ((BIRTHDAY, {"month": 2, "day": 29}), (FIND, {"userId": "selected-id"})):
        with pytest.raises(RpcFailure) as error:
            call(directory, path, **values)
        assert error.value.code == RpcCode.FAILED_PRECONDITION
        assert dump(game[1]) == before


def test_atomic_registration_cannot_overwrite_a_concurrent_registration_or_name(game, directory):
    def register(pair):
        try: return call(directory, BIRTHDAY, month=pair[0], day=pair[1])
        except RpcFailure as error: return error
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(register, pair) for pair in ((1, 2), (3, 4))]
        names = ProfileNames(directory.schema, game[1], "player")
        future = pool.submit(names.handle, "/api.Profile/UpdateName",
                             directory.schema.request_type("/api.Profile/UpdateName")(name="Concurrent").SerializeToString())
        values = [f.result() for f in futures]; future.result()
    assert sum(isinstance(value, RpcFailure) for value in values) == 1
    assert next(value for value in values if isinstance(value, RpcFailure)).code == RpcCode.FAILED_PRECONDITION
    winner = next(value for value in values if not isinstance(value, RpcFailure))
    assert snapshot(game).profile == winner.commonResponse.updatedData.profile
    assert snapshot(game).user.name == "Concurrent"


@pytest.mark.parametrize("alias", ("serverUserId", "publicUserId"))
def test_real_selected_identity_returns_full_saved_profile_without_mutation(game, directory, alias):
    value = snapshot(game); before, kept = dump(game[1]), protected(game[1])
    result = call(directory, FIND, userId=getattr(value.userPublic, alias))
    assert result.userId == value.userPublic.serverUserId
    for field in ("name", "managerExp", "managerLevel", "divisionId", "guildId", "emblemId"):
        assert getattr(result, field) == getattr(value.user, field)
    for field in ("message", "birthMonth", "birthDay", "backgroundType", "layoutType", "decorationId", "informationType", "colorType"):
        assert getattr(result, field) == getattr(value.profile, field)
    assert list(result.favoriteCharacterIds) == list(value.profile.favoriteCharacterIds)
    assert result.hierarchyCurrentDetailGradeId == "detail-high" and result.hierarchyCurrentRank == 0
    assert not result.HasField("favoriteCard") and not result.HasField("favoritePhoto")
    assert result.HasField("commonResponse") and not result.commonResponse.ListFields()
    assert dump(game[1]) == before and protected(game[1]) == kept
    restart = ProfileDirectory(directory.schema, State(game[1].path), "player", directory.catalog, directory.preferences)
    assert call(restart, FIND, userId=getattr(value.userPublic, alias)) == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("card,photo", ((True, False), (False, True), (True, True)))
def test_favorite_card_and_photo_use_owned_saved_image_references(game, directory, card, photo):
    change(game, profile__favoriteCardId="kept-card" if card else "", profile__favoriteCardDisplayType=2 if card else 0,
           profile__favoritePhotoId="kept-photo" if photo else "")
    value = snapshot(game); before = dump(game[1])
    result = call(directory, FIND, userId=value.userPublic.publicUserId)
    assert result.HasField("favoriteCard") == card and result.HasField("favoritePhoto") == photo
    if card:
        assert (result.favoriteCard.cardId, result.favoriteCard.rarity, result.favoriteCard.displayType,
                result.favoriteCard.evolutionLevel) == ("kept-card", 5, 2, 0)
    if photo:
        assert (result.favoritePhoto.photoId, result.favoritePhoto.assetId, result.favoritePhoto.imageType) == ("kept-photo", "kept-photo-asset", 2)
    assert dump(game[1]) == before


@pytest.mark.parametrize("case", ("card_not_owned", "card_image", "photo_not_owned", "photo_duplicate", "photo_no_asset", "photo_unknown_type", "hierarchy_master"))
def test_broken_saved_media_or_hierarchy_is_reported_without_substituting_an_empty_profile(game, directory, case):
    change(game, profile__favoriteCardId="kept-card", profile__favoriteCardDisplayType=2, profile__favoritePhotoId="kept-photo")
    if case == "card_not_owned": change(game, profile__favoriteCardId="another-card")
    elif case == "card_image": (directory.catalog.directory/"CardImage.json").write_text("[]")
    elif case == "photo_not_owned": change(game, profile__favoritePhotoId="another-photo")
    elif case == "hierarchy_master": (directory.catalog.directory/"HierarchyGrade.json").unlink()
    else:
        def break_photo(raw):
            value = directory.schema.response_type(USER).FromString(raw)
            if case == "photo_duplicate": value.photos.add().CopyFrom(value.photos[0])
            elif case == "photo_no_asset": value.photos[0].assetId = ""
            else: value.photos[0].imageType = 99
            return value.SerializeToString()
        game[1].mutate_snapshot("player", directory.schema.fingerprint, break_photo)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(directory, FIND, userId=snapshot(game).userPublic.publicUserId)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_unknown_and_other_local_account_ids_do_not_expose_other_profiles(game, directory):
    before = dump(game[1]); other = game[1].profile("other")
    for identity in ("unknown-user", other["server_id"], other["public_id"]):
        with pytest.raises(RpcFailure) as error:
            call(directory, FIND, userId=identity)
        assert error.value.code == RpcCode.NOT_FOUND and dump(game[1]) == before


@pytest.mark.parametrize("path,raw", ((BIRTHDAY, b"\x08\x80"), (FIND, b"\x0a\x02x"), (FIND, b"")))
def test_malformed_or_empty_lookup_requests_never_mutate_state(game, directory, path, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: directory.handle(path, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


def test_authenticated_encrypted_registration_and_lookup_flow(game, directory, tmp_path):
    values = snapshot(game); request = directory.schema.request_type(BIRTHDAY)(month=2, day=29).SerializeToString()
    before = dump(game[1])
    with connected(game, directory, tmp_path/"fixtures") as invoke:
        for auth in (None, "invalid-token", game[3]):
            with pytest.raises(grpc.RpcError) as error: invoke(BIRTHDAY, request, auth)
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert dump(game[1]) == before
        response = directory.schema.response_type(BIRTHDAY).FromString(invoke(BIRTHDAY, request))
        assert (response.commonResponse.updatedData.profile.birthMonth, response.commonResponse.updatedData.profile.birthDay) == (2, 29)
        before_retry = dump(game[1])
        assert invoke(BIRTHDAY, request) == response.SerializeToString()
        assert invoke(USER) == game[1].snapshot("player")[0]
        find = directory.schema.request_type(FIND)(userId=values.userPublic.publicUserId).SerializeToString()
        result = directory.schema.response_type(FIND).FromString(invoke(FIND, find))
        assert (result.birthMonth, result.birthDay) == (2, 29)
        assert dump(game[1]) == before_retry


def test_explicit_profile_fixture_still_requires_auth_and_keeps_precedence(game, directory, tmp_path):
    captured = directory.schema.response_type(BIRTHDAY)()
    captured.commonResponse.updatedData.profile.birthMonth = 8
    captured.commonResponse.updatedData.profile.birthDay = 9
    source, fixtures = tmp_path/"captured.pb", tmp_path/"fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, fixtures, directory.schema, BIRTHDAY)
    before = dump(game[1])
    with connected(game, directory, fixtures) as invoke:
        with pytest.raises(grpc.RpcError) as error: invoke(BIRTHDAY, auth=None)
        assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(BIRTHDAY) == source.read_bytes()
    assert dump(game[1]) == before


def test_birthday_registration_rolls_back_a_failed_database_write(game, directory):
    import sqlite3
    with game[1].connect() as db:
        db.execute("CREATE TRIGGER stop_birthday BEFORE UPDATE OF response ON snapshots "
                   "BEGIN SELECT RAISE(ABORT, 'injected write failure'); END")
    before = dump(game[1])
    with pytest.raises(sqlite3.DatabaseError): call(directory, BIRTHDAY, month=2, day=29)
    assert dump(game[1]) == before
    assert (snapshot(game).profile.birthMonth, snapshot(game).profile.birthDay) == (0, 0)
    assert game[1].authenticated(game[2], "player")


@pytest.mark.parametrize("values", ({"userPublic__serverUserId": ""}, {"userPublic__publicUserId": ""},
                                    {"user__name": ""}, {"user__managerLevel": 0}, {"user__managerExp": -1}))
def test_incomplete_saved_identity_or_manager_is_not_a_fabricated_public_profile(game, directory, values):
    identity = snapshot(game).userPublic.publicUserId
    change(game, **values)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: call(directory, FIND, userId=identity)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_automatic_favorite_card_display_keeps_the_saved_choice(game, directory):
    change(game, profile__favoriteCardId="kept-card", profile__favoriteCardDisplayType=0)
    before = dump(game[1])
    result = call(directory, FIND, userId=snapshot(game).userPublic.publicUserId)
    assert result.favoriteCard.displayType == 0 and result.favoriteCard.cardId == "kept-card"
    assert dump(game[1]) == before


def test_unrelated_auth_and_birthday_campaign_routes_are_not_claimed(directory):
    for path in ("/api.Auth/Create", "/api.Auth/Recreate", "/api.Auth/Delete", "/api.Birthday/ReceiveReward", "/api.Birthday/Top"):
        assert directory.handle(path, b"") is None
