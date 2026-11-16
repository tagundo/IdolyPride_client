"""Credential-free Web requests and native-only official account integration."""
import json
from pathlib import Path

import pytest

from test_ios_host import harness, start, command
from test_ios_unified_web import run_js


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
assert.ok(!html.includes('type="password"'));assert.ok(!js.includes('localStorage'));
assert.ok(!js.includes('user_id'));assert.ok(!js.includes('password'));
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
