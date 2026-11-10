"""Audited story reads through authenticated, encrypted unary HTTP/2."""
import pytest
import grpc

from idoly_local.catalog import import_response

from test_story_application import connected, database
from test_story_reads import catalog_game, game, schema


USER = "/api.User/Get"
DIRECT = "/api.Story/Read"
EVENT = "/api.Story/ReadEvent"
EXTRA = "/api.Story/ReadExtra"
LIST_EXTRA = "/api.Story/ListExtra"
LIST_EVENT = "/api.Story/ListEvent"
HOME = "/api.Home/Enter"


def request(schema, path, *, is_last=True):
    values = ({"storyId": "story-b"} if path == DIRECT else
              {"eventStoryId": "event-a", "episode": 2} if path == EVENT else
              {"extraStoryId": "extra-a", "episode": 1})
    return schema.request_type(path)(**values, isLast=is_last).SerializeToString()


@pytest.mark.parametrize("path", (DIRECT, EVENT, EXTRA))
def test_three_read_routes_authenticate_validate_and_commit_only_local_state_over_http2(game, tmp_path, path):
    reader, state = game[:2]
    original = state.snapshot("player")[0]
    expected = reader.schema.response_type(USER).FromString(original)
    identity = "story-c" if path == EXTRA else "story-b"
    expected.stories.add(storyId=identity, statusType=2)
    if path != EXTRA:
        expected.balance.freeBalance += 30
    before = database(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(path, raw=request(reader.schema, path), authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(path, raw=b"\x0a\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert database(state) == before
        # Native isLast=false is a skip completion, not an incomplete start.
        response = reader.schema.response_type(path).FromString(
            invoke(path, raw=request(reader.schema, path, is_last=False)))
        assert response.commonResponse.updatedData.stories[0].storyId == identity
        assert response.commonResponse.updatedData.stories[0].statusType == 2
        assert response.commonResponse.HasField("deletedData")
        assert not response.commonResponse.deletedData.ListFields()
        if path == EXTRA:
            assert not response.rewards
            assert not response.commonResponse.updatedData.HasField("balance")
        else:
            reward, = response.rewards
            assert (reward.resourceType, reward.resourceId, reward.amountI64,
                    reward.beforeAmount, reward.afterAmount) == (15, "", 30, 100, 130)
            assert response.commonResponse.updatedData.balance == expected.balance
        assert invoke(USER) == expected.SerializeToString()
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert state.authenticated(game[4], "player")


def test_event_and_direct_routes_share_one_durable_first_read_reward_over_http2(game, tmp_path):
    reader, state = game[:2]
    with connected(game, tmp_path / "fixtures") as invoke:
        first = reader.schema.response_type(EVENT).FromString(invoke(EVENT, raw=request(reader.schema, EVENT)))
        assert len(first.rewards) == 1 and first.rewards[0].amountI64 == 30
        after_first = database(state)
        for path in (DIRECT, EVENT, DIRECT):
            retry = reader.schema.response_type(path).FromString(
                invoke(path, raw=request(reader.schema, path, is_last=False)))
            assert not retry.rewards
            assert (retry.commonResponse.updatedData.balance.freeBalance,
                    retry.commonResponse.updatedData.balance.paidBalance) == (130, 7)
        snapshot = reader.schema.response_type(USER).FromString(invoke(USER))
        assert len([row for row in snapshot.stories if row.storyId == "story-b"]) == 1
        assert database(state) == after_first


@pytest.mark.parametrize("source_path", (LIST_EXTRA, HOME), ids=("private-extra", "private-home"))
@pytest.mark.parametrize("empty", (False, True), ids=("locked", "explicit-empty"))
def test_private_extra_or_home_eligibility_blocks_both_leaf_and_extra_read_routes_without_writes(
        game, tmp_path, source_path, empty):
    reader, state = game[:2]
    captured = reader.schema.response_type(source_path)()
    if not empty:
        target = captured.infos if source_path == LIST_EXTRA else captured.extraStoryPartInfos
        part = target.add(id="part-a", unlocked=False)
        part.stories.add(id="extra-a", unlocked=False).episodes.add(episode=1, unlocked=False)
    source, directory = tmp_path / "account-eligibility.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, reader.schema, source_path)
    if empty:
        assert source.read_bytes() == b""
    before = database(state)
    original = state.snapshot("player")[0]
    with connected(game, directory) as invoke:
        effective = reader.schema.response_type(LIST_EXTRA).FromString(invoke(LIST_EXTRA))
        if empty:
            assert not effective.infos
        else:
            assert effective.infos[0].id == "part-a" and not effective.infos[0].unlocked
        direct = reader.schema.request_type(DIRECT)(storyId="story-c", isLast=True).SerializeToString()
        for path, raw in ((DIRECT, direct), (EXTRA, request(reader.schema, EXTRA))):
            with pytest.raises(grpc.RpcError) as denied:
                invoke(path, raw=raw)
            assert denied.value.code() == grpc.StatusCode.PERMISSION_DENIED
        assert invoke(USER) == original
    assert database(state) == before


def eligibility(reader, source_path, *, empty=False, locked=False, marker=None):
    result = reader.schema.response_type(source_path)()
    if not empty:
        list_path = LIST_EVENT if source_path == LIST_EVENT else LIST_EXTRA
        baseline = reader.schema.response_type(list_path).FromString(reader.public.handle(list_path, b""))
        target = result.extraStoryPartInfos if source_path == HOME else result.infos
        target.extend(baseline.infos)
        if locked:
            for parent in target:
                if source_path == LIST_EVENT:
                    for episode in parent.episodes:
                        episode.unlocked = False
                else:
                    parent.unlocked = False
                    for child in parent.stories:
                        child.unlocked = False
                        for episode in child.episodes:
                            episode.unlocked = False
    if marker is not None:
        result.commonResponse.updatedData.user.name = marker
        result.commonResponse.updatedData.balance.freeBalance = 999999
    return result


def add_fixture(reader, tmp_path, directory, source_path, result, *, scoped, name):
    source = tmp_path / (name + "-response.pb")
    source.write_bytes(result.SerializeToString())
    request_path = None
    if scoped:
        request_path = tmp_path / (name + "-request.pb")
        cls = reader.schema.request_type(source_path)
        raw = (cls(skipUpdate=True).SerializeToString() if source_path == HOME and
               "skipUpdate" in cls.DESCRIPTOR.fields_by_name else b"\x08\x01")
        assert raw
        request_path.write_bytes(raw)
    import_response(source, directory, reader.schema, source_path, request=request_path)


def read_targets(reader, source_path):
    if source_path == LIST_EVENT:
        return ((EVENT, request(reader.schema, EVENT)), (DIRECT, request(reader.schema, DIRECT)))
    direct = reader.schema.request_type(DIRECT)(storyId="story-c", isLast=True).SerializeToString()
    return ((EXTRA, request(reader.schema, EXTRA)), (DIRECT, direct))


@pytest.mark.parametrize("source_path", (HOME, LIST_EXTRA, LIST_EVENT))
@pytest.mark.parametrize("empty", (False, True), ids=("scoped-locked", "scoped-empty"))
def test_scoped_catalog_fixture_is_authoritative_for_reads_even_with_a_different_request(
        game, tmp_path, source_path, empty):
    reader, state = game[:2]
    directory = tmp_path / "scoped-fixtures"
    captured = eligibility(reader, source_path, empty=empty, locked=True)
    add_fixture(reader, tmp_path, directory, source_path, captured, scoped=True, name="scoped")
    before = database(state)
    original = state.snapshot("player")[0]
    with connected(game, directory) as invoke:
        for path, raw in read_targets(reader, source_path):
            with pytest.raises(grpc.RpcError) as denied:
                invoke(path, raw=raw)
            assert denied.value.code() == grpc.StatusCode.PERMISSION_DENIED
        assert invoke(USER) == original
    assert database(state) == before


@pytest.mark.parametrize("source_path", (HOME, LIST_EXTRA, LIST_EVENT))
@pytest.mark.parametrize("empty", (False, True), ids=("conflicting-lock", "conflicting-empty"))
def test_conflicting_requestless_and_scoped_permissions_fail_closed_instead_of_guessing_latest(
        game, tmp_path, source_path, empty):
    reader, state = game[:2]
    directory = tmp_path / "conflicting-fixtures"
    add_fixture(reader, tmp_path, directory, source_path, eligibility(reader, source_path),
                scoped=False, name="requestless")
    add_fixture(reader, tmp_path, directory, source_path,
                eligibility(reader, source_path, empty=empty, locked=True), scoped=True, name="scoped")
    before = database(state)
    with connected(game, directory) as invoke:
        for path, raw in read_targets(reader, source_path):
            with pytest.raises(grpc.RpcError) as ambiguous:
                invoke(path, raw=raw)
            assert ambiguous.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert database(state) == before


@pytest.mark.parametrize("source_path", (HOME, LIST_EXTRA, LIST_EVENT))
def test_equal_permissions_with_different_account_common_updates_are_accepted_without_copying_them(
        game, tmp_path, source_path):
    reader, state = game[:2]
    directory = tmp_path / "equivalent-fixtures"
    requestless = eligibility(reader, source_path, marker="PRIVATE_REQUESTLESS_UPDATE")
    scoped = eligibility(reader, source_path, marker="PRIVATE_SCOPED_UPDATE")
    if source_path == LIST_EVENT:
        scoped.infos[0].episodes.reverse()
    add_fixture(reader, tmp_path, directory, source_path, requestless, scoped=False, name="requestless")
    add_fixture(reader, tmp_path, directory, source_path, scoped, scoped=True, name="scoped")
    expected = reader.schema.response_type(USER).FromString(state.snapshot("player")[0])
    expected.stories.add(storyId="story-b" if source_path == LIST_EVENT else "story-c", statusType=2)
    if source_path == LIST_EVENT:
        expected.balance.freeBalance += 30
    path, raw = read_targets(reader, source_path)[0]
    with connected(game, directory) as invoke:
        response_raw = invoke(path, raw=raw)
        response = reader.schema.response_type(path).FromString(response_raw)
        assert not response.commonResponse.updatedData.HasField("user")
        assert b"PRIVATE_REQUESTLESS_UPDATE" not in response_raw
        assert b"PRIVATE_SCOPED_UPDATE" not in response_raw
        assert invoke(USER) == expected.SerializeToString()
    assert state.snapshot("player")[0] == expected.SerializeToString()
