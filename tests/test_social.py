"""Local inbox/social list contracts, independent of official account data."""
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.social import SocialInbox
from idoly_local.state import State


ROUTES = (
    "/api.Gift/List", "/api.Gift/ListHistory", "/api.Friend/List",
    "/api.Friend/ListApplying", "/api.Friend/ListApplied", "/api.Friend/Search",
)


def small_schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="social-test.proto", package="api", syntax="proto3")
    for name, values in (("GiftSortType", (0, 1, 2)), ("GiftFilterType", (0, 1, 2, 3, 4, 5, 999))):
        enum = file.enum_type.add(name=name)
        for number in values:
            enum.value.add(name=name + str(number), number=number)

    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, name, kind, repeated in fields:
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type = 14 if kind in ("GiftSortType", "GiftFilterType") else 11
                field.type_name = ".api." + kind

    for name in ("Empty", "UpdatedData", "DeletedData", "GiftRow", "ProfileRow"):
        message(name, ())
    message("CommonResponse", ((1, "updatedData", "UpdatedData", False), (2, "deletedData", "DeletedData", False)))
    message("GiftRequest", ((1, "offset", 5, False), (3, "sortType", "GiftSortType", False),
        (4, "filters", "GiftFilterType", True), (5, "desc", 8, False)))
    message("GiftResponse", ((1, "gifts", "GiftRow", True), (2, "hasNext", 8, False),
        (3, "count", 5, False), (9999, "commonResponse", "CommonResponse", False)))
    message("HistoryResponse", ((1, "gifts", "GiftRow", True), (9999, "commonResponse", "CommonResponse", False)))
    message("FriendResponse", ((1, "profiles", "ProfileRow", True), (9999, "commonResponse", "CommonResponse", False)))
    for name, methods in (
        ("System", (("Check", "Empty", "Empty"),)),
        ("Gift", (("List", "GiftRequest", "GiftResponse"), ("ListHistory", "Empty", "HistoryResponse"))),
        ("Friend", tuple((method, "Empty", "FriendResponse") for method in ("List", "ListApplying", "ListApplied", "Search"))),
    ):
        service = file.service.add(name=name)
        for name, request, response in methods:
            service.method.add(name=name, input_type=".api." + request, output_type=".api." + response)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("social-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


def call(schema, path, **values):
    request = schema.request_type(path)(**values)
    raw = SocialInbox(schema).handle(path, request.SerializeToString())
    assert raw is not None
    return schema.response_type(path).FromString(raw)


@pytest.mark.parametrize("path", ROUTES)
def test_empty_lists_have_complete_common_containers_without_account_updates(schema, path):
    response = call(schema, path)
    rows = response.gifts if path.startswith("/api.Gift/") else response.profiles
    assert not rows
    assert response.HasField("commonResponse")
    assert response.commonResponse.HasField("updatedData") and response.commonResponse.HasField("deletedData")
    assert not response.commonResponse.updatedData.ListFields() and not response.commonResponse.deletedData.ListFields()
    if path == "/api.Gift/List":
        assert response.count == 0 and response.hasNext is False


@pytest.mark.parametrize("offset", (0, 1, 100, (1 << 31) - 1))
@pytest.mark.parametrize("sort_type", (0, 1, 2))
def test_gift_empty_pagination_stays_exhausted_for_all_defined_sorts(schema, offset, sort_type):
    response = call(schema, "/api.Gift/List", offset=offset, sortType=sort_type, desc=True)
    assert not response.gifts and response.count == 0 and response.hasNext is False


def test_defined_gift_filter_values_and_duplicates_are_valid(schema):
    response = call(schema, "/api.Gift/List", filters=[0, 1, 2, 3, 4, 5, 999, 1])
    assert not response.gifts and not response.hasNext


@pytest.mark.parametrize("values", ({"offset": -1}, {"sortType": 3}, {"sortType": -1},
                                    {"filters": [6]}, {"filters": [999, 77]}, {"filters": [-1]}))
def test_invalid_offset_or_undefined_enum_is_explicitly_rejected(schema, values):
    with pytest.raises(RpcFailure) as error:
        call(schema, "/api.Gift/List", **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT


@pytest.mark.parametrize("path", ROUTES)
def test_malformed_protobuf_is_not_reported_as_an_empty_success(schema, path):
    with pytest.raises(RpcFailure) as error:
        SocialInbox(schema).handle(path, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT


def test_unknown_request_fields_remain_forward_compatible(schema):
    # An unknown field in google.protobuf.Empty is legal protobuf, not damage.
    raw = SocialInbox(schema).handle("/api.Friend/List", b"\x08\x07")
    assert not schema.response_type("/api.Friend/List").FromString(raw).profiles


def test_mutating_and_story_routes_remain_unsupported(schema):
    handler = SocialInbox(schema)
    for path in ("/api.Gift/Receive", "/api.Friend/Apply", "/api.Friend/Approve", "/api.Friend/Delete",
                 "/api.Friend/CancelAll", "/api.Story/ListEvent", "/api.Story/ListExtra", "/api.Story/Read"):
        assert handler.handle(path, b"") is None


def test_all_lists_leave_existing_local_profiles_sessions_and_snapshots_unchanged(schema, tmp_path):
    state = State(tmp_path / "profiles.sqlite")
    state.save_snapshot("local", b"opaque profile snapshot", schema.fingerprint, starter_version=4)
    token, _ = state.login("local")
    state.save_snapshot("other", b"another imported snapshot", schema.fingerprint)
    with state.connect() as db:
        before = tuple(db.iterdump())
    for path in ROUTES:
        call(schema, path)
    with state.connect() as db:
        assert tuple(db.iterdump()) == before
    assert state.authenticated(token, "local")
    assert state.snapshot("local")[0] == b"opaque profile snapshot"
