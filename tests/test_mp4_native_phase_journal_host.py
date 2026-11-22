"""Shipping native phase/Raw/Journal join; native callback leaves are modeled."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include "mp4_engine_clock.hpp"
#include <cassert>
#include <cstring>
#include <string>
using idoly_mp4_world::AnimationGate;
AnimationGate mp4_animation_gate;
using Phase=void(*)();
Phase mp4_animation_original[8]{};
uintptr_t mp4_native_base=0;
struct Profile{struct Row{idoly_mp4_world::CodeBinding callback{};}phases[8];}mp4_animation_profile;
std::string mode;
bool owner=true,source_current=true,routes=true,closure=true;
bool game_call(){return owner;}
bool mp4_animation_routes_ready(){return routes;}
bool mp4_world_source_current(void*){return source_current;}
bool mp4_scene_source_current(){return source_current;}
struct World{bool animation_owned=true;uint64_t epoch=17;bool invalidated=false;const char*error="none";}mp4_world_host;
struct Scene{bool active=true;struct Source{uint64_t generation=17;void*director=reinterpret_cast<void*>(22);}source;
 void*root_asset=reinterpret_cast<void*>(33);uint32_t root_asset_handle=1;}mp4_scene_host;
void*mp4_scene_root_asset_receipt(uint64_t e){return source_current&&e==17?mp4_scene_host.root_asset:nullptr;}
'''
MIDDLE=r'''
namespace dm=mp4_director_maintenance;
struct PendingHost{dm::Journal value;dm::Journal&journal(){return value;}bool routes_current()const{return routes&&mode!="unconfigured";}}mp4_child_pending_host;
bool mp4_child_call_same(const dm::Call&a,const dm::Call&b){return a.kind==b.kind&&a.epoch==b.epoch&&a.serial==b.serial
 &&a.source_asset==b.source_asset&&a.receiver==b.receiver&&a.method==b.method&&a.original_receipt==b.original_receipt;}
'''
DRIVER=r'''
unsigned after_receipts=0;dm::Call last_after{};unsigned calls[8]{};bool native_entered=false,maintenance=false,returned_body=false;
alignas(16) unsigned char manager[0x500]{},queue[16]{};
bool plan(const dm::Call&c){const auto&r=mp4_raw_original_operation;
 return source_current&&owner&&r.depth&&c.epoch==r.epoch&&c.serial==r.serial&&c.source_asset==r.root_asset
  &&c.receiver==r.director&&c.method==r.method&&c.original_receipt==r.receipt&&static_cast<uint8_t>(c.kind)==r.kind
  &&(r.kind==6||mp4_native_phase_origin(c.epoch,reinterpret_cast<void*>(c.receiver),c.method));
}
bool current(void*,const dm::Call&c){if(mode=="after_observer_throw"&&returned_body)throw 42;return plan(c)&&!(mode=="entry_failure"&&mp4_raw_original_operation.invoked);}
bool origin(void*,const dm::Call&c){return plan(c);}
bool retired(void*,uint64_t,uintptr_t,uintptr_t,uint32_t,uint64_t,uintptr_t){return false;}
bool read(void*,uintptr_t a,void*out,size_t n){
 const auto*scope=Mp4NativePhaseReturnedScope::current;uint64_t rt=999;uint8_t rp=99;
 dm::Call current_call{};const bool operation=mp4_director_actual_operation(&current_call);
 const bool wanted=scope&&scope->returned&&operation&&current_call.kind==dm::Kind::native_phase;
 assert(mp4_native_phase_returned_current(current_call,&rt,&rp)==wanted);
 if(wanted){++after_receipts;last_after=current_call;assert(rt==scope->tick&&rp==scope->phase);
  auto wrong=current_call;++wrong.serial;assert(!mp4_native_phase_returned_current(wrong,&rt,&rp)&&!rt&&!rp);
  if(mode=="after_wrong_tick"){auto*mutable_scope=Mp4NativePhaseReturnedScope::current;++mutable_scope->tick;assert(!mp4_native_phase_returned_current(current_call,&rt,&rp));--mutable_scope->tick;}
  if(mode=="after_wrong_phase"){auto*mutable_scope=Mp4NativePhaseReturnedScope::current;++mutable_scope->phase;assert(!mp4_native_phase_returned_current(current_call,&rt,&rp));--mutable_scope->phase;}
  if(mode=="after_offthread"){owner=false;assert(!mp4_native_phase_returned_current(current_call,&rt,&rp));owner=true;}
 }
 const auto m=reinterpret_cast<uintptr_t>(manager),q=reinterpret_cast<uintptr_t>(queue);
 if(!((a>=m&&n<=sizeof manager&&a-m<=sizeof manager-n)||(a>=q&&n<=sizeof queue&&a-q<=sizeof queue-n)))return false;
 memcpy(out,reinterpret_cast<void*>(a),n);return true;
}
bool hook(void*,dm::Hook,uintptr_t receiver,const dm::Call&c){return native_entered&&receiver==reinterpret_cast<uintptr_t>(manager)&&plan(c);}
bool basis(void*,const dm::Call&,idoly_mp4_world::AnimationGraph,uint32_t,dm::Basis*){return false;}
bool future(void*,const dm::Call&){return closure;}
void observe(unsigned p){
 ++calls[p];dm::Call c{};uint64_t tick=999;uint8_t phase=99;
 const bool actual=mp4_director_actual_operation(&c);
 assert(!mp4_native_phase_returned_current(c,&tick,&phase)&&!tick&&!phase);
 const bool admitted=!mp4_world_host.invalidated&&source_current&&mode!="ordinary";
 assert(actual==admitted);
 if(admitted){
  assert(c.kind==(maintenance?dm::Kind::maintenance:dm::Kind::native_phase));
  assert(mp4_child_pending_host.journal().current_call(c));
  if(maintenance){assert(!mp4_native_phase_call_current(c,&tick,&phase));assert(tick==0&&phase==0);}
  else{
   assert(mp4_native_phase_call_current(c,&tick,&phase)&&tick==0&&phase==p);
   auto wrong=c;++wrong.serial;assert(!mp4_native_phase_call_current(wrong,&tick,&phase)&&tick==0&&phase==0);
   assert(mp4_native_phase_deferred_current(nullptr,c)==(p==5));
  }
 }
 if(mode=="source_loss"&&p==0)source_current=false;
 if(mode=="throw"&&p==0)throw 31;
 if(mode=="begin_throw"&&p==2)throw 31;
 if((mode=="deferred"&&p==5)||(mode=="wrong_deferred_phase"&&p==1)){
  native_entered=true;auto&j=mp4_child_pending_host.journal();
  const bool wanted=p==5;
  assert(j.deferred_begin(0)==wanted);if(wanted)assert(j.deferred_end(0));
  native_entered=false;
 }
}
void p0(){observe(0);returned_body=true;}void p1(){observe(1);}void p2(){observe(2);}void p3(){observe(3);}
void p4(){observe(4);}void p5(){observe(5);}void p6(){observe(6);}void p7(){observe(7);}
void f0(){if(mode=="unowned_forward")mp4_animation_unowned_original(0);else mp4_animation_journal_original(0);}void f1(){mp4_animation_journal_original(1);}
void f2(){mp4_animation_journal_original(2);}void f3(){mp4_animation_journal_original(3);}
void f4(){mp4_animation_journal_original(4);}void f5(){mp4_animation_journal_original(5);}
void f6(){mp4_animation_journal_original(6);}void f7(){mp4_animation_journal_original(7);}
bool thread(){return owner;}
bool before(void*,uint64_t e){return e==17&&mp4_animation_gate.closed(e);}
bool after(void*,uint64_t e){return e==17&&mp4_animation_gate.closed(e);}
void setup(){
 Phase raw[]={p0,p1,p2,p3,p4,p5,p6,p7};for(unsigned i=0;i<8;++i){mp4_animation_original[i]=raw[i];mp4_animation_profile.phases[i].callback.rva=reinterpret_cast<uintptr_t>(raw[i]);}
 idoly_mp4_world::AnimationApi gate{{f0,f1,f2,f3,f4,f5,f6,f7},thread};assert(mp4_animation_gate.install(gate));
 uintptr_t q=reinterpret_cast<uintptr_t>(queue);memcpy(manager+0x478,&q,sizeof q);
 dm::Api api{};api.manager=reinterpret_cast<uintptr_t>(manager);api.current=current;api.call_origin=origin;api.retired_output=retired;
 api.read=read;api.hook_origin=hook;api.basis=basis;api.future_producers_closed=future;api.frame_deferred_current=mp4_native_phase_deferred_current;
 if(mode!="unconfigured")assert(mp4_child_pending_host.journal().configure(api));
}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];setup();
 if(mode=="ordinary"){mp4_animation_journal_original(0);assert(calls[0]==1&&!mp4_raw_original_operation.depth);return 0;}
 {Mp4OriginalOperationScope fake(17,7,reinterpret_cast<void*>(22),reinterpret_cast<uintptr_t>(p0),0);assert(!fake.valid);}
 assert(mp4_animation_gate.acquire(17));
 if(mode=="maintenance"){
  maintenance=true;Mp4OriginalOperationScope op(17,6,reinterpret_cast<void*>(22),reinterpret_cast<uintptr_t>(p5),0);assert(op.valid);
  const auto&r=mp4_raw_original_operation;dm::Call c{dm::Kind::maintenance,r.epoch,r.serial,r.root_asset,r.director,r.method,r.receipt};
  auto&j=mp4_child_pending_host.journal();assert(j.begin(c));op.invoked();assert(j.invoked());
  assert(mp4_animation_gate.maintenance(17,{nullptr,before,after})&&calls[5]==1&&j.end());
  assert(mp4_raw_original_sequence==1&&!mp4_animation_gate.completed_frame(17,0));return 0;
 }
 if(mode=="bad_routes")routes=false;
 if(mode=="bad_closure")closure=false;
 assert(mp4_animation_gate.grant(17,0));
 if(mode=="throw"||mode=="begin_throw"||mode=="after_observer_throw"){
  try{for(unsigned i=0;i<(mode=="begin_throw"?3u:1u);++i)mp4_animation_gate.invoke(i);assert(false);}catch(int x){assert(x==(mode=="after_observer_throw"?42:31));}
  assert(!mp4_animation_gate.healthy(17)&&!mp4_animation_gate.completed_frame(17,0));
  assert(mp4_world_host.invalidated&&!mp4_child_pending_host.journal().active()&&!mp4_raw_original_operation.depth&&!Mp4NativePhaseReturnedScope::current);
  if(mode=="begin_throw"){assert(mp4_animation_gate.invoke(4)&&calls[4]==1);}
  for(unsigned i=0;i<3;++i)assert(calls[i]<=1);
  assert(mp4_animation_gate.release(17));return 0;
 }
 const bool success=mode=="sequence"||mode=="deferred"||mode=="after_returned"||mode=="after_wrong_tick"||mode=="after_wrong_phase"||mode=="after_offthread";
 const unsigned count=success?8:mode=="wrong_deferred_phase"?2:1;
 for(unsigned i=0;i<count;++i)assert(mp4_animation_gate.invoke(i));
 assert(!mp4_raw_original_operation.depth&&!mp4_child_pending_host.journal().active()&&!Mp4NativePhaseReturnedScope::current);
 uint64_t out_tick=999;uint8_t out_phase=99;assert(!mp4_native_phase_returned_current(last_after,&out_tick,&out_phase)&&!out_tick&&!out_phase);
 if(success)assert(after_receipts>=8);
 assert(mp4_animation_gate.completed_frame(17,0)==success);
 assert(mp4_world_host.invalidated==!success);
 for(unsigned i=0;i<count;++i)assert(calls[i]==1);
 if(success){for(unsigned i=0;i<8;++i)assert(!mp4_animation_gate.invoke(i));assert(mp4_raw_original_sequence==8);}
 assert(mp4_animation_gate.release(17));return 0;
}
'''
def function(text,signature):
    a=text.index(signature);left=text.index('{',a);depth=1;right=left+1
    while depth:
        depth+=(text[right]=='{')-(text[right]=='}');right+=1
    return text[a:right]+'\n'
def marker(text,name):
    return text.split('// BEGIN_'+name,1)[1].split('// END_'+name,1)[0]
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    a=text.index('struct Mp4RawOriginalOperation {');b=text.index('struct Mp4OriginalEvaluationScope',a)
    source=PREFIX+marker(text,'MP4_DIRECTOR_MAINTENANCE_CORE')+text[a:b]
    source+='\n'+function(text,'[[maybe_unused]] bool mp4_director_actual_operation(')
    source+=MIDDLE+marker(text,'MP4_NATIVE_PHASE_JOURNAL_HOST')+DRIVER
    folder=tmp_path_factory.mktemp('mp4-native-phase-journal');cpp=folder/'test.cpp';out=folder/'test';cpp.write_text(source)
    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(out)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    return out
@pytest.mark.parametrize('mode',['ordinary','sequence','maintenance','deferred','wrong_deferred_phase','unconfigured','unowned_forward','bad_routes','bad_closure','entry_failure','source_loss','throw','begin_throw','after_observer_throw','after_returned','after_wrong_tick','after_wrong_phase','after_offthread'])
def test_shipping_phase_journal_boundary(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
