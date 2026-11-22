#include <atomic>
#include <thread>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
thread_local bool owner_thread=true;
bool game_call(){return owner_thread;}
#include "particle-operation-rw-host.inc"
int main(){unsigned n=0;uint64_t watch=0;
 assert(mp4_particle_operation_read_begin(&watch)&&mp4_particle_operation_read_stable(watch));++n;
 uint64_t nested=0;assert(mp4_particle_operation_read_begin(&nested)&&nested==watch);++n;mp4_particle_operation_read_end();assert(mp4_particle_operation_read_stable(watch));++n;mp4_particle_operation_read_end();assert(!mp4_particle_operation_read_stable(watch));++n;
 {Mp4ParticleOperationWriter w;assert(!mp4_particle_operation_read_begin(&watch));++n;}assert(!mp4_particle_operation_writers);++n;
 {Mp4ParticleOperationRead r;assert(r);{Mp4ParticleOperationWriter w;assert(!r);++n;}assert(!r);++n;}
 {Mp4ParticleOperationRead r;assert(r);std::atomic<bool>body{false};std::thread t([&]{owner_thread=false;Mp4ParticleOperationWriter w;body.store(true,std::memory_order_release);});while(!__atomic_load_n(&mp4_particle_operation_writers,__ATOMIC_SEQ_CST))std::this_thread::yield();assert(!body.load(std::memory_order_acquire)&&!r);++n;mp4_particle_operation_read_end();r.acquired=false;t.join();assert(body.load()&&!mp4_particle_operation_writers);++n;}
 {std::atomic<bool>entered{false},leave{false};std::thread t([&]{owner_thread=false;Mp4ParticleOperationWriter w;entered.store(true);while(!leave.load())std::this_thread::yield();});while(!entered.load())std::this_thread::yield();assert(!mp4_particle_operation_read_begin(&watch));++n;leave.store(true);t.join();}
 try{Mp4ParticleOperationWriter w;throw std::runtime_error("ordinary");}catch(const std::runtime_error&){}assert(!mp4_particle_operation_writers);++n;
 {Mp4ParticleOperationRead r;assert(r);++n;}owner_thread=false;assert(!mp4_particle_operation_read_begin(&watch));owner_thread=true;++n;
 std::printf("%u actual particle writer/read concurrency cases passed\n",n);
}
