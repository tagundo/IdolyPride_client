"""Credential-free Web requests and native-only official account integration."""
import json
import subprocess
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest

from test_ios_host import harness, start, command
from test_ios_unified_web import run_js as _run_js
from test_official_import import schema, Client, Timer, MASTER, snapshot, populate, ready


def run_js(body):
    try:
        _run_js(body)
    except subprocess.CalledProcessError as error:
        pytest.fail("Offline Node UI assertion failed:\n"+(error.stderr or "")[:4096],pytrace=False)


class OfficialFixture:
    def __init__(self):
        self.state = "idle"
        self.calls = []
        self.closed = False

    def status(self, *, public=True):
        value = {"schema":1,"state":self.state,"job_id":"a"*32 if self.state != "idle" else None,
            "progress":self.state,"error_code":None,"counts":{"cards":2,"items":3,"photos":4},
            "busy":False,"expires_in_seconds":120}
        if not public:
            value["preview"] = {"manager_name":"Explicit preview only","public_id":"public-account", "manager_level":9,
                "inventory":{"cards":2,"items":3,"photos":4}}
        return value

    def command(self, action, payload):
        # Record only non-sensitive command metadata, like the shipping service.
        self.calls.append((action,{k:v for k,v in payload.items() if k not in ("user_id","password")}))
        if action == "official_inspect":
            assert payload == {"user_id":"Transfer_A1","password":"Case Preserved_2","platform":"ios"}
            self.state = "verified"
        elif action == "official_fetch":
            assert payload == {"job_id":"a"*32}
            self.state = "ready"
        elif action == "official_cancel":
            self.state = "cancelled"
        elif action == "official_apply":
            self.state = "completed"
        return {"action":action,"job":self.status(public=False)}

    def close(self):
        self.closed = True


def test_host_official_preview_is_explicit_and_credentials_never_reach_status_or_events(harness):
    h=harness;start(h);service=OfficialFixture();h.subject._official_import=service
    checked=command(h,"official_inspect",user_id="Transfer_A1",password="Case Preserved_2",platform="ios")
    assert checked["ok"] and checked["result"]["job"]["state"] == "verified"
    assert checked["result"]["job"]["preview"]["manager_name"] == "Explicit preview only"
    generic=command(h,"status")["result"]
    assert generic["official_import_available"] is True
    assert "preview" not in generic["official_import"]
    exported=json.dumps([generic,h.bridge.events])
    for text in ("Transfer_A1","Case Preserved_2","Explicit preview only"):
        assert text not in exported
    assert command(h,"official_fetch",job_id="a"*32)["result"]["job"]["state"] == "ready"
    assert command(h,"official_cancel",job_id="a"*32)["result"]["job"]["state"] == "cancelled"
    h.subject.close();assert service.closed


@pytest.mark.parametrize("runtime_present",[True,False])
def test_official_apply_cannot_replace_prepared_normal_account_after_server_failure(harness,runtime_present):
    h=harness;start(h);service=OfficialFixture();h.subject._official_import=service
    h.subject._game_prepared=True;h.subject._prepared_account=("normal","source")
    h.runtimes[0].running=False
    if not runtime_present:h.subject._runtime=None
    result=command(h,"official_apply",job_id="a"*32,profile="source",replace=True,expected_revision="b"*64)
    assert result["ok"] is False and result["error"]["code"] == "account_restart_required"
    assert service.calls == []


def test_official_inactive_apply_is_normal_only_and_does_not_select_or_change_mode(harness):
    h=harness;start(h);service=OfficialFixture();h.subject._official_import=service
    original=h.subject._options()
    result=command(h,"official_apply",job_id="a"*32,profile="new-normal",replace=False,expected_revision=None)
    assert result["ok"] and result["result"]["job"]["state"] == "completed"
    assert service.calls == [("official_apply",{"job_id":"a"*32,"profile":"new-normal","replace":False,"expected_revision":None})]
    assert h.subject._options() == original
    assert h.runtimes[0].stops == 0
    assert not (h.data/"account-management/selection.json").exists()


