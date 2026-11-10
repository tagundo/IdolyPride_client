"""Story catalog fallbacks stay authenticated, account-specific and read-only."""
from contextlib import contextmanager
import json

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_story_catalog import game, schema


ROUTES = ("/api.Story/ListEvent", "/api.Story/ListExtra")
USER_GET = "/api.User/Get"
UNKNOWN_ROW = b"\xa0\x06\x07"
UNKNOWN_SNAPSHOT = b"\x80\x4b\x7b"


def database(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


@pytest.fixture
def accounts(game):
    catalog, state, master, _rows, token = game
    story_id = json.loads((master / "Story.json").read_text())[0]["id"]

    def preserve_read_story(payload):
        snapshot = catalog.schema.response_type(USER_GET).FromString(payload)
        story = next((row for row in snapshot.stories if row.storyId == story_id), None)
        if story is None:
            story = snapshot.stories.add(storyId=story_id)
        story.statusType = 2  # UserStoryStatusType.Read, independent of eligibility.
        story.MergeFromString(UNKNOWN_ROW)
        snapshot.MergeFromString(UNKNOWN_SNAPSHOT)
        return snapshot.SerializeToString()

    payload = state.mutate_snapshot("player", catalog.schema.fingerprint, preserve_read_story,
                                    setting_info=b"existing private settings\x00")
    state.save_snapshot("other", payload, catalog.schema.fingerprint)
    other_token, _ = state.login("other")
    return game, other_token, story_id


@contextmanager
def connected(game, fixture_directory, *, profile="player", token=None):
    catalog, state, master, _rows, default_token = game
    application = Application(catalog.schema, state, FixtureStore(fixture_directory, catalog.schema),
                              profile=profile, master_dir=master)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)

            def invoke(path, *, raw=b"", authenticated=True):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                           response_deserializer=codec.decode)
                metadata = (("x-auth-token", token or default_token),) if authenticated else ()
                return call(raw, metadata=metadata, timeout=3)

            yield invoke
    finally:
        server.stop()


def first_episode(response, path):
    if path == ROUTES[0]:
        return response.infos[0].episodes[0]
    return response.infos[0].stories[0].episodes[0]


