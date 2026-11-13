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


@pytest.fixture
def company_game(game):
    rows = [{"id": "company-owned", "companyEnjoyStories": [
        {"number": 1, "storyId": "media-main"}, {"number": 2, "storyId": "media-extra"}]},
        {"id": "company-unowned", "companyEnjoyStories": [{"number": 1, "storyId": "media-event"}]}]
    (game.master / "Character.json").write_text(json.dumps(rows))
    value = snapshot(game)
    value.characters.add(characterId="company-owned", companyEnjoyPoint=123)
    game.state.mutate_snapshot("media", game.schema.fingerprint, lambda _: value.SerializeToString())
    return game


@pytest.mark.parametrize("is_last", (False, True))
def test_media_company_story_uses_actual_character_number_and_preserves_points_without_rewards(company_game, is_last):
    game = company_game
    before = snapshot(game)
    result = invoke(game, module._COMPANY, characterId="company-owned", number=1, isLast=is_last)
    after = snapshot(game)
    expected = type(before)()
    expected.CopyFrom(before)
    expected.stories.add(storyId="media-main", statusType=2)
    assert after.SerializeToString() == expected.SerializeToString()
    assert not result.rewards
    assert result.commonResponse.updatedData.stories[0].storyId == "media-main"
    saved = game.state.snapshot("media")
    invoke(game, module._COMPANY, characterId="company-owned", number=1, isLast=not is_last)
    assert game.state.snapshot("media") == saved


@pytest.mark.parametrize("character,number,code", (("company-owned", 9, RpcCode.INVALID_ARGUMENT),
    ("unknown", 1, RpcCode.INVALID_ARGUMENT), ("company-unowned", 1, RpcCode.PERMISSION_DENIED)))
def test_media_company_story_rejects_invalid_target_or_unowned_character_without_changes(company_game, character, number, code):
    before = dump(company_game)
    with pytest.raises(RpcFailure) as error:
        invoke(company_game, module._COMPANY, characterId=character, number=number, isLast=True)
    assert error.value.code == code and dump(company_game) == before


def test_media_company_story_malformed_reference_cannot_partly_mark_a_story_read(company_game):
    game = company_game
    (game.master / "Character.json").write_text(json.dumps([{"id": "company-owned",
        "companyEnjoyStories": [{"number": 1, "storyId": {"invalid": "reference"}}]}]))
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game, module._COMPANY, characterId="company-owned", number=1, isLast=True)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


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
        assert response.HasField("commonResponse")
        assert not response.commonResponse.HasField("updatedData")
        assert not response.commonResponse.HasField("deletedData")
        assert not response.commonResponse.updatedData.ListFields()
        assert not response.commonResponse.deletedData.ListFields()
    assert dump(game) == before


def test_event_gallery_preserves_real_groups_nonconsecutive_episodes_and_retry_progress(game):
    # The API's unlocked flags and the client's master-side gates are separate.
    # Its gallery overlay removes the latter; this server projection keeps the
    # real parent/episode IDs without rewriting the original master JSON.
    definitions = [
        {"id": "event-gated", "assetId": "actual-event-thumbnail", "viewConditionId": "expired-term",
         "episodes": [{"episode": 1, "storyId": "media-event", "viewConditionId": "expired-episode",
                       "unlockConditionId": "old-event-clear"},
                      {"episode": 3, "storyId": "media-main", "viewConditionId": "",
                       "unlockConditionId": "old-event-clear-3"}]},
        {"id": "event-other", "viewConditionId": "old-event-period",
         "episodes": [{"episode": 2, "storyId": "media-extra"}]},
    ]
    source = game.master / "EventStory.json"
    source.write_text(json.dumps(definitions))
    source_bytes = source.read_bytes()
    ordinary = game.state.snapshot("ordinary")
    before = dump(game)
    response = invoke(game, module._LIST_EVENT)
    assert [(row.id, [(episode.episode, episode.unlocked) for episode in row.episodes])
            for row in response.infos] == [("event-gated", [(1, True), (3, True)]),
                                         ("event-other", [(2, True)])]
    assert response.HasField("commonResponse")
    assert not response.commonResponse.HasField("updatedData")
    assert not response.commonResponse.HasField("deletedData")
    assert dump(game) == before
    read = invoke(game, module._EVENT, eventStoryId="event-gated", episode=3, isLast=True)
    current = snapshot(game)
    assert [(row.storyId, row.statusType) for row in current.stories] == [("media-main", 2)]
    assert list(read.commonResponse.updatedData.stories) == list(current.stories)
    assert not read.rewards and not read.commonResponse.updatedData.HasField("balance")
    saved = dump(game)
    assert invoke(game, module._EVENT, eventStoryId="event-gated", episode=3, isLast=False) == read
    assert dump(game) == saved and game.state.snapshot("ordinary") == ordinary
    assert source.read_bytes() == source_bytes


