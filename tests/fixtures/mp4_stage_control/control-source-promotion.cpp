#include <cassert>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <string>
#include <unordered_map>
using Method=const void;
namespace mp4ctl{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};struct Cache{void*controlled_asset=nullptr;double duration=0;uint8_t director=1,active=1,loop=0,controlling_directors=0,controlling_particles=0;};struct Input{uint32_t source_name=0;void*source_default=nullptr,*prefab=nullptr;uint32_t seed=7;uint8_t particles=1,time_control=1,hierarchy=0;int32_t post=0;};}
struct Object{const char*type;bool alive=true;};
struct GO:Object{explicit GO():Object{"UnityEngine.GameObject"}{}};
struct Array;struct Timeline:Object{Array*tracks=nullptr;explicit Timeline():Object{"UnityEngine.Timeline.TimelineAsset"}{}};
struct Director:Object{GO*go=nullptr;Timeline*asset=nullptr;explicit Director():Object{"UnityEngine.Playables.PlayableDirector"}{}};
struct Asset:Object{mp4ctl::Cache cache{};mp4ctl::Input input{};uint8_t update=1;GO*source=nullptr;explicit Asset():Object{"UnityEngine.Timeline.ControlPlayableAsset"}{}};
struct Clip:Object{void*asset=nullptr;Clip():Object{"UnityEngine.Timeline.TimelineClip"}{}};struct Track:Object{Array*clips=nullptr,*children=nullptr;Track():Object{"UnityEngine.Timeline.TrackAsset"}{}};struct Array{void*values[65]{};size_t count=0;};
struct Binding{uintptr_t rva=0;};struct Pin{Binding binding{};};
struct{Pin director_component,control_asset;Binding control_create,graph_resolver;}mp4_stage_other_pins;
struct{Binding components_internal,component_gameobject;}mp4_stage_profile;
struct{Binding component_get_component;}mp4_camera_owner_profile;
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=40,timeline_tracks=160,track_clips=96,track_children=80;};}
struct Mp4TimelineContext{Director*director=nullptr;void*asset=nullptr;mp4ctl::Handle graph{42,2,0},runtime_playables[4]{};size_t element_count=0,clip_count=0,track_count=0;void*elements[4]{},*clips[4]{},*clip_tracks[4]{},*tracks[4]{};};
struct Element:Object{void*clip=nullptr;Element():Object{"UnityEngine.Timeline.RuntimeClip"}{}};Element element;
struct{Pin clip;}mp4_timeline_pins;
bool main_thread=true,graph_valid=true,node_valid=true,weak_fail=false;size_t graph_reads=0;
uintptr_t image_base=0;bool pins=true,current=true,schema=true,force_retain_failure=false,callback_ok=true;uint32_t next_handle=0;std::unordered_map<uint32_t,void*> roots;
Track authored_track;Array authored_tracks,authored_clips,authored_children;bool catalogue_current=true;
GO parent_go,source_go;Timeline parent_asset,child_asset,excluded_asset;Director parent,child,first;Asset asset;Clip clip;Array components;int track=0,unknown=0;size_t calls=0;std::string scenario;bool queried_recursive=false;
uint32_t mp4_retain(void*p){if(force_retain_failure)return 0;roots[++next_handle]=p;return next_handle;}void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
bool game_call(){return main_thread;}bool mp4_stage_other_pins_ready(){return pins;}void*mp4_timeline_class(const Pin&){return &unknown;}
void*mp4_type_get_object(void*){return &unknown;}
bool mp4_type_is(void*p,const char*t){return p&&(!std::strcmp(static_cast<Object*>(p)->type,t)||(!std::strcmp(t,"UnityEngine.Playables.PlayableAsset")&&!std::strcmp(static_cast<Object*>(p)->type,"UnityEngine.Timeline.TimelineAsset")));}bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_timeline_current(const Mp4TimelineContext&){return current;}
bool mp4_timeline_exact(void*p,const Pin&pin){return p&&((&pin==&mp4_stage_other_pins.control_asset&&mp4_type_is(p,"UnityEngine.Timeline.ControlPlayableAsset"))||(&pin==&mp4_timeline_pins.clip&&mp4_type_is(p,"UnityEngine.Timeline.RuntimeClip")));}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){
if(p==&element&&off==24&&sizeof(T)==sizeof(void*)){std::memcpy(&v,&element.clip,sizeof(void*));return true;}
if(off==16&&sizeof(T)==sizeof(uintptr_t)){auto x=reinterpret_cast<uintptr_t>(p);std::memcpy(&v,&x,sizeof x);return true;}
if(off==0&&sizeof(T)==sizeof(uintptr_t)){std::memcpy(&v,p,sizeof(uintptr_t));return true;}
if((off==59||off==80||off==81||off==82)&&sizeof(T)==1){auto&a=static_cast<Asset*>(p)->cache;auto x=off==59?a.active:off==80?a.loop:off==81?a.controlling_directors:a.controlling_particles;std::memcpy(&v,&x,1);return true;}
if(off==64&&sizeof(T)==sizeof(void*)){auto x=static_cast<Asset*>(p)->cache.controlled_asset;std::memcpy(&v,&x,sizeof x);return true;}
if(off==72&&sizeof(T)==sizeof(double)){auto x=static_cast<Asset*>(p)->cache.duration;std::memcpy(&v,&x,sizeof x);return true;}
if(off==160&&sizeof(T)==sizeof(void*)){auto x=static_cast<Timeline*>(p)->tracks;std::memcpy(&v,&x,sizeof x);return true;}if((off==96||off==80)&&sizeof(T)==sizeof(void*)){auto x=off==96?static_cast<Track*>(p)->clips:static_cast<Track*>(p)->children;std::memcpy(&v,&x,sizeof x);return true;}if(off==40&&sizeof(T)==sizeof(void*)){auto x=static_cast<Clip*>(p)->asset;std::memcpy(&v,&x,sizeof x);return true;}if(off==56&&sizeof(T)==1){auto x=static_cast<Asset*>(p)->update;std::memcpy(&v,&x,1);return true;}return false;}
bool mp4_control_schema(void*){return schema;}namespace mp4ctl{struct Owner{void*asset=nullptr,*director=nullptr,*timeline=nullptr,*track=nullptr,*clip=nullptr,*source_object=nullptr,*owner_object=nullptr;uintptr_t native=0;};}
bool mp4_control_input(void*,const mp4ctl::Owner&o,mp4ctl::Input*out){*out=static_cast<Asset*>(o.asset)->input;return true;}
void*mp4_control_resolve(void*,void*a){return static_cast<Asset*>(a)->source;}
void*get_go(void*d,Method*){return static_cast<Director*>(d)->go;}
template<class T>T mp4_equipment_call(const Binding&b){return reinterpret_cast<T>(image_base+b.rva);}
void*get_components(void*go,void*type,bool use_search,bool recursive,bool inactive,bool reverse,void*list,Method*){assert(go==&source_go&&type==&unknown&&use_search&&inactive&&!reverse&&!list);queried_recursive=recursive;return &components;}
void*get_first(void*d,void*type,Method*){assert(d==&parent&&type==&unknown);return &first;}
bool mp4_actor_list(void*a,void***out,size_t*n,size_t cap){auto*v=static_cast<Array*>(a);if(v->count>cap)return false;*out=v->values;*n=v->count;return true;}
bool mp4_stage_array(void*a,void***out,size_t*n,size_t cap){auto*v=static_cast<Array*>(a);if(v->count>cap)return false;*out=v->values;*n=v->count;return true;}
void*get_asset(void*d,Method*){return static_cast<Director*>(d)->asset;}
struct{decltype(&get_asset)director_get_asset=get_asset;}mp4_api;

