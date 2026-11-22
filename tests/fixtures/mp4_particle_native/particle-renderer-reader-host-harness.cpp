#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
struct Mp4ParticleRendererReaderPin{uintptr_t rva;uint8_t prefix[16];};
Mp4ParticleRendererReaderPin mp4_particle_renderer_reader_pin{};
uint8_t manager_mem[0x90]{},other_manager[0x90]{};uintptr_t singleton=0,mp4_native_base=1;
struct{const char*native_sha256="native";}mp4_native_profile;
struct{const char*sha256="native";uintptr_t singleton=0;}mp4_particle_manager_pins;
struct{struct{uint64_t generation=7;}source;}mp4_stage_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
struct{uint64_t serial=13;}mp4_particle_mutation_boundary;
struct{uint64_t generation=17;}mp4_particle_mutation_host;
bool main_thread=true,boundary=true,mapping=true,pin_current=true;int original_mode=0,calls=0;
bool game_call(){return main_thread;}bool mp4_particle_native_capture_boundary(){return boundary;}
bool mp4_particle_native_state_mapped(uintptr_t p,size_t n){return n<=0x90&&(p==reinterpret_cast<uintptr_t>(manager_mem)||p==reinterpret_cast<uintptr_t>(other_manager));}
bool mp4_native_mapped(uintptr_t,size_t,int){return mapping;}
template<class T>bool mp4_actor_field(void*p,size_t o,T&v){if(p==&singleton&&o==0&&sizeof v==sizeof singleton){::memcpy(&v,p,sizeof v);return true;}if((p==manager_mem||p==other_manager)&&o+sizeof v<=0x90){::memcpy(&v,static_cast<uint8_t*>(p)+o,sizeof v);return true;}return false;}
template<class T>void put(size_t o,T v){::memcpy(manager_mem+o,&v,sizeof v);}
void original(){++calls;if(original_mode==1)return;if(original_mode==2)throw std::runtime_error("original");put(0x40,uint32_t(0));put(0x80,uintptr_t(0));if(original_mode==3)singleton=reinterpret_cast<uintptr_t>(other_manager);if(original_mode==4)++mp4_particle_mutation_host.generation;if(original_mode==5)++mp4_particle_mutation_boundary.serial;if(original_mode==6)++idoly_mp4_runtime::job.generation;if(original_mode==7)++mp4_stage_host.source.generation;if(original_mode==8)boundary=false;}
#include "particle-renderer-reader-host.inc"
void reset(){main_thread=boundary=mapping=pin_current=true;original_mode=calls=0;::memset(manager_mem,0,sizeof manager_mem);::memset(other_manager,0,sizeof other_manager);singleton=reinterpret_cast<uintptr_t>(manager_mem);mp4_particle_manager_pins.singleton=reinterpret_cast<uintptr_t>(&singleton)-1;mp4_native_profile.native_sha256="native";mp4_particle_renderer_reader_pin.rva=reinterpret_cast<uintptr_t>(&original)-1;::memcpy(mp4_particle_renderer_reader_pin.prefix,reinterpret_cast<void*>(&original),16);mp4_stage_host.source.generation=7;idoly_mp4_runtime::job.generation=11;mp4_particle_mutation_boundary.serial=13;mp4_particle_mutation_host.generation=17;mp4_particle_renderer_reader_withdraw();put(0x40,uint32_t(2));put(0x80,uintptr_t(0x1234));}
int main(){unsigned cases=0;
 {reset();assert(mp4_particle_renderer_reader_finish()&&calls==1&&mp4_particle_renderer_reader_current());auto old=mp4_particle_renderer_reader_receipt.serial;mp4_particle_renderer_reader_withdraw();assert(!mp4_particle_renderer_reader_current());assert(mp4_particle_renderer_reader_finish()&&mp4_particle_renderer_reader_receipt.serial>old);++cases;}
 for(int mode=1;mode<=8;++mode){reset();assert(mp4_particle_renderer_reader_finish());original_mode=mode;put(0x40,uint32_t(2));put(0x80,uintptr_t(0x1234));bool ok=false;try{ok=mp4_particle_renderer_reader_finish();}catch(const std::runtime_error&){assert(mode==2);}assert(!ok&&!mp4_particle_renderer_reader_receipt.serial&&!mp4_particle_renderer_reader_current());++cases;}
 for(int state=0;state<8;++state){reset();if(state==0)main_thread=false;if(state==1)boundary=false;if(state==2)mapping=false;if(state==3)mp4_native_profile.native_sha256="wrong";if(state==4)++mp4_particle_renderer_reader_pin.prefix[0];if(state==5)singleton=0;if(state==6)mp4_native_base=0;if(state==7)mp4_particle_renderer_reader_sequence=~uint64_t(0);assert(!mp4_particle_renderer_reader_finish()&&calls==0);mp4_native_base=1;if(state==7)mp4_particle_renderer_reader_sequence=100; ++cases;}
 for(int state=0;state<5;++state){reset();assert(mp4_particle_renderer_reader_finish());if(state==0)put(0x40,uint32_t(1));if(state==1)put(0x80,uintptr_t(1));if(state==2)++mp4_particle_mutation_host.generation;if(state==3)++mp4_particle_mutation_boundary.serial;if(state==4)main_thread=false;assert(!mp4_particle_renderer_reader_current());++cases;}
 std::printf("%u actual native renderer-reader host cases passed\n",cases);
}
