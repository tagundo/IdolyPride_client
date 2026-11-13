"""Outing gallery uses real scene joins without inventing rewards or progress."""
import json
from pathlib import Path

import pytest

from idoly_local.excursion import (Excursions, _LIST, _START, _WATCH, _FINISH, _CHECK,
                                   prepare_excursion, apply_excursion_access)
from idoly_local.media_access import MASTER_VERSION
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State

USER = "/api.User/Get"
UNKNOWN = b"\x80\x4b\x07"


@pytest.fixture(scope="module")
def schema():
    return Schema.from_descriptor_set(Path(__file__).resolve().parents[1]/"data/protocol/idolypride-6.1.1.pb")


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path/"master";master.mkdir()
    (master/"!version.txt").write_text(MASTER_VERSION)
    places=[dict(id=p,name=p,advAssetId="adv",idleCameraMotionAssetId="cam",backgroundAssetId="scene",
                 bgmAssetId="bgm",sceneLayoutAssetId="layout",notWearableCostumeTypeIds=["schl"],
                 advNotWearableCostumeTypeIds=[],finishAdvNotWearableCostumeTypeIds=[]) for p in ("park","pool")]
    settings=[];reactions=[]
    for character,place in (("char-a","park"),("char-a","pool"),("char-b","park"),("char-u","park")):
        costume="cos-"+character[-1]
        settings.append(dict(characterId=character,excursionPlaceId=place,advForceCostumeId=costume,
                             forceCostumeId=costume,finishAdvForceCostumeId=costume,minFocalLength=28,
                             defaultFocalLength=45,maxFocalLength=100,sceneLayoutPositionIndex=1))
        for number in range(3):
            reactions.append(dict(characterId=character,excursionPlaceId=place,number=number,motionAssetId="motion",
                                  unlockCostumeIds=[],unlockNotCostumeIds=[],unlockGazeNumbers=[]))
    tables={"Character":[{"id":f"char-{x}"} for x in ("a","b","u")],
            "Costume":[dict(id=f"cos-{x}",characterId=f"char-{x}",costumeTypeId="casl") for x in ("a","b","u")]
                       +[dict(id="cos-school",characterId="char-a",costumeTypeId="schl")],
            "Hair":[dict(id=f"hair-{x}",characterId=f"char-{x}",wearableCostumeIds=[],notWearableCostumeIds=[]) for x in ("a","b","u")],
            "Area":[dict(id="area-main-013",type=1,questIds=["quest-a","quest-b"])],
            "Quest":[dict(id=x,areaId="area-main-013") for x in ("quest-a","quest-b")],
            "ExcursionPlace":places,"ExcursionPlaceSetting":settings,"ExcursionGazeReaction":reactions}
    for table,rows in tables.items():(master/(table+".json")).write_text(json.dumps(rows))
    state=State(tmp_path/"state.db");snapshot=schema.response_type(USER)();snapshot.user.name="Gallery"
    snapshot.user.MergeFromString(UNKNOWN);snapshot.balance.freeBalance=123;snapshot.balance.paidBalance=45
    for key in ("a","b"):
        snapshot.characters.add(characterId="char-"+key)
        snapshot.costumes.add(costumeId="cos-"+key,checked=True)
        snapshot.hairs.add(hairId="hair-"+key,checked=True)
    snapshot.costumes.add(costumeId="cos-school",checked=True)
    snapshot.items.add(itemId="unrelated",amount=99);snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("gallery",snapshot.SerializeToString(),schema.fingerprint,starter_version=4)
    state.save_snapshot("ordinary",snapshot.SerializeToString(),schema.fingerprint)
    token,_=state.login("gallery")
    provider=Excursions(schema,state,"gallery",master,media_mode=True)
    return provider,state,master,tables,token


def call(game,path,**values):
    provider=game[0];request=provider.schema.request_type(path)(**values)
    raw=provider.handle(path,request.SerializeToString());assert raw is not None
    return provider.schema.response_type(path).FromString(raw)


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("gallery")[0])


def dump(game):
    with game[1].connect() as db:return tuple(db.iterdump())


def finish(game,**values):
    return call(game,_FINISH,**dict(gazeReactionNumbers=[1],costumeId="cos-a",hairId="hair-a",**values))


def test_original_places_and_style_check_are_read_only_and_have_no_empty_deltas(game):
    before=dump(game)
    result=call(game,_LIST,characterId="char-a")
    assert list(result.excursionPlaceIds)==["park","pool"]
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert call(game,_LIST,characterId="char-a")==result
    result=call(game,_CHECK,characterId="char-a",excursionPlaceId="park",costumeId="cos-a",hairId="hair-a")
    assert result.HasField("commonResponse") and not result.commonResponse.ListFields()
    assert dump(game)==before


