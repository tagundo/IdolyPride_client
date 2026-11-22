#include "mp4_actor_state.hpp"
#include <cassert>
#include <array>
#include <vector>
#include <map>
#include <memory>
#include <string>
#include <cstring>
#include <cstdlib>
#include <initializer_list>
#include <set>
namespace mp4actor=idoly_mp4_actor;
namespace mp4game{using PlayableGraph=idoly_mp4_actor::Handle;struct Layout{size_t player_director_controller=0x38,controller_directors=0x28;};struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct PropertyName4{int32_t id=0;};}
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=24;};}
using Method=const void;
struct Class{std::string name;};struct Object{std::array<unsigned char,1024>bytes{};Class*klass=nullptr;bool alive=true;std::vector<unsigned char>array;size_t length=0;};
std::map<void*,std::map<size_t,uintptr_t>> vtables;
std::vector<std::unique_ptr<Class>>classes;std::vector<std::unique_ptr<Object>>objects;std::map<void*,Object*>memory;std::map<std::string,Class*>class_names;
Class*cls(const char*n){auto it=class_names.find(n);if(it!=class_names.end())return it->second;auto p=std::make_unique<Class>();p->name=n;auto*r=p.get();classes.push_back(std::move(p));class_names[n]=r;return r;}
Object*object(const char*n){auto p=std::make_unique<Object>();p->klass=cls(n);auto*r=p.get();objects.push_back(std::move(p));memory[r]=r;return r;}
template<class T>void put(void*p,size_t at,T value){assert(memory.count(p)&&at+sizeof value<=1024);std::memcpy(memory[p]->bytes.data()+at,&value,sizeof value);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!memory.count(p)){auto i=vtables.find(p);if(i==vtables.end()||!i->second.count(at)||sizeof out!=8)return false;auto value=i->second[at];std::memcpy(static_cast<void*>(&out),&value,sizeof out);return true;}if(at+sizeof out>1024)return false;std::memcpy(&out,memory[p]->bytes.data()+at,sizeof out);return true;}
void*object_class(void*p){return memory.count(p)?memory[p]->klass:nullptr;}
bool mp4_exact_type(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));return c&&c->name==n;}
bool mp4_type_is(void*p,const char*n){return mp4_exact_type(p,n)||(!std::strcmp(n,"System.Array")&&memory.count(p)&&memory[p]->length!=size_t(-1));}
bool mp4_alive(void*p){return memory.count(p)&&memory[p]->alive;}
size_t mp4_array_length(void*p){return memory[p]->length;}void*mp4_array_data(void*p){return memory[p]->array.data();}
bool source_current=true,source_pins=true,inventory_ready=true,presentation_ready=true,temporal_catalog_ready=true,metadata_fields=true,reference_valid=false;
void*reference_value=nullptr;uintptr_t image_base=1;size_t source_collections=0,catalog_calls=0;
bool game_call(){return true;}bool mp4_timeline_pins_current(){return source_pins;}bool mp4_temporal_pins_ready(){return source_pins;}
bool mp4_prefix(const mp4game::Binding&){return source_pins;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_actor_refresh_maps(){return true;}bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}
uint32_t sequence=0;std::map<uint32_t,void*>roots;
uint32_t mp4_retain(void*p){if(!p)return 0;roots[++sequence]=p;return sequence;}void*weak_get(uint32_t t){auto i=roots.find(t);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t t){assert(roots.erase(t)==1);}
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(mp4_retain(p)){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
struct Mp4TimelineTypePin{const char*name;mp4game::Binding binding;};
void*mp4_timeline_class(const Mp4TimelineTypePin&p){return source_pins?cls(p.name):nullptr;}bool mp4_timeline_exact(void*p,const Mp4TimelineTypePin&t){return p&&object_class(p)==mp4_timeline_class(t);}
enum class Mp4TimelineProofPhase:uint8_t{admission,active,source_restore_plan,source_restored};enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4SceneWitness{void*player=nullptr,*director=nullptr;uint64_t generation=7;};
struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::admission;Mp4SceneWitness witness{};void*director=nullptr,*asset=nullptr;mp4actor::Handle graph{},compiled[4]{};void*tracks[4]{},*clips[8]{},*clip_tracks[8]{},*elements[8]{};size_t track_count=0,clip_count=0,element_count=0;};
struct Mp4TimelineRuntime{void*element=nullptr,*clip=nullptr,*track=nullptr;mp4actor::Handle playable{},mixer{};uint8_t kind=0;};
struct{Mp4TimelineTypePin clip={"RuntimeClip",{} };}mp4_timeline_pins;
bool mp4_timeline_current(const Mp4TimelineContext&c){return source_current&&c.witness.generation==7&&static_cast<unsigned>(c.phase)<4;}
bool mp4_root_track_field(void*,const char*,size_t){return metadata_fields;}
bool mp4_actor_list(void*p,void***out,size_t*n,size_t max){void*a=nullptr;int32_t count=0;if(!mp4_actor_field(p,16,a)||!a||!mp4_actor_field(p,24,count)||count<0||size_t(count)>max||mp4_array_length(a)<size_t(count))return false;*out=static_cast<void**>(mp4_array_data(a));*n=size_t(count);return true;}
struct Node{mp4actor::Handle graph{};void*script=nullptr;unsigned kind=0;std::vector<mp4actor::Handle>inputs;bool valid=true;};std::map<uintptr_t,Node>nodes;
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
std::vector<mp4actor::Handle>actor_roots;std::set<uintptr_t>factory_roles;uint32_t mp4_actor_talk_type=0;
bool valid(mp4actor::Handle*h,Method*){return nodes.count(h->handle)&&nodes[h->handle].valid&&h->version==1;}
int32_t count(mp4actor::Handle*h,Method*){return int32_t(nodes.at(h->handle).inputs.size());}
void input(mp4actor::Handle*h,int32_t i,mp4actor::Handle*out,Method*){*out=nodes.at(h->handle).inputs.at(size_t(i));}
int32_t graph_root_count(mp4actor::Handle*,Method*){return int32_t(actor_roots.size());}
void graph_root(mp4actor::Handle*,int32_t i,mp4actor::Handle*out,Method*){*out=actor_roots.at(size_t(i));}
void*job_data(mp4actor::Handle*h,Method*){return nodes[h->handle].kind==3?reinterpret_cast<void*>(h->handle):nullptr;}void*job_type(mp4actor::Handle*,Method*){return reinterpret_cast<void*>(uintptr_t(0xabc));}bool job_type_actor(void*p){return p==reinterpret_cast<void*>(uintptr_t(0xabc));}
struct StateApi{int32_t(*graph_root_count)(mp4actor::Handle*,Method*)=::graph_root_count;void(*graph_root)(mp4actor::Handle*,int32_t,mp4actor::Handle*,Method*)=::graph_root;void*(*job_data)(mp4actor::Handle*,Method*)=::job_data;void*(*job_type)(mp4actor::Handle*,Method*)=::job_type;bool(*job_type_is_actor)(void*)=job_type_actor;bool(*playable_valid)(mp4actor::Handle*,Method*)=valid;int32_t(*playable_input_count)(mp4actor::Handle*,Method*)=count;void(*playable_input)(mp4actor::Handle*,int32_t,mp4actor::Handle*,Method*)=input;};StateApi mp4_actor_state_api(){return {};}
void*mp4_temporal_script(mp4actor::Handle h){return nodes.count(h.handle)?nodes[h.handle].script:nullptr;}void*mp4_timeline_script(mp4actor::Handle h){return mp4_temporal_script(h);}
bool mp4_temporal_type(mp4actor::Handle h,size_t k){return nodes.count(h.handle)&&nodes[h.handle].kind==k&&nodes[h.handle].valid;}
bool mp4_temporal_link(mp4actor::Handle h,int32_t i,mp4actor::Handle child){return nodes.count(h.handle)&&i>=0&&size_t(i)<nodes[h.handle].inputs.size()&&mp4_actor_same_handle(nodes[h.handle].inputs[size_t(i)],child);}
void graph_get(mp4actor::Handle*h,mp4actor::Handle*out,Method*){*out=nodes[h->handle].graph;}
struct{struct{uint16_t actor_player=56;}fields;mp4actor::ActorBinding get_game_object,get_components_internal,playable_graph_get;}mp4_actor_profile;
struct{mp4actor::ActorBinding layer_prepare,layer_play;}mp4_temporal_pins;
const mp4actor::ActorPresentationSchema*mp4_actor_presentation_schema(const char*){static mp4actor::ActorPresentationSchema schema{};schema.klass.rva=200;return &schema;}
mp4actor::Owner selected_owner{};void*selected_player=nullptr;Object*actor_components=nullptr;
bool mp4_scene_actor_inventory(const Mp4SceneWitness&,mp4actor::Owner*out,size_t*n){++source_collections;if(!inventory_ready)return false;out[0]=selected_owner;*n=1;return true;}
std::vector<mp4actor::FixedJobOwner> fixed_jobs;
bool mp4_actor_presentation_collect(const mp4actor::Owner*o,size_t n,bool live,mp4actor::PresentationInventory&i){for(const auto&f:fixed_jobs)i.fixed_jobs[i.fixed_job_count++]=f;assert(n==1&&!live&&o[0].actor==selected_owner.actor);return presentation_ready;}
idoly_mp4_native_temporal::Handle mp4_temporal_native(mp4actor::Handle h){return {h.handle,h.version,h.padding};}
struct Mp4TemporalHost{mp4actor::Owner owner{};void*player=nullptr,*root_asset=nullptr;uint64_t epoch=0;};struct Mp4TemporalImage{bool base_parameter=false;};
const void*mp4_temporal_role_of(const Mp4TemporalImage&,idoly_mp4_native_temporal::Handle h){return factory_roles.count(h.slot)?reinterpret_cast<void*>(h.slot):nullptr;}
bool mp4_temporal_catalog(Mp4TemporalHost&h,Mp4TemporalImage&i,bool heavy){++catalog_calls;assert(h.player==selected_player&&heavy);i.base_parameter=temporal_catalog_ready;return temporal_catalog_ready;}
bool mp4_temporal_array(void*p,void**&data,size_t&n,size_t stride,size_t max){if(!memory.count(p))return false;auto&o=*memory[p];n=o.length;data=reinterpret_cast<void**>(o.array.data());return n<=max&&o.array.size()==n*stride;}
bool mp4_temporal_null_relay(void*p,void*,uintptr_t){return !p;}bool mp4_temporal_body_null_callbacks(Mp4TemporalHost&,void*p){return !p;}
struct Motion{void*clip=nullptr;};std::map<void*,Motion>motions;
bool mp4_temporal_motion(void*p,int32_t&layers){layers=1;return motions.count(p)&&mp4_alive(p);}
bool mp4_temporal_motion_clip(void*p,int32_t layer,void*&clip,uint64_t&,bool heavy){assert(layer==0&&heavy);if(!motions.count(p))return false;clip=motions[p].clip;return true;}
void*source_binding=nullptr;void*director_binding(void*,void*,Method*){return source_binding;}void*director_reference(void*,mp4game::PropertyName4,bool*valid,Method*){*valid=reference_valid;return reference_value;}
std::map<void*,void*>director_assets;std::map<void*,mp4actor::Handle>director_graphs;bool mutate_roster=false;void*roster_for_mutation=nullptr;
void*director_asset(void*d,Method*){return director_assets[d];}
void director_graph(void*d,mp4game::PlayableGraph*out,Method*){*out=director_graphs[d];if(mutate_roster){put(roster_for_mutation,28,uint32_t(2));mutate_roster=false;}}
struct{void*(*director_get_asset)(void*,Method*)=director_asset;void(*director_graph_injected)(void*,mp4game::PlayableGraph*,Method*)=director_graph;void*(*director_get_binding)(void*,void*,Method*)=director_binding;void*(*director_get_reference)(void*,mp4game::PropertyName4,bool*,Method*)=director_reference;}mp4_api;
std::map<std::pair<void*,std::string>,void*>method_map;
void*method(void*k,const char*n,int32_t){auto i=method_map.find({k,n});return i==method_map.end()?nullptr:i->second;}void*(*font_method)(void*,const char*,int32_t)=method;
void*component_object(void*p,Method*){return p;}
void*components(void*,void*,bool,bool,bool,bool,void*,Method*){return actor_components;}
void*reflection(const void*){return object("System.Type");}void*(*mp4_type_get_object)(const void*)=reflection;

struct Mp4TimelineActorPins{Mp4TimelineTypePin track,asset,track_playable,mixer,clip;mp4game::Binding reset_base,reset_solis,reset_swing,setup,weight;const mp4game::Binding*callbacks;size_t callback_count;};
mp4game::Binding actor_callback_pins[1]{};
Mp4TimelineActorPins mp4_timeline_actor_pins={{"VL.Timeline.VLAnimationClipPlayerTimelineTrack",{}},{"VL.Timeline.VLAnimationClipPlayerTimelineAsset",{}},{"VL.Timeline.VLAnimationClipPlayerTimelineTrackPlayable",{}},{"VL.Timeline.VLAnimationClipPlayerTimelineMixerPlayable",{}},{"VL.Timeline.VLAnimationClipPlayerTimelineClipPlayable",{}},{901,{}},{902,{}},{903,{}},{904,{}},{905,{}},actor_callback_pins,1};
