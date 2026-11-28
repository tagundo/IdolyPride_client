#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <string>
#include <unordered_map>
using Method=const void;
namespace mp4ctl{struct Input{uint32_t source_name=0;void*source_default=nullptr,*prefab=nullptr;uint32_t seed=7;uint8_t particles=1,time_control=1,hierarchy=0;int32_t post=0;};}
struct Object{const char*type;bool alive=true;};
struct GO:Object{explicit GO():Object{"UnityEngine.GameObject"}{}};
struct Array;struct Timeline:Object{Array*tracks=nullptr;explicit Timeline():Object{"UnityEngine.Timeline.TimelineAsset"}{}};
struct Director:Object{GO*go=nullptr;Timeline*asset=nullptr;explicit Director():Object{"UnityEngine.Playables.PlayableDirector"}{}};
struct Asset:Object{mp4ctl::Input input{};uint8_t update=1;GO*source=nullptr;explicit Asset():Object{"UnityEngine.Timeline.ControlPlayableAsset"}{}};
struct Script{const char*type="UnityEngine.Timeline.DirectorControlPlayable";bool alive=true;void*target=nullptr;uint8_t sync=0,pad[7]{};double duration=99;};
static_assert(offsetof(Script,target)==16&&offsetof(Script,sync)==24&&offsetof(Script,duration)==32);
struct Element:Object{void*clip=nullptr;Element():Object{"UnityEngine.Timeline.RuntimeClip"}{}};
struct Clip:Object{void*asset=nullptr;Clip():Object{"UnityEngine.Timeline.TimelineClip"}{}};struct Track:Object{Array*clips=nullptr,*children=nullptr;Track():Object{"UnityEngine.Timeline.TrackAsset"}{}};struct Array{void*values[65]{};size_t count=0;};
struct Binding{uintptr_t rva=0;};struct Pin{Binding binding{};};
struct{Pin director_component,control_asset,director_control;}mp4_stage_other_pins;
struct{Binding components_internal,component_gameobject;}mp4_stage_profile;
struct{Binding component_get_component;}mp4_camera_owner_profile;
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=40,timeline_tracks=160,track_clips=96,track_children=80;};}
struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};namespace mp4actor{using Handle=::Handle;}namespace mp4game{using PlayableGraph=::Handle;}
struct Mp4TimelineContext{Director*director=nullptr;void*asset=nullptr;Handle graph{42,2,0};void*elements[2]{},*scripts[3]{};size_t element_count=1;Handle runtime_playables[2]{{1,2,0}};bool keep(void*){return true;}size_t clip_count=0,track_count=0;void*clips[4]{},*clip_tracks[4]{},*tracks[4]{};};
uintptr_t image_base=0;bool pins=true,current=true,schema=true,force_retain_failure=false,callback_ok=true;uint32_t next_handle=0;std::unordered_map<uint32_t,void*> roots;
Track authored_track;Array authored_tracks,authored_clips,authored_children;bool catalogue_current=true;
GO parent_go,source_go;Timeline parent_asset,child_asset,excluded_asset;Director parent,child,first;Asset asset;Clip clip;Array components;int track=0,unknown=0;size_t calls=0;std::string scenario;bool queried_recursive=false;
uint32_t mp4_retain(void*p){if(force_retain_failure)return 0;roots[++next_handle]=p;return next_handle;}void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
bool mp4_stage_other_pins_ready(){return pins;}void*mp4_timeline_class(const Pin&){return &unknown;}
void*mp4_type_get_object(void*){return &unknown;}
bool mp4_type_is(void*p,const char*t){return p&&!std::strcmp(static_cast<Object*>(p)->type,t);}bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_timeline_current(const Mp4TimelineContext&){return current;}
bool mp4_timeline_exact(void*p,const Pin&pin){if(&pin==&mp4_stage_other_pins.control_asset)return p&&mp4_type_is(p,"UnityEngine.Timeline.ControlPlayableAsset");if(&pin==&mp4_stage_other_pins.director_control)return p&&mp4_type_is(p,"UnityEngine.Timeline.DirectorControlPlayable");return p&&mp4_type_is(p,"UnityEngine.Timeline.RuntimeClip");}
extern Script script;extern Element element;
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){
 if(p==&script){if(off==16&&sizeof(T)==8){auto x=static_cast<Script*>(p)->target;std::memcpy(&v,&x,8);return true;}if(off==24&&sizeof(T)==1){auto x=static_cast<Script*>(p)->sync;std::memcpy(&v,&x,1);return true;}if(off==32&&sizeof(T)==8){auto x=static_cast<Script*>(p)->duration;std::memcpy(&v,&x,8);return true;}}
 if(p==&element&&off==24&&sizeof(T)==8){auto x=static_cast<Element*>(p)->clip;std::memcpy(&v,&x,8);return true;}
if(off==8&&sizeof(T)==4){std::memcpy(&v,static_cast<uint8_t*>(p)+8,4);return true;}if(off==160&&sizeof(T)==sizeof(void*)){auto x=static_cast<Timeline*>(p)->tracks;std::memcpy(&v,&x,sizeof x);return true;}if((off==96||off==80)&&sizeof(T)==sizeof(void*)){auto x=off==96?static_cast<Track*>(p)->clips:static_cast<Track*>(p)->children;std::memcpy(&v,&x,sizeof x);return true;}if(off==40&&sizeof(T)==sizeof(void*)){auto x=static_cast<Clip*>(p)->asset;std::memcpy(&v,&x,sizeof x);return true;}if(off==56&&sizeof(T)==1){auto x=static_cast<Asset*>(p)->update;std::memcpy(&v,&x,1);return true;}return false;}
bool mp4_control_schema(void*){return schema;}namespace mp4ctl{struct Owner{void*asset=nullptr,*director=nullptr,*timeline=nullptr,*track=nullptr,*clip=nullptr,*source_object=nullptr,*owner_object=nullptr;uintptr_t native=1;};struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
bool mp4_control_input(void*,const mp4ctl::Owner&o,mp4ctl::Input*out){*out=static_cast<Asset*>(o.asset)->input;return true;}
void*mp4_control_resolve(void*,void*a){return static_cast<Asset*>(a)->source;}
void*get_go(void*d,Method*){return static_cast<Director*>(d)->go;}
template<class T>T mp4_equipment_call(const Binding&b){return reinterpret_cast<T>(image_base+b.rva);}
void*get_components(void*go,void*type,bool use_search,bool recursive,bool inactive,bool reverse,void*list,Method*){assert(go==&source_go&&type==&unknown&&use_search&&inactive&&!reverse&&!list);queried_recursive=recursive;return &components;}
void*get_first(void*d,void*type,Method*){assert(d==&parent&&type==&unknown);return &first;}
bool mp4_actor_list(void*a,void***out,size_t*n,size_t cap){auto*v=static_cast<Array*>(a);if(v->count>cap)return false;*out=v->values;*n=v->count;return true;}
bool mp4_stage_array(void*a,void***out,size_t*n,size_t cap){auto*v=static_cast<Array*>(a);if(v->count>cap)return false;*out=v->values;*n=v->count;return true;}
void*get_asset(void*d,Method*){return static_cast<Director*>(d)->asset;}
void get_director_graph(void*,mp4game::PlayableGraph*out,Method*){*out={42,2,0};}
struct{decltype(&get_asset)director_get_asset=get_asset;decltype(&get_director_graph)director_graph_injected=get_director_graph;}mp4_api;

#include "director-edges.cpp"
#include "director-node-scope.hpp.inc"
Script script;Element element;bool graph_ok=true,leaf=true,path_ok=true,node_present=true,factory_ok=true,birth_ok=true,target_ok=true,field_ok=true,clock_held=true;size_t emitted=0,writes=0;mp4ctl::Owner captured_owner;
struct{Pin clip;}mp4_timeline_pins;
struct{Binding calls[1];}mp4_director_control_pins;
struct{Binding playable_graph_get;}mp4_actor_profile;
struct Field{uint32_t words[4]{};};Field field;
bool mp4_root_track_field(void*,const char*name,size_t,void**out){field.words[2]=(std::strcmp(name,"director")==0?18u:std::strcmp(name,"m_SyncTime")==0?2u:13u)<<16;*out=&field;return field_ok;}
const void*font_field_type(void*p){return p;}
bool mp4_prefix(const Binding&){return pins;}bool mp4_hook_was_statically_verified(const Binding&){return false;}
bool valid(Handle*n,Method*){return n->handle==1||n->handle==2;}bool graph_check(Handle*n,Method*){return graph_ok&&n->handle==42&&n->version==2;}
int inputs(Handle*n,Method*){return n->handle==1?1:leaf?0:1;}void input(Handle*,int,Handle*out,Method*){*out={path_ok?uintptr_t(2):uintptr_t(3),2,0};}
struct API{decltype(&valid)playable_valid=valid;decltype(&graph_check)graph_valid=nullptr;decltype(&inputs)playable_input_count=inputs;decltype(&input)playable_input=input;};
API mp4_actor_state_api(){API a;a.graph_valid=graph_check;return a;}
void get_graph(Handle*,Handle*out,Method*){*out={42,2,0};}
bool mp4_actor_same_handle(Handle a,Handle b){return a.handle==b.handle&&a.version==b.version;}
void*mp4_timeline_script(Handle n){return n.handle==2?&script:nullptr;}
int mp4_timeline_node_index(const Mp4TimelineContext&,Handle n){return node_present?(n.handle==1?0:n.handle==2?1:-1):-1;}
bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool){return true;}
bool mp4_control_owner_current(void*,const mp4ctl::Owner&o){return current&&o.asset==&asset&&o.director==&parent;}
bool mp4_control_source_current(void*,uint64_t e){return current&&e==11;}bool mp4_stage_clock_held(void*){return clock_held;}
bool captured_scope=true;
struct{bool captured()const{return captured_scope;}bool captured_owner(void*a,mp4ctl::Owner*out)const{if(a!=&asset)return false;*out=::captured_owner;return true;}
 bool factory_event(void*,mp4ctl::Handle,mp4ctl::Handle,uint64_t*out)const{*out=10;return factory_ok;}}mp4_control_assets;
