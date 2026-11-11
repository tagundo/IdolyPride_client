"""Media-only story access uses real protocol fields, not official unlock rules."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local import media_stories as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


UNKNOWN = b"\x80\x4b\x07"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Recovered 6.1.1 schema is not installed")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "!version.txt").write_text(module.MASTER_VERSION)
    rows = {
        "Story": [
            {"id": "media-main", "advPlayTypes": [1, 2], "advAssetIds": ["main-adv", "main-live"],
             "rewardId": "unsupported-reward-is-not-paid-in-media-mode"},
            {"id": "media-event", "advPlayTypes": [3], "advAssetIds": ["event-adv"]},
            {"id": "media-extra", "advPlayTypes": [6], "advAssetIds": [],
             "branchChoices": [{"index": 1, "advAssetId": "extra-branch"}]},
        ],
        "EventStory": [{"id": "event", "episodes": [{"episode": 1, "storyId": "media-event"}]}],
        "ExtraStoryPart": [{"id": "extra-part", "extraStoryIds": ["extra"]}],
        "ExtraStory": [{"id": "extra", "extraStoryPartId": "extra-part",
                        "episodes": [{"episode": 1, "storyId": "media-extra"}]}],
        "StoryPart": [{"id": "main-part", "chapters": [
            {"chapter": 1, "route": 0, "episodes": [{"episode": 1, "storyId": "media-main"}]}]}],
    }
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    state = State(tmp_path / "state.db")
    snapshot = schema.response_type(module._USER)()
    snapshot.user.name = "Media"
    snapshot.balance.freeBalance, snapshot.balance.paidBalance = 123, 45
    snapshot.MergeFromString(UNKNOWN)
    for profile in ("media", "ordinary"):
        state.save_snapshot(profile, snapshot.SerializeToString(), schema.fingerprint)
    token, _ = state.login("media")
    state.mutate_snapshot("media", schema.fingerprint, lambda raw: raw, setting_info=b"keep-settings")
    state.mutate_lesson_snapshot("media", schema.fingerprint, lambda raw, _: (raw, b"keep-clock"))
    handler = module.MediaStories(schema, state, "media", master)
    return SimpleNamespace(schema=schema, state=state, master=master, rows=rows, handler=handler, token=token)


def invoke(game, path, **values):
    request = game.schema.request_type(path)(**values)
    raw = game.handler.handle(path, request.SerializeToString())
    return game.schema.response_type(path).FromString(raw)


def dump(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def snapshot(game):
    return game.schema.response_type(module._USER).FromString(game.state.snapshot("media")[0])


def test_seed_unlocks_only_defined_stories_and_preserves_read_photo_and_unknown_fields(game):
    value = snapshot(game)
    value.stories.add(storyId="media-main", statusType=2, isInvalid=True, isPhotoShot=True).MergeFromString(UNKNOWN)
    value.stories.add(storyId="media-event", statusType=0, isUseActivatePhotoShootingStoryTicket=True)
    value.stories.add(storyId="unrelated-imported-story", statusType=0, isInvalid=True)
    ordinary = game.state.snapshot("ordinary")
    assert module.unlock_media_stories(value, game.master) == 3
    by_id = {row.storyId: row for row in value.stories}
    assert by_id["media-main"].statusType == 2 and not by_id["media-main"].isInvalid
    assert by_id["media-main"].isPhotoShot and UNKNOWN in by_id["media-main"].SerializeToString()
    assert by_id["media-event"].statusType == by_id["media-extra"].statusType == 1
    assert by_id["media-event"].isUseActivatePhotoShootingStoryTicket
    assert by_id["unrelated-imported-story"].isInvalid
    before = value.SerializeToString()
    assert module.unlock_media_stories(value, game.master) == 0
    assert value.SerializeToString() == before and game.state.snapshot("ordinary") == ordinary
    assert (value.balance.freeBalance, value.balance.paidBalance) == (123, 45)


def test_full_media_lists_and_home_are_consistent_read_only_and_use_exact_master_links(game):
    before = dump(game)
    events = invoke(game, module._LIST_EVENT)
    extras = invoke(game, module._LIST_EXTRA)
    assert [(row.id, [(ep.episode, ep.unlocked) for ep in row.episodes]) for row in events.infos] == [
        ("event", [(1, True)])]
    assert extras.infos[0].id == "extra-part" and extras.infos[0].unlocked
    assert extras.infos[0].stories[0].id == "extra" and extras.infos[0].stories[0].unlocked
    assert extras.infos[0].stories[0].episodes[0].unlocked
    home = game.schema.response_type("/api.Home/Enter")()
    home.extraStoryPartInfos.add(id="stale-normal-list")
    game.handler.fill_home(home)
    assert list(home.extraStoryPartInfos) == list(extras.infos)
    for response in (events, extras):
        assert not response.commonResponse.updatedData.ListFields()
        assert not response.commonResponse.deletedData.ListFields()
    assert dump(game) == before


@pytest.mark.parametrize("is_last", (False, True), ids=("skip", "end"))
@pytest.mark.parametrize("path,fields,identity", (
    (module._READ, {"storyId": "media-main"}, "media-main"),
    (module._EVENT, {"eventStoryId": "event", "episode": 1}, "media-event"),
    (module._EXTRA, {"extraStoryId": "extra", "episode": 1}, "media-extra"),
))
def test_complete_or_skip_all_story_types_without_reward_and_retry_is_identical(game, path, fields, identity, is_last):
    before = snapshot(game)
    ordinary = game.state.snapshot("ordinary")
    response = invoke(game, path, **fields, isLast=is_last)
    expected = type(before)()
    expected.CopyFrom(before)
    expected.stories.add(storyId=identity, statusType=2)
    assert snapshot(game) == expected
    assert not response.rewards and not response.commonResponse.updatedData.HasField("balance")
    assert response.commonResponse.updatedData.stories[0].storyId == identity
    assert response.commonResponse.updatedData.stories[0].statusType == 2
    saved = dump(game)
    assert invoke(game, path, **fields, isLast=not is_last) == response
    restarted = module.MediaStories(game.schema, State(game.state.path), "media", game.master)
    request = game.schema.request_type(path)(**fields, isLast=is_last)
    assert restarted.handle(path, request.SerializeToString()) == response.SerializeToString()
    assert dump(game) == saved and game.state.snapshot("ordinary") == ordinary
    assert game.state.authenticated(game.token, "media")


def test_release_main_episode_is_free_unread_and_does_not_unread_a_completed_story(game):
    released = invoke(game, module._RELEASE, storyPartId="main-part", chapter=1, route=0, episode=1)
    assert released.commonResponse.updatedData.stories[0].statusType == 1
    assert snapshot(game).stories[0].statusType == 1
    assert (snapshot(game).balance.freeBalance, snapshot(game).balance.paidBalance) == (123, 45)
    saved = dump(game)
    assert invoke(game, module._RELEASE, storyPartId="main-part", chapter=1, route=0, episode=1) == released
    assert dump(game) == saved
    invoke(game, module._READ, storyId="media-main", isLast=True)
    saved = dump(game)
    released = invoke(game, module._RELEASE, storyPartId="main-part", chapter=1, route=0, episode=1)
    assert released.commonResponse.updatedData.stories[0].statusType == 2 and dump(game) == saved


def test_release_matches_proto_default_chapter_and_route_when_json_omits_them(game):
    chapter = game.rows["StoryPart"][0]["chapters"][0]
    del chapter["chapter"], chapter["route"]
    (game.master / "StoryPart.json").write_text(json.dumps(game.rows["StoryPart"]))
    response = invoke(game, module._RELEASE, storyPartId="main-part", chapter=0, route=0, episode=1)
    assert response.commonResponse.updatedData.stories[0].storyId == "media-main"
    assert snapshot(game).stories[0].statusType == 1


@pytest.mark.parametrize("path,fields", (
    (module._READ, {"storyId": "missing"}),
    (module._EVENT, {"eventStoryId": "event", "episode": 0}),
    (module._EVENT, {"eventStoryId": "missing", "episode": 1}),
    (module._EXTRA, {"extraStoryId": "extra", "episode": 99}),
    (module._RELEASE, {"storyPartId": "main-part", "chapter": 1, "route": 9, "episode": 1}),
))
def test_unknown_target_has_fixed_error_and_no_state_change(game, path, fields):
    before = dump(game)
    with pytest.raises(RpcFailure) as denied:
        invoke(game, path, **fields)
    assert denied.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == before


@pytest.mark.parametrize("corruption", ("missing-story", "orphan-extra", "bad-assets", "wrong-master", "duplicate-state"))
def test_corrupt_master_or_snapshot_never_partially_changes_the_media_profile(game, corruption):
    if corruption == "missing-story":
        game.rows["EventStory"][0]["episodes"][0]["storyId"] = "missing"
    elif corruption == "orphan-extra":
        game.rows["ExtraStoryPart"][0]["extraStoryIds"] = []
    elif corruption == "bad-assets":
        game.rows["Story"][0]["advAssetIds"] = []
    elif corruption == "wrong-master":
        (game.master / "!version.txt").write_text("unsupported")
    else:
        def duplicate(raw):
            value = game.schema.response_type(module._USER).FromString(raw)
            value.stories.add(storyId="media-main", statusType=1)
            value.stories.add(storyId="media-main", statusType=1)
            return value.SerializeToString()
        game.state.mutate_snapshot("media", game.schema.fingerprint, duplicate)
    for name, rows in game.rows.items():
        (game.master / (name + ".json")).write_text(json.dumps(rows))
    before = dump(game)
    with pytest.raises(RpcFailure) as denied:
        if corruption == "missing-story":
            invoke(game, module._LIST_EVENT)
        elif corruption == "orphan-extra":
            invoke(game, module._LIST_EXTRA)
        else:
            invoke(game, module._READ, storyId="media-main", isLast=True)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


def test_invalid_wire_and_unrelated_route_do_not_touch_state(game):
    before = dump(game)
    with pytest.raises(RpcFailure) as denied:
        game.handler.handle(module._READ, b"\x0a\x80")
    assert denied.value.code == RpcCode.INVALID_ARGUMENT
    assert game.handler.handle("/api.Pvp/Top", b"") is None
    assert dump(game) == before
