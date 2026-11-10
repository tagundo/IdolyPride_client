"""The finite opening continuation crosses real encrypted HTTP/2 boundaries."""
from contextlib import contextmanager
import os
from pathlib import Path

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.gameplay import seed_starter_profile
from idoly_local.h2_server import create_server
from idoly_local.schema import Schema
from idoly_local.state import State
from idoly_local.tutorial_qa import run_tutorial_continuation, assert_tutorial_continuation_snapshot


@pytest.fixture
def continuation(tmp_path):
    descriptor = Path("data/protocol/idolypride-6.1.1.pb")
    directory = Path(os.environ.get("IDOLY_TEST_MASTER_DIR", "data/master-json"))
    if not descriptor.is_file() or not all((directory / (name + ".json")).is_file()
                                         for name in ("CardLevel", "ManagerLevel", "Consumption", "Message", "MessageGroup")):
        pytest.skip("Optional recovered 6.1.1 schema and progression master tables are unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    state = State(tmp_path / "state.db")
    seed_starter_profile(state, schema, "sandbox", directory, manager_name="Synthetic continuation QA")
    token, _ = state.login("sandbox")
    return schema, state, directory, token, tmp_path / "fixtures"


@contextmanager
def connected(values):
    schema, state, directory, token, fixtures = values
    server = create_server(Application(schema, state, FixtureStore(fixtures, schema),
                                      profile="sandbox", master_dir=directory), port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)

            def invoke(path, message, *, authenticated=True):
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                raw = call(message.SerializeToString(), timeout=3,
                           metadata=(("x-auth-token", token),) if authenticated else ())
                return schema.response_type(path).FromString(raw)

            yield invoke
    finally:
        server.stop()


def preserved(state):
    with state.connect() as db:
        return {table: db.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
                for table in ("profiles", "sessions", "profile_settings", "starter_profiles")}


def test_complete_continuation_and_transport_restart_reuse_original_session(continuation):
    schema, state, directory, token, _fixtures = continuation
    before = preserved(state)
    with connected(continuation) as invoke:
        receipt = run_tutorial_continuation(schema, invoke, directory, label="encrypted-http2")
    reopened = State(state.path)
    restarted = (schema, reopened, directory, token, continuation[-1])
    with connected(restarted) as invoke:
        user = invoke("/api.User/Get", schema.request_type("/api.User/Get")())
        assert_tutorial_continuation_snapshot(schema, user, receipt)
    assert preserved(reopened) == before
    assert reopened.authenticated(token, "sandbox")


@pytest.mark.parametrize("path", [
    "/api.Tutorial/ReceiveLessonReward", "/api.Card/Enhance", "/api.Deck/Save",
    "/api.Message/ListGroup", "/api.Message/Timeline", "/api.Message/Save", "/api.Message/Finish",
])
def test_continuation_actions_require_local_auth_before_reading_or_mutating(continuation, path):
    schema, state, _directory, _token, _fixtures = continuation
    before = state.snapshot("sandbox")
    with connected(continuation) as invoke:
        with pytest.raises(grpc.RpcError) as error:
            invoke(path, schema.request_type(path)(), authenticated=False)
        assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert state.snapshot("sandbox") == before


def test_explicit_authenticated_fixture_keeps_precedence_over_lesson_grant(continuation, tmp_path):
    schema, state, _directory, _token, fixtures = continuation
    path = "/api.Tutorial/ReceiveLessonReward"
    response = schema.response_type(path)()
    response.rewards.add(resourceType=8, amount=123)
    source = tmp_path / "explicit.pb"
    source.write_bytes(response.SerializeToString())
    import_response(source, fixtures, schema, path)
    before = state.snapshot("sandbox")
    with connected(continuation) as invoke:
        assert invoke(path, schema.request_type(path)()) == response
    assert state.snapshot("sandbox") == before
