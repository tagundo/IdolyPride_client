// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <vector>
using Method=void;enum class Mp4SceneResult{ok,waiting,stale,unsupported,failed};
struct Mp4SceneWitness{uint64_t generation=7;void*camera=reinterpret_cast<void*>(1);};
struct Mp4ProFlareSourcePlan{};struct Mp4ProFlareScalarImage{bool captured=true;};struct Mp4ProFlareSubImage{};
struct Data{int cpu=41,gpu=43;bool alive=true;}object;
struct Mp4ProFlareDataImage{void*object=nullptr;bool captured=false,gpu_touched=false;int cpu=41,gpu=43;};
struct{bool active=true;unsigned captured=15,restored=0,all=15;}mp4_scene_host;
struct{bool restored=false;}mp4_stage_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
namespace mp4_gpu_fence{enum class Result{waiting,ready,failed};}
extern unsigned access_depth;struct Ledger{bool waiting=false,bad=false;unsigned polls=0,retires=0;mp4_gpu_fence::Result poll(uint64_t j,uint64_t seq){assert(j==11&&seq&&!access_depth);++polls;return bad?mp4_gpu_fence::Result::failed:waiting?mp4_gpu_fence::Result::waiting:mp4_gpu_fence::Result::ready;}bool retire_sequence(uint64_t j,uint64_t seq){assert(j==11&&seq&&!access_depth);++retires;return !bad;}};
struct Gpu{bool configured=false,draw=false;uint64_t source=7,epoch=11,sequence=0,retired=0;Ledger ledger;}mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;bool mp4_owned_render_ticket_active=false;
bool initial_source_only=true,zero_witness=true;bool thread=true,access=true,held=true,registry=true,refs=true,scalar=true,sub=true,upload=true,begin_wait=false,poll_wait=false,dispose_wait=false,ready_service=true;
unsigned access_depth=0;std::vector<int>events;
bool mp4_gpu_initial_source_only_current(uint64_t s,uint64_t j){return initial_source_only&&s==7&&j==11&&mp4_gpu_fence_host.configured&&mp4_gpu_fence_host.sequence==1&&mp4_gpu_fence_host.retired==1;}bool mp4_proflare_empty_capture_current(uint64_t*out){*out=zero_witness?17:0;return zero_witness;}bool game_call(){return thread;}bool mp4_proflare_access_current(){return access&&access_depth;}bool mp4_stage_clock_held(void*){return held;}
struct Mp4ProFlareAccess{Mp4ProFlareAccess(){assert(thread);++access_depth;}~Mp4ProFlareAccess(){--access_depth;}};struct Mp4ProFlareAccessPause{bool paused=false;Mp4ProFlareAccessPause(){if(access_depth==1){access_depth=0;paused=true;}}~Mp4ProFlareAccessPause(){if(paused)access_depth=1;}explicit operator bool()const{return paused;}};
namespace mp4pf{enum class Result{ok,failed};}
struct{bool restored=false;}pass;
unsigned born=1;enum class Mp4ProFlareRetireResult{ok,waiting,failed};
Mp4ProFlareRetireResult mp4_proflare_birth_retire(size_t i){assert(i<born);events.push_back(3);return dispose_wait?Mp4ProFlareRetireResult::waiting:Mp4ProFlareRetireResult::ok;}
size_t mp4_proflare_data_birth_count=1;
bool mp4_proflare_pass_restore_references(){events.push_back(2);pass.restored=refs;return refs;}
mp4pf::Result mp4_proflare_registry_restore(){events.push_back(7);return registry?mp4pf::Result::ok:mp4pf::Result::failed;}
bool mp4_proflare_scalar_restore(Mp4ProFlareScalarImage&){events.push_back(8);return scalar;}bool mp4_proflare_scalar_verified(const Mp4ProFlareScalarImage&){return scalar;}bool mp4_proflare_sub_restore(Mp4ProFlareSubImage&){events.push_back(9);return sub;}
uint64_t aux_next=0,last_ticket=0;bool aux_returned=false;int active_mode=0;unsigned uploads=0;
Mp4SceneResult mp4_gpu_auxiliary_begin(uint64_t s,uint64_t j,uint64_t recipe,uint64_t*out){assert(s==7&&j==11&&recipe);if(begin_wait)return Mp4SceneResult::waiting;mp4_gpu_auxiliary_host.configured=true;mp4_gpu_auxiliary_host.draw=true;++mp4_gpu_auxiliary_host.sequence;*out=++aux_next;last_ticket=*out;return Mp4SceneResult::ok;}
Mp4SceneResult mp4_gpu_auxiliary_complete(uint64_t t,bool returned){assert(t==last_ticket&&mp4_gpu_auxiliary_host.draw);mp4_gpu_auxiliary_host.draw=false;aux_returned=returned;return returned?Mp4SceneResult::waiting:Mp4SceneResult::stale;}
Mp4SceneResult mp4_gpu_auxiliary_poll(uint64_t t){assert(t==last_ticket&&!access_depth);return poll_wait?Mp4SceneResult::waiting:aux_returned?Mp4SceneResult::ok:Mp4SceneResult::stale;}
bool mp4_gpu_auxiliary_retire(uint64_t t){assert(t==last_ticket&&!access_depth);mp4_gpu_auxiliary_host.retired=mp4_gpu_auxiliary_host.sequence;events.push_back(5);return true;}
bool mp4_proflare_existing_current(void*,const Mp4ProFlareDataImage&s){return s.object==&object&&object.alive;}
bool mp4_proflare_existing_quiet(void*,const Mp4ProFlareDataImage&){return !mp4_gpu_auxiliary_host.draw&&mp4_gpu_auxiliary_host.retired==mp4_gpu_auxiliary_host.sequence;}
bool mp4_proflare_data_upload(Mp4ProFlareDataImage&s,bool reset,bool(*current)(void*,const Mp4ProFlareDataImage&),void*c,uint64_t t,uint64_t src,uint64_t j,uint64_t){assert(current(c,s)&&t==last_ticket&&src==7&&j==11);events.push_back(reset?1:4);++uploads;s.gpu_touched=true;object.gpu=reset?0:s.gpu;return upload;}
bool mp4_proflare_data_restore_cpu(Mp4ProFlareDataImage&s,bool(*current)(void*,const Mp4ProFlareDataImage&),void*c,bool(*quiet)(void*,const Mp4ProFlareDataImage&)){assert(current(c,s)&&quiet(c,s));events.push_back(6);object.cpu=s.cpu;return true;}

