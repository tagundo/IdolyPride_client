"""Exercise persisted numeric export choices through the shipping page bridge."""
from test_ios_unified_web import run_js


def test_export_options_are_written_before_menu_close_and_reloaded_without_web_storage():
    run_js(r"""
let stored={schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080};
async function openMenu(){
 const e=environment(),post=e.scope.webkit.messageHandlers.idolyServer.postMessage;
 e.scope.webkit.messageHandlers.idolyServer.postMessage=request=>{
  post(request);
  // Model the trusted native preference write at dispatch, before its delayed
  // acknowledgement; a destroyed WebView cannot cancel this write.
  if(request.action==='mp4_options_save')stored=JSON.parse(JSON.stringify(request.options));
 };
 const app=api.createSettingsApp(e.scope,e.document,e.timers);
 e.elements.get('category-graphics').fire('click');await flush();
 assert.equal(e.elements.get('mp4-fields').disabled,true);
 e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{...stored}});
 e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:false});
 e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:false,running:false,phase:'idle',jobs:[]});
 return {e,app};
}
const first=await openMenu();await flush();const e=first.e;
assert.equal(e.scope.localStorage,undefined);assert.equal(e.elements.get('mp4-fields').disabled,false);
e.elements.get('panel-mp4').fire('toggle');await flush();
// Ordinary progress/readiness polling must not disable a focused number field.
assert.equal(e.elements.get('mp4-fields').disabled,false);
function edit(id,value,event='change'){e.elements.get(id).value=value;e.elements.get(id).fire(event);}
edit('mp4-fps','30');edit('mp4-codec','2');edit('mp4-resolution-mode','custom');
edit('mp4-width','1280','input');edit('mp4-height','720','input');
edit('mp4-bitrate-mode','custom');edit('mp4-bitrate','12.345678','input');
const expected={schema:1,fps:30,video_codec:2,bitrate_mode:'custom',video_bitrate:12345678,resolution_mode:'custom',width:1280,height:720};
assert.deepEqual(stored,expected);
const saves=e.posted.filter(x=>x.action==='mp4_options_save');assert.equal(saves.length,7);
assert.ok(saves.every(x=>Object.keys(x).sort().join(',')==='action,id,options'));
// Older acknowledgements never reset the visible, newer input.
e.respond(saves[0],{options:saves[0].options});await flush();
assert.equal(e.elements.get('mp4-bitrate').value,'12.345678');assert.equal(e.elements.get('mp4-fps').value,'30');
const oldReply=e.scope.idolyServerReply;first.app.dispose();
// A new page and a fresh JavaScript scope have no shared localStorage at all.
const second=await openMenu();await flush();
assert.equal(second.e.elements.get('mp4-fps').value,'30');assert.equal(second.e.elements.get('mp4-codec').value,'2');
assert.equal(second.e.elements.get('mp4-bitrate-mode').value,'custom');assert.equal(second.e.elements.get('mp4-bitrate').value,'12.345678');
assert.equal(second.e.elements.get('mp4-resolution-mode').value,'custom');assert.equal(second.e.elements.get('mp4-width').value,'1280');assert.equal(second.e.elements.get('mp4-height').value,'720');
oldReply(saves.at(-1).id,{id:saves.at(-1).id,ok:true,result:{options:saves[0].options}});
assert.equal(second.e.elements.get('mp4-bitrate').value,'12.345678');second.app.dispose();
""")


def test_invalid_numeric_drafts_stay_visible_and_do_not_replace_last_valid_preferences():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
const options={schema:1,fps:30,video_codec:2,bitrate_mode:'custom',video_bitrate:12345678,resolution_mode:'custom',width:1280,height:720};
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:true,source_width:1920,source_height:1080});
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[]});await flush();
const writes=()=>e.posted.filter(x=>x.action==='mp4_options_save');
for(const value of ['','1e1','0.099999','200.000001','NaN','Infinity']){
 e.elements.get('mp4-bitrate').value=value;e.elements.get('mp4-bitrate').fire('input');await flush();
 assert.equal(e.elements.get('mp4-bitrate').value,value);assert.equal(writes().length,0);
 assert.equal(e.elements.get('mp4-start').disabled,true);assert.equal(e.elements.get('mp4-enqueue').disabled,true);
 assert.match(e.elements.get('mp4-options-feedback').textContent,/0.1~200/);
}
e.elements.get('mp4-bitrate').value='0.1';e.elements.get('mp4-bitrate').fire('input');await flush();
assert.equal(writes().at(-1).options.video_bitrate,100000);assert.equal(e.elements.get('mp4-start').disabled,false);
const count=writes().length;
for(const value of ['','17','4098','1280.5']){
 e.elements.get('mp4-width').value=value;e.elements.get('mp4-width').fire('input');await flush();
 assert.equal(e.elements.get('mp4-width').value,value);assert.equal(writes().length,count);
 assert.equal(e.elements.get('mp4-start').disabled,true);assert.match(e.elements.get('mp4-options-feedback').textContent,/16~4096/);
}
e.elements.get('mp4-width').value='3840';e.elements.get('mp4-width').fire('input');await flush();
assert.equal(writes().at(-1).options.width,3840);assert.equal(e.elements.get('mp4-start').disabled,false);
e.elements.get('mp4-start').fire('click');await flush();
const start=e.posted.find(x=>x.action==='mp4_start');assert.deepEqual(start,{id:start.id,action:'mp4_start',fps:30,video_codec:2,video_bitrate:100000,width:3840,height:720});
app.dispose();
""")


def test_recommended_bitrate_tracks_source_output_fps_and_codec_without_storing_a_stale_number():
    run_js(r"""
