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
assert.match(env.elements.get('events-effective').textContent,/0/);assert.match(env.elements.get('events-next').getAttribute('title'),/Event A/);
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


def test_event_cas_conflict_merges_only_local_intents_onto_latest_mode_revision():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
env.respond(env.posted[0],eventStatus());await flush();env.elements.get('events-enabled').checked=true;env.elements.get('events-enabled').fire('change');
const first=env.posted.at(-1);env.scope.idolyServerReply(first.id,{id:first.id,ok:false,error:{code:'event_settings_revision_conflict',message:'safe'}});await flush();
const refresh=env.posted.at(-1);assert.equal(refresh.action,'events_status');assert.equal(refresh.mode,'normal');
const newest=eventStatus({schema:1,revision:9,love_events:[{event_id:'love-b',start_time_ms:1000,end_time_ms:2000}]}).runtime.event_settings;newest.media_mode=false;
env.respond(refresh,newest);await flush();await env.tick(180);
const retried=env.posted.at(-1);assert.equal(retried.action,'events_save');assert.equal(retried.expected_revision,9);
assert.deepEqual(retried.settings.love_events.map(row=>row.event_id),['love-a','love-b'],'Other window changes are retained');
assert.equal(env.elements.get('events-save-retry').hidden,true);
env.respond(retried,eventSaved(retried));await flush();assert.equal(env.elements.get('events-save-feedback').dataset.state,'saved');app.dispose();
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
if(language==='en')assert.match(label,/Active/);else if(language==='ja')assert.match(label,/適用中/);else assert.match(label,/현재 적용/);
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


def test_visible_checklist_and_bulk_controls_support_rapid_changes_without_rebuilding_rows():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);env.respond(env.posted[0],eventStatus());await flush();
const cards=env.elements.get('events-list').children;assert.equal(cards.length,2);
cards[0].eventInput.checked=true;cards[0].eventInput.fire('change');cards[1].eventInput.checked=true;cards[1].eventInput.fire('change');
assert.equal(env.elements.get('events-list').children[0],cards[0]);await env.tick(180);
const first=env.posted.at(-1);assert.equal(first.action,'events_save');assert.deepEqual(first.settings.love_events.map(row=>row.event_id),['love-a','love-b']);
cards[0].eventInput.checked=false;cards[0].eventInput.fire('change');await env.tick(180);assert.equal(env.posted.at(-1),first);
env.respond(first,eventSaved(first));await flush();const next=env.posted.at(-1);assert.equal(next.expected_revision,1);assert.deepEqual(next.settings.love_events.map(row=>row.event_id),['love-b']);
env.respond(next,eventSaved(next));await flush();env.elements.get('events-enable-all').fire('click');const all=env.posted.at(-1);
assert.equal(all.settings.love_events.length,2);env.respond(all,eventSaved(all));await flush();env.elements.get('events-disable-all').fire('click');assert.equal(env.posted.at(-1).settings.love_events.length,0);app.dispose();
""")


def test_gallery_default_all_is_editable_without_fake_windows_and_titles_follow_interface_language():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);const initial=eventStatus({schema:1,revision:0,love_events:[{event_id:'love-a',start_time_ms:0,end_time_ms:0},{event_id:'love-b',start_time_ms:0,end_time_ms:0}]});
initial.runtime.event_settings.media_mode=true;initial.runtime.event_settings.media_default_all=true;initial.runtime.event_settings.effective=structuredClone(initial.runtime.event_settings.saved);
initial.runtime.event_settings.catalog.events[0].titles={ko:'레이 편',ja:'怜編',en:'Rei'};
env.respond(env.posted[0],initial);await flush();assert.equal(env.elements.get('events-mode').value,'media');assert.equal(env.elements.get('events-period-editor').hidden,true);
assert.equal(env.elements.get('events-list').children[0].children[1].textContent,'레이 편');
env.elements.get('events-disable-all').fire('click');const empty=env.posted.at(-1);assert.equal(empty.action,'events_save');assert.equal(empty.mode,'media');assert.equal(empty.settings.love_events.length,0);
const receipt=structuredClone(initial);receipt.runtime.event_settings.saved={schema:1,revision:1,love_events:[]};env.respond(empty,receipt);await flush();
env.elements.get('events-enable-all').fire('click');const all=env.posted.at(-1);assert.equal(all.mode,'media');assert.ok(all.settings.love_events.every(row=>row.start_time_ms===0&&row.end_time_ms===0));
env.respond(all,{...initial,runtime:{...initial.runtime,event_settings:{...initial.runtime.event_settings,saved:{...all.settings,revision:2}}}});await flush();
env.elements.get('interface_language').value='en';env.elements.get('interface_language').fire('change');await flush();assert.equal(env.elements.get('events-list').children[0].children[1].textContent,'Rei');app.dispose();
""")


