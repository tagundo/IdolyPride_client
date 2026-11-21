"""Completed output access is independent of the current render session."""
from test_ios_unified_web import run_js

OPEN = r'''
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
const latest=action=>[...e.posted].reverse().find(row=>row.action===action);
e.respond(latest('status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(latest('mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});
e.respond(latest('mp4_status'),{phase:'idle',ready:false});
e.respond(latest('mp4_queue_status'),{available:false,running:false,phase:'idle',jobs:[]});await flush();
const id='b'.repeat(32),record={export_id:id,bytes:2048,created_ms:1795236000000};
function catalog(records=[record],offset=0,total=records.length){return {schema:1,available:true,records,offset,total,has_more:offset+records.length<total};}
'''


def test_completed_bridge_accepts_only_export_ids_and_bounded_pages():
    run_js(r'''
const e=environment(),b=api.createBridge(e.scope,e.timers),id='a'.repeat(32);
for(const [action,payload] of [
 ['mp4_completed_status',{path:'/tmp/private'}],['mp4_completed_status',{offset:-1}],
 ['mp4_completed_status',{offset:1}],['mp4_completed_status',{offset:65568}],
 ['mp4_save',{export_id:'../foreign'}],['mp4_save',{export_id:id,job_id:id}],
 ['mp4_save',{export_id:id,path:'/tmp/private'}],['mp4_save',{export_id:true}]
])await assert.rejects(b.request(action,payload));
assert.equal(e.posted.length,0);
for(const [action,payload] of [['mp4_completed_status',{}],['mp4_completed_status',{offset:32}],['mp4_save',{export_id:id}]]){
 const p=b.request(action,payload),request=e.posted.at(-1);e.respond(request,{});await p;
}b.dispose();
''')


def test_cold_idle_session_can_save_persisted_export_without_auto_picker():
    run_js(OPEN+r'''
e.respond(latest('mp4_completed_status'),catalog());await flush();
assert.equal(e.elements.get('mp4-save').hidden,true,'No current session is complete');
let rows=e.elements.get('mp4-completed-rows').children;assert.equal(rows.length,1);
assert.match(rows[0].children[0].textContent,/2.0 KB/);assert.doesNotMatch(rows[0].children[0].textContent,/bbbbbb/);
assert.equal(e.posted.some(row=>row.action==='mp4_save'),false,'Loading completed outputs never opens a picker');
rows[0].children[1].fire('click');await flush();
const save=latest('mp4_save');assert.deepEqual(save,{id:save.id,action:'mp4_save',export_id:id});
e.respond(save,{});await flush();
assert.equal(e.elements.get('mp4-completed-rows').children.length,1);
assert.equal(e.elements.get('mp4-completed-rows').children[0].children[1].disabled,false);
app.dispose();
''')


def test_canceled_save_and_new_render_do_not_remove_completed_output():
    run_js(OPEN+r'''
e.respond(latest('mp4_completed_status'),catalog());await flush();
e.elements.get('mp4-completed-rows').children[0].children[1].fire('click');await flush();
const save=latest('mp4_save');e.scope.idolyServerReply(save.id,{id:save.id,ok:false,error:'cancelled'});await flush();
assert.equal(e.elements.get('mp4-completed-rows').children[0].children[1].disabled,false);
e.elements.get('panel-mp4').fire('toggle');await flush();
e.respond(latest('mp4_status'),{phase:'preparing_audio',ready:false,export_id:'c'.repeat(32)});
e.respond(latest('mp4_queue_status'),{available:true,running:true,phase:'rendering',jobs:[]});
e.respond(latest('mp4_completed_status'),catalog());await flush();
assert.equal(e.elements.get('mp4-save').hidden,true);
assert.equal(e.elements.get('mp4-completed-rows').children.length,1);
e.elements.get('mp4-completed-rows').children[0].children[1].fire('click');await flush();
assert.equal(latest('mp4_save').export_id,id,'Save remains bound to retained output, not the new job');
app.dispose();
''')


def test_completed_poll_keeps_button_identity_and_rejects_untrusted_rows():
    run_js(OPEN+r'''
e.respond(latest('mp4_completed_status'),catalog());await flush();
const button=e.elements.get('mp4-completed-rows').children[0].children[1];
e.elements.get('panel-mp4').fire('toggle');await flush();
e.respond(latest('mp4_completed_status'),catalog());await flush();
assert.equal(e.elements.get('mp4-completed-rows').children[0].children[1],button,'Status polls do not replace touch targets');
e.elements.get('panel-mp4').fire('toggle');await flush();
e.respond(latest('mp4_completed_status'),catalog([{...record,path:'/tmp/private/foreign.mp4'}]));await flush();
assert.equal(e.elements.get('mp4-completed-rows').children[0].children[1],button,'Invalid catalog cannot replace verified rows');
assert.equal(e.posted.some(row=>row.action==='mp4_save'),false);app.dispose();
''')


def test_completed_pagination_and_stale_row_use_stable_ids():
    run_js(OPEN+r'''
const page=Array.from({length:32},(_,index)=>({...record,export_id:(index+1).toString(16).padStart(32,'0')}));
e.respond(latest('mp4_completed_status'),catalog(page,0,33));await flush();
const stale=e.elements.get('mp4-completed-rows').children[0].children[1];
assert.equal(e.elements.get('mp4-completed-next').disabled,false);
e.elements.get('mp4-completed-next').fire('click');await flush();
assert.equal(latest('mp4_completed_status').offset,32);
e.respond(latest('mp4_completed_status'),catalog([record],32,33));await flush();
assert.equal(e.elements.get('mp4-completed-next').disabled,true);
assert.equal(e.elements.get('mp4-completed-previous').disabled,false);
stale.fire('click');await flush();assert.equal(e.posted.some(row=>row.action==='mp4_save'),false);
e.elements.get('mp4-completed-rows').children[0].children[1].fire('click');await flush();
assert.equal(latest('mp4_save').export_id,id);app.dispose();
''')


def test_completed_page_shrinking_returns_to_first_page_without_saving():
    run_js(OPEN+r'''
const page=Array.from({length:32},(_,index)=>({...record,export_id:(index+1).toString(16).padStart(32,'0')}));
e.respond(latest('mp4_completed_status'),catalog(page,0,33));await flush();
e.elements.get('mp4-completed-next').fire('click');await flush();
e.respond(latest('mp4_completed_status'),catalog([],32,1));await flush();
assert.equal(latest('mp4_completed_status').offset,0,'Removed outputs cannot strand the selected page');
e.respond(latest('mp4_completed_status'),catalog());await flush();
assert.equal(e.elements.get('mp4-completed-rows').children.length,1);
assert.equal(e.elements.get('mp4-completed-previous').disabled,true);
assert.equal(e.posted.some(row=>row.action==='mp4_save'),false);app.dispose();
''')
