#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <cstdio>
using Method=const void;
namespace mp4game {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct PropertyName4{int32_t id=0;};struct PlayableGraph{void*handle=nullptr;int32_t version=0,padding=0;};struct Layout{size_t controller_master=32,controller_directors=40,player_binder=88,binder_actors=64;};}
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4stage {struct Layout{static constexpr size_t clip_asset=40,timeline_tracks=32,track_children=72,track_clips=128;};}
struct Object{alignas(8) uint8_t bytes[256]{};std::string type;bool alive=true,muted=false;std::vector<void*>values;std::vector<uint8_t>raw;size_t raw_count=0;void*asset=nullptr,*graph=nullptr,*go=nullptr;int mode=1;};
std::vector<std::unique_ptr<Object>>objects;
std::unordered_map<uint32_t,void*>handles;uint32_t next_handle=1;
Object*type_token=nullptr,*component_token=nullptr;uintptr_t image_base=1;bool mp4_source_verified=true,mp4_actor_source_verified=true;
Object*make(const char*type){auto p=std::make_unique<Object>();p->type=type;auto*q=p.get();objects.push_back(std::move(p));return q;}
template<class T>void put(void*p,size_t at,T v){assert(p&&at+sizeof v<=256);std::memcpy(static_cast<Object*>(p)->bytes+at,&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!p||at+sizeof out>256)return false;std::memcpy(&out,static_cast<Object*>(p)->bytes+at,sizeof out);return true;}
bool game_call(){return true;}
bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_type_is(void*p,const char*name){if(!p)return false;const auto&t=static_cast<Object*>(p)->type;
 return t==name||(std::string(name)=="System.Array"&&t.size()>2&&t.substr(t.size()-2)=="[]")
  ||(std::string(name)=="UnityEngine.Timeline.TrackAsset"&&(t=="UnityEngine.Timeline.ControlTrack"||t=="GroupTrack"||t=="PlainTrack"));}
