"""Actual accepted native-phase stack receipts, using shipping AnimationGate.

Only callback leaves are modeled; these cases make no game/device claim.
"""
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
AnimationGate gate;
std::string mode;
unsigned calls[8]{},queries=0;
bool owner=true,accepted=false,maintenance=false;
uint64_t current_tick=0;
bool thread(){++queries;return owner;}
void observe(unsigned n){
 ++calls[n];uint64_t tick=999;uint8_t phase=99;const unsigned before=queries;
 const bool valid=gate.granted_phase(17,&tick,&phase);
 assert(queries==before); // receipt getters never invoke thread/Unity callbacks
 assert(valid==accepted);
 assert(gate.issued_frame(17,current_tick)==accepted);
 if(valid){assert(tick==current_tick&&phase==n);assert(!gate.completed_frame(17,current_tick));}
 else{assert(tick==0&&phase==0);}
 tick=999;phase=99;assert(!gate.granted_phase(18,&tick,&phase)&&tick==0&&phase==0);
 if(maintenance){assert(n==5&&gate.maintenance_inflight(17)&&!valid);return;}
 if((mode=="revoke_inside"||mode=="reject_inside")&&n==2){
  if(mode=="reject_inside"){assert(!gate.reject_inflight(18));assert(gate.reject_inflight(17));}
  else{gate.revoke_grants(17);}tick=999;phase=99;
  assert(!gate.granted_phase(17,&tick,&phase)&&tick==0&&phase==0);
 }
 if(mode=="recursive"&&n==1){
  assert(!gate.invoke(2));tick=999;phase=99;
  assert(!gate.granted_phase(17,&tick,&phase)&&tick==0&&phase==0);
 }
 if(mode=="throw"&&n==2)throw 31;
}
void p0(){observe(0);}void p1(){observe(1);}void p2(){observe(2);}void p3(){observe(3);}
void p4(){observe(4);}void p5(){observe(5);}void p6(){observe(6);}void p7(){observe(7);}
bool before(void*,uint64_t e){return e==17&&gate.closed(e);}
bool after(void*,uint64_t e){return e==17&&gate.closed(e);}
void outside(){uint64_t t=999;uint8_t p=99;const unsigned q=queries;
 assert(!gate.granted_phase(17,&t,&p)&&t==0&&p==0);
 assert(!gate.granted_phase(17,&t,nullptr)&&t==0);
 assert(!gate.granted_phase(17,nullptr,&p)&&p==0);
 assert(queries==q);
}
int main(int argc,char**argv){
 assert(argc==2);mode=argv[1];AnimationApi api{{p0,p1,p2,p3,p4,p5,p6,p7},thread};assert(gate.install(api));
 outside();assert(!gate.completed_frame(17,0)&&!gate.issued_frame(17,0));
 if(mode=="ordinary"){for(unsigned i=0;i<8;++i)assert(gate.invoke(i));outside();assert(!gate.completed_frame(17,0));return 0;}
 assert(gate.acquire(17));outside();assert(!gate.completed_frame(17,0)&&!gate.revoked_unconsumed_frame(17,0));
 if(mode=="revoke_unissued"){gate.revoke_grants(17);assert(!gate.revoked_unconsumed_frame(17,0)&&gate.release(17));return 0;}
 if(mode=="maintenance_initial"){
  maintenance=true;assert(gate.maintenance(17,{nullptr,before,after}));maintenance=false;
  outside();assert(!gate.completed_frame(17,0));assert(gate.release(17));return 0;
 }
 assert(!gate.issued_frame(17,0));assert(gate.grant(17,0));outside();accepted=true;
 assert(gate.issued_frame(17,0)&&!gate.issued_frame(18,0)&&!gate.issued_frame(17,1));
 if(mode=="offthread"){
  owner=false;accepted=false;assert(gate.invoke(0));owner=true;
  outside();assert(!gate.completed_frame(17,0)&&!gate.healthy(17));assert(gate.release(17));return 0;
 }
 if(mode=="revoke_before"||mode=="revoked_unconsumed"){
  assert(!gate.revoked_unconsumed_frame(17,0));gate.revoke_grants(17);accepted=false;
  assert(gate.revoked_unconsumed_frame(17,0)&&!gate.revoked_unconsumed_frame(18,0)&&!gate.revoked_unconsumed_frame(17,1));
  for(unsigned i=0;i<8;++i)assert(!gate.invoke(i));
  assert(!gate.completed_frame(17,0)&&gate.release(17));return 0;
 }
 if(mode=="throw"){
  try{for(unsigned i=0;i<3;++i)gate.invoke(i);assert(false);}catch(int x){assert(x==31);}
  accepted=false;outside();assert(!gate.completed_frame(17,0)&&!gate.healthy(17));
  assert(gate.invoke(4)&&calls[4]==1);assert(gate.release(17));return 0;
 }
 if(mode=="recursive"){
  assert(gate.invoke(0)&&gate.invoke(1));accepted=false;outside();
  assert(!gate.completed_frame(17,0)&&!gate.healthy(17)&&gate.release(17));return 0;
 }
 if(mode=="revoke_inside"||mode=="reject_inside"){
  for(unsigned i=0;i<3;++i){assert(gate.invoke(i));}accepted=false;outside();
  assert(!gate.completed_frame(17,0)&&!gate.revoked_unconsumed_frame(17,0)&&!gate.invoke(3));assert(gate.invoke(4));
  assert(!gate.completed_frame(17,0)&&gate.release(17));return 0;
 }
 for(unsigned i=0;i<8;++i){assert(gate.invoke(i));outside();if(i<7)assert(!gate.completed_frame(17,0));}
 accepted=false;assert(!gate.issued_frame(17,0));assert(gate.completed_frame(17,0)&&!gate.completed_frame(18,0)&&!gate.completed_frame(17,1));
 if(mode=="maintenance_after"){
  maintenance=true;assert(gate.maintenance(17,{nullptr,before,after}));maintenance=false;
  outside();assert(gate.completed_frame(17,0));
 }
 assert(gate.grant(17,1));current_tick=1;accepted=true;assert(gate.issued_frame(17,1)&&!gate.issued_frame(17,0)&&!gate.completed_frame(17,0));
 for(unsigned i=0;i<8;++i){assert(gate.invoke(i));}accepted=false;
 assert(gate.completed_frame(17,1)&&!gate.completed_frame(17,0));
 assert(gate.release(17));outside();assert(!gate.completed_frame(17,1));return 0;
}
'''
@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    compiler=shutil.which("c++")
    if not compiler:pytest.skip("C++ compiler required")
    folder=tmp_path_factory.mktemp("mp4-animation-phase-receipt")
    source=folder/"test.cpp";out=folder/"test";source.write_text(HARNESS)
    result=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-fno-omit-frame-pointer","-no-pie","-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(out)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return out
@pytest.mark.parametrize("mode",["ordinary","sequence","maintenance_initial","maintenance_after","offthread","revoke_before","revoked_unconsumed","revoke_unissued","revoke_inside","reject_inside","throw","recursive"])
def test_actual_phase_receipt_lifetime(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
