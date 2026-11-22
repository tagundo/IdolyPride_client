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
static bool owner=true,source_current=true,channels_valid=true,pins_ready=true,managed_clip_set=false,route_ready=true,detached=false,trust_begin=true,trust_invoke=true,trust_evaluate=true,native_playing[2]={true,false};
static bool observed_paused=false;static double observed_time=100;static int pin_refs=0,gc_refs=0,pin_calls=0,throw_root_at=0,root_calls=0,original_calls=0,process_calls=0,unknown_calls=0;
static bool throw_original=false,handoff_original=false,throw_process=false,source_write=false;static uint64_t receipt=0;
static std::map<uint32_t,void*>roots;static uint32_t nextroot=0;
template<class T>void set(void*p,size_t o,T x){std::memcpy(static_cast<uint8_t*>(p)+o,&x,sizeof x);}
template<class T>bool mp4_actor_field(void*p,size_t o,T&x){if(!p)return false;std::memcpy(&x,static_cast<uint8_t*>(p)+o,sizeof x);return true;}
bool game_call(bool=false){return owner;}bool mp4_alive(void*p){return p!=nullptr;}bool mp4_exact_type(void*p,const char*){return p!=nullptr;}
bool mp4_actor_mapped(void*p,size_t,bool){return p!=nullptr;}bool mp4_audio_channel_bindings(){return pins_ready;}bool mp4_audio_program_pins_ready(){return pins_ready;}
uint32_t mp4_retain(void*p){if(++root_calls==throw_root_at)throw std::runtime_error("root");if(!p)return 0;roots[++nextroot]=p;++gc_refs;return nextroot;}
void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t h){assert(roots.erase(h)==1);--gc_refs;}
struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*x):p(x){}void*get()const{return p;}};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return std::memcmp(&a,&b,sizeof a)==0;}
namespace idoly_mp4_runtime{struct Game{
 size_t selected_audio_track_count()const{return track_count;}
 bool selected_audio_track(size_t i,void*&d,void*&a,void*&t,void*&s)const{if(i>=track_count)return false;d=live[i].director;a=live[i].asset;t=live[i].track;s=live[i].source;return true;}
 bool selected_scene_witness(Mp4SceneWitness&w)const{w=witness;return source_current;}
 bool observe_source(double&t,bool&p)const{t=observed_time;p=observed_paused;return source_current;}
}game;}
struct API{void(*director_graph_injected)(void*,mp4game::PlayableGraph*,Method*); }mp4_api;
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
bool mp4_audio_trusted_rebuild_begin(uint64_t,void*,bool,uint64_t*out){*out=++receipt;return trust_begin;}
bool mp4_audio_trusted_rebuild_invoked(uint64_t,uint64_t,uintptr_t,uintptr_t,uint32_t){return trust_invoke;}
bool mp4_audio_trusted_evaluate(uint64_t,bool,double){return trust_evaluate;}
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
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];if(c=="two_sources"||c=="same_source")track_count=2;if(c=="paused"||c=="paused_early_natural")observed_paused=true;setup();if(c=="same_source"){live[1].source=live[0].source;live[1].target_native=live[0].target_native;set(reinterpret_cast<void*>(live[1].clips[0].native),0xc0,live[0].target_native);}
 if(c=="nonplaying")native_playing[0]=false;
 const int permanent=gc_refs;
 if(c=="bank_null_hooks"){assert(!mp4_audio_outer_storage);mp4_audio_outer_invoke(original,nullptr);mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));assert(!mp4_audio_outer_storage&&original_calls==1&&process_calls==1&&!mp4_audio_outer_active());}
 else if(c=="bank_oom"){mp4_audio_bank_allocate=failed_bank;assert(!mp4_audio_outer_capture(witness,11)&&!mp4_audio_outer_storage&&!mp4_audio_outer_epoch()&&bank_allocations==1);mp4_audio_bank_allocate=counted_bank;capture();assert(mp4_audio_outer_storage&&bank_allocations==2);}
 else if(c=="bank_reuse"){mp4_audio_bank_allocate=counted_bank;capture();auto*bank=mp4_audio_outer_storage;assert(mp4_audio_outer_release());capture();assert(bank==mp4_audio_outer_storage&&bank_allocations==1);}
 else if(c=="admit"){assert(mp4_audio_outer_admit(witness)&&pin_refs==0&&gc_refs==permanent);}
 else if(c=="admit_clip"){managed_clip_set=true;assert(!mp4_audio_outer_admit(witness));}
 else if(c=="admit_channels"){channels_valid=false;assert(!mp4_audio_outer_admit(witness)&&pin_refs==0);}
 else if(c=="admit_route"){route_ready=false;assert(!mp4_audio_outer_admit(witness));}
 else if(c=="capture_rollback"){managed_clip_set=true;assert(!mp4_audio_outer_capture(witness,11));assert(!mp4_audio_outer.epoch&&gc_refs==permanent&&pin_refs==0);}
 else if(c=="capture_exception"){throw_root_at=root_calls+7;try{mp4_audio_outer_capture(witness,11);assert(false);}catch(const std::runtime_error&){}assert(!mp4_audio_outer.epoch&&gc_refs==permanent&&pin_refs==0);}
 else if(c=="before_untrusted"){capture();trust_begin=false;assert(!mp4_audio_outer_before_rebuild(witness.director,false));}
 else if(c=="rebuild_uninvoked"){capture();assert(mp4_audio_outer_before_rebuild(witness.director,false));generation_set(1,false);trust_invoke=false;assert(!mp4_audio_outer_after_rebuild());}
 else if(c=="unchanged_graph"){capture();assert(mp4_audio_outer_before_rebuild(witness.director,false));assert(mp4_audio_outer_after_rebuild());live[0].clips[0].voice_shared=0;assert(!mp4_audio_outer_after_evaluate(false,0));}
 else if(c=="private_voice"){capture();assert(mp4_audio_outer_before_rebuild(witness.director,false));generation_set(1,true);assert(mp4_audio_outer_after_rebuild());assert(!mp4_audio_outer_after_evaluate(false,0));}
 else if(c=="private_filter"){private_start();invoke();assert(original_calls==0&&!live[0].clips[0].voice_shared);}
 else if(c=="recipe_change"){private_start();++live[0].recipe;invoke();assert(original_calls==1&&mp4_audio_outer.failed&&!mp4_audio_published);}
 else if(c=="mixed_failure"){private_start();uintptr_t entries[]={uintptr_t(1234),live[0].output_native};mp4audio::VectorView v{reinterpret_cast<uintptr_t>(entries),0,2,0};channels_valid=false;mp4_audio_outer_invoke(original,&v);assert(original_calls==1&&unknown_calls==1&&!mp4_audio_published);}
 else if(c=="fallback_exception"){private_start();channels_valid=false;throw_original=true;try{invoke();assert(false);}catch(const std::runtime_error&){}assert(original_calls==1&&!mp4_audio_published);}
 else if(c=="retired"){private_start();const auto&r=mp4_audio_outer.retired[0];assert(mp4_audio_retired_before_closed(11,r.native,r.slot,r.version,r.receipt,r.output));assert(!mp4_audio_retired_before_closed(11,r.native,r.slot,r.version,r.receipt+1,r.output));assert(mp4_audio_outer_route(nullptr,r.output)==mp4audio::Route::reject);}
 else if(c=="wrong_restore_time"){private_start();assert(mp4_audio_outer_before_rebuild(witness.director,true));generation_set(2,false);assert(mp4_audio_outer_after_rebuild());assert(!mp4_audio_outer_after_evaluate(true,101));}
 else if(c=="logical_checkpoint"){logical_restore();assert(mp4_audio_outer.logical_checkpoint&&mp4_audio_outer.phase==Mp4AudioOuterPhase::restore_ready);}
 else if(c=="logical_time_change"){logical_restore();observed_time=101;assert(!mp4_audio_outer_logical_source(live[0].source,true,false));}
 else if(c=="before_detach"){logical_restore();assert(mp4_audio_outer_post_restore_ready()==2&&!mp4_audio_outer_source_waiting());}
 else if(c=="paused"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==0&&!original_calls&&!process_calls);}
 else if(c=="natural"||c=="two_sources"||c=="same_source"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();assert(original_calls==1&&mp4_audio_outer_post_restore_ready()==1);for(size_t i=0;i<track_count;++i)mp4_audio_outer_process(process,reinterpret_cast<void*>(live[i].target_native));assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="moving_callback"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));const auto first=mp4_audio_outer.sources[0].canonical;invoke();assert(mp4_audio_outer.sources[0].canonical==first);assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="ordinary_clip_stop"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();live[0].clips[0].voice_shared=0;set(reinterpret_cast<void*>(live[0].clips[0].native),0x110,uintptr_t(0));assert(mp4_audio_outer_channels());mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="nonplaying"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();assert(mp4_audio_outer_post_restore_ready()==0&&!process_calls);}
 else if(c=="ordinary_playstate_change"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));native_playing[0]=false;observed_time=101;assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="early_natural_during_cleanup"){logical_restore();detached=true;invoke();mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="paused_early_natural"){logical_restore();detached=true;invoke();assert(mp4_audio_outer_post_restore_ready()==0&&!process_calls);}
 else if(c=="capture_retry"){capture();const int roots_before=gc_refs,pins_before=pin_refs;assert(mp4_audio_outer_capture(witness,11));assert(gc_refs==roots_before&&pin_refs==pins_before);}
 else if(c=="post_arm_retry"){logical_restore();detached=true;invoke();mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));observed_time=101;assert(mp4_audio_outer_begin_post_restore());assert(mp4_audio_outer_post_restore_ready()==0);}
 else if(c=="post_before_checkpoint"){private_start();detached=true;assert(mp4_audio_outer_post_restore_ready()==2);}
 else if(c=="root_identity"){private_start();roots[mp4_audio_outer.roots[0]]=&objects[29];assert(!mp4_audio_outer_roots());invoke();assert(original_calls==1&&!mp4_audio_published);}
 else if(c=="source_handoff"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);handoff_original=true;invoke();assert(original_calls==1&&source_write&&!mp4_audio_published&&mp4_audio_outer_post_restore_ready()==2);}
 else if(c=="canonical_exception"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);throw_original=true;try{invoke();assert(false);}catch(const std::runtime_error&){}assert(original_calls==1&&!mp4_audio_published);}
 else if(c=="process_exception"){logical_restore();detached=true;assert(mp4_audio_outer_post_restore_ready()==1);invoke();throw_process=true;try{mp4_audio_outer_process(process,reinterpret_cast<void*>(live[0].target_native));assert(false);}catch(const std::runtime_error&){}assert(process_calls==1&&!mp4_audio_published);}
 else if(c=="foreign_thread"){private_start();owner=false;invoke();owner=true;assert(original_calls==1&&mp4_audio_foreign_dirty&&!mp4_audio_published);}
 else if(c=="release_wait"){private_start();mp4_audio_native_readers=1;assert(!mp4_audio_outer_release()&&gc_refs>permanent&&pin_refs==1);mp4_audio_native_readers=0;}
 else if(c=="reuse"){private_start();assert(mp4_audio_outer_release());generation_set(0,true);capture();assert(mp4_audio_outer.epoch==11);}
 else if(c=="output_admission"){mp4world::DirectorGraphIdentity id{live[0].graph_native,live[0].graph.handle,live[0].graph.version&~1u};assert(mp4_audio_outer_output_closed(witness,id,live[0].output_native,true));++id.version;assert(!mp4_audio_outer_output_closed(witness,id,live[0].output_native,true));}
 else assert(false);
 assert(mp4_audio_native_readers==0);assert(mp4_audio_outer_release());assert(gc_refs==permanent&&pin_refs==0);weak_free(mp4_audio_program_types[0]);assert(!gc_refs);}
