#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <vector>
#include <memory>
#include "particle-state-image.hpp.inc"
struct Region{uintptr_t first=0;size_t bytes=0;};std::vector<Region>regions;std::vector<std::unique_ptr<uint8_t[]>>storage;
bool mp4_actor_mapped(const void*p,size_t n,bool){const auto a=reinterpret_cast<uintptr_t>(p);if(!a||!n||a+n<a)return false;for(const auto&r:regions)if(a>=r.first&&a+n<=r.first+r.bytes)return true;return false;}
bool mp4_actor_refresh_maps(){return true;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof out,false))return false;::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return true;}
template<class T>void write(void*p,size_t at,T value){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof value,true));::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
uint8_t*allocate(size_t bytes){storage.emplace_back(new uint8_t[bytes]{});auto*p=storage.back().get();regions.push_back({reinterpret_cast<uintptr_t>(p),bytes});return p;}
bool source=true,fenced=true,policy_ok=true,public_restored=false,restore_ok=true;bool game_call(){return true;}bool mp4_stage_owner(void*){return source;}bool mp4_actor_clock_held(void*){return fenced;}
bool mp4_type_is(void*p,const char*t){return p&&source&&!std::strcmp(t,"UnityEngine.ParticleSystem");}bool mp4_alive(void*p){return p&&source;}
uintptr_t mp4_native_base=0x20000000;struct{const char*native_sha256=nullptr;}mp4_native_profile;
#ifdef IDOLY_DARWIN_BRIDGE
constexpr struct{const char*sha256;uintptr_t vtable;}mp4_particle_manager_pins{"b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",0x980c5d0};
#else
constexpr struct{const char*sha256;uintptr_t vtable;}mp4_particle_manager_pins{"c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85",0x143a580};
#endif
namespace idoly_mp4_stage{struct Owner{void*particle=nullptr;void*producer=nullptr;uint32_t producer_kind=0;};}
void*managed=nullptr;uint64_t public_capture=13;
struct{bool snapshot_receipt(void*p,idoly_mp4_stage::Owner*out,uint64_t*receipt,bool*restored){if(p!=managed||!source)return false;*out={p,p,1};*receipt=public_capture;*restored=public_restored;return true;}}mp4_stage_particles;
#include "particle-state-host.cpp.inc"
uint8_t*native=nullptr,*state=nullptr,*modules=nullptr,*particles=nullptr,*parameters=nullptr,*data0=nullptr,*data1=nullptr;
mp4ps::Owner owner{},bank[2]{};
bool policy(const mp4ps::Owner&o,uint64_t*out){if(!policy_ok||o.managed!=managed||o.capture!=13)return false;*out=17;return true;}
bool fence(const mp4ps::Owner&o){return fenced&&o.capture==13&&o.policy==17;}
bool restoration(const mp4ps::Owner&o,uint64_t r){return restore_ok&&o.capture==13&&r==19;}
void setup(){managed=allocate(32);native=allocate(0xa8);state=allocate(0x220);modules=allocate(0x1400);particles=allocate(0x20);parameters=allocate(0x40);data0=allocate(1024);data1=allocate(1024);}
void reset(){source=fenced=policy_ok=restore_ok=true;public_restored=false;public_capture=13;::memset(state,0,0x220);::memset(modules,0,0x1400);write(managed,16,reinterpret_cast<uintptr_t>(native));write(native,0,mp4_native_base+mp4_particle_manager_pins.vtable);write(native,8,int32_t(7));write(native,0x38,reinterpret_cast<uintptr_t>(particles));write(native,0x40,reinterpret_cast<uintptr_t>(parameters));write(native,0x48,reinterpret_cast<uintptr_t>(state));write(native,0x50,reinterpret_cast<uintptr_t>(modules));write(native,0x6c,uint8_t(0));write(modules,0x21c,uint32_t(4));write(state,0x1c0,reinterpret_cast<uintptr_t>(data0));write(state,0x1d8,uint64_t(64));write(state,0x200,reinterpret_cast<uintptr_t>(data1));write(state,0x218,uint64_t(128));mp4_native_profile.native_sha256=mp4_particle_manager_pins.sha256;
 bank[0]={};bank[1]={};mp4_particle_native_state_context={bank,1,policy,fence,restoration};bool restored=false;assert(mp4_particle_native_state_source(managed,&owner,&restored)&&!restored);bank[0]=owner;
}
int main(){setup();unsigned cases=0;using R=mp4ps::Result;
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok);state[0x22]=1;modules[0x480]=2;public_restored=true;assert(mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::ok&&!state[0x22]&&!modules[0x480]);++cases;}
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok);auto*newdata=allocate(2048);write(state,0x1c0,reinterpret_cast<uintptr_t>(newdata));write(state,0x1d8,uint64_t(256));write(state,0x1d0,uint64_t(3));public_restored=true;assert(mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::ok);uintptr_t actual=0;assert(mp4_actor_field(state,0x1c0,actual)&&actual==reinterpret_cast<uintptr_t>(newdata));++cases;}
 {reset();policy_ok=false;mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();fenced=false;mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();public_capture=14;mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(managed,16,uintptr_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(native,8,int32_t(8));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(native,0x6c,uint8_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(modules,0x21c,uint32_t(6));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(modules,0x360,uintptr_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(modules,0x420,uintptr_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();write(modules,0x430,uintptr_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::invalid);++cases;}
 {reset();public_restored=true;uint64_t zero=0;assert(!mp4_particle_native_state_write(nullptr,owner.state+0x1c0,8,&zero,19));++cases;}
 {reset();write(state,0x1d0,uint64_t(1));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::unsupported);++cases;}
 {reset();write(state,0x210,uint64_t(999));mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::unsupported);++cases;}
 {reset();public_restored=true;uint64_t nonzero=1;assert(!mp4_particle_native_state_write(nullptr,owner.state+0x1d0,8,&nonzero,19));++cases;}
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok&&mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::stale);++cases;}
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok);public_restored=true;restore_ok=false;assert(mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::unsupported);++cases;}
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok);public_restored=true;bank[1]=bank[0];mp4_particle_native_state_context.count=2;assert(mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::failed);++cases;}
 {reset();mp4ps::Image image;assert(mp4ps::capture(mp4_particle_native_state_api(),owner,image)==R::ok);write(modules,0x430,reinterpret_cast<uintptr_t>(native));public_restored=true;assert(mp4ps::restore(mp4_particle_native_state_api(),image,19)==R::ok);uintptr_t actual=0;assert(mp4_actor_field(modules,0x430,actual)&&actual==reinterpret_cast<uintptr_t>(native));++cases;}
 std::printf("%u concrete native Particle State host cases passed; native source/fence/restore providers modeled\n",cases);
}
