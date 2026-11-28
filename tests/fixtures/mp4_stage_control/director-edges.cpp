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
struct Clip:Object{void*asset=nullptr;Clip():Object{"UnityEngine.Timeline.TimelineClip"}{}};struct Track:Object{Array*clips=nullptr,*children=nullptr;Track():Object{"UnityEngine.Timeline.TrackAsset"}{}};struct Array{void*values[65]{};size_t count=0;};
struct Binding{uintptr_t rva=0;};struct Pin{Binding binding{};};
struct{Pin director_component,control_asset;}mp4_stage_other_pins;
struct{Binding components_internal,component_gameobject;}mp4_stage_profile;
struct{Binding component_get_component;}mp4_camera_owner_profile;
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=40,timeline_tracks=160,track_clips=96,track_children=80;};}
struct Mp4TimelineContext{Director*director=nullptr;size_t clip_count=0,track_count=0;void*clips[4]{},*clip_tracks[4]{},*tracks[4]{};};
uintptr_t image_base=0;bool pins=true,current=true,schema=true,force_retain_failure=false,callback_ok=true;uint32_t next_handle=0;std::unordered_map<uint32_t,void*> roots;
Track authored_track;Array authored_tracks,authored_clips,authored_children;bool catalogue_current=true;
GO parent_go,source_go;Timeline parent_asset,child_asset,excluded_asset;Director parent,child,first;Asset asset;Clip clip;Array components;int track=0,unknown=0;size_t calls=0;std::string scenario;bool queried_recursive=false;
uint32_t mp4_retain(void*p){if(force_retain_failure)return 0;roots[++next_handle]=p;return next_handle;}void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
bool mp4_stage_other_pins_ready(){return pins;}void*mp4_timeline_class(const Pin&){return &unknown;}
void*mp4_type_get_object(void*){return &unknown;}
bool mp4_type_is(void*p,const char*t){return p&&!std::strcmp(static_cast<Object*>(p)->type,t);}bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
bool mp4_timeline_current(const Mp4TimelineContext&){return current;}
bool mp4_timeline_exact(void*p,const Pin&pin){return &pin==&mp4_stage_other_pins.control_asset&&p&&mp4_type_is(p,"UnityEngine.Timeline.ControlPlayableAsset");}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){if(off==160&&sizeof(T)==sizeof(void*)){auto x=static_cast<Timeline*>(p)->tracks;std::memcpy(&v,&x,sizeof x);return true;}if((off==96||off==80)&&sizeof(T)==sizeof(void*)){auto x=off==96?static_cast<Track*>(p)->clips:static_cast<Track*>(p)->children;std::memcpy(&v,&x,sizeof x);return true;}if(off==40&&sizeof(T)==sizeof(void*)){auto x=static_cast<Clip*>(p)->asset;std::memcpy(&v,&x,sizeof x);return true;}if(off==56&&sizeof(T)==1){auto x=static_cast<Asset*>(p)->update;std::memcpy(&v,&x,1);return true;}return false;}
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
#include "director-edges.cpp"
bool authored_current(void*,const Mp4ControlAuthoredSource&s){return catalogue_current&&s.director==&parent&&s.asset==&parent_asset&&s.owner==&parent_go&&s.epoch==11&&s.root_asset==22;}
bool on_edge(void*p,void*c,void*){assert(p==&parent&&c==&child);assert(roots.size()>=6);++calls;if(scenario=="authored_metadata_changed")authored_clips.count=0;if(scenario=="authored_catalogue_lost")catalogue_current=false;if(scenario=="changed_source")asset.source=&parent_go;if(scenario=="changed_child_asset")child.asset=&excluded_asset;if(scenario=="source_lost")current=false;if(scenario=="changed_input")asset.input.seed=8;return callback_ok;}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];parent.go=&parent_go;parent.asset=&parent_asset;child.go=&source_go;child.asset=&child_asset;first.go=&parent_go;first.asset=&parent_asset;asset.source=&source_go;clip.asset=&asset;components.values[0]=&child;components.count=1;mp4_stage_profile.components_internal.rva=reinterpret_cast<uintptr_t>(get_components);mp4_stage_profile.component_gameobject.rva=reinterpret_cast<uintptr_t>(get_go);mp4_camera_owner_profile.component_get_component.rva=reinterpret_cast<uintptr_t>(get_first);Mp4TimelineContext c{};c.director=&parent;c.clip_count=1;c.track_count=1;c.clips[0]=&clip;c.clip_tracks[0]=&track;c.tracks[0]=&track;
 if(scenario=="hierarchy")asset.input.hierarchy=1;
 else if(scenario=="disabled")asset.update=0;
 else if(scenario=="null_source")asset.source=nullptr;
 else if(scenario=="self_guard")asset.source=&parent_go;
 else if(scenario=="same_asset")child.asset=&parent_asset;
 else if(scenario=="first_asset_differs"){first.asset=&excluded_asset;child.asset=&parent_asset;}
 else if(scenario=="no_directors")components.count=0;
 else if(scenario=="unknown_clip")clip.asset=&source_go;
 else if(scenario=="pins_lost")pins=false;
 else if(scenario=="source_not_current")current=false;
 else if(scenario=="bad_track")c.track_count=0;
 else if(scenario=="duplicate_track"){c.track_count=2;c.tracks[1]=&track;}
 else if(scenario=="bad_schema")schema=false;
 else if(scenario=="bad_flag")asset.update=2;
 else if(scenario=="prefab")asset.input.prefab=&source_go;
 else if(scenario=="bad_hierarchy")asset.input.hierarchy=2;
 else if(scenario=="dead_source")source_go.alive=false;
 else if(scenario=="dead_owner")parent_go.alive=false;
 else if(scenario=="dead_first")first.alive=false;
 else if(scenario=="duplicate_child"){components.count=2;components.values[1]=&child;}
 else if(scenario=="null_child")components.values[0]=nullptr;
 else if(scenario=="non_director")components.values[0]=&source_go;
 else if(scenario=="null_child_asset")child.asset=nullptr;
 else if(scenario=="self_child"){components.values[0]=&parent;first.asset=&excluded_asset;}
 else if(scenario=="callback_reject")callback_ok=false;
 else if(scenario=="retain_failure")force_retain_failure=true;
 else if(scenario=="empty")c.clip_count=0;
 else if(scenario=="too_many")c.clip_count=4097;
 else if(scenario=="sequence_exhausted")mp4_control_edge_sequence=~uint64_t(0);

 if(scenario.rfind("authored_",0)==0){
  parent_asset.tracks=&authored_tracks;authored_tracks.values[0]=&authored_track;authored_tracks.count=1;
  authored_track.clips=&authored_clips;authored_clips.values[0]=&clip;authored_clips.count=1;
  Mp4ControlAuthoredSource source{&parent,&parent_asset,&parent_go,11,22};
  if(scenario=="authored_unbuilt")current=false;
  if(scenario=="authored_no_graph")current=false;
  if(scenario=="authored_wrong_epoch")++source.epoch;
  if(scenario=="authored_wrong_owner")source.owner=&source_go;
  if(scenario=="authored_initial_catalogue_lost")catalogue_current=false;
  if(scenario=="authored_cycle"){authored_track.children=&authored_children;authored_children.values[0]=&authored_track;authored_children.count=1;}
  if(scenario=="authored_empty")authored_tracks.count=0;
  if(scenario=="authored_duplicate_clip"){authored_clips.values[1]=&clip;authored_clips.count=2;}
  if(scenario=="authored_duplicate_track"){authored_tracks.values[1]=&authored_track;authored_tracks.count=2;}
  uint64_t receipt=99;bool ok=scenario=="authored_normal"||scenario=="authored_unbuilt"||scenario=="authored_no_graph"||scenario=="authored_empty";
  assert(mp4_control_collect_authored_edges(source,authored_current,nullptr,on_edge,nullptr,&receipt)==ok);
  assert((receipt!=0)==ok);assert(roots.size()==(mp4_control_director_type?1u:0u));return 0;
 }
 uint64_t receipt=99;const bool ok=scenario=="normal"||scenario=="hierarchy"||scenario=="disabled"||scenario=="null_source"||scenario=="self_guard"||scenario=="same_asset"||scenario=="first_asset_differs"||scenario=="no_directors"||scenario=="unknown_clip"||scenario=="empty";
 assert(mp4_control_collect_edges(c,on_edge,nullptr,&receipt)==ok);assert((receipt!=0)==ok);assert(roots.size()==(mp4_control_director_type?1u:0u));if(scenario=="hierarchy")assert(queried_recursive);if(scenario=="normal")assert(!queried_recursive);if(scenario=="normal"||scenario=="hierarchy"||scenario=="first_asset_differs")assert(calls==1);if(scenario=="disabled"||scenario=="null_source"||scenario=="self_guard"||scenario=="same_asset"||scenario=="no_directors"||scenario=="unknown_clip"||scenario=="empty")assert(calls==0);
}
