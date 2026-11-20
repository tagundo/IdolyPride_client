"""Original frame-gap math plus real native scoped hook and restoration metadata."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_owned_camera_clock_rebases_once_and_mode_observations_survive_lru(tmp_path):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    begin=source.index('void mp4_core_camera_hook(')
    end=source.index('// END_MP4_OWNED_CLOCK_HOOKS',begin)
    hook=source[begin:end]
    code=r'''
#include "mp4_graph_modes.hpp"
#include "mp4_camera_clock.hpp"
#include <cassert>
#include <cstring>
using Method=const void;
namespace mp4game=idoly_mp4_game;
struct Vec3{float x,y,z;};
mp4game::CameraGrant mp4_camera_grant;bool mp4_owned_camera_scope=true,unity=true,status_available=true,lookup_broken=false;
int frame=100,original_calls=0;float advanced=0;unsigned char core[80]{},status[48]{};
bool game_call(){return unity;}
template<class T>T read(void* p,size_t off){T v;std::memcpy(&v,static_cast<char*>(p)+off,sizeof v);return v;}
template<class T>void write(void* p,size_t off,T v){std::memcpy(static_cast<char*>(p)+off,&v,sizeof v);}
int frame_count(Method*){return frame;}
struct {int(*frame_count)(Method*);}orientation_calls{frame_count};
void* mp4_camera_update_status(void*,void*){return status_available&&!lookup_broken?status:nullptr;}
void core_original(void*,void*,Vec3,float delta,Method*){
 ++original_calls;
 if(delta>=0)advanced+=delta*float(frame-read<int>(status,0x10));
 status_available=true;write(status,0x10,frame);
}
using Original=void(*)(void*,void*,Vec3,float,Method*);Original mp4_core_camera_original=core_original;
'''+hook+r'''
int main(){
 mp4game::GraphModes modes;mp4game::PlayableGraph owned{reinterpret_cast<void*>(1),7,0};assert(modes.record(owned,2));int restoration=0;assert(modes.get(owned,&restoration)&&restoration==2);
 for(uintptr_t i=2;i<140;++i){assert(modes.record({reinterpret_cast<void*>(i),1,0},1));}
 int mode=0;assert(!modes.get(owned,&mode));assert(restoration==2);assert(modes.record(owned,3));assert(modes.get(owned,&mode)&&mode==3);assert(!modes.get({owned.handle,8,0},&mode));
 write(core,0x38,int(1));write(status,0x10,int(10));void* camera=reinterpret_cast<void*>(9);mp4_camera_grant.begin();
 mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(original_calls==1&&advanced==.02f&&read<int>(status,0x10)==100&&mp4_camera_grant.ok());
 mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(original_calls==1&&advanced==.02f);
 frame=700;mp4_camera_grant.begin();mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(original_calls==2&&advanced==.04f&&mp4_camera_grant.ok());
 mp4_camera_grant.begin();status_available=false;frame=710;mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(original_calls==4&&advanced==.06f&&mp4_camera_grant.ok());
 mp4_camera_grant.begin();lookup_broken=true;mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(!mp4_camera_grant.ok()&&original_calls==5&&advanced==.06f);
 lookup_broken=false;mp4_owned_camera_scope=false;frame=720;mp4_core_camera_hook(core,camera,{0,1,0},.02f,nullptr);assert(original_calls==6&&advanced>.25f); // Original behavior outside owned scope remains unchanged.
 mp4_camera_grant.begin();for(uintptr_t i=1;i<=128;++i)assert(mp4_camera_grant.visit(reinterpret_cast<void*>(i))==mp4game::CameraGrant::Visit::first);assert(mp4_camera_grant.visit(reinterpret_cast<void*>(129))==mp4game::CameraGrant::Visit::failed&&!mp4_camera_grant.ok());
}
'''
    path=tmp_path/'clock.cpp';path.write_text(code);binary=tmp_path/'clock'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(path),'-o',str(binary)],check=True,capture_output=True,text=True)
    subprocess.run([str(binary)],check=True,capture_output=True,text=True)