def test_official_failure_never_uses_credential_shaped_exception_as_error_code(harness):
    h=harness;start(h)
    class Failed(OfficialFixture):
        def command(self,action,payload):
            error=RuntimeError("official_private_password");error.code="official_private_password";raise error
    h.subject._official_import=Failed()
    result=command(h,"official_status")
    assert result["ok"] is False and result["error"]["code"] == "operation_failed"
    assert "private_password" not in json.dumps([result,h.bridge.events])


def test_native_official_prompt_is_secure_cleared_and_cannot_receive_web_credentials():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/native/IdolySettings.m").read_text()
    block=source.split("- (void)presentOfficialPrompt:(NSDictionary *)request {",1)[1].split("- (void)dispatchRequest:",1)[0]
    assert "request.count != 2" in block
    assert "field.secureTextEntry = YES" in block and 'field.textContentType = @""' in block
    assert block.index("[strongSelf clearOfficialPrompt]") < block.index('[strongSelf sendRequest:@{')
    assert 'submit(@"ios")' in block and 'submit(@"android")' in block
    assert 'request[@"user_id"] || request[@"password"]' in source
    assert 'for (UITextField *field in _officialPrompt.textFields) field.text = nil' in source
    assert 'identifierMatch.length == userID.length' in block
    assert '[prompt dismissViewControllerAnimated:NO completion:nil]' in source


def test_web_official_bridge_refuses_credentials_paths_and_unbound_apply():
    run_js(r"""
const env=environment(),bridge=api.createBridge(env.scope,env.timers);
for(const [action,payload] of [
  ['official_inspect',{user_id:'private',password:'private',platform:'ios'}],
  ['official_inspect',{platform:'ios'}],['official_fetch',{job_id:'bad'}],
  ['official_apply',{job_id:'a'.repeat(32),profile:'target',replace:true,expected_revision:null}],
  ['official_apply',{job_id:'a'.repeat(32),profile:'target',replace:false,expected_revision:null,mode:'media'}],
  ['official_status',{path:'/private/account'}]
])await assert.rejects(bridge.request(action,payload));
assert.equal(env.posted.length,0);bridge.dispose();
""")


