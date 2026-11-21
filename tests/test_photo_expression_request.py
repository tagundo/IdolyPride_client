"""Pose confirmation retains standby roster styles beside the active prefix.

The client can keep three roster styles while a one-place room activates only
its first character. Checks validate the complete roster without interpreting
its serialized length as the number of actors placed in the selected room.
"""
import hashlib
import json
import os
from pathlib import Path

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
        request.characterIds.extend(["char-a"] * 5)
        request.costumeIds.extend(["cos-a"] * 5)
        request.hairIds.extend(["hair-a"] * 5)
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


@pytest.mark.parametrize("capacity", (1, 3))
def test_three_style_roster_projects_only_the_active_room_prefix(native_expression, capacity):
    app, state, master, _token = native_expression
    path = master / "PhotoExpression.json"
    rows = json.loads(path.read_text())
    rows[0]["characterAmountArray"] = [capacity]
    path.write_text(json.dumps(rows))
    request = native_request(app, 3)
    provider = app.photo_shootings
    before = dump(state)
    active = provider._expression(request, provider._snapshot(), provider._access())
    assert active == (tuple(request.characterIds[:capacity]), tuple(request.costumeIds[:capacity]),
                      tuple(request.hairIds[:capacity]))
    result = invoke(native_expression, request)
    assert result.HasField("commonResponse") and not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert invoke(native_expression, request) == result and dump(state) == before


def test_inactive_roster_keeps_identity_ownership_and_hair_guards(native_expression):
    app, state, master, _token = native_expression
    path = master / "PhotoExpression.json"
    rows = json.loads(path.read_text()); rows[0]["characterAmountArray"] = [1]
    path.write_text(json.dumps(rows))
    attempts = (
        ("characterIds", "unknown-character", RpcCode.INVALID_ARGUMENT),
        ("costumeIds", "unknown-costume", RpcCode.INVALID_ARGUMENT),
        ("costumeIds", "unowned", RpcCode.PERMISSION_DENIED),
        ("costumeIds", "cos-a", RpcCode.INVALID_ARGUMENT),
        ("hairIds", "hair-a", RpcCode.INVALID_ARGUMENT),
    )
    before = dump(state)
    for field, replacement, code in attempts:
        request = native_request(app, 3)
        getattr(request, field)[1] = replacement
        with pytest.raises(RpcFailure) as error:
            invoke(native_expression, request)
        assert error.value.code == code and dump(state) == before
    hair = master / "Hair.json"
    values = json.loads(hair.read_text())
    # An explicit whitelist match permits the outfit in the original
    # compatibility rule, even when the blacklist also names it. Remove that
    # inherited allowance so this fixture is unambiguously incompatible.
    next(row for row in values if row["id"] == "hair-b").update(
        wearableCostumeIds=[], notWearableCostumeIds=["cos-b"])
    hair.write_text(json.dumps(values))
    app.photo_shootings.catalog.loaded.pop("Hair", None)
    with pytest.raises(RpcFailure) as error:
        invoke(native_expression, native_request(app, 3))
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(state) == before


def test_room_restrictions_apply_to_active_prefix_without_unlocking_standby(native_expression):
    app, state, master, _token = native_expression
    path = master / "PhotoExpression.json"
    rows = json.loads(path.read_text()); rows[0]["characterAmountArray"] = [1]
    rows[0]["impossibleShootingCharacterIds"] = ["char-b"]
    path.write_text(json.dumps(rows))
    app.photo_shootings.media_mode = False
    before = dump(state)
    request = native_request(app, 3)
    # Inactive B is both scene-excluded and wearing the scene's disallowed
    # idol type; all of its master, ownership and hair checks still execute.
    assert invoke(native_expression, request).HasField("commonResponse")
    for field in ("characterIds", "costumeIds", "hairIds"):
        values = getattr(request, field)
        values[0], values[1] = values[1], values[0]
    with pytest.raises(RpcFailure) as error:
        invoke(native_expression, request)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(state) == before


def test_pinned_ymkw_capacity_accepts_three_style_roster_as_one_active_character(native_expression):
    app, state, master, _token = native_expression
    explicit = os.environ.get("IDOLY_PREFERENCE_MASTER_DIR")
    source = (Path(explicit) if explicit else Path(__file__).resolve().parents[1] / "data/master-json") / "PhotoExpression.json"
    if not source.is_file():
        if explicit:
            pytest.fail("The required pinned photo-expression master is unavailable")
        pytest.skip("Original public photo-expression master is unavailable")
    raw = source.read_bytes()
    assert len(raw) == 18071
    assert hashlib.sha256(raw).hexdigest() == "ede48c24a81498d02569d6bc5aae81ae7ceeb36516d78fc601df679c58709ae4"
    expression = next(row for row in json.loads(raw) if row["id"] == "photo_expression-ymkw")
    assert expression["characterAmountArray"] == [1]
    (master / "PhotoExpression.json").write_text(json.dumps([expression]))
    (master / "Stage.json").write_text(json.dumps([{"id": expression["stageId"], "assetId": "synthetic-stage-presence"}]))
    app.photo_shootings.scene_access = PhotoSceneAccess(expressions={expression["id"]: True})
    request = native_request(app, 3)
    request.photoExpressionId = expression["id"]
    before = dump(state)
    provider = app.photo_shootings
    assert provider._expression(request, provider._snapshot(), provider._access()) == (
        ("char-a",), ("cos-a",), ("hair-a",))
    assert invoke(native_expression, request).HasField("commonResponse")
    assert dump(state) == before


def test_five_owned_roster_styles_preserve_three_active_places_and_reject_a_sixth(native_expression):
    app, state, master, _token = native_expression
    value = app.schema.response_type(USER).FromString(state.snapshot("player")[0])
    for suffix in ("d", "e"):
        for table, row in (
            ("Character", {"id": "char-" + suffix}),
            ("Costume", {"id": "cos-" + suffix, "characterId": "char-" + suffix, "costumeTypeId": "casl"}),
            ("Hair", {"id": "hair-" + suffix, "characterId": "char-" + suffix,
                      "wearableCostumeIds": [], "notWearableCostumeIds": []}),
        ):
            path = master / (table + ".json")
            rows = json.loads(path.read_text()); rows.append(row); path.write_text(json.dumps(rows))
        value.characters.add(characterId="char-" + suffix)
        value.costumes.add(costumeId="cos-" + suffix)
        value.hairs.add(hairId="hair-" + suffix)
    state.mutate_snapshot("player", app.schema.fingerprint, lambda _raw: value.SerializeToString())
    request = app.schema.request_type(EXPRESSION_CHECK)(photoExpressionId="expression-a",
        characterIds=["char-" + suffix for suffix in "abcde"],
        costumeIds=["cos-" + suffix for suffix in "abcde"],
        hairIds=["hair-" + suffix for suffix in "abcde"])
    before = dump(state)
    provider = app.photo_shootings
    assert provider._expression(request, provider._snapshot(), provider._access()) == (
        ("char-a", "char-b", "char-c"), ("cos-a", "cos-b", "cos-c"), ("hair-a", "hair-b", "hair-c"))
    assert invoke(native_expression, request).HasField("commonResponse")
    request.characterIds.append("char-a"); request.costumeIds.append("cos-a"); request.hairIds.append("hair-a")
    with pytest.raises(RpcFailure) as error:
        invoke(native_expression, request)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(state) == before
