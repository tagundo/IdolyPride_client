"""Original Home conversation receipts in an explicit reward-free gallery."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import Context
from idoly_local.home_talk import HomeTalks
from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_photo_shooting import schema, UNKNOWN


READ, USER = "/api.Home/ReadTalk", "/api.User/Get"


@pytest.fixture
def talks(schema, tmp_path):
    master = tmp_path / "master-json"; master.mkdir()
    (master / "!version.txt").write_text("original-shaped-home-talks")
    rows = {
        "Character": [{"id": "character-a"}, {"id": "character-b"}],
        "HomeTalk": [
            {"homeTalkId": "talk-a", "characterId": "character-a", "cardId": "card-a",
             "conditionId": "original-condition-not-emulated-in-gallery", "releaseDate": "0", "reliability": 500,
             "characterTalks": [{"text": "Original conversation", "voiceAssetId": "original-voice-a",
                                 "motionAssetId": "original-motion-a", "additionMotionAssetId": ""}]},
            {"homeTalkId": "talk-b", "characterId": "character-b", "cardId": "", "releaseDate": "0"},
            {"homeTalkId": "talk-card", "characterId": "character-a", "cardId": "card-not-owned", "releaseDate": "0"},
            {"homeTalkId": "talk-future", "characterId": "character-a", "cardId": "card-a",
             "conditionId": "future-gallery-choice", "releaseDate": "4102444800000", "reliability": 9999},
        ],
    }
    for row in rows["HomeTalk"]:
        row.setdefault("characterTalks", [{"text": "Preserved original-shaped dialogue", "voiceAssetId": "voice"}])
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    state = State(tmp_path / "state.db")
    value = schema.response_type(USER)(); value.user.name = "Gallery"
    value.user.MergeFromString(UNKNOWN); value.MergeFromString(UNKNOWN)
    value.balance.freeBalance, value.balance.paidBalance = 123, 45
    value.characters.add(characterId="character-a", reliability=777, lastHomeTalkFirstReadTime=900).MergeFromString(UNKNOWN)
    value.cards.add(cardId="card-a")
    value.items.add(itemId="preserved-film", amount=1)
    value.homeTalks.add(homeTalkId="archived-before-this-catalog").MergeFromString(UNKNOWN)
    value.stories.add(storyId="preserved-story", statusType=2)
    for profile in ("media", "ordinary"):
        state.save_snapshot(profile, value.SerializeToString(), schema.fingerprint)
    token, _ = state.login("media"); normal_token, _ = state.login("ordinary")
    clock = []
    def now():
        clock.append(1000)
        return 1000
    provider = HomeTalks(schema, state, "media", master, media_mode=True, now_ms=now)
    return SimpleNamespace(schema=schema, state=state, master=master, rows=rows,
                           provider=provider, clock=clock, token=token, normal_token=normal_token, root=tmp_path)


def snapshot(game, profile="media"):
    return game.schema.response_type(USER).FromString(game.state.snapshot(profile)[0])


def call(game, identity="talk-a"):
    request = game.schema.request_type(READ)(homeTalkId=identity)
    return game.schema.response_type(READ).FromString(game.provider.handle(READ, request.SerializeToString()))


def dump(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def test_first_read_records_real_talk_timestamp_and_full_current_rows_without_any_reward(talks):
    game = talks
    before = snapshot(game); normal_before = game.state.snapshot("ordinary")
    masters_before = (game.master / "HomeTalk.json").read_bytes()
    expected = type(before)(); expected.CopyFrom(before)
    expected.homeTalks.add(homeTalkId="talk-a")
    expected.characters[0].lastHomeTalkFirstReadTime = 1000
    response = call(game)
    assert snapshot(game) == expected
    assert not response.isReliabilityUp
    assert response.commonResponse.updatedData.characters == [expected.characters[0]]
    assert response.commonResponse.updatedData.homeTalks == [expected.homeTalks[-1]]
    assert [field.name for field, _ in response.commonResponse.updatedData.ListFields()] == ["characters", "homeTalks"]
    assert not response.commonResponse.HasField("deletedData")
    assert snapshot(game).characters[0].reliability == before.characters[0].reliability == 777
    assert game.state.snapshot("ordinary") == normal_before
    assert (game.master / "HomeTalk.json").read_bytes() == masters_before
    assert game.state.authenticated(game.token, "media")
    assert game.clock == [1000]


def test_retry_acknowledges_current_rows_unknown_fields_and_never_rewrites_snapshot(talks):
    game = talks; call(game)
    value = snapshot(game)
    value.characters[0].reliability = 888
    value.characters[0].favoriteCostumeId = "changed-since-first-response"
    value.homeTalks[-1].MergeFromString(UNKNOWN)
    # A historical receipt remains meaningful if the card was later removed.
    del value.cards[:]
    game.state.mutate_snapshot("media", game.schema.fingerprint, lambda _: value.SerializeToString())
    before = dump(game)
    with game.state.connect() as monitor:
        version = monitor.execute("PRAGMA data_version").fetchone()[0]
        result = call(game)
        assert monitor.execute("PRAGMA data_version").fetchone()[0] == version
    assert result.commonResponse.updatedData.characters == [value.characters[0]]
    assert result.commonResponse.updatedData.homeTalks == [value.homeTalks[-1]]
    assert UNKNOWN in result.commonResponse.updatedData.homeTalks[0].SerializeToString()
    assert game.clock == [1000] and dump(game) == before
    game.provider = HomeTalks(game.schema, State(game.state.path), "media", game.master,
                              media_mode=True, now_ms=lambda: pytest.fail("retry must not request a timestamp"))
    assert call(game) == result and dump(game) == before


def test_simultaneous_first_reads_create_one_receipt_and_one_timestamp(talks):
    game = talks
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(lambda _: call(game), range(2)))
    assert result[0] == result[1]
    assert [row.homeTalkId for row in snapshot(game).homeTalks].count("talk-a") == 1
    assert game.clock == [1000]
    assert snapshot(game).characters[0].reliability == 777


def test_lost_first_response_retry_keeps_a_later_different_talk_timestamp(talks):
    game = talks
    times = iter((1000, 2000))
    game.provider._clock = lambda: next(times)
    call(game, "talk-a")
    call(game, "talk-future")
    before = dump(game)
    retried = call(game, "talk-a")
    assert retried.commonResponse.updatedData.homeTalks[0].homeTalkId == "talk-a"
    assert retried.commonResponse.updatedData.characters[0].lastHomeTalkFirstReadTime == 2000
    assert not retried.isReliabilityUp and dump(game) == before


def test_gallery_release_condition_policy_is_explicit_and_never_grants_official_rewards(talks):
    game = talks; before = snapshot(game)
    result = call(game, "talk-future")
    assert not result.isReliabilityUp
    assert snapshot(game).characters[0].reliability == before.characters[0].reliability
    assert snapshot(game).balance == before.balance
    assert len(snapshot(game).homeTalks) == len(before.homeTalks) + 1


@pytest.mark.parametrize("identity,code", (("", RpcCode.INVALID_ARGUMENT), ("missing", RpcCode.NOT_FOUND),
    ("talk-b", RpcCode.PERMISSION_DENIED), ("talk-card", RpcCode.FAILED_PRECONDITION)))
def test_missing_unowned_and_unknown_talks_fail_without_any_write(talks, identity, code):
    game = talks; before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game, identity)
    assert error.value.code == code and dump(game) == before and not game.clock


@pytest.mark.parametrize("value", (0, -1, True, 1.0, 2**63))
def test_bad_clock_cannot_partly_add_a_receipt(talks, value):
    game = talks; game.provider._clock = lambda: value; before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


def test_clock_regression_keeps_existing_later_first_read_timestamp(talks):
    game = talks; value = snapshot(game); value.characters[0].lastHomeTalkFirstReadTime = 2000
    game.state.mutate_snapshot("media", game.schema.fingerprint, lambda _: value.SerializeToString())
    assert call(game).commonResponse.updatedData.characters[0].lastHomeTalkFirstReadTime == 2000
    assert snapshot(game).homeTalks[-1].homeTalkId == "talk-a"


@pytest.mark.parametrize("change", ("duplicate-master", "empty-id", "bad-date", "bad-dialogue", "empty-dialogue", "unknown-owner", "missing-table"))
def test_invalid_original_master_does_not_cache_a_partial_catalog_or_write_a_receipt(talks, change):
    game = talks; path = game.master / "HomeTalk.json"
    rows = list(game.rows["HomeTalk"])
    if change == "duplicate-master": rows.append(dict(rows[0]))
    elif change == "empty-id": rows[-1] = dict(rows[-1], homeTalkId="")
    elif change == "bad-date": rows[-1] = dict(rows[-1], releaseDate=True)
    elif change == "bad-dialogue": rows[-1] = dict(rows[-1], characterTalks=[{"text": []}])
    elif change == "empty-dialogue": rows[-1] = dict(rows[-1], characterTalks=[])
    elif change == "unknown-owner": rows[0] = dict(rows[0], characterId="not-in-Character-master")
    if change == "missing-table": path.unlink()
    else: path.write_text(json.dumps(rows))
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before
    assert game.provider._talks is None
    # Fixing the input must not reuse an incomplete failed parse.
    path.write_text(json.dumps(game.rows["HomeTalk"]))
    game.provider = HomeTalks(game.schema, game.state, "media", game.master, media_mode=True, now_ms=lambda: 1000)
    assert call(game).commonResponse.updatedData.homeTalks[0].homeTalkId == "talk-a"


def test_duplicate_local_receipts_cannot_be_ambiguously_acknowledged(talks):
    game = talks; value = snapshot(game)
    value.homeTalks.add(homeTalkId=value.homeTalks[0].homeTalkId)
    game.state.mutate_snapshot("media", game.schema.fingerprint, lambda _: value.SerializeToString())
    before = dump(game)
    with pytest.raises(RpcFailure) as error: call(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


def test_malformed_wire_request_and_ordinary_mode_do_not_touch_any_profile(talks):
    game = talks; before = dump(game)
    with pytest.raises(RpcFailure) as error: game.provider.handle(READ, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    ordinary = HomeTalks(game.schema, game.state, "ordinary", game.master, media_mode=False)
    assert ordinary.handle(READ, b"\x0a\x80") is None
    assert game.provider.handle("/api.Home/Unrelated", b"") is None
    assert dump(game) == before


def test_encrypted_application_read_userget_restart_and_auth_conversation_flow(talks):
    game = talks
    fixtures = FixtureStore(game.root / "fixtures", game.schema)
    app = Application(game.schema, game.state, fixtures, profile="media", master_dir=game.master,
                      media_mode=True, photo_scene_access=PhotoSceneAccess())
    app.home_talks._clock = lambda: 1000
    def invoke(route, values=None, *, token=game.token):
        request = game.schema.request_type(route)(**(values or {})).SerializeToString()
        raw = app.handle(route, codec.encode(request), Context((("x-auth-token", token),)))
        return game.schema.response_type(route).FromString(raw)
    before = dump(game)
    with pytest.raises(RpcFailure) as denied: invoke(READ, {"homeTalkId": "talk-a"}, token="")
    assert denied.value.code == RpcCode.UNAUTHENTICATED and dump(game) == before
    initial = invoke(USER)
    assert "talk-a" not in {row.homeTalkId for row in initial.homeTalks}
    result = invoke(READ, {"homeTalkId": "talk-a"})
    assert not result.isReliabilityUp
    assert result.commonResponse.updatedData.homeTalks[0].homeTalkId == "talk-a"
    assert "talk-a" in {row.homeTalkId for row in invoke(USER).homeTalks}
    assert invoke(USER).balance == initial.balance
    assert not any("talk" in field.name.lower() for field in game.schema.response_type("/api.Home/Enter").DESCRIPTOR.fields)
    with pytest.raises(RpcFailure) as denied: invoke(READ, {"homeTalkId": "talk-a"}, token=game.normal_token)
    assert denied.value.code == RpcCode.UNAUTHENTICATED


def test_ordinary_captured_readtalk_response_keeps_fixture_precedence(talks):
    game = talks; folder = game.root / "fixtures"
    response = game.schema.response_type(READ)(isReliabilityUp=True)
    response.commonResponse.updatedData.homeTalks.add(homeTalkId="preserved-normal-receipt")
    source = game.root / "preserved-read-talk.pb"; source.write_bytes(response.SerializeToString())
    import_response(source, folder, game.schema, READ)
    app = Application(game.schema, game.state, FixtureStore(folder, game.schema), profile="ordinary",
                      master_dir=game.master, media_mode=False)
    before = dump(game)
    request = game.schema.request_type(READ)(homeTalkId="talk-a").SerializeToString()
    raw = app.handle(READ, codec.encode(request), Context((("x-auth-token", game.normal_token),)))
    assert game.schema.response_type(READ).FromString(raw) == response
    assert dump(game) == before
