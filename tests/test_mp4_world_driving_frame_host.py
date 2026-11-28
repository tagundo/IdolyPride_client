"""Shipping World/Driver frame latches with real AnimationGate and model Driver.

The independent driving suite checks the real Driver protocol. This suite
checks its World wiring and does not claim a Unity/GPU/runtime export.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include "mp4_engine_clock.hpp"
#include <atomic>
#include <cassert>
#include <string>
namespace mp4child{using Result=idoly_mp4_world::Result;}
enum class Mp4SceneResult:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
using R=mp4child::Result;using S=Mp4SceneResult;
std::string mode;bool held=true,physical=true,source=true,owner=true;
unsigned native_calls[8]{},begins=0,marks=0,finishes=0,discard_prepared=0,discard_issued=0,releases=0;
struct World{uint64_t epoch=17,driving_tick=0;bool driving_prepared=false,driving_granted=false,driving_marked=false;const char*error="none";}mp4_world_host;
std::atomic<bool>mp4_child_driving_active{true},mp4_child_driving_rejected{false};
struct Driver{bool captured_value=true,failed_value=false,prepared=false,issued=false;unsigned depth=0;
 bool captured()const{return captured_value;}bool failed()const{return failed_value;}}mp4_child_driving_scope;
idoly_mp4_world::AnimationGate mp4_animation_gate;
bool game_call(){return owner;}
bool mp4_actor_clock_held(void*){return held;}
bool mp4_director_boundary_closed(void*){return physical;}
bool mp4_world_driving_permission();
bool mp4_world_source_current(void*){return source&&mp4_world_driving_permission();}
S mp4_world_result(R r){return static_cast<S>(static_cast<int>(r));}
R mp4_child_driving_begin_frame(uint64_t t){++begins;assert(!mp4_child_driving_scope.prepared&&t==0);
 if(mode=="prepare_wait"&&begins==1)return R::waiting;
 mp4_child_driving_scope.prepared=true;return R::ok;
}
R mp4_child_driving_mark_issued(uint64_t t){++marks;assert(mp4_child_driving_scope.prepared&&mp4_animation_gate.issued_frame(17,t));
 if(mode=="mark_fail"||mode=="unacknowledged_complete")return R::failed;
 if(mode=="mark_wait"&&marks==1)return R::waiting;
 assert(!mp4_child_driving_scope.issued);mp4_child_driving_scope.issued=true;return R::ok;
}
R mp4_child_driving_finish_frame(uint64_t t){++finishes;assert(mp4_child_driving_scope.issued&&mp4_animation_gate.completed_frame(17,t));
 if(mode=="finish_wait"&&finishes==1)return R::waiting;
 mp4_child_driving_scope.prepared=mp4_child_driving_scope.issued=false;return R::ok;
}
R mp4_child_driving_discard_prepared(uint64_t){++discard_prepared;assert(mp4_child_driving_scope.prepared&&!mp4_child_driving_scope.issued);mp4_child_driving_scope.prepared=false;return R::ok;}
R mp4_child_driving_discard_issued_unconsumed(uint64_t t){++discard_issued;assert(mp4_child_driving_scope.issued&&mp4_animation_gate.revoked_unconsumed_frame(17,t));mp4_child_driving_scope.prepared=mp4_child_driving_scope.issued=false;return R::ok;}
R mp4_child_driving_release(){++releases;if(mp4_child_driving_scope.depth)return R::waiting;mp4_child_driving_active.store(false);mp4_child_driving_scope.prepared=mp4_child_driving_scope.issued=false;return R::ok;}
void p0(){++native_calls[0];}void p1(){++native_calls[1];}void p2(){++native_calls[2];}void p3(){++native_calls[3];}
void p4(){++native_calls[4];}void p5(){++native_calls[5];}void p6(){++native_calls[6];}void p7(){++native_calls[7];}
bool thread(){return owner;}
'''
DRIVER=r'''
int main(int argc,char**argv){assert(argc==2);mode=argv[1];auto&h=mp4_world_host;
 idoly_mp4_world::AnimationApi api{{p0,p1,p2,p3,p4,p5,p6,p7},thread};assert(mp4_animation_gate.install(api)&&mp4_animation_gate.acquire(17));
 if(mode=="grant_without_prepare"){assert(mp4_world_driving_grant(0)==S::stale&&!mp4_animation_gate.issued_frame(17,0)&&!marks);return 0;}
 if(mode=="uncaptured"){mp4_child_driving_active.store(false);assert(mp4_world_driving_prepare(0)==S::unsupported&&!begins);return 0;}
 if(mode=="scope_failed"){mp4_child_driving_scope.failed_value=true;assert(!mp4_world_driving_permission()&&mp4_world_driving_prepare(0)==S::unsupported&&!begins);return 0;}
 if(mode=="prepare_wait"){assert(mp4_world_driving_prepare(0)==S::waiting&&!h.driving_prepared&&!mp4_animation_gate.issued_frame(17,0));}
 assert(mp4_world_driving_prepare(0)==S::ok&&h.driving_prepared&&!h.driving_granted);
 const unsigned initial_begins=begins;assert(mp4_world_driving_prepare(0)==S::ok&&begins==initial_begins);
 if(mode=="prepare_wrong_tick"){assert(mp4_world_driving_prepare(1)==S::invalid&&begins==1);return 0;}
 if(mode=="neutral"){physical=false;assert(mp4_world_driving_quiesce()==S::ok&&h.driving_prepared&&!h.driving_granted&&!finishes&&!discard_prepared&&!discard_issued);return 0;}
 if(mode=="wrong_tick"){assert(mp4_world_driving_grant(1)==S::stale&&!h.driving_granted&&!marks);return 0;}
 if(mode=="rejected"){mp4_child_driving_rejected.store(true);assert(mp4_world_driving_grant(0)==S::stale&&!h.driving_granted&&!marks);return 0;}
 if(mode=="source_lost"){source=false;assert(mp4_world_driving_grant(0)==S::stale&&!h.driving_granted&&!marks);return 0;}
 if(mode=="mark_wait"){assert(mp4_world_driving_grant(0)==S::waiting&&h.driving_granted&&!h.driving_marked&&mp4_animation_gate.issued_frame(17,0));}
 const auto granted=mp4_world_driving_grant(0);
 if(mode=="mark_fail"||mode=="unacknowledged_complete"){
  assert(granted==S::failed&&h.driving_granted&&!h.driving_marked&&mp4_animation_gate.issued_frame(17,0));
  if(mode=="mark_fail"){mp4_animation_gate.revoke_grants(17);assert(mp4_world_driving_quiesce()==S::ok&&discard_prepared==1&&!discard_issued&&!finishes&&!h.driving_prepared);return 0;}
  for(unsigned i=0;i<8;++i){assert(mp4_animation_gate.invoke(i));}
  assert(mp4_world_driving_quiesce()==S::failed&&!finishes&&h.driving_granted);return 0;
 }
 assert(granted==S::ok&&h.driving_granted&&h.driving_marked);
 const unsigned actual_marks=marks;assert(mp4_world_driving_grant(0)==S::ok&&marks==actual_marks);
 if(mode=="release_wait"){
  mp4_child_driving_scope.depth=1;assert(mp4_world_driving_release()==S::waiting&&h.driving_prepared&&h.driving_granted);
  mp4_child_driving_scope.depth=0;assert(mp4_world_driving_release()==S::ok&&!h.driving_prepared&&!h.driving_granted&&releases==2);return 0;
 }
 if(mode=="zero_revoked"){
  mp4_animation_gate.revoke_grants(17);physical=false;assert(mp4_world_driving_quiesce()==S::waiting&&h.driving_granted&&!discard_issued);
  physical=true;assert(mp4_world_driving_quiesce()==S::ok&&discard_issued==1&&!finishes&&!h.driving_granted);for(auto n:native_calls)assert(!n);return 0;
 }
 if(mode=="partial"||mode=="partial_pair"){
  const unsigned count=mode=="partial_pair"?3:2;for(unsigned i=0;i<count;++i){assert(mp4_animation_gate.invoke(i));}
  mp4_animation_gate.revoke_grants(17);assert(mp4_world_driving_quiesce()==S::waiting&&h.driving_granted&&!finishes&&!discard_issued);
  if(mode=="partial_pair"){assert(mp4_animation_gate.invoke(4));assert(mp4_world_driving_quiesce()==S::waiting&&h.driving_granted&&!finishes);}
  assert(!mp4_animation_gate.completed_frame(17,0)&&!mp4_animation_gate.revoked_unconsumed_frame(17,0));return 0;
 }
 for(unsigned i=0;i<8;++i){assert(mp4_animation_gate.invoke(i));}
 if(mode=="regrant_after_complete"){assert(mp4_world_driving_grant(0)==S::stale&&h.driving_granted&&marks==actual_marks);}
 if(mode=="physical_wait"){physical=false;assert(mp4_world_driving_quiesce()==S::waiting&&!finishes&&h.driving_granted);physical=true;}
 if(mode=="clock_wait"){held=false;assert(mp4_world_driving_quiesce()==S::waiting&&!finishes&&h.driving_granted);held=true;}
 if(mode=="finish_wait"){assert(mp4_world_driving_quiesce()==S::waiting&&finishes==1&&h.driving_granted);}
 assert(mp4_world_driving_quiesce()==S::ok&&!h.driving_prepared&&!h.driving_granted&&!h.driving_marked);
 assert(finishes==(mode=="finish_wait"?2u:1u)&&!discard_prepared&&!discard_issued);
 for(auto n:native_calls)assert(n==1);
 assert(mp4_world_driving_quiesce()==S::ok&&begins==initial_begins&&marks==actual_marks);return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text.split('// BEGIN_MP4_WORLD_DRIVING_FRAME_HOST',1)[1].split('// END_MP4_WORLD_DRIVING_FRAME_HOST',1)[0]
    folder=tmp_path_factory.mktemp('world-driving-frame');cpp=folder/'test.cpp';out=folder/'test';cpp.write_text(PREFIX+actual+DRIVER)
    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(out)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    return out
@pytest.mark.parametrize('mode',['sequence','grant_without_prepare','uncaptured','scope_failed','prepare_wait','prepare_wrong_tick','neutral','wrong_tick','rejected','source_lost','mark_wait','mark_fail','unacknowledged_complete','release_wait','zero_revoked','partial','partial_pair','physical_wait','clock_wait','finish_wait','regrant_after_complete'])
def test_world_joins_only_real_frame_issue_and_completion(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