@pytest.mark.parametrize("path,values,code",[
    (_LIST,{"characterId":"missing"},RpcCode.INVALID_ARGUMENT),
    (_LIST,{"characterId":"char-u"},RpcCode.PERMISSION_DENIED),
    (_START,{"characterId":"char-a","excursionPlaceId":"missing"},RpcCode.INVALID_ARGUMENT),
    (_CHECK,{"characterId":"char-a","excursionPlaceId":"park","costumeId":"cos-b","hairId":"hair-a"},RpcCode.INVALID_ARGUMENT),
    (_CHECK,{"characterId":"char-a","excursionPlaceId":"park","costumeId":"cos-school","hairId":"hair-a"},RpcCode.INVALID_ARGUMENT),
    (_WATCH,{"characterId":"char-a","excursionPlaceId":"park","number":0},RpcCode.INVALID_ARGUMENT),
    (_WATCH,{"characterId":"char-a","excursionPlaceId":"park","number":9},RpcCode.INVALID_ARGUMENT),
])
def test_invalid_or_unowned_requests_do_not_change_any_database_table(game,path,values,code):
    before=dump(game)
    with pytest.raises(RpcFailure) as caught:call(game,path,**values)
    assert caught.value.code==code and dump(game)==before


def test_visit_watches_and_finish_survive_restart_and_retry_without_grants(game):
    before=snapshot(game);ordinary=game[1].snapshot("ordinary")
    start=call(game,_START,characterId="char-a",excursionPlaceId="park")
    assert not start.rewardResults and not start.commonResponse.ListFields()
    assert snapshot(game)==before
    watched=call(game,_WATCH,characterId="char-a",excursionPlaceId="park",number=1)
    assert len(watched.commonResponse.updatedData.excursionGazeReactions)==1
    row=watched.commonResponse.updatedData.excursionGazeReactions[0]
    assert (row.characterId,row.excursionPlaceId,row.gazeReactionNumber)==("char-a","park",1)
    current=dump(game)
    assert call(game,_WATCH,characterId="char-a",excursionPlaceId="park",number=1)==watched
    assert dump(game)==current
    game[0]._plan=None
    reopened=Excursions(game[0].schema,State(game[1].path),"gallery",game[2],media_mode=True)
    request=game[0].schema.request_type(_FINISH)(gazeReactionNumbers=[1,2],costumeId="cos-a",hairId="hair-a")
    response=game[0].schema.response_type(_FINISH).FromString(reopened.handle(_FINISH,request.SerializeToString()))
    assert not response.rewardResults
    assert [x.gazeReactionNumber for x in response.commonResponse.updatedData.excursionGazeReactions]==[1,2]
    saved=dump(game)
    assert reopened.handle(_FINISH,request.SerializeToString())==response.SerializeToString()
    assert dump(game)==saved
    expected=type(before)();expected.CopyFrom(before)
    for number in (1,2):expected.excursionGazeReactions.add(characterId="char-a",excursionPlaceId="park",gazeReactionNumber=number)
    assert snapshot(game)==expected and game[1].snapshot("ordinary")==ordinary
    assert game[1].authenticated(game[4],"gallery") and game[1].starter_version("gallery")==4


def test_current_full_watch_row_unknown_fields_are_returned_on_retry_without_rewriting_bytes(game):
    call(game,_WATCH,characterId="char-a",excursionPlaceId="park",number=1)
    value=snapshot(game);value.excursionGazeReactions[0].MergeFromString(UNKNOWN)
    raw=UNKNOWN+value.SerializeToString()
    game[1].mutate_snapshot("gallery",game[0].schema.fingerprint,lambda _:raw)
    before=dump(game)
    result=call(game,_WATCH,characterId="char-a",excursionPlaceId="park",number=1)
    assert result.commonResponse.updatedData.excursionGazeReactions[0]==value.excursionGazeReactions[0]
    assert game[1].snapshot("gallery")[0]==raw and dump(game)==before


def test_empty_finish_is_valid_and_a_new_visit_can_be_opened_after_completion(game):
    call(game,_START,characterId="char-a",excursionPlaceId="park")
    response=call(game,_FINISH,costumeId="cos-a",hairId="hair-a")
    assert not response.rewardResults and not response.commonResponse.ListFields()
    call(game,_START,characterId="char-b",excursionPlaceId="park")
    response=call(game,_FINISH,costumeId="cos-b",hairId="hair-b",gazeReactionNumbers=[1])
    assert response.commonResponse.updatedData.excursionGazeReactions[0].characterId=="char-b"


@pytest.mark.parametrize("values",[
    dict(costumeId="cos-a",hairId="hair-a",gazeReactionNumbers=[1,1]),
    dict(costumeId="cos-a",hairId="hair-a",gazeReactionNumbers=[0]),
    dict(costumeId="cos-a",hairId="hair-a",gazeReactionNumbers=[99]),
    dict(costumeId="cos-b",hairId="hair-a",gazeReactionNumbers=[1]),
])
def test_invalid_finish_rolls_back_reactions_and_active_visit(game,values):
    call(game,_START,characterId="char-a",excursionPlaceId="park");before=dump(game)
    with pytest.raises(RpcFailure):call(game,_FINISH,**values)
    assert dump(game)==before
    assert finish(game).commonResponse.updatedData.excursionGazeReactions[0].gazeReactionNumber==1


