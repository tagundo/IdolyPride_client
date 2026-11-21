"""Production empty-world admission and whole fixed-subtree lease checks.

Callbacks provide synthetic typed objects; no Unity PlayerLoop/GPU is claimed.
The original native condition/registry instructions are tested separately below.
"""
from pathlib import Path
import importlib.util,json,os,shutil,subprocess,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <vector>
#include <string>
#include <cassert>
using namespace idoly_mp4_world;
struct Arr{std::vector<void*>items;std::vector<LoopEntry>loops;bool is_loop=false;};
struct Cloth{bool live=true,enabled=false;} cloth_item;
struct Fixture{
 alignas(8) unsigned char manager[128]{},buckets[16*24]{},info[8][80]{};
 char names[8][40]{};Arr families[4],loop;
 bool source=true,held=true,actors=true,normal=true,routes=true,thread=true,lookup_bad=false;
 unsigned calls=0,root_count=0;void*roots[64]{};
} f;
FixedGate gate;
template<class T>void put(void*p,size_t at,T v){memcpy(static_cast<unsigned char*>(p)+at,&v,sizeof v);}
template<class T>T get(const void*p,size_t at){T v{};memcpy(&v,static_cast<const unsigned char*>(p)+at,sizeof v);return v;}
bool contains(uintptr_t a,size_t n,const void*p,size_t len){const uintptr_t b=reinterpret_cast<uintptr_t>(p);return a>=b&&n<=len&&a-b<=len-n;}
bool mapped(uintptr_t a,size_t n){
 if(!a||!n)return false;
 if(contains(a,n,f.manager,sizeof f.manager)||contains(a,n,f.buckets,sizeof f.buckets)
 ||contains(a,n,f.info,sizeof f.info)||contains(a,n,f.names,sizeof f.names))return true;
 for(auto&x:f.families)if(contains(a,n,x.items.data(),x.items.size()*sizeof(void*)))return true;
 return contains(a,n,f.loop.loops.data(),f.loop.loops.size()*sizeof(LoopEntry));
}
bool source(void*c){++f.calls;return c==&f&&f.source;}
bool held(void*){return f.held;}
bool actors(void*){return f.actors;}
bool normal(void*){return f.normal;}
bool routes(){return f.routes&&gate.installed();}
bool type(void*p,const char*n){if(!strcmp(n,"System.Array")){for(auto&a:f.families)if(p==&a)return true;return p==&f.loop;}return p==&cloth_item&&!strcmp(n,"UnityEngine.Cloth");}
bool alive(void*p){return p==&cloth_item&&cloth_item.live;}
uint32_t retain(void*p){for(unsigned i=0;i<64;++i)if(!f.roots[i]){f.roots[i]=p;++f.root_count;return i+1;}return 0;}
void*retained(uint32_t i){return i&&i<=64?f.roots[i-1]:nullptr;}
void free_root(uint32_t i){assert(i&&i<=64&&f.roots[i-1]);f.roots[i-1]=nullptr;--f.root_count;}
size_t length(void*p){auto*a=static_cast<Arr*>(p);return a->is_loop?a->loops.size():a->items.size();}
void*data(void*p){auto*a=static_cast<Arr*>(p);return a->is_loop?static_cast<void*>(a->loops.data()):static_cast<void*>(a->items.data());}
void*find(void*t,bool inactive,Method*){assert(!inactive);auto n=reinterpret_cast<uintptr_t>(t);assert(n>=1&&n<=4);return &f.families[n-1];}
void*current_loop(Method*){return &f.loop;}
bool enabled(void*p,Method*){assert(p==&cloth_item);return cloth_item.enabled;}
void*native_registry(){return f.manager;}
const void*native_type(int32_t id){
 if(f.lookup_bad&&id==54)return f.info[1];
 for(size_t i=0;i<16;++i){auto*p=f.buckets+i*24;if(get<uint32_t>(p,0)<0xfffffffeu&&get<uint32_t>(p,8)==uint32_t(id))return reinterpret_cast<void*>(get<uintptr_t>(p,16));}return nullptr;
}
bool owner_thread(){return f.thread;}
bool original(){++f.calls;return true;}
void row(unsigned i,uint32_t id,const char*name){assert(i<8);strcpy(f.names[i],name);put(f.info[i],16,reinterpret_cast<uintptr_t>(f.names[i]));put(f.info[i],40,id);put(f.buckets+i*24,0,uint32_t(0x100+i*4));put(f.buckets+i*24,8,id);put(f.buckets+i*24,16,reinterpret_cast<uintptr_t>(f.info[i]));}
Api api(){Api a{};a.source_current=source;a.clock_held=held;a.actor_jobs_closed=actors;a.normal_animation_closed=normal;
 a.routes_ready=routes;a.mapped=mapped;a.is_type=type;a.alive=alive;a.retain=retain;a.retained=retained;a.release_root=free_root;
 a.array_length=length;a.array_data=data;a.find_objects=find;a.current_loop=current_loop;a.cloth_enabled=enabled;
 a.native_registry=native_registry;a.native_type=native_type;a.rigidbody_type=reinterpret_cast<void*>(1);a.rigidbody2d_type=reinterpret_cast<void*>(2);
 a.cloth_type=reinterpret_cast<void*>(3);a.character_controller_type=reinterpret_cast<void*>(4);a.fixed_update_type=reinterpret_cast<void*>(5);return a;}
