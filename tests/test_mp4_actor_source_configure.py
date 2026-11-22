"""Execute the real configure function: source plans cannot capture native images."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_source_configure_defers_native_animation_image():
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    start = source.index('bool mp4_actor_configure_context(bool source_only=false)')
    end = source.index('\nmp4actor::Result mp4_actor_quiesce', start)
    actual = source[start:end]
    prefix = r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
struct Model {bool selected=true,routes=true,maps=true,configured=true,presentation=true,bind=true,current=true,captured=false,capture_ok=true;int captures=0,currents=0,configures=0; } m;
namespace mp4actor {struct Owner {void *actor=nullptr,*extension=nullptr,*rig=nullptr,*builder=nullptr,*animator=nullptr;int playable=0,output=0,graph=0;};}
struct StateApi{bool node_supported=true;};
struct Scope {bool live=false,bound=false;bool active(){return live;}bool presentation_bound(){return bound;}bool configure(StateApi,void*,mp4actor::Owner*,size_t,void*,uint64_t,int,uint32_t){++m.configures;live=m.configured;return live;}template<class T>bool bind_presentation(T*){bound=m.bind;return bound;}};
struct Host {Scope scope;void *player=nullptr,*presenter=nullptr,*director=nullptr;uint64_t epoch=0;bool invalidated=false,restoration_verified=false;uint32_t roots[3]{};size_t count=0;mp4actor::Owner owners[32]{};const char*error=nullptr;}mp4_actor_host;
struct Presentation{bool live=false;bool configure(int,void*,void*,uint64_t){live=m.presentation;return live;}bool active(){return live;}bool release(bool){live=false;return true;}}mp4_actor_presentation_scope;
int mp4_actor_gate=0,mp4_actor_mono_gate=0,mp4_actor_foot_apply_original=0;
void*player=reinterpret_cast<void*>(1),*presenter=reinterpret_cast<void*>(2),*director=reinterpret_cast<void*>(3),*controller=reinterpret_cast<void*>(4),*binder=reinterpret_cast<void*>(5),*list=reinterpret_cast<void*>(6),*actor=reinterpret_cast<void*>(7),*extension=reinterpret_cast<void*>(8),*builder=reinterpret_cast<void*>(9),*animation=reinterpret_cast<void*>(10);void*actors[]={actor};void*extensions[]={extension};
namespace mp4game{struct Layout {size_t player_director_controller=1,controller_master=2,player_binder=3,binder_actors=4;};}
struct Fields {size_t actor_extensions=5,extension_rig=6,extension_builder=7,actor_animator=8,builder_playable=9,builder_output=10,actor_player=11,player_graph=12;};struct{Fields fields;}mp4_actor_profile;
namespace idoly_mp4_runtime {struct{void*selected_player(){return player;}void*selected_presenter(){return presenter;}uint64_t owned_scene_generation(){return 17;}}game;struct{uint64_t generation=0;bool automatic=false;struct{uint32_t fps_num=60;}options;}job;bool busy_stage(){return false;}}
namespace idoly_mp4_output{uint32_t simulation_hz(uint32_t f){return f;}}
bool mp4_persistent_animation_captured(){return m.captured;}bool mp4_persistent_animation_current(){++m.currents;return m.current;}bool mp4_persistent_animation_capture(){++m.captures;if(m.capture_ok)m.captured=true;return m.capture_ok;}
bool mp4_actor_selected_source(void*){return m.selected;}bool mp4_actor_routes(void*){return m.routes;}bool mp4_actor_refresh_maps(){return m.maps;}
bool mp4_actor_field(void*p,size_t at,void*&v){if(p==player&&at==1)v=controller;else if(p==controller&&at==2)v=director;else if(p==player&&at==3)v=binder;else if(p==binder&&at==4)v=list;else if(p==actor&&at==5)v=list;else if(p==extension&&at==6)v=actor;else if(p==extension&&at==7)v=builder;else if(p==actor&&at==8)v=actor;else if(p==actor&&at==11)v=animation;else return false;return true;}
bool mp4_actor_field(void*p,size_t at,int&v){if((p==builder&&(at==9||at==10))||(p==animation&&at==12)){v=1;return true;}return false;}
bool mp4_actor_list(void*,void***v,size_t*n,size_t limit){*n=1;*v=limit==32?actors:extensions;return true;}
bool mp4_type_is(void*p,const char*n){return (p==binder&&!std::strcmp(n,"Solis.Common.Live.SolisLiveBinder"))||(p==actor&&!std::strcmp(n,"VL.Core.VLActorController"))||(p==extension&&!std::strcmp(n,"VL.VLActorActorSwing"));}
bool mp4_alive(void*){return true;}uint32_t mp4_retain(void*p){return static_cast<uint32_t>(reinterpret_cast<uintptr_t>(p));}void*weak_get(uint32_t r){return reinterpret_cast<void*>(static_cast<uintptr_t>(r));}bool mp4_actor_owner(void*,mp4actor::Owner&){return true;}StateApi mp4_actor_state_api(){return {};}int mp4_actor_presentation_api(int){return 0;}
'''
    driver = r'''
int main(){
 // Actual ordinary source configure only builds owner/presentation recipes.
 assert(mp4_actor_configure_context(true));assert(m.configures==1&&m.captures==0&&!m.captured);
 assert(mp4_actor_configure_context(true));assert(m.configures==1&&m.captures==0);
 // The later full/held request captures exactly once; subsequent checks reuse
 // the image only through its actual current predicate.
 assert(mp4_actor_configure_context());assert(m.captures==1&&m.captured);
 assert(mp4_actor_configure_context());assert(m.captures==1&&m.currents==1);
 m.current=false;assert(!mp4_actor_configure_context());assert(m.captures==1);
 m.current=true;mp4_actor_host.scope.bound=false;assert(!mp4_actor_configure_context(true));assert(!mp4_actor_configure_context());assert(m.captures==1);
 // Partial initial presentation binding never reaches native image capture.
 m={};mp4_actor_host={};mp4_actor_presentation_scope={};m.presentation=false;assert(!mp4_actor_configure_context(true));assert(m.captures==0);assert(!mp4_actor_configure_context());assert(m.captures==0);
 m={};mp4_actor_host={};mp4_actor_presentation_scope={};m.capture_ok=false;assert(!mp4_actor_configure_context());assert(m.captures==1&&!m.captured);
 m={};mp4_actor_host={};mp4_actor_presentation_scope={};m.selected=false;assert(!mp4_actor_configure_context(true));assert(m.configures==0&&m.captures==0);
}
'''
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'actual.cpp'; path.write_text(prefix + actual + driver)
        exe = Path(d) / 'actual'
        subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-fno-pie', '-no-pie', str(path), '-o', str(exe)], check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)
