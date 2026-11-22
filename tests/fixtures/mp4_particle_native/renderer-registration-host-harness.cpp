#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <vector>
#include <memory>
#include <sys/mman.h>
#include "renderer-registration-state.hpp.inc"
struct Region{uintptr_t first=0;size_t bytes=0;};std::vector<Region>regions;std::vector<std::unique_ptr<uint8_t[]>>storage;
bool mp4_actor_mapped(const void*p,size_t n,bool){const auto a=reinterpret_cast<uintptr_t>(p);if(!a||!n||a+n<a)return false;for(const auto&r:regions)if(a>=r.first&&a+n<=r.first+r.bytes)return true;return false;}
bool mp4_actor_refresh_maps(){return true;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof out,false))return false;::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return true;}
template<class T>void write(void*p,size_t at,T value){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof value,true));::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
uint8_t*allocate(size_t bytes){storage.emplace_back(new uint8_t[bytes]{});auto*p=storage.back().get();regions.push_back({reinterpret_cast<uintptr_t>(p),bytes});return p;}
bool source=true,fenced=true,restore_ok=true,source_ok=true;bool game_call(){return true;}bool mp4_stage_owner(void*){return source;}bool mp4_actor_clock_held(void*){return fenced;}
uintptr_t mp4_native_base=0x20000000;struct{const char*native_sha256=nullptr;}mp4_native_profile;
bool mp4_native_mapped(uintptr_t p,size_t n,unsigned flags){return (flags==4||flags==5)&&mp4_actor_mapped(reinterpret_cast<void*>(p),n,false);}
#include "renderer-registration-pins.inc"
#include "renderer-registration-host.cpp.inc"
uint8_t*table=nullptr,*buckets=nullptr,*optional=nullptr,*alt=nullptr,*transform_manager=nullptr,*bits=nullptr;
uint8_t*renderers[3]{},*gos[3]{},*transforms[3]{},*components[3]{};uintptr_t selected[3]{};size_t cells[3]{};
bool fence(uint64_t e,uint64_t c){return fenced&&e==5&&c==7;}bool restoration(uint64_t e,uint64_t r){return restore_ok&&e==5&&r==11;}
bool current_source(uintptr_t p,int32_t id,uint64_t e,uint64_t c){if(!source_ok||e!=5||c!=7)return false;for(unsigned i=0;i<3;++i)if(p==selected[i]&&id==int32_t(100+i))return true;return false;}
void map_page(uintptr_t at){const auto page=at&~uintptr_t(4095);for(const auto&r:regions)if(r.first==page&&r.bytes==4096)return;void*p=mmap(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(p==reinterpret_cast<void*>(page));regions.push_back({page,4096});}
void setup(){for(const auto&pin:mp4_renderer_registration_pins.functions){const auto at=mp4_native_base+pin.rva;map_page(at);::memcpy(reinterpret_cast<void*>(at),pin.prefix,16);}
 table=allocate(0x20);buckets=allocate(128*12);optional=allocate(0x400);alt=allocate(64*0x48);transform_manager=allocate(0x80);bits=allocate(16*4);
 for(const auto& pair:{std::pair<uintptr_t,uintptr_t>{mp4_renderer_registration_pins.hash,reinterpret_cast<uintptr_t>(table)},
  {mp4_renderer_registration_pins.manager,reinterpret_cast<uintptr_t>(optional)},{mp4_renderer_registration_pins.alt,reinterpret_cast<uintptr_t>(alt)}}){const auto at=mp4_native_base+pair.first;map_page(at);write(reinterpret_cast<void*>(at),0,pair.second);}
 const auto info=mp4_native_base+mp4_renderer_registration_pins.transform;map_page(info);write(reinterpret_cast<void*>(info),0x30,uint32_t(4));write(reinterpret_cast<void*>(info),0x34,uint32_t(2));
 const auto bit=mp4_native_base+mp4_renderer_registration_pins.bit;map_page(bit);write(reinterpret_cast<void*>(bit),0,uint32_t(5));
 write(transform_manager,0x60,reinterpret_cast<uintptr_t>(bits));
 for(unsigned i=0;i<3;++i){renderers[i]=allocate(0x1c0);selected[i]=reinterpret_cast<uintptr_t>(renderers[i]);gos[i]=allocate(0x50);transforms[i]=allocate(0x50);components[i]=allocate(16);
  write(renderers[i],0,mp4_native_base+mp4_renderer_registration_pins.vtable);write(renderers[i],8,int32_t(100+i));write(renderers[i],0x30,reinterpret_cast<uintptr_t>(gos[i]));write(renderers[i],0x128,uint32_t(7));
  write(gos[i],8,int32_t(900+i));write(gos[i],0x30,reinterpret_cast<uintptr_t>(components[i]));write(gos[i],0x40,uint64_t(1));write(components[i],0,uint32_t(4));write(components[i],8,reinterpret_cast<uintptr_t>(transforms[i]));
  write(transforms[i],8,int32_t(200+i));write(transforms[i],0x30,reinterpret_cast<uintptr_t>(gos[i]));write(transforms[i],0x38,reinterpret_cast<uintptr_t>(transform_manager));write(transforms[i],0x40,uint32_t(i));}
 mp4_native_profile.native_sha256=mp4_renderer_registration_pins.sha256;
}
size_t insert(uint8_t*data,size_t slots,int32_t key,uint32_t count){const auto hash=mp4_renderer_registration_hash(static_cast<uint32_t>(key));size_t at=(hash&uint32_t((slots-1)*4))/4;
 for(size_t n=0;n<slots;++n){uint32_t marker=0;::memcpy(&marker,data+at*12,4);if(marker>=0xfffffffeu){write(data,at*12,hash&0xfffffffcu);write(data,at*12+4,key);write(data,at*12+8,count);return at;}at=(at+n+1)&(slots-1);}std::abort();}
void reset(){source=fenced=restore_ok=source_ok=true;mp4_renderer_registration_context={5,7,fence,restoration,current_source};std::memset(table,0,0x20);std::memset(buckets,0xff,128*12);write(table,0,reinterpret_cast<uintptr_t>(buckets));write(table,8,uint32_t(63*4));write(table,12,uint32_t(3));write(optional,mp4_renderer_registration_pins.manager_enabled,uint8_t(0));write(alt,7*0x48+0x10,int32_t(-1));write(transform_manager,0,uintptr_t(0));
 for(unsigned i=0;i<3;++i){cells[i]=insert(buckets,64,900+i,1+i);write(renderers[i],0x1b0,int32_t(-1));write(renderers[i],0x1b8,int32_t(-1));write(renderers[i],0x198,int32_t(0));write(renderers[i],0x19c,int32_t(0));write(renderers[i],0x1b4,uint8_t(1));write(renderers[i],0x1b5,uint8_t(1));write(bits,i*4,uint32_t(1<<5));}
}
int main(){setup();unsigned cases=0;
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3)&&s.restored(11));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));auto*promoted=allocate(128*12);::memset(promoted,0xff,128*12);for(int i=2;i>=0;--i)insert(promoted,128,900+i,1+i);write(table,0,reinterpret_cast<uintptr_t>(promoted));write(table,8,uint32_t(127*4));assert(s.restored(11));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));write(buckets,cells[2]*12+8,uint32_t(9));assert(!s.restored(11));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));insert(buckets,64,999,1);write(table,12,uint32_t(4));assert(!s.restored(11));++cases;}
 {reset();write(renderers[1],0x198,int32_t(4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(renderers[1],0x19c,int32_t(4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(optional,mp4_renderer_registration_pins.manager_enabled,uint8_t(1));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(renderers[0],0x1b0,int32_t(1));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(alt,7*0x48+0x10,int32_t(4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(bits,4,uint32_t(0));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(transform_manager,0,uintptr_t(1));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();source_ok=false;mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));fenced=false;assert(!s.restored(11));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));restore_ok=false;assert(!s.restored(11));++cases;}
 {reset();write(table,12,uint32_t(4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();write(buckets,cells[0]*12,uint32_t(4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 {reset();mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(s.capture(selected,3));write(renderers[0],0x1b8,int32_t(12));assert(!s.restored(11));++cases;}
 {reset();write(table,8,uint32_t(62*4));mp4psrreg::Scope s(mp4_renderer_registration_api(),5);assert(!s.capture(selected,3));++cases;}
 std::printf("%u concrete Renderer registration projection cases passed; native job/source/restore providers modeled\n",cases);
}
