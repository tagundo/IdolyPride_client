"""Concrete source-host callbacks preserve partial births across handoff.

The C++ fixture substitutes actual engine APIs, never GPU execution proof.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def host(tmp_path_factory):
    cc=shutil.which('c++')
    if not cc:pytest.skip('C++ compiler required')
    header=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    bank=header[header.index('// BEGIN_MP4_CAPTURE_PRODUCTION_BANK'):header.index('// END_MP4_CAPTURE_PRODUCTION_BANK')]
    guard=header[header.index('// BEGIN_MP4_CAPTURE_PUBLICATION_GUARD'):header.index('// END_MP4_CAPTURE_PUBLICATION_GUARD')]
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    begin='// BEGIN_MP4_CAPTURE_PRODUCTION_HOST';end='// END_MP4_CAPTURE_PRODUCTION_HOST'
    assert begin in bridge and end in bridge, 'Concrete production host must ship in the actual bridge'
    body=bridge[bridge.index(begin):bridge.index(end)+len(end)]
    source=r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <string>
#include <unordered_map>
#include <vector>
#include <stdexcept>
using Method=void;
'''+bank+guard+r'''
namespace mp4production=idoly_mp4_capture_production;
struct Obj{alignas(16) uint8_t bytes[512]{};std::string type;};
Obj controller,camera,target,target_rt,original,private_wrapper,private_rt,name,foreign;
std::unordered_map<void*,Obj*>objects;std::unordered_map<uint32_t,void*>roots;uint32_t root_serial=0;
std::vector<uint32_t>sink_roots;mp4production::Descriptor descriptor{};
bool thread_ok=true,current_ok=true,held=true,pending=true,adopt_ok=true,fail_root=false,fresh_maps=true;
bool program_ok=true;
int refreshes=0,source_reads=0,setter_calls=0;uint64_t actual_request=13;
void*ref(Obj&o){return o.bytes;}
template<class T>void put(Obj&o,size_t at,T value){std::memcpy(o.bytes+at,&value,sizeof value);}
bool game_call(){return thread_ok;}
bool mp4_exact_type(void*p,const char*t){auto i=objects.find(p);return i!=objects.end()&&i->second->type==t;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){
 if(p==ref(controller))++source_reads;
 if(p==ref(private_rt)&&at==16&&!fresh_maps)return false;
 auto i=objects.find(p);if(i==objects.end()||at+sizeof out>512)return false;std::memcpy(&out,i->second->bytes+at,sizeof out);return true;}
bool mp4_alive(void*p){uintptr_t n=0;return mp4_actor_field(p,16,n)&&n;}
bool mp4_actor_refresh_maps(){++refreshes;fresh_maps=true;return true;}
bool mp4_actor_mapped(void*,size_t,bool){return true;}
uint32_t mp4_retain(void*p){if(!p||fail_root)return 0;roots[++root_serial]=p;return root_serial;}
void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4SceneWitness{uint64_t generation=0;void*controller=nullptr,*camera=nullptr;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.controller==b.controller&&a.camera==b.camera;}
struct{bool active=true,invalidated=false,releasing=false;unsigned configured=15,all=15;Mp4SceneWitness source{};}mp4_scene_host;
struct{bool verified=true;}mp4_camera_host;
bool mp4_scene_source_current(){return current_ok;}
namespace idoly_mp4_runtime{
 struct{uint64_t generation=9;bool automatic=true;}job;
 struct Clock{bool held(){return ::held;}}clock;Clock&native_clock_scope(){return clock;}
 struct Game{
  bool owned_capture_request(void*c,uint64_t r){return pending&&current_ok&&c==ref(controller)&&r==actual_request;}
  uint64_t owned_capture_request_serial(void*c){return owned_capture_request(c,actual_request)?actual_request:0;}
 }game;
}
mp4production::Descriptor get_descriptor(void*p,Method*){assert(p==ref(target_rt));return descriptor;}
void dynamic_scale(mp4production::Descriptor*d,bool on,Method*){assert(!on);++setter_calls;d->fields[11]&=~0x400;}
uintptr_t image_base=16;
namespace idoly_mp4_capture_publication{
 struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};
 struct Profile{Binding descriptor_dynamic_scale{};uintptr_t wrapper_return=0x1234,texture_return=0x5678,original_return=0x9998;};
 Profile make_profile(){Profile p{};p.descriptor_dynamic_scale.rva=reinterpret_cast<uintptr_t>(dynamic_scale)-image_base;
  std::memcpy(p.descriptor_dynamic_scale.prefix,reinterpret_cast<void*>(dynamic_scale),16);return p;}
 const Profile android_profile=make_profile();
}
struct{struct{uintptr_t rva=reinterpret_cast<uintptr_t>(get_descriptor)-image_base;}frame_rt_descriptor;}mp4_cam_profile;
bool adopt(void*,const mp4production::Resource&r){if(!adopt_ok)return false;sink_roots.push_back(mp4_retain(r.wrapper));if(r.texture)sink_roots.push_back(mp4_retain(r.texture));return true;}
bool program(void*p,uint64_t epoch,uint64_t job){assert(p==&program_ok&&epoch==7&&job==9);return program_ok;}
void setup(){for(auto pair:{std::pair<Obj*,const char*>{&controller,"VL.Rendering.VLSRPCameraController"},{&camera,"UnityEngine.Camera"},{&target,"VL.VLRenderTexture"},{&target_rt,"UnityEngine.RenderTexture"},{&original,"VL.VLRenderTexture"},{&private_wrapper,"VL.VLRenderTexture"},{&private_rt,"UnityEngine.RenderTexture"},{&name,"System.String"},{&foreign,"UnityEngine.Camera"}}){pair.first->type=pair.second;objects[ref(*pair.first)]=pair.first;}
 put(controller,16,uintptr_t(1001));put(camera,16,uintptr_t(1002));put(target_rt,16,uintptr_t(101));
 put(controller,80,ref(camera));put(controller,152,ref(target));put(controller,160,ref(original));put(target,16,ref(target_rt));
 constexpr char text[]="_VLCapturedTexture";put(name,16,int32_t(sizeof(text)-1));for(size_t i=0;i<sizeof(text)-1;++i)put(name,20+i*2,uint16_t(text[i]));
 descriptor.fields[0]=1920;descriptor.fields[1]=1080;descriptor.fields[2]=descriptor.fields[3]=descriptor.fields[4]=1;descriptor.fields[11]=0xc01;
 mp4_scene_host.source={7,ref(controller),ref(camera)};
}
'''+body+r'''
int main(int argc,char**argv){assert(argc==2);setup();std::string mode=argv[1];Mp4CaptureProductionHost h;
 if(mode=="missing_frontend"){assert(!mp4_capture_production_bind(h,mp4_scene_host.source,9,&h,adopt,false)&&roots.empty());return 0;}
 if(mode=="missing_retirement"){assert(!mp4_capture_production_bind(h,mp4_scene_host.source,9,nullptr,adopt,true)&&roots.empty());return 0;}
 if(mode=="source_not_current")current_ok=false;
 if(mode=="root_failure")fail_root=true;
 const bool bound=mp4_capture_production_bind(h,mp4_scene_host.source,9,&h,adopt,true);
 if(mode=="source_not_current"||mode=="root_failure"){assert(!bound&&roots.empty()&&!mp4_capture_production_active_bank());return 0;}
 assert(bound&&roots.size()==4&&mp4_capture_production_active_bank()==&h.bank);
 assert(mp4_capture_production_request(ref(controller))==13&&mp4_capture_production_request(ref(foreign))==0);
 if(mode=="foreign_thread"){thread_ok=false;assert(!mp4_capture_production_active_bank());mp4_capture_production_foreign();thread_ok=true;
  assert(mp4_capture_production_active_bank()==&h.bank&&!mp4_capture_production_current(&h,7,9)&&mp4_capture_production_request(ref(controller))==0);
  assert(mp4_capture_production_transfer_all(h)&&mp4_capture_production_finish(h)&&roots.empty());return 0;}
 const bool publication=mode.rfind("publication_",0)==0;
 idoly_mp4_capture_publication::Request publication_scope;
 if(publication){
  const bool missing=mode=="publication_missing_provider";
  assert(mp4_capture_production_publication_bind(h,57,&program_ok,missing?nullptr:program,true)==!missing);
  mp4_capture_publication_enter(publication_scope,ref(controller),13);
  if(!missing)assert(!mp4_capture_production_transfer_all(h)&&!mp4_capture_production_finish(h));
 }
 auto d=descriptor;d.fields[11]&=~0x400;
 if(mode=="bad_descriptor")++d.fields[1];
 if(mode=="bad_name")put(name,20,uint16_t('x'));
 if(mode=="target_changed")put(controller,152,ref(original));
 {
  auto update=h.bank.update(ref(controller),13);
  {
   auto wrapper=h.bank.wrapper(ref(private_wrapper),&d,ref(name),image_base+0x1234);
   if(mode=="bad_descriptor"||mode=="bad_name"||mode=="target_changed"){
    assert(!wrapper.owned()&&!h.bank.count());assert(!wrapper.finish(false));update.finish(false);
    assert(mp4_capture_production_transfer_all(h)&&mp4_capture_production_finish(h)&&roots.empty());return 0;
   }
   assert(wrapper.owned()&&setter_calls);
   {
    auto texture=h.bank.texture(ref(private_rt),&d,image_base+0x5678);assert(texture.owned());
    put(private_rt,16,mode=="partial_native_zero"?uintptr_t(0):uintptr_t(202));fresh_maps=false;
    const int before=refreshes;assert(texture.finish(mode!="partial_ctor"&&mode!="partial_native_zero"));assert(refreshes==before+1&&fresh_maps);
   }
   put(private_wrapper,16,ref(private_rt));assert(wrapper.finish(mode!="partial_ctor"&&mode!="partial_native_zero"));
  }
  if(mode!="partial_ctor"&&mode!="partial_native_zero")put(controller,160,ref(private_wrapper));
  if(publication&&mode=="publication_unowned_nested"){
   idoly_mp4_capture_publication::Request inner;mp4_capture_publication_enter(inner,ref(foreign),0);
   assert(!idoly_mp4_capture_publication::Request::suppress(57,ref(private_rt),image_base+0x9998));
   const auto receipt=inner.finish();mp4_capture_publication_complete(ref(foreign),0,receipt,true);
  }
  if(publication){
   const bool expected=mode!="publication_missing_provider"&&mode!="publication_missing_native";
   const bool suppressed=mode!="publication_missing_native"&&idoly_mp4_capture_publication::Request::suppress(57,ref(private_rt),image_base+0x9998);
   assert(suppressed==expected);
  }
  assert(update.finish(mode!="update_body_failure"));
 }
 if(publication){
  const auto receipt=publication_scope.finish();const bool returned=mode!="publication_body_failure";
  if(mode=="publication_handoff")current_ok=false;
  const int before=source_reads;
  mp4_capture_publication_complete(ref(controller),13,receipt,returned);
  if(mode=="publication_handoff")assert(source_reads==before);
  const bool expected=returned&&mode!="publication_missing_provider"&&mode!="publication_missing_native"&&mode!="publication_handoff";
  assert(mp4_capture_publication_completed(h,13)==expected&&!mp4_capture_publication_completed(h,14));
  if(mode=="publication_reuse"){
   actual_request=14;idoly_mp4_capture_publication::Request reuse;
   mp4_capture_publication_enter(reuse,ref(controller),14);
   {auto update=h.bank.update(ref(controller),14);assert(update.owned()&&update.finish(true));}
   const auto reused=reuse.finish();assert(reused.valid&&!reused.suppressed);
   mp4_capture_publication_complete(ref(controller),14,reused,true);
   assert(mp4_capture_publication_completed(h,14)&&!mp4_capture_publication_completed(h,13));
  }
 }
 const bool partial=mode=="partial_ctor"||mode=="partial_native_zero";
 assert(mp4_capture_production_produced(&h,7,9,ref(private_wrapper),ref(private_rt),202)==!partial);
 if(mode=="historical_root_lost"){
  mp4production::Resource resource{};assert(h.bank.historical(0,&resource));roots[resource.texture_root]=ref(foreign);
  assert(!mp4_capture_production_transfer_all(h)&&!mp4_capture_production_finish(h)&&roots.size()==6);return 0;
 }
 if(mode=="handoff"){current_ok=false;pending=false;put(controller,152,ref(original));const int reads=source_reads;
  assert(mp4_capture_production_produced(&h,7,9,ref(private_wrapper),ref(private_rt),202));
  assert(mp4_capture_production_transfer_all(h)&&source_reads==reads);
 }else{
  if(mode=="retirement_wait"){adopt_ok=false;assert(!mp4_capture_production_transfer_all(h)&&roots.size()==6&&!mp4_capture_production_finish(h));adopt_ok=true;}
  assert(mp4_capture_production_transfer_all(h));
 }
 assert(mp4_capture_production_transfer_all(h));assert(mp4_capture_production_finish(h)&&!mp4_capture_production_active_bank());
 for(auto root:sink_roots)weak_free(root);
 assert(roots.empty());
}
'''
    folder=tmp_path_factory.mktemp('capture-production-host');cpp=folder/'test.cpp';binary=folder/'test';cpp.write_text(source)
    p=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined','-fno-pie','-no-pie',str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=50)
    assert p.returncode==0,p.stdout+p.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','missing_frontend','missing_retirement','source_not_current','root_failure',
    'foreign_thread','bad_descriptor','bad_name','target_changed','partial_ctor','partial_native_zero',
    'update_body_failure','handoff','retirement_wait','publication_normal','publication_unowned_nested',
    'publication_missing_provider','publication_missing_native','publication_body_failure',
    'publication_handoff','publication_reuse','historical_root_lost'])
def test_actual_production_host_receipts_and_cleanup(host,mode):
    p=subprocess.run([str(host),mode],capture_output=True,text=True,timeout=6)
    assert p.returncode==0,p.stdout+p.stderr
