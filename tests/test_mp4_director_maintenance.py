"""Shipping Deferred-only gate: modeled callbacks, no GPU/game claim."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <cassert>
#include <string>
using namespace idoly_mp4_world;
AnimationGate gate;unsigned called[8]{},before_calls=0,after_calls=0;
bool owner=true,before_ok=true,after_ok=true;std::string mode;
void p0(){++called[0];}void p1(){++called[1];}void p2(){++called[2];}void p3(){++called[3];}void p4(){++called[4];}
void p5(){++called[5];
 if(mode.rfind("maintenance_",0)==0){assert(gate.maintenance_inflight(9)&&!gate.granted_inflight(9));
  assert(!gate.prepare(9,0)&&!gate.release(9));
  if(mode=="maintenance_reenter")assert(!gate.invoke(0));
  if(mode=="maintenance_throw")throw 31;
  if(mode=="maintenance_revoke")gate.revoke_grants(9);
 }
}
void p6(){++called[6];}void p7(){++called[7];}bool thread(){return owner;}
bool before(void*,uint64_t epoch){++before_calls;return epoch==9&&before_ok&&gate.closed(9);}
bool after(void*,uint64_t epoch){++after_calls;if(mode=="maintenance_after_throw")throw 32;return epoch==9&&after_ok&&gate.closed(9);}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];AnimationApi api{{p0,p1,p2,p3,p4,p5,p6,p7},thread};assert(gate.install(api)&&gate.acquire(9));AnimationMaintenanceApi proof{nullptr,before,after};
 if(mode=="missing_before"){proof.before=nullptr;assert(!gate.maintenance(9,proof)&&!called[5]);return 0;}
 if(mode=="missing_after"){proof.after=nullptr;assert(!gate.maintenance(9,proof)&&!called[5]);return 0;}
 if(mode=="before_reject"){before_ok=false;assert(!gate.maintenance(9,proof)&&!called[5]&&before_calls==1&&!after_calls&&gate.closed(9));return 0;}
 if(mode=="wrong_epoch"){assert(!gate.maintenance(10,proof)&&!called[5]&&!before_calls);return 0;}
 if(mode=="wrong_thread"){owner=false;assert(!gate.maintenance(9,proof)&&!called[5]);return 0;}
 if(mode=="open_grant"||mode=="open_pair"){assert(gate.grant(9,0));if(mode=="open_pair")for(unsigned k=0;k<3;++k)assert(gate.invoke(k));assert(!gate.maintenance(9,proof)&&!called[5]);return 0;}
 if(mode=="maintenance_throw"||mode=="maintenance_after_throw"){try{gate.maintenance(9,proof);assert(false);}catch(int x){assert(x==(mode=="maintenance_throw"?31:32));}assert(!gate.healthy(9)&&!gate.maintenance_inflight(9)&&after_calls==(mode=="maintenance_throw"?0u:1u)&&gate.release(9));return 0;}
 if(mode=="maintenance_after_reject")after_ok=false;
 const bool expected=mode!="maintenance_after_reject"&&mode!="maintenance_reenter";
 assert(gate.maintenance(9,proof)==expected);assert(called[5]==1&&before_calls==1);
 for(unsigned k=0;k<8;++k)if(k!=5)assert(!called[k]);
 assert(!gate.maintenance_inflight(9)&&!gate.granted_inflight(9));
 if(!expected){assert(!gate.healthy(9)&&!gate.grant(9,0)&&gate.release(9));return 0;}
 assert(after_calls==1&&gate.closed(9));
 if(mode=="maintenance_twice"){assert(gate.maintenance(9,proof)&&called[5]==2);}
 // Maintenance consumed no logical tick and no phase-order bit. Tick0 still
 // starts with SampleTime; next accepted tick is exactly1 after the full cycle.
 mode="ordinary";assert(gate.prepare(9,0)&&gate.grant(9,0));
 for(unsigned k=0;k<8;++k)assert(gate.invoke(k));
 assert(gate.closed(9)&&!gate.grant(9,0)&&gate.prepare(9,1));
 assert(gate.maintenance(9,proof)&&gate.prepare(9,1)&&!gate.prepare(9,2));
 assert(gate.release(9));return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('mp4-director-maintenance')
    source=folder/'test.cpp';binary=folder/'test';source.write_text(HARNESS)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary
@pytest.mark.parametrize('mode',['maintenance_once','maintenance_twice','maintenance_revoke','maintenance_reenter','maintenance_throw','maintenance_after_throw','maintenance_after_reject','missing_before','missing_after','before_reject','wrong_epoch','wrong_thread','open_grant','open_pair'])
def test_actual_deferred_only_gate(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

PATCH_HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <cassert>
using namespace idoly_mp4_world;
alignas(16) unsigned char image[0x1000]{};unsigned proofs=0;bool published=true;
bool mapped(uintptr_t at,size_t size){const auto base=reinterpret_cast<uintptr_t>(image);return at>=base&&size<=sizeof image&&at-base<=sizeof image-size;}
bool owned(const CodeBinding&binding){++proofs;if(!published||binding.rva!=0x100)return false;for(unsigned k=0;k<16;++k)if(binding.prefix[k]!=0xa5||image[0x100+k]!=0x5a)return false;return true;}
int main(){DirectorRegistryProfile p{};CodeBinding code{0x100,{}};for(auto&b:code.prefix)b=0xa5;
 CodeBinding*all[]={&p.registry_getter,&p.sample_category,&p.rebuild,&p.append,&p.category,&p.callbacks_rebuild,&p.callbacks_dispatch,&p.output_callbacks,&p.drain,&p.collect,&p.enqueue,&p.deferred_a,&p.deferred_b,&p.deferred_append_a,&p.deferred_append_b,&p.graph_create,&p.graph_destroy,&p.atomic_push,&p.atomic_pop};
 for(auto*c:all)*c=code;
 const auto base=reinterpret_cast<uintptr_t>(image);for(unsigned i=0;i<3;++i){auto&o=p.outputs[i];o.vtable=0x200+i*0x100;o.producer=code;o.count=1;o.callbacks[0]=code;uintptr_t target=base+0x100;memcpy(image+o.vtable+0x20,&target,8);}
 memset(image+0x100,0xa5,16);assert(director_registry_profile_matches(p,base,mapped,owned)&&proofs==0);
 memset(image+0x100,0x5a,16);assert(!director_registry_profile_matches(p,base,mapped));
 assert(director_registry_profile_matches(p,base,mapped,owned)&&proofs>0);
 published=false;assert(!director_registry_profile_matches(p,base,mapped,owned));published=true;
 image[0x100]=0x33;assert(!director_registry_profile_matches(p,base,mapped,owned));
 memset(image+0x100,0x5a,16);p.enqueue.rva=0x110;assert(!director_registry_profile_matches(p,base,mapped,owned));
 return 0;}
'''

def test_exact_owned_native_patch_receipt(tmp_path):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    source=tmp_path/'patch.cpp';binary=tmp_path/'patch';source.write_text(PATCH_HARNESS)
    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
