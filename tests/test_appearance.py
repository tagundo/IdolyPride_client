"""Owned appearance changes use real fields and never grant equipment."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.appearance import Appearance
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


SET = "/api.Costume/SetCostume"
LIVE = "/api.Costume/SetLiveCostume"
CHECK = "/api.Costume/CheckCostume"
HAIR = "/api.Hair/CheckHair"
BULK = "/api.Costume/CheckBulk"
ROUTES = (SET, LIVE, CHECK, HAIR, BULK)
USER = "/api.User/Get"
UNKNOWN = b"\x80\x4b\x7b"


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    # Protobuf services and messages share one package symbol namespace.
    for message in file.message_type:
        if message.name in ("Costume", "Hair"):
            message.name = "Owned" + message.name
        for field in message.field:
            if field.type_name in (".api.Costume", ".api.Hair"):
                field.type_name = ".api.Owned" + field.type_name.rsplit(".", 1)[-1]
    for name, fields in (
        ("OutfitRequest", (("costumeId", False), ("hairId", False))),
        ("CostumeCheckRequest", (("costumeId", False),)),
        ("HairCheckRequest", (("hairId", False),)),
        ("OutfitBulkRequest", (("costumeIds", True), ("hairIds", True))),
    ):
        message = file.message_type.add(name=name)
        for number, (name, repeated) in enumerate(fields, 1):
            message.field.add(name=name, number=number, type=9, label=3 if repeated else 1)
    for name, methods in (("Costume", (("SetCostume", "OutfitRequest"),
            ("SetLiveCostume", "OutfitRequest"), ("CheckCostume", "CostumeCheckRequest"),
            ("CheckBulk", "OutfitBulkRequest"))), ("Hair", (("CheckHair", "HairCheckRequest"),))):
        service = file.service.add(name=name)
        for method, request in methods:
            service.method.add(name=method, input_type=".api." + request, output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("appearance-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    rows = {
        "Character": [{"id": "char-a"}, {"id": "char-b"}],
        "Costume": [{"id": key, "characterId": owner, "defaultHairId": hair} for key, owner, hair in (
            ("cos-a0", "char-a", "hair-a0"), ("cos-a1", "char-a", "hair-a1"),
            ("cos-b0", "char-b", "hair-b0"), ("cos-unowned", "char-a", "hair-unowned"))],
        "Hair": [{"id": key, "characterId": owner, "wearableCostumeIds": [],
                  "notWearableCostumeIds": []} for key, owner in (
            ("hair-a0", "char-a"), ("hair-a1", "char-a"), ("hair-b0", "char-b"),
            ("hair-unowned", "char-a"))],
    }
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    state = State(tmp_path / "profiles.sqlite")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "Preserved manager"
    snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId = identity["server_id"], identity["public_id"]
    for suffix in ("a", "b"):
        row = snapshot.characters.add(characterId="char-" + suffix,
            favoriteCostumeId="cos-" + suffix + "0", favoriteHairId="hair-" + suffix + "0",
            liveCostumeId="cos-" + suffix + "0", liveHairId="hair-" + suffix + "0")
        row.MergeFromString(UNKNOWN)
    for identity in ("cos-a0", "cos-a1", "cos-b0"):
        row = snapshot.costumes.add(costumeId=identity, checked=identity.endswith("0"), obtainedTime=123456)
        row.MergeFromString(UNKNOWN)
    for identity in ("hair-a0", "hair-a1", "hair-b0"):
        row = snapshot.hairs.add(hairId=identity, checked=identity.endswith("0"))
        row.MergeFromString(UNKNOWN)
    snapshot.balance.MergeFromString(b"\x08\x64\x10\x07" + UNKNOWN)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"private settings\x00")
    state.mutate_lesson_snapshot("player", schema.fingerprint, lambda raw, _: (raw, b"existing lesson clock\x00"))
    state.save_snapshot("other", snapshot.SerializeToString(), schema.fingerprint)
    other_token, _ = state.login("other")
    token, _ = state.login("player")
    return Appearance(schema, state, "player", master), state, master, rows, token, other_token


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def protected(state):
    with state.connect() as connection:
        tables = {name: [tuple(row) for row in connection.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
                  for name in ("profiles", "sessions", "profile_settings", "starter_profiles", "profile_lesson_progress")}
    return tables, state.snapshot("other")


def call(game, path, **values):
    provider = game[0]
    request = provider.schema.request_type(path)(**values)
    raw = provider.handle(path, request.SerializeToString())
    assert raw is not None
    return provider.schema.response_type(path).FromString(raw)


@pytest.mark.parametrize("path,prefix", ((SET, "favorite"), (LIVE, "live")))
def test_owned_alternative_changes_only_selected_preferences_and_survives_retry_restart(game, path, prefix):
    provider, state, master = game[:3]
    expected = snapshot(game)
    setattr(expected.characters[0], prefix + "CostumeId", "cos-a1")
    setattr(expected.characters[0], prefix + "HairId", "hair-a1")
    kept = protected(state)
    result = call(game, path, costumeId="cos-a1", hairId="hair-a1")
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert list(result.commonResponse.updatedData.characters) == [expected.characters[0]]
    assert not result.commonResponse.deletedData.ListFields()
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"characters"}
    assert protected(state) == kept
    before_retry = dump(state)
    call(game, path, costumeId="cos-a1", hairId="hair-a1")
    restarted = State(state.path)
    again = Appearance(provider.schema, restarted, "player", master)
    again.handle(path, provider.schema.request_type(path)(costumeId="cos-a1", hairId="hair-a1").SerializeToString())
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[4], "player") and restarted.authenticated(game[5], "other")


@pytest.mark.parametrize("path,values", ((CHECK, {"costumeId": "cos-a1"}), (HAIR, {"hairId": "hair-a1"}),
    (BULK, {"costumeIds": ["cos-a1", "cos-a1"], "hairIds": ["hair-a1", "hair-a1"]})))
def test_checked_acknowledgements_are_idempotent_and_do_not_change_preferences_or_inventory(game, path, values):
    state = game[1]
    expected = snapshot(game)
    if path in (CHECK, BULK):
        expected.costumes[1].checked = True
    if path in (HAIR, BULK):
        expected.hairs[1].checked = True
    kept = protected(state)
    result = call(game, path, **values)
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert len(result.commonResponse.updatedData.costumes) == int(path in (CHECK, BULK))
    assert len(result.commonResponse.updatedData.hairs) == int(path in (HAIR, BULK))
    assert protected(state) == kept
    before_retry = dump(state)
    assert call(game, path, **values) == result
    assert dump(state) == before_retry


@pytest.mark.parametrize("path", ROUTES)
def test_empty_and_malformed_requests_fail_without_writes(game, path):
    before = dump(game[1])
    for raw in ((b"\x0a\x80",) if path == BULK else (b"", b"\x0a\x80")):
        with pytest.raises(RpcFailure) as error:
            game[0].handle(path, raw)
        assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


def test_empty_bulk_is_an_idempotent_acknowledgement_without_snapshot_or_clock_writes(game):
    before = dump(game[1])
    result = call(game, BULK)
    assert result.commonResponse.HasField("updatedData")
    assert result.commonResponse.HasField("deletedData")
    assert not result.commonResponse.updatedData.ListFields()
    assert not result.commonResponse.deletedData.ListFields()
    assert call(game, BULK) == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("values,code", (
    ({"costumeId": "missing", "hairId": "hair-a1"}, RpcCode.INVALID_ARGUMENT),
    ({"costumeId": "cos-unowned", "hairId": "hair-a1"}, RpcCode.PERMISSION_DENIED),
    ({"costumeId": "cos-a1", "hairId": "hair-unowned"}, RpcCode.PERMISSION_DENIED),
    ({"costumeId": "cos-a1", "hairId": "hair-b0"}, RpcCode.INVALID_ARGUMENT),
))
def test_missing_unowned_and_cross_character_outfits_are_rejected(game, values, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, SET, **values)
    assert error.value.code == code
    assert dump(game[1]) == before


@pytest.mark.parametrize("allowed,denied,accepted", (([], [], True), (["cos-a1"], [], True),
    (["cos-a0"], [], False), ([], ["cos-a1"], False), (["cos-a0"], ["cos-a0"], True)))
def test_hair_compatibility_preserves_the_native_whitelist_or_blacklist_rule(game, allowed, denied, accepted):
    provider, state, master, rows = game[:4]
    rows["Hair"][1].update(wearableCostumeIds=allowed, notWearableCostumeIds=denied)
    (master / "Hair.json").write_text(json.dumps(rows["Hair"]))
    before = dump(state)
    if accepted:
        call(game, SET, costumeId="cos-a1", hairId="hair-a1")
        assert snapshot(game).characters[0].favoriteHairId == "hair-a1"
    else:
        with pytest.raises(RpcFailure) as error:
            call(game, SET, costumeId="cos-a1", hairId="hair-a1")
        assert error.value.code == RpcCode.INVALID_ARGUMENT
        assert dump(state) == before


@pytest.mark.parametrize("field", ("characters", "costumes", "hairs"))
def test_duplicate_owned_rows_do_not_choose_an_arbitrary_inventory_entry(game, field):
    provider, state = game[:2]
    def duplicate(raw):
        value = provider.schema.response_type(USER).FromString(raw)
        getattr(value, field).add().CopyFrom(getattr(value, field)[0])
        return value.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, duplicate)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(game, SET, costumeId="cos-a1", hairId="hair-a1")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_bulk_validation_rolls_back_all_acknowledgements_when_one_item_is_not_owned(game):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, BULK, costumeIds=["cos-a1"], hairIds=["hair-a1", "hair-unowned"])
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(game[1]) == before


def test_concurrent_favorite_and_live_changes_preserve_both_and_other_state(game):
    expected = snapshot(game)
    for prefix in ("favorite", "live"):
        setattr(expected.characters[0], prefix + "CostumeId", "cos-a1")
        setattr(expected.characters[0], prefix + "HairId", "hair-a1")
    kept = protected(game[1])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: call(game, SET if index % 2 else LIVE,
                                       costumeId="cos-a1", hairId="hair-a1"), range(16)))
    assert game[1].snapshot("player")[0] == expected.SerializeToString()
    assert protected(game[1]) == kept


@pytest.mark.parametrize("damage", ("schema", "malformed", "missing-user", "missing-character"))
def test_invalid_profile_cannot_be_changed_or_partially_acknowledged(game, damage):
    provider, state = game[:2]
    value = snapshot(game)
    if damage == "missing-user":
        value.ClearField("user")
    if damage == "missing-character":
        del value.characters[:]
    raw = b"\x0a\x80" if damage == "malformed" else value.SerializeToString()
    state.save_snapshot("player", raw, "different-schema" if damage == "schema" else provider.schema.fingerprint)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(game, SET, costumeId="cos-a1", hairId="hair-a1")
    assert error.value.code == (RpcCode.PERMISSION_DENIED if damage == "missing-character" else RpcCode.FAILED_PRECONDITION)
    assert dump(state) == before


def test_forward_unknown_request_fields_and_unsupported_paths(game):
    provider = game[0]
    raw = provider.schema.request_type(SET)(costumeId="cos-a1", hairId="hair-a1").SerializeToString() + UNKNOWN
    assert provider.handle(SET, raw) is not None
    assert provider.handle("/api.Costume/Grant", b"") is None
    assert Appearance(provider.schema, provider.state, "player").handle(SET, raw) is None