def test_web_official_steps_require_explicit_login_then_default_new_normal_apply():
    run_js(r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const base=status();base.official_import_available=true;
const job=(state,preview=true)=>({schema:1,state,job_id:'a'.repeat(32),busy:false,progress:state,
  counts:{cards:2,items:3,photos:4},error_code:null,expires_in_seconds:120,
  ...(preview?{preview:{manager_name:'Preview-only manager',public_id:'public-id',manager_level:9,inventory:{cards:2,items:3,photos:4}}}:{})});
const sync=async state=>{const r=env.posted.filter(x=>x.action==='status').at(-1);env.respond(r,{...base,official_import:job(state,false)});await flush();};
env.respond(env.posted[0],base);await flush();
assert.equal(env.elements.get('official-fetch').disabled,true);
env.elements.get('official-inspect').fire('click');await flush();
const inspect=env.posted.find(x=>x.action==='official_inspect');
assert.deepEqual(inspect,{id:inspect.id,action:'official_inspect'});
env.respond(inspect,{action:'official_inspect',job:job('verified')});await flush();await sync('verified');
assert.equal(env.elements.get('official-fetch').disabled,false);
assert.equal(env.posted.some(x=>x.action==='official_fetch'),false);
assert.ok(env.elements.get('official-preview').textContent.includes('Preview-only manager'));
assert.ok(!env.elements.get('diagnostics').textContent.includes('Preview-only manager'));
env.elements.get('official-fetch').fire('click');await flush();
const download=env.posted.find(x=>x.action==='official_fetch');
assert.deepEqual(download,{id:download.id,action:'official_fetch',job_id:'a'.repeat(32)});
env.respond(download,{action:'official_fetch',job:job('ready')});await flush();await sync('ready');
env.elements.get('official-profile').value='official-new';
assert.equal(env.elements.get('official-replace').checked,false);
env.elements.get('official-apply').fire('click');await flush();
const apply=env.posted.find(x=>x.action==='official_apply');
assert.deepEqual(apply,{id:apply.id,action:'official_apply',job_id:'a'.repeat(32),profile:'official-new',replace:false,expected_revision:null});
env.respond(apply,{action:'official_apply',job:job('completed')});await flush();
assert.equal(env.elements.get('official-apply').disabled,true);
assert.equal(env.posted.some(x=>['save_options','accounts_select'].includes(x.action)),false);
app.dispose();
""")


@pytest.mark.parametrize("language",["ko","ja","en"])
def test_official_interface_has_translations_without_credential_fields(language):
    run_js("const language="+json.dumps(language)+";\n"+r"""
for(const value of ['일본 공식 계정 가져오기','공식 인계 로그인·내려받기','받은 데이터를 일반 계정으로 저장','공식 계정 작업에 실패했습니다. 입력 정보와 연결 상태를 확인해 주세요.']) {
  assert.equal(typeof api.translateUI(value,language),'string');
  if(language!=='ko')assert.notEqual(api.translateUI(value,language),value);
}
const html=fs.readFileSync(WEB+'/index.html','utf8'),js=fs.readFileSync(WEB+'/app.js','utf8');
assert.ok(!html.includes('type="password"'));
// Session UI storage may keep only finite category/fold preferences. Account
// names, preview data and credentials must never enter that storage.
const layoutEnv=environment(),writes=[];
const categories=['console','server','users','content','graphics'];
const panelKeys=['diagnostics','options','accounts','official','events','graphics','playback','media','resources','mp4'];
layoutEnv.scope.localStorage={getItem:()=>null,setItem:(key,raw)=>{
  assert.equal(key,'idoly.settings.layout.v1');const value=JSON.parse(raw);
  assert.deepEqual(Object.keys(value).sort(),['category','panels','schema']);assert.equal(value.schema,1);
  assert.ok(categories.includes(value.category));assert.deepEqual(Object.keys(value.panels).sort(),panelKeys.slice().sort());
  assert.ok(Object.values(value.panels).every(item=>typeof item==='boolean'));
  assert.ok(!raw.includes('private-preview-canary')&&!raw.includes('private-slot-canary'));writes.push(raw);
}};
const layoutApp=api.createSettingsApp(layoutEnv.scope,layoutEnv.document,layoutEnv.timers),base=status();
base.official_import_available=true;base.official_import={schema:1,state:'ready',job_id:'a'.repeat(32),busy:false,progress:'ready',counts:{cards:1,items:1,photos:1},error_code:null,expires_in_seconds:120,
 preview:{manager_name:'private-preview-canary',public_id:'private-id',manager_level:1,inventory:{cards:1,items:1,photos:1}}};
layoutEnv.respond(layoutEnv.posted[0],base);await flush();layoutEnv.elements.get('official-profile').value='private-slot-canary';
layoutEnv.elements.get('category-users').fire('click');layoutEnv.elements.get('panel-official').open=true;layoutEnv.elements.get('panel-official').fire('toggle');
assert.ok(writes.length>=3);assert.ok(layoutEnv.elements.get('official-preview').textContent.includes('private-preview-canary'));layoutApp.dispose();
const panel=html.split('aria-labelledby="official-heading"')[1].split('</section>')[0];
assert.deepEqual([...panel.matchAll(/<input\b[^>]*id="([^"]+)"/g)].map(row=>row[1]),['official-profile','official-replace']);
const env=environment(),bridge=api.createBridge(env.scope,env.timers);
await assert.rejects(bridge.request('official_inspect',{user_id:'never-send',password:'never-send',platform:'ios'}));
const request=bridge.request('official_inspect');assert.deepEqual(env.posted,[{id:1,action:'official_inspect'}]);
env.respond(env.posted[0],{action:'official_inspect',cancelled:true});await request;bridge.dispose();
""")


def test_game_start_refuses_busy_official_worker_before_any_game_preparation(harness):
    h=harness;start(h)
    class Busy(OfficialFixture):
        def status(self, *, public=True):
            value=super().status(public=public);value["busy"]=True;return value
    h.subject._official_import=Busy()
    with pytest.raises(RuntimeError,match="official account operation"):
        h.subject.prepare_game_start()
    assert h.subject._game_prepared is False


def test_official_fixed_error_remains_translatable_and_does_not_retry_login():
    run_js(r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const base=status();base.official_import_available=true;
env.respond(env.posted[0],base);await flush();
env.elements.get('official-inspect').fire('click');await flush();
const request=env.posted.find(x=>x.action==='official_inspect');
env.scope.idolyServerReply(request.id,{id:request.id,ok:false,error:{code:'transfer_rejected',message:'DO-NOT-DISPLAY'}});await flush();
assert.ok(!env.elements.get('official-feedback').textContent.includes('DO-NOT-DISPLAY'));
assert.equal(env.elements.get('official-feedback').textContent,'공식 서버에서 인계 정보를 확인하지 못했습니다. 입력 정보를 다시 확인해 주세요.');
env.elements.get('interface_language').value='en';env.elements.get('interface_language').fire('change');await flush();
assert.equal(env.elements.get('official-feedback').textContent,'The official server could not verify the transfer details. Check the entered details.');
assert.equal(env.posted.filter(x=>x.action==='official_inspect').length,1);
assert.equal(env.posted.filter(x=>x.action==='official_fetch').length,0);
app.dispose();
""")


def test_host_reprojects_even_unexpected_service_fields_before_web_or_diagnostics(harness):
    h=harness;start(h)
    class Unexpected(OfficialFixture):
        def status(self, *, public=True):
            value=super().status(public=public)
            value.update(user_id="DO-NOT-EXPORT",password="DO-NOT-EXPORT",token="DO-NOT-EXPORT")
            value["preview"]={"manager_name":"Allowed preview","user_id":"DO-NOT-EXPORT","password":"DO-NOT-EXPORT",
                "inventory":{"cards":2,"items":True,"photos":2**63}}
            return value
    h.subject._official_import=Unexpected()
    public=command(h,"status")["result"]["official_import"]
    explicit=command(h,"official_status")["result"]["job"]
    assert "preview" not in public
    assert explicit["preview"] == {"manager_name":"Allowed preview","inventory":{"cards":2}}
    assert "DO-NOT-EXPORT" not in json.dumps([public,explicit,h.bridge.events])


def test_host_keeps_atomic_apply_busy_progress_without_inventing_a_new_state(harness):
    h=harness;start(h)
    class Applying(OfficialFixture):
        def status(self, *, public=True):
            value=super().status(public=public);value.update(state="ready",busy=True,progress="applying");return value
    h.subject._official_import=Applying()
    observed=command(h,"status")["result"]["official_import"]
    assert observed["state"] == "ready" and observed["progress"] == "applying" and observed["busy"] is True


@pytest.fixture
def local_official_host(harness,schema):
    """Real official staging and SQLite apply with an offline protocol client."""
    from idoly_local.account_manager import AccountManager
    from idoly_local.official_import import OfficialImportManager, ERROR_CODES
    h=harness;assert start(h)["running"]
    (h.data/"original-master").mkdir();(h.data/"master-json").mkdir()
    (h.data/"original-master/master-tag.json").write_text(json.dumps({"version":MASTER}))
    (h.data/"master-json/!version.txt").write_text(MASTER)
    for table,identity in (("Card","card-a"),("Item","item-a")):
        (h.data/("master-json/"+table+".json")).write_text(json.dumps([{"id":identity}]))
    accounts=AccountManager(h.data,schema=schema)
    env=SimpleNamespace(root=h.data,schema=schema,accounts=accounts,clock=[1800000000.0],calls=[],clients=[],
        raw=snapshot(schema),remote_version=MASTER,inspect_gate=None,fetch_gate=None,
        inspect_error=None,fetch_error=None,credentials_ok=False,inspect_started=threading.Event(),fetch_started=threading.Event())
    def factory(protocol, *, platform):
        assert protocol is schema
        client=Client(env,platform);env.clients.append(client);return client
    env.manager=OfficialImportManager(h.data,accounts=accounts,client_factory=factory,
        now=lambda:env.clock[0],timer_factory=Timer)
    h.subject._official_import=env.manager;h.subject._official_errors=frozenset(ERROR_CODES)
    yield h,env
    env.manager.close()
    if env.manager._thread is not None:env.manager._thread.join(timeout=3)


@pytest.mark.parametrize("restart_failure",["exception","not_running"])
@pytest.mark.parametrize("status_refresh_failure",[False,True])
def test_real_official_commit_survives_restart_failure_and_preserves_canonical_revision(local_official_host,monkeypatch,restart_failure,status_refresh_failure):
    h,env=local_official_host;state=populate(env,"active");before=state.account_snapshot("active")
    job=ready(env);runtime=h.runtimes[0];original_status=runtime.status
    monkeypatch.setattr(runtime,"status",lambda:{**original_status(),"profile":"active","media_mode":False})
    attempts=[]
    def fail_restart(*args,**kwargs):
        attempts.append(True)
        # The fault is strictly after the real SQLite replacement committed.
        assert state.snapshot("active")[0] == env.raw
        assert env.manager.status()["state"] == "completed"
        if restart_failure == "exception":raise OSError("DO-NOT-EXPORT-restart-detail")
        return {"state":"failed","running":False}
    monkeypatch.setattr(h.subject,"start",fail_restart)
    if status_refresh_failure:
        actual_status=env.accounts.status
        def fault_after_commit(*args,**kwargs):
            if state.snapshot("active")[0] == env.raw:raise OSError("DO-NOT-EXPORT-status-detail")
            return actual_status(*args,**kwargs)
        monkeypatch.setattr(env.accounts,"status",fault_after_commit)
    result=command(h,"official_apply",job_id=job,profile="active",replace=True,expected_revision=before[1])
    assert result["ok"] is True
    saved=result["result"];actual=state.account_snapshot("active")
    assert saved["job"]["state"] == "completed" and saved["job"]["busy"] is False
    assert saved["account"]["mode"] == "normal" and saved["account"]["profile"] == "active"
    assert actual[1] == saved["account"]["revision"] and actual != before and state.snapshot("active")[0] == env.raw
    assert "official_server_restart_required" in saved["warning_codes"]
    assert attempts == [True] and runtime.stops == 1
    if status_refresh_failure:
        assert saved["status_refresh_required"] is True
        assert "account_status_refresh_required" in saved["warning_codes"]
    observed=command(h,"status")["result"]
    assert observed["state"] == "failed" and observed["running"] is False
    assert observed["last_error"]["code"] == "official_server_restart_required"
    again=command(h,"official_apply",job_id=job,profile="active",replace=True,expected_revision=before[1])
    assert again["ok"] is False and again["error"]["code"] == "official_invalid_state"
    assert env.manager.status()["state"] == "completed" and attempts == [True]
    assert env.calls == ["inspect","fetch"]
    assert "DO-NOT-EXPORT" not in json.dumps([result,observed,again,h.bridge.events])


def test_real_precommit_cas_error_survives_best_effort_restart_failure(local_official_host,monkeypatch):
    h,env=local_official_host;state=populate(env,"active");before=state.account_snapshot("active");job=ready(env)
    runtime=h.runtimes[0];actual_status=runtime.status
    monkeypatch.setattr(runtime,"status",lambda:{**actual_status(),"profile":"active","media_mode":False})
    attempts=[]
    def fail_restart(*args,**kwargs):attempts.append(True);raise OSError("DO-NOT-EXPORT-restart")
    monkeypatch.setattr(h.subject,"start",fail_restart)
    failed=command(h,"official_apply",job_id=job,profile="active",replace=True,expected_revision="0"*64)
    assert failed["ok"] is False and failed["error"]["code"] == "account_revision_conflict"
    assert state.account_snapshot("active") == before and env.manager.status()["state"] == "ready"
    assert attempts == [True] and env.calls == ["inspect","fetch"]
    assert "DO-NOT-EXPORT" not in json.dumps([failed,h.bridge.events])


def test_completed_service_warning_projection_keeps_only_finite_codes_and_strict_refresh_bool(harness):
    h=harness;start(h)
    class Warned(OfficialFixture):
        def command(self,action,payload):
            result=super().command(action,payload)
            result.update(warning_codes=["account_temporary_cleanup_pending","account_temporary_cleanup_pending","account_status_refresh_required","DO-NOT-EXPORT",True],status_refresh_required=1)
            return result
    h.subject._official_import=Warned()
    result=command(h,"official_apply",job_id="a"*32,profile="new",replace=False,expected_revision=None)["result"]
    assert result["job"]["state"] == "completed"
    assert result["warning_codes"] == ["account_temporary_cleanup_pending","account_status_refresh_required"]
    assert "status_refresh_required" not in result and "DO-NOT-EXPORT" not in json.dumps(result)


@pytest.mark.parametrize("language",["ko","en","ja"])
def test_completed_warning_ui_preserves_success_and_never_retries_apply(language):
    run_js("const language="+json.dumps(language)+";\n"+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const job=state=>({schema:1,state,job_id:'a'.repeat(32),busy:false,progress:state,counts:{cards:1,items:1,photos:1},expires_in_seconds:120,error_code:null});
const base=status();base.official_import_available=true;base.options.interface_language=language;base.official_import=job('ready');
env.respond(env.posted[0],base);await flush();
const read=env.posted.find(x=>x.action==='official_status');assert.ok(read);
env.respond(read,{action:'official_status',job:job('ready')});await flush();
env.elements.get('official-profile').value='saved-target';env.elements.get('official-apply').fire('click');await flush();
const apply=env.posted.find(x=>x.action==='official_apply');assert.ok(apply);
env.respond(apply,{action:'official_apply',job:job('completed'),account:{mode:'normal',profile:'saved-target',revision:'b'.repeat(64)},
  warning_codes:['account_temporary_cleanup_pending','account_status_refresh_required','official_server_restart_required','DO-NOT-DISPLAY'],status_refresh_required:true});await flush();
const refresh=env.posted.filter(x=>x.action==='status').at(-1);
env.respond(refresh,{...base,state:'failed',running:false,official_import:job('completed'),last_error:{code:'official_server_restart_required',message:'계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요.'}});await flush();
assert.equal(env.elements.get('official-state').textContent,api.translateUI('일반 계정 저장 완료',language));
for(const notice of ['계정 저장은 완료됐습니다. 임시 파일 정리가 남아 있습니다.','계정 저장은 완료됐습니다. 위 ‘계정 목록 불러오기’로 목록을 새로 확인해 주세요.','계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요.'])
  assert.ok(env.elements.get('official-feedback').textContent.includes(api.translateUI(notice,language)));
assert.ok(!env.elements.get('official-feedback').textContent.includes('DO-NOT-DISPLAY'));
assert.equal(env.elements.get('official-apply').disabled,true);
assert.equal(env.posted.filter(x=>x.action==='official_apply').length,1);
assert.equal(env.posted.some(x=>['official_inspect','official_fetch'].includes(x.action)),false);
app.dispose();
""")


def test_native_restart_notice_requires_exact_completed_official_warning_without_changing_gate():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/native/IdolySettings.m").read_text()
    block=source.split("- (void)sendReply:(NSNumber *)identifier json:(NSString *)json {",1)[1].split("- (void)localFailure:",1)[0]
    assert '[value[@"ok"] isEqual:@YES]' in block
    assert '[officialResult[@"action"] isEqual:@"official_apply"]' in block
    assert '[officialJob[@"state"] isEqual:@"completed"]' in block
    assert '[warnings containsObject:@"official_server_restart_required"]' in block
    assert 'IDNativeSetServerState(NO, NO, @"계정 저장 완료 · 서버 재시작 필요")' in block
    assert block.index("IDNativeSetServerState") < block.index("if (!_web) return")
    assert 'gate.phase' not in block
    assert '@"アカウント保存完了 · サーバーの再起動が必要"' in source
    assert '@"Account Saved · Restart Server"' in source
