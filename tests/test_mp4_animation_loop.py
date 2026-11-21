"""Production native phase gates and current typed loop admission.

The callbacks/arrays in this host test are modeled. Unchanged original native
counter instructions execute in the separate ARM64 tests, not a game or GPU.
"""
from pathlib import Path
import importlib.util,json,os,shutil,subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <array>
#include <cassert>
#include <string>
#include <vector>
using namespace idoly_mp4_world;
AnimationGate gate;bool on_thread=true;unsigned calls[8]{};bool recursive=false;int throw_phase=-1;
void p0(){++calls[0];if(throw_phase==0)throw 17;if(recursive)gate.invoke(1);}void p1(){++calls[1];}void p2(){++calls[2];if(throw_phase==2)throw 17;}void p3(){++calls[3];}
void p4(){++calls[4];}void p5(){++calls[5];}void p6(){++calls[6];}void p7(){++calls[7];}
bool thread(){return on_thread;}
struct Fixture{std::vector<LoopEntry>entries;alignas(8)unsigned char registry[0x800]{};uintptr_t pointer=0;unsigned roots=0;bool root_live=true;}f;
AnimationProfile profile=android_animation_profile;void*types[8]{};
bool span(uintptr_t a,size_t n,const void*p,size_t size){const uintptr_t b=reinterpret_cast<uintptr_t>(p);return a>=b&&n<=size&&a-b<=size-n;}
bool mapped(uintptr_t a,size_t n){return span(a,n,f.registry,sizeof f.registry)||span(a,n,&f.pointer,sizeof f.pointer)||span(a,n,f.entries.data(),f.entries.size()*sizeof(LoopEntry));}
bool route_write=true,route_race=false;
bool route_mapped(uintptr_t a,size_t n,bool write){
 if(write&&!route_write)return false;
 if(write&&route_race&&a==reinterpret_cast<uintptr_t>(f.registry)+profile.phases[7].slot){uintptr_t foreign=0x9999;memcpy(f.registry+profile.phases[3].slot,&foreign,sizeof foreign);route_race=false;}
 return mapped(a,n);
}
void*loop(Method*){return &f;}bool type(void*p,const char*n){return p==&f&&!strcmp(n,"System.Array");}
uint32_t retain(void*p){assert(p==&f);++f.roots;return 1;}void*retained(uint32_t n){return n==1&&f.root_live?&f:nullptr;}
void release(uint32_t n){assert(n==1&&f.roots);--f.roots;}size_t length(void*){return f.entries.size();}void*data(void*){return f.entries.data();}
Api api(){Api a{};a.current_loop=loop;a.is_type=type;a.retain=retain;a.retained=retained;a.release_root=release;a.array_length=length;a.array_data=data;a.mapped=mapped;return a;}
void setup(){
 AnimationApi a{{p0,p1,p2,p3,p4,p5,p6,p7},thread};assert(gate.install(a));
 profile.registry=reinterpret_cast<uintptr_t>(f.registry);profile.indirect=false;
 for(unsigned i=0;i<8;++i){types[i]=reinterpret_cast<void*>(0x100+i);profile.phases[i].callback.rva=0x1000+i*0x100;
  uintptr_t callback=profile.phases[i].callback.rva;memcpy(f.registry+profile.phases[i].slot,&callback,sizeof(callback));
  f.entries.push_back({types[i],nullptr,profile.registry+profile.phases[i].slot,0,0,0});}
}
int main(int argc,char**argv){assert(argc==2);setup();std::string mode=argv[1];
 if(mode.rfind("route_",0)==0){
  AnimationRoutes routes;uintptr_t hooks[8]{};for(unsigned i=0;i<8;++i)hooks[i]=0x3000+i*0x100;
  if(mode=="route_readonly")route_write=false;
  if(mode=="route_race")route_race=true;
  if(mode=="route_duplicate")hooks[7]=hooks[0];
  if(mode=="route_indirect"){f.pointer=profile.registry;profile.registry=reinterpret_cast<uintptr_t>(&f.pointer);profile.indirect=true;}
  const bool expected=mode!="route_readonly"&&mode!="route_race"&&mode!="route_duplicate";
  assert(routes.install({route_mapped},profile,0,hooks)==expected);
  if(expected){
   assert(routes.ready()&&animation_loop_matches(api(),profile,0,types,routes.dispatch()));
   assert(!animation_loop_matches(api(),profile,0,types));
   assert(!routes.install({route_mapped},profile,0,hooks));
   if(mode=="route_foreign_write"){uintptr_t foreign=0x9999;memcpy(f.registry+profile.phases[3].slot,&foreign,sizeof foreign);assert(!routes.ready());}
   assert(routes.release()&&!routes.ready());
  }
  for(unsigned i=0;i<8;++i){uintptr_t actual=0;memcpy(&actual,f.registry+profile.phases[i].slot,sizeof actual);
   assert(actual==((i==3&&(mode=="route_race"||mode=="route_foreign_write"))?0x9999:profile.phases[i].callback.rva));}
  return 0;
 }
 if(mode.rfind("loop_",0)==0){
  bool expected=false;
  if(mode=="loop_valid")expected=true;
  if(mode=="loop_indirect"){f.pointer=profile.registry;profile.registry=reinterpret_cast<uintptr_t>(&f.pointer);profile.indirect=true;expected=true;}
  if(mode=="loop_duplicate")f.entries.push_back(f.entries[2]);
  if(mode=="loop_order")std::swap(f.entries[2],f.entries[4]);
  if(mode=="loop_missing")f.entries.erase(f.entries.begin()+3);
  if(mode=="loop_delegate")f.entries[2].delegate=reinterpret_cast<void*>(99);
  if(mode=="loop_condition")f.entries[2].condition=99;
  if(mode=="loop_children")f.entries[2].children=1;
  if(mode=="loop_slot")f.entries[2].update+=8;
  if(mode=="loop_callback"){uintptr_t x=0x9999;memcpy(f.registry+profile.phases[2].slot,&x,sizeof x);}
  if(mode=="loop_type_duplicate")types[2]=types[1];
  if(mode=="loop_type_missing")types[2]=nullptr;
  if(mode=="loop_foreign_slot")f.entries.push_back({reinterpret_cast<void*>(0x444),nullptr,f.entries[2].update,0,0,0});
  if(mode=="loop_foreign_callback"){uintptr_t cb=profile.phases[2].callback.rva;memcpy(f.registry+0x10,&cb,sizeof cb);f.entries.push_back({reinterpret_cast<void*>(0x444),nullptr,profile.registry+0x10,0,0,0});}
  if(mode=="loop_root_lost")f.root_live=false;
  assert(animation_loop_matches(api(),profile,0,types)==expected&&f.roots==0);return 0;
 }
 if(mode=="passive"){for(unsigned n=0;n<3;++n)for(unsigned i=0;i<8;++i)assert(gate.invoke(i));for(auto n:calls)assert(n==3);return 0;}
 assert(gate.acquire(7)&&gate.closed(7));
 if(mode=="closed"){for(unsigned i=0;i<8;++i)assert(!gate.invoke(i)&&!calls[i]);assert(gate.release(7));return 0;}
 if(mode=="wrong_tick"){assert(!gate.prepare(7,1)&&!gate.grant(7,1));assert(gate.closed(7));return 0;}
 assert(gate.prepare(7,0)&&gate.grant(7,0));
 if(mode=="original_throw"||mode=="begin_throw"){
  throw_phase=mode=="original_throw"?0:2;
  try{for(unsigned i=0;i<3;++i)gate.invoke(i);assert(false);}catch(int value){assert(value==17);}
  assert(!gate.healthy(7));
  if(mode=="begin_throw"){assert(!gate.release(7));assert(gate.invoke(4)&&calls[4]==1);}
  assert(gate.release(7));return 0;
 }
 if(mode=="revoke_before_phase"||mode=="revoke_pair"||mode=="revoke_foreign"){
  if(mode=="revoke_pair")for(unsigned i=0;i<3;++i)assert(gate.invoke(i));
  gate.revoke_grants(mode=="revoke_foreign"?8:7);
  if(mode=="revoke_foreign"){for(unsigned i=0;i<8;++i)assert(gate.invoke(i));assert(gate.closed(7));}
  else{
   for(unsigned i=0;i<8;++i){const bool expected=mode=="revoke_pair"&&i==4;assert(gate.invoke(i)==expected);}
   if(mode=="revoke_pair")assert(calls[2]==1&&calls[3]==0&&calls[4]==1);
   assert(gate.closed(7));
  }
  assert(gate.release(7));return 0;
 }
 if(mode=="partial_release"){for(unsigned i=0;i<3;++i)assert(gate.invoke(i));assert(!gate.release(7));assert(gate.invoke(3)&&gate.invoke(4));assert(gate.release(7));return 0;}
 if(mode=="misordered"){assert(gate.invoke(0));assert(!gate.invoke(2));assert(!gate.healthy(7));assert(gate.release(7));return 0;}
 if(mode=="pair_failure"){for(unsigned i=0;i<3;++i)assert(gate.invoke(i));assert(!gate.invoke(5));assert(!gate.healthy(7)&&!gate.release(7));assert(gate.invoke(4)&&calls[4]==1);assert(gate.release(7));return 0;}
 if(mode=="wrong_thread"){on_thread=false;assert(gate.invoke(0)&&calls[0]==1);on_thread=true;assert(!gate.healthy(7)&&gate.release(7)&&!gate.acquire(8));return 0;}
 if(mode=="reentered"){recursive=true;assert(gate.invoke(0));assert(calls[0]==1&&calls[1]==0&&!gate.healthy(7));assert(gate.release(7));return 0;}
 for(unsigned i=0;i<8;++i){assert(gate.invoke(i));assert(!gate.invoke(i));}
 assert(gate.closed(7));for(auto n:calls)assert(n==1);
 if(mode=="retry"){for(unsigned n=0;n<10;++n)for(unsigned i=0;i<8;++i)assert(!gate.invoke(i));for(auto n:calls)assert(n==1);return 0;}
 assert(!gate.grant(7,0)&&!gate.grant(7,2));assert(gate.prepare(7,1)&&gate.grant(7,1));
 for(unsigned i=0;i<8;++i){assert(gate.invoke(i));}
 assert(gate.closed(7));for(auto n:calls)assert(n==2);
 assert(!gate.release(8)&&gate.closed(7)&&gate.release(7));for(unsigned i=0;i<8;++i)assert(gate.invoke(i));
 for(auto n:calls){assert(n==3);}
 return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 compiler=shutil.which('c++')
 if not compiler:pytest.skip('Host C++ compiler required')
 d=tmp_path_factory.mktemp('mp4-animation-loop');s=d/'test.cpp';b=d/'test';s.write_text(HARNESS)
 r=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(s),'-o',str(b)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return b
@pytest.mark.parametrize('mode',['passive','closed','wrong_tick','partial_release','misordered','pair_failure','wrong_thread','reentered','retry','sequence','original_throw','begin_throw','revoke_before_phase','revoke_pair','revoke_foreign',
 'loop_valid','loop_indirect','loop_duplicate','loop_order','loop_missing','loop_delegate','loop_condition','loop_children','loop_slot','loop_callback','loop_type_duplicate','loop_type_missing','loop_foreign_slot','loop_foreign_callback','loop_root_lost','route_valid','route_readonly','route_race','route_duplicate','route_indirect','route_foreign_write'])
def test_production_phase_gate_and_typed_live_loop(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True);assert r.returncode==0,r.stderr

def test_profile_reproduces_from_whole_originals():
 originals=os.environ.get('IDOLY_MP4_ORIGINALS_DIR')
 if not originals:pytest.skip('Whole original binaries required')
 sys.path.insert(0,str(ROOT/'tools'))
 spec=importlib.util.spec_from_file_location('audit_mp4_animation_loop',ROOT/'tools/audit_mp4_animation_loop.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 profiles={p:module.build(Path(originals),p)for p in('android','ios')}
 assert module.render_scope(profiles)==(NATIVE/'mp4_engine_clock.hpp').read_text()
