"""Actual localhost gRPC exchanges against public and recovered client schemas."""

from contextlib import closing, contextmanager
import hashlib
import importlib
from pathlib import Path
import sqlite3
import sys

import grpc
import pytest
from google.protobuf import descriptor_pb2

from idoly_local import codec
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.schema import Schema
from idoly_local.server import Application, ServerConfig, create_server
from idoly_local.state import State


SOLIS_DIRECTORY = Path(__file__).resolve().parents[2] / "SolisClient"
CLIENT_DESCRIPTOR = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
SYSTEM_CHECK = "/api.System/Check"
AUTH_LOGIN = "/api.Auth/Login"
USER_GET = "/api.User/Get"
MASTER_GET = "/api.Master/Get"


@pytest.fixture(scope="module", params=("solis", "client-6.1.1"))
def schema_source(request):
    return request.param


@pytest.fixture(scope="module")
def schema(schema_source):
    if schema_source == "solis":
        if not SOLIS_DIRECTORY.is_dir():
            pytest.skip("Sibling SolisClient checkout is absent")
        return Schema.from_solis(SOLIS_DIRECTORY)
    if not CLIENT_DESCRIPTOR.is_file():
        pytest.skip("Recovered 6.1.1 descriptor set is absent")
    return Schema.from_descriptor_set(CLIENT_DESCRIPTOR)


@pytest.fixture(scope="module")
def upstream(schema, schema_source):
    if schema_source != "solis":
        pytest.skip("Upstream generated stubs are tested against their own Solis schema")
    # Generated stubs import their sibling marshaller by module name.
    sys.path.insert(0, str(SOLIS_DIRECTORY))
    try:
        return importlib.import_module("papi_grpc"), importlib.import_module("papi_pb2")
    finally:
        sys.path.remove(str(SOLIS_DIRECTORY))


@pytest.fixture
def user_fixture(tmp_path, schema):
    response = schema.response_type(USER_GET)()
    response.user.name = "Local manager"
    response.user.managerExp = 12345
    response.user.managerLevel = 7
    response.items.add(itemId="fixture-item", amount=42)
    response.profile.message = "Offline fixture"
    payload = response.SerializeToString()
    source = tmp_path / "user-response.pb"
    source.write_bytes(payload)
    directory = tmp_path / "fixtures"
    import_response(source, directory, schema, USER_GET)
    return FixtureStore(directory, schema), payload


@contextmanager
def running_server(schema, fixtures, state_path, profile="local"):
    application = Application(schema, State(state_path), fixtures, profile=profile)
    config = ServerConfig(bind="127.0.0.1:0", state=state_path, profile=profile)
    server, port = create_server(schema, application, config)
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=5)
            yield channel
    finally:
        assert server.stop(0).wait(timeout=5), "gRPC server did not stop"


def wire_call(channel, method, raw, metadata=()):
    return channel.unary_unary(method)(raw, timeout=5, metadata=metadata)


def rpc(channel, schema, method, request=None, token=None):
    if request is None:
        request = schema.request_type(method)()
    metadata = (("x-auth-token", token),) if token is not None else ()
    raw = wire_call(channel, method, codec.encode(request.SerializeToString()), metadata)
    return schema.response_type(method).FromString(codec.decode(raw))


def login(channel, schema):
    request = schema.request_type(AUTH_LOGIN)(firebaseIDToken="dummy-offline-test-token")
    return rpc(channel, schema, AUTH_LOGIN, request)


def test_encrypted_system_check_over_grpc(tmp_path, schema, user_fixture):
    fixtures, _ = user_fixture
    request = schema.request_type(SYSTEM_CHECK)(firebaseIDToken="dummy-check-token")
    encrypted = codec.encode(request.SerializeToString(), ticks=638660000001234567)
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        raw = wire_call(channel, SYSTEM_CHECK, encrypted)
    assert raw[:4] == b"\x0a\x00\x00\x08"
    response = schema.response_type(SYSTEM_CHECK).FromString(codec.decode(raw))
    assert response.keepAliveTimeMilliseconds == 60000
    assert response.keepAliveTimeoutMilliseconds == 20000
    assert response.maintenanceInfo.inMaintenance is False
    assert response.reviewInfo.inReview is False