uint32_t make_weak(void*p,bool){return weak_fail?0:mp4_retain(p);}
auto weak_new=make_weak;
struct NativeMethod{uintptr_t entry=17;} method;
void*object_class(void*p){return p;}const void*font_method(void*,const char*,int){return &method;}
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
struct ActorApi{bool(*graph_valid)(mp4actor::Handle*,Method*);bool(*playable_valid)(mp4actor::Handle*,Method*);};
bool graph_check(mp4actor::Handle*g,Method*){++graph_reads;return graph_valid&&g->handle==42&&g->version==2;}
bool node_check(mp4actor::Handle*g,Method*){return node_valid&&g->handle==101&&g->version==2;}
ActorApi mp4_actor_state_api(){return {graph_check,node_check};}
void*resolver(mp4actor::Handle*,Method*){return &parent;}
void node_graph(mp4actor::Handle*,mp4actor::Handle*out,Method*){*out={42,2,0};}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
struct{Binding playable_graph_get;}mp4_actor_profile;
bool mp4_control_source_pins_ready(){return mp4_stage_other_pins_ready();}
#include "control-passive.cpp"
bool mp4_control_source_observe(const Mp4ControlPassiveImage&,uint64_t){return false;}

namespace mp4dn {enum class Result:uint8_t{ok,waiting,invalid,stale,failed,unsupported};enum class Round:uint8_t{source,exporting,restoring,restored};}
enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
bool held=true,scope_current=true,nodes_current=true,nodes_captured=true,nodes_restored=true,factory_exists=true,restored_image=true,context_wait=false,context_receipt=true,runtime_good=true,owner_good=true;
struct{bool active=true,invalidated=false,releasing=false,logical_checkpoint=true;}mp4_scene_host;
struct{struct{uint64_t generation=77;}source;}mp4_stage_host;
namespace idoly_mp4_runtime {struct{uint64_t generation=99;}job;}
bool mp4_scene_source_current(){return current;}bool mp4_stage_clock_held(void*){return held;}
struct{bool captured()const{return nodes_captured;}bool current()const{return nodes_current;}mp4dn::Round round()const{return nodes_restored?mp4dn::Round::restored:mp4dn::Round::restoring;}}mp4_director_nodes;
mp4ctl::Owner captured_owner;mp4ctl::Input saved_input;mp4ctl::Cache saved_logical,raw_before,raw_after;
struct{
 bool current()const{return scope_current;}
 bool restored_source_image(void*a,mp4ctl::Owner*o,mp4ctl::Input*i,mp4ctl::Cache*c,uint64_t*e)const{if(!restored_image||a!=&asset)return false;*o=captured_owner;*i=saved_input;*c=saved_logical;*e=77;return true;}
 bool factory_event(void*a,mp4ctl::Handle g,mp4ctl::Handle r,uint64_t*t,mp4ctl::Cache*b,mp4ctl::Cache*c)const{if(!factory_exists||a!=&asset||g.handle!=42||r.handle!=101)return false;*t=888;*b=raw_before;*c=raw_after;return true;}
}mp4_control_assets;
bool mp4_control_owner_current(void*,const mp4ctl::Owner&o){return owner_good&&o.asset==&asset&&o.director==&parent;}
bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool){return runtime_good;}
Mp4TimelineContext actual_context;
mp4dn::Result contexts(mp4dn::Round r,mp4dn::Result(*visit)(void*,Mp4TimelineContext&),void*ctx,uint64_t*recipe){assert(r==mp4dn::Round::restored);*recipe=0;if(context_wait)return mp4dn::Result::waiting;auto result=visit(ctx,actual_context);if(result==mp4dn::Result::ok&&context_receipt)*recipe=999;return result;}
auto mp4_director_node_contexts=contexts;
#include "control-source-promotion.cpp"
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];parent.go=&parent_go;asset.source=&source_go;asset.input.source_default=&source_go;asset.cache.controlled_asset=&parent_asset;mp4_stage_other_pins.control_create.rva=17;mp4_stage_other_pins.graph_resolver.rva=reinterpret_cast<uintptr_t>(resolver);mp4_stage_profile.component_gameobject.rva=reinterpret_cast<uintptr_t>(get_go);mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(node_graph);
 Mp4ControlPassiveTicket ticket;const mp4ctl::Handle graph{42,2,0},result{101,2,0};
 assert(mp4_control_passive_before(&asset,graph,&parent_go,&method,ticket));raw_before=asset.cache;
 asset.cache.duration=25;asset.cache.controlled_asset=&child_asset;raw_after=asset.cache;
 assert(mp4_control_passive_after(ticket,result,true));ticket.clear();
 saved_logical=raw_before;saved_logical.duration=17;asset.cache=saved_logical;saved_input=asset.input;
 captured_owner={&asset,&parent,&parent_asset,&track,&clip,&source_go,&parent_go,reinterpret_cast<uintptr_t>(&asset)};
 clip.asset=&asset;element.clip=&clip;actual_context.director=&parent;actual_context.asset=&parent_asset;actual_context.element_count=1;actual_context.elements[0]=&element;actual_context.runtime_playables[0]=result;
 if(scenario=="no_checkpoint"){current=false;assert(mp4_control_promote_source_history(false)==Mp4SceneResult::ok);mp4_control_passive_clear();assert(roots.empty());return 0;}
 if(scenario=="unheld")held=false;else if(scenario=="scope_not_current")scope_current=false;else if(scenario=="nodes_not_current")nodes_current=false;else if(scenario=="nodes_uncaptured")nodes_captured=false;else if(scenario=="nodes_not_restored")nodes_restored=false;else if(scenario=="source_lost")current=false;else if(scenario=="invalidated")mp4_scene_host.invalidated=true;else if(scenario=="releasing")mp4_scene_host.releasing=true;else if(scenario=="marker_missing")mp4_scene_host.logical_checkpoint=false;else if(scenario=="restored_image_missing")restored_image=false;else if(scenario=="wrong_epoch")mp4_stage_host.source.generation=78;else if(scenario=="wrong_owner")owner_good=false;else if(scenario=="raw_event_mismatch")++raw_after.duration;else if(scenario=="logical_mismatch")++asset.cache.duration;else if(scenario=="context_wait")context_wait=true;else if(scenario=="context_incomplete")context_receipt=false;else if(scenario=="runtime_invalid")runtime_good=false;else if(scenario=="no_private_event")factory_exists=false;else if(scenario=="ordinary_unchanged"){factory_exists=false;saved_logical=raw_after;asset.cache=raw_after;}
 const auto status=mp4_control_promote_source_history(true);
 const bool ok=scenario=="normal"||scenario=="ordinary_unchanged"||scenario=="repeat";
 assert((status==Mp4SceneResult::ok)==ok);
 if(scenario=="context_wait")assert(status==Mp4SceneResult::waiting);
 if(ok){uint64_t raw=0,logical=0;assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result,&raw,&logical)&&raw);assert(bool(logical)==(scenario!="ordinary_unchanged"));if(scenario=="repeat")assert(mp4_control_promote_source_history(true)==Mp4SceneResult::ok);}
 mp4_control_passive_clear();assert(roots.empty());
}
