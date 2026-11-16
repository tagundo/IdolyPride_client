"""Original 6.1.1 messages with finite synthetic rules; no official traffic."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from idoly_local.love import Love, ROUTES, validate_progress
from idoly_local.rpc import RpcCode,RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State

ROOT=Path(__file__).resolve().parents[1]
EV="love-23-0514"
EXTRA="love-extra-25-0426"
E1="love-event-story-love-23-0514-001"
E2="love-event-story-love-23-0514-002"
END_BAD="love-end-test-bad"
END_GOOD="love-end-test-good"
POINT="item-love-23-0514-story"
PRESENT="item-love-23-0514-present"
BOOST="item-love-23-0514-lesson-boost"
NOW=1794840000000
RULES=hashlib.sha256(b"finite synthetic Love rules v1").hexdigest()
UNKNOWN=b"\xa0\x06\x07"


@pytest.fixture(scope="module")
def schema():
    return Schema.from_descriptor_set(ROOT/"data/protocol/idolypride-6.1.1.pb")


def settings(*events,start=NOW-1000,end=NOW+100000000):
    return {"schema":1,"revision":0,"love_events":[{"event_id":key,"start_time_ms":start,"end_time_ms":end}
            for key in sorted(events or (EV,))]}


def event():
    return {"loveId":EV,"name":"もし恋 Synthetic","description":"Original protocol, synthetic route",
        "simpleName":"QA","startTime":1,"unlockConditionId":"cd-clear-area-main-002",
        "bannerAssetId":"img_banner_l_event-love-test","assetId":EV,"expAssetId":"exp-"+EV,"baseType":1,
        "characterId":"char-rei","costumeId":"cos-rei-schl-00","characterAssetId":"img_chr_mem_rei","color":"68D2E9",
        "storyReadItemId":POINT,"presentItemId":PRESENT,"promoteItemId":BOOST,"lessonMaxHours":1,
        "lessonStepSeconds":10,"saveSlotCount":5,"eventMissionIds":[],"limitedEventMissionIds":[],
        "episodeUnlockLevels":{"1":1,"2":2},"hintUnlockLevels":{"1":2,"2":3},
        "levels":[{"loveId":EV,"level":1,"requiredExp":"0","lessonStepRewardExp":"14","lessonStepRewardStoryReadItemAmount":"4"},
                  {"loveId":EV,"level":2,"requiredExp":"20","lessonStepRewardExp":"14","lessonStepRewardStoryReadItemAmount":"4"},
                  {"loveId":EV,"level":3,"requiredExp":"100","lessonStepRewardExp":"14","lessonStepRewardStoryReadItemAmount":"4"}],
        "episodes":{E1:{"id":E1,"loveId":EV,"episode":1,"storyId":"st-love-test-001","assetId":"love-test-001","storyAssetId":"love_2305_01_01","consumptionItemAmount":0},
                    E2:{"id":E2,"loveId":EV,"episode":2,"storyId":"st-love-test-002","assetId":"love-test-002","storyAssetId":"love_2305_02_01","consumptionItemAmount":5}},
        "routes":{E1:{"groups":[{"index":1,"count":2,"best":2,"scores":[-5,5]},
                                      {"index":2,"count":2,"scores":[0,0],"requires":[{"group":1,"choice":2}]}],
                         "outcomes":[{"all":[{"group":1,"choice":1}],"ending":END_BAD}],"next":E2},
                  E2:{"groups":[{"index":1,"count":2,"best":1,"scores":[10,-10],"points":[1,0]}],
                      "branches":[{"group":1,"match":1,"otherwise":2,"all":[{"episode":E1,"group":1,"choice":2}]}],
                      "outcomes":[{"all":[],"minPoints":1,"ending":END_GOOD},{"all":[],"maxPoints":0,"ending":END_BAD}]}},
        "endings":[{"id":END_BAD,"name":"Bad test end","favorability":100},
                   {"id":END_GOOD,"name":"Good test end","favorability":200,"endRollAssetId":"test_end_roll"}],
        "inference_status":"reference_routes_inferred","source_grade":"synthetic_test_only"}


@pytest.fixture
def game(tmp_path,schema):
    master=tmp_path/"master-json";master.mkdir()
    definitions={"Condition":[{"id":"cd-clear-area-main-002","settings":[{"clearArea":{"areaId":"area-main-002"}}]}],
        "Area":[{"id":"area-main-002","questIds":["quest-main-002-001","quest-main-002-002"]}],
        "Item":[{"id":POINT,"type":9001,"value":1},{"id":PRESENT,"type":9002,"value":167},
                {"id":BOOST,"type":9003,"value":2}],"EventMission":[]}
    for name,rows in definitions.items():(master/(name+".json")).write_text(json.dumps(rows))
    clock=[NOW];state=State(tmp_path/"normal.db")
    snapshot=schema.response_type("/api.User/Get")()
    snapshot.user.name="QA";snapshot.user.managerLevel=1
    snapshot.userPublic.serverUserId="SYNTHETIC_SERVER";snapshot.userPublic.publicUserId="SYNTHETIC_PUBLIC"
    snapshot.areas.add(areaId="area-main-002",clearQuestCount=2)
    snapshot.items.add(itemId=POINT,amount=20)
    snapshot.items.add(itemId=POINT,amount=2,expiredTime=NOW+10000)
    snapshot.items.add(itemId=POINT,amount=9999,expiredTime=NOW-1)
    snapshot.items.add(itemId=PRESENT,amount=2)
    snapshot.items.add(itemId=BOOST,amount=2)
    snapshot.points.add(pointType=1,amount=777)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("player",snapshot.SerializeToString(),schema.fingerprint,server_id="SYNTHETIC_SERVER",
                        public_id="SYNTHETIC_PUBLIC",starter_version=7)
    state.save_snapshot("other",snapshot.SerializeToString(),schema.fingerprint,starter_version=7)
    token,_=state.login("player");other_token,_=state.login("other")
    plan={"schema":1,"schema_sha256":schema.fingerprint,"master_version":"synthetic-test",
          "ruleset_sha256":RULES,"events":{EV:event()}}
    love=Love(schema,state,"player",master,event_settings=settings(),clock=lambda:clock[0])
    love._prepared=plan
    return SimpleNamespace(love=love,state=state,master=master,clock=clock,schema=schema,plan=plan,
        token=token,other_token=other_token,original=snapshot.SerializeToString())


def invoke(game,method_name,**fields):
    path="/api.Love/"+method_name
    raw=game.schema.request_type(path)(**fields).SerializeToString()
    return game.schema.response_type(path).FromString(game.love.handle(path,raw))


def user(game):
    return game.schema.response_type("/api.User/Get").FromString(game.state.snapshot("player")[0])


def progress(game):
    return validate_progress(game.state.love_progress("player",EV)[0],EV)


def register(game):
    return invoke(game,"Register",loveId=EV,name="Manager")


def finish_first(game,*,bad=False):
    invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    choices=[{"groupIndex":1,"index":1 if bad else 2,"isValid":True}]
    if not bad:choices.append({"groupIndex":2,"index":1,"isValid":True})
    return invoke(game,"Finish",storyEpisodeId=E1,selectStoryChoiceInfos=choices,hintLevel=0)


def database(state):
    with state.connect() as db:return tuple(db.iterdump())


def test_default_disabled_is_lazy_even_with_minimal_schema_and_missing_catalog(tmp_path):
    love=Love(object(),object(),"player",tmp_path/"absent")
    assert love.home_info() is None and love._prepared is None
    assert love.handle("/api.Unknown/Get",b"garbage") is None
    with pytest.raises(RpcFailure) as stopped:love.handle("/api.Love/Title",b"")
    assert stopped.value.code==RpcCode.FAILED_PRECONDITION and love._prepared is None


def test_title_home_are_read_only_and_standard_extra_have_separate_entries(game):
    extra=copy.deepcopy(event());extra.update(loveId=EXTRA,baseType=2,titleAssetId="love-25-0426",assetId="love-25-0426")
    game.plan["events"][EXTRA]=extra;game.love.settings=settings(EV,EXTRA)
    before=database(game.state)
    title=invoke(game,"Title");assert [row.loveId for row in title.loveInfos]==[EV]
    assert title.loveInfos[0].isUnplayed and title.loveInfos[0].isUnlocked
    special=invoke(game,"TitleExtra",loveId=EXTRA)
    assert special.loveInfo.loveId==EXTRA and special.titleAssetId=="love-25-0426"
    home,entries=game.love.home_info()
    assert home.isViewable and home.isUnlocked and {row.id for row in entries}=={EV,EXTRA}
    assert next(row for row in entries if row.id==EXTRA).limitedExtraTitleAssetId=="love-25-0426"
    assert database(game.state)==before and not game.state.has_love_progress("player")


def test_registration_top_name_and_main_character_preserve_other_profile_sessions_unknowns(game):
    before_other=game.state.account_snapshot("other")
    registered=register(game)
    assert registered.commonResponse.updatedData.loves[0].loveId==EV
    assert progress(game)["lesson_anchor_ms"]==NOW and progress(game)["exp"]==0
    assert user(game).loves[0].hiddenFavorability==0 and not user(game).loves[0].isReadingStory
    top=invoke(game,"Top",loveId=EV)
    assert top.playerName=="Manager" and list(top.storyEpisodeIds)==[E1]
    assert top.lessonProgress.maxRewardTime==NOW+3600000 and not top.saveInfo.unlocked
    invoke(game,"UpdateName",loveId=EV,name="다른 이름")
    assert invoke(game,"Top",loveId=EV).playerName=="다른 이름"
    assert invoke(game,"GetMainCharacter",loveId=EV).mainCharacterInfo.characterId=="char-rei"
    assert game.state.account_snapshot("other")==before_other
    assert game.state.authenticated(game.token,"player") and game.state.authenticated(game.other_token,"other")
    assert UNKNOWN in game.state.snapshot("player")[0]
    before=database(game.state)
    with pytest.raises(RpcFailure) as stopped:register(game)
    assert stopped.value.code==RpcCode.ALREADY_EXISTS and database(game.state)==before


def test_first_episode_branch_end_unlocks_save_and_never_grants_stones(game):
    register(game);before=user(game);end=finish_first(game,bad=True)
    after=user(game)
    assert end.storyEndName=="Bad test end" and end.unlockSave and not end.rewards
    assert list(after.loves[0].unlockedLoveStoryEndIDs)==[END_BAD]
    assert after.loves[0].hiddenFavorability==0
    assert not after.loves[0].isReadingStory and progress(game)["path"]==[E1]
    assert after.points==before.points and after.balance==before.balance
    assert after.stories[0].storyId=="st-love-test-001" and after.stories[0].statusType==2
    assert end.commonResponse.updatedData.stories[0]==after.stories[0]
    assert not end.commonResponse.updatedData.points and not end.commonResponse.updatedData.balance.SerializeToString()
    # Inferred end bonuses are withheld on both the first clear and replay.
    second=finish_first(game,bad=True)
    assert not second.unlockSave and user(game).loves[0].hiddenFavorability==0


def test_start_restart_resume_charge_once_use_earliest_valid_stack_and_finish_route(game):
    register(game);finish_first(game)
    game.clock[0]+=20000;reward=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert reward.obtainExp==28 and reward.totalExp==28 and reward.rewards[0].amount==8
    # Extend the synthetic expiring stack so it is valid at the time of Start.
    def extend(raw):
        value=game.schema.response_type("/api.User/Get").FromString(raw)
        value.items[1].expiredTime=game.clock[0]+10000
        return value.SerializeToString()
    game.state.mutate_snapshot("player",game.schema.fingerprint,extend)
    initial=user(game)
    first=invoke(game,"Start",storyEpisodeId=E2,hintLevel=1)
    assert first.advBranchInfos[0].groupIndex==1 and first.advBranchInfos[0].index==1
    assert first.storyChoiceGroupInfos[0].existsObtainableFavorabilityDifference
    assert not any(row.isBestObtainableFavorability for row in first.storyChoiceGroupInfos[0].storyChoiceInfos)
    charged=user(game)
    assert charged.items[1].amount==0 and charged.items[0].amount==initial.items[0].amount-3
    invoke(game,"Start",storyEpisodeId=E2,hintLevel=1)
    invoke(game,"Restart",storyEpisodeId=E2,hintLevel=1)
    assert user(game).items==charged.items
    end=invoke(game,"Finish",storyEpisodeId=E2,hintLevel=1,
        selectStoryChoiceInfos=[{"groupIndex":1,"index":1,"isValid":True}])
    assert end.storyEndName=="Good test end" and end.endRollAssetId=="test_end_roll"
    assert user(game).loves[0].hiddenFavorability==0 and progress(game)["path"]==[E1]
    assert progress(game)["past_choices"][E2]["1"]==[1]
    before=database(game.state)
    with pytest.raises(RpcFailure):invoke(game,"Finish",storyEpisodeId=E2,hintLevel=1)
    assert database(game.state)==before


def test_invalid_forged_conditional_choices_and_unknown_ending_roll_back_everything(game):
    register(game);invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    original=database(game.state)
    for choices in ([{"groupIndex":1,"index":2,"isValid":True}],
        [{"groupIndex":1,"index":1,"isValid":True},{"groupIndex":2,"index":1,"isValid":True}],
        [{"groupIndex":1,"index":2,"isValid":True},{"groupIndex":1,"index":1,"isValid":True}],
        [{"groupIndex":1,"index":3,"isValid":True}]):
        with pytest.raises(RpcFailure) as stopped:
            invoke(game,"Finish",storyEpisodeId=E1,hintLevel=0,selectStoryChoiceInfos=choices)
        assert stopped.value.code==RpcCode.INVALID_ARGUMENT and database(game.state)==original
    game.plan["events"][EV]["routes"][E1]["outcomes"][0]["ending"]="unknown-ending"
    with pytest.raises(RpcFailure) as stopped:
        invoke(game,"Finish",storyEpisodeId=E1,hintLevel=0,
               selectStoryChoiceInfos=[{"groupIndex":1,"index":1,"isValid":True}])
    assert stopped.value.code==RpcCode.UNIMPLEMENTED and database(game.state)==original


def test_normal_save_load_rename_reset_roundtrip_and_reading_reset_preserve_end_history(game):
    register(game)
    with pytest.raises(RpcFailure):invoke(game,"Save",loveId=EV,slotNumber=1)
    finish_first(game,bad=True);finish_first(game)
    saved_choices=copy.deepcopy(progress(game)["choices"])
    invoke(game,"Save",loveId=EV,slotNumber=1)
    invoke(game,"UpdateSaveName",loveId=EV,slotNumber=1,name="첫 저장")
    assert invoke(game,"Top",loveId=EV).saveInfo.saveDataInfos[0].name=="첫 저장"
    invoke(game,"Reset",loveId=EV)
    assert progress(game)["path"]==[E1] and user(game).loves[0].hiddenFavorability==0
    restored=invoke(game,"Load",loveId=EV,slotNumber=1)
    assert list(restored.storyEpisodeIds)==[E1,E2] and progress(game)["choices"]==saved_choices
    assert user(game).loves[0].hiddenFavorability==0
    invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    with pytest.raises(RpcFailure):invoke(game,"Load",loveId=EV,slotNumber=1)
    invoke(game,"ResetReadingStoryStatus",loveId=EV)
    assert progress(game)["current"] is None and not user(game).loves[0].isReadingStory
    assert list(user(game).loves[0].unlockedLoveStoryEndIDs)==[END_BAD]


def test_actual_item_definitions_present_promote_and_lesson_clock_have_no_backfill_or_double_claim(game):
    register(game)
    no_time=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert no_time.obtainExp==0 and not no_time.rewards
    before=user(game)
    present=invoke(game,"Present",loveId=EV)
    assert present.hiddenFavorability==167 and user(game).items[3].amount==before.items[3].amount-1
    promoted=invoke(game,"PromoteLesson",loveId=EV)
    assert promoted.totalExp==168 and promoted.obtainExp==168 and promoted.rewards[0].amount==48
    assert user(game).items[4].amount==before.items[4].amount-1
    assert progress(game)["lesson_anchor_ms"]==NOW
    game.clock[0]+=10000
    received=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert received.obtainExp==14 and received.totalExp==182 and received.rewards[0].amount==4
    repeated=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert repeated.obtainExp==0 and not repeated.rewards
    game.clock[0]-=20000
    rolled=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert not rolled.rewards and progress(game)["lesson_anchor_ms"]==NOW+10000


def test_atomic_concurrent_reward_claim_and_sql_failure_preserve_inventory(game):
    register(game);game.clock[0]+=20000
    def claim(_):return invoke(game,"ReceiveLessonReward",loveId=EV).obtainExp
    with ThreadPoolExecutor(max_workers=2) as executor:assert sorted(executor.map(claim,range(2)))==[0,28]
    before=database(game.state)
    with game.state.connect() as db:
        db.execute("CREATE TRIGGER deny_love BEFORE UPDATE ON profile_love_progress BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    guarded=database(game.state)
    with pytest.raises(sqlite3.IntegrityError):invoke(game,"Present",loveId=EV)
    assert database(game.state)==guarded


def test_rule_changes_ambiguous_items_insufficient_cost_and_locked_conditions_fail_without_mutation(game):
    register(game);finish_first(game);game.clock[0]+=20000;invoke(game,"ReceiveLessonReward",loveId=EV)
    def remove(raw):
        value=game.schema.response_type("/api.User/Get").FromString(raw)
        for row in value.items:
            if row.itemId==POINT:row.amount=0
        return value.SerializeToString()
    game.state.mutate_snapshot("player",game.schema.fingerprint,remove)
    before=database(game.state)
    with pytest.raises(RpcFailure) as stopped:invoke(game,"Start",storyEpisodeId=E2,hintLevel=0)
    assert stopped.value.code==RpcCode.RESOURCE_EXHAUSTED and database(game.state)==before
    game.plan["ruleset_sha256"]="f"*64
    with pytest.raises(RpcFailure):invoke(game,"Top",loveId=EV)
    assert database(game.state)==before


def test_existing_imported_user_love_without_server_progress_is_never_repaired_or_erased(game):
    def seed(raw):
        value=game.schema.response_type("/api.User/Get").FromString(raw)
        love=value.loves.add(loveId=EV,hiddenFavorability=345,isReadingStory=True)
        love.unlockedLoveStoryEndIDs.append(END_BAD);love.MergeFromString(UNKNOWN)
        return value.SerializeToString()
    game.state.mutate_snapshot("player",game.schema.fingerprint,seed)
    before=database(game.state)
    assert not invoke(game,"Title").loveInfos[0].isUnplayed
    for name,fields in (("Register",{"loveId":EV,"name":"Manager"}),("Top",{"loveId":EV}),
                        ("Reset",{"loveId":EV}),("Start",{"storyEpisodeId":E1,"hintLevel":0})):
        with pytest.raises(RpcFailure):invoke(game,name,**fields)
        assert database(game.state)==before
    assert user(game).loves[0].hiddenFavorability==345 and UNKNOWN in user(game).loves[0].SerializeToString()


def test_disable_period_and_reenable_resume_exact_progress_without_seed_or_reset(game):
    register(game);finish_first(game)
    before=database(game.state);raw=game.state.love_progress("player",EV)
    game.love.settings=settings(end=NOW)
    assert game.love.home_info() is None
    with pytest.raises(RpcFailure):invoke(game,"Top",loveId=EV)
    assert database(game.state)==before
    reopened=Love(game.schema,game.state,"player",game.master,event_settings=settings(),clock=lambda:game.clock[0])
    reopened._prepared=game.plan;game.love=reopened
    assert list(invoke(game,"Top",loveId=EV).storyEpisodeIds)==[E1,E2]
    assert game.state.love_progress("player",EV)==raw


def test_media_viewer_cost_level_hint_save_and_full_end_ui_are_isolated_without_item_grants(game,tmp_path):
    normal_before=game.state.account_snapshot("player")
    media=State(tmp_path/"media.db")
    snapshot=game.schema.response_type("/api.User/Get")()
    snapshot.user.name="Media";snapshot.userPublic.serverUserId="MEDIA_SERVER";snapshot.userPublic.publicUserId="MEDIA_PUBLIC"
    existing=snapshot.loves.add(loveId=EV,hiddenFavorability=9)
    existing.unlockedLoveStoryEndIDs.append(END_BAD);existing.MergeFromString(UNKNOWN)
    media.save_snapshot("player",snapshot.SerializeToString(),game.schema.fingerprint)
    viewer=Love(game.schema,media,"player",game.master,event_settings=settings(),media_mode=True,clock=lambda:game.clock[0])
    viewer._prepared=game.plan
    media_game=SimpleNamespace(**{**vars(game),"state":media,"love":viewer})
    before=database(media)
    assert invoke(media_game,"Title").loveInfos[0].isUnplayed and database(media)==before
    register(media_game)
    assert progress(media_game)["exp"]==100 and user(media_game).loves[0].hiddenFavorability==9
    assert all(row.unlocked for row in invoke(media_game,"Top",loveId=EV).storyEndInfos)
    invoke(media_game,"Save",loveId=EV,slotNumber=1)
    finish_first(media_game)
    invoke(media_game,"Start",storyEpisodeId=E2,hintLevel=2)
    assert not user(media_game).items and not user(media_game).areas
    invoke(media_game,"Finish",storyEpisodeId=E2,hintLevel=2,
           selectStoryChoiceInfos=[{"groupIndex":1,"index":1,"isValid":True}])
    reward=invoke(media_game,"ReceiveLessonReward",loveId=EV)
    assert reward.obtainExp==0 and not reward.rewards and not user(media_game).items
    for action in ("Present","PromoteLesson"):
        frozen=database(media)
        with pytest.raises(RpcFailure):invoke(media_game,action,loveId=EV)
        assert database(media)==frozen
    assert UNKNOWN in user(media_game).loves[0].SerializeToString()
    assert game.state.account_snapshot("player")==normal_before
    old=media.love_progress("player",EV)
    new=Love(game.schema,media,"player",game.master,event_settings=settings(),media_mode=True,clock=lambda:game.clock[0])
    new._prepared=game.plan
    new.home_info()
    assert media.love_progress("player",EV)==old


@pytest.mark.parametrize("field,value",[("unknown","extra"),("schema",True),("love_id","../escape"),
    ("exp",-1),("promotion_day","2026-02-31"),("promotion_used",True),("path",[]),
    ("current",{"episode_id":"not-on-route","hint":0}), ("player_name","bad\nname")])
def test_pure_portable_progress_validation_is_exact_and_bounded(game,field,value):
    register(game);data=progress(game);data[field]=value
    with pytest.raises(ValueError,match="love_progress_invalid"):
        validate_progress(json.dumps(data).encode(),EV)


def test_duplicate_json_keys_and_oversize_progress_are_never_normalized(game):
    register(game);raw=game.state.love_progress("player",EV)[0]
    with pytest.raises(ValueError):validate_progress(raw[:-1]+b',"schema":1}',EV)
    with pytest.raises(ValueError):validate_progress(b"x"*(128*1024+1),EV)
    with pytest.raises(ValueError):validate_progress(raw,EXTRA)


def test_nested_user_love_unknowns_and_other_event_rows_survive_exact_deltas(game):
    register(game)
    def preserve(raw):
        value=game.schema.response_type("/api.User/Get").FromString(raw)
        value.loves[0].MergeFromString(UNKNOWN)
        unrelated=value.loves.add(loveId=EXTRA,hiddenFavorability=481)
        unrelated.MergeFromString(UNKNOWN)
        return value.SerializeToString()
    game.state.mutate_snapshot("player",game.schema.fingerprint,preserve)
    other=user(game).loves[1].SerializeToString()
    result=invoke(game,"Present",loveId=EV)
    assert UNKNOWN in result.commonResponse.updatedData.loves[0].SerializeToString()
    assert user(game).loves[1].SerializeToString()==other
    assert UNKNOWN in game.state.snapshot("player")[0]


def test_missing_preserved_adv_is_unsupported_before_cost_or_reading_mutation(game):
    register(game)
    game.plan["events"][EV]["episodes"][E1]["advEvidence"]={"available":False,"assetId":"missing-preserved-adv"}
    before=database(game.state)
    with pytest.raises(RpcFailure) as stopped:invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    assert stopped.value.code==RpcCode.UNIMPLEMENTED and database(game.state)==before


def test_title_remains_viewable_but_registration_cannot_bypass_normal_area_unlock(game):
    def lock(raw):
        value=game.schema.response_type("/api.User/Get").FromString(raw)
        value.areas[0].clearQuestCount=1
        return value.SerializeToString()
    game.state.mutate_snapshot("player",game.schema.fingerprint,lock)
    before=database(game.state)
    assert not invoke(game,"Title").loveInfos[0].isUnlocked
    with pytest.raises(RpcFailure) as stopped:register(game)
    assert stopped.value.code==RpcCode.PERMISSION_DENIED and database(game.state)==before


def test_finish_ignores_bounded_false_history_echoes_but_requires_single_active_selection(game):
    register(game);invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    result=invoke(game,"Finish",storyEpisodeId=E1,hintLevel=0,selectStoryChoiceInfos=[
        {"groupIndex":1,"index":1,"isValid":False},
        {"groupIndex":1,"index":2,"isValid":True},
        {"groupIndex":2,"index":2,"isValid":False},
        {"groupIndex":2,"index":1,"isValid":True}])
    assert not result.storyEndName and progress(game)["path"]==[E1,E2]
    assert progress(game)["choices"][E1]==[{"group":1,"index":2,"valid":True},
                                            {"group":2,"index":1,"valid":True}]
    assert user(game).loves[0].hiddenFavorability==0


def test_false_history_echoes_still_require_real_group_and_choice_bounds(game):
    register(game);invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    before=database(game.state)
    with pytest.raises(RpcFailure) as stopped:
        invoke(game,"Finish",storyEpisodeId=E1,hintLevel=0,selectStoryChoiceInfos=[
            {"groupIndex":1,"index":100,"isValid":False},
            {"groupIndex":1,"index":1,"isValid":True}])
    assert stopped.value.code==RpcCode.INVALID_ARGUMENT and database(game.state)==before


def test_lesson_claim_uses_preclaim_level_rates_across_threshold_without_invented_exp_cap(game):
    game.plan["events"][EV]["levels"][1].update(lessonStepRewardExp="100",lessonStepRewardStoryReadItemAmount="50")
    register(game);game.clock[0]+=30000
    received=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert received.obtainExp==42 and received.totalExp==42 and received.rewards[0].amount==12
    # The next claim starts at level2 and can legitimately exceed the highest
    # level's requiredExp threshold. No fake 100-EXP cap truncates that grant.
    game.clock[0]+=10000
    received=invoke(game,"ReceiveLessonReward",loveId=EV)
    assert received.obtainExp==100 and received.totalExp==142 and received.rewards[0].amount==50


def test_lesson_signed_amount_overflow_rolls_back_clock_experience_and_inventory(game):
    register(game)
    def huge(snapshot_raw,progress_raw):
        data=validate_progress(progress_raw,EV);data["exp"]=(1<<63)-5
        return snapshot_raw,json.dumps(data).encode()
    game.state.mutate_love_snapshot("player",game.schema.fingerprint,EV,RULES,huge)
    game.clock[0]+=10000;before=database(game.state)
    with pytest.raises(RpcFailure) as stopped:invoke(game,"ReceiveLessonReward",loveId=EV)
    assert stopped.value.code==RpcCode.OUT_OF_RANGE and database(game.state)==before


def test_extra_only_schedule_keeps_dedicated_entry_and_hides_empty_standard_title_menu(game):
    extra=copy.deepcopy(event());extra.update(loveId=EXTRA,baseType=2,titleAssetId="love-25-0426",assetId="love-25-0426")
    game.plan["events"][EXTRA]=extra;game.love.settings=settings(EXTRA)
    home,entries=game.love.home_info()
    assert not home.isViewable and not home.isUnlocked and not home.existsUnplayedLove
    assert len(entries)==1 and entries[0].id==EXTRA and entries[0].isUnlocked
    assert entries[0].isUnplayed and entries[0].limitedExtraTitleAssetId=="love-25-0426"
    assert not invoke(game,"Title").loveInfos
    assert invoke(game,"TitleExtra",loveId=EXTRA).loveInfo.loveId==EXTRA


def test_mixed_schedule_extra_notifications_do_not_leak_into_standard_aggregate(game):
    register(game)
    extra=copy.deepcopy(event());extra.update(loveId=EXTRA,baseType=2,titleAssetId="love-25-0426",assetId="love-25-0426")
    game.plan["events"][EXTRA]=extra;game.love.settings=settings(EV,EXTRA)
    home,entries=game.love.home_info()
    assert home.isViewable and home.isUnlocked and not home.existsUnplayedLove
    assert not next(row for row in entries if row.id==EV).isUnplayed
    assert next(row for row in entries if row.id==EXTRA).isUnplayed


def test_media_viewer_never_reports_a_full_reward_notification(game,tmp_path):
    media=State(tmp_path/"media-notification.db")
    snapshot=game.schema.response_type("/api.User/Get")();snapshot.user.name="Viewer"
    media.save_snapshot("player",snapshot.SerializeToString(),game.schema.fingerprint)
    viewer=Love(game.schema,media,"player",game.master,event_settings=settings(),media_mode=True,clock=lambda:game.clock[0])
    viewer._prepared=game.plan
    local=SimpleNamespace(**{**vars(game),"state":media,"love":viewer})
    register(local);game.clock[0]+=7200000
    title=invoke(local,"Title");home,entries=viewer.home_info()
    assert not title.loveInfos[0].isLessonRewardMax
    assert not home.existsLessonRewardMaxLove and not entries[0].isLessonRewardMax
    assert not user(local).items


def test_start_keeps_all_unlocked_hint_metadata_when_current_local_display_is_off(game):
    register(game);invoke(game,"PromoteLesson",loveId=EV)
    game.plan["events"][EV]["routes"][E1]["groups"][1]["best"]=1
    result=invoke(game,"Start",storyEpisodeId=E1,hintLevel=0)
    assert result.storyChoiceGroupInfos[0].existsObtainableFavorabilityDifference
    assert result.storyChoiceGroupInfos[0].storyChoiceInfos[1].isBestObtainableFavorability
    # best is pinned route metadata, not recomputed from potentially tied
    # compatibility scores. The client controls whether it displays the hint.
    assert result.storyChoiceGroupInfos[1].existsObtainableFavorabilityDifference
    assert result.storyChoiceGroupInfos[1].storyChoiceInfos[0].isBestObtainableFavorability
    assert progress(game)["current"]["hint"]==0


def test_inferred_choice_and_ending_bonuses_never_change_real_present_affinity(game):
    register(game);invoke(game,"Present",loveId=EV)
    assert user(game).loves[0].hiddenFavorability==167
    # Numeric compatibility weights remain available to the route interpreter,
    # but even extreme inferred bonuses cannot become actual account affinity.
    game.plan["events"][EV]["endings"][0]["favorability"]=(1<<63)-1
    result=finish_first(game,bad=True)
    assert result.storyEndName=="Bad test end" and result.unlockSave
    assert user(game).loves[0].hiddenFavorability==167 and not result.rewards
    finish_first(game)
    invoke(game,"Save",loveId=EV,slotNumber=1)
    invoke(game,"Reset",loveId=EV)
    invoke(game,"Load",loveId=EV,slotNumber=1)
    assert user(game).loves[0].hiddenFavorability==167
