// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <pthread.h>
thread_local bool main_thread=false;
bool game_call(){return main_thread;}using Method=void;
namespace mp4pf{enum class Result{unowned};}
struct Owner{bool started=true;uint64_t serial=13,job=11;void*batch=nullptr;}owner,*mp4_proflare_coordinator=&owner;
namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;struct Clock{bool live=true;bool active(){return live;}}clock;Clock&native_clock_scope(){return clock;}}
unsigned handoffs=0;std::atomic<unsigned>originals{0};bool throw_original=false;

#include "access-host.inc"

bool mp4_proflare_handoff(void*,mp4pf::Result){++handoffs;mp4_proflare_access_withdrawn.store(true,std::memory_order_release);return false;}
void original(void*,Method*){++originals;if(throw_original)throw 37;}
void reset(){assert(mp4_proflare_access_idle());main_thread=true;owner={};owner.batch=&owner;mp4_proflare_coordinator=&owner;idoly_mp4_runtime::job.generation=11;idoly_mp4_runtime::clock.live=true;handoffs=0;originals=0;throw_original=false;mp4_proflare_access_published=false;mp4_proflare_access_withdrawn=false;}

#include "coordinator-batch-late.inc"

#include "coordinator-batch-disable.inc"
int main(){unsigned cases=0;reset();assert(!mp4_proflare_access_current()&&mp4_proflare_access_idle());{Mp4ProFlareAccess a;assert(mp4_proflare_access_current()&&!mp4_proflare_access_idle());{Mp4ProFlareAccess b;assert(mp4_proflare_access_depth==2&&mp4_proflare_access_current());}assert(mp4_proflare_access_depth==1);}assert(mp4_proflare_access_idle());++cases;
 reset();std::thread ordinary([]{Mp4ProFlareAccess a(true);assert(!mp4_proflare_access_current());++originals;});ordinary.join();assert(originals==1&&!mp4_proflare_access_withdrawn);++cases;
 reset();mp4_proflare_access_published=true;std::thread foreign;{Mp4ProFlareAccess a;foreign=std::thread([]{Mp4ProFlareAccess b(true);assert(!mp4_proflare_access_current());++originals;});while(!mp4_proflare_access_withdrawn.load(std::memory_order_acquire))std::this_thread::yield();assert(originals==0&&!mp4_proflare_access_current());}foreign.join();assert(originals==1&&mp4_proflare_access_idle());++cases;
 reset();mp4_proflare_batch_late_invoke(owner.batch,nullptr,original);assert(originals==1&&!handoffs);++cases;
 reset();mp4_proflare_access_published=true;mp4_proflare_batch_late_invoke(owner.batch,nullptr,original);assert(!originals&&!handoffs);++cases;
 for(int bad=0;bad<7;++bad){reset();mp4_proflare_access_published=true;if(bad==0)owner.started=false;if(bad==1)owner.serial=0;if(bad==2)owner.job=12;if(bad==3)idoly_mp4_runtime::clock.live=false;if(bad==4)mp4_proflare_access_withdrawn=true;if(bad==5)mp4_proflare_coordinator=nullptr;void*b=bad==6?static_cast<void*>(&originals):owner.batch;mp4_proflare_batch_late_invoke(b,nullptr,original);assert(originals==1&&handoffs==1&&mp4_proflare_access_withdrawn);++cases;}
 reset();mp4_proflare_access_published=true;std::thread late([]{mp4_proflare_batch_late_invoke(owner.batch,nullptr,original);});late.join();assert(originals==1&&handoffs==1&&mp4_proflare_access_withdrawn);++cases;
 reset();mp4_proflare_access_published=true;mp4_proflare_batch_disable_invoke(owner.batch,nullptr,original);assert(originals==1&&handoffs==1&&mp4_proflare_access_withdrawn);++cases;
 reset();mp4_proflare_batch_disable_invoke(owner.batch,nullptr,original);assert(originals==1&&!handoffs);++cases;
 reset();throw_original=true;bool caught=false;try{mp4_proflare_batch_disable_invoke(owner.batch,nullptr,original);}catch(int e){caught=e==37;}assert(caught&&originals==1&&mp4_proflare_access_idle());++cases;
 reset();mp4_proflare_batch_late_invoke(owner.batch,nullptr,nullptr);mp4_proflare_batch_disable_invoke(owner.batch,nullptr,nullptr);assert(!originals&&!handoffs&&mp4_proflare_access_idle());++cases;
 reset();{Mp4ProFlareAccess a;{Mp4ProFlareAccess b;Mp4ProFlareAccessPause nested;assert(!nested&&mp4_proflare_access_depth==2);}assert(mp4_proflare_access_current());}++cases;
 reset();mp4_proflare_access_published=true;{Mp4ProFlareAccess a;{Mp4ProFlareAccessPause pause;assert(pause&&mp4_proflare_access_idle()&&!mp4_proflare_access_current());std::thread writer([]{Mp4ProFlareAccess b(true);++originals;});writer.join();assert(originals==1);}assert(mp4_proflare_access_depth==1&&!mp4_proflare_access_current());}assert(mp4_proflare_access_idle());++cases;
 reset();{Mp4ProFlareAccess a;bool caught=false;try{Mp4ProFlareAccessPause pause;assert(pause);throw 41;}catch(int e){caught=e==41;}assert(caught&&mp4_proflare_access_depth==1&&mp4_proflare_access_current());}++cases;
 std::printf("%u actual PF whole-access/Late/Disable cases passed\n",cases);}
