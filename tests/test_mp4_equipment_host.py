"""Run the shipping equipment wrapper with explicit original-call outcomes."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def function(text,signature):
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


@pytest.fixture(scope='module')
def wrapper(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=function(bridge,'bool mp4_stage_hooks_intercept(bool on_thread) noexcept')+'\n'+function(bridge,'void mp4_equipment_late_hook(')
    prefix=r'''
#include <cassert>
#include <atomic>
#include <cstdint>
#include <stdexcept>
#include <string>
using Method=const void;using Mp4EquipmentLate=void(*)(void*,Method*);
enum class Mp4EquipmentDispatch:uint8_t{forward,skip,owned};
Mp4EquipmentLate mp4_equipment_late_original=nullptr;
Mp4EquipmentDispatch (*mp4_equipment_dispatch_begin)(void*)=nullptr;
void (*mp4_equipment_dispatch_end)(void*,bool)=nullptr;
void (*mp4_equipment_observe_late)(void*)=nullptr;
void (*mp4_equipment_invalidate_late)(void*)=nullptr;
std::atomic<bool> mp4_stage_lease_active{true},mp4_stage_foreign_dirty{false};
bool on_thread=true,throws=false;int original_calls=0,begin_calls=0,end_calls=0,receipts=0,invalidations=0;bool completed=false;
void* receiver=reinterpret_cast<void*>(1);Method* method=reinterpret_cast<Method*>(2);Mp4EquipmentDispatch decision=Mp4EquipmentDispatch::forward;
bool game_call(){return on_thread;}
struct RngGate{template<class Action>bool isolate(Action action){action();return true;}}mp4_actor_mono_gate;
void mp4_stage_equipment_isolation_failed(){assert(false);}
void original(void* self,Method* info){assert(self==receiver&&info==method);++original_calls;if(throws)throw std::runtime_error("original");}
Mp4EquipmentDispatch begin(void* self){assert(self==receiver);++begin_calls;return decision;}
void end(void* self,bool success){assert(self==receiver);++end_calls;completed=success;}
void invalidate(void* self){assert(self==receiver);++invalidations;}
void receipt(void* self){assert(self==receiver);++receipts;}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];mp4_equipment_late_original=original;
    mp4_equipment_observe_late=receipt;mp4_equipment_invalidate_late=invalidate;
    if(mode!="passive"){mp4_equipment_dispatch_begin=begin;mp4_equipment_dispatch_end=end;}
    if(mode=="owned"||mode=="throw")decision=Mp4EquipmentDispatch::owned;
    if(mode=="skip")decision=Mp4EquipmentDispatch::skip;
    if(mode=="withdrawn"){mp4_stage_lease_active=false;decision=Mp4EquipmentDispatch::skip;}
    if(mode=="foreign_thread")on_thread=false;
    if(mode=="throw")throws=true;
    bool threw=false;try{mp4_equipment_late_hook(receiver,method);}catch(const std::runtime_error&){threw=true;}
    assert(mp4_stage_foreign_dirty.load()==(mode=="foreign_thread"));
    assert(threw==(mode=="throw"));assert(original_calls==(mode=="skip"?0:1));
    assert(begin_calls==((mode=="passive"||mode=="foreign_thread"||mode=="withdrawn")?0:1));
    assert(invalidations==((mode=="skip"||mode=="foreign_thread")?0:1));
    assert(end_calls==((mode=="owned"||mode=="throw")?1:0));
    assert(completed==(mode=="owned"));assert(receipts==((mode=="skip"||mode=="throw"||mode=="foreign_thread")?0:1));
}
'''
    folder=tmp_path_factory.mktemp('equipment-wrapper');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize('mode',['passive','forward','owned','skip','throw','foreign_thread','withdrawn'])
def test_original_forwarding_and_owned_unwind_are_exact(wrapper,mode):
    result=subprocess.run([str(wrapper),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
