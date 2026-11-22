"""Actual participant/image restoration calls, with engine and image leaves modeled.

The test checks real ordering and failure propagation; it claims no Unity/GPU
execution or export validation.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    bodies = '\n'.join(function(source, signature) for signature in (
        'Mp4SceneResult mp4_world_target_images_restore(){',
        'Mp4SceneResult mp4_stage_activation_targets_restore() {',
        'Mp4SceneResult mp4_world_restore(void*){',
        'Mp4SceneResult mp4_stage_restore(void*){',
    ))
    model = r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
enum class Mp4SceneResult{ok,waiting,unsupported,stale,invalid,failed};
namespace mp4world{using Result=Mp4SceneResult;}
namespace mp4stage{using Result=Mp4SceneResult;}
std::vector<int> events;
bool main_thread=true,inventory=true,controls=true,clock_closed=true;
Mp4SceneResult world_result=Mp4SceneResult::ok,image_result=Mp4SceneResult::ok;
Mp4SceneResult activation_result=Mp4SceneResult::ok,equipment_result=Mp4SceneResult::ok;
Mp4SceneResult particles_result=Mp4SceneResult::ok,psy_result=Mp4SceneResult::ok;
bool game_call(){return main_thread;}
struct ImageScope{bool captured_=false;uint64_t serial=9;
 bool captured()const{return captured_;}uint64_t capture_receipt_raw()const{return serial;}};
struct{ImageScope scope;}mp4_target_image_host;
struct{const ImageScope*scope=nullptr;bool entered=false,completed=false;uint64_t capture=0;}mp4_target_image_capture_receipt;
Mp4SceneResult mp4_target_image_restore(){events.push_back(2);return image_result;}
struct{bool captured_=false;bool captured()const{return captured_;}
 Mp4SceneResult restore(){events.push_back(3);return activation_result;}}mp4_activation_targets;
bool mp4_activation_targets_capture_completed=false;
struct{struct{Mp4SceneResult restore(){events.push_back(1);return world_result;}
 bool restorable(){return true;}}scope;bool restoration_verified=true,animation_owned=true;uint64_t epoch=17;}mp4_world_host;
struct{bool closed(uint64_t epoch){assert(epoch==17);return clock_closed;}}mp4_animation_gate;
Mp4SceneResult mp4_world_result(Mp4SceneResult result){return result;}
Mp4SceneResult mp4_stage_result(Mp4SceneResult result){return result;}
struct{bool restored=true;}mp4_stage_host;
bool mp4_stage_refresh_inventory(){return inventory;}
bool mp4_stage_refresh_controls(){return controls;}
struct{Mp4SceneResult restore(){events.push_back(4);return equipment_result;}}mp4_stage_equipment;
struct{Mp4SceneResult restore(){events.push_back(5);return particles_result;}}mp4_stage_particles;
struct{Mp4SceneResult restore(){events.push_back(6);return psy_result;}}mp4_stage_psyllium;
'''
    driver = r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 const bool world=mode.rfind("world_",0)==0;
 if(world){auto&scope=mp4_target_image_host.scope;auto&r=mp4_target_image_capture_receipt;
  if(mode!="world_no_image"){scope.captured_=true;r.scope=&scope;r.entered=r.completed=true;r.capture=scope.serial;}
  if(mode=="world_bare")r={};
  if(mode=="world_partial")r.completed=false;
  if(mode=="world_serial")++r.capture;
  if(mode=="world_base_wait")world_result=Mp4SceneResult::waiting;
  if(mode=="world_image_wait")image_result=Mp4SceneResult::waiting;
  if(mode=="world_clock_open")clock_closed=false;
  if(mode=="world_foreign")main_thread=false;
  auto result=mp4_world_restore(nullptr);
  if(mode=="world_base_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>{1});}
  else if(mode=="world_bare"){assert(result==Mp4SceneResult::invalid&&events==std::vector<int>{1});}
  else if(mode=="world_partial"||mode=="world_serial"){assert(result==Mp4SceneResult::stale&&events==std::vector<int>{1});}
  else if(mode=="world_foreign"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>{1});}
  else if(mode=="world_image_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>({1,2}));}
  else {assert(result==Mp4SceneResult::ok);assert(events==(mode=="world_no_image"?std::vector<int>{1}:std::vector<int>{1,2}));}
  assert(mp4_world_host.restoration_verified==(result==Mp4SceneResult::ok&&clock_closed));
 }else{
  mp4_activation_targets.captured_=mode!="stage_no_activation";
  mp4_activation_targets_capture_completed=true;
  if(mode=="stage_partial")mp4_activation_targets_capture_completed=false;
  if(mode=="stage_activation_wait")activation_result=Mp4SceneResult::waiting;
  if(mode=="stage_equipment_wait")equipment_result=Mp4SceneResult::waiting;
  if(mode=="stage_particles_wait")particles_result=Mp4SceneResult::waiting;
  if(mode=="stage_psy_wait")psy_result=Mp4SceneResult::waiting;
  if(mode=="stage_inventory")inventory=false;
  if(mode=="stage_controls")controls=false;
  if(mode=="stage_foreign")main_thread=false;
  auto result=mp4_stage_restore(nullptr);
  if(mode=="stage_inventory"||mode=="stage_controls"){assert(result==Mp4SceneResult::stale&&events.empty());}
  else if(mode=="stage_partial"){assert(result==Mp4SceneResult::stale&&events.empty());}
  else if(mode=="stage_foreign"){assert(result==Mp4SceneResult::waiting&&events.empty());}
  else if(mode=="stage_activation_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>{3});}
  else if(mode=="stage_equipment_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>({3,4}));}
  else if(mode=="stage_particles_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>({3,4,5}));}
  else if(mode=="stage_psy_wait"){assert(result==Mp4SceneResult::waiting&&events==std::vector<int>({3,4,5,6}));}
  else{assert(result==Mp4SceneResult::ok);assert(events==(mode=="stage_no_activation"?std::vector<int>{4,5,6}:std::vector<int>{3,4,5,6}));}
  assert(mp4_stage_host.restored==(result==Mp4SceneResult::ok));
 }
}
'''
    folder = tmp_path_factory.mktemp('participant-images')
    cpp, out = folder / 'test.cpp', folder / 'test'
    cpp.write_text(model + bodies + driver)
    built = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-fno-pie', '-no-pie', str(cpp), '-o', str(out)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return out


@pytest.mark.parametrize('mode', '''world_normal world_no_image world_bare world_partial world_serial
world_base_wait world_image_wait world_clock_open world_foreign stage_normal stage_no_activation
stage_partial stage_activation_wait stage_equipment_wait stage_particles_wait stage_psy_wait
stage_inventory stage_controls stage_foreign'''.split())
def test_actual_participant_image_restoration(binary, mode):
    result = subprocess.run([str(binary), mode], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
