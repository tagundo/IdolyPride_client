#include <atomic>
struct Mp4ChildPendingDeferredOrigin{mp4_director_maintenance::Call call{},parent{};uint64_t execution_ticket=0;bool entered=false;};
bool deferred_origin=true;bool mp4_child_pending_deferred_origin(const mp4_director_maintenance::Call&c,Mp4ChildPendingDeferredOrigin*out){if(!deferred_origin||c.kind!=mp4_director_maintenance::Kind::maintenance||!mp4_child_planned_operation(c)||!mp4_child_call_same(c,mp4_child_pending_host.j.value))return false;*out={c,mp4_child_execution_bank.records[0].mutation.call,99,mp4_raw_original_operation.invoked};return true;}
enum class Mp4AudioOuterPhase:uint8_t{idle,captured,rebuilding,private_silent,restore_rebuilding,restore_ready,source_wait,restored,abandoned};
struct AudioWitness{void*director=(void*)0x220,*bgm=(void*)0x500,*voice=(void*)0x600;};
struct AudioProgram{void*source=nullptr;uintptr_t target_native=0;uint64_t recipe=0;};
struct AudioOuterProgram{AudioProgram before{},current{};bool captured=false,fresh=false;};
struct AudioSource{void*managed=nullptr;uintptr_t native=0;bool playing=true,paused=false;};
struct AudioPin{uintptr_t box=0,source=0;uint64_t recipe=0,retirement=0;};
struct AudioProof{uintptr_t graph=0,slot=0,output=0;uint32_t version=0;uint64_t canonical_lifetime=0;};
struct AudioGate{bool valid=true;bool current()const{return valid;}};
struct Mp4AudioOuterHost{AudioWitness witness;uint64_t epoch=7,transaction=0;bool failed=false,restoring=false,evaluated=false,post_started=false;Mp4AudioOuterPhase phase=Mp4AudioOuterPhase::captured;uint32_t canonical_readers=0,source_readers=0;uint64_t pending_canonical=0;size_t count=1,source_count=1,pin_count=1,root_count=1;AudioOuterProgram programs[64]{};AudioSource sources[64]{};AudioPin pins[8192]{};AudioProof pin_proofs[8192]{};uint32_t roots[32768]{};void*root_values[32768]{};AudioGate gate;};
Mp4AudioOuterHost audio_bank;Mp4AudioOuterHost*mp4_audio_outer_storage=&audio_bank;
#define mp4_audio_outer (*mp4_audio_outer_storage)
std::atomic<bool>mp4_audio_published{false},mp4_audio_foreign_dirty{false},mp4_animation_published{true};std::atomic<uint32_t>mp4_audio_native_readers{0};
struct{bool animation_owned=true,invalidated=false;uint64_t epoch=7;}mp4_world_host;
struct{uint64_t epoch=7,transaction=2;void*director=(void*)0x220;}mp4_rebuild_ledger;
struct{bool hooks=true,current=true,roots=true,channel=true,throw_channel=false,change_call=false,begin_reader=false,change_phase=false,lose_root=false;uintptr_t root=0x330;unsigned channels=0;}audio_model;
bool mp4_audio_native_hooks_current(){return audio_model.hooks;}
bool mp4_audio_outer_current(){return audio_model.current;}
bool mp4_audio_outer_roots(){return audio_model.roots;}
void*mp4_scene_root_asset_receipt(uint64_t e){return e==7?(void*)audio_model.root:nullptr;}
struct Mp4AudioChannelImage{uintptr_t native=0;};
bool mp4_audio_channel_image(void*s,const AudioPin*,size_t,Mp4AudioChannelImage&out){++audio_model.channels;if(audio_model.throw_channel)throw std::runtime_error("source image");if(audio_model.change_call)++mp4_child_module_operations.records[0].ticket;if(audio_model.begin_reader)mp4_audio_native_readers=1;if(audio_model.change_phase)audio_bank.phase=Mp4AudioOuterPhase::source_wait;if(audio_model.lose_root)audio_model.roots=false;out.native=s==(void*)0x500?0x700:0x800;return audio_model.channel;}
void*audio_direct_clip=nullptr;bool audio_clip_throws=false;void*audio_clip(void*){if(audio_clip_throws)throw std::runtime_error("clip getter");return audio_direct_clip;}void*(*mp4_audio_managed_clip)(void*)=audio_clip;
