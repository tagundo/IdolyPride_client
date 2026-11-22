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


def test_queue_scene_preparation_replaces_idle_or_previous_terminal_summary_and_stale_progress():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
async function sample(session,queue){
 e.elements.get('panel-mp4').fire('toggle');await flush();
 e.respond(e.posted.filter(x=>x.action==='mp4_status').at(-1),session);
 e.respond(e.posted.filter(x=>x.action==='mp4_queue_status').at(-1),{available:true,can_run:false,running:false,command_pending:false,phase:'idle',jobs:[],...queue});await flush();
}
for(const phase of ['idle','completed','cancelled','failed']){
 await sample({phase,ready:false,frames:200,total_frames:200,width:1920,height:1080,error_code:phase==='failed'?'capture_failed':'none'},
  {running:true,phase:'replaying'});
 assert.equal(e.elements.get('mp4-summary').textContent,'게임 화면을 준비하고 있습니다.');
 assert.equal(e.elements.get('mp4-progress').hidden,true);
 if(phase==='failed')assert.equal(e.elements.get('mp4-feedback').textContent,'capture_failed');
}
// Enqueue can be accepted before its first native Unity tick creates the job.
await sample({phase:'idle',ready:false},{command_pending:true});
assert.equal(e.elements.get('mp4-summary').textContent,'게임 화면을 준비하고 있습니다.');
for(const [language,expected] of [['ja','ゲーム画面を準備しています。'],['en','Preparing the game scene.']]){
 e.elements.get('interface_language').value=language;e.elements.get('interface_language').fire('change');await flush();
 assert.equal(e.elements.get('mp4-summary').textContent,expected);
}
app.dispose();
""")


def test_queue_work_does_not_replace_active_capture_pause_or_failure_feedback():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
async function sample(session,queue){
 e.elements.get('panel-mp4').fire('toggle');await flush();
 e.respond(e.posted.filter(x=>x.action==='mp4_status').at(-1),{ready:false,frames:41,total_frames:100,...session});
 e.respond(e.posted.filter(x=>x.action==='mp4_queue_status').at(-1),{available:true,can_run:false,running:true,command_pending:true,phase:'waiting_for_scene',jobs:[],...queue});await flush();
}
for(const [phase,label] of [['preparing_audio','음원 준비 중'],['rendering','MP4 렌더링'],['finishing','MP4 마무리 중'],['cancelling','취소 중'],['pausing','MP4 일시 정지 중…'],['paused','MP4 일시 정지']]){
 await sample({phase,pause_reason:'user_paused'});
 assert.equal(e.elements.get('mp4-summary').textContent,label+' · 41 / 100');
 assert.equal(e.elements.get('mp4-progress').hidden,false);assert.equal(e.elements.get('mp4-progress').value,.41);
 if(['paused','pausing'].includes(phase))assert.match(e.elements.get('mp4-feedback').textContent,/계속하기/);
}
await sample({phase:'failed',error_code:'audio_mix_failed'},{running:false,command_pending:false,phase:'failed',error_code:'queued_mv_prepare_failed'});
assert.match(e.elements.get('mp4-summary').textContent,/MP4 실패/);
assert.equal(e.elements.get('mp4-feedback').textContent,'audio_mix_failed');
assert.equal(e.elements.get('mp4-queue-feedback').textContent,'queued_mv_prepare_failed');
await sample({phase:'completed',frames:100},{running:false,command_pending:false,phase:'completed'});
assert.equal(e.elements.get('mp4-summary').textContent,'MP4 완료 · 100 / 100');assert.equal(e.elements.get('mp4-progress').hidden,false);
await sample({phase:'idle',frames:0,total_frames:0},{running:false,command_pending:false,phase:'idle'});
assert.equal(e.elements.get('mp4-summary').textContent,'3D MV 준비 대기');app.dispose();
""")


def test_saved_runnable_queue_does_not_request_current_mv_playback():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:false,selected_mv:false,selection_error:'selected_mv_not_loaded'});
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[{job_id:'a'.repeat(32),state:'pending',title_localizations:{ko:'저장한 곡'},actor_count:3,fps_num:60,width:2880,height:2160}]});await flush();
assert.equal(e.elements.get('mp4-queue-run').disabled,false);
assert.equal(e.elements.get('mp4-summary').textContent,'저장된 목록을 내보낼 수 있습니다.');
assert.equal(e.elements.get('mp4-feedback').textContent,'');
for(const [language,expected] of [['en','The saved queue is ready to export.'],['ja','保存したリストを書き出せます。']]){
 e.elements.get('interface_language').value=language;e.elements.get('interface_language').fire('change');await flush();
 assert.equal(e.elements.get('mp4-summary').textContent,expected);
}
app.dispose();
""")
