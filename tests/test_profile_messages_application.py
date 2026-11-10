"""Introductions use authenticated encrypted RPCs and retain fixture precedence."""
import grpc
import pytest

from idoly_local.catalog import import_response

from test_profile_messages import PATH, USER, dump, game, messages, schema, snapshot
from test_profile_names_application import connected


def test_message_change_requires_own_session_and_returns_persisted_profile(game, messages, tmp_path):
    provider, state, token, other_token = game
    raw = provider.schema.request_type(PATH)(message="新しい紹介文").SerializeToString()
    expected = snapshot(game)
    expected.profile.message = "新しい紹介文"
    before = dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        for auth in (None, "invalid", other_token):
            with pytest.raises(grpc.RpcError) as failure:
                invoke(PATH, raw, auth)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as invalid:
            invoke(PATH, provider.schema.request_type(PATH)(message="😀" * 31).SerializeToString())
        assert invalid.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert dump(state) == before
        result = provider.schema.response_type(PATH).FromString(invoke(PATH, raw, token))
        assert result.commonResponse.updatedData.profile == expected.profile
        assert invoke(USER) == expected.SerializeToString()
        saved = dump(state)
        assert provider.schema.response_type(PATH).FromString(invoke(PATH, raw)) == result
        assert dump(state) == saved


def test_message_fixture_precedes_handler_without_bypassing_auth(game, messages, tmp_path):
    provider, state = game[:2]
    captured = provider.schema.response_type(PATH)()
    captured.commonResponse.updatedData.profile.message = "Captured introduction"
    source, directory = tmp_path / "message.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, PATH)
    before = dump(state)
    with connected(game, directory) as invoke:
        with pytest.raises(grpc.RpcError) as failure:
            invoke(PATH, auth=None)
        assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH) == source.read_bytes()
    assert dump(state) == before
