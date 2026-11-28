// Public query/PM/target programme leaves are modeled; actual roster body follows.
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <map>
#include <vector>
#include <memory>
#include <string>
#include <stdexcept>
using Method=void;
namespace mp4actor {struct Handle{uintptr_t handle=0;
uint32_t version=0,padding=0;
};
}
namespace mp4world {using AnimationOutput=mp4actor::Handle;
}
namespace mp4game {using PlayableGraph=mp4actor::Handle;
struct Binding{uintptr_t rva=0;
uint8_t prefix[16]{};
};
struct Layout{size_t player_director_controller=16,controller_directors=24;
};
}
namespace mp4stage {struct Layout{static constexpr size_t timeline_tracks=40,track_children=32;
};
}
namespace mp4_animation_defaults{struct Object{void*managed=nullptr;
uintptr_t native=0;
int32_t instance_id=0;
uint32_t strong_root=0;
};
}
struct Mp4SceneWitness{void*player=nullptr,*director=nullptr,*camera_director=nullptr;
uint64_t generation=0;
};
struct Obj{std::string type;
bool alive=true,known=true;
int64_t local=0;
uintptr_t native=0;
int32_t id=0;
std::map<size_t,uint64_t>fields;
std::vector<void*>list;
};
struct Graph{mp4actor::Handle handle{},root{};
bool valid=true;
std::vector<mp4world::AnimationOutput>outputs;
};
struct Output{bool animation=true;
void*target=nullptr;
};
std::vector<std::unique_ptr<Obj>> objects;
std::map<uintptr_t,Graph>graphs;
std::map<uintptr_t,Output>outputs;
std::map<void*,void*>assets;
std::map<void*,mp4actor::Handle>director_graphs;
std::map<std::pair<void*,void*>,void*>bindings;
std::map<uint32_t,void*>roots;
uint32_t nextroot=1;
bool owner=true,prefixes=true,target_provider=true,origin=true;
uint64_t mp4_scene_shader_foreign=7;
uintptr_t image_base=0,mp4_native_base=0x1000;
unsigned retains=0,releases=0,target_reads=0,output_reads=0,query_calls=0;
int fail_retain_at=0,throw_query_at=0;
void query(){++query_calls;
if(throw_query_at&&int(query_calls)==throw_query_at)throw std::runtime_error("modeled original public query throw");
}
void*make(const char*t,int64_t local=0){auto o=std::make_unique<Obj>();
o->type=t;
o->local=local;
o->native=0x100000+objects.size()*0x100;
o->id=int32_t(objects.size()+1);
void*p=o.get();
objects.push_back(std::move(o));
return p;
}
Obj&obj(void*p){assert(p);
return *static_cast<Obj*>(p);
}
bool game_call(){return owner;
}bool mp4_alive(void*p){return p&&obj(p).alive;
}
bool mp4_type_is(void*p,const char*t){return p&&(obj(p).type==t||(std::string(t)=="UnityEngine.Timeline.TrackAsset"&&obj(p).type=="UnityEngine.Timeline.AnimationTrack"));
}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){if(!p||!obj(p).fields.count(offset))return false;
auto value=obj(p).fields[offset];
std::memcpy(&out,&value,sizeof out);
return true;
}
bool mp4_actor_list(void*p,void***out,size_t*count,size_t cap){if(!p||obj(p).type!="List"||obj(p).list.size()>cap)return false;
*out=obj(p).list.data();
*count=obj(p).list.size();
return true;
}
uint32_t mp4_retain(void*p){if(!p)return 0;
++retains;
if(fail_retain_at&&int(retains)==fail_retain_at)return 0;
const auto n=nextroot++;
roots[n]=p;
return n;
}
void*weak_get(uint32_t n){auto i=roots.find(n);
return i==roots.end()?nullptr:i->second;
}
void weak_free(uint32_t n){assert(n&&roots.count(n));
roots.erase(n);
++releases;
}
struct Mp4ActorTempRoot{uint32_t root=0;
explicit Mp4ActorTempRoot(void*p):root(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(root)weak_free(root);
}void*get()const{return weak_get(root);
}};
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;
}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.director==b.director&&a.camera_director==b.camera_director&&a.generation==b.generation;
}
namespace idoly_mp4_runtime {struct Game{Mp4SceneWitness selected{};
bool selected_scene_witness(Mp4SceneWitness&out){out=selected;
return true;
}}game;
}
void*get_asset(void*d,Method*){query();
return assets[d];
}
void get_graph(void*d,mp4game::PlayableGraph*out,Method*){query();
*out=director_graphs[d];
}
void*get_binding(void*d,void*t,Method*){query();
return bindings[{d,t}];
}
bool graph_valid(mp4actor::Handle*g,Method*){query();
auto i=graphs.find(g->handle);
return i!=graphs.end()&&i->second.valid&&i->second.handle.version==g->version;
}
int32_t root_count(mp4actor::Handle*g,Method*){query();
return graphs.at(g->handle).root.handle?1:0;
}
void get_root(mp4actor::Handle*g,int32_t i,mp4actor::Handle*out,Method*){query();
assert(i==0);
*out=graphs.at(g->handle).root;
}
int32_t output_count(mp4actor::Handle*g,Method*){query();
return int32_t(graphs.at(g->handle).outputs.size());
}
void get_output(mp4actor::Handle*g,int32_t index,mp4world::AnimationOutput*out,Method*){query();
++output_reads;
*out=graphs.at(g->handle).outputs.at(size_t(index));
}
void*animation_type=nullptr;
void*other_type=nullptr;
void*output_type(mp4world::AnimationOutput*out,Method*){query();
return outputs.at(out->handle).animation?animation_type:other_type;
}
void*output_target(mp4actor::Handle*out,Method*){query();
++target_reads;
return outputs.at(out->handle).target;
}
struct State{decltype(&::graph_valid)graph_valid=::graph_valid;
decltype(&root_count)graph_root_count=::root_count;
decltype(&get_root)graph_root=::get_root;
decltype(&::output_target)output_target=::output_target;
};
State mp4_actor_state_api(){return {};
}
struct GameApi{decltype(&get_asset)director_get_asset=::get_asset;
decltype(&get_graph)director_graph_injected=::get_graph;
decltype(&get_binding)director_get_binding=::get_binding;
}mp4_api;
struct Profile{mp4game::Binding director_get_asset,director_graph_injected,director_get_binding,graph_valid;
}mp4_profile;
struct ActorProfile{mp4game::Binding graph_root_count,graph_root,output_target;
}mp4_actor_profile;
struct WorldProfile{mp4game::Binding graph_output_count,graph_output,output_type;
}mp4_world_profile;
struct{mp4game::Binding animation{77,{}};
}mp4_output_pins;
bool mp4_prefix(const mp4game::Binding&){return prefixes;
}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;
}
void*mp4_resolved_type_class(const mp4game::Binding&,const char*,const char*){return prefixes?animation_type:nullptr;
}
void*mp4_type_get_object(void*){return animation_type;
}
struct{mp4game::Binding track{88,{}};
}mp4_animation_factory_source;
bool mp4_timeline_exact(void*p,const mp4game::Binding&){return mp4_type_is(p,"UnityEngine.Timeline.AnimationTrack")&&obj(p).known;
}
struct Mp4AnimationTargetRole{int64_t animator=0,game_object=0;
};
Mp4AnimationTargetRole roles[2]={{501,601},{502,602}};
struct Mp4AnimationProgrammeTarget{void*animator=nullptr,*game_object=nullptr,*bundle=nullptr;
uintptr_t native=0;
int32_t instance=0,scene=0;
const Mp4AnimationTargetRole*role=nullptr;
uint64_t receipt=0;
};
struct Mp4AnimationProgrammeLease{uint32_t roots[3]{};
};
struct Mp4AnimationProgrammeOrigin{void*animator=nullptr,*go=nullptr,*bundle=nullptr;
int32_t scene=0;
uint64_t foreign=0;
};
std::map<void*,Mp4AnimationProgrammeTarget>programmes;
bool mp4_animation_programme_current(void*opaque){auto&c=*static_cast<Mp4AnimationProgrammeOrigin*>(opaque);
return origin&&c.foreign==mp4_scene_shader_foreign&&programmes.count(c.animator)&&mp4_alive(c.animator);
}
bool mp4_animation_programme_target(void*a,Mp4AnimationProgrammeTarget*out,Mp4AnimationProgrammeLease*lease){
 if(!target_provider||!programmes.count(a))return false;
 *out=programmes.at(a);
 void*values[]={out->animator,out->game_object,out->bundle};
 for(size_t i=0;i<3;++i){lease->roots[i]=mp4_retain(values[i]);
 if(!lease->roots[i]){for(auto&r:lease->roots)if(r){weak_free(r);
 r=0;
 }return false;
 }}
 return true;
}
bool mp4_animation_factory_native(void*a,uintptr_t*n,int32_t*i){if(!a||!mp4_alive(a))return false;
*n=obj(a).native;
*i=obj(a).id;
return true;
}
namespace mp4shader{struct Identity{uintptr_t native=0;
int32_t instance=0;
};
}
bool mp4_scene_shader_identity(void*p,const char*t,mp4shader::Identity&out){if(!mp4_type_is(p,t)||!mp4_alive(p))return false;
out={obj(p).native,obj(p).id};
return true;
}
bool mp4_scene_origin_thread(){return owner;
}bool mp4_scene_origin_read(uintptr_t,void*,size_t){return true;
}
namespace idoly_mp4_origin{
struct ObjectRef{void*object=nullptr,*native=nullptr;
int32_t id=0;
};
struct Origin{int64_t local=0;
uint64_t file=0;
};
struct Api{void*context;
bool(*thread)();
bool(*current)(void*);
bool(*read)(uintptr_t,void*,size_t);
};
struct NativeHost{Api api{};
bool bind(uintptr_t,int,Api v){api=v;
return origin;
}bool query(const ObjectRef*refs,size_t n,Origin*out){if(!api.thread()||!api.current(api.context))return false;
for(size_t i=0;i<n;++i)out[i]={obj(refs[i].object).local,42};
return origin;
}};
constexpr int android_profile=1,ios_profile=2;
bool same_file(const Origin&a,const Origin&b){return a.file==b.file;
}
}
struct Mp4AnimationTrackRole{int64_t timeline,root,track,animator;
};
constexpr Mp4AnimationTrackRole mp4_animation_track_roles[]={{100,101,101,501},{200,201,201,502}};
