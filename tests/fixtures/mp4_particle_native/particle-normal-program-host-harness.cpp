#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <cstddef>
struct Mp4ParticleNormalProgramCode{uintptr_t rva=0;size_t bytes=0;uint8_t body[4096]{};};
struct Mp4ParticleNormalProgramPins{uintptr_t context=0,wrapper=0;size_t count=0;Mp4ParticleNormalProgramCode code[9]{};}mp4_particle_normal_program_pins;
uintptr_t mp4_native_base=1;bool main_thread=true,reader=true,mapped=true;uint8_t code[9][4096]{},event[0xc10]{};int count_reads=0;bool drift=false;
bool game_call(){return main_thread;}bool mp4_particle_renderer_reader_bindings(){return reader;}
bool mp4_native_mapped(uintptr_t at,size_t n,int flags){if(!mapped||flags!=5)return false;for(auto&a:code){const auto base=reinterpret_cast<uintptr_t>(a);if(at>=base&&at+n<=base+sizeof a)return true;}return false;}
template<class T>void put(size_t off,const T&v){assert(off+sizeof v<=sizeof event);::memcpy(event+off,&v,sizeof v);}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){if(p!=event||off+sizeof v>sizeof event)return false;if(off==0xc00&&++count_reads==2&&drift){put(0xc00,uint32_t(3));}::memcpy(&v,event+off,sizeof v);return true;}
#include "particle-normal-program-host.inc"
void reset(){main_thread=reader=mapped=true;count_reads=0;drift=false;::memset(event,0,sizeof event);auto&p=mp4_particle_normal_program_pins;p={};p.context=reinterpret_cast<uintptr_t>(event)-mp4_native_base-0x2c988;p.wrapper=0x12340;p.count=9;for(size_t i=0;i<9;++i){for(size_t j=0;j<4096;++j)code[i][j]=uint8_t(i+j);p.code[i].rva=reinterpret_cast<uintptr_t>(code[i])-mp4_native_base;p.code[i].bytes=4096;::memcpy(p.code[i].body,code[i],4096);}put(0xc00,uint32_t(1));put(0,mp4_native_base+p.wrapper);}
int main(){unsigned cases=0;
 reset();assert(mp4_particle_renderer_normal_program_bindings());++cases;
 reset();put(0xc00,uint32_t(128));put(0,uintptr_t(0));put(127*24,mp4_native_base+mp4_particle_normal_program_pins.wrapper);put(24,uintptr_t(0xdead));put(24+8,uintptr_t(0xdef));put(24+16,uint8_t(1));assert(mp4_particle_renderer_normal_program_bindings());++cases;
 for(int bad=0;bad<13;++bad){reset();if(bad==0)main_thread=false;if(bad==1)reader=false;if(bad==2)mapped=false;if(bad==3)mp4_particle_normal_program_pins.context=0;if(bad==4)mp4_particle_normal_program_pins.wrapper=0;if(bad==5)--mp4_particle_normal_program_pins.count;if(bad==6)put(0xc00,uint32_t(0));if(bad==7)put(0xc00,uint32_t(129));if(bad==8)put(0xc08,uintptr_t(1));if(bad==9)put(0,uintptr_t(0));if(bad==10)put(8,uintptr_t(1));if(bad==11)put(16,uint8_t(1));if(bad==12){put(0xc00,uint32_t(2));put(24,mp4_native_base+mp4_particle_normal_program_pins.wrapper);}assert(!mp4_particle_renderer_normal_program_bindings());++cases;}
 for(size_t i=0;i<9;++i){reset();code[i][4095]^=1;assert(!mp4_particle_renderer_normal_program_bindings());++cases;}
 for(int bad=0;bad<3;++bad){reset();if(bad==0)mp4_particle_normal_program_pins.code[0].rva=0;if(bad==1)mp4_particle_normal_program_pins.code[0].bytes=0;if(bad==2)mp4_particle_normal_program_pins.code[0].bytes=4097;assert(!mp4_particle_renderer_normal_program_bindings());++cases;}
 reset();drift=true;assert(!mp4_particle_renderer_normal_program_bindings());++cases;
 std::printf("%u actual normal renderer programme host cases passed\n",cases);
}
