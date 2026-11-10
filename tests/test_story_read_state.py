"""Story reads commit one local receipt and preserve unrelated account data."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from idoly_local.catalog import FixtureStore, import_response
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from idoly_local.story_catalog import StoryCatalog
from idoly_local.story_reads import StoryReads

from test_story_reads import catalog_game, game, schema


USER = "/api.User/Get"
EXTRA = "/api.Story/ReadExtra"
EVENT = "/api.Story/ReadEvent"
DIRECT = "/api.Story/Read"
ROW_UNKNOWN = b"\x80\x4b\x7b"
OUTER_UNKNOWN = b"\x88\x4b\x19"
WALLET_UNKNOWN = b"\x90\x4b\x23"


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def user(reader, state=None):
    state = state or reader.state
    return reader.schema.response_type(USER).FromString(state.snapshot("player")[0])


def story(snapshot, identity):
    return next(row for row in snapshot.stories if row.storyId == identity)


def mutate(game, change):
    reader, state = game[:2]

    def callback(raw):
        snapshot = reader.schema.response_type(USER).FromString(raw)
        change(snapshot)
        return snapshot.SerializeToString()

    return state.mutate_snapshot("player", reader.schema.fingerprint, callback)


def read(reader, path=EXTRA, *, is_last=True):
    values = ({"extraStoryId": "extra-a", "episode": 1} if path == EXTRA else
              {"eventStoryId": "event-a", "episode": 2} if path == EVENT else
              {"storyId": "story-b"})
    request = reader.schema.request_type(path)(**values, isLast=is_last)
    raw = reader.handle(path, request.SerializeToString())
    assert raw is not None
    return reader.schema.response_type(path).FromString(raw)


def reopened(game, *, state=None, fixtures=None, extra_fixture=None):
    original, original_state, master = game[:3]
    return StoryReads(original.schema, state or original_state, "player", master,
                      story_catalog=StoryCatalog(original.schema, master), fixtures=fixtures,
                      extra_fixture=extra_fixture)


@pytest.fixture
def preserved(game):
    reader, state = game[:2]

    def seed(snapshot):
        snapshot.balance.freeBalance, snapshot.balance.paidBalance = 73, 17
        snapshot.balance.MergeFromString(WALLET_UNKNOWN)
        for identity in ("story-b", "story-c"):
            rows = [row for row in snapshot.stories if row.storyId == identity]
            row = rows[0] if rows else snapshot.stories.add(storyId=identity)
            row.statusType = 1
            row.MergeFromString(ROW_UNKNOWN)
        kept = story(snapshot, "story-a")
        kept.statusType = 2
        kept.isInvalid = kept.isUseActivatePhotoShootingStoryTicket = kept.isPhotoShot = True
        kept.MergeFromString(ROW_UNKNOWN)
        snapshot.MergeFromString(OUTER_UNKNOWN)

    payload = mutate(game, seed)
    state.mutate_snapshot("player", reader.schema.fingerprint, lambda raw: raw,
                          setting_info=b"private existing settings\x00")
    state.mutate_lesson_snapshot("player", reader.schema.fingerprint,
                                lambda raw, _clock: (raw, b"opaque existing lesson clock\x00"))
    identity = state.ensure_profile("other")
    other = reader.schema.response_type(USER).FromString(payload)
    other.user.name = "Other account"
    other.userPublic.serverUserId = identity["server_id"]
    other.userPublic.publicUserId = identity["public_id"]
    state.save_snapshot("other", other.SerializeToString(), reader.schema.fingerprint)
    other_token, _identity = state.login("other")
    return game, other_token


def expected_after(game, identity, *, free_stone=0):
    reader, state = game[:2]
    expected = user(reader, state)
    story(expected, identity).statusType = 2
    expected.balance.freeBalance += free_stone
    return expected.SerializeToString()


def protected_rows(state):
    """Everything outside the one allowed primary snapshot write is stable."""
    with state.connect() as connection:
        return {table: [tuple(row) for row in connection.execute('SELECT * FROM "' + table + '" ORDER BY 1')]
                for table in ("profiles", "sessions", "profile_settings", "starter_profiles",
                              "profile_lesson_progress")}, state.snapshot("other")


@pytest.mark.parametrize("is_last", (False, True), ids=("skip", "end"))
def test_no_reward_end_or_skip_changes_only_one_story_receipt(preserved, is_last):
    game, other_token = preserved
    reader, state = game[:2]
    protected = protected_rows(state)
    expected = expected_after(game, "story-c")
    result = read(reader, is_last=is_last)
    assert not result.rewards
    assert state.snapshot("player")[0] == expected
    assert protected_rows(state) == protected
    before_retry = dump(state)
    assert not read(reader, is_last=not is_last).rewards
    assert dump(state) == before_retry
    assert state.authenticated(game[4], "player") and state.authenticated(other_token, "other")


@pytest.mark.parametrize("is_last", (False, True), ids=("skip", "end"))
def test_first_reward_uses_local_wallet_then_retry_and_restart_do_not_award_again(preserved, is_last):
    game, other_token = preserved
    reader, state = game[:2]
    protected = protected_rows(state)
    expected = expected_after(game, "story-b", free_stone=30)
    first = read(reader, EVENT, is_last=is_last)
    assert len(first.rewards) == 1
    reward = first.rewards[0]
    assert (reward.resourceType, reward.resourceId, reward.amountI64,
            reward.beforeAmount, reward.afterAmount) == (15, "", 30, 73, 103)
    assert state.snapshot("player")[0] == expected
    assert protected_rows(state) == protected
    before_retry = dump(state)
    assert not read(reader, DIRECT, is_last=not is_last).rewards
    restarted = State(state.path)
    assert not read(reopened(game, state=restarted), EVENT, is_last=is_last).rewards
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[4], "player") and restarted.authenticated(other_token, "other")


def test_concurrent_completions_and_cross_route_retries_commit_one_reward(preserved):
    game = preserved[0]
    reader, state = game[:2]
    protected = protected_rows(state)
    expected = expected_after(game, "story-b", free_stone=30)

    def finish(index):
        return read(reader, EVENT if index % 2 else DIRECT, is_last=bool(index % 3))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(finish, range(16)))
    assert sum(len(response.rewards) for response in results) == 1
    assert sum(reward.amountI64 for response in results for reward in response.rewards) == 30
    assert state.snapshot("player")[0] == expected
    assert len([row for row in user(reader).stories if row.storyId == "story-b"]) == 1
    assert protected_rows(state) == protected


def test_imported_read_receipt_keeps_all_flags_unknown_fields_and_wallet(preserved):
    game = preserved[0]
    reader, state = game[:2]
    previous = user(reader)
    kept = story(previous, "story-a")
    assert kept.statusType == 2
    assert kept.isInvalid and kept.isUseActivatePhotoShootingStoryTicket and kept.isPhotoShot
    assert ROW_UNKNOWN in kept.SerializeToString() and OUTER_UNKNOWN in previous.SerializeToString()
    assert WALLET_UNKNOWN in previous.balance.SerializeToString()
    request_type = reader.schema.request_type(DIRECT)
    before = dump(state)
    for is_last in (False, True):
        with pytest.raises(RpcFailure) as error:
            reader.handle(DIRECT, request_type(storyId="story-a", isLast=is_last).SerializeToString())
        assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(state) == before
    # Clearing only the invalid bit models an eligible, already-read imported
    # story. Its ticket/photo flags and every unknown field still remain intact.
    mutate(game, lambda snapshot: setattr(story(snapshot, "story-a"), "isInvalid", False))
    before = dump(state)
    for is_last in (False, True):
        raw = reader.handle(DIRECT, request_type(storyId="story-a", isLast=is_last).SerializeToString())
        assert not reader.schema.response_type(DIRECT).FromString(raw).rewards
    assert dump(state) == before


@pytest.mark.parametrize("damage", ("duplicate-story", "unknown-status", "negative-wallet"))
def test_invalid_stored_data_never_leaves_a_partial_read_receipt_or_reward(preserved, damage):
    game = preserved[0]
    reader, state = game[:2]

    def corrupt(snapshot):
        if damage == "duplicate-story":
            snapshot.stories.add().CopyFrom(story(snapshot, "story-b"))
        elif damage == "unknown-status":
            story(snapshot, "story-b").statusType = 99
        else:
            snapshot.balance.freeBalance = -1

    mutate(game, corrupt)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        read(reader, EVENT)
    assert error.value.code == (RpcCode.PERMISSION_DENIED if damage == "unknown-status"
                                else RpcCode.FAILED_PRECONDITION)
    assert dump(state) == before


@pytest.mark.parametrize("limit", ("configured-cap", "int32-cap"))
def test_reward_cap_failures_rollback_the_read_receipt_and_preserve_wallet(preserved, limit):
    game = preserved[0]
    reader, state, master = game[:3]
    setting_path = master / "Setting.json"
    settings = json.loads(setting_path.read_text())
    settings[0]["freeStoneLimit"] = 100 if limit == "configured-cap" else 1 << 31
    setting_path.write_text(json.dumps(settings))
    mutate(game, lambda snapshot: setattr(snapshot.balance, "freeBalance", 80 if limit == "configured-cap" else (1 << 31) - 11))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        read(reopened(game), EVENT)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


@pytest.mark.parametrize("empty", (False, True), ids=("locked", "explicit-empty"))
def test_account_extra_eligibility_denial_preserves_whole_database(preserved, tmp_path, empty):
    game = preserved[0]
    reader, state = game[:2]
    path = "/api.Story/ListExtra"
    catalog = reader.schema.response_type(path)()
    if not empty:
        part = catalog.infos.add(id="part-a", unlocked=False)
        part.stories.add(id="extra-a", unlocked=False).episodes.add(episode=1, unlocked=False)
    source, directory = tmp_path / "account-extra.pb", tmp_path / "account-fixtures"
    source.write_bytes(catalog.SerializeToString())
    import_response(source, directory, reader.schema, path)
    if empty:
        assert source.read_bytes() == b""
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        read(reopened(game, fixtures=FixtureStore(directory, reader.schema)))
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(state) == before


def test_valid_master_story_with_an_unaudited_reward_rule_is_not_granted(preserved):
    game = preserved[0]
    reader, state, master = game[:3]
    path = master / "Story.json"
    rows = json.loads(path.read_text())
    rows.append({"id": "story-outside-reward-scope", "rewardId": "unsupported-local-reward",
                 "advPlayTypes": [1], "advAssetIds": ["outside-reward-scope"]})
    path.write_text(json.dumps(rows))
    reward_path = master / "Reward.json"
    rewards = json.loads(reward_path.read_text()) if reward_path.is_file() else []
    rewards.append({"id": "unsupported-local-reward", "resources": [
        {"resourceType": 8, "resourceId": "", "amount": 7}]})
    reward_path.write_text(json.dumps(rewards))
    request = reader.schema.request_type(DIRECT)(storyId="story-outside-reward-scope", isLast=True)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        reopened(game).handle(DIRECT, request.SerializeToString())
    assert error.value.code == RpcCode.UNIMPLEMENTED
    assert dump(state) == before
