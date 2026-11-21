"""Queue actions use stable job IDs and retain snapshots across status polls."""
from test_ios_unified_web import run_js


def test_queue_bridge_only_accepts_documented_actions_and_owned_job_id_shapes():
    run_js(r"""
const e=environment(), b=api.createBridge(e.scope,e.timers), id='a'.repeat(32);
for (const [action,payload] of [
 ['mp4_queue_run',{path:'/tmp/jobs'}],['mp4_queue_status',{output_id:id}],
 ['mp4_queue_cancel',{job_id:'../foreign'}],['mp4_queue_remove',{job_id:id,delete_file:true}],
 ['mp4_queue_retry',{job_id:true}],['mp4_queue_move',{job_id:id,position:8}],
 ['mp4_queue_remove',{job_id:id,delete_output:false}],['mp4_queue_remove',{job_id:id,delete_output:1}],
 ['mp4_queue_move',{job_id:id,position:-1}],['mp4_queue_move',{job_id:id,position:1.5}],
 ['mp4_enqueue',{fps:30,video_bitrate:16000000,video_codec:1,timeline:'other'}],
 ['mp4_save',{job_id:id,output_id:'b'.repeat(32)}]
]) await assert.rejects(b.request(action,payload));
assert.equal(e.posted.length,0);
for (const [action,payload] of [['mp4_queue_run',{}],['mp4_queue_pause',{}],['mp4_queue_resume',{}],['mp4_queue_move',{job_id:id,position:0}],['mp4_save',{job_id:id}]]) {
 const p=b.request(action,payload);const request=e.posted.at(-1);assert.equal(request.action,action);e.respond(request,{});await p;
}b.dispose();
""")


def test_cold_queue_cannot_run_and_completed_deletion_requires_second_click():
    run_js(r"""
const e=environment(), app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'completed',ready:false,export_id:'b'.repeat(32)});
const completed={job_id:'a'.repeat(32),output_id:'b'.repeat(32),timeline:'tln_live_secret',title_localizations:{ko:'노래 이름',en:'Song title',ja:'曲名'},state:'completed',actor_count:5,fps_num:30,width:1280,height:720};
const pending={...completed,job_id:'c'.repeat(32),output_id:'',state:'pending'};
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:false,running:false,phase:'idle',jobs:[completed,pending]});await flush();
assert.equal(e.elements.get('mp4-queue-run').disabled,true);
assert.equal(e.elements.get('mp4-save').hidden,true);
e.elements.get('interface_language').value='en';e.elements.get('interface_language').fire('change');await flush();
let row=e.elements.get('mp4-queue-jobs').children[0];assert.match(row.children[0].textContent,/Song title/);
assert.doesNotMatch(row.children[0].textContent,/tln_live_secret/);
const remove=row.children[2].children.find(node=>node.textContent==='Delete file and job');assert.ok(remove);
remove.fire('click');await flush();assert.equal(e.posted.some(x=>x.action==='mp4_queue_remove'),false);
assert.equal(remove.textContent,'Confirm deletion');assert.match(row.children[3].textContent,/saved elsewhere/);
remove.fire('click');await flush();
const request=e.posted.find(x=>x.action==='mp4_queue_remove');assert.deepEqual(request,{id:request.id,action:'mp4_queue_remove',job_id:completed.job_id,delete_output:true});
e.respond(request,{available:true,can_run:false,running:false,phase:'idle',jobs:[pending]});await flush();app.dispose();
""")


def test_queue_displays_distinct_mv_snapshots_and_moves_by_id_without_paths():
    run_js(r"""
const e=environment(), app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:true});
const a={job_id:'a'.repeat(32),timeline:'tri-004',title_localizations:{ko:'첫 번째 노래',ja:'最初の曲',en:'First song'},state:'pending',actor_count:5,fps_num:60,width:1920,height:1080};
const b={...a,job_id:'b'.repeat(32),timeline:'tri-005',title_localizations:{ko:'두 번째 노래',ja:'次の曲',en:'Second song'},fps_num:30};
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[a,b]});await flush();
let rows=e.elements.get('mp4-queue-jobs').children;assert.equal(rows.length,2);
assert.match(rows[0].children[0].textContent,/첫 번째 노래/);assert.match(rows[1].children[0].textContent,/두 번째 노래/);
assert.match(rows[0].children[1].textContent,/60 fps/);assert.match(rows[1].children[1].textContent,/30 fps/);
const move=rows[1].children[2].children.find(node=>node.textContent==='위로');assert.ok(move);move.fire('click');await flush();
const request=e.posted.find(x=>x.action==='mp4_queue_move');assert.deepEqual(request,{id:request.id,action:'mp4_queue_move',job_id:b.job_id,position:0});
e.respond(request,{available:true,can_run:true,running:false,phase:'idle',jobs:[b,a]});await flush();
assert.match(e.elements.get('mp4-queue-jobs').children[0].children[0].textContent,/두 번째 노래/);
assert.equal(e.elements.get('mp4-queue-run').disabled,false);
e.elements.get('mp4-fps').value='60';e.elements.get('mp4-codec').value='1';e.elements.get('mp4-bitrate').value='16000000';
e.elements.get('mp4-enqueue').fire('click');await flush();
const add=e.posted.find(x=>x.action==='mp4_enqueue');assert.ok(add);assert.deepEqual(Object.keys(add).sort(),['action','fps','height','id','video_bitrate','video_codec','width']);
assert.equal(add.video_bitrate,0);assert.equal(add.width,0);assert.equal(add.height,0);
e.respond(add,{available:true,can_run:true,command_pending:true,running:false,phase:'idle',jobs:[b,a]});await flush();
assert.equal(e.elements.get('mp4-queue-run').disabled,true);app.dispose();
""")


def test_completed_job_save_and_interrupted_retry_use_original_stable_job_ids():
    run_js(r"""
const e=environment(), app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:true});
const completed={job_id:'c'.repeat(32),output_id:'d'.repeat(32),timeline:'done',state:'completed',actor_count:5,fps_num:30,width:1280,height:720};
const interrupted={...completed,job_id:'e'.repeat(32),output_id:'f'.repeat(32),timeline:'interrupted',state:'interrupted',error_code:'process_interrupted'};
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[completed,interrupted]});await flush();
let rows=e.elements.get('mp4-queue-jobs').children;
assert.match(rows[1].children[1].textContent,/중단됨/);
assert.equal(rows[1].children[2].children.some(node=>node.textContent==='저장·공유'),false);
rows[0].children[2].children.find(node=>node.textContent==='저장·공유').fire('click');await flush();
const save=e.posted.find(x=>x.action==='mp4_save');assert.deepEqual(save,{id:save.id,action:'mp4_save',job_id:completed.job_id});e.respond(save,{presented:true});await flush();
rows=e.elements.get('mp4-queue-jobs').children;
rows[1].children[2].children.find(node=>node.textContent==='다시 시도').fire('click');await flush();
const retry=e.posted.find(x=>x.action==='mp4_queue_retry');assert.deepEqual(retry,{id:retry.id,action:'mp4_queue_retry',job_id:interrupted.job_id});
e.respond(retry,{available:true,can_run:true,running:false,phase:'idle',jobs:[completed,{...interrupted,state:'pending',output_id:'',error_code:'none'}]});await flush();
assert.equal(api.translateUI('큐 실행','en'),'Run queue');assert.equal(api.translateUI('현재 MV 추가','ja'),'現在のMVを追加');app.dispose();
""")
