"""Original pose confirmation sends only the currently selected actor styles.

Android 6.1.1's current confirm caller constructs a request using the compact
actorCostumes.Select(...) sequences, leaving deprecated scalar fields empty.
A three-place scene therefore receives one style when one actor was selected.
"""
import json

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import Context
from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from test_photo_shooting import game, schema, EXPRESSION_CHECK, USER, dump


@pytest.fixture
def native_expression(game, tmp_path):
    provider, state, master, access = game
    # Recovered 6.1.1 uses [1], [2], or [3] for the actual room variants.
    # This represents its three-place variant rather than an invented [1,2]
    # exact-count set, which hid the one-selected-actor failure previously.
    source = master / "PhotoExpression.json"
    expression = json.loads(source.read_text())[0]
    expression["characterAmountArray"] = [3]
    source.write_text(json.dumps([expression]))
    for name, row in (
        ("Character", {"id": "char-c"}),
        ("Costume", {"id": "cos-c", "characterId": "char-c", "costumeTypeId": "casl"}),
        ("Hair", {"id": "hair-c", "characterId": "char-c", "wearableCostumeIds": [],
                  "notWearableCostumeIds": []}),
    ):
        path = master / (name + ".json")
        rows = json.loads(path.read_text())
        rows.append(row)
        path.write_text(json.dumps(rows))
    raw, fingerprint = state.snapshot("player")
    value = provider.schema.response_type(USER).FromString(raw)
    value.characters.add(characterId="char-c")
    value.costumes.add(costumeId="cos-c")
    value.hairs.add(hairId="hair-c")
    state.mutate_snapshot("player", fingerprint, lambda _: value.SerializeToString())
    scene_access = PhotoSceneAccess(activities=access.activities, musics=access.musics,
                                    stages=access.stages, expressions={"expression-a": True})
    app = Application(provider.schema, state, FixtureStore(tmp_path / "fixtures", provider.schema),
                      profile="player", master_dir=master, media_mode=True, photo_scene_access=scene_access)
    token, _ = state.login("player")
    return app, state, master, token


def native_request(app, count):
    # The original current constructor populates only repeated styles using
    # actorCostumes, not all empty room slots and not deprecated scalar styles.
    selected = ["a", "b", "c"][:count]
    request = app.schema.request_type(EXPRESSION_CHECK)(photoExpressionId="expression-a",
        characterIds=["char-" + identity for identity in selected],
        costumeIds=["cos-" + identity for identity in selected],
        hairIds=["hair-" + identity for identity in selected])
    assert not request.characterId and not request.costumeId and not request.hairId
    return request


def invoke(fixture, request, *, authenticated=True):
    app, _state, _master, token = fixture
    context = Context((("x-auth-token", token),) if authenticated else ())
    result = app.handle(EXPRESSION_CHECK, codec.encode(request.SerializeToString()), context)
    return app.schema.response_type(EXPRESSION_CHECK).FromString(result)


@pytest.mark.parametrize("count", (1, 2, 3))
def test_native_compact_actor_arrays_fit_a_three_place_expression(native_expression, count):
    app, state, _master, _token = native_expression
    request = native_request(app, count)
    before = dump(state)
    result = invoke(native_expression, request)
    assert result.HasField("commonResponse") and not result.commonResponse.ListFields()
    assert invoke(native_expression, request) == result
    assert dump(state) == before


def test_expression_layout_capacities_allow_a_partly_occupied_larger_layout(native_expression):
    app, state, master, _token = native_expression
    path = master / "PhotoExpression.json"
    rows = json.loads(path.read_text()); rows[0]["characterAmountArray"] = [1, 3]
    path.write_text(json.dumps(rows))
    before = dump(state)
    assert invoke(native_expression, native_request(app, 2)).HasField("commonResponse")
    assert dump(state) == before


def test_legacy_single_style_still_fits_a_three_place_expression(native_expression):
    app, state, _master, _token = native_expression
    request = app.schema.request_type(EXPRESSION_CHECK)(photoExpressionId="expression-a",
        characterId="char-a", costumeId="cos-a", hairId="hair-a")
    before = dump(state)
    assert invoke(native_expression, request).HasField("commonResponse")
    assert dump(state) == before


@pytest.mark.parametrize("case,code", (
    ("too-many", RpcCode.INVALID_ARGUMENT), ("empty", RpcCode.INVALID_ARGUMENT),
    ("partial-style", RpcCode.INVALID_ARGUMENT), ("sparse-style", RpcCode.INVALID_ARGUMENT),
    ("unowned-style", RpcCode.PERMISSION_DENIED), ("wrong-owner", RpcCode.INVALID_ARGUMENT),
    ("incompatible-hair", RpcCode.INVALID_ARGUMENT), ("excluded-character", RpcCode.INVALID_ARGUMENT),
    ("locked-expression", RpcCode.PERMISSION_DENIED), ("unauthenticated", RpcCode.UNAUTHENTICATED),
))
def test_expression_capacity_change_keeps_style_scene_and_auth_guards(native_expression, case, code):
    app, state, master, _token = native_expression
    request = native_request(app, 1)
    if case == "too-many":
        request.characterIds.extend(["char-a"] * 3)
        request.costumeIds.extend(["cos-a"] * 3)
        request.hairIds.extend(["hair-a"] * 3)
    elif case == "empty":
        request.ClearField("characterIds"); request.ClearField("costumeIds"); request.ClearField("hairIds")
    elif case == "partial-style":
        request.ClearField("hairIds")
    elif case == "sparse-style":
        request.characterIds.append(""); request.costumeIds.append(""); request.hairIds.append("")
    elif case == "unowned-style":
        request.costumeIds[0] = "unowned"
    elif case == "wrong-owner":
        request.costumeIds[0] = "cos-b"
    elif case == "incompatible-hair":
        path = master / "Hair.json"; rows = json.loads(path.read_text())
        rows[0]["notWearableCostumeIds"] = ["cos-a"]; path.write_text(json.dumps(rows))
    elif case == "excluded-character":
        path = master / "PhotoExpression.json"; rows = json.loads(path.read_text())
        rows[0]["impossibleShootingCharacterIds"] = ["char-a"]; path.write_text(json.dumps(rows))
    elif case == "locked-expression":
        app.photo_shootings.scene_access = PhotoSceneAccess(expressions={"expression-a": False})
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        invoke(native_expression, request, authenticated=case != "unauthenticated")
    assert error.value.code == code
    assert dump(state) == before
