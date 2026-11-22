#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <new>
#include <cassert>
#include <vector>
struct Model {bool thread=true,current=true,target=true,build=true,throw_build=false,reenter=false;int build_calls=0,retains=0,releases=0;std::vector<int>events;}m;
namespace idoly_mp4_actor_placement{struct Address{void*p;};}void*operator new(size_t,idoly_mp4_actor_placement::Address a){return a.p;}void operator delete(void*,idoly_mp4_actor_placement::Address){}
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,pad=0;};}
namespace mp4_animation_programme{struct Plan {int id=0;};}
struct Mp4AnimationProgrammeTarget{void*animator=nullptr,*game_object=nullptr,*bundle=nullptr;uintptr_t native=0;int32_t instance=0;};
struct Mp4AnimationProgrammeLease{uint32_t roots[3]{};};
struct Mp4TimelineContext{void*animation_programmes=nullptr;void(*release_animation_programmes)(void*)=nullptr;void*director=nullptr;void*tracks[512]{};mp4actor::Handle compiled[512]{};size_t track_count=0;uint32_t roots[3]{};size_t root_count=0;
~Mp4TimelineContext(){if(animation_programmes&&release_animation_programmes)release_animation_programmes(animation_programmes);for(size_t i=0;i<root_count;++i)if(roots[i]){m.events.push_back(30);++m.releases;}}
};
struct Mp4AnimationPlanContext{const Mp4TimelineContext*timeline=nullptr;void*track=nullptr;Mp4AnimationProgrammeTarget target{};uint64_t foreign=0;};
struct FactorySource{int track=2;}mp4_animation_factory_source;uint64_t mp4_scene_shader_foreign=5;
bool game_call(){return m.thread;}bool mp4_timeline_current(const Mp4TimelineContext&){return m.current;}bool mp4_timeline_exact(void*p,int){return reinterpret_cast<uintptr_t>(p)%2==0;}
void* get_binding(void*,void*track,void*){return reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(track)+100);}
struct Api{decltype(&get_binding)director_get_binding=get_binding;}mp4_api;
bool mp4_animation_programme_release(Mp4AnimationProgrammeLease&l){if(!game_call())return false;for(auto&r:l.roots)if(r){++m.releases;m.events.push_back(10);r=0;}return true;}
bool mp4_animation_programme_target(void*a,Mp4AnimationProgrammeTarget*out,Mp4AnimationProgrammeLease*l){if(!m.target)return false;out->animator=a;for(auto&r:l->roots)r=uint32_t(++m.retains);return true;}
bool mp4_animation_build_plan(const Mp4TimelineContext&,void*track,mp4_animation_programme::Plan*out,Mp4AnimationProgrammeTarget*){++m.build_calls;m.events.push_back(20);if(m.throw_build)throw 1;out->id=int(reinterpret_cast<uintptr_t>(track));return m.build;}
