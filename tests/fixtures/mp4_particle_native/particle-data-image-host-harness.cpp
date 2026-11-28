#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <memory>
#include <vector>
#include "particle-state-image.hpp.inc"
namespace mp4ps=idoly_mp4_particle_state;
struct R{uintptr_t p;size_t n;};std::vector<R>regions;std::vector<std::unique_ptr<uint8_t[]>>storage;
void*alloc(size_t n){storage.emplace_back(new uint8_t[n]{});void*p=storage.back().get();regions.push_back({reinterpret_cast<uintptr_t>(p),n});return p;}
bool mapped(uintptr_t p,size_t n){for(auto&r:regions)if(p>=r.p&&p+n>=p&&p+n<=r.p+r.n)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t o,T&v){auto at=reinterpret_cast<uintptr_t>(p)+o;if(!mapped(at,sizeof v))return false;::memcpy(&v,reinterpret_cast<void*>(at),sizeof v);return true;}
template<class T>void put(uintptr_t p,size_t o,T v){assert(mapped(p+o,sizeof v));::memcpy(reinterpret_cast<void*>(p+o),&v,sizeof v);}
bool main_thread=true,reader=true,owner_current=true,restoring=false,resize_current=true,writable=true;uint64_t restore_token=31;unsigned resizes=0;mp4ps::Owner accepted{};
bool game_call(){return main_thread;}bool mp4_particle_native_state_mapped(uintptr_t p,size_t n,bool write=false){return (!write||writable)&&mapped(p,n);}
bool mp4_particle_renderer_reader_current(){return reader;}
bool mp4_particle_native_owner_fence(const mp4ps::Owner&o){return owner_current&&mp4ps::same(o,accepted);}
bool mp4_particle_native_restore_owner(const mp4ps::Owner&o,uint64_t r){return restoring&&r==restore_token&&mp4_particle_native_owner_fence(o);}
uintptr_t mp4_native_base=1;struct{uintptr_t rva=0;}mp4_particle_data_bit_resize_pin;
bool mp4_particle_data_bit_resize_current(){return resize_current;}
void bit_resize(void*bits,uint64_t count,bool value){assert(!value&&restoring);++resizes;auto address=reinterpret_cast<uintptr_t>(bits);auto words=(count+31)>>5;auto data=words?reinterpret_cast<uintptr_t>(alloc(words*4)):0;put(address,8,data);put(address,16,count);put(address,24,words);}
#include "particle-data-image-host.inc"
void array(uint32_t at,uint64_t count,uint64_t cap){auto data=cap?reinterpret_cast<uintptr_t>(alloc(cap*4)):0;put(accepted.particles,at,data);put(accepted.particles,at+8,uint32_t(47));put(accepted.particles,at+16,count);put(accepted.particles,at+24,cap<<1);for(uint64_t i=0;i<cap;++i)put(data,i*4,uint32_t(at*13+i*7));}
void bits(uint32_t at,uint64_t count){auto words=(count+31)>>5;auto data=words?reinterpret_cast<uintptr_t>(alloc(words*4)):0;put(accepted.particles,at,uint32_t(53));put(accepted.particles,at+8,data);put(accepted.particles,at+16,count);put(accepted.particles,at+24,words);for(uint64_t i=0;i<words;++i)put(data,i*4,uint32_t(i+0x12345678));}
void setup(bool empty=false){mp4_particle_data_bit_resize_pin.rva=reinterpret_cast<uintptr_t>(&bit_resize)-1;main_thread=reader=owner_current=resize_current=writable=true;restoring=false;resizes=0;accepted={};accepted.managed=alloc(32);accepted.native=reinterpret_cast<uintptr_t>(alloc(0xb0));accepted.particles=reinterpret_cast<uintptr_t>(alloc(0x7f0));accepted.instance=3;accepted.capture=7;accepted.policy=11;put(accepted.particles,0x7e8,uint32_t(1));for(size_t i=0;i<50;++i)array(mp4_particle_data_array_offset(i),empty?0:5,empty?0:8);bits(0x520,empty?0:35);bits(0x5e0,empty?0:35);put(accepted.particles,0x7e4,int32_t(2));}
Mp4ParticleDataImage capture(){Mp4ParticleDataImage image{};assert(mp4_particle_data_capture(accepted,image)&&image.captured);return image;}
void exported(){for(size_t i=0;i<50;++i)array(mp4_particle_data_array_offset(i),13,16);bits(0x520,65);bits(0x5e0,65);put(accepted.particles,0x7d0,uint8_t(1));}
int main(){unsigned cases=0;
 {setup();auto image=capture();assert(mp4_particle_data_verify(image));exported();uintptr_t current=0;assert(mp4_actor_field(reinterpret_cast<void*>(accepted.particles),0,current));restoring=true;assert(mp4_particle_data_restore(image,31)&&image.restored&&resizes==2);uintptr_t after=0;assert(mp4_actor_field(reinterpret_cast<void*>(accepted.particles),0,after)&&after==current);uint64_t cap=0;assert(mp4_actor_field(reinterpret_cast<void*>(accepted.particles),24,cap)&&cap==32);assert(mp4_particle_data_verify(image));mp4_particle_data_release(image);assert(!image.payload&&!image.captured);++cases;}
 {setup(true);auto image=capture();exported();restoring=true;assert(mp4_particle_data_restore(image,31)&&resizes==2&&mp4_particle_data_verify(image));mp4_particle_data_release(image);++cases;}
 for(int state=0;state<13;++state){setup();Mp4ParticleDataImage image{};if(state==0)main_thread=false;if(state==1)reader=false;if(state==2)owner_current=false;if(state==3)put(accepted.particles,0x7e8,uint32_t(2));if(state==4)put(accepted.particles,0x550,uint64_t(1));if(state==5)put(accepted.particles,0x6a0,uint64_t(1));if(state==6)put(accepted.particles,0x7da,uint8_t(1));if(state==7)put(accepted.particles,24,uint64_t(17));if(state==8)put(accepted.particles,16,uint64_t(9));if(state==9)put(accepted.particles,0x538,uint64_t(4));if(state==10)put(accepted.particles,0x7e4,int32_t(3));if(state==11){uintptr_t p=0;assert(mp4_actor_field(reinterpret_cast<void*>(accepted.particles),0,p));put(accepted.particles,32,p);}if(state==12)put(accepted.particles,16,uint64_t(7));if(state==12)put(accepted.particles,24,uint64_t(14));assert(!mp4_particle_data_capture(accepted,image)&&!image.payload&&!image.captured);++cases;}
 for(int state=0;state<12;++state){setup();auto image=capture();exported();restoring=true;if(state==0)restoring=false;if(state==1)reader=false;if(state==2)owner_current=false;if(state==3)resize_current=false;if(state==4)put(accepted.particles,0x550,uint64_t(1));if(state==5)put(accepted.particles,0x6a8,uint64_t(1));if(state==6)put(accepted.particles,0x7e8,uint32_t(2));if(state==7)put(accepted.particles,8,uint32_t(99));if(state==8)put(accepted.particles,0x520,uint32_t(99));if(state==9)array(0,1,4);if(state==10)main_thread=false;if(state==11)writable=false;assert(!mp4_particle_data_restore(image,31)&&!image.restored);mp4_particle_data_release(image);++cases;}
 {setup();auto image=capture();restoring=true;assert(!mp4_particle_data_restore(image,32)&&!resizes);mp4_particle_data_release(image);++cases;}
 for(int state=0;state<4;++state){setup();auto image=capture();if(state==0){uintptr_t p=0;assert(mp4_actor_field(reinterpret_cast<void*>(accepted.particles),0,p));put(p,7*4,uint32_t(999));}if(state==1)put(accepted.particles,0x7d0,uint8_t(1));if(state==2)put(accepted.particles,0x30,uint64_t(4));if(state==3)++image.owner.instance;assert(!mp4_particle_data_verify(image));mp4_particle_data_release(image);++cases;}
 {setup();auto previous=mp4_particle_data_bytes_live;mp4_particle_data_bytes_live=mp4_particle_data_budget;Mp4ParticleDataImage image{};assert(!mp4_particle_data_capture(accepted,image)&&!image.payload);mp4_particle_data_bytes_live=previous;++cases;}
 assert(mp4_particle_data_bytes_live==0);
 std::printf("%u actual native PSData logical-image cases passed\n",cases);
}