def test_login_profile_and_session_survive_reopen_and_reject_other_profile(tmp_path, schema, user_fixture):
    fixtures, _ = user_fixture
    state_path = tmp_path / "state.db"
    with running_server(schema, fixtures, state_path, profile="first") as channel:
        original = login(channel, schema)
        assert original.gameAuthToken.startswith("local-")
        assert original.userPublic.serverUserId
        assert len(original.userPublic.publicUserId) == 12
        assert original.userPublic.publicUserId.isdecimal()
    # A new State and server must accept the previous process's local session.
    with running_server(schema, fixtures, state_path, profile="first") as channel:
        assert rpc(channel, schema, USER_GET, token=original.gameAuthToken).user.name == "Local manager"
        second = login(channel, schema)
        assert second.gameAuthToken != original.gameAuthToken
        assert second.userPublic == original.userPublic
    with running_server(schema, fixtures, state_path, profile="different") as channel:
        with pytest.raises(grpc.RpcError) as failure:
            rpc(channel, schema, USER_GET, token=original.gameAuthToken)
        assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        other = login(channel, schema)
        assert other.userPublic.serverUserId != original.userPublic.serverUserId
        assert rpc(channel, schema, USER_GET, token=other.gameAuthToken).user.managerLevel == 7
    with closing(sqlite3.connect(state_path)) as database:
        hashes = {row[0] for row in database.execute("SELECT token_hash FROM sessions")}
        assert hashlib.sha256(original.gameAuthToken.encode()).hexdigest() in hashes
        assert original.gameAuthToken not in hashes
        assert database.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 2


def test_user_get_replays_exact_validated_protobuf_bytes(tmp_path, schema, user_fixture):
    fixtures, expected = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        token = login(channel, schema).gameAuthToken
        raw = wire_call(channel, USER_GET, b"", (("x-auth-token", token),))
    assert codec.decode(raw) == expected
    response = schema.response_type(USER_GET).FromString(codec.decode(raw))
    assert response.items[0].itemId == "fixture-item"
    assert response.items[0].amount == 42


@pytest.mark.parametrize("token", [None, "local-invalid"])
def test_unauthenticated_user_get_is_rejected(tmp_path, schema, user_fixture, token):
    fixtures, _ = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        with pytest.raises(grpc.RpcError) as failure:
            rpc(channel, schema, USER_GET, token=token)
    assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_unknown_method_is_unimplemented(tmp_path, schema, user_fixture):
    fixtures, _ = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        with pytest.raises(grpc.RpcError) as failure:
            wire_call(channel, "/api.User/UnknownMethod", b"")
    assert failure.value.code() == grpc.StatusCode.UNIMPLEMENTED


@pytest.mark.parametrize("raw", [b"\x01", codec.encode(b"\x0a\x80")])
def test_malformed_transport_or_protobuf_is_invalid_argument(tmp_path, schema, user_fixture, raw):
    fixtures, _ = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        with pytest.raises(grpc.RpcError) as failure:
            wire_call(channel, SYSTEM_CHECK, raw)
    assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_master_without_archive_or_fixture_is_unimplemented(tmp_path, schema, user_fixture):
    fixtures, _ = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        token = login(channel, schema).gameAuthToken
        with pytest.raises(grpc.RpcError) as failure:
            rpc(channel, schema, MASTER_GET, token=token)
    assert failure.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_solis_generated_stubs_interoperate_with_generic_server(tmp_path, schema, user_fixture, upstream):
    stubs, messages = upstream
    fixtures, expected = user_fixture
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        check = stubs.SystemStub(channel).Check(
            messages.SystemCheckRequest(firebaseIDToken="dummy-stub-token"), timeout=5,
        )
        assert check.keepAliveTimeMilliseconds == 60000
        auth = stubs.AuthStub(channel).Login(
            messages.AuthLoginRequest(firebaseIDToken="dummy-stub-token"), timeout=5,
        )
        response = stubs.UserStub(channel).Get(
            messages.Empty(), metadata=(("x-auth-token", auth.gameAuthToken),), timeout=5,
        )
    assert response.SerializeToString() == expected


