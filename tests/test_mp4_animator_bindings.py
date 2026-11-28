"""Production complete bound-output admission over native-layout fixtures.

Original record construction/append/query instructions are checked separately;
this test never equates fake handles to an actual Unity graph or render proof.
"""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <array>
#include <cassert>
#include <string>
using namespace idoly_mp4_world;
alignas(8)unsigned char object[64]{},native[0x300]{},other_native[0x300]{},records[80]{},other_records[80]{};
std::string mode;unsigned roots=0;bool source=true,live=true,root_live=true,changed=false;void*target_object=object;
template<class T>void put(void*p,size_t at,T value){memcpy(static_cast<unsigned char*>(p)+at,&value,sizeof(value));}
bool span(uintptr_t a,size_t n,const void*p,size_t bytes){const uintptr_t b=reinterpret_cast<uintptr_t>(p);return a>=b&&n<=bytes&&a-b<=bytes-n;}
bool mapped(uintptr_t a,size_t n){if(mode=="unmapped")return false;return span(a,n,object,sizeof object)||span(a,n,native,sizeof native)||span(a,n,other_native,sizeof other_native)||span(a,n,records,sizeof records)||span(a,n,other_records,sizeof other_records);}
bool current(void*){return source;}bool type(void*p,const char*n){return p==object&&!strcmp(n,"UnityEngine.Animator");}bool alive(void*p){return p==object&&live;}
uint32_t retain(void*){if(mode=="root_failed")return 0;++roots;return 1;}void*target(uint32_t n){return n==1&&root_live?object:nullptr;}void free_root(uint32_t n){assert(n==1&&roots);--roots;}
bool output_valid(AnimationOutput*o,Method*){return o->handle&&(o->version==7);}
bool graph_valid(AnimationGraph*g,Method*){return g->handle&&(g->version==9);}
void*output_type(AnimationOutput*,Method*){return reinterpret_cast<void*>(mode=="wrong_type"?0x666:0x777);}
void*output_target(AnimationOutput*,Method*){
 if(!changed){changed=true;
  if(mode=="count_changed")put(native,0x178,uint64_t(2));
  if(mode=="capacity_changed")put(native,0x180,uint64_t(99));
  if(mode=="flags_changed")put(native,0x194,uint8_t(16));
  if(mode=="native_changed")put(object,0x10,reinterpret_cast<uintptr_t>(other_native));
  if(mode=="data_changed")put(native,0x168,reinterpret_cast<uintptr_t>(other_records));
  if(mode=="output_changed")put(records,8,uint32_t(11));
  if(mode=="graph_changed")put(records,24,uint32_t(11));
  if(mode=="source_changed")source=false;
  if(mode=="root_lost")root_live=false;
  if(mode=="destroyed")live=false;
 }
 return mode=="wrong_target"?nullptr:target_object;
}
bool owned(void*,void*p,const AnimationGraph&g){return p==object&&g.handle!=0x333;}
AnimationBindingsApi api(){AnimationBindingsApi a{};auto&w=a.world;w.source_current=current;w.mapped=mapped;w.is_type=type;w.alive=alive;w.retain=retain;w.retained=target;w.release_root=free_root;
 a.output_valid=output_valid;a.output_type=output_type;a.output_target=output_target;a.graph_valid=graph_valid;a.graph_owned=owned;a.animation_output_type=reinterpret_cast<void*>(0x777);return a;}
void record(unsigned index,uintptr_t output,uintptr_t graph){AnimationOutput o{output,7,0};AnimationGraph g{graph,9,0};put(records,index*40,o);put(records,index*40+16,g);}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];
 put(object,0x10,reinterpret_cast<uintptr_t>(native));put(native,0x168,reinterpret_cast<uintptr_t>(records));put(native,0x178,uint64_t(1));put(native,0x180,uint64_t(4));record(0,0x111,0x222);
 if(mode=="cast_stage"||mode=="extra_unowned"||mode=="duplicate"){put(native,0x178,uint64_t(2));record(1,mode=="duplicate"?0x111:0x112,mode=="extra_unowned"?0x333:0x223);}
 if(mode=="empty"||mode=="suspended_empty")put(native,0x178,uint64_t(0));
 if(mode=="suspended"||mode=="suspended_empty")put(native,0x194,uint8_t(16));
 if(mode=="bad_output")put(records,8,uint32_t(8));
 if(mode=="bad_graph")put(records,24,uint32_t(8));
 if(mode=="too_many")put(native,0x178,uint64_t(9000));
 if(mode=="capacity_small")put(native,0x180,uint64_t(0));
 auto a=api();if(mode=="missing_api")a.output_valid=nullptr;
 AnimationBindingsAdmission admission;int context=1;const auto result=admission.admit(a,&context,object);
 const bool expected=mode=="valid"||mode=="cast_stage"||mode=="empty";
 assert((result==Result::ok)==expected&&roots==0);return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 compiler=shutil.which('c++')
 if not compiler:pytest.skip('Host C++ compiler required')
 d=tmp_path_factory.mktemp('mp4-animator-bindings');s=d/'test.cpp';b=d/'test';s.write_text(HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(s),'-o',str(b)],capture_output=True,text=True);assert r.returncode==0,r.stderr
 return b
@pytest.mark.parametrize('mode',['valid','cast_stage','empty','extra_unowned','duplicate','wrong_type','wrong_target','bad_output','bad_graph','too_many','capacity_small','suspended','suspended_empty','count_changed','capacity_changed','flags_changed','native_changed','data_changed','output_changed','graph_changed','source_changed','root_lost','root_failed','destroyed','unmapped','missing_api'])
def test_production_all_bound_output_ownership(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True);assert r.returncode==0,r.stderr
