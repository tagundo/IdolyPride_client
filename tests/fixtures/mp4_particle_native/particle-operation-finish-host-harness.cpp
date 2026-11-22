#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <stdexcept>
#include <atomic>
namespace mp4_director_maintenance{enum class Kind:uint8_t{play=1,stop=2,rebuild=3,zero_evaluate=4,saved_evaluate=5,maintenance=6,native_phase=7};struct Call{Kind kind=Kind::play;uint64_t epoch=0,serial=0;uintptr_t source_asset=0,receiver=0,method=0;uint64_t original_receipt=0;};}
namespace mp4ps{struct Owner{void*managed=nullptr;uintptr_t native=0,particles=0,parameters=0,state=0,modules=0;int32_t instance=0;uint64_t policy=0,capture=0;};bool same(const Owner&a,const Owner&b){return a.managed==b.managed&&a.native==b.native&&a.particles==b.particles&&a.parameters==b.parameters&&a.state==b.state&&a.modules==b.modules&&a.instance==b.instance&&a.policy==b.policy&&a.capture==b.capture;}}
struct Mp4ParticleRetainedWorkerOwner{mp4ps::Owner owner{};void*renderer=nullptr;uintptr_t renderer_native=0;int32_t renderer_id=0;uint64_t image=0;};
enum class Mp4SceneResult{ok,waiting,stale,failed};
struct Native{uint8_t pending=1;};Native ps[2];int manager=0;uint32_t queued=2;uintptr_t queuehead=123;
Mp4ParticleRetainedWorkerOwner retained[2];size_t retainedcount=2;
bool thread=true,held=true,inventory=true,finishpin=true,readerpin=true,mapped=true,current=true;uint64_t generation=17;unsigned gets=0,drains=0;int fault=0;bool throwget=false,throwdrain=false;
bool game_call(){return thread;}bool mp4_actor_clock_held(void*){return held;}bool mp4_particle_finish_entry_current(){return finishpin;}bool mp4_particle_renderer_reader_bindings(){return readerpin;}bool mp4_particle_native_state_mapped(uintptr_t,size_t){return mapped;}
uintptr_t mp4_native_base=0;struct{uintptr_t singleton=12;}mp4_particle_manager_pins;
bool mp4_actor_field(void*p,size_t at,uintptr_t&value){if(p==reinterpret_cast<void*>(12)&&at==0){value=reinterpret_cast<uintptr_t>(&manager);return true;}if(p==&manager&&at==0x80){value=queuehead;return true;}return false;}
bool mp4_actor_field(void*p,size_t at,uint32_t&value){if(p==&manager&&at==0x40){value=queued;return true;}return false;}
bool mp4_actor_field(void*p,size_t at,uint8_t&value){if(at==0x6c&&(p==&ps[0]||p==&ps[1])){value=static_cast<Native*>(p)->pending;return true;}return false;}
bool mp4_particle_native_retained_worker_inventory(uint64_t s,uint64_t j,uint64_t c,Mp4ParticleRetainedWorkerOwner*out,size_t cap,size_t*n){if(!inventory||s!=7||j!=11||c!=13||cap<retainedcount)return false;*n=retainedcount;for(size_t i=0;i<retainedcount;++i)out[i]=retained[i];return true;}
struct Mp4ParticleStateNativeValue{uint8_t bytes[352]{};};
Mp4ParticleStateNativeValue mp4_particle_finish_original(uintptr_t p){++gets;if(throwget)throw std::runtime_error("original");auto*n=reinterpret_cast<Native*>(p);n->pending=0;if(fault==1)++generation;if(fault==2)++retained[0].owner.modules;if(fault==3)n->pending=1;if(fault==6)finishpin=false;return{};}
void original_drain(){++drains;if(throwdrain)throw std::runtime_error("drain");queued=0;queuehead=0;if(fault==4)queuehead=3;if(fault==5)++generation;}
struct{uintptr_t rva=reinterpret_cast<uintptr_t>(&original_drain);}mp4_particle_renderer_reader_pin;
#include "particle-operation-rw-host.inc"
#include "particle-operation-finish-host.inc"
mp4_director_maintenance::Call call;Mp4ParticleOperationLease lease;
bool leasecurrent(void*,const mp4_director_maintenance::Call&c,uint64_t serial,Mp4ParticleOperationPhase phase){return current&&serial==generation&&c.serial==23&&c.epoch==7&&c.source_asset==31&&c.receiver==37&&c.method==41&&c.original_receipt==43&&phase==lease.phase;}
void reset(){ps[0]={};ps[1]={};queued=2;queuehead=123;thread=held=inventory=finishpin=readerpin=mapped=current=true;generation=17;gets=drains=0;fault=0;throwget=throwdrain=false;retainedcount=2;for(size_t i=0;i<2;++i)retained[i]={{reinterpret_cast<void*>(1+i),reinterpret_cast<uintptr_t>(&ps[i]),51+i,61+i,71+i,81+i,static_cast<int32_t>(91+i),101+i,111+i},reinterpret_cast<void*>(121+i),131+i,static_cast<int32_t>(141+i),151+i};call={mp4_director_maintenance::Kind::rebuild,7,23,31,37,41,43};lease={nullptr,17,Mp4ParticleOperationPhase::before,leasecurrent};mp4_particle_operation_finish_withdraw();}
Mp4SceneResult run(Mp4ParticleOperationReceipt*r){Mp4ParticleRetainedWorkerOwner input[2]={retained[0],retained[1]};return mp4_particle_operation_finish(call,lease,7,11,13,input,2,r);}
int main(){unsigned cases=0;Mp4ParticleOperationReceipt r{};reset();assert(run(&r)==Mp4SceneResult::ok&&gets==2&&drains==1&&r.serial&&mp4_particle_operation_finish_current(r));++cases;
 for(int bad=0;bad<20;++bad){reset();if(bad==0)thread=false;if(bad==1)held=false;if(bad==2)inventory=false;if(bad==3)finishpin=false;if(bad==4)readerpin=false;if(bad==5)mapped=false;if(bad==6)current=false;if(bad==7)++call.serial;if(bad==8)call.original_receipt=0;if(bad==9)lease.serial=0;if(bad==10)lease.current=nullptr;if(bad==11)++call.epoch;if(bad==12)lease.phase=Mp4ParticleOperationPhase::native_before;if(bad>=13&&bad<=18)fault=bad-12;if(bad==19)retainedcount=1;assert(run(&r)!=Mp4SceneResult::ok&&!r.serial);assert(!mp4_particle_operation_finish_current(r));++cases;}
 reset();call.kind=mp4_director_maintenance::Kind::native_phase;lease.phase=Mp4ParticleOperationPhase::native_before;assert(run(&r)==Mp4SceneResult::ok);++cases;
 reset();call.kind=mp4_director_maintenance::Kind::native_phase;lease.phase=Mp4ParticleOperationPhase::native_after;assert(run(&r)==Mp4SceneResult::ok);++cases;
 reset();lease.phase=Mp4ParticleOperationPhase::after;assert(run(&r)==Mp4SceneResult::ok);++cases;
 reset();assert(run(&r)==Mp4SceneResult::ok);auto prior=r;++generation;assert(!mp4_particle_operation_finish_current(prior));++cases;
 reset();assert(run(&r)==Mp4SceneResult::ok);prior=r;assert(run(&r)==Mp4SceneResult::ok&&r.serial!=prior.serial&&!mp4_particle_operation_finish_current(prior));++cases;
 reset();assert(run(&r)==Mp4SceneResult::ok);prior=r;++prior.call.method;assert(!mp4_particle_operation_finish_current(prior));++cases;
 reset();assert(run(&r)==Mp4SceneResult::ok);ps[1].pending=1;assert(!mp4_particle_operation_finish_current(r));++cases;
 reset();throwget=true;bool caught=false;try{(void)run(&r);}catch(const std::runtime_error&){caught=true;}assert(caught&&!r.serial&&!mp4_particle_operation_completion.receipt.serial&&drains==0);++cases;
 reset();throwdrain=true;caught=false;try{(void)run(&r);}catch(const std::runtime_error&){caught=true;}assert(caught&&!r.serial&&!mp4_particle_operation_completion.receipt.serial&&gets==2);++cases;
 reset();assert(run(&r)==Mp4SceneResult::ok);prior=r;current=false;assert(run(&r)==Mp4SceneResult::waiting&&!mp4_particle_operation_finish_current(prior));++cases;
 std::printf("%u actual per-operation particle Finish/drain cases passed\n",cases);
}