assert.equal(api.recommendedMP4Bitrate(1920,1080,60,1),17420000);
assert.equal(api.recommendedMP4Bitrate(1920,1080,120,1),34840000);
assert.equal(api.recommendedMP4Bitrate(1920,1080,60,2),11200000);
assert.equal(api.recommendedMP4Bitrate(3840,2160,60,1),69670000);
assert.equal(api.recommendedMP4Bitrate(1921,1081,60,1),17420000);
assert.equal(api.recommendedMP4Bitrate(16,16,30,1),250000);
for(const args of [[0,1080,60,1],[1920,5000,60,1],[1920,1080,90,1],[1920,1080,60,true]])assert.equal(api.recommendedMP4Bitrate(...args),null);
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:true,source_width:1921,source_height:1081});
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[]});await flush();
assert.match(e.elements.get('mp4-recommendation').textContent,/17.42 Mbps · 1920 × 1080/);
e.elements.get('mp4-codec').value='2';e.elements.get('mp4-codec').fire('change');await flush();
assert.match(e.elements.get('mp4-recommendation').textContent,/11.20 Mbps/);
e.elements.get('mp4-enqueue').fire('click');await flush();
const add=e.posted.find(x=>x.action==='mp4_enqueue');assert.deepEqual(add,{id:add.id,action:'mp4_enqueue',fps:60,video_codec:2,video_bitrate:0,width:0,height:0});
app.dispose();
""")


def test_export_bridge_rejects_odd_partial_and_out_of_range_output_options():
    run_js(r"""
const e=environment(),bridge=api.createBridge(e.scope,e.timers);
const base={fps:60,video_codec:2,video_bitrate:0,width:1280,height:720};
for(const patch of [{width:0},{height:0},{width:17},{height:4098},{width:true},{video_bitrate:99999},{video_bitrate:200000001},{video_bitrate:0.1},{output_path:'/tmp/movie.mp4'}])await assert.rejects(bridge.request('mp4_start',{...base,...patch}));
const options={schema:1,fps:30,video_codec:2,bitrate_mode:'custom',video_bitrate:100000,resolution_mode:'custom',width:1280,height:720};
for(const patch of [{fps:true},{fps:90},{width:0},{height:17},{video_bitrate:0},{video_bitrate:200000001},{bitrate_mode:'other'},{path:'/tmp/movie.mp4'}])await assert.rejects(bridge.request('mp4_options_save',{options:{...options,...patch}}));
assert.equal(e.posted.length,0);bridge.dispose();
for(const source of ['출력 크기','권장값 자동 계산','가로 (픽셀)','세로 (픽셀)','비트레이트는 0.1~200 Mbps로 입력해 주세요.','선택한 크기와 화면비로 여백 없이 촬영합니다.']){
 assert.notEqual(api.translateUI(source,'en'),source);assert.notEqual(api.translateUI(source,'ja'),source);
}
""")


def test_hidden_during_first_preference_read_retries_before_accepting_edits():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.elements.get('category-graphics').fire('click');await flush();
const first=e.posted.find(x=>x.action==='mp4_options');assert.ok(first);
await e.visibility(true);assert.equal(e.elements.get('mp4-fields').disabled,true);
await e.visibility(false);await flush();
const retry=e.posted.filter(x=>x.action==='mp4_options').at(-1);assert.notEqual(retry.id,first.id);
const saved={schema:1,fps:30,video_codec:2,bitrate_mode:'custom',video_bitrate:22000000,resolution_mode:'custom',width:1280,height:720};
e.respond(retry,{options:saved});await flush();
assert.equal(e.elements.get('mp4-fps').value,'30');assert.equal(e.elements.get('mp4-bitrate').value,'22');
assert.equal(e.elements.get('mp4-width').value,'1280');assert.equal(e.elements.get('mp4-options-feedback').textContent,'');
e.respond(first,{options:{...saved,fps:60}});await flush();assert.equal(e.elements.get('mp4-fps').value,'30');
app.dispose();
""")


def test_120fps_editor_reload_and_queue_request_preserve_rate():
    run_js(r"""
const e=environment(),app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();e.elements.get('category-graphics').fire('click');await flush();
const saved={schema:1,fps:120,video_codec:2,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'custom',width:1280,height:720};
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:saved});await flush();
assert.equal(e.elements.get('mp4-fps').value,'120');
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'idle',ready:true,source_width:1920,source_height:1080});
e.respond(e.posted.find(x=>x.action==='mp4_queue_status'),{available:true,can_run:true,running:false,phase:'idle',jobs:[]});await flush();
e.elements.get('mp4-enqueue').fire('click');await flush();
const add=e.posted.find(x=>x.action==='mp4_enqueue');assert.deepEqual(add,{id:add.id,action:'mp4_enqueue',fps:120,video_codec:2,video_bitrate:0,width:1280,height:720});
app.dispose();
""")