@pytest.mark.parametrize("path", ROUTES)
def test_encrypted_story_lists_validate_auth_and_leave_read_progress_and_whole_database_unchanged(
        accounts, tmp_path, path):
    game, other_token, story_id = accounts
    catalog, state = game[:2]
    original = state.snapshot("player")
    snapshot = catalog.schema.response_type(USER_GET).FromString(original[0])
    read_story = next(row for row in snapshot.stories if row.storyId == story_id)
    assert read_story.statusType == 2 and UNKNOWN_ROW in read_story.SerializeToString()
    assert UNKNOWN_SNAPSHOT in original[0]
    before = database(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(path, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(path, raw=b"\x0a\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        for raw in (b"", b"\x08\x07", b""):
            response = catalog.schema.response_type(path).FromString(invoke(path, raw=raw))
            assert response.infos and first_episode(response, path).unlocked
            assert response.HasField("commonResponse")
            assert response.commonResponse.HasField("updatedData")
            assert response.commonResponse.HasField("deletedData")
            assert not response.commonResponse.updatedData.ListFields()
            assert not response.commonResponse.deletedData.ListFields()
        assert invoke(USER_GET) == original[0]
    assert state.snapshot("player") == original
    assert database(state) == before
    assert state.authenticated(game[4], "player") and state.authenticated(other_token, "other")


@pytest.mark.parametrize("path", ROUTES)
def test_account_fixture_locked_eligibility_precedes_public_fallback_without_affecting_other_account(
        accounts, tmp_path, path):
    game, other_token, _story_id = accounts
    catalog, state = game[:2]
    baseline = catalog.schema.response_type(path).FromString(catalog.handle(path, b""))
    assert first_episode(baseline, path).unlocked
    captured = catalog.schema.response_type(path)()
    captured.CopyFrom(baseline)
    first_episode(captured, path).unlocked = False
    if path == ROUTES[1]:
        captured.infos[0].unlocked = False
        captured.infos[0].stories[0].unlocked = False
    source, fixture_directory = tmp_path / "account-story.pb", tmp_path / "account-fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, fixture_directory, catalog.schema, path)
    before = database(state)
    with connected(game, fixture_directory) as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(path, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(path) == source.read_bytes()
    with connected(game, tmp_path / "other-fixtures", profile="other", token=other_token) as invoke:
        result = catalog.schema.response_type(path).FromString(invoke(path))
        assert first_episode(result, path).unlocked
    assert database(state) == before


def test_explicit_home_fixture_preserves_locked_story_rows_and_precedes_fallback_and_clock_creation(
        accounts, tmp_path):
    game = accounts[0]
    catalog, state = game[:2]
    path = "/api.Home/Enter"
    response = catalog.schema.response_type(path)()
    extra = catalog.schema.response_type(ROUTES[1]).FromString(catalog.handle(ROUTES[1], b""))
    response.extraStoryPartInfos.extend(extra.infos)
    response.extraStoryPartInfos[0].unlocked = False
    response.extraStoryPartInfos[0].stories[0].unlocked = False
    response.extraStoryPartInfos[0].stories[0].episodes[0].unlocked = False
    source, fixture_directory = tmp_path / "account-home.pb", tmp_path / "home-fixtures"
    source.write_bytes(response.SerializeToString())
    import_response(source, fixture_directory, catalog.schema, path)
    before = database(state)
    with connected(game, fixture_directory) as invoke:
        assert invoke(path) == source.read_bytes()
    assert database(state) == before


@pytest.mark.parametrize("empty", (False, True), ids=("locked-account-catalog", "explicit-empty-catalog"))
def test_dynamic_home_uses_account_extra_catalog_including_explicit_empty_without_writes(
        accounts, tmp_path, empty):
    game = accounts[0]
    catalog, state, master = game[:3]
    home_path, extra_path = "/api.Home/Enter", ROUTES[1]
    required_home_fields = {"currentMainAreaId", "hierarchyNotiInfo", "lessonProgress", "extraStoryPartInfos"}
    if not required_home_fields.issubset(catalog.schema.response_type(home_path).DESCRIPTOR.fields_by_name):
        pytest.skip("Minimal descriptor does not support dynamic Home.Enter")
    # Only genuine Home references are needed here. No Setting table means
    # ordinary lesson support cannot initialize a clock during this read.
    tables = {
        "Area": [{"id": "area-main-initial", "type": 1, "order": 1, "questIds": ["quest-initial"]}],
        "HierarchyGrade": [{"id": "grade-initial"}],
        "HierarchyDetailGrade": [{"id": "detail-initial", "hierarchyGradeId": "grade-initial",
                                  "requiredHierarchyPoint": 0, "requiredHierarchyRank": 0}],
    }
    for table, rows in tables.items():
        (master / (table + ".json")).write_text(json.dumps(rows))
    assert not (master / "Setting.json").exists()
    baseline = catalog.schema.response_type(extra_path).FromString(catalog.handle(extra_path, b""))
    assert baseline.infos and first_episode(baseline, extra_path).unlocked
    captured = catalog.schema.response_type(extra_path)()
    if not empty:
        captured.CopyFrom(baseline)
        captured.infos[0].unlocked = False
        captured.infos[0].stories[0].unlocked = False
        first_episode(captured, extra_path).unlocked = False
    captured.commonResponse.updatedData.SetInParent()
    captured.commonResponse.deletedData.SetInParent()
    source, fixture_directory = tmp_path / "account-extra.pb", tmp_path / "extra-only-fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, fixture_directory, catalog.schema, extra_path)
    fixtures = FixtureStore(fixture_directory, catalog.schema)
    assert fixtures.get(home_path, b"") is None
    before = database(state)
    original_snapshot = state.snapshot("player")
    with connected(game, fixture_directory) as invoke:
        observed_extra = catalog.schema.response_type(extra_path).FromString(invoke(extra_path))
        for _ in range(2):
            home = catalog.schema.response_type(home_path).FromString(invoke(home_path))
            assert home.currentMainAreaId == "area-main-initial"
            assert home.hierarchyNotiInfo.currentDetailGradeId == "detail-initial"
            assert [row.SerializeToString() for row in home.extraStoryPartInfos] == [
                row.SerializeToString() for row in observed_extra.infos]
            if empty:
                assert not home.extraStoryPartInfos
            else:
                assert not home.extraStoryPartInfos[0].unlocked
                assert not home.extraStoryPartInfos[0].stories[0].unlocked
                assert not home.extraStoryPartInfos[0].stories[0].episodes[0].unlocked
        assert invoke(USER_GET) == original_snapshot[0]
    assert database(state) == before


@pytest.mark.parametrize("empty", (False, True), ids=("locked-home-catalog", "explicit-empty-home"))
def test_home_only_account_fixture_controls_extra_list_without_copying_account_updates(
        accounts, tmp_path, empty):
    game = accounts[0]
    catalog, state = game[:2]
    home_path, extra_path = "/api.Home/Enter", ROUTES[1]
    baseline = catalog.schema.response_type(extra_path).FromString(catalog.handle(extra_path, b""))
    assert baseline.infos and first_episode(baseline, extra_path).unlocked
    captured = catalog.schema.response_type(home_path)()
    if not empty:
        captured.extraStoryPartInfos.extend(baseline.infos)
        captured.extraStoryPartInfos[0].unlocked = False
        captured.extraStoryPartInfos[0].stories[0].unlocked = False
        captured.extraStoryPartInfos[0].stories[0].episodes[0].unlocked = False
        # ListExtra may inherit only the eligibility DTOs, never unrelated
        # account updates stored in an explicit Home response fixture.
        captured.commonResponse.updatedData.user.name = "Private Home response update"
    source, fixture_directory = tmp_path / "account-home-only.pb", tmp_path / "home-only-fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, fixture_directory, catalog.schema, home_path)
    fixtures = FixtureStore(fixture_directory, catalog.schema)
    assert fixtures.get(extra_path, b"") is None
    if empty:
        assert source.read_bytes() == b""
    before = database(state)
    original_snapshot = state.snapshot("player")
    with connected(game, fixture_directory) as invoke:
        assert invoke(home_path) == source.read_bytes()
        for _ in range(2):
            response = catalog.schema.response_type(extra_path).FromString(invoke(extra_path))
            assert [row.SerializeToString() for row in response.infos] == [
                row.SerializeToString() for row in captured.extraStoryPartInfos]
            assert response.HasField("commonResponse")
            assert not response.commonResponse.updatedData.ListFields()
            assert not response.commonResponse.deletedData.ListFields()
        assert invoke(USER_GET) == original_snapshot[0]
    assert database(state) == before


def test_story_read_fails_closed_without_its_audited_schema_and_master_version(accounts, tmp_path):
    game, _other_token, story_id = accounts
    catalog, state = game[:2]
    path = "/api.Story/Read"
    request = catalog.schema.request_type(path)(storyId=story_id, isLast=True)
    before = database(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as unaudited:
            invoke(path, raw=request.SerializeToString())
        assert unaudited.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert database(state) == before
