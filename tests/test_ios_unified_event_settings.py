"""Offline iOS bridge/UI contracts; no real game or official authentication."""
import copy
import json
import subprocess

import pytest

from idoly_local import event_settings
from test_ios_host import harness, start, command
from test_ios_unified_web import run_js as _run_js

CATALOG={"schema":1,"available":True,"events":[{"id":"love-a","title":"Event A","supported":True},
    {"id":"love-b","title":"Event B","supported":True},{"id":"love-unsupported","title":"Unsupported","supported":False}],"ruleset_sha256":"a"*64}

def run_js(body):
    try:_run_js(body)
    except subprocess.CalledProcessError as error:
        pytest.fail("Offline event UI assertion failed:\n"+(error.stderr or "")[:4096],pytrace=False)


def test_host_event_save_uses_common_cas_and_keeps_running_account_untouched(harness,monkeypatch):
    h=harness
    monkeypatch.setattr(event_settings,"_catalog",lambda root,override=None:copy.deepcopy(CATALOG))
    start(h)
    runtime=h.runtimes[0];original=runtime.status
    active=copy.deepcopy(event_settings.DEFAULTS)
    monkeypatch.setattr(runtime,"status",lambda:{**original(),"event_settings":event_settings.event_settings_status(h.data,effective=active)})
    observed=command(h,"events_status")
    assert observed["ok"] and observed["result"]["catalog"]==CATALOG
    settings={"schema":1,"revision":0,"love_events":[{"event_id":"love-a","start_time_ms":1000,"end_time_ms":2000}]}
    result=command(h,"events_save",settings=settings,expected_revision=0)
    assert result["ok"] and result["result"]["restart_required"] is True
    saved=result["result"]["runtime"]["event_settings"]
    assert saved["saved"]["love_events"]==settings["love_events"] and saved["effective"]==active
    assert runtime.stops==0 and len(h.calls)==1 and runtime.running
    before=(h.data/event_settings.FILENAME).read_bytes()
    stale=command(h,"events_save",settings=settings,expected_revision=0)
    assert stale["ok"] is False and stale["error"]["code"]=="event_settings_revision_conflict"
    assert (h.data/event_settings.FILENAME).read_bytes()==before
    unsupported={**saved["saved"],"love_events":[{"event_id":"love-unsupported","start_time_ms":1000,"end_time_ms":2000}]}
    bad=command(h,"events_save",settings=unsupported,expected_revision=unsupported["revision"])
    assert bad["ok"] is False and bad["error"]["code"]=="event_settings_unsupported"
    assert (h.data/event_settings.FILENAME).read_bytes()==before
    assert command(h,"events_save",settings=saved["saved"],expected_revision=saved["saved"]["revision"],reset=True)["ok"] is False
    assert (h.data/event_settings.FILENAME).read_bytes()==before


EVENT_JS=r"""
function eventStatus(saved={schema:1,revision:0,love_events:[]}) {
 const base=status();base.runtime.event_settings={schema:1,saved:structuredClone(saved),effective:{schema:1,revision:0,love_events:[]},restart_required:saved.love_events.length>0,invalid_settings_file:false,
  catalog:{schema:1,available:true,events:[{id:'love-a',title:'Event A',supported:true},{id:'love-b',title:'Event B',supported:true},{id:'love-unsupported',title:'Unsupported',supported:false}]}};return base;
}
function eventSaved(request) {const value=eventStatus({...request.settings,revision:request.expected_revision+1});value.restart_required=true;return value;}
"""


def test_event_autosave_uses_supported_catalog_and_only_saves_preferences():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
env.respond(env.posted[0],eventStatus());await flush();
assert.equal(env.elements.get('events-fields').disabled,false);
assert.deepEqual(env.elements.get('events-choice').children.map(x=>x.value),['love-a','love-b']);
env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');
const request=env.posted.at(-1);assert.equal(request.action,'events_save');assert.equal(request.expected_revision,0);
assert.deepEqual(Object.keys(request).sort(),['action','expected_revision','id','settings']);
assert.equal(request.settings.love_events.length,1);assert.equal(request.settings.love_events[0].event_id,'love-a');
assert.equal(request.settings.love_events[0].end_time_ms-request.settings.love_events[0].start_time_ms,30*86400000);
env.respond(request,eventSaved(request));await flush();
assert.equal(env.elements.get('events-save-feedback').dataset.state,'saved');
assert.match(env.elements.get('events-detail').textContent,/다음 서버 시작/);
assert.match(env.elements.get('events-effective').textContent,/없음/);assert.match(env.elements.get('events-next').textContent,/Event A/);
assert.equal(env.posted.some(x=>/reset|reward|clock|restart/.test(x.action)),false);app.dispose();
""")


def test_event_edits_preserve_other_events_and_coalesce_with_latest_cas_revision():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const initial={schema:1,revision:3,love_events:[{event_id:'love-a',start_time_ms:1000,end_time_ms:2000}]};
env.respond(env.posted[0],eventStatus(initial));await flush();
env.elements.get('events-choice').value='love-b';env.elements.get('events-choice').fire('change');
assert.equal(env.posted.length,1,'selection navigation does not save');
env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');const first=env.posted.at(-1);
assert.deepEqual(first.settings.love_events.map(x=>x.event_id),['love-a','love-b']);
env.elements.get('events-choice').value='love-a';env.elements.get('events-choice').fire('change');
env.elements.get('events-enabled').checked=false;env.elements.get('events-enabled').fire('change');
assert.equal(env.posted.at(-1),first,'one request at a time');env.respond(first,eventSaved(first));await flush();
const second=env.posted.at(-1);assert.notEqual(second.id,first.id);assert.equal(second.action,'events_save');
assert.equal(second.expected_revision,4);assert.deepEqual(second.settings.love_events.map(x=>x.event_id),['love-b']);
env.respond(second,eventSaved(second));await flush();assert.equal(env.elements.get('events-save-feedback').dataset.state,'saved');app.dispose();
""")