bool mp4_exact_type(void*p,const char*name){return p&&static_cast<Object*>(p)->type==name;}
uint32_t mp4_retain(void*p){if(!p)return 0;const auto h=next_handle++;handles[h]=p;return h;}
void*weak_get(uint32_t h){auto it=handles.find(h);return it==handles.end()?nullptr:it->second;}
void weak_free(uint32_t h){assert(handles.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(mp4_retain(p)){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
bool mp4_prefix(const mp4game::Binding&){return true;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return true;}
struct TypePin{mp4game::Binding binding{1,{}};};struct{TypePin director_component;}mp4_stage_other_pins;
void*mp4_timeline_class(const TypePin&){return type_token;}
void*mp4_type_get_object(void*p);
bool mp4_root_track_field(void*,const char*,size_t){return true;}
size_t mp4_array_length(void*p){return p?(static_cast<Object*>(p)->raw.empty()?static_cast<Object*>(p)->values.size():static_cast<Object*>(p)->raw_count):0;}
void*mp4_array_data(void*p){if(!p)return nullptr;auto&o=*static_cast<Object*>(p);return !o.raw.empty()?static_cast<void*>(o.raw.data()):(!o.values.empty()?o.values.data():nullptr);}
bool mp4_actor_mapped(void*p,size_t,bool){return p!=nullptr;}
bool mp4_actor_list(void*p,void***values,size_t*count,size_t cap){void*array=nullptr;int32_t n=0;
 if(!mp4_actor_field(p,16,array)||!mp4_actor_field(p,24,n)||n<0||size_t(n)>cap||!array||mp4_array_length(array)<size_t(n))return false;
 *values=static_cast<void**>(mp4_array_data(array));*count=size_t(n);return !n||*values;}
void*get_asset(void*p,Method*){return static_cast<Object*>(p)->asset;}
void graph_injected(void*p,mp4game::PlayableGraph*out,Method*){*out={static_cast<Object*>(p)->graph,2,0};}
bool valid_graph(mp4game::PlayableGraph*g,Method*){return g&&g->handle&&mp4_alive(g->handle);}
int32_t get_mode(void*p,Method*){return static_cast<Object*>(p)->mode;}
bool muted(void*p,Method*){return static_cast<Object*>(p)->muted;}
struct Reference{bool valid=false;void*value=nullptr;};std::unordered_map<int32_t,Reference>references;
void*get_reference(void*,mp4game::PropertyName4 name,bool*valid,Method*){const auto value=references[name.id];*valid=value.valid;return value.value;}
void*get_go(void*p,Method*){return static_cast<Object*>(p)->go;}
void*first_director(void*p,void*,Method*){auto*go=static_cast<Object*>(static_cast<Object*>(p)->go);return go->values.empty()?nullptr:go->values[0];}
std::unordered_map<void*,std::vector<void*>>descendants;
void*components(void*go,void*type,bool,bool hierarchy,bool,bool,void*,Method*){auto*array=make("UnityEngine.Component[]");auto all=static_cast<Object*>(go)->values;
 if(hierarchy){auto&deep=descendants[go];all.insert(all.end(),deep.begin(),deep.end());}
 for(void*v:all)if(type==component_token||mp4_type_is(v,"UnityEngine.Playables.PlayableDirector"))array->values.push_back(v);
 return array;}
bool mp4_actor_graph_mode(mp4actor::Handle*graph,int32_t*mode){if(!graph||!graph->handle||!mp4_alive(reinterpret_cast<void*>(graph->handle)))return false;*mode=static_cast<Object*>(reinterpret_cast<void*>(graph->handle))->mode;return *mode>=0&&*mode<=3;}
struct Profile{mp4game::Binding director_get_asset,director_get_reference,director_graph_injected,director_get_mode,track_muted_hierarchy,graph_valid;}mp4_profile;
struct{mp4game::Binding get_game_object,get_components_internal,playable_valid,script_instance,playable_graph_get,graph_root_count,graph_root;}mp4_actor_profile;
struct{mp4game::Binding component;}mp4_cam_types;
void*mp4_resolved_type_class(const mp4game::Binding&,const char*,const char*){return component_token;}
struct{mp4game::Binding output_valid;}mp4_world_profile;struct{mp4game::Binding source;}mp4_output_pins;
void*mp4_type_get_object(void*p){return reinterpret_cast<uintptr_t>(p)==image_base+mp4_cam_types.component.rva?component_token:type_token;}
bool handle_valid(mp4actor::Handle*h,Method*){return h&&h->handle&&mp4_alive(reinterpret_cast<void*>(h->handle));}
void playable_graph(mp4actor::Handle*h,mp4actor::Handle*out,Method*){*out={reinterpret_cast<uintptr_t>(static_cast<Object*>(reinterpret_cast<void*>(h->handle))->graph),2,0};}
int32_t graph_roots(mp4actor::Handle*h,Method*){return int32_t(static_cast<Object*>(reinterpret_cast<void*>(h->handle))->values.size());}
void graph_root_get(mp4actor::Handle*h,int32_t i,mp4actor::Handle*out,Method*){*out={reinterpret_cast<uintptr_t>(static_cast<Object*>(reinterpret_cast<void*>(h->handle))->values.at(size_t(i))),2,0};}
void output_source(mp4actor::Handle*h,mp4actor::Handle*out,Method*){*out={reinterpret_cast<uintptr_t>(static_cast<Object*>(reinterpret_cast<void*>(h->handle))->values.at(0)),2,0};}
void*mp4_timeline_script(mp4actor::Handle h){return static_cast<Object*>(reinterpret_cast<void*>(h.handle))->asset;}
struct StateApi{decltype(&handle_valid)graph_valid=handle_valid,playable_valid=handle_valid;decltype(&graph_roots)graph_root_count=graph_roots;decltype(&graph_root_get)graph_root=graph_root_get;};
StateApi mp4_actor_state_api(){return {};}
struct{mp4game::Binding component_get_component;}mp4_camera_owner_profile;
struct Api{decltype(&get_asset)director_get_asset=get_asset;decltype(&get_reference)director_get_reference=get_reference;decltype(&graph_injected)director_graph_injected=graph_injected;decltype(&get_mode)director_get_mode=get_mode;decltype(&muted)track_muted_hierarchy=muted;decltype(&valid_graph)graph_valid=valid_graph;}mp4_api;
// ACTUAL_FRESH_CONTROL_ROSTER
Object*list(const char*array_type,std::vector<void*>values){auto*a=make(array_type);a->values=std::move(values);auto*l=make("System.Collections.Generic.List`1");put(l,16,static_cast<void*>(a));put(l,24,int32_t(a->values.size()));put(l,28,int32_t(1));return l;}
// Shipped metadata: m_Tracks/m_Children are List<ScriptableObject>, m_Clips List<TimelineClip>.
Object*asset(){auto*a=make("UnityEngine.Timeline.TimelineAsset");put(a,32,static_cast<void*>(list("UnityEngine.ScriptableObject[]",{})));return a;}
Object*director(Object*a,int component_mode=1,int graph_mode=1){auto*d=make("UnityEngine.Playables.PlayableDirector");d->asset=a;d->mode=component_mode;auto*n=make("native");put(n,8,int32_t(objects.size()));put(d,16,reinterpret_cast<uintptr_t>(n));auto*g=make("graph");g->mode=graph_mode;d->graph=g;auto*go=make("UnityEngine.GameObject");go->values={d};d->go=go;return d;}
Object*control(Object*parent,Object*target,bool hierarchy=false){auto*c=make("UnityEngine.Timeline.ControlPlayableAsset");put(c,24,mp4game::PropertyName4{int32_t(objects.size())});put(c,32,static_cast<void*>(target));put(c,56,uint8_t(1));put(c,58,uint8_t(hierarchy));
 auto*clip=make("UnityEngine.Timeline.TimelineClip");put(clip,40,static_cast<void*>(c));put(clip,48,double(10));put(clip,56,double(1));auto*t=make("UnityEngine.Timeline.ControlTrack");put(t,72,static_cast<void*>(list("UnityEngine.ScriptableObject[]",{})));put(t,128,static_cast<void*>(list("UnityEngine.Timeline.TimelineClip[]",{clip})));
 void*tracks=nullptr,*array=nullptr;assert(mp4_actor_field(parent->asset,32,tracks)&&mp4_actor_field(tracks,16,array));static_cast<Object*>(array)->values.push_back(t);put(tracks,24,int32_t(static_cast<Object*>(array)->values.size()));return c;}
void configure(){type_token=make("System.Type");component_token=make("System.Type");mp4_cam_types.component.rva=12345;
 mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(&playable_graph)-image_base;
 mp4_world_profile.output_valid.rva=reinterpret_cast<uintptr_t>(&handle_valid)-image_base;
 mp4_output_pins.source.rva=reinterpret_cast<uintptr_t>(&output_source)-image_base;
 mp4_profile.director_get_asset.rva=reinterpret_cast<uintptr_t>(&get_asset)-image_base;
 mp4_profile.director_get_reference.rva=reinterpret_cast<uintptr_t>(&get_reference)-image_base;
 mp4_profile.director_graph_injected.rva=reinterpret_cast<uintptr_t>(&graph_injected)-image_base;
 mp4_profile.director_get_mode.rva=reinterpret_cast<uintptr_t>(&get_mode)-image_base;
 mp4_profile.track_muted_hierarchy.rva=reinterpret_cast<uintptr_t>(&muted)-image_base;
 mp4_profile.graph_valid.rva=reinterpret_cast<uintptr_t>(&valid_graph)-image_base;
 mp4_actor_profile.get_game_object.rva=reinterpret_cast<uintptr_t>(&get_go)-image_base;
 mp4_actor_profile.get_components_internal.rva=reinterpret_cast<uintptr_t>(&components)-image_base;
 mp4_camera_owner_profile.component_get_component.rva=reinterpret_cast<uintptr_t>(&first_director)-image_base;
}
void native_component(Object*c){auto*n=make("native");put(n,8,int32_t(objects.size()));put(c,16,reinterpret_cast<uintptr_t>(n));}
Object*raw_array(size_t stride,size_t count){auto*a=make("System.ValueType[]");a->raw.resize(stride*count);a->raw_count=count;return a;}
struct PathFixture{Object*owner=nullptr,*declared=nullptr,*binder=nullptr,*cache=nullptr,*array=nullptr,*playable=nullptr,*script=nullptr,*graph=nullptr,*output=nullptr;};
PathFixture path(Object*root,Object*child){PathFixture p{};p.owner=make("Solis.Common.PathBindingAnimation");native_component(p.owner);p.owner->go=root->go;static_cast<Object*>(root->go)->values.push_back(p.owner);
 p.binder=make("Solis.Common.PathBinder.PathBinderTimeline");p.binder->go=child->go;native_component(p.binder);put(p.binder,32,static_cast<void*>(child));
 p.graph=make("pathgraph");p.graph->mode=0;p.playable=make("playable");p.playable->graph=p.graph;p.graph->values={p.playable};p.script=make("Solis.Common.PathBindingTimelinePlayable");put(p.script,16,static_cast<void*>(child));p.playable->asset=p.script;
 p.output=make("output");p.output->values={p.playable};put(p.binder,48,mp4actor::Handle{reinterpret_cast<uintptr_t>(p.output),2,0});put(p.binder,64,mp4actor::Handle{reinterpret_cast<uintptr_t>(p.playable),2,0});
 auto*key=make("System.String");p.declared=raw_array(16,1);void*k=key,*b=p.binder;std::memcpy(p.declared->raw.data(),&k,8);std::memcpy(p.declared->raw.data()+8,&b,8);put(p.owner,32,static_cast<void*>(p.declared));
 p.array=raw_array(24,1);std::memcpy(p.array->raw.data(),&k,8);const mp4actor::Handle node{reinterpret_cast<uintptr_t>(p.playable),2,0};std::memcpy(p.array->raw.data()+8,&node,16);
 p.cache=make("System.Collections.Generic.List`1");put(p.cache,16,static_cast<void*>(p.array));put(p.cache,24,int32_t(1));put(p.cache,28,int32_t(1));put(p.owner,40,static_cast<void*>(p.cache));return p;}
int main(int argc,char**argv){assert(argc==2);configure();const std::string mode=argv[1];
 auto*a=director(asset());auto*b=director(asset(),1,3);auto*source=make("UnityEngine.GameObject");source->values={b};auto*c=control(a,source);
 auto*timeline=make("Solis.Common.Live.SolisLiveTimelineController");put(timeline,32,static_cast<void*>(a));put(timeline,40,static_cast<void*>(list("UnityEngine.Playables.PlayableDirector[]",{a})));
 if(mode=="dsp"){a->mode=0;static_cast<Object*>(a->graph)->mode=0;b->mode=0;static_cast<Object*>(b->graph)->mode=0;}
 if(mode=="hierarchy"){source->values.clear();descendants[source]={b};put(c,58,uint8_t(1));}
 if(mode=="valid_null"){mp4game::PropertyName4 name{};assert(mp4_actor_field(c,24,name));references[name.id]={true,nullptr};}
 if(mode=="same_asset")b->asset=a->asset;
 if(mode=="self_guard"){put(c,32,a->go);}
 if(mode=="prefab")put(c,40,static_cast<void*>(source));
 if(mode=="manual_orphan"){void*l=nullptr,*array=nullptr;assert(mp4_actor_field(timeline,40,l)&&mp4_actor_field(l,16,array));static_cast<Object*>(array)->values.push_back(b);put(l,24,int32_t(2));put(c,56,uint8_t(0));}
 if(mode=="cycle"){auto*back=make("UnityEngine.GameObject");back->values={a};control(b,back);}
 if(mode=="born")b->graph=nullptr;
 PathFixture pf{};if(mode.rfind("path_",0)==0){put(c,56,uint8_t(0));b->mode=3;static_cast<Object*>(b->graph)->mode=3;pf=path(a,b);}
 auto r=std::make_unique<Mp4FreshControlRoster>();const bool built=mp4_fresh_control_roster_build(timeline,*r);
 const bool failure=mode=="prefab"||mode=="manual_orphan"||mode=="cycle";
 if(failure){assert(!built);assert(r->root_count);assert(!mp4_fresh_control_roster_build(timeline,*r));}
 else{
  if(!built){std::fprintf(stderr,"%s\n",r->error);}
  assert(built&&mp4_fresh_control_roster_current(*r));
  const size_t expected=mode=="valid_null"||mode=="same_asset"||mode=="self_guard"?1:2;assert(r->count==expected);
  const int original=mode=="dsp"?0:1;
  assert(r->nodes[0].graph_mode==original&&!r->nodes[0].controlled&&r->nodes[0].desired_mode==1);
  static_cast<Object*>(a->graph)->mode=3;assert(mp4_fresh_control_roster_current(*r));assert(r->nodes[0].graph_mode==original);
  if(expected==2)assert(r->nodes[1].controlled&&r->nodes[1].director_mode==(mode=="dsp"?0:(mode.rfind("path_",0)==0?3:1))&&r->nodes[1].desired_mode==3);
  if(mode=="dsp"){a->mode=1;static_cast<Object*>(a->graph)->mode=1;assert(mp4_fresh_control_roster_current(*r));b->mode=3;static_cast<Object*>(b->graph)->mode=3;assert(mp4_fresh_control_roster_current(*r));r->converted=true;assert(mp4_fresh_control_roster_current(*r));b->mode=0;assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="unreturned_conversion"){r->converted=true;assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="born"){assert(r->nodes[1].graph_mode==-1);auto*g=make("graph");g->mode=3;b->graph=g;assert(mp4_fresh_control_roster_current(*r));}
  if(mode=="changed_components"){auto*other=director(asset(),1,3);source->values={other};assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="changed_reference"){mp4game::PropertyName4 name{};assert(mp4_actor_field(c,24,name));references[name.id]={true,nullptr};assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="retired_reborn"){static_cast<Object*>(b->graph)->alive=false;assert(mp4_fresh_control_roster_current(*r));auto*g=make("graph");g->mode=3;b->graph=g;assert(mp4_fresh_control_roster_current(*r));}
  if(mode=="foreign_root"){auto*g=make("graph");g->mode=1;a->graph=g;assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="foreign_asset"){b->asset=asset();assert(!mp4_fresh_control_roster_current(*r));}
  if(mode=="foreign_owner"){put(b,16,reinterpret_cast<uintptr_t>(make("alien-native")));assert(!mp4_fresh_control_roster_current(*r));}
  if(mode.rfind("path_",0)==0){assert(r->path_graph_count==1&&r->path_owner_count==1&&r->path_binding_count==1);assert(r->path_graphs[0].original_mode==0&&r->path_graphs[0].desired_mode==1);assert(r->nodes[1].controlled);
   pf.graph->mode=3;assert(mp4_fresh_control_roster_current(*r));
   if(mode=="path_conversion"){a->mode=1;b->mode=3;static_cast<Object*>(b->graph)->mode=3;pf.graph->mode=1;r->converted=true;assert(mp4_fresh_control_roster_current(*r));pf.graph->mode=0;assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_cache"){put(pf.cache,28,int32_t(2));assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_target"){put(pf.script,16,static_cast<void*>(a));assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_output"){pf.output->values={make("otherplayable")};assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_registry"){void*other=make("otherbinder");std::memcpy(pf.declared->raw.data()+8,&other,8);assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_roots"){pf.graph->values.push_back(make("foreignroot"));assert(!mp4_fresh_control_roster_current(*r));}
   if(mode=="path_graph"){pf.playable->graph=make("foreigngraph");assert(!mp4_fresh_control_roster_current(*r));}
  }
  if(mode=="changed_clip"){put(c,58,uint8_t(1));assert(!mp4_fresh_control_roster_current(*r));}
 }
 assert(mp4_fresh_control_roster_clear(*r));assert(handles.empty());
}
