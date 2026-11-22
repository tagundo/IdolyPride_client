#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <map>
namespace mp4_director_birth{struct SourceTuple{uintptr_t director=0,asset=0,game_object=0,klass=0,method=0;uint64_t epoch=0,capture=0;};struct SourcePins{uintptr_t factory=0x222;};}
namespace mp4_director_maintenance{struct Call{uint64_t epoch=7;uintptr_t source_asset=0,receiver=0;};}
namespace mp4game{struct Layout{size_t player_director_controller=0x80,controller_directors=0x20;};}
struct Model{bool thread=true,current=true,held=true,alive=true,bad_primary=false,bad_child_prefix=false,bad_mi=false,list_bad=false,same_go=false;uintptr_t base=0x1000;int32_t version=3;size_t retained=0,fail_retain=0;uint32_t sequence=0;std::map<uint32_t,void*>roots;void*values[1]{};}model;
struct{bool active=true;struct{void*player=nullptr,*director=nullptr,*camera_director=nullptr;uint64_t generation=7;}source;}mp4_scene_host;
bool game_call(){return model.thread;}bool mp4_scene_source_current(){return model.current;}namespace idoly_mp4_runtime{struct Clock{bool held(){return model.held;}}clock;Clock&native_clock_scope(){return clock;}}
uint32_t mp4_retain(void*p){++model.retained;if(model.fail_retain==model.retained)return 0;const auto h=++model.sequence;model.roots[h]=p;return h;}void*weak_get(uint32_t h){auto i=model.roots.find(h);return i==model.roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(model.roots.erase(h)==1);}
void*get_asset(void*d,void*){const auto p=(uintptr_t)d;return (void*)(p==model.base+0x100?model.base+0x300:p==model.base+0x200?model.base+0x400:0);}struct{decltype(&get_asset)director_get_asset=get_asset;}mp4_api;
void*get_go(void*d,const void*){return (void*)(model.base+((uintptr_t)d==model.base+0x100||model.same_go?0x500:0x600));}uintptr_t image_base=0;struct{struct{uintptr_t rva=(uintptr_t)get_go;}get_game_object;}mp4_actor_profile;
bool mp4_exact_type(void*p,const char*type){const auto a=(uintptr_t)p;if(!strcmp(type,"UnityEngine.Playables.PlayableDirector"))return !(model.bad_primary&&a==model.base+0x100)&&(a==model.base+0x100||a==model.base+0x200);if(!strcmp(type,"UnityEngine.Timeline.TimelineAsset"))return a==model.base+0x300||a==model.base+0x400;if(!strcmp(type,"UnityEngine.GameObject"))return a==model.base+0x500||a==model.base+0x600;return false;}bool mp4_alive(void*){return model.alive;}
void*object_class(void*p){return (void*)(uintptr_t)((uintptr_t)p==model.base+0x300?0x7000:0x7100);}const void*font_method(void*,const char*,int){return (void*)0x8888;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){uintptr_t v=0;const auto a=(uintptr_t)p;if(a==model.base&&at==0x80)v=model.base+0x700;else if(a==model.base+0x700&&at==0x20)v=model.base+0x800;else if(a==model.base+0x800&&at==0x1c)v=model.version;else if((a==0x7000||a==0x7100)&&at==0x198)v=model.bad_child_prefix&&a==0x7100?0x223:0x222;else if((a==0x7000||a==0x7100)&&at==0x1a0)v=model.bad_mi?0x8889:0x8888;else return false;std::memcpy(&out,&v,sizeof out);return true;}
bool mp4_actor_list(void*,void***values,size_t*count,size_t){if(model.list_bad)return false;*values=model.values;*count=1;return true;}
void select(uintptr_t base,uint64_t epoch){model.base=base;mp4_scene_host.source.player=(void*)base;mp4_scene_host.source.director=(void*)(base+0x100);mp4_scene_host.source.camera_director=nullptr;mp4_scene_host.source.generation=epoch;model.values[0]=(void*)(base+0x200);}
mp4_director_maintenance::Call selector(){return {mp4_scene_host.source.generation,model.base+0x300,model.base+0x100};}