#include "coordinator-types.inc"

bool mp4_proflare_quiet(){return access&&!mp4_owned_render_depth&&!mp4_unowned_render_depth&&!mp4_owned_render_ticket_active&&!mp4_gpu_fence_host.draw&&!mp4_gpu_auxiliary_host.draw&&(!mp4_gpu_fence_host.configured||mp4_gpu_fence_host.retired==mp4_gpu_fence_host.sequence)&&(!mp4_gpu_auxiliary_host.configured||mp4_gpu_auxiliary_host.retired==mp4_gpu_auxiliary_host.sequence);}
bool mp4_proflare_ready(void*b){auto*h=mp4_proflare_coordinator;return ready_service&&h&&h->captured&&h->serial&&h->batch==b&&h->source.generation==7&&h->job==11&&object.alive;}

#include "coordinator-sequence.inc"

void setup(){static Mp4ProFlareCoordinator h;h={};mp4_proflare_coordinator=&h;h.source={};h.job=11;h.serial=13;h.batch=&pass;h.started=h.prepared=h.captured=true;h.existing={&object,true,false,41,43};h.count=1;static Mp4ProFlareOwnedElement e;h.flares[0].elements=&e;h.flares[0].count=1;mp4_scene_host={};mp4_stage_host={};mp4_gpu_fence_host={};mp4_gpu_fence_host.configured=true;mp4_gpu_fence_host.sequence=mp4_gpu_fence_host.retired=1;mp4_gpu_auxiliary_host={};mp4_owned_render_depth=mp4_unowned_render_depth=0;mp4_owned_render_ticket_active=false;initial_source_only=zero_witness=true;thread=access=held=registry=refs=scalar=sub=upload=ready_service=true;begin_wait=poll_wait=dispose_wait=false;object={};events.clear();uploads=0;aux_returned=false;pass={};}
int main(){unsigned cases=0;setup();assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok&&object.gpu==0&&mp4_proflare_coordinator->reset&&uploads==1);++cases;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok&&uploads==1);++cases;
 setup();poll_wait=true;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::waiting&&!mp4_proflare_coordinator->reset);assert(uploads==1);poll_wait=false;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok&&uploads==1);++cases;
 setup();begin_wait=true;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::waiting&&uploads==0);begin_wait=false;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok);++cases;
 setup();mp4_gpu_fence_host.configured=true;mp4_gpu_fence_host.sequence=2;mp4_gpu_fence_host.retired=2;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::stale&&uploads==0);++cases;
 setup();assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok);object.cpu=91;object.gpu=97;mp4_scene_host.restored=mp4_scene_host.all;mp4_stage_host.restored=true;events.clear();assert(mp4_proflare_verify_source_restored()==Mp4SceneResult::ok&&object.cpu==41&&object.gpu==43&&mp4_proflare_coordinator->restored&&!mp4_proflare_coordinator->existing.gpu_touched);assert(events==std::vector<int>({2,3,4,5,6,7,8,8,9}));++cases;
 setup();mp4_scene_host.restored=mp4_scene_host.all;mp4_stage_host.restored=true;dispose_wait=true;assert(mp4_proflare_verify_source_restored()==Mp4SceneResult::waiting&&uploads==0&&!mp4_proflare_coordinator->restored);dispose_wait=false;assert(mp4_proflare_verify_source_restored()==Mp4SceneResult::ok);++cases;
 for(int bad=0;bad<8;++bad){setup();mp4_scene_host.restored=mp4_scene_host.all;mp4_stage_host.restored=true;if(bad==0)held=false;if(bad==1)mp4_stage_host.restored=false;if(bad==2)mp4_scene_host.restored=0;if(bad==3)refs=false;if(bad==4)registry=false;if(bad==5)scalar=false;if(bad==6)sub=false;if(bad==7)ready_service=false;assert(mp4_proflare_verify_source_restored()!=Mp4SceneResult::ok&&!mp4_proflare_coordinator->restored);++cases;}
 setup();poll_wait=true;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::waiting);poll_wait=false;mp4_scene_host.restored=mp4_scene_host.all;mp4_stage_host.restored=true;assert(mp4_proflare_verify_source_restored()==Mp4SceneResult::ok&&object.gpu==43);++cases;
 setup();initial_source_only=false;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::stale&&uploads==0&&!mp4_proflare_coordinator->operation);++cases;
 setup();mp4_proflare_coordinator=nullptr;zero_witness=false;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::stale);zero_witness=true;assert(mp4_proflare_prepare_first_render()==Mp4SceneResult::ok);++cases;
 std::printf("%u actual PF reset/restore/fence orchestration cases passed\n",cases);}