def test_exported_descriptors_preserve_real_rpc_types(tmp_path, schema):
    descriptor_path = tmp_path / "schema.pb"
    schema.export(descriptor_path)
    imported = Schema.from_descriptor_set(descriptor_path)
    assert set(imported.methods) == set(schema.methods)
    assert imported.fingerprint == schema.fingerprint
    request = schema.request_type(AUTH_LOGIN)(firebaseIDToken="dummy-descriptor-token")
    imported_request = imported.request_type(AUTH_LOGIN).FromString(request.SerializeToString())
    assert imported_request.firebaseIDToken == "dummy-descriptor-token"
    assert imported.response_type(USER_GET).DESCRIPTOR.full_name == "api.UserGetResponse"


def test_unary_server_starts_with_streaming_descriptors_without_game_files(tmp_path):
    """Keep transport coverage runnable without either external schema artifact."""
    file = descriptor_pb2.FileDescriptorProto(name="minimal-server.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    for name, field in (("MaintenanceInfo", "inMaintenance"), ("ReviewInfo", "inReview")):
        message = file.message_type.add(name=name)
        message.field.add(name=field, number=1, type=8)
    response = file.message_type.add(name="SystemCheckResponse")
    response.field.add(name="maintenanceInfo", number=1, type=11, type_name=".api.MaintenanceInfo")
    response.field.add(name="reviewInfo", number=2, type=11, type_name=".api.ReviewInfo")
    response.field.add(name="keepAliveTimeMilliseconds", number=3, type=5)
    response.field.add(name="keepAliveTimeoutMilliseconds", number=4, type=5)
    system = file.service.add(name="System")
    system.method.add(name="Check", input_type=".api.Empty", output_type=".api.SystemCheckResponse")
    health = file.service.add(name="Health")
    health.method.add(name="Watch", input_type=".api.Empty", output_type=".api.Empty", server_streaming=True)
    health.method.add(name="Upload", input_type=".api.Empty", output_type=".api.Empty", client_streaming=True)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    descriptor_path = tmp_path / "minimal.pb"
    descriptor_path.write_bytes(descriptors.SerializeToString())
    minimal = Schema.from_descriptor_set(descriptor_path)
    fixtures = FixtureStore(tmp_path / "fixtures", minimal)
    with running_server(minimal, fixtures, tmp_path / "state.db") as channel:
        assert rpc(channel, minimal, SYSTEM_CHECK).keepAliveTimeMilliseconds == 60000
        for method in ("/api.Health/Watch", "/api.Health/Upload"):
            with pytest.raises(grpc.RpcError) as failure:
                wire_call(channel, method, b"")
            assert failure.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_user_get_uses_active_profile_snapshot(tmp_path, schema):
    from idoly_local.profiles import new_profile

    state_path = tmp_path / "state.db"
    state = State(state_path)
    new_profile(state, schema, "sandbox", "New local manager")
    new_profile(state, schema, "preserved", "Preserved manager")
    fixtures = FixtureStore(tmp_path / "fixtures", schema)
    for profile, expected in (("sandbox", "New local manager"), ("preserved", "Preserved manager")):
        with running_server(schema, fixtures, state_path, profile) as channel:
            session = login(channel, schema)
            user = rpc(channel, schema, USER_GET, token=session.gameAuthToken)
            assert user.user.name == expected
            if "userPublic" in user.DESCRIPTOR.fields_by_name:
                assert user.userPublic == session.userPublic


def test_snapshot_schema_mismatch_fails_before_replay(tmp_path, schema):
    response = schema.response_type(USER_GET)()
    response.user.name = "Different schema"
    state_path = tmp_path / "state.db"
    State(state_path).save_snapshot("local", response.SerializeToString(), "different-fingerprint")
    fixtures = FixtureStore(tmp_path / "fixtures", schema)
    with running_server(schema, fixtures, state_path) as channel:
        token = login(channel, schema).gameAuthToken
        with pytest.raises(grpc.RpcError) as failure:
            rpc(channel, schema, USER_GET, token=token)
        assert failure.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_title_screen_rule_fixture_does_not_require_login(tmp_path, schema):
    method = "/api.Master/Rule"
    response = schema.response_type(method)(text="Archived terms")
    source = tmp_path / "rule.pb"
    source.write_bytes(response.SerializeToString())
    import_response(source, tmp_path / "fixtures", schema, method)
    fixtures = FixtureStore(tmp_path / "fixtures", schema)
    with running_server(schema, fixtures, tmp_path / "state.db") as channel:
        assert rpc(channel, schema, method).text == "Archived terms"
