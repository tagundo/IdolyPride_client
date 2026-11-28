"""Shipping native-output adapters: exact phase dispatch, no payload grants.

Concrete payload validators are modeled here and have independent shipping
host suites. These cases do not claim device/Unity/MP4 execution.
"""
from pathlib import Path
import re
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdint>
#include <string>
#include <stdexcept>
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0;};}
struct Mp4SceneWitness{uint64_t generation=7;void*director=reinterpret_cast<void*>(9);};
bool same_identity(const mp4world::DirectorGraphIdentity&a,const mp4world::DirectorGraphIdentity&b){return a.native==b.native&&a.slot==b.slot&&a.version==b.version;}
Mp4SceneWitness selected{};mp4world::DirectorGraphIdentity expected{16,32,2};
bool owner=true,available=true,source_current=true,admission_receipt=true,normal_closed=true,context_current=true;
bool mp4_source_verified=true,mp4_actor_source_verified=true,audio_proof=true,script_proof=true,animation_proof=true;
bool throw_selection=false,throw_payload=false;
unsigned audio_calls=0,script_calls=0;bool audio_admission=false;
bool game_call(){return owner;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.director==b.director;}
bool mp4_stage_admission_source(const Mp4SceneWitness&w){return admission_receipt&&mp4_scene_same_source(w,selected);}
bool mp4_scene_source_current(){return source_current;}
bool mp4_scene_normal_animation_closed(){return normal_closed;}
struct Host{bool active=false,invalidated=false,releasing=false,logical_checkpoint=false;unsigned admitted=7,configured=31,captured=31,prepared=31,restored=0,finalized=0,all=31;Mp4SceneWitness admitted_source=selected;}mp4_scene_host;
struct SourceHost{bool verified=true;Mp4SceneWitness source=selected;}mp4_camera_host,mp4_world_host,mp4_stage_host;
struct{bool active=false;}mp4_rebuild_ledger;
namespace idoly_mp4_playback{enum class Phase{idle,acquiring,held,starting,playing,restoring};}
namespace idoly_mp4_runtime{
struct Clock{bool active_value=true,held_value=true;bool active()const{return active_value;}bool held()const{return held_value;}}clock;
const Clock&native_clock_scope(){return clock;}
struct Game{idoly_mp4_playback::Phase phase=idoly_mp4_playback::Phase::held;
 bool selected_scene_witness(Mp4SceneWitness&out){if(throw_selection)throw std::runtime_error("selected");out=selected;return available;}
 idoly_mp4_playback::Phase automatic_rebuild_phase(){return phase;}}game;
}
// SHIPPING_PHASE_DECLARATION
bool bootstrap_proof=true,history_sealed=false;
bool mp4_source_bootstrap_roots_current(const Mp4SceneWitness&w){return bootstrap_proof&&mp4_scene_same_source(w,selected);}
bool mp4_root_history_initial_sealed(uint64_t epoch){return epoch==selected.generation&&history_sealed;}
void mp4_bind_source_prepass(){}
enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::admission;Mp4SceneWitness witness{};mp4world::DirectorGraphIdentity identity{16,32,2};void*director=reinterpret_cast<void*>(9),*asset=reinterpret_cast<void*>(10);};
struct Mp4TimelineRuntime{};
struct Mp4TimelineProducer{Mp4TimelineVerdict(*node)(const Mp4TimelineContext&,mp4actor::Handle,void*)=nullptr;bool(*userdata)(const Mp4TimelineContext&,mp4actor::Handle,void*,void*)=nullptr;Mp4TimelineVerdict(*runtime)(const Mp4TimelineContext&,const Mp4TimelineRuntime&)=nullptr;};
struct{bool(*current)(const Mp4TimelineContext&)=nullptr;bool(*restoration_closed)(const Mp4TimelineContext&)=nullptr;bool(*animation_output)(const Mp4TimelineContext&,uintptr_t)=nullptr;Mp4TimelineProducer actor{},camera{},world{},stage_other{};}mp4_timeline_hooks;
using Mp4NativeOutputClosed=bool(*)(const mp4world::DirectorGraphIdentity&,uintptr_t);
Mp4NativeOutputClosed mp4_director_output_closed[3]{};
Mp4TimelineProofPhase last_phase=Mp4TimelineProofPhase::admission;
bool mp4_audio_outer_output_closed(const Mp4SceneWitness&w,const mp4world::DirectorGraphIdentity&id,uintptr_t output,bool admission){++audio_calls;audio_admission=admission;if(throw_payload)throw 17;return audio_proof&&mp4_scene_same_source(w,selected)&&same_identity(id,expected)&&output==48;}
bool mp4_timeline_script_output_closed(Mp4TimelineProofPhase phase,const Mp4SceneWitness&w,const mp4world::DirectorGraphIdentity&id,uintptr_t output){++script_calls;last_phase=phase;if(throw_payload)throw 17;return script_proof&&mp4_scene_same_source(w,selected)&&same_identity(id,expected)&&output==56;}
bool mp4_persistent_or_rebuilt_animation_output_closed(const mp4world::DirectorGraphIdentity&id,uintptr_t output){return animation_proof&&same_identity(id,expected)&&output==64;}
bool mp4_timeline_current(const Mp4TimelineContext&c){return context_current&&same_identity(c.identity,expected);}
Mp4TimelineVerdict target_node(const Mp4TimelineContext&,mp4actor::Handle,void*){return Mp4TimelineVerdict::closed;}
bool target_data(const Mp4TimelineContext&,mp4actor::Handle,void*,void*){return false;}
Mp4TimelineVerdict target_runtime(const Mp4TimelineContext&,const Mp4TimelineRuntime&){return Mp4TimelineVerdict::unrecognized;}
Mp4TimelineProducer mp4_target_image_producer(){return {target_node,target_data,target_runtime};}
Mp4TimelineVerdict mp4_timeline_actor_node(const Mp4TimelineContext&,mp4actor::Handle,void*){return Mp4TimelineVerdict::unrecognized;}
bool mp4_timeline_actor_userdata(const Mp4TimelineContext&,mp4actor::Handle,void*,void*){return false;}
Mp4TimelineVerdict mp4_timeline_actor_runtime(const Mp4TimelineContext&,const Mp4TimelineRuntime&){return Mp4TimelineVerdict::unrecognized;}
// SHIPPING_PHASE_WITNESS
// SHIPPING_NATIVE_OUTPUT_ROUTES
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];mp4_bind_native_output_routes();
 assert(mp4_director_output_closed[0]==mp4_persistent_or_rebuilt_animation_output_closed&&mp4_director_output_closed[1]==mp4_native_audio_output_closed&&mp4_director_output_closed[2]==mp4_native_script_output_closed);
 assert(mp4_timeline_hooks.actor.node==mp4_timeline_actor_node&&mp4_timeline_hooks.actor.userdata==mp4_timeline_actor_userdata&&mp4_timeline_hooks.actor.runtime==mp4_timeline_actor_runtime&&mp4_timeline_hooks.world.node==target_node&&mp4_timeline_hooks.world.userdata==target_data&&mp4_timeline_hooks.world.runtime==target_runtime);
 if(mode=="payload_refused"){audio_proof=script_proof=false;}
 if(mode=="audio_only_refused")audio_proof=false;
 if(mode=="script_only_refused")script_proof=false;
 if(mode=="after_stage_cleanup")mp4_stage_host.source.generation=0;
 if(mode=="missing_stage_receipt")admission_receipt=false;
 if(mode=="unpublished_admission")mp4_scene_host.admitted=3;
 if(mode=="wrong_source")mp4_world_host.source.generation=8;
 if(mode=="foreign_thread")owner=false;
 if(mode=="no_selection")available=false;
 if(mode=="source_unverified")mp4_source_verified=false;
 if(mode=="releasing")mp4_scene_host.releasing=true;
 if(mode=="invalidated")mp4_scene_host.invalidated=true;
 if(mode=="selection_throw")throw_selection=true;
 if(mode=="payload_throw")throw_payload=true;
 const bool bootstrap=mode.rfind("bootstrap",0)==0;
 const bool active=mode.rfind("active",0)==0||mode.rfind("restore",0)==0||bootstrap;
 if(bootstrap){idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::acquiring;
  if(mode=="bootstrap_roots_refused")bootstrap_proof=false;
  if(mode=="bootstrap_sealed")history_sealed=true;
  if(mode=="bootstrap_payload_refused")script_proof=false;
 }
 if(active)mp4_scene_host.active=true;
 if(mode=="active_clock_only")mp4_scene_host.configured=0;
 if(mode=="active_clock_missing")idoly_mp4_runtime::clock.active_value=false;
 if(mode=="active_stage_lost")mp4_stage_host.source.generation=8;
 if(mode=="active_source_lost")source_current=false;
 if(mode=="active_idle")idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::idle;
 if(mode.rfind("restore",0)==0){idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::restoring;
  if(mode=="restore_final"||mode=="restore_final_payload_refused"){mp4_scene_host.logical_checkpoint=true;mp4_scene_host.restored=31;mp4_scene_host.finalized=2;}
  if(mode=="restore_final_payload_refused")script_proof=false;
  if(mode=="restore_unheld")idoly_mp4_runtime::clock.held_value=false;
  if(mode=="restore_uncaptured")mp4_scene_host.captured=3;
 }
 if(mode=="bad_output"){assert(!mp4_native_audio_output_closed(expected,0)&&!mp4_native_script_output_closed(expected,0)&&!audio_calls&&!script_calls);return 0;}
 if(mode=="bad_graph"){auto id=expected;id.version=3;assert(!mp4_native_audio_output_closed(id,48)&&!mp4_native_script_output_closed(id,56)&&!audio_calls&&!script_calls);return 0;}
 if(mode=="wrong_payload_identity"){auto id=expected;++id.slot;assert(!mp4_native_audio_output_closed(id,48)&&!mp4_native_script_output_closed(id,56)&&audio_calls==1&&script_calls==1);return 0;}
 if(mode=="animation_context"||mode=="animation_context_lost"||mode=="animation_payload_lost"){
  Mp4TimelineContext c{};if(mode=="animation_context_lost")context_current=false;if(mode=="animation_payload_lost")animation_proof=false;
  assert(mp4_timeline_hooks.animation_output(c,64)==(mode=="animation_context"));return 0;
 }
 const bool phase_ok=(bootstrap&&mode!="bootstrap_roots_refused")||mode=="admission"||mode=="after_stage_cleanup"||mode=="payload_refused"||mode=="audio_only_refused"||mode=="script_only_refused"||mode=="payload_throw"||mode=="active"||mode=="restore_plan"||mode=="restore_final"||mode=="restore_final_payload_refused";
 const bool a=mp4_native_audio_output_closed(expected,48),s=mp4_native_script_output_closed(expected,56);
 assert(a==(phase_ok&&audio_proof&&!throw_payload));assert(s==(phase_ok&&script_proof&&!throw_payload));
 assert(audio_calls==static_cast<unsigned>(phase_ok)&&script_calls==static_cast<unsigned>(phase_ok));
 if(phase_ok){assert(audio_admission==(!active||(bootstrap&&!history_sealed)));assert(last_phase==(bootstrap&&!history_sealed?Mp4TimelineProofPhase::source_bootstrap_plan:mode=="restore_final"||mode=="restore_final_payload_refused"?Mp4TimelineProofPhase::source_restored:mode=="restore_plan"?Mp4TimelineProofPhase::source_restore_plan:active?Mp4TimelineProofPhase::active:Mp4TimelineProofPhase::admission));}
 return 0;
}
'''
def function(text,name):
    m=re.search(r'bool\s+'+name+r'\(',text);assert m
    a=text.index('{',m.start());depth=1;b=a+1
    while depth:
        depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[m.start():b]
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    routes=text.split('// BEGIN_MP4_NATIVE_OUTPUT_ROUTE_HOST',1)[1].split('// END_MP4_NATIVE_OUTPUT_ROUTE_HOST',1)[0]
    declaration=text[text.index('enum class Mp4TimelineProofPhase'):text.index('enum class Mp4TimelineVerdict')]
    declaration=declaration[:declaration.index('bool mp4_source_bootstrap_roots_current')]
    source=HARNESS.replace('// SHIPPING_PHASE_DECLARATION',declaration).replace('// SHIPPING_PHASE_WITNESS',function(text,'mp4_timeline_phase_witness_current')).replace('// SHIPPING_NATIVE_OUTPUT_ROUTES',routes)
    folder=tmp_path_factory.mktemp('native-output-routes');cpp=folder/'test.cpp';out=folder/'test';cpp.write_text(source)
    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',str(cpp),'-o',str(out)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    return out
@pytest.mark.parametrize('mode','''bootstrap bootstrap_roots_refused bootstrap_sealed bootstrap_payload_refused admission after_stage_cleanup missing_stage_receipt unpublished_admission wrong_source foreign_thread no_selection source_unverified releasing invalidated selection_throw payload_throw payload_refused audio_only_refused script_only_refused bad_output bad_graph wrong_payload_identity active active_clock_only active_clock_missing active_stage_lost active_source_lost active_idle restore_plan restore_final restore_final_payload_refused restore_unheld restore_uncaptured animation_context animation_context_lost animation_payload_lost'''.split())
def test_only_complete_payload_proofs_close_native_outputs(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
