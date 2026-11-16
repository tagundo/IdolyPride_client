"""Account UI commands and portable account bytes through the actual iOS host."""
import hashlib
import json
from pathlib import Path

import pytest

from idoly_local import account_manager
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema
from test_ios_host import harness, start, command
from test_ios_unified_web import run_js


def seeded_account(h):
    descriptor = h.data/"protocol/idolypride-6.1.1.pb"
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    synthetic_schema(descriptor)
    from google.protobuf import descriptor_pb2, message_factory
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(descriptor.read_bytes())
    file = descriptors.file[0]
    reward = file.message_type.add(name="BackupLessonResponse")
    reward.field.add(name="progress",number=1,label=1,type=11,type_name=".api.LessonProgress")
    file.service.add(name="Activity").method.add(name="ReceiveLessonReward",input_type=".api.Empty",output_type=".api.BackupLessonResponse")
    file.service.add(name="Quest").method.add(name="StartMainLive",input_type=".api.Empty",output_type=".api.ActionResponse")
    descriptor.write_bytes(descriptors.SerializeToString())
    schema = Schema.from_descriptor_set(descriptor)
    state = State(h.data/"state.db")
    identity = state.ensure_profile("source")
    user = schema.response_type("/api.User/Get")()
    user.user.name = "Portable manager"
    user.user.managerLevel = 19
    user.userPublic.serverUserId = identity["server_id"]
    user.userPublic.publicUserId = identity["public_id"]
    user.cards.add(cardId="retained-card",totalExp=9876)
    payload = user.SerializeToString()+b"\x80\x4b\x7b"
    state.save_snapshot("source",payload,schema.fingerprint,starter_version=4)
    unknown = b"\x80\x4b\x7b"
    settings_descriptor = schema.request_type("/api.Home/Login").DESCRIPTOR.fields_by_name["settingInfo"].message_type
    settings = message_factory.GetMessageClass(settings_descriptor)(soundBgm=33,frameRate=60)
    lesson_descriptor = schema.response_type("/api.Activity/ReceiveLessonReward").DESCRIPTOR.fields_by_name["progress"].message_type
    lesson = message_factory.GetMessageClass(lesson_descriptor)(currentAreaId="main-area-001",lastReceiveTime=1700000000000)
    preference = schema.response_type("/api.Home/SetReview")()
    preference.commonResponse.updatedData.user.name = "Portable manager"
    live = schema.response_type("/api.Quest/StartMainLive")()
    live.commonResponse.updatedData.user.name = "Portable manager"
    love={"schema":1,"love_id":"love-23-0514","player_name":"HostQA","registered_ms":1,"exp":0,
        "lesson_anchor_ms":1,"last_play_ms":1,"path":["love-event-story-love-23-0514-001"],"choices":{},
        "past_choices":{},"current":None,"saves":[],"promotion_day":"2026-11-16","promotion_used":0}
    love_raw=(json.dumps(love,sort_keys=True,indent=2)+"\n").encode()
    from idoly_local.love import validate_progress
    validate_progress(love_raw,love["love_id"])
    with state.connect() as db:
        db.execute("INSERT INTO profile_love_progress VALUES (?,?,?,?,?)",("source",love["love_id"],love_raw,schema.fingerprint,"c"*64))
        db.execute("INSERT INTO profile_settings VALUES (?,?,?)",("source",settings.SerializeToString()+unknown,schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES (?,?,?)",("source",lesson.SerializeToString()+unknown,schema.fingerprint))
        db.execute("INSERT INTO preference_receipts VALUES (?,?,?,?,?,?)",("source","/api.Home/SetReview","7","a"*64,schema.fingerprint,preference.SerializeToString()+unknown))
        db.execute("INSERT INTO main_live_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("source","9","b"*64,"/api.Quest/StartMainLive",schema.fingerprint,"master","live-v5","123",1700000000000,live.SerializeToString()+unknown))
    return state,schema,payload


def revision(h, profile):
    response = command(h,"accounts_status")
    assert response["ok"],response
    return next(row["revision"] for row in response["result"]["status"]["accounts"] if row["profile"] == profile)


def test_account_archive_roundtrip_uses_real_state_and_preserves_every_non_session_table(harness):
    h=harness;start(h)
    state,schema,payload=seeded_account(h)
    token,_=state.login("source")
    source,original_revision=state.account_snapshot("source")
    exported=command(h,"accounts_export",mode="normal",profile="source",expected_revision=original_revision)
    assert exported["ok"],exported
    result=exported["result"]
    archive=Path(result["output_path"])
    assert archive.parent == h.data/"tmp/exports" and archive.is_file()
    assert archive.name.startswith("IdolyPride-Account-")
    assert archive.stat().st_size == result["bytes"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["sha256"]
    assert not (h.data/"account-management/exports"/archive.name).exists()
    copied=h.data/"imports/native-approved.zip"
    copied.write_bytes(archive.read_bytes())
    preview=command(h,"accounts_preview",path=str(copied))
    assert preview["ok"],preview
    assert not copied.exists()
    assert len(preview["result"]["token"]) == 32
    assert state.authenticated(token,"source")
    imported=command(h,"accounts_import",token=preview["result"]["token"],mode="normal",profile="imported",
        replace=False,expected_revision=None)
    assert imported["ok"],imported
    assert State(h.data/"state.db").snapshot("imported") == (payload,schema.fingerprint)
    restored,_=state.account_snapshot("imported")
    for table, rows in source["tables"].items():
        assert [{key:value for key,value in row.items() if key not in ("name","profile")} for row in rows] == [
            {key:value for key,value in row.items() if key not in ("name","profile")} for row in restored["tables"][table]]
    assert state.authenticated(token,"source")
    assert source["tables"]["profile_settings"] and source["tables"]["profile_lesson_progress"]
    assert source["tables"]["preference_receipts"] and source["tables"]["main_live_attempts"]
    assert source["schema"] == restored["schema"] == 2
    assert set(source["tables"]) == set(restored["tables"]) == {"profiles","snapshots","profile_settings","starter_profiles",
        "profile_lesson_progress","preference_receipts","main_live_attempts","profile_love_progress"}
    original_love=source["tables"]["profile_love_progress"][0]
    imported_love=restored["tables"]["profile_love_progress"][0]
    assert original_love["response"] == imported_love["response"]
    assert original_love["response"].endswith(b"\n") and b'  "player_name": "HostQA"' in original_love["response"]
    assert original_love["ruleset_sha256"] == imported_love["ruleset_sha256"] == "c"*64
    cached=h.subject.status()
    assert cached["account_management_available"] is True
    assert any(row["profile"]=="imported" for row in cached["accounts"]["accounts"])


@pytest.mark.parametrize("case",["outside","symlink","hardlink"])
def test_native_account_preview_requires_the_approved_regular_import_directory(case,harness,tmp_path):
    h=harness;start(h)
    state,schema,payload=seeded_account(h)
    archive=command(h,"accounts_export",mode="normal",profile="source",expected_revision=revision(h,"source"))["result"]
    approved=h.data/"imports/copied.zip"
    approved.write_bytes(Path(archive["output_path"]).read_bytes())
    outside=tmp_path/"outside.zip";outside.write_bytes(approved.read_bytes())
    if case=="outside":target=outside
    elif case=="symlink":
        approved.unlink();approved.symlink_to(outside);target=approved
    else:
        approved.unlink();approved.hardlink_to(outside);target=approved
    before=state.account_snapshot("source")
    rejected=command(h,"accounts_preview",path=str(target))
    assert rejected["ok"] is False
    assert state.account_snapshot("source")==before


def test_active_account_restore_is_rejected_after_game_preparation_without_stopping_server(harness,monkeypatch):
    h=harness;start(h)
    runtime=h.runtimes[0]
    prior=runtime.status
    monkeypatch.setattr(runtime,"status",lambda:{**prior(),"profile":"source","media_mode":False})
    h.subject._game_prepared=True
    seen=[]
    monkeypatch.setattr(account_manager,"account_command",lambda *args:seen.append(args))
    result=command(h,"accounts_import",token="c"*32,mode="normal",profile="source",replace=True,expected_revision="d"*64)
    assert not result["ok"] and result["error"]["code"]=="account_restart_required"
    assert runtime.stops==0 and seen==[]
    assert h.subject.status()["running"] is True


def test_restore_point_identifier_is_separate_from_native_request_id(harness,monkeypatch):
    h=harness;start(h)
    seen=[]
    status={"schema":1,"accounts":[],"restore_points":[],"selected":{"normal":"sandbox","media":"sandbox"},"selection_revision":"a"*64}
    def core(root,action,payload):
        seen.append((root,action,payload))
        return {"schema":1,"ok":True,"action":action,"status":status}
    monkeypatch.setattr(account_manager,"account_command",core)
    reply=command(h,"accounts_restore",restore_id="b"*32,mode="normal",profile="other",expected_revision="c"*64)
    assert reply["ok"] and reply["id"]==7
    assert seen[0][2]=={"id":"b"*32,"mode":"normal","profile":"other","expected_revision":"c"*64}


def test_account_web_bridge_never_accepts_paths_or_unbound_overwrite_commands():
    run_js(r"""
const env=environment();const bridge=api.createBridge(env.scope,env.timers);
for(const [action,payload] of [
 ['accounts_preview',{path:'/private/provider/account.zip'}],
 ['accounts_export',{mode:'normal',profile:'source',expected_revision:'a'.repeat(64),output_path:'/tmp/x'}],
 ['accounts_import',{token:'b'.repeat(32),mode:'normal',profile:'source',replace:true,expected_revision:null}],
 ['accounts_restore',{id:'b'.repeat(32),mode:'normal',profile:'source',expected_revision:'a'.repeat(64)}],
 ['accounts_create',{mode:'normal',profile:'../other',manager_name:'Manager'}],
 ['accounts_select',{mode:'normal',profile:'source',expected_revision:'a'.repeat(64),selection_revision:'old'}]
]) await assert.rejects(bridge.request(action,payload),/허용되지/);
assert.equal(env.posted.length,0);
bridge.dispose();
""")


def test_account_import_preview_and_new_target_are_explicit_and_keep_resource_controls_separate():
    run_js(r"""
const env=environment();const app=api.createSettingsApp(env.scope,env.document,env.timers);
const initial=status();initial.account_management_available=true;initial.runtime.profile='source';initial.runtime.media_mode=false;
env.respond(env.posted[0],initial);await flush();
const listing=env.posted.find(x=>x.action==='accounts_status');assert.ok(listing);
const accounts={schema:1,accounts:[{mode:'normal',profile:'source',revision:'a'.repeat(64),has_snapshot:true,counts:{snapshots:1}}],
 selected:{normal:'source',media:'sandbox'},selection_revision:'b'.repeat(64),restore_points:[],offset:0,restore_offset:0,next_offset:null,next_restore_offset:null};
env.respond(listing,{status:accounts});await flush();
assert.ok(env.elements.get('accounts-summary').textContent.includes('source'));
env.elements.get('accounts-preview').fire('click');await flush();
const preview=env.posted.find(x=>x.action==='accounts_preview');
assert.deepEqual(preview,{id:preview.id,action:'accounts_preview'});
const oldResourceText=env.elements.get('resource-summary').textContent;
env.scope.idolyServerEvent({event:'account_import_progress',request_id:preview.id,stage:'copying',copied_bytes:50,total_bytes:100});
assert.equal(env.elements.get('accounts-progress').value,50);
assert.equal(env.elements.get('resource-summary').textContent,oldResourceText);
env.respond(preview,{status:accounts,token:'c'.repeat(32),archive:{mode:'normal',profile:'source',bytes:100,counts:{snapshots:1}}});await flush();
assert.equal(env.elements.get('accounts-import').disabled,false);
assert.equal(env.elements.get('accounts-new-profile').value,'source-import');
env.elements.get('accounts-import').fire('click');await flush();
const apply=env.posted.find(x=>x.action==='accounts_import');
assert.deepEqual(apply,{id:apply.id,action:'accounts_import',token:'c'.repeat(32),mode:'normal',profile:'source-import',replace:false,expected_revision:null});
env.respond(apply,{status:accounts});await flush();
assert.equal(env.elements.get('accounts-import').disabled,true);
app.dispose();
""")


@pytest.mark.parametrize("language,label",[("en","User management"),("ja","ユーザー管理")])
def test_new_account_controls_and_failure_text_have_interface_translations(language,label):
    run_js("const LANGUAGE="+json.dumps(language)+";const LABEL="+json.dumps(label)+";\n"+r"""
assert.equal(api.translateUI('유저 관리',LANGUAGE),LABEL);
assert.notEqual(api.translateUI('계정 ZIP 선택·검사',LANGUAGE),'계정 ZIP 선택·검사');
assert.notEqual(api.translateUI('계정 작업을 마치지 못했습니다. 목록을 새로 불러와 확인해 주세요.',LANGUAGE),'계정 작업을 마치지 못했습니다. 목록을 새로 불러와 확인해 주세요.');
""")


def test_native_account_picker_has_separate_progress_name_and_bounded_copy():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/native/IdolySettings.m").read_text()
    assert '@"accounts_preview"' in source and '@"accounts_export"' in source
    assert '@"account_import_progress"' in source and '@"resource_import_progress"' in source
    assert "128ULL * 1024ULL * 1024ULL" in source
    assert "(uint64_t)size > byteLimit - copied" in source
    assert '[result removeObjectForKey:@"path"]' in source and '[result removeObjectForKey:@"output_path"]' in source
    assert 'initWithDocumentTypes:@[@"public.zip-archive"] inMode:UIDocumentPickerModeImport' in source
    assert 'request[@"path"] || request[@"output_path"]' in source


@pytest.mark.parametrize("runtime_present",[True,False])
def test_prepared_account_identity_remains_protected_after_listener_failure(runtime_present,harness,monkeypatch):
    h=harness;start(h)
    h.subject._game_prepared=True
    h.subject._prepared_account=("normal","source")
    h.runtimes[0].running=False
    if not runtime_present:
        h.subject._runtime=None
    seen=[]
    monkeypatch.setattr(account_manager,"account_command",lambda *args:seen.append(args))
    result=command(h,"accounts_import",token="c"*32,mode="normal",profile="source",replace=True,expected_revision="d"*64)
    assert not result["ok"] and result["error"]["code"]=="account_restart_required"
    assert seen==[]


def test_export_reservation_is_before_status_cleanup_and_retained_until_picker_completion():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/native/IdolySettings.m").read_text()
    block=source.split("- (void)dispatchRequest:(NSDictionary *)request {",1)[1].split("- (void)sendRequest:",1)[0]
    assert block.index('_pendingExportRequestID = request[@"id"]') < block.index('IdolyEmbeddedServerCommand(statusRequest')
    assert "if (_pendingExportRequestID || _pendingImport || _officialPrompt)" in block
    assert "pendingExportJobID" in source and "releaseExportRequest" in source
    assert 'if (_pendingImport || _pendingExportRequestID || _officialPrompt)' in source
    assert 'if (_preparedExportPath) [self exportPath:_preparedExportPath]' in source



def test_failed_payload_installation_exposes_persisted_history_before_runtime_creation(harness,monkeypatch):
    h=harness
    def fail(*args):
        raise PermissionError("provider-path-must-not-be-exported")
    h.subject._installer=fail
    result=start(h)
    assert result["state"]=="failed" and h.runtimes==[]
    assert result["runtime"]["durable_history"]["last_failure"]["kind"]=="startup_failure"
    assert result["runtime"]["startup_checks"]["scope"]=="current_run"
    from idoly_local.ios_host import _Host
    fresh=_Host(bridge=h.bridge)
    fresh._paths=(h.bundle,h.data,h.resources)
    prior=fresh.status()
    assert prior["runtime"]["startup_checks"]["scope"]=="previous_run"
    assert prior["runtime"]["durable_history"]["last_failure"]["kind"]=="startup_failure"
    assert "provider-path-must-not-be-exported" not in json.dumps(result)

def test_account_page_and_last_failure_survive_status_budget_with_native_headroom(harness,monkeypatch):
    h=harness;start(h)
    base=h.runtimes[0].status()
    accounts={"schema":1,"selected":{"normal":"slot-0","media":"sandbox"},"selection_revision":"a"*64,
        "restore_points":[],"accounts":[]}
    for number in range(24):
        accounts["accounts"].append({"mode":"normal","profile":"slot-"+str(number),"revision":"b"*64,
            "server_id":"s"*256,"public_id":"p"*256,"has_snapshot":True,"manager_name":"매"*40,
            "inventory":{"cards":100,"items":30,"photos":9},
            "counts":{"profiles":1,"snapshots":1,"profile_settings":1,"starter_profiles":1,
                "profile_lesson_progress":1,"preference_receipts":100,"main_live_attempts":10,"profile_love_progress":6}})
    h.subject._account_status=accounts
    last={"sequence":100,"timestamp":"2026-11-16T00:00:00.000Z","run_id":"c"*32,
        "kind":"http_failure","code":"http_request_failed","http_status":404}
    base["durable_history"]={"schema":1,"available":True,"load_state":"loaded","persistence":"stored",
        "last_write_error":None,"current_run":"c"*32,"retained_records":128,"total_records":400,
        "last_failure":last,"records":[{**last,"sequence":index,"path":"/api."+("A"*1700)+"/Get"} for index in range(20)]}
    base["startup_checks"]={"schema":1,"scope":"current_run","state":"blocked","gameplay_verified":False,
        "checks":[{"id":"http","state":"blocked","code":"address_in_use"}]}
    base["huge_probe"]="x"*100000
    monkeypatch.setattr(h.runtimes[0],"status",lambda:base)
    encoded=h.subject.command('{"id":7,"action":"status"}')
    response=json.loads(encoded)
    assert response["ok"] and len(encoded.encode("utf-8")) <= 65536-8192+128
    observed=response["result"]
    assert len(observed["accounts"]["accounts"])==24
    assert observed["runtime"]["startup_checks"]["checks"][0]["code"]=="address_in_use"
    history=observed["runtime"]["durable_history"]
    assert history["last_failure"]==last
    assert history["records_truncated"] is True and len(history["records"]) <= 3
    assert history["retained_records"]==128 and history["total_records"]==400


@pytest.mark.parametrize("language,description",[("en","Close another server using the same port."),("ja","同じポートを使う別のサーバーを終了してください。")])
def test_readiness_cards_show_localized_action_and_keep_fixed_codes_in_diagnostic_copy(language,description):
    run_js("const LANGUAGE="+json.dumps(language)+";const DESCRIPTION="+json.dumps(description)+";\n"+r"""
const env=environment();const app=api.createSettingsApp(env.scope,env.document,env.timers);
const value=status();value.options.interface_language=LANGUAGE;
value.runtime.startup_checks={scope:'current_run',checks:[{id:'http',state:'blocked',code:'address_in_use'}]};
value.runtime.durable_history={available:true,last_failure:{kind:'startup_failure',code:'internal_error',timestamp:'2026-11-16T00:00:00Z'}};
env.respond(env.posted[0],value);await flush();
assert.ok(env.elements.get('startup-checks').textContent.includes(DESCRIPTION));
assert.ok(!env.elements.get('startup-checks').textContent.includes('address_in_use'));
assert.ok(!env.elements.get('history-summary').textContent.includes('internal_error'));
assert.ok(env.elements.get('diagnostics').textContent.includes('address_in_use'));
app.dispose();
""")

def test_new_manager_name_preserves_accepted_text_and_uses_game_utf16_limit():
    run_js(r"""
const env=environment();const bridge=api.createBridge(env.scope,env.timers);
const accepted=bridge.request('accounts_create',{mode:'normal',profile:'local-slot',manager_name:' A '});
assert.equal(env.posted[0].manager_name,' A ');
env.respond(env.posted[0],{ok:true});await accepted;
await assert.rejects(bridge.request('accounts_create',{mode:'normal',profile:'local-slot',manager_name:'😀'.repeat(6)}),/허용되지/);
await assert.rejects(bridge.request('accounts_create',{mode:'normal',profile:'local-slot',manager_name:'A\nB'}),/허용되지/);
bridge.dispose();
""")