def test_extra_event_shows_its_separate_game_entry_in_all_interface_languages():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);const initial=eventStatus();
initial.runtime.event_settings.catalog.events[1]={id:'love-extra-25-0426',title:'サキュ×まほ',supported:true};
env.respond(env.posted[0],initial);await flush();
for (const [language,expected] of [['ko','게임 홈 → 이벤트 → 사큐×마호'],['ja','ゲームホーム → イベント → サキュ×まほ'],['en','Game Home → Event → Succu × Magic']]) {
 env.elements.get('interface_language').value=language;env.elements.get('interface_language').fire('change');await flush();
 const cards=env.elements.get('events-list').children;
 assert.equal((cards[0].children[1].children || []).length,0,'Standard events do not use the Extra entry');
 assert.equal(cards[1].children[1].children[1].textContent,expected);
 assert.equal(cards[1].eventInput.value,'love-extra-25-0426');
}
assert.equal(env.posted.some(request=>request.action==='events_save'),false,'Viewing directions never edits event choices');app.dispose();
""")


def test_mode_navigation_waits_for_pending_save_and_does_not_accept_old_mode_status():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);env.respond(env.posted[0],eventStatus());await flush();
env.elements.get('events-enable-all').fire('click');const saving=env.posted.at(-1);env.elements.get('events-mode').value='media';env.elements.get('events-mode').fire('change');await flush();assert.equal(env.posted.at(-1),saving);
env.respond(saving,eventSaved(saving));await flush();const loading=env.posted.at(-1);assert.equal(loading.action,'events_status');assert.equal(loading.mode,'media');
const media=eventStatus({schema:1,revision:0,love_events:[]}).runtime.event_settings;media.media_mode=true;env.respond(loading,media);await flush();
assert.equal(env.elements.get('events-mode').value,'media');assert.equal(env.elements.get('events-period-editor').hidden,true);
env.scope.idolyServerEvent({event:'status',status:eventStatus({schema:1,revision:90,love_events:[]})});await flush();assert.equal(env.elements.get('events-mode').value,'media');
assert.equal(env.elements.get('events-fields').disabled,false);app.dispose();
""")


def test_host_gallery_preferences_are_separate_and_legacy_commands_keep_normal_windows(harness,monkeypatch):
    h=harness
    monkeypatch.setattr(event_settings,"_catalog",lambda root,override=None:copy.deepcopy(CATALOG))
    start(h)
    normal=command(h,"events_status",mode="normal")["result"]
    gallery=command(h,"events_status",mode="media")["result"]
    assert normal["saved"]["love_events"]==[] and normal["media_mode"] is False
    assert gallery["media_mode"] is True and gallery["media_default_all"] is True
    assert {row["event_id"] for row in gallery["saved"]["love_events"]}=={"love-a","love-b"}
    assert all(row["start_time_ms"]==row["end_time_ms"]==0 for row in gallery["saved"]["love_events"])
    (h.data/"state.db").write_bytes(b"normal-account-canary")
    (h.data/"media-state.db").write_bytes(b"gallery-account-canary")
    empty={"schema":1,"revision":gallery["saved"]["revision"],"love_events":[]}
    receipt=command(h,"events_save",mode="media",settings=empty,expected_revision=empty["revision"])
    assert receipt["ok"] and receipt["result"]["runtime"]["event_settings"]["media_mode"] is True
    assert command(h,"events_status",mode="media")["result"]["saved"]["love_events"]==[]
    assert command(h,"events_status")["result"]["saved"]["love_events"]==[]
    settings={"schema":1,"revision":0,"love_events":[{"event_id":"love-a","start_time_ms":1000,"end_time_ms":2000}]}
    assert command(h,"events_save",mode="normal",settings=settings,expected_revision=0)["ok"]
    assert command(h,"events_status")["result"]["saved"]["love_events"]==settings["love_events"]
    assert command(h,"events_status",mode="media")["result"]["saved"]["love_events"]==[]
    assert (h.data/"state.db").read_bytes()==b"normal-account-canary"
    assert (h.data/"media-state.db").read_bytes()==b"gallery-account-canary"
    assert h.runtimes[0].stops==0 and len(h.calls)==1
    from idoly_local import ios_host
    original_status=h.runtimes[0].status
    monkeypatch.setattr(h.runtimes[0],"status",lambda:{**original_status(),"unrelated_large_history":"x"*(ios_host.MAX_JSON_BYTES*2)})
    thinned=command(h,"status")["result"]
    assert thinned["diagnostics_truncated"] is True
    assert thinned["runtime"]["event_settings"]["media_mode"] is True
    assert thinned["runtime"]["event_settings"]["media_default_all"] is False
    assert thinned["runtime"]["event_settings"]["media_all_supported"] is False
    assert not command(h,"events_status",mode="other")["ok"]


