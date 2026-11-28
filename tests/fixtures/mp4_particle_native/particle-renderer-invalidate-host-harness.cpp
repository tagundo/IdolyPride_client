#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <initializer_list>
#include <stdexcept>
#include "particle-state-image.hpp.inc"
namespace mp4ps=idoly_mp4_particle_state;
uint8_t native_memory[0x850]{},vtable[0x180]{},source_base[16]{},source_ret[16]{};
uintptr_t mp4_native_base=1;void*particle=reinterpret_cast<void*>(0x1234),*renderer=reinterpret_cast<void*>(0x5678);mp4ps::Owner accepted{};
struct Pin{uintptr_t rva=0;size_t bytes=0;uint8_t body[28]{};uintptr_t base=0;uint8_t branch[4]{};uintptr_t ret=0;uint8_t end[4]{};}mp4_particle_renderer_invalidate_pin;
struct{uintptr_t renderer_vtable=0;}mp4_particle_policy_pins;
struct Policy{mp4ps::Owner owner{};void*renderer=nullptr;uintptr_t renderer_native=0;int32_t renderer_id=0;uint64_t serial=0;}mp4_particle_source_policies[1];
size_t mp4_particle_source_policy_count=1;bool main_thread=true,reader=true,current=true,restoring=false,mapped=true;int calls=0,mode=0;
bool game_call(){return main_thread;}bool mp4_particle_renderer_reader_bindings(){return reader;}
bool mp4_native_mapped(uintptr_t,size_t,int){return mapped;}
bool mp4_particle_data_current(const mp4ps::Owner&o){return main_thread&&reader&&current&&mp4ps::same(o,accepted);}
bool mp4_particle_native_restore_owner(const mp4ps::Owner&o,uint64_t r){return r==17&&restoring&&mp4_particle_data_current(o);}
bool mp4_particle_source_policy_owner(void*p,mp4ps::Owner*out){if(p!=particle||!current||!main_thread)return false;*out=accepted;return true;}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){if((p==native_memory&&off+sizeof v<=sizeof native_memory)||(p==vtable&&off+sizeof v<=sizeof vtable)){::memcpy(&v,static_cast<uint8_t*>(p)+off,sizeof v);return true;}return false;}
template<class T>void put(size_t off,T v){::memcpy(native_memory+off,&v,sizeof v);}
void original(void*self,uintptr_t one,uintptr_t two,bool skip){assert(self==native_memory&&!one&&!two&&skip);++calls;if(mode==1)return;if(mode==2){current=false;return;}if(mode==3)throw std::runtime_error("original");put(0x448,uint32_t(0));put(0x450,uint32_t(0));put(0x74c,uint8_t(0));}
#include "particle-renderer-invalidate-host.inc"
void reset(){main_thread=reader=current=mapped=true;restoring=false;calls=mode=0;::memset(native_memory,0,sizeof native_memory);::memset(vtable,0,sizeof vtable);accepted={};accepted.managed=particle;accepted.native=777;accepted.instance=3;accepted.capture=5;accepted.policy=7;mp4_particle_source_policy_count=1;mp4_particle_source_policies[0]={accepted,renderer,reinterpret_cast<uintptr_t>(native_memory),11,7};mp4_particle_policy_pins.renderer_vtable=reinterpret_cast<uintptr_t>(vtable)-1;put(0,reinterpret_cast<uintptr_t>(vtable));put(8,int32_t(11));put(0x448,uint32_t(999));put(0x450,uint32_t(888));put(0x74c,uint8_t(1));put(0x750,uintptr_t(0xfeedface));auto entry=reinterpret_cast<uintptr_t>(&original);::memcpy(vtable+0x168,&entry,8);auto&p=mp4_particle_renderer_invalidate_pin;p={};p.rva=entry-1;p.bytes=28;::memcpy(p.body,reinterpret_cast<void*>(entry),28);p.base=reinterpret_cast<uintptr_t>(source_base)-1;p.ret=reinterpret_cast<uintptr_t>(source_ret)-1;}
Mp4ParticleRendererCacheImage capture(){Mp4ParticleRendererCacheImage image{};assert(mp4_particle_renderer_cache_capture(accepted,image)&&image.serial);return image;}
int main(){unsigned cases=0;
 {reset();auto image=capture();assert(!mp4_particle_renderer_cache_invalidated(image));restoring=true;assert(mp4_particle_renderer_cache_restore(image,17)&&image.invalidated&&calls==1);uintptr_t untouched=0;assert(mp4_actor_field(native_memory,0x750,untouched)&&untouched==0xfeedface);assert(mp4_particle_renderer_cache_invalidated(image));auto old=image.serial;image={};assert(mp4_particle_renderer_cache_capture(accepted,image)&&image.serial>old);++cases;}
 for(int state=0;state<10;++state){reset();Mp4ParticleRendererCacheImage image{};if(state==0)main_thread=false;if(state==1)reader=false;if(state==2)current=false;if(state==3)mapped=false;if(state==4)++mp4_particle_renderer_invalidate_pin.body[0];if(state==5)++mp4_particle_renderer_invalidate_pin.branch[0];if(state==6)++mp4_particle_renderer_invalidate_pin.end[0];if(state==7)mp4_particle_source_policies[0].renderer_id++;if(state==8)put(0,uintptr_t(1));if(state==9){uintptr_t zero=0;::memcpy(vtable+0x168,&zero,8);}assert(!mp4_particle_renderer_cache_capture(accepted,image)&&!image.captured&&!image.serial&&!calls);++cases;}
 for(int state=0;state<8;++state){reset();auto image=capture();restoring=true;if(state==0)restoring=false;if(state==1)reader=false;if(state==2)current=false;if(state==3)++image.policy;if(state==4)++image.owner.instance;if(state==5)image.serial=0;if(state==6)image.captured=false;if(state==7)mp4_particle_source_policies[0].renderer=reinterpret_cast<void*>(1);assert(!mp4_particle_renderer_cache_restore(image,17)&&!image.invalidated&&!calls);++cases;}
 for(int state=1;state<=3;++state){reset();auto image=capture();restoring=true;mode=state;bool result=false;try{result=mp4_particle_renderer_cache_restore(image,17);}catch(const std::runtime_error&){assert(state==3);}assert(!result&&!image.invalidated&&calls==1);++cases;}
 std::printf("%u actual native PSR invalidation-branch cases passed\n",cases);
}
