"""Paused source MVs remain exportable without weakening native readiness.

The production game adapter executes with synthetic managed objects. The real
settings JavaScript then exercises that readiness contract while its menu is
visible. Actual UIKit/Unity presentation remains a device verification step.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_game_adapter import SOURCE
from test_ios_unified_web import run_js


def test_paused_source_mv_keeps_native_snapshot_ready_without_advancing_it(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler required")
    preamble, original_main = SOURCE.split("int main(){",1)
    setup = original_main[original_main.index("    setup();"):original_main.index("    GameAdapter a(")]
    source = tmp_path / "paused-source.cpp"
    source.write_text(preamble + "int main(){\n" + setup + r'''
    GameAdapter adapter(selected_api);clock_game=&adapter;
    adapter.observe_presenter(ptr(presenter));adapter.observe_camera_controller(ptr(camera_controller));
    for(int source_mode:{0,3}) {
        mode=source_mode;actor_mode=source_mode;
        const double paused_time=time_value;const float old_bgm=bgm_volume,old_voice=voice_volume;
        Snapshot snapshot{};assert(adapter.snapshot(snapshot)==Result::ok);
        assert(snapshot.previous_update_mode==source_mode&&snapshot.previous_time_seconds==paused_time);
        int32_t width=0,height=0;assert(adapter.source_geometry(width,height)==Result::ok&&width==4096&&height==2458);
        assert(!adapter.manual()&&time_value==paused_time&&mode==source_mode&&actor_mode==source_mode);
        assert(bgm_volume==old_bgm&&voice_volume==old_voice&&evals==0&&graph_steps==0&&actor_steps==0);
    }
    adapter.reset_observations();assert(handles.empty());
}
''')
    output = tmp_path / "paused-source"
    root = Path(__file__).resolve().parents[1]
    compiled = subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",
                               "-I",str(root / "client-presentation/native"),str(source),"-o",str(output)],
                              check=False,capture_output=True,text=True,timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result = subprocess.run([str(output)],check=False,capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_visible_ios_menu_accepts_ready_paused_mv_and_preserves_real_not_ready_gate():
    run_js(r"""
const e=environment();const app=api.createSettingsApp(e.scope,e.document,e.timers);
e.respond(e.posted.find(x=>x.action==='status'),status());await flush();
e.elements.get('category-graphics').fire('click');await flush();
e.respond(e.posted.find(x=>x.action==='mp4_options'),{options:{schema:1,fps:60,video_codec:1,bitrate_mode:'recommended',video_bitrate:16000000,resolution_mode:'current',width:1920,height:1080}});await flush();
const initial=e.posted.find(x=>x.action==='mp4_status');
const queue=e.posted.find(x=>x.action==='mp4_queue_status');
assert.ok(initial&&queue);
e.respond(initial,{phase:'idle',ready:false});
e.respond(queue,{available:true,can_run:true,running:false,paused:false,phase:'idle',command_pending:false,jobs:[]});await flush();
assert.equal(e.elements.get('mp4-start').disabled,true);
assert.equal(e.elements.get('mp4-enqueue').disabled,true);
// A fresh, valid snapshot of the paused source MV enables both actions while
// the same foreground settings page stays visible; no focus flag is required.
e.elements.get('panel-mp4').fire('toggle');await flush();
const fresh=e.posted.filter(x=>x.action==='mp4_status').at(-1);assert.notEqual(fresh,initial);
e.respond(fresh,{phase:'idle',ready:true,width:4096,height:2458});
const refreshQueue=e.posted.filter(x=>x.action==='mp4_queue_status').at(-1);
if(refreshQueue!==queue)e.respond(refreshQueue,{available:true,can_run:true,running:false,paused:false,phase:'idle',command_pending:false,jobs:[]});await flush();
assert.equal(e.elements.get('mp4-start').disabled,false);
assert.equal(e.elements.get('mp4-enqueue').disabled,false);
e.elements.get('mp4-fps').value='60';e.elements.get('mp4-codec').value='2';e.elements.get('mp4-bitrate').value='16000000';
e.elements.get('mp4-start').fire('click');await flush();
const start=e.posted.find(x=>x.action==='mp4_start');assert.ok(start);
assert.deepEqual(start,{id:start.id,action:'mp4_start',fps:60,video_bitrate:0,video_codec:2,width:0,height:0});
e.respond(start,{phase:'preparing_audio',ready:false,frames:0,total_frames:100});await flush();
assert.equal(e.elements.get('mp4-start').disabled,true);
assert.equal(e.elements.get('mp4-cancel').disabled,false);
assert.equal(e.elements.get('mp4-feedback').textContent,'');
app.dispose();
""")
