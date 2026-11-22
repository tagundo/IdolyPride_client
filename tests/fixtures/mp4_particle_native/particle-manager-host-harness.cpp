#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <vector>
#include <memory>
#include <sys/mman.h>
#include "particle-manager-scope.hpp.inc"
struct Region {uintptr_t first=0;size_t bytes=0;};std::vector<Region>regions;
bool mp4_actor_mapped(const void*p,size_t n,bool){const auto at=reinterpret_cast<uintptr_t>(p);if(!at||!n||at+n<at)return false;for(auto&r:regions)if(at>=r.first&&at+n<=r.first+r.bytes)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof(T),false))return false;std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
template<class T>void write(void*p,size_t at,const T&v){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof(T),true));std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
std::vector<std::unique_ptr<uint8_t[]>>storage;
uint8_t*allocate(size_t n){storage.emplace_back(new uint8_t[n]{});auto*p=storage.back().get();regions.push_back({reinterpret_cast<uintptr_t>(p),n});return p;}
bool live=true,fenced=true,restore_live=true;bool game_call(){return true;}bool mp4_stage_owner(void*){return live;}bool mp4_actor_clock_held(void*){return fenced;}
uintptr_t mp4_native_base=0;struct{const char*native_sha256=nullptr;}mp4_native_profile;
#include "particle-manager-host.cpp.inc"
bool fence(uint64_t e,uint64_t c){return fenced&&e==5&&c==7;}
bool restore(uint64_t e,uint64_t r){return restore_live&&e==5&&r==11;}
uint8_t*manager=nullptr;uint8_t*arrays[2]{};mp4pm::Member particles[6]{};
void set_array(unsigned which,std::initializer_list<unsigned>ids){const auto off=which?32:0;write(manager,off,reinterpret_cast<uintptr_t>(arrays[which]));write(manager,off+16,uint64_t(ids.size()));write(manager,off+24,uint64_t(32*2));size_t i=0;for(auto id:ids){write(arrays[which],i*8,particles[id].native);write(reinterpret_cast<void*>(particles[id].native),0x68,which?int32_t(-1):static_cast<int32_t>(i));++i;}}
void init(){
 const size_t size=(mp4_particle_manager_pins.singleton&~uintptr_t(4095))+8192;
 void*image=mmap(nullptr,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(image!=MAP_FAILED);mp4_native_base=reinterpret_cast<uintptr_t>(image);
 regions.push_back({mp4_native_base+mp4_particle_manager_pins.singleton,8});
 manager=allocate(64);arrays[0]=allocate(32*8);arrays[1]=allocate(32*8);
 for(unsigned i=0;i<6;++i){auto*p=allocate(0xa8);particles[i]={reinterpret_cast<uintptr_t>(p),static_cast<int32_t>(100+i)};write(p,0,mp4_native_base+mp4_particle_manager_pins.vtable);write(p,8,particles[i].instance);write(p,0x68,int32_t(-1));}
 write(reinterpret_cast<void*>(mp4_native_base+mp4_particle_manager_pins.singleton),0,reinterpret_cast<uintptr_t>(manager));mp4_native_profile.native_sha256=mp4_particle_manager_pins.sha256;
}
void reset(){live=fenced=restore_live=true;mp4_particle_manager_context={5,7,fence,restore};for(auto&m:particles)write(reinterpret_cast<void*>(m.native),0x68,int32_t(-1));set_array(0,{0,1,2,3});set_array(1,{4,5});}
int main(){init();unsigned cases=0;using R=mp4pm::Result;
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);assert(s.verify()==R::ok&&s.restore(11)==R::ok);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{0,2,1,3});assert(s.verify()==R::failed);assert(s.restore(11)==R::ok&&s.verify()==R::ok);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{3,2,1,0});set_array(1,{5,4});assert(s.restore(11)==R::ok);int32_t index=-1;for(unsigned i=0;i<4;++i){assert(mp4_particle_manager_index(nullptr,particles[i],&index)&&index==static_cast<int32_t>(i));}++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{0,2,3});assert(s.restore(11)==R::waiting);mp4pm::View v{};assert(mp4_particle_manager_view(nullptr,0,&v)&&v.count==3);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{0,1,2,3,4});set_array(1,{5});assert(s.restore(11)==R::waiting);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{0,2,1,3});restore_live=false;assert(s.restore(11)==R::unsupported);uintptr_t row=0;assert(mp4_actor_field(arrays[0],8,row)&&row==particles[2].native);assert(!mp4_particle_manager_write_index(nullptr,particles[1],1,11));++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);set_array(0,{0,2,1,3});fenced=false;assert(s.restore(11)==R::stale);assert(!mp4_particle_manager_write_row(nullptr,{reinterpret_cast<uintptr_t>(manager),reinterpret_cast<uintptr_t>(arrays[0]),4,32},1,particles[1],11));++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);live=false;assert(s.verify()==R::stale&&s.restore(11)==R::stale);s.abandon();++cases;}
 {reset();set_array(0,{0,1,1,3});mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::stale);++cases;}
 {reset();set_array(1,{4,1});mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::stale);++cases;}
 {reset();write(reinterpret_cast<void*>(particles[2].native),0,uintptr_t(1));mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::stale);write(reinterpret_cast<void*>(particles[2].native),0,mp4_native_base+mp4_particle_manager_pins.vtable);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);write(reinterpret_cast<void*>(particles[1].native),8,int32_t(909));assert(s.restore(11)==R::waiting);write(reinterpret_cast<void*>(particles[1].native),8,particles[1].instance);++cases;}
 {reset();write(manager,24,uint64_t(2));mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::unsupported);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);auto*new_array=allocate(32*8);std::memcpy(new_array,arrays[0],4*8);write(manager,0,reinterpret_cast<uintptr_t>(new_array));assert(s.verify()==R::ok);++cases;}
 {reset();mp4pm::Scope s;assert(s.capture(mp4_particle_manager_api(),5,7)==R::ok);assert(s.restore(12)==R::unsupported);++cases;}
 std::printf("%u actual-host ParticleSystemManager cases passed; native callbacks/job fence modeled\n",cases);
}
