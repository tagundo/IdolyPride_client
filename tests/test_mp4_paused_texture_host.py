"""Compile the shipping original-RT host, including failed native construction."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def texture_host(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text[text.index('// BEGIN_MP4_PAUSED_TEXTURE_HOST'):text.index('// END_MP4_PAUSED_TEXTURE_HOST')]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <string>
#include <unordered_map>
namespace idoly_mp4_paused_frame {
enum class Result:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct Descriptor {int32_t width=0,height=0,samples=0,depth=0,mips=0,format=0,stencil=0,depth_stencil=0,dimension=0,shadow=0,vr=0,flags=0,memoryless=0;};
struct Texture{void*object=nullptr;uintptr_t native=0;Descriptor descriptor{};};
}
using Method=void;using D=idoly_mp4_paused_frame::Descriptor;
struct Obj{void*klass=nullptr;void*monitor=nullptr;uintptr_t native=0;D descriptor{};bool created=false,exact=true;};
Obj original{},fresh{};bool thread=true,create_ok=true,root_ok=true,throw_ctor=false,bad_width=false,mutate_native=false;int support=1,ctors=0,creates=0,copies=0,destroys=0;
std::unordered_map<uint32_t,void*> roots;uint32_t next_root=0;
bool mp4_actor_refresh_maps(){return true;}
bool game_call(){return thread;}struct{bool verified=true;}mp4_camera_host;
bool mp4_exact_type(void*p,const char*){return p&&static_cast<Obj*>(p)->exact;}
bool mp4_alive(void*p){return p&&static_cast<Obj*>(p)->native;}
template<class T>bool mp4_actor_field(void*p,uint32_t off,T&out){if(!p)return false;std::memcpy(&out,static_cast<uint8_t*>(p)+off,sizeof(T));return true;}
void*object_class(void*p){return static_cast<Obj*>(p)->klass;}
void*font_new(void*klass){assert(klass==original.klass);fresh={};fresh.klass=klass;return &fresh;}
uint32_t mp4_retain(void*p){if(!root_ok)return 0;roots[++next_root]=p;return next_root;}
void*weak_get(uint32_t t){auto i=roots.find(t);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t t){assert(roots.erase(t)==1);}
D descriptor(void*p,Method*){auto&o=*static_cast<Obj*>(p);D d=o.descriptor;if(mutate_native)++o.native;return d;}
bool created(void*p,Method*){return static_cast<Obj*>(p)->created;}
void ctor(void*p,D d,Method*){assert(p==&fresh);++ctors;fresh.native=202;fresh.descriptor=d;if(throw_ctor)throw std::runtime_error("ctor");}
bool create(void*p,Method*){assert(p==&fresh);++creates;fresh.created=create_ok;return create_ok;}
int32_t copy_support(Method*){return support;}
void copy(void*s,void*d,Method*){assert(s!=d&&static_cast<Obj*>(s)->created&&static_cast<Obj*>(d)->created);++copies;}
void destroy(void*p,bool allow,Method*){assert(p==&fresh&&!allow);++destroys;fresh.native=0;fresh.created=false;}
int32_t rt_width(void*p,Method*){return static_cast<Obj*>(p)->descriptor.width+(bad_width?1:0);}
int32_t rt_height(void*p,Method*){return static_cast<Obj*>(p)->descriptor.height;}
int32_t format(void*p,Method*){return static_cast<Obj*>(p)->descriptor.format;}
struct{int32_t(*texture_graphics_format)(void*,Method*)=format;}mp4_api;
struct{uintptr_t frame_rt_descriptor=reinterpret_cast<uintptr_t>(descriptor),frame_rt_created=reinterpret_cast<uintptr_t>(created),frame_rt_ctor=reinterpret_cast<uintptr_t>(ctor),frame_rt_create=reinterpret_cast<uintptr_t>(create),frame_copy_support=reinterpret_cast<uintptr_t>(copy_support),frame_copy=reinterpret_cast<uintptr_t>(copy),object_destroy_immediate=reinterpret_cast<uintptr_t>(destroy);}mp4_cam_profile;
template<class F>F mp4_cam_call(uintptr_t binding){return reinterpret_cast<F>(binding);}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 D d{};d.width=256;d.height=144;d.samples=d.depth=d.mips=1;d.format=8;d.dimension=2;
 original.klass=reinterpret_cast<void*>(1);original.native=101;original.created=true;original.descriptor=d;
 mp4frame::Texture source{};assert(mp4_paused_texture_read(&original,&source));
 if(mode=="derived")original.exact=false;
 if(mode=="uncreated")original.created=false;
 if(mode=="dimension_mismatch")bad_width=true;
 if(mode=="identity_swap")mutate_native=true;
 if(mode=="off_thread")thread=false;
 if(mode=="missing_format_api")mp4_api.texture_graphics_format=nullptr;
 if(mode=="derived"||mode=="uncreated"||mode=="dimension_mismatch"||mode=="identity_swap"||mode=="off_thread"||mode=="missing_format_api"){
  mp4frame::Texture out{};assert(!mp4_paused_texture_read(&original,&out)&&!out.object&&!out.native);return 0;
 }
 Mp4PausedTextureStorage storage{};mp4frame::Texture backup{};
 if(mode=="root_failure")root_ok=false;
 if(mode=="create_failure")create_ok=false;
 if(mode=="constructor_exception")throw_ctor=true;
 mp4frame::Result result=mp4frame::Result::failed;
 try{result=mp4_paused_texture_allocate(storage,&original,d,&backup);}catch(const std::runtime_error&){assert(mode=="constructor_exception");}
 if(mode=="root_failure"||mode=="create_failure"||mode=="constructor_exception"){
  assert(result==mp4frame::Result::failed&&backup.object==&fresh&&storage.object==&fresh);
  assert(mp4_paused_texture_destroy(storage,backup)&&!backup.object&&roots.empty());
  assert(destroys==(mode=="root_failure"?0:1));return 0;
 }
 assert(result==mp4frame::Result::ok&&ctors==1&&creates==1&&backup.object==&fresh&&backup.native==202);
 assert(mp4_paused_texture_allocate(storage,&original,d,&source)==mp4frame::Result::unsupported);
 assert(mp4_paused_texture_read(&original,&source));
 if(mode=="missing_basic")support=0;
 if(mode=="format_mismatch")++backup.descriptor.format;
 if(mode=="native_mismatch")++backup.native;
 if(mode=="missing_basic"||mode=="format_mismatch"||mode=="native_mismatch")assert(!mp4_paused_texture_copy_supported(source,backup)&&!copies);
 else{assert(mp4_paused_texture_copy_supported(source,backup));mp4_paused_texture_copy_original(source.object,backup.object);assert(copies==1);}
 if(mode=="foreign_private_native"){fresh.native=303;assert(!mp4_paused_texture_destroy(storage,backup)&&!destroys&&roots.size()==1);fresh.native=202;}
 assert(mp4_paused_texture_destroy(storage,backup)&&destroys==1&&roots.empty());
 assert(mp4_paused_texture_destroy(storage,backup)&&destroys==1);
}
'''
    folder=tmp_path_factory.mktemp('paused-texture');src=folder/'test.cpp';binary=folder/'test';src.write_text(prefix+actual+driver)
    proc=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(src),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stdout+proc.stderr
    return binary
@pytest.mark.parametrize('mode',['normal','derived','uncreated','dimension_mismatch','identity_swap','off_thread','missing_format_api','root_failure','create_failure','constructor_exception','missing_basic','format_mismatch','native_mismatch','foreign_private_native'])
def test_actual_original_texture_host(texture_host,mode):
    p=subprocess.run([str(texture_host),mode],capture_output=True,text=True,timeout=5)
    assert p.returncode==0,p.stdout+p.stderr