bool mp4_control_passive_receipted(void*,void*,void*,mp4ctl::Handle,mp4ctl::Handle,uint64_t*out){*out=9;return factory_ok;}
template<class T>bool mp4_stage_store(void*p,size_t off,T value){++writes;if(!p)return false;std::memcpy(static_cast<uint8_t*>(p)+off,&value,sizeof value);return true;}
#include "director-node-host.cpp"
bool target_current(void*p){return target_ok&&p==&child;}
uint64_t graph_birth(const Mp4TimelineContext&){return birth_ok?100:0;}
bool emit(void*,const mp4dn::Node&n){++emitted;assert(n.key.target==&child&&n.key.length==1&&n.key.path[0]==0&&n.key.clip==&clip&&n.factory);return true;}
#include "director-source-edge.cpp"
Mp4TimelineContext*source_context=nullptr;bool complete=true,waiting=false;
mp4dn::Result contexts(mp4dn::Round round,mp4dn::Result(*visit)(void*,Mp4TimelineContext&),void*opaque,uint64_t*recipe){assert(round==mp4dn::Round::source);*recipe=complete?9:0;if(waiting)return mp4dn::Result::waiting;return visit(opaque,*source_context);}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];parent.go=&parent_go;parent.asset=&parent_asset;child.go=&source_go;child.asset=&child_asset;first.asset=&parent_asset;asset.source=&source_go;clip.asset=&asset;components.values[0]=&child;components.count=1;script.target=&child;element.clip=&clip;captured_owner={&asset,&parent,&parent_asset,&track,&clip,&source_go,&parent_go,1};mp4_stage_profile.component_gameobject.rva=reinterpret_cast<uintptr_t>(get_go);mp4_stage_profile.components_internal.rva=reinterpret_cast<uintptr_t>(get_components);mp4_camera_owner_profile.component_get_component.rva=reinterpret_cast<uintptr_t>(get_first);mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(get_graph);mp4_director_control_target_current=target_current;mp4_director_control_graph_birth=graph_birth;
 Mp4TimelineContext c;c.director=&parent;c.asset=&parent_asset;c.clips[0]=&clip;c.clip_tracks[0]=&track;c.tracks[0]=&track;c.clip_count=c.track_count=1;c.elements[0]=&element;c.scripts[1]=&script;

 source_context=&c;mp4_director_node_contexts=contexts;
 void*from=&parent,*to=&child;
 if(scenario=="context")mp4_director_node_contexts=nullptr;
 if(scenario=="unheld")clock_held=false;
 if(scenario=="uncaptured")captured_scope=false;
 if(scenario=="incomplete")complete=false;
 if(scenario=="waiting")waiting=true;
 if(scenario=="parent")from=&child;
 if(scenario=="child")to=&unknown;
 if(scenario=="same")to=&parent;
 if(scenario=="factory")factory_ok=false;
 if(scenario=="graph")graph_ok=false;
 if(scenario=="path")path_ok=false;
 if(scenario=="target")target_ok=false;
 if(scenario=="state")script.sync=2;
 uint64_t receipt=0;size_t nodes=0;assert(mp4_director_control_source_edge(from,to,&receipt,&nodes)==(scenario=="normal"));
 if(scenario=="normal")assert(receipt&&nodes==1);else assert(!receipt&&!nodes);
 assert(roots.size()==(mp4_control_director_type?1u:0u));
}
