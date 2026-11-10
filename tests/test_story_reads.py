"""Audited story completion uses local state, eligibility and exact rewards."""
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import story_read_rules as rules
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.story_reads import StoryReads
from test_story_catalog import game as catalog_game, small_schema as catalog_schema


READ = "/api.Story/Read"
EVENT = "/api.Story/ReadEvent"
EXTRA = "/api.Story/ReadExtra"
USER = "/api.User/Get"
STONE = "rd_auto;stone;;30"


def small_schema(path):
    catalog_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]

    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind

    owned = next(row for row in file.message_type if row.name == "OwnedStory")
    owned.field.add(name="isUseActivatePhotoShootingStoryTicket", number=5, label=1, type=8)
    message("Wallet", [("freeBalance", 5, False), ("paidBalance", 5, False)])
    for name in ("UserGetResponse", "UpdatedData"):
        target = next(row for row in file.message_type if row.name == name)
        next(row for row in target.field if row.name == "balance").type_name = ".api.Wallet"
    message("RewardResult", [(name, kind, False) for name, kind in (
        ("resourceType", 5), ("resourceId", 9), ("beforeAmount", 3), ("afterAmount", 3),
        ("amountI64", 3), ("isNew", 8), ("isTruncate", 8), ("isGift", 8))])
    message("StoryReadResponse", [("rewards", "RewardResult", True), ("commonResponse", "CommonResponse", False)])
    message("EventReadRequest", [("eventStoryId", 9, False), ("episode", 5, False), ("isLast", 8, False)])
    message("ExtraReadRequest", [("extraStoryId", 9, False), ("episode", 5, False), ("isLast", 8, False)])
    service = next(row for row in file.service if row.name == "Story")
    next(row for row in service.method if row.name == "Read").output_type = ".api.StoryReadResponse"
    for name, request in (("ReadEvent", "EventReadRequest"), ("ReadExtra", "ExtraReadRequest")):
        service.method.add(name=name, input_type=".api." + request, output_type=".api.StoryReadResponse")
    master = next(row for row in descriptors.file if row.package == "master")
    story = next(row for row in master.message_type if row.name == "Story")
    story.field.add(name="rewardId", number=4, label=1, type=9)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("story-read-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(catalog_game, schema, monkeypatch):
    catalog, state, master, rows, token = catalog_game
    for row in rows["Story"]:
        row["rewardId"] = "" if row["id"] == "story-c" else STONE
    rows["Setting"] = [{"id": 1, "freeStoneLimit": 9999999}]
    for name in ("Story", "Setting"):
        (master / (name + ".json")).write_text(json.dumps(rows[name]))
    monkeypatch.setattr(rules, "SCHEMA_SHA256", schema.fingerprint)
    monkeypatch.setattr(rules, "MASTER_VERSION", "fixture-story-master")
    monkeypatch.setattr(rules, "NO_REWARD_STORIES", frozenset(("story-c",)))
    monkeypatch.setattr(rules, "FREE_STONE_STORIES", frozenset(("story-a", "story-b")))

    def wallet(raw):
        snapshot = schema.response_type(USER).FromString(raw)
        snapshot.balance.freeBalance, snapshot.balance.paidBalance = 100, 7
        return snapshot.SerializeToString()

    state.mutate_snapshot("player", schema.fingerprint, wallet)
    return StoryReads(schema, state, "player", master, story_catalog=catalog), state, master, rows, token


def call(reader, path, **values):
    request = reader.schema.request_type(path)(**values)
    return reader.schema.response_type(path).FromString(reader.handle(path, request.SerializeToString()))


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("is_last", (False, True), ids=("skip", "end"))
def test_extra_no_reward_completion_and_retry(game, is_last):
    reader, state, *_ = game
    before = snapshot(game)
    response = call(reader, EXTRA, extraStoryId="extra-a", episode=1, isLast=is_last)
    after = snapshot(game)
    expected = type(before)()
    expected.CopyFrom(before)
    expected.stories.add(storyId="story-c", statusType=2)
    assert after == expected
    assert not response.rewards and not response.commonResponse.updatedData.HasField("balance")
    assert response.commonResponse.updatedData.stories[0].storyId == "story-c"
    assert response.commonResponse.updatedData.stories[0].statusType == 2
    assert response.commonResponse.HasField("deletedData")
    saved = dump(state)
    assert call(reader, EXTRA, extraStoryId="extra-a", episode=1, isLast=not is_last) == response
    assert dump(state) == saved and state.authenticated(game[4], "player")


@pytest.mark.parametrize("is_last", (False, True), ids=("skip", "end"))
def test_first_event_reward_is_additive_local_free_stone_once(game, is_last):
    reader, state, *_ = game
    before = snapshot(game)
    response = call(reader, EVENT, eventStoryId="event-a", episode=2, isLast=is_last)
    after = snapshot(game)
    expected = type(before)()
    expected.CopyFrom(before)
    expected.stories.add(storyId="story-b", statusType=2)
    expected.balance.freeBalance += 30
    assert after == expected
    reward, = response.rewards
    assert (reward.resourceType, reward.resourceId, reward.beforeAmount, reward.afterAmount, reward.amountI64) == (15, "", 100, 130, 30)
    assert not reward.isGift and not reward.isTruncate and not reward.isNew
    assert response.commonResponse.updatedData.balance == after.balance
    saved = dump(state)
    retry = call(reader, READ, storyId="story-b", isLast=not is_last)
    assert not retry.rewards and retry.commonResponse.updatedData.balance == after.balance
    assert dump(state) == saved


@pytest.mark.parametrize("path,values", (
    (READ, {"storyId": ""}), (READ, {"storyId": "missing"}),
    (EVENT, {"eventStoryId": "", "episode": 1}),
    (EVENT, {"eventStoryId": "event-a", "episode": 0}),
    (EVENT, {"eventStoryId": "event-a", "episode": 99}),
    (EVENT, {"eventStoryId": "missing", "episode": 1}),
    (EXTRA, {"extraStoryId": "missing", "episode": 1}),
    (EXTRA, {"extraStoryId": "extra-a", "episode": -1}),
))
def test_invalid_target_is_rejected_without_writes(game, path, values):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game[0], path, **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("path", (READ, EVENT, EXTRA))
def test_malformed_transport_rejected(game, path):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(path, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("layer", ("part", "story", "episode", "empty"))
@pytest.mark.parametrize("path", (READ, EXTRA))
def test_effective_extra_permission_is_authoritative_for_both_routes(game, layer, path):
    reader, state, *_ = game
    response = reader.schema.response_type("/api.Story/ListExtra").FromString(reader.public.handle("/api.Story/ListExtra", b""))
    if layer == "empty":
        raw = b""
    else:
        target = response.infos[0]
        if layer in ("story", "episode"):
            target = target.stories[0]
        if layer == "episode":
            target = target.episodes[0]
        target.unlocked = False
        raw = response.SerializeToString()
    reader.extra_fixture = lambda: raw
    before = dump(state)
    values = {"storyId": "story-c"} if path == READ else {"extraStoryId": "extra-a", "episode": 1}
    with pytest.raises(RpcFailure) as error:
        call(reader, path, **values)
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(state) == before


@pytest.mark.parametrize("change", ("unlisted", "changed-reward", "master-version", "schema", "broken-parent", "bad-episodes"))
def test_unsupported_or_corrupt_rules_fail_without_a_receipt(game, monkeypatch, change):
    reader, state, master, rows, _ = game
    code = RpcCode.FAILED_PRECONDITION
    if change == "unlisted":
        monkeypatch.setattr(rules, "NO_REWARD_STORIES", frozenset())
        code = RpcCode.UNIMPLEMENTED
    elif change == "changed-reward":
        rows["Story"][2]["rewardId"] = STONE
        (master / "Story.json").write_text(json.dumps(rows["Story"]))
        code = RpcCode.UNIMPLEMENTED
    elif change == "master-version":
        (master / "!version.txt").write_text("other-version")
    elif change == "schema":
        monkeypatch.setattr(rules, "SCHEMA_SHA256", "other-schema")
    elif change == "broken-parent":
        rows["ExtraStoryPart"][0]["extraStoryIds"] = []
        (master / "ExtraStoryPart.json").write_text(json.dumps(rows["ExtraStoryPart"]))
    else:
        rows["EventStory"][0]["episodes"] = ["broken"]
        (master / "EventStory.json").write_text(json.dumps(rows["EventStory"]))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(reader, READ, storyId="story-c")
    assert error.value.code == code
    assert dump(state) == before


def test_disabled_provider_is_lazy(game):
    assert StoryReads(None, None, None).handle(READ, b"bad") is None
    assert game[0].handle("/api.Story/Release", b"") is None


def test_read_retry_validates_negative_current_wallet_without_granting(game):
    reader, state, *_ = game

    def broken(raw):
        value = reader.schema.response_type(USER).FromString(raw)
        value.balance.freeBalance = -1
        return value.SerializeToString()

    state.mutate_snapshot("player", reader.schema.fingerprint, broken)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(reader, EVENT, eventStoryId="event-a", episode=1)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_pinned_rules_are_disjoint_and_bounded_to_the_audited_baseline():
    assert len(rules.NO_REWARD_STORIES) == 143
    assert len(rules.FREE_STONE_STORIES) == 282
    assert not rules.NO_REWARD_STORIES & rules.FREE_STONE_STORIES
    assert len(rules.NO_REWARD_STORIES | rules.FREE_STONE_STORIES) == 425
    assert all(isinstance(identity, str) and identity for identity in rules.NO_REWARD_STORIES | rules.FREE_STONE_STORIES)


def test_actual_pinned_catalog_master_and_rewards(tmp_path):
    """Optional local public artifacts independently cover every supported ID."""
    from idoly_local.story_catalog import StoryCatalog
    from idoly_local.state import State

    root = Path(__file__).resolve().parents[1]
    descriptor = root / "data/protocol/idolypride-6.1.1.pb"
    master = root / "data/master-json"
    if not master.is_dir():
        master = Path("/workspace/scratch/server0214-master-json")
    directory = root / "data/public-story"
    if not descriptor.is_file() or not master.is_dir() or not directory.is_dir():
        pytest.skip("Optional public client/master/catalog artifacts are unavailable")
    actual = Schema.from_descriptor_set(descriptor)
    catalog = StoryCatalog(actual, master)
    catalog.directory = directory
    rows = {table: {row["id"]: row for row in json.loads((master / (table + ".json")).read_text())}
            for table in ("Story", "EventStory", "ExtraStory")}
    assert (master / "!version.txt").read_text().strip() == rules.MASTER_VERSION
    identities = set()
    requests = []
    for path, table, field in (("/api.Story/ListEvent", "EventStory", "eventStoryId"),
                               ("/api.Story/ListExtra", "ExtraStory", "extraStoryId")):
        response = actual.response_type(path).FromString(catalog.handle(path, b""))
        infos = response.infos if table == "EventStory" else [info for part in response.infos for info in part.stories]
        for info in infos:
            episodes = {row["episode"]: row["storyId"] for row in rows[table][info.id]["episodes"]}
            for episode in info.episodes:
                identity = episodes[episode.episode]
                identities.add(identity)
                assert episode.unlocked
                requests.append((EVENT if table == "EventStory" else EXTRA,
                                 {field: info.id, "episode": episode.episode, "isLast": False}, identity))
    assert identities == rules.NO_REWARD_STORIES | rules.FREE_STONE_STORIES
    assert all(rows["Story"][identity]["rewardId"] == "" for identity in rules.NO_REWARD_STORIES)
    assert all(rows["Story"][identity]["rewardId"] == STONE for identity in rules.FREE_STONE_STORIES)
    state = State(tmp_path / "profiles.sqlite")
    state.ensure_profile("player")
    user = actual.response_type(USER)()
    user.user.name = "Local verification"
    user.balance.freeBalance, user.balance.paidBalance = 7, 11
    user.MergeFromString(b"\x80\x4b\x7b")
    state.save_snapshot("player", user.SerializeToString(), actual.fingerprint)
    reader = StoryReads(actual, state, "player", master, story_catalog=catalog)
    for path, values, identity in requests:
        response = call(reader, path, **values)
        assert response.commonResponse.updatedData.stories[0].storyId == identity
        assert len(response.rewards) == (1 if identity in rules.FREE_STONE_STORIES
                                         and identity not in {row.storyId for row in user.stories} else 0)
        user = actual.response_type(USER).FromString(state.snapshot("player")[0])
    assert len(user.stories) == 425 and all(story.statusType == 2 for story in user.stories)
    assert (user.balance.freeBalance, user.balance.paidBalance) == (7 + 282 * 30, 11)
    assert b"\x80\x4b\x7b" in user.SerializeToString()
