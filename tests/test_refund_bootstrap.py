"""Regression for the observed 6.1.1 pre-login refund schedule request.

Client logic: TitleView 0x5173e8c..0x5173ee8 treats zero interval bounds as
unbounded; TimeManager.IsBefore 0x45d1ee4 returns false for zero. The title
calls GetTerm at 0x517189c before Auth.Login, as observed on an Android device.
"""
from contextlib import contextmanager
from pathlib import Path

import grpc
import pytest
from google.protobuf import descriptor_pb2

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server as create_h2_server
from idoly_local.schema import Schema
from idoly_local.server import ServerConfig, create_server as create_grpc_server
from idoly_local.state import State


CHECK = "/api.System/Check"
TERM = "/api.Refund/GetTerm"
PAID = "/api.Refund/GetPaidStone"
LOGIN = "/api.Auth/Login"
USER = "/api.User/Get"
LOCAL_FUTURE = 4102444800000


def _minimal_schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="refund-boot-test.proto", package="api", syntax="proto3")

    def message(name, fields=()):
        result = file.message_type.add(name=name)
        for number, (name, kind) in enumerate(fields, 1):
            field = result.field.add(name=name, number=number, label=1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind

    message("Empty")
    message("Maintenance", [("inMaintenance", 8)])
    message("Review", [("inReview", 8)])
    message("CheckResponse", [("keepAliveTimeMilliseconds", 5), ("keepAliveTimeoutMilliseconds", 5),
                              ("maintenanceInfo", "Maintenance"), ("reviewInfo", "Review")])
    message("RefundPeriod", [("endDatetime", 3), ("startDatetime", 3), ("shopInvalidStartDatetime", 3)])
    message("PaidResponse", [("totalPaidStone", 9), ("refundRequestUrl", 9)])
    message("LoginRequest", [("firebaseIDToken", 9)])
    message("PublicUser", [("serverUserId", 9), ("publicUserId", 9)])
    message("LoginResponse", [("gameAuthToken", 9), ("userPublic", "PublicUser")])
    message("Manager", [("name", 9)])
    message("UserResponse", [("user", "Manager")])
    for name, methods in {"System": [("Check", "Empty", "CheckResponse")],
                          "Refund": [("GetTerm", "Empty", "RefundPeriod"), ("GetPaidStone", "Empty", "PaidResponse")],
                          "Auth": [("Login", "LoginRequest", "LoginResponse")],
                          "User": [("Get", "Empty", "UserResponse")]}.items():
        service = file.service.add(name=name)
        for name, request, response in methods:
            service.method.add(name=name, input_type=".api." + request, output_type=".api." + response)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("minimal", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "minimal":
        return _minimal_schema(tmp_path_factory.mktemp("refund-schema") / "schema.pb")
    descriptor = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(descriptor)


@contextmanager
def _server(transport, application, schema, state):
    if transport == "pure-h2":
        server = create_h2_server(application, port=0).start()
        port = server.port
    else:
        server, port = create_grpc_server(schema, application, ServerConfig(bind="127.0.0.1:0", state=state.path))
        server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            yield channel
    finally:
        if transport == "pure-h2":
            server.stop()
        else:
            assert server.stop(0).wait(timeout=3)


def _call(channel, schema, path, *, token=None, **fields):
    request = schema.request_type(path)(**fields).SerializeToString()
    metadata = (("x-auth-token", token),) if token else ()
    raw = channel.unary_unary(path)(codec.encode(request), metadata=metadata, timeout=3)
    return schema.response_type(path).FromString(codec.decode(raw))


def _data(state):
    with state.connect() as database:
        return tuple(database.iterdump())


def _client_refund_visible(start, end, now):
    return (start == 0 or now >= start) and (end == 0 or now <= end)


def _client_is_before(boundary, now):
    return boundary != 0 and now < boundary


@pytest.mark.parametrize("transport", ("pure-h2", "grpcio"))
@pytest.mark.parametrize("existing", (False, True))
def test_real_prelogin_boot_order_hides_refund_without_changing_account(tmp_path, schema, transport, existing):
    state = State(tmp_path / "state.db")
    old_token = None
    if existing:
        saved = schema.response_type(USER)()
        saved.user.name = "Preserved imported manager"
        state.save_snapshot("sandbox", saved.SerializeToString() + b"\x80\x4b\x7b", schema.fingerprint)
        old_token, _ = state.login("sandbox")
    before, original_snapshot, identity = _data(state), state.snapshot("sandbox"), state.profile("sandbox")
    app = Application(schema, state, FixtureStore(tmp_path / "fixtures", schema), profile="sandbox")
    with _server(transport, app, schema, state) as channel:
        # The real failing device issued these two anonymous calls before login.
        check = _call(channel, schema, CHECK)
        assert not check.maintenanceInfo.inMaintenance
        period = _call(channel, schema, TERM)
        assert (period.startDatetime, period.endDatetime, period.shopInvalidStartDatetime) == (LOCAL_FUTURE, LOCAL_FUTURE, 0)
        now = 1794182400000  # November 2026, Unix milliseconds.
        assert not _client_refund_visible(period.startDatetime, period.endDatetime, now)
        assert _client_refund_visible(0, 0, now), "Zero bounds recreate the client's unbounded refund window"
        assert not (not _client_is_before(period.startDatetime, now))  # CheckRefundStart is false.
        assert not _client_is_before(period.shopInvalidStartDatetime, now)  # Stone shop stays closed.
        assert _call(channel, schema, TERM) == period  # Anonymous retry is a read, too.
        for path in (PAID, USER):
            with pytest.raises(grpc.RpcError) as denied:
                _call(channel, schema, path)
            assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert _data(state) == before
        assert state.snapshot("sandbox") == original_snapshot
        assert state.profile("sandbox") == identity
        login = _call(channel, schema, LOGIN, firebaseIDToken="synthetic-local-identity")
        assert login.gameAuthToken.startswith("local-")
        assert state.authenticated(login.gameAuthToken, "sandbox")
        if existing:
            assert state.authenticated(old_token, "sandbox")
            assert state.profile("sandbox") == identity
            assert _call(channel, schema, USER, token=login.gameAuthToken).user.name == "Preserved imported manager"
        else:
            assert state.profile("sandbox") is not None
        with pytest.raises(grpc.RpcError) as unavailable:
            _call(channel, schema, PAID, token=login.gameAuthToken)
        assert unavailable.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert state.snapshot("sandbox") == original_snapshot
    assert State(state.path).snapshot("sandbox") == original_snapshot
