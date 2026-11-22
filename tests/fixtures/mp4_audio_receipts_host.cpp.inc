#include <atomic>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include "shipping-gate.inc"
using Method=const void;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct PlayableGraph{void*handle=nullptr;int32_t version=0,padding=0;};}
namespace mp4world{struct AnimationOutput{uintptr_t handle=0;uint32_t version=0,padding=0;};struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
struct Mp4SceneWitness{void*presenter=nullptr,*player=nullptr,*director=nullptr,*controller=nullptr,*camera=nullptr,*brain=nullptr,*bgm=nullptr,*voice=nullptr,*environment=nullptr,*camera_director=nullptr,*camera_asset=nullptr,*camera_track=nullptr;uint64_t generation=0;};
struct Mp4AudioProgramClip{void*timeline=nullptr,*asset=nullptr,*clip=nullptr,*properties=nullptr;mp4actor::Handle playable{};uintptr_t native=0,voice_shared=0,voice=0;};
struct Mp4AudioProgramImage{void*director=nullptr,*asset=nullptr,*track=nullptr,*source=nullptr,*track_properties=nullptr;mp4actor::Handle graph{},root{},mixer{};mp4world::AnimationOutput output{};uintptr_t graph_native=0,output_native=0,mixer_native=0,target_native=0;uint64_t recipe=0;size_t count=0;float output_weight=1;int32_t output_port=0;uint8_t seek=0;Mp4AudioProgramClip clips[128]{};};
struct Mp4AudioSharedPin{uintptr_t box=0,source=0;uint64_t recipe=0,retirement=0;};
struct Mp4AudioChannelImage{void*managed=nullptr;uintptr_t native=0;uint64_t count=0;uint8_t paused=0,fast=0;};
struct Bytes{alignas(8)uint8_t data[0x420]{};};
static Bytes objects[32],slots[8],native_graphs[8],outputs[8],outputslots[8],native_clips[8],native_sources[2],boxes[4];
static Mp4SceneWitness witness;static Mp4AudioProgramImage live[2];static size_t track_count=1;static int generation=0;
static bool owner=true,source_current=true,channels_valid=true,pins_ready=true,managed_clip_set=false,route_ready=true,detached=false,native_playing[2]={true,false};
static bool observed_paused=false;static double observed_time=100;static int pin_refs=0,gc_refs=0,pin_calls=0,throw_root_at=0,root_calls=0,original_calls=0,process_calls=0,unknown_calls=0;
static bool throw_original=false,handoff_original=false,throw_process=false,source_write=false;
static std::map<uint32_t,void*>roots;static uint32_t nextroot=0;
template<class T>void set(void*p,size_t o,T x){std::memcpy(static_cast<uint8_t*>(p)+o,&x,sizeof x);}
template<class T>bool mp4_actor_field(void*p,size_t o,T&x){if(!p)return false;std::memcpy(&x,static_cast<uint8_t*>(p)+o,sizeof x);return true;}
bool game_call(bool=false){return owner;}bool mp4_alive(void*p){return p!=nullptr;}bool mp4_exact_type(void*p,const char*){return p!=nullptr;}
bool mp4_actor_mapped(void*p,size_t,bool){return p!=nullptr;}bool mp4_audio_channel_bindings(){return pins_ready;}bool mp4_audio_program_pins_ready(){return pins_ready;}
uint32_t mp4_retain(void*p){if(++root_calls==throw_root_at)throw std::runtime_error("root");if(!p)return 0;roots[++nextroot]=p;++gc_refs;return nextroot;}
void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);--gc_refs;}
struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*x):p(x){}void*get()const{return p;}};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return std::memcmp(&a,&b,sizeof a)==0;}
namespace idoly_mp4_playback{enum class Phase{starting,restoring,other};}
static idoly_mp4_playback::Phase phase=idoly_mp4_playback::Phase::starting;static bool rebuild_flag=true,held_flag=true;
namespace idoly_mp4_runtime{struct Clock{bool held()const{return held_flag;}};static Clock clock;Clock&native_clock_scope(){return clock;}struct Game{
 idoly_mp4_playback::Phase automatic_rebuild_phase()const{return phase;}bool automatic_rebuild_in_progress()const{return rebuild_flag;}
 size_t selected_audio_track_count()const{return track_count;}
 bool selected_audio_track(size_t i,void*&d,void*&a,void*&t,void*&s)const{if(i>=track_count)return false;d=live[i].director;a=live[i].asset;t=live[i].track;s=live[i].source;return true;}
 bool selected_scene_witness(Mp4SceneWitness&w)const{w=witness;return source_current;}
 bool observe_source(double&t,bool&p)const{t=observed_time;p=observed_paused;return source_current;}
}game;}
struct API{void(*director_graph_injected)(void*,mp4game::PlayableGraph*,Method*);double(*director_get_time)(void*,Method*); }mp4_api;
uintptr_t image_base=0,mp4_native_base=0;
struct{mp4game::Binding graph_output_count,graph_output,output_type;}mp4_world_profile;
struct{struct{size_t slot_output=0;}native_output;}mp4_actor_profile;
struct{mp4game::Binding object_id;}mp4_audio_program_pins;
struct{mp4game::Binding playing;}mp4_audio_channel_pins;
uint32_t mp4_audio_program_types[1]{};
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
bool mp4_scene_registry_current_graph(uintptr_t n,uintptr_t s,uint32_t v){for(size_t i=0;i<track_count;++i)if(live[i].graph_native==n&&live[i].graph.handle==s&&(live[i].graph.version&~1u)==v)return true;return false;}
bool mp4_receipt_graph(mp4actor::Handle g,uintptr_t*n,uint32_t*v){for(size_t i=0;i<track_count;++i)if(mp4_actor_same_handle(g,live[i].graph)){*n=live[i].graph_native;*v=g.version&~1u;return true;}return false;}
bool mp4_director_graph_handle(const mp4world::DirectorGraphIdentity&i,mp4actor::Handle*g){for(size_t k=0;k<track_count;++k)if(live[k].graph_native==i.native&&live[k].graph.handle==i.slot&&(live[k].graph.version&~1u)==i.version){*g=live[k].graph;return true;}return false;}
bool mp4_audio_program_collect(size_t i,const mp4world::DirectorGraphIdentity&,uintptr_t out,bool fresh,Mp4AudioProgramImage&r){if(i>=track_count||out!=live[i].output_native||(fresh&&live[i].clips[0].voice_shared))return false;r=live[i];return true;}
bool mp4_audio_program_native_node(mp4actor::Handle h,mp4actor::Handle g,bool,uintptr_t&n){for(size_t i=0;i<track_count;++i)if(mp4_actor_same_handle(g,live[i].graph)&&mp4_actor_same_handle(h,live[i].clips[0].playable)){n=live[i].clips[0].native;return true;}return false;}
bool mp4_audio_shared_pin(const Mp4AudioProgramImage&p,const Mp4AudioProgramClip&c,uint64_t r,Mp4AudioSharedPin&pin){++pin_calls;if(pin.box||!c.voice_shared)return false;pin={c.voice_shared,p.target_native,p.recipe,r};++pin_refs;return true;}
void mp4_audio_shared_release(Mp4AudioSharedPin&p){if(p.box)--pin_refs;p={};}
bool mp4_audio_channel_image(void*s,const Mp4AudioSharedPin*p,size_t n,Mp4AudioChannelImage&o){if(!channels_valid)return false;for(size_t i=0;i<track_count;++i)if(live[i].source==s){o={s,live[i].target_native,0,uint8_t(observed_paused),0};for(size_t j=0;j<n;++j)if(p[j].source==o.native)o.fast=1;return true;}return false;}
bool native_is_playing(void*s){return s==&native_sources[0]?native_playing[0]:native_playing[1];}
void graph_get(void*d,mp4game::PlayableGraph*g,Method*){for(size_t i=0;i<track_count;++i)if(live[i].director==d){g->handle=reinterpret_cast<void*>(live[i].graph.handle);g->version=live[i].graph.version;return;}}
int32_t output_count(mp4actor::Handle*,Method*){return int32_t(track_count);}
void output_get(mp4actor::Handle*,int32_t i,mp4world::AnimationOutput*out,Method*){*out=live[i].output;}
void*output_type(mp4world::AnimationOutput*,Method*){return &objects[31];}
int32_t object_id(void*t,Method*){for(size_t i=0;i<track_count;++i)if(t==live[i].track)return 42+int32_t(i);return -1;}
#include <algorithm>
#include "shipping-outer.inc"
bool pending(uint64_t,uintptr_t,uintptr_t,uint32_t,uint64_t,uintptr_t){return true;}
bool ready(){return route_ready;}bool is_detached(uint64_t){return detached;}
void*source_clip(void*){return managed_clip_set?&objects[30]:nullptr;}
void generation_set(int gen,bool voices){generation=gen;for(size_t i=0;i<track_count;++i){auto&p=live[i];p.graph={reinterpret_cast<uintptr_t>(&slots[gen*2+i]),uint32_t(gen*2+2),0};p.graph_native=reinterpret_cast<uintptr_t>(&native_graphs[gen*2+i]);p.output={reinterpret_cast<uintptr_t>(&outputslots[gen*2+i]),uint32_t(gen*2+2),0};p.output_native=reinterpret_cast<uintptr_t>(&outputs[gen*2+i]);set(reinterpret_cast<void*>(p.output.handle),0,p.output_native);set(reinterpret_cast<void*>(p.output_native),0x48,int32_t(42+i));p.clips[0].playable={reinterpret_cast<uintptr_t>(&native_clips[gen*2+i]),uint32_t(gen*2+2),0};p.clips[0].native=p.clips[0].playable.handle;p.clips[0].voice_shared=voices?reinterpret_cast<uintptr_t>(&boxes[i]):0;set(reinterpret_cast<void*>(p.clips[0].native),0xc0,p.target_native);set(reinterpret_cast<void*>(p.clips[0].native),0x110,p.clips[0].voice_shared);}}
void setup(){witness={&objects[0],&objects[1],&objects[2],&objects[3],&objects[4],&objects[5],&objects[6],&objects[7],&objects[8],&objects[9],&objects[10],&objects[11],11};
 for(size_t i=0;i<track_count;++i){auto&p=live[i];p.director=&objects[2];p.asset=&objects[12+i];p.track=&objects[14+i];p.source=i?witness.voice:witness.bgm;p.target_native=reinterpret_cast<uintptr_t>(&native_sources[i]);p.track_properties=&objects[16+i];p.recipe=99+i;p.count=1;p.clips[0].timeline=&objects[18+i];p.clips[0].asset=&objects[20+i];p.clips[0].clip=&objects[22+i];p.clips[0].properties=&objects[24+i];set(p.source,16,p.target_native);set(reinterpret_cast<void*>(p.target_native),0x3ac,uint8_t(observed_paused));}
 generation_set(0,true);mp4_api.director_graph_injected=graph_get;mp4_world_profile.graph_output_count.rva=reinterpret_cast<uintptr_t>(output_count);mp4_world_profile.graph_output.rva=reinterpret_cast<uintptr_t>(output_get);mp4_world_profile.output_type.rva=reinterpret_cast<uintptr_t>(output_type);mp4_audio_program_pins.object_id.rva=reinterpret_cast<uintptr_t>(object_id);mp4_audio_channel_pins.playing.rva=reinterpret_cast<uintptr_t>(native_is_playing);mp4_audio_program_types[0]=mp4_retain(&objects[31]);
 mp4_audio_native_hook_ready=mp4_audio_process_hook_ready=true;mp4_audio_pending_destroy_receipt=pending;mp4_audio_natural_restore_route_ready=ready;mp4_audio_natural_restore_detached=is_detached;mp4_audio_managed_clip=source_clip;
}
void capture(){assert(mp4_audio_outer_capture(witness,11));}
void private_start(){capture();assert(mp4_audio_outer_before_rebuild(witness.director,false));generation_set(1,false);assert(mp4_audio_outer_after_rebuild());assert(mp4_audio_outer_after_evaluate(false,0));}
void logical_restore(){private_start();assert(mp4_audio_outer_before_rebuild(witness.director,true));generation_set(2,false);assert(mp4_audio_outer_after_rebuild());assert(mp4_audio_outer_after_evaluate(true,100));for(size_t i=0;i<track_count;++i)assert(mp4_audio_outer_logical_source(live[i].source,native_is_playing(reinterpret_cast<void*>(live[i].target_native)),observed_paused));assert(mp4_audio_outer_begin_post_restore());}
void original(void*raw){++original_calls;auto*v=static_cast<mp4audio::VectorView*>(raw);if(v)for(size_t i=0;i<v->count;++i){auto out=reinterpret_cast<uintptr_t*>(v->data)[i];bool known=false;for(size_t k=0;k<track_count;++k)if(live[k].output_native==out){known=true;live[k].clips[0].voice_shared=reinterpret_cast<uintptr_t>(&boxes[2+k]);set(reinterpret_cast<void*>(live[k].clips[0].native),0x110,live[k].clips[0].voice_shared);}if(!known)++unknown_calls;}
 if(handoff_original){++witness.generation;source_write=true;}if(throw_original)throw std::runtime_error("native");}