def test_event_cas_conflict_preserves_draft_and_waits_for_explicit_retry():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
env.respond(env.posted[0],eventStatus());await flush();env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');
const first=env.posted.at(-1);env.scope.idolyServerReply(first.id,{id:first.id,ok:false,error:{code:'event_settings_revision_conflict',message:'safe'}});await flush();
const refresh=env.posted.at(-1);assert.equal(refresh.action,'status');const newest=eventStatus({schema:1,revision:9,love_events:[]});env.respond(refresh,newest);await flush();
assert.equal(env.elements.get('events-enabled').checked,true);assert.equal(env.elements.get('events-save-retry').hidden,false);
assert.match(env.elements.get('events-save-feedback').textContent,/다른 화면/);await env.tick(100);assert.equal(env.posted.at(-1),refresh);
env.elements.get('events-save-retry').fire('click');const retried=env.posted.at(-1);assert.equal(retried.action,'events_save');assert.equal(retried.expected_revision,9);
assert.deepEqual(retried.settings.love_events,first.settings.love_events);app.dispose();
""")


def test_event_invalid_period_and_missing_catalog_never_save_or_block_old_launch_flow():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
env.respond(env.posted[0],eventStatus());await flush();env.elements.get('events-start').value='2026-01-01T00:00';env.elements.get('events-end').value='2027-01-03T00:00';
env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');
assert.equal(env.posted.length,1);assert.equal(env.elements.get('events-save-feedback').dataset.state,'invalid');app.dispose();
const other=environment(),second=api.createSettingsApp(other.scope,other.document,other.timers);other.respond(other.posted[0],status());await flush();
assert.equal(other.elements.get('events-fields').disabled,true);other.scope.idolyServerFlushSettings('00000000-0000-4000-8000-000000000123');await flush();
assert.equal(other.posted.at(-1).action,'launch_settings_barrier');assert.equal(other.posted.at(-1).ready,true);second.dispose();
""")


@pytest.mark.parametrize('language',['ko','en','ja'])
def test_event_interface_changes_immediately_and_has_no_manual_save_button(language):
    run_js(EVENT_JS+"const language="+json.dumps(language)+r""";
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);env.respond(env.posted[0],eventStatus());await flush();
env.elements.get('interface_language').value=language;env.elements.get('interface_language').fire('change');await flush();
const label=env.elements.get('events-effective').textContent;
if(language==='en')assert.match(label,/Active events/);else if(language==='ja')assert.match(label,/現在適用/);else assert.match(label,/현재 적용/);
assert.ok(!env.elements.has('events-save'));assert.equal(env.elements.get('events-fields').disabled,false);app.dispose();
""")


def test_event_bridge_rejects_extra_fields_unsupported_commands_and_malformed_periods():
    run_js(r"""
const env=environment(),bridge=api.createBridge(env.scope,env.timers);
for(const [action,payload] of [['events_reset',{}],['events_status',{path:'/private'}],['events_save',{settings:{schema:1,revision:0,love_events:[]},expected_revision:0,reset:true}],
 ['events_save',{settings:{schema:1,revision:0,love_events:[{event_id:'love-a',start_time_ms:true,end_time_ms:10}]},expected_revision:0}],
 ['events_save',{settings:{schema:1,revision:1,love_events:[]},expected_revision:0}]])await assert.rejects(bridge.request(action,payload));
assert.equal(env.posted.length,0);bridge.dispose();
""")


def test_event_launch_barrier_waits_for_the_pending_event_settings_ack():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
env.respond(env.posted[0],eventStatus());await flush();env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');
const saving=env.posted.at(-1);env.scope.idolyServerFlushSettings('00000000-0000-4000-8000-000000000123');await flush();
assert.equal(env.posted.at(-1),saving);assert.equal(env.elements.get('events-fields').disabled,true);
env.respond(saving,eventSaved(saving));await flush();const barrier=env.posted.at(-1);
assert.equal(barrier.action,'launch_settings_barrier');assert.equal(barrier.ready,true);app.dispose();
""")
