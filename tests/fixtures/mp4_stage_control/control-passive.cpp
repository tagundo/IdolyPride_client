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
struct Mp4TimelineContext{Director*director=nullptr;size_t clip_count=0,track_count=0;void*clips[4]{},*clip_tracks[4]{},*tracks[4]{};};
bool main_thread=true,graph_valid=true,node_valid=true,weak_fail=false;size_t graph_reads=0;
uintptr_t image_base=0;bool pins=true,current=true,schema=true,force_retain_failure=false,callback_ok=true;uint32_t next_handle=0;std::unordered_map<uint32_t,void*> roots;
Track authored_track;Array authored_tracks,authored_clips,authored_children;bool catalogue_current=true;
GO parent_go,source_go;Timeline parent_asset,child_asset,excluded_asset;Director parent,child,first;Asset asset;Clip clip;Array components;int track=0,unknown=0;size_t calls=0;std::string scenario;bool queried_recursive=false;
uint32_t mp4_retain(void*p){if(force_retain_failure)return 0;roots[++next_handle]=p;return next_handle;}void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
bool game_call(){return main_thread;}bool mp4_stage_other_pins_ready(){return pins;}bool mp4_control_source_pins_ready(){return pins;}void*mp4_timeline_class(const Pin&){return &unknown;}
void*mp4_type_get_object(void*){return &unknown;}
bool mp4_type_is(void*p,const char*t){return p&&(!std::strcmp(static_cast<Object*>(p)->type,t)||(!std::strcmp(t,"UnityEngine.Playables.PlayableAsset")&&!std::strcmp(static_cast<Object*>(p)->type,"UnityEngine.Timeline.TimelineAsset")));}bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_timeline_current(const Mp4TimelineContext&){return current;}
bool mp4_timeline_exact(void*p,const Pin&pin){return &pin==&mp4_stage_other_pins.control_asset&&p&&mp4_type_is(p,"UnityEngine.Timeline.ControlPlayableAsset");}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){
if(off==16&&sizeof(T)==sizeof(uintptr_t)){auto x=reinterpret_cast<uintptr_t>(p);std::memcpy(&v,&x,sizeof x);return true;}
if(off==0&&sizeof(T)==sizeof(uintptr_t)){std::memcpy(&v,p,sizeof(uintptr_t));return true;}
if((off==59||off==80||off==81||off==82)&&sizeof(T)==1){auto&a=static_cast<Asset*>(p)->cache;auto x=off==59?a.active:off==80?a.loop:off==81?a.controlling_directors:a.controlling_particles;std::memcpy(&v,&x,1);return true;}
if(off==64&&sizeof(T)==sizeof(void*)){auto x=static_cast<Asset*>(p)->cache.controlled_asset;std::memcpy(&v,&x,sizeof x);return true;}
if(off==72&&sizeof(T)==sizeof(double)){auto x=static_cast<Asset*>(p)->cache.duration;std::memcpy(&v,&x,sizeof x);return true;}
if(off==160&&sizeof(T)==sizeof(void*)){auto x=static_cast<Timeline*>(p)->tracks;std::memcpy(&v,&x,sizeof x);return true;}if((off==96||off==80)&&sizeof(T)==sizeof(void*)){auto x=off==96?static_cast<Track*>(p)->clips:static_cast<Track*>(p)->children;std::memcpy(&v,&x,sizeof x);return true;}if(off==40&&sizeof(T)==sizeof(void*)){auto x=static_cast<Clip*>(p)->asset;std::memcpy(&v,&x,sizeof x);return true;}if(off==56&&sizeof(T)==1){auto x=static_cast<Asset*>(p)->update;std::memcpy(&v,&x,1);return true;}return false;}
bool mp4_control_schema(void*){return schema;}namespace mp4ctl{struct Owner{void*asset=nullptr;};}
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
#include "control-passive.cpp"
bool proof_good=true;uint64_t proof_epoch=77,proof_job=99;
bool logical_proof(void*ctx,const Mp4ControlPassiveImage&raw,uint64_t receipt,const mp4ctl::Cache&logical,uint64_t epoch,uint64_t job){
 assert(ctx==&asset&&receipt&&raw.before.duration==0&&raw.after.duration==25&&raw.after.controlled_asset==&child_asset);
 if(scenario=="promote_proof_mutates")++asset.cache.duration;
 if(scenario=="promote_owner_lost")parent.go=&source_go;
 return proof_good&&epoch==proof_epoch&&job==proof_job&&logical.duration==17;
}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];parent.go=&parent_go;asset.source=&source_go;asset.input.source_default=&source_go;asset.cache.controlled_asset=&parent_asset;mp4_stage_other_pins.control_create.rva=17;mp4_stage_other_pins.graph_resolver.rva=reinterpret_cast<uintptr_t>(resolver);mp4_stage_profile.component_gameobject.rva=reinterpret_cast<uintptr_t>(get_go);mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(node_graph);
 Mp4ControlPassiveTicket ticket;const mp4ctl::Handle graph{42,2,0},result{101,2,0};
 if(scenario=="before_pins")pins=false;else if(scenario=="before_method")method.entry=18;else if(scenario=="before_graph")graph_valid=false;else if(scenario=="before_schema")schema=false;else if(scenario=="before_owner")parent.go=&source_go;else if(scenario=="before_dead_asset")asset.alive=false;else if(scenario=="before_retain")force_retain_failure=true;else if(scenario=="before_foreign")main_thread=false;
 const bool initial=scenario.rfind("before_",0)!=0;
 assert(mp4_control_passive_before(&asset,graph,&parent_go,&method,ticket)==initial);
 if(!initial){ticket.clear();assert(roots.empty());return 0;}
 asset.cache.duration=25;asset.cache.controlled_asset=&child_asset;
 if(scenario=="after_source")asset.source=&parent_go;else if(scenario=="after_input")asset.input.seed=22;else if(scenario=="after_graph")node_valid=false;else if(scenario=="after_weak")weak_fail=true;else if(scenario=="after_foreign")mp4_control_passive_foreign();else if(scenario=="after_nan")asset.cache.duration=__builtin_nan("");
 const bool published=scenario.rfind("after_",0)!=0&&scenario!="original_exception";
 assert(mp4_control_passive_after(ticket,result,scenario!="original_exception")==published);ticket.clear();
 if(!published){assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));mp4_control_passive_clear();assert(roots.empty());return 0;}
 assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));
 if(scenario.rfind("promote_",0)==0){
  uint64_t raw_receipt=0,logical_receipt=0;Mp4ControlPassiveImage raw{};
  assert(mp4_control_passive_raw_receipted(&asset,&parent,&parent_go,graph,result,&raw_receipt,&raw)&&raw_receipt);
  auto desired=asset.cache;desired.duration=17;desired.controlled_asset=&parent_asset;asset.cache=desired;
  assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));
  assert(mp4_control_passive_raw_receipted(&asset,&parent,&parent_go,graph,result,&raw_receipt));
  Mp4ControlLogicalProof proof=logical_proof;void*ctx=&asset;uint64_t epoch=77,job=99;
  if(scenario=="promote_missing_proof")proof=nullptr;
  if(scenario=="promote_wrong_epoch")epoch=78;
  if(scenario=="promote_wrong_job")job=100;
  if(scenario=="promote_bad_proof")proof_good=false;
  if(scenario=="promote_weak_failure")weak_fail=true;
  if(scenario=="promote_sequence_limit")mp4_control_logical_sequence=~uint64_t(0);
  if(scenario=="promote_wrong_factory")++raw_receipt;
  const bool ok=scenario=="promote_normal"||scenario=="promote_idempotent"||scenario=="promote_raw_after_expired"||scenario=="promote_logical_expired"||scenario=="promote_changed_cache"||scenario=="promote_next_factory";
  assert(mp4_control_passive_promote_source(&asset,&parent,&parent_go,graph,result,raw_receipt,desired,epoch,job,proof,ctx,&logical_receipt)==ok);
  if(!ok){assert(!logical_receipt&&!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));mp4_control_passive_clear();assert(roots.empty());return 0;}
  assert(logical_receipt&&mp4_control_passive_bank[0].image.after.duration==25&&mp4_control_passive_bank[0].image.before.duration==0);
  uint64_t checked_raw=0,checked_logical=0;assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result,&checked_raw,&checked_logical)&&checked_raw==raw_receipt&&checked_logical==logical_receipt);
  if(scenario=="promote_idempotent"){auto count=roots.size();uint64_t again=0;assert(mp4_control_passive_promote_source(&asset,&parent,&parent_go,graph,result,raw_receipt,desired,epoch,job,proof,ctx,&again)&&again==logical_receipt&&roots.size()==count);}
  if(scenario=="promote_raw_after_expired"){for(auto&v:roots)if(v.second==&child_asset)v.second=nullptr;assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));}
  if(scenario=="promote_logical_expired"){for(auto&v:roots)if(v.second==&parent_asset)v.second=nullptr;assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));}
  if(scenario=="promote_changed_cache"){++asset.cache.duration;assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));}
  if(scenario=="promote_next_factory"){Mp4ControlPassiveTicket next;assert(mp4_control_passive_before(&asset,graph,&parent_go,&method,next));assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));asset.cache.duration=30;asset.cache.controlled_asset=&child_asset;assert(mp4_control_passive_after(next,result,true));next.clear();assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result,&checked_raw,&checked_logical)&&checked_raw!=raw_receipt&&!checked_logical);}
  mp4_control_passive_clear();assert(roots.empty());return 0;
 }
 if(scenario=="weak_expired"){for(auto&v:roots)if(v.second==&asset)v.second=nullptr;}
 else if(scenario=="historical_expired"){for(auto&v:roots)if(v.second==&parent_asset)v.second=nullptr;}
 else if(scenario=="input_changed")++asset.input.seed;
 else if(scenario=="cache_changed")++asset.cache.duration;
 else if(scenario=="graph_changed")graph_valid=false;
 else if(scenario=="source_changed")asset.source=&parent_go;
 else if(scenario=="owner_changed")parent.go=&source_go;
 else if(scenario=="foreign_dirty")mp4_control_passive_foreign();
 else if(scenario=="original_retry_exception"){
  Mp4ControlPassiveTicket second;assert(mp4_control_passive_before(&asset,graph,&parent_go,&method,second));
  assert(!mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));
  assert(!mp4_control_passive_after(second,{},false));second.clear();
 }
 const bool remains=scenario=="normal"||scenario=="historical_expired"||scenario=="reuse";
 assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result)==remains);
 if(scenario=="reuse"){
  Mp4ControlPassiveTicket second;assert(mp4_control_passive_before(&asset,graph,&parent_go,&method,second));
  assert(mp4_control_passive_after(second,result,true));second.clear();assert(mp4_control_passive_receipted(&asset,&parent,&parent_go,graph,result));
 }
 mp4_control_passive_clear();assert(roots.empty());
}
