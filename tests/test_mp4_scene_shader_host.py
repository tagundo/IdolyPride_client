"""Shipping Scene producer and serialized-origin proofs; Unity/native leaves modeled."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures'
SCENE_CASES='normal missing_producer_receipt invalid_producer_receipt memory wrong_size unknown_bundle input_changed duplicate_bundle custom_api bad_parameters prefix wrong_path wrong_scene duplicate_component wrong_shader_type root_failure shader_native_changed shader_id_changed foreign_after_load offthread unloaded bundle_unload_false bundle_unload_true hook original_throw event_before_return stale_ticket reentry async_memory async_memory_changed async_request_changed file duplicate_pending hook_input_root_failure'.split()
def block(text,name):
    return text.split('// BEGIN_'+name,1)[1].split('// END_'+name,1)[0]
def fixture(name):return (FIXTURES/name).read_text()
def compile_model(folder,source):
    cpp=folder/'test.cpp';binary=folder/'test';cpp.write_text(source)
    cmd=[shutil.which('c++') or 'clang++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-address','-Wno-misleading-indentation','-g','-O1','-fsanitize=address,undefined','-fno-pie','-no-pie','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)]
    run=subprocess.run(cmd,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    return binary
@pytest.fixture(scope='module')
def scene(tmp_path_factory):
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    source=fixture('mp4_scene_shader_prefix.cpp.inc')
    source+='\n'.join(block(text,n)for n in ['MP4_SHADER_OBSERVER_ROOTS','MP4_SCENE_SHADER_HOST','MP4_SCENE_SHADER_OBSERVER','MP4_SCENE_SHADER_HOOKS'])
    source+=fixture('mp4_scene_shader_driver.cpp.inc')
    return compile_model(tmp_path_factory.mktemp('scene-shader-host'),source)
@pytest.mark.parametrize('case',SCENE_CASES)
def test_actual_source_scene_producer(scene,case):
    run=subprocess.run([str(scene),case],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
@pytest.fixture(scope='module',params=['core','native','scene'])
def origin(request,tmp_path_factory):
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    names=['MP4_PERSISTENT_ORIGIN_CORE','MP4_PERSISTENT_ORIGIN_PINS']
    if request.param in ['core','native']:
        source=fixture('mp4_origin_prefix.cpp.inc')+'\n'.join(block(text,n)for n in names+['MP4_PERSISTENT_ORIGIN_NATIVE'])
        source+=fixture('mp4_origin_'+request.param+'_driver.cpp.inc')
    else:
        source=fixture('mp4_scene_shader_prefix.cpp.inc')+'\n'.join(block(text,n)for n in ['MP4_SHADER_OBSERVER_ROOTS','MP4_SCENE_SHADER_HOST','MP4_SCENE_SHADER_OBSERVER','MP4_SCENE_SHADER_HOOKS'])
        source+=fixture('mp4_scene_shader_driver.cpp.inc').split('int main(',1)[0]
        source+='\n'.join(block(text,n)for n in names)+fixture('mp4_scene_origin_native_model.cpp.inc')
        source+=block(text,'MP4_SCENE_SHADER_ORIGIN_RECEIPT')+fixture('mp4_scene_origin_driver.cpp.inc')
    return request.param,compile_model(tmp_path_factory.mktemp('persistent-origin-'+request.param),source)
def test_actual_native_and_scene_origin(origin):
    kind,binary=origin
    for args in ([[]]if kind!='scene' else [[str(i)]for i in range(13)]):
        run=subprocess.run([str(binary),*args],capture_output=True,text=True)
        assert run.returncode==0,run.stderr
        if kind=='core':assert 'PASS 34' in run.stdout
        if kind=='native':assert 'PASS 14' in run.stdout