void setup(){
 for(size_t i=0;i<16;++i)put(f.buckets+i*24,0,uint32_t(0xffffffff));
 row(0,54,"Rigidbody");row(1,50,"Rigidbody2D");row(2,183,"Cloth");row(3,143,"CharacterController");
 put(f.manager,64,reinterpret_cast<uintptr_t>(f.buckets));put(f.manager,72,uint32_t(15*8));put(f.manager,76,uint32_t(4));put(f.manager,80,uint32_t(12));
 f.loop.is_loop=true;
 f.loop.loops={{reinterpret_cast<void*>(100),nullptr,0,0,2,0},
  {reinterpret_cast<void*>(5),nullptr,0,0x3330,1,0},
  {reinterpret_cast<void*>(101),reinterpret_cast<void*>(500),0,0,0,0},
  {reinterpret_cast<void*>(102),nullptr,0,0,0,0}};
 assert(gate.install({original,owner_thread}));
}
int main(int argc,char**argv){assert(argc==2);setup();std::string mode=argv[1];Scope s;
 if(mode=="valid"){
  assert(s.admit(api(),&f,0x3330)==Result::ok&&!s.active());
  assert(gate.native_condition());const unsigned before=f.calls;
  assert(s.configure(api(),&gate,&f,1,0x3330));assert(s.quiesce()==Result::ok&&s.capture()==Result::ok);
  assert(s.active()&&!gate.native_condition()&&f.calls>=before);assert(s.validate()==Result::ok&&s.restorable());
  assert(s.prepare()==Result::ok&&s.reset()==Result::ok&&s.restore()==Result::ok);assert(s.release(true)==Result::ok&&!s.active());
  assert(gate.native_condition()&&!gate.healthy(1));
 }else if(mode=="not_held"){
  f.held=false;assert(s.configure(api(),&gate,&f,2,0x3330));assert(s.quiesce()==Result::waiting&&!s.active());assert(gate.native_condition());
 }else if(mode=="foreign_lease"){
  assert(gate.acquire(99));assert(s.configure(api(),&gate,&f,2,0x3330));assert(s.capture()==Result::unsupported&&!s.active());s.release(false);assert(gate.healthy(99));gate.release(99);
 }else if(mode=="wrong_thread"){
  assert(s.configure(api(),&gate,&f,3,0x3330)&&s.capture()==Result::ok);f.thread=false;assert(gate.native_condition());f.thread=true;
  assert(s.validate()==Result::stale&&!s.restorable());s.release(false);assert(!gate.acquire(4));
 }else if(mode=="source_lost_release"){
  assert(s.configure(api(),&gate,&f,4,0x3330)&&s.capture()==Result::ok);f.source=false;assert(s.validate()==Result::stale);
  const unsigned n=f.calls;assert(s.release(false)==Result::ok&&f.calls==n);assert(gate.native_condition());
 }else if(mode=="source_not_current"){
  f.source=false;assert(s.admit(api(),&f,0x3330)==Result::stale);
 }else if(mode=="missing_api"){
  auto a=api();a.native_type=nullptr;assert(s.admit(a,&f,0x3330)==Result::unsupported);
 }else if(mode=="missing_route"){
  f.routes=false;assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="actors_unowned"||mode=="animation_fixed"){
  if(mode=="actors_unowned")f.actors=false;else f.normal=false;assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="disabled_cloth"){
  f.families[2].items={&cloth_item};assert(s.admit(api(),&f,0x3330)==Result::ok);
 }else if(mode=="cloth_active"||mode=="cloth_destroyed"){
  f.families[2].items={&cloth_item};cloth_item.enabled=true;cloth_item.live=mode!="cloth_destroyed";
  assert(s.admit(api(),&f,0x3330)==(cloth_item.live?Result::unsupported:Result::stale));
 }else if(mode=="rigidbody"||mode=="rigidbody2d"||mode=="character_controller"){
  f.families[mode=="rigidbody"?0:mode=="rigidbody2d"?1:3].items={reinterpret_cast<void*>(42)};assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="articulation_id"||mode=="articulation_name"){
  row(4,mode=="articulation_id"?171741748u:900u,mode=="articulation_name"?"ArticulationBody":"OtherNativeClass");put(f.manager,76,uint32_t(5));put(f.manager,80,uint32_t(11));
  assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="registry_count"||mode=="registry_mask"||mode=="registry_status"||mode=="registry_anchor"||mode=="registry_lookup"){
  if(mode=="registry_count")put(f.manager,76,uint32_t(5));
  if(mode=="registry_mask")put(f.manager,72,uint32_t(0xffffffff));
  if(mode=="registry_status")put(f.buckets,0,uint32_t(1));
  if(mode=="registry_anchor")strcpy(f.names[0],"DifferentType");
  if(mode=="registry_lookup")f.lookup_bad=true;
  assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="condition_changed"||mode=="root_delegate"||mode=="root_update"||mode=="fixed_missing"||mode=="tree_extra"||mode=="tree_short"){
  if(mode=="condition_changed")f.loop.loops[1].condition=0x4440;
  if(mode=="root_delegate")f.loop.loops[1].delegate=reinterpret_cast<void*>(2);
  if(mode=="root_update")f.loop.loops[1].update=0x4440;
  if(mode=="fixed_missing")f.loop.loops[1].type=reinterpret_cast<void*>(3);
  if(mode=="tree_extra")f.loop.loops[0].children=1;
  if(mode=="tree_short")f.loop.loops[1].children=4;
  assert(s.admit(api(),&f,0x3330)==Result::unsupported);
 }else if(mode=="registry_changed"||mode=="dynamic_appeared"||mode=="loop_changed"){
  assert(s.configure(api(),&gate,&f,5,0x3330)&&s.capture()==Result::ok);
  if(mode=="registry_changed"){row(4,999,"NewType");put(f.manager,76,uint32_t(5));put(f.manager,80,uint32_t(11));}
  if(mode=="dynamic_appeared")f.families[0].items={reinterpret_cast<void*>(42)};
  if(mode=="loop_changed")f.loop.loops[1].condition=0x4440;
  assert(s.validate()!=Result::ok&&!s.restorable());s.release(false);
 }else return 2;
 assert(f.root_count==0);return 0;
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
 c=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
 if not c:pytest.skip('C++ compiler required')
 p=tmp_path_factory.mktemp('world-scope');s=p/'world.cpp';s.write_text(HARNESS);b=p/'world'
 r=subprocess.run([c,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(s),'-o',str(b)],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
 return b
MODES=['valid','not_held','foreign_lease','wrong_thread','source_lost_release','source_not_current','missing_api','missing_route','actors_unowned','animation_fixed','disabled_cloth','cloth_active','cloth_destroyed','rigidbody','rigidbody2d','character_controller','articulation_id','articulation_name','registry_count','registry_mask','registry_status','registry_anchor','registry_lookup','condition_changed','root_delegate','root_update','fixed_missing','tree_extra','tree_short','registry_changed','dynamic_appeared','loop_changed']
@pytest.mark.parametrize('mode',MODES)
def test_actual_world_scope_and_fixed_gate(binary,mode):
 r=subprocess.run([str(binary),mode],capture_output=True,text=True,timeout=5);assert r.returncode==0,r.stdout+r.stderr

def generator():
 sys.path.insert(0,str(ROOT/'tools'));spec=importlib.util.spec_from_file_location('world_generator',ROOT/'tools/audit_mp4_world.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_embedded_world_profile_reproduces_from_whole_originals(tmp_path):
 originals=os.environ.get('IDOLY_MP4_ORIGINALS_DIR')
 if not originals:pytest.skip('Whole-original world profile regeneration requires pinned inputs')
 m=generator();p={pl:m.build(Path(originals),pl)for pl in('android','ios')}
 assert m.render_scope(p)==(NATIVE/'mp4_engine_clock.hpp').read_text()