void process(void*){++process_calls;if(throw_process)throw std::runtime_error("process");}
void invoke(){uintptr_t entries[2]{};for(size_t i=0;i<track_count;++i)entries[i]=live[i].output_native;mp4audio::VectorView v{reinterpret_cast<uintptr_t>(entries),0,track_count,0};mp4_audio_outer_invoke(original,&v);}
int bank_allocations=0;void* counted_bank(size_t n){++bank_allocations;return std::malloc(n);}
void* failed_bank(size_t){++bank_allocations;return nullptr;}

struct ReceiptGraph{uintptr_t native=0,slot=0;uint32_t version=0;uint64_t epoch=0,receipt=0;bool invoked=false;};
struct {uint64_t epoch=0,transaction=0;void*director=nullptr;bool active=false,evaluation_pending=false;ReceiptGraph graphs[8]{};size_t graph_count=0,transaction_begin=0;}mp4_rebuild_ledger;
struct {bool active=true;}mp4_scene_host;
bool mp4_scene_source_current(){return source_current;}
uint64_t mp4_volume_original_evaluate_epoch=0;uint32_t mp4_volume_original_evaluate_depth=0;
double time_get(void*,Method*){return observed_time;}
#include "shipping-late.inc"
void transaction_begin(){auto&l=mp4_rebuild_ledger;l.epoch=11;++l.transaction;l.director=witness.director;l.active=true;l.evaluation_pending=false;l.transaction_begin=0;l.graph_count=1;l.graphs[0]={live[0].graph_native,live[0].graph.handle,live[0].graph.version&~1u,11,l.transaction,false};}
void rebuilt(){mp4_rebuild_ledger.graphs[0].invoked=true;generation_set(1,false);assert(mp4_audio_outer_after_rebuild());mp4_rebuild_ledger.active=false;mp4_rebuild_ledger.evaluation_pending=true;}
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];setup();mp4_api.director_get_time=time_get;capture();transaction_begin();
 if(c=="begin_no_active"){mp4_rebuild_ledger.active=false;uint64_t out=99;assert(!mp4_audio_trusted_rebuild_begin(11,witness.director,false,&out)&&!out);}
 else if(c=="begin_wrong_epoch"){uint64_t out=0;assert(!mp4_audio_trusted_rebuild_begin(12,witness.director,false,&out));}
 else if(c=="begin_wrong_director"){uint64_t out=0;assert(!mp4_audio_trusted_rebuild_begin(11,&objects[29],false,&out));}
 else if(c=="begin_clock_open"){held_flag=false;uint64_t out=0;assert(!mp4_audio_trusted_rebuild_begin(11,witness.director,false,&out));}
 else if(c=="begin_phase"){phase=idoly_mp4_playback::Phase::restoring;uint64_t out=0;assert(!mp4_audio_trusted_rebuild_begin(11,witness.director,false,&out));}
 else if(c=="begin_flag"){rebuild_flag=false;uint64_t out=0;assert(!mp4_audio_trusted_rebuild_begin(11,witness.director,false,&out));}
 else {assert(mp4_audio_outer_before_rebuild(witness.director,false));
  if(c=="invoke_missing"){generation_set(1,false);assert(!mp4_audio_outer_after_rebuild());}
  else if(c=="invoke_wrong_version"){++mp4_rebuild_ledger.graphs[0].version;mp4_rebuild_ledger.graphs[0].invoked=true;generation_set(1,false);assert(!mp4_audio_outer_after_rebuild());}
  else {rebuilt();observed_time=0;mp4_volume_original_evaluate_epoch=11;mp4_volume_original_evaluate_depth=1;
   if(c=="evaluate_outside_epoch"){mp4_volume_original_evaluate_epoch=12;assert(!mp4_audio_outer_evaluation_begin(witness.director,false));}
   else if(c=="evaluate_nested"){mp4_volume_original_evaluate_depth=2;assert(!mp4_audio_outer_evaluation_begin(witness.director,false));}
   else if(c=="evaluate_future_time"){observed_time=1;assert(!mp4_audio_outer_evaluation_begin(witness.director,false));}
   else {assert(mp4_audio_outer_evaluation_begin(witness.director,false));
    if(c=="evaluate_exception"){mp4_rebuild_ledger.evaluation_pending=false;mp4_volume_original_evaluate_depth=0;assert(!mp4_audio_outer_after_original_evaluate(false));}
    else if(c=="complete_wrong_time"){observed_time=1;assert(!mp4_audio_outer_evaluation_completed(witness.director));}
    else if(c=="complete_wrong_epoch"){mp4_volume_original_evaluate_epoch=12;assert(!mp4_audio_outer_evaluation_completed(witness.director));}
    else {assert(mp4_audio_outer_evaluation_completed(witness.director));mp4_rebuild_ledger.evaluation_pending=false;mp4_volume_original_evaluate_depth=0;mp4_volume_original_evaluate_epoch=0;
     if(c=="consume_phase"){assert(!mp4_audio_trusted_evaluate(11,true,0));}
     else if(c=="consume_wrong_transaction"){++mp4_rebuild_ledger.transaction;assert(!mp4_audio_outer_after_original_evaluate(false));}
     else {assert(c=="consume_once");assert(mp4_audio_outer_after_original_evaluate(false));assert(!mp4_audio_outer_after_original_evaluate(false));}
    }
   }
  }
 }
 assert(mp4_audio_outer_release());assert(pin_refs==0&&gc_refs==1);weak_free(mp4_audio_program_types[0]);assert(!gc_refs);
}
