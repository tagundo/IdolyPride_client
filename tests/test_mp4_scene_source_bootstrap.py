"""Actual lifecycle adapters and ordering; native/image services modeled."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
def function(text,signature):
    first=text.index(signature);start=text.index('{',first);depth=1;end=start+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[first:end]
def marker(text,name):
    return text.split('// BEGIN_'+name,1)[1].split('// END_'+name,1)[0]
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    fixture=(ROOT/'tests/fixtures/mp4_scene_source_bootstrap.cpp.inc').read_text()
    fixture=fixture.replace('// FORMAL_SCOPE',marker(bridge,'MP4_SOURCE_BOOTSTRAP_SCOPE')).replace('// CONCRETE_HOST',marker(bridge,'MP4_SCENE_SOURCE_BOOTSTRAP_HOST'))
    fixture=fixture.replace('// OUTER_QUIESCE',function(bridge,'Mp4SceneResult mp4_scene_quiesce(void*){')).replace('// OUTER_RELEASE',function(bridge,'Mp4SceneResult mp4_scene_release(void*,bool owned){'))
    folder=tmp_path_factory.mktemp('scene-source-bootstrap');source=folder/'test.cpp';out=folder/'test';source.write_text(fixture)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(source),'-o',str(out)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stderr
    return out
@pytest.mark.parametrize('mode','pf_capture_wait pf_missing_receipt pf_stale_receipt pf_release_wait render_hold_wait render_checkpoint_wait render_retire_wait render_retire_reentry render_retire_source_changed property_restore_reentry video_handoff_reentry playback_handoff_reentry srp_capture_refuses srp_current_lost srp_restore_wait srp_release_wait normal idempotent reuse foreign_release missing_handoff handoff_wait handoff_reentry release_reentry outer_abort transferred_release_wait missing_producer before_wait before_throw missing_commit commit_refuses cohort_refuses source_loss commit_source_loss cleanup_wait'.split())
def test_actual_scene_source_bootstrap(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_actual_first_render_resets_pf_before_actor_prewarm(tmp_path):
    compiler=shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    text=(ROOT/'tests/fixtures/mp4_scene_prepare_order.cpp.inc').read_text()
    text=text.replace('// ACTUAL_SCENE_RUN',function(bridge,'Mp4SceneResult mp4_scene_run(Mp4SceneOperation operation){'))
    source=tmp_path/'prepare.cpp';binary=tmp_path/'prepare';source.write_text(text)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stderr
    for case in ['normal','capture_missing','gpu_wait','pf_wait','pf_reentry','property_active','video_active','playback_active']:
        result=subprocess.run([str(binary),case],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,(case,result.stdout,result.stderr)
