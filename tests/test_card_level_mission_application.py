"""Mission reads and enhancement deltas share the authenticated encrypted route."""
import grpc
import pytest

from idoly_local.catalog import import_response

from test_card_level_missions import ENHANCE, PATH, USER, dump, game, mission_game, row, schema
from test_story_application import connected


def test_list_then_enhance_updates_persisted_achievement_once(mission_game, tmp_path):
    game = mission_game
    provider, state = game[:2]
    before = dump(state)
    request = provider.schema.request_type(ENHANCE)(cardId="card-a", level=2).SerializeToString()
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(PATH, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(PATH, raw=b"\x0a\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        listed = provider.schema.response_type(PATH).FromString(invoke(PATH))
        assert len(listed.userMissions) == 1 and listed.userMissions[0] == row(game)
        assert dump(state) == before
        result = provider.schema.response_type(ENHANCE).FromString(invoke(ENHANCE, raw=request))
        assert len(result.commonResponse.updatedData.missions) == 1
        assert result.commonResponse.updatedData.missions[0].progress == 2
        committed = dump(state)
        assert not provider.schema.response_type(ENHANCE).FromString(
            invoke(ENHANCE, raw=request)).commonResponse.updatedData.missions
        assert dump(state) == committed
        listed = provider.schema.response_type(PATH).FromString(invoke(PATH))
        user = provider.schema.response_type(USER).FromString(invoke(USER))
        assert listed.userMissions[0] == user.missions[0] == row(game)
        assert dump(state) == committed


def test_explicit_mission_fixture_precedes_restricted_handler(mission_game, tmp_path):
    game = mission_game
    provider, state = game[:2]
    captured = provider.schema.response_type(PATH)()
    captured.userMissions.add(missionId="captured-mission", currentThreshold=17, progress=4, statusType=1)
    captured.commonResponse.SetInParent()
    source, directory = tmp_path / "mission.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, PATH)
    before = dump(state)
    with connected(game, directory) as invoke:
        with pytest.raises(grpc.RpcError) as failure:
            invoke(PATH, authenticated=False)
        assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH) == source.read_bytes()
    assert dump(state) == before