def test_status_poll_started_during_event_save_cannot_revert_a_newer_acknowledged_revision():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);env.respond(env.posted[0],eventStatus());await flush();
env.elements.get('events-enable-all').fire('click');const saving=env.posted.at(-1);
env.elements.get('refresh').fire('click');const stalePoll=env.posted.at(-1);assert.equal(stalePoll.action,'status');
env.respond(saving,eventSaved(saving));await flush();
env.respond(stalePoll,eventStatus());await flush();
assert.ok(env.elements.get('events-list').children.every(card=>card.eventInput.checked),'Old status cannot repaint newer saved choices');
assert.match(env.elements.get('events-next').getAttribute('title'),/Event B/);
env.elements.get('events-list').children[0].eventInput.checked=false;env.elements.get('events-list').children[0].eventInput.fire('change');await env.tick(180);
const next=env.posted.at(-1);assert.equal(next.expected_revision,1);assert.deepEqual(next.settings.love_events.map(row=>row.event_id),['love-b']);app.dispose();
""")


def test_automatic_account_mode_change_can_load_revision_zero_after_a_high_normal_revision():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const normal=eventStatus({schema:1,revision:900,love_events:[]});normal.options.media_mode=false;normal.runtime.event_settings.media_mode=false;env.respond(env.posted[0],normal);await flush();
const media=eventStatus({schema:1,revision:0,love_events:[{event_id:'love-a',start_time_ms:0,end_time_ms:0},{event_id:'love-b',start_time_ms:0,end_time_ms:0}]});media.runtime.event_settings.media_mode=true;
env.scope.idolyServerEvent({event:'status',status:media});await flush();
assert.equal(env.elements.get('events-mode').value,'media');assert.equal(env.elements.get('events-fields').disabled,false);
assert.ok(env.elements.get('events-list').children.every(card=>card.eventInput.checked));app.dispose();
""")


def test_options_ack_invalidates_an_inflight_poll_before_it_can_revert_gallery_mode():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);
const normal=eventStatus();normal.options.media_mode=false;normal.runtime.event_settings.media_mode=false;env.respond(env.posted[0],normal);await flush();
env.elements.get('media_mode').checked=true;env.elements.get('media_mode').fire('change');const saving=env.posted.at(-1);assert.equal(saving.action,'save_options');
env.elements.get('refresh').fire('click');const oldPoll=env.posted.at(-1);assert.equal(oldPoll.action,'status');
const media=eventStatus({schema:1,revision:0,love_events:[{event_id:'love-a',start_time_ms:0,end_time_ms:0},{event_id:'love-b',start_time_ms:0,end_time_ms:0}]});media.runtime.event_settings.media_mode=true;
env.respond(saving,media);await flush();env.respond(oldPoll,normal);await flush();
assert.equal(env.elements.get('media_mode').checked,true);assert.equal(env.elements.get('events-mode').value,'media');assert.equal(env.elements.get('events-fields').disabled,false);app.dispose();
""")


def test_newer_same_value_intent_survives_old_ack_and_an_external_newer_revision():
    run_js(EVENT_JS+r"""
const env=environment(),app=api.createSettingsApp(env.scope,env.document,env.timers);env.respond(env.posted[0],eventStatus());await flush();
const enabled=env.elements.get('events-enabled');enabled.checked=true;enabled.fire('change');const oldOn=env.posted.at(-1);
enabled.checked=false;enabled.fire('change');enabled.checked=true;enabled.fire('change');assert.equal(env.posted.at(-1),oldOn);
const external=eventStatus({schema:1,revision:2,love_events:[{event_id:'love-b',start_time_ms:1000,end_time_ms:2000}]});
env.scope.idolyServerEvent({event:'status',status:external});await flush();
env.respond(oldOn,eventSaved(oldOn));await flush();
const latest=env.posted.at(-1);assert.notEqual(latest.id,oldOn.id);assert.equal(latest.action,'events_save');assert.equal(latest.expected_revision,2);
assert.deepEqual(latest.settings.love_events.map(row=>row.event_id),['love-a','love-b'],'The later on intent survives while unrelated external changes remain');
assert.equal(env.elements.get('events-list').children[0].eventInput.checked,true);app.dispose();
""")