def test_finish_without_a_visit_does_not_create_session_tables(game):
    before=dump(game)
    with pytest.raises(RpcFailure):finish(game)
    assert dump(game)==before


@pytest.mark.parametrize("path",[_LIST,_START,_WATCH,_FINISH,_CHECK])
def test_malformed_requests_are_rejected_before_any_state_change(game,path):
    before=dump(game)
    with pytest.raises(RpcFailure) as caught:game[0].handle(path,b"\x0a\x80")
    assert caught.value.code==RpcCode.INVALID_ARGUMENT and dump(game)==before


def test_normal_accounts_and_photo_creation_remain_outside_this_gallery_provider(game):
    provider=Excursions(game[0].schema,game[1],"ordinary",game[2])
    before=dump(game)
    for path in (_LIST,_START,_WATCH,_FINISH,_CHECK):assert provider.handle(path,b"\x0a\x80") is None
    assert game[0].handle("/api.Photo/CreateExcursionShootings",b"") is None
    assert dump(game)==before


def test_only_the_original_area_aggregate_is_raised_in_the_explicit_media_snapshot(game):
    plan=prepare_excursion(game[2]);value=snapshot(game)
    value.areas.add(areaId="other",clearQuestCount=1).MergeFromString(UNKNOWN)
    value.areas.add(areaId="area-main-013",clearQuestCount=1).MergeFromString(UNKNOWN)
    expected=type(value)();expected.CopyFrom(value);expected.areas[1].clearQuestCount=2
    assert apply_excursion_access(value,plan) and value==expected
    before=value.SerializeToString();assert not apply_excursion_access(value,plan)
    assert value.SerializeToString()==before


@pytest.mark.parametrize("damage",["missing-idle","duplicate-reaction","duplicate-setting","unknown-scene","wrong-force-owner","camera-order","missing-area-quest","orphan-gaze-dependency"])
def test_bad_original_joins_fail_before_media_account_changes(game,damage):
    tables=game[3]
    if damage=="missing-idle":tables["ExcursionGazeReaction"]=tables["ExcursionGazeReaction"][1:]
    elif damage=="duplicate-reaction":tables["ExcursionGazeReaction"].append(dict(tables["ExcursionGazeReaction"][0]))
    elif damage=="duplicate-setting":tables["ExcursionPlaceSetting"].append(dict(tables["ExcursionPlaceSetting"][0]))
    elif damage=="unknown-scene":tables["ExcursionPlaceSetting"][0]["excursionPlaceId"]="unknown"
    elif damage=="wrong-force-owner":tables["ExcursionPlaceSetting"][0]["forceCostumeId"]="cos-b"
    elif damage=="camera-order":tables["ExcursionPlaceSetting"][0]["minFocalLength"]=200
    elif damage=="missing-area-quest":tables["Quest"]=tables["Quest"][:1]
    else:tables["ExcursionGazeReaction"][1]["unlockGazeNumbers"]=[99]
    for name,rows in tables.items():(game[2]/(name+".json")).write_text(json.dumps(rows))
    before=dump(game)
    with pytest.raises(RpcFailure):call(game,_LIST,characterId="char-a")
    assert dump(game)==before


def test_cached_masters_never_cache_character_ownership(game):
    assert call(game,_LIST,characterId="char-a").excursionPlaceIds
    value=snapshot(game)
    del value.characters[:]
    game[1].mutate_snapshot("gallery",game[0].schema.fingerprint,lambda _:value.SerializeToString())
    before=dump(game)
    with pytest.raises(RpcFailure) as caught:call(game,_LIST,characterId="char-a")
    assert caught.value.code==RpcCode.PERMISSION_DENIED and dump(game)==before


def test_finish_rollback_keeps_the_active_visit_when_snapshot_write_fails(game):
    call(game,_START,characterId="char-a",excursionPlaceId="park")
    with game[1].connect() as db:
        db.executescript("CREATE TRIGGER reject_outing_snapshot BEFORE UPDATE ON snapshots "
                         "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END;")
    before=dump(game)
    with pytest.raises(RpcFailure):finish(game)
    assert dump(game)==before
    with game[1].connect() as db:db.execute("DROP TRIGGER reject_outing_snapshot")
    assert finish(game).commonResponse.updatedData.excursionGazeReactions[0].gazeReactionNumber==1


def test_finish_enforces_original_reaction_outfit_restrictions(game):
    game[3]["ExcursionGazeReaction"][1]["unlockNotCostumeIds"]=["cos-a"]
    (game[2]/"ExcursionGazeReaction.json").write_text(json.dumps(game[3]["ExcursionGazeReaction"]))
    call(game,_START,characterId="char-a",excursionPlaceId="park");before=dump(game)
    with pytest.raises(RpcFailure) as caught:finish(game)
    assert caught.value.code==RpcCode.INVALID_ARGUMENT and dump(game)==before
    assert not call(game,_FINISH,costumeId="cos-a",hairId="hair-a").rewardResults