def test_extra_episode_reads_reuse_master_validation_without_building_menu_dtos(game, monkeypatch):
    game.rows["ExtraStory"][0]["episodes"].append({"episode": 2, "storyId": "media-event"})
    (game.master / "ExtraStory.json").write_text(json.dumps(game.rows["ExtraStory"]))
    original_episodes = game.handler._episodes
    validated = []

    def episodes(row):
        validated.append(row["id"])
        return original_episodes(row)

    def unexpected_menu(path):
        pytest.fail("Reading one episode must not build the complete story menu")

    monkeypatch.setattr(game.handler, "_episodes", episodes)
    monkeypatch.setattr(game.handler, "_lists", unexpected_menu)
    first = invoke(game, module._EXTRA, extraStoryId="extra", episode=1, isLast=True)
    assert first.commonResponse.updatedData.stories[0].storyId == "media-extra"
    assert validated == ["extra"]
    second = invoke(game, module._EXTRA, extraStoryId="extra", episode=2, isLast=True)
    assert second.commonResponse.updatedData.stories[0].storyId == "media-event"
    assert validated == ["extra"]
    assert {row.storyId for row in snapshot(game).stories} == {"media-extra", "media-event"}


@pytest.mark.parametrize("path", (module._LIST_EXTRA, module._EXTRA))
@pytest.mark.parametrize("damage", ("duplicate-link", "missing-extra", "wrong-parent", "orphan-extra",
    "duplicate-parent", "duplicate-extra", "duplicate-episode", "bad-episode-number", "missing-story"))
def test_extra_master_validation_is_shared_and_fails_before_profile_write(game, monkeypatch, path, damage):
    extras, parts = game.rows["ExtraStory"], game.rows["ExtraStoryPart"]
    if damage == "duplicate-link":
        parts[0]["extraStoryIds"].append("extra")
    elif damage == "missing-extra":
        parts[0]["extraStoryIds"].append("missing")
    elif damage == "wrong-parent":
        extras[0]["extraStoryPartId"] = "other-part"
    elif damage == "orphan-extra":
        parts[0]["extraStoryIds"] = []
    elif damage == "duplicate-parent":
        parts.append(dict(parts[0]))
    elif damage == "duplicate-extra":
        extras.append(dict(extras[0]))
    elif damage == "duplicate-episode":
        extras[0]["episodes"].append(dict(extras[0]["episodes"][0]))
    elif damage == "bad-episode-number":
        extras[0]["episodes"][0]["episode"] = True
    else:
        extras[0]["episodes"][0]["storyId"] = "missing-story"
    for name in ("ExtraStory", "ExtraStoryPart"):
        (game.master / (name + ".json")).write_text(json.dumps(game.rows[name]))
    before = dump(game)

    def unexpected_mutation(*args, **kwargs):
        pytest.fail("Invalid master links must fail before starting a profile mutation")

    monkeypatch.setattr(game.state, "mutate_snapshot", unexpected_mutation)
    with pytest.raises(RpcFailure) as denied:
        fields = {"extraStoryId": "extra", "episode": 1, "isLast": True} if path == module._EXTRA else {}
        invoke(game, path, **fields)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert game.handler._extra_catalog is None and dump(game) == before


def test_new_handler_revalidates_extra_master_generation_after_an_earlier_valid_read(game):
    invoke(game, module._EXTRA, extraStoryId="extra", episode=1, isLast=True)
    game.rows["ExtraStoryPart"][0]["extraStoryIds"] = []
    (game.master / "ExtraStoryPart.json").write_text(json.dumps(game.rows["ExtraStoryPart"]))
    game.handler = module.MediaStories(game.schema, State(game.state.path), "media", game.master)
    before = dump(game)
    with pytest.raises(RpcFailure) as denied:
        invoke(game, module._EXTRA, extraStoryId="extra", episode=1, isLast=True)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


def test_extra_retry_still_returns_current_full_story_with_unknown_fields_and_no_reward(game):
    value = snapshot(game)
    value.stories.add(storyId="media-extra", statusType=1, isPhotoShot=True).MergeFromString(UNKNOWN)
    game.state.mutate_snapshot("media", game.schema.fingerprint, lambda _: value.SerializeToString())
    first = invoke(game, module._EXTRA, extraStoryId="extra", episode=1, isLast=True)
    saved = dump(game)
    retry = invoke(game, module._EXTRA, extraStoryId="extra", episode=1, isLast=False)
    assert retry == first and dump(game) == saved
    assert retry.commonResponse.HasField("updatedData")
    assert retry.commonResponse.HasField("deletedData")
    row = retry.commonResponse.updatedData.stories[0]
    assert row.storyId == "media-extra" and row.statusType == 2 and row.isPhotoShot
    assert UNKNOWN in row.SerializeToString() and not retry.rewards


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
