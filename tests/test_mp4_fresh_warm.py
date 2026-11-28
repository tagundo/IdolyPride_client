"""The fresh export snapshots only a reloaded MV the game has visibly run.

Every device failure from 2026.11.23.5 to .7 was a check reading state the
game creates during its first frames (VideoImage binding, MaterialInfo),
because acquire snapshotted in the same call that released the deferred Play.
Elichika instead waits until it has observed the MV render. mp4_fresh_warm
runs zero-delta frames at t=0 until the delayed actor reset returned, a few
frames passed, the camera drew at the settled target size and its aspect
matches. These checks run the shipping function with modeled game state; they
do not execute Unity.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"


def _function(source, signature):
    begin = source.index(signature)
    at = source.index("{", begin) + 1
    depth = 1
    while depth:
        depth += (source[at] == "{") - (source[at] == "}")
        at += 1
    return source[begin:at]


def _line(source, prefix):
    begin = source.index(prefix)
    return source[begin:source.index("\n", begin)]


HARNESS = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
enum class Mp4FreshResult{ok,waiting,stale,unsupported,failed,invalid};
struct Method;
struct Witness{void*controller=nullptr;};
struct{Witness source{};bool warming=false,warmed=false,warm_ready=false;uint64_t warm_ready_at=0,warm_ready_ms=0,warm_size_at=0;
 uint32_t warm_draws=0,warm_draws_at_size=0;int32_t warm_width=0,warm_height=0;const char*error="none";}mp4_fresh_host;
struct{bool failed=false,reset_required=false,reset_returned=false;}mp4_fresh_play_gate;
struct Event{std::string stage,code;uint64_t frame,tick;};
std::vector<Event> events;
namespace idoly_mp4_runtime{
uint64_t native_entries=0,now_ms=1000;
uint64_t milliseconds(){return now_ms;}
void diagnostic_event(const char*stage,const char*code,uint64_t frame=0,uint64_t tick=0,bool=false){events.push_back({stage,code,frame,tick});}
}
Mp4FreshResult mp4_fresh_fail(Mp4FreshResult r,const char*error){mp4_fresh_host.error=error;return r;}
int controller=0,camera=0;int32_t target_w=1280,target_h=720;float camera_aspect=1280.f/720.f;bool typed=true,lens_api=true;
bool mp4_actual_source_geometry(void*c,int32_t*w,int32_t*h){if(!typed||c!=&controller)return false;*w=target_w;*h=target_h;return true;}
bool mp4_projection_api_available(){return lens_api;}
void*rt_camera(void*c,Method*){return c==&controller?&camera:nullptr;}
bool mp4_alive(void*p){return p==&camera;}
float aspect_get_original(void*,Method*){return camera_aspect;}
'''

DRIVER = r'''
using R=Mp4FreshResult;
auto&h=mp4_fresh_host;auto&g=mp4_fresh_play_gate;
R step(unsigned draws=0,uint64_t ms=16){
 // One native boundary: the engine frame (and its draws) runs, then acquire.
 ++idoly_mp4_runtime::native_entries;idoly_mp4_runtime::now_ms+=ms;
 if(h.warming)h.warm_draws+=draws;
 return mp4_fresh_warm();
}
bool traced(const char*code){for(auto&e:events)if(e.stage=="fresh_warm"&&e.code==code)return true;return false;}
void reset_state(){h={};h.source.controller=&controller;g={};events.clear();target_w=1280;target_h=720;camera_aspect=1280.f/720.f;typed=true;lens_api=true;}
int main(int argc,char**argv){
 assert(argc==2);const std::string scenario=argv[1];reset_state();
 if(scenario=="observed"){
  g.reset_required=true;
  // Draws before the delayed reset returned never count.
  for(int i=0;i<8;++i){assert(step(1)==R::waiting&&!std::strcmp(h.error,"fresh_warm_reset_wait"));}
  assert(h.warming&&traced("started"));
  g.reset_returned=true;
  // The reset boundary starts the count; ten engine frames must follow.
  for(int i=0;i<10;++i)assert(step(1)==R::waiting&&!std::strcmp(h.error,"fresh_warm_frame_wait"));
  // The target was first seen at the reset; ten frames later it is settled.
  assert(step(1)==R::ok&&h.warmed&&!h.warming);
  assert(traced("observed")&&!traced("observed_without_draw"));
  assert(events.back().frame>=1&&events.back().tick==10);
 }else if(scenario=="no_reset_required"){
  for(int i=0;i<10;++i)assert(step(1)==R::waiting);
  assert(step(1)==R::ok&&traced("observed"));
 }else if(scenario=="reset_never_returns"){
  // Strict: a late reset would replace actors after the snapshot. The
  // acquire stage budget (15 s) ends it with this code.
  g.reset_required=true;
  for(int i=0;i<1000;++i)assert(step(1,100)==R::waiting&&!std::strcmp(h.error,"fresh_warm_reset_wait"));
 }else if(scenario=="draw_wait_then_draw"){
  for(int i=0;i<20;++i)assert(step(0)==R::waiting);
  assert(!std::strcmp(h.error,"fresh_warm_draw_wait"));
  assert(step(1)==R::ok&&traced("observed"));
 }else if(scenario=="resize_restarts_settle"){
  for(int i=0;i<5;++i)assert(step(1)==R::waiting);
  // The reload turns the window: the old-size draws no longer count.
  target_w=720;target_h=1280;camera_aspect=1280.f/720.f;
  assert(step(0)==R::waiting);
  for(int i=0;i<6;++i)assert(step(0)==R::waiting);
  assert(!std::strcmp(h.error,"fresh_warm_draw_wait"));
  assert(step(1)==R::waiting&&!std::strcmp(h.error,"fresh_warm_target_wait")); // aspect still old
  camera_aspect=720.f/1280.f;  // the next draw at the new size refreshes it
  for(int i=0;i<2;++i)assert(step(1)==R::waiting); // settle: 10 frames since the resize
  R r=R::waiting;for(int i=0;i<3&&r!=R::ok;++i)r=step(1);
  assert(r==R::ok&&traced("observed")&&traced("target_size"));
 }else if(scenario=="aspect_never_settles"){
  camera_aspect=1.f;
  for(int i=0;i<200;++i)assert(step(1,16)==R::waiting);
  assert(!std::strcmp(h.error,"fresh_warm_target_wait"));
  R r=R::waiting;for(int i=0;i<200&&r!=R::ok;++i)r=step(1,16);
  assert(r==R::ok&&traced("observed_target_unsettled"));
 }else if(scenario=="never_draws"){
  R r=R::waiting;int n=0;for(;n<1000&&r!=R::ok;++n)r=step(0,16);
  assert(r==R::ok&&traced("observed_without_draw")&&n*16>=4000);
 }else if(scenario=="untyped_controller"){
  typed=false;for(int i=0;i<10;++i)assert(step(1)==R::waiting);
  assert(step(1)==R::ok&&traced("observed")&&!traced("target_size"));
 }else if(scenario=="lens_api_unavailable"){
  // The aspect cannot be read: never wait 4 s for it.
  lens_api=false;camera_aspect=1.f;for(int i=0;i<10;++i)assert(step(1)==R::waiting);
  assert(step(1)==R::ok&&traced("observed")&&!traced("observed_target_unsettled"));
 }else if(scenario=="staging_failed"){
  g.failed=true;assert(step(1)==R::failed&&!std::strcmp(h.error,"fresh_play_staging_failed"));
 }else return 2;
 return 0;
}
'''


@pytest.fixture(scope="module")
def warm_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    bridge = BRIDGE.read_text()
    source = (HARNESS + _line(bridge, "constexpr uint64_t mp4_fresh_warm_frames=") + "\n"
              + _function(bridge, "Mp4FreshResult mp4_fresh_warm(){") + "\n" + DRIVER)
    directory = tmp_path_factory.mktemp("fresh-warm")
    (directory / "warm.cpp").write_text(source)
    built = subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", str(directory / "warm.cpp"),
                            "-o", str(directory / "warm")], capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stderr
    return directory / "warm"


@pytest.mark.parametrize("scenario", [
    "observed", "no_reset_required", "reset_never_returns", "draw_wait_then_draw", "resize_restarts_settle",
    "aspect_never_settles", "never_draws", "untyped_controller", "lens_api_unavailable", "staging_failed"])
def test_fresh_warm_gate(warm_binary, scenario):
    run = subprocess.run([str(warm_binary), scenario], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr


def test_acquire_warms_before_any_snapshot_and_draws_ordinarily():
    bridge = BRIDGE.read_text()
    acquire = _function(bridge, "Mp4FreshResult mp4_fresh_acquire(void*,const Mp4SceneWitness&source,uint64_t job){")
    released = acquire.index("mp4_fresh_release_deferred_play()")
    warmed = acquire.index("mp4_fresh_warm()")
    # Released Play, then warm-up, then the first roster / inventory snapshot.
    assert released < warmed < acquire.index("mp4_fresh_control_roster_build(")
    assert warmed < acquire.index("mp4_fresh_video_inventory(") < acquire.index("mp4_actor_presentation_collect(")
    render = _function(bridge, "bool mp4_fresh_render_call(Mp4RenderCamera original,")
    # The warm draw precedes the scene-currency check that suppresses it.
    assert render.index("if(h.warming)") < render.index("if(!mp4_fresh_current(nullptr))return true;")
    brain = _function(bridge, "bool mp4_fresh_permit_brain(void*brain){")
    assert brain.index("if(h.warming)return true;") < brain.index("mp4_fresh_current(nullptr)")
    # Cleanup never keeps drawing as warm-up; a new job restarts the warm-up.
    assert "h.warming=false;" in _function(bridge, "Mp4FreshResult mp4_fresh_prepare_finish(void*){")
    assert "if(!h.active){h.warming=h.warmed=h.warm_ready=false;" in acquire
