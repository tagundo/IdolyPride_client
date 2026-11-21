"""Trusted MP4 controls use one native bridge and never send filesystem paths."""
from __future__ import annotations

from test_ios_unified_web import run_js


def test_mp4_bridge_rejects_paths_extra_fields_and_unsupported_presets():
    run_js(r"""
const e=environment();const bridge=api.createBridge(e.scope,e.timers);
for(const [action,payload] of [
 ['mp4_save',{path:'/private/song.mp4'}],['mp4_save',{export_id:'other-job'}],
 ['mp4_status',{directory:'/private'}],['mp4_cancel',{id:3}],
 ['mp4_pause',{reason:'lifecycle_background'}],['mp4_resume',{export_id:'foreign'}],
 ['mp4_start',{fps:120,video_bitrate:16000000,video_codec:1}],
 ['mp4_start',{fps:60,video_bitrate:16000000,video_codec:1,output_path:'/tmp/a.mp4'}],
 ['mp4_start',{fps:true,video_bitrate:16000000,video_codec:1}]
])await assert.rejects(bridge.request(action,payload));
assert.equal(e.posted.length,0);
const operation=bridge.request('mp4_start',{fps:60,video_bitrate:16000000,video_codec:2});
assert.deepEqual(e.posted[0],{id:1,action:'mp4_start',fps:60,video_bitrate:16000000,video_codec:2});
e.respond(e.posted[0],{phase:'preparing_audio',ready:false});await operation;bridge.dispose();
""")


def test_mp4_pause_preserves_progress_and_requires_explicit_resume_for_user_pause():
    run_js(r"""
const e=environment();const app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'rendering',ready:false,frames:41,total_frames:100});await flush();
assert.equal(e.elements.get('mp4-pause').hidden,false);
e.elements.get('mp4-pause').fire('click');await flush();
const pause=e.posted.find(x=>x.action==='mp4_pause');assert.deepEqual(Object.keys(pause).sort(),['action','id']);
e.respond(pause,{phase:'paused',ready:false,frames:41,total_frames:100,pause_reason:'user_paused',resume_phase:'rendering'});await flush();
assert.equal(e.elements.get('mp4-progress').value,.41);
assert.equal(e.elements.get('mp4-start').disabled,true);
assert.equal(e.elements.get('mp4-cancel').disabled,false);
assert.equal(e.elements.get('mp4-resume').hidden,false);
assert.match(e.elements.get('mp4-feedback').textContent,/계속하기/);
e.elements.get('mp4-resume').fire('click');await flush();
const resume=e.posted.find(x=>x.action==='mp4_resume');assert.deepEqual(Object.keys(resume).sort(),['action','id']);
e.respond(resume,{phase:'rendering',ready:false,frames:41,total_frames:100});await flush();
assert.equal(e.elements.get('mp4-resume').hidden,true);
assert.equal(e.elements.get('mp4-progress').value,.41);
assert.equal(api.translateUI('MP4 일시 정지','en'),'MP4 paused');
assert.equal(api.translateUI('MP4 일시 정지','ja'),'MP4を一時停止中');app.dispose();
""")


def test_mp4_controls_use_actual_geometry_and_only_poll_visible_graphics():
    run_js(r"""
const e=environment();const app=api.createSettingsApp(e.scope,e.document,e.timers);
const initial=e.posted.find(x=>x.action==='status');e.respond(initial,status());await flush();
assert.equal(e.posted.some(x=>x.action==='mp4_status'),false);
e.elements.get('category-graphics').fire('click');await flush();
const probe=e.posted.find(x=>x.action==='mp4_status');assert.ok(probe);
e.respond(probe,{phase:'idle',ready:true,width:3840,height:2160});await flush();
assert.equal(e.elements.get('mp4-start').disabled,false);
assert.match(e.elements.get('mp4-summary').textContent,/3840 × 2160/);
e.elements.get('mp4-fps').value='60';e.elements.get('mp4-bitrate').value='16000000';e.elements.get('mp4-codec').value='1';
e.elements.get('mp4-start').fire('click');await flush();
const start=e.posted.find(x=>x.action==='mp4_start');assert.ok(start);
e.respond(start,{phase:'rendering',ready:false,width:3840,height:2160,frames:2,total_frames:100});await flush();
assert.equal(e.elements.get('mp4-start').disabled,true);
assert.equal(e.elements.get('mp4-cancel').disabled,false);
assert.equal(e.elements.get('mp4-progress').value,.02);
e.elements.get('category-console').fire('click');await flush();
const count=e.posted.filter(x=>x.action==='mp4_status').length;
await e.visibility(true);await e.tick(10000);
assert.equal(e.posted.filter(x=>x.action==='mp4_status').length,count);
app.dispose();
""")


def test_completed_mp4_save_sends_no_file_identity_and_translates():
    run_js(r"""
const e=environment();const app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_status'),{phase:'completed',ready:true,width:1920,height:1080,frames:60,total_frames:60,export_id:'private-owned-id'});await flush();
assert.equal(e.elements.get('mp4-save').hidden,false);
e.elements.get('mp4-save').fire('click');await flush();
const save=e.posted.find(x=>x.action==='mp4_save');assert.deepEqual(Object.keys(save).sort(),['action','id']);
e.respond(save,{presented:true});await flush();
assert.equal(api.translateUI('MV를 MP4로 내보내기','en'),'Export MV as MP4');
assert.equal(api.translateUI('MV를 MP4로 내보내기','ja'),'MVをMP4に書き出す');
assert.equal(api.translateUI('MP4 프레임 수','ko'),'MP4 프레임 수');app.dispose();
""")
