#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <vector>
#include <map>
#include <memory>
#include <sys/mman.h>
#include "renderer-scene-order.hpp.inc"
struct Region{uintptr_t first=0;size_t bytes=0;};std::vector<Region>regions;std::vector<std::unique_ptr<uint8_t[]>>storage;
bool mp4_actor_mapped(const void*p,size_t n,bool){const auto a=reinterpret_cast<uintptr_t>(p);if(!a||!n||a+n<a)return false;for(const auto&r:regions)if(a>=r.first&&a+n<=r.first+r.bytes)return true;return false;}
bool mp4_actor_refresh_maps(){return true;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof out,false))return false;::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return true;}
template<class T>void write(void*p,size_t at,T value){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof value,true));::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
uint8_t*allocate(size_t bytes){storage.emplace_back(new uint8_t[bytes]{});auto*p=storage.back().get();regions.push_back({reinterpret_cast<uintptr_t>(p),bytes});return p;}
bool source=true,fenced=true,restore_ok=true;bool game_call(){return true;}bool mp4_stage_owner(void*){return source;}bool mp4_actor_clock_held(void*){return fenced;}
uintptr_t mp4_native_base=0x20000000;struct{const char*native_sha256=nullptr;}mp4_native_profile;
bool mp4_native_mapped(uintptr_t p,size_t n,unsigned flags){return (flags==4||flags==5)&&mp4_actor_mapped(reinterpret_cast<void*>(p),n,false);}
#include "renderer-scene-order-pins.inc"
#include "renderer-scene-order-host.cpp.inc"
uint8_t*scene=nullptr,*records=nullptr,*boxes=nullptr,*visibility=nullptr,*vtable=nullptr;uint8_t*objects[5]{},*gos[5]{};uint8_t data[5][24]{},aabbs[5][24]{},status[5]{};
bool fence(uint64_t e,uint64_t c){return fenced&&e==5&&c==7;}bool restoration(uint64_t e,uint64_t r){return restore_ok&&e==5&&r==11;}
void map_page(uintptr_t at){const auto page=at&~uintptr_t(4095);for(const auto&r:regions)if(r.first==page&&r.bytes==4096)return;void*p=mmap(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(p==reinterpret_cast<void*>(page));regions.push_back({page,4096});}
void setup(){
 for(const auto*pin:{&mp4_renderer_scene_order_pins.get,&mp4_renderer_scene_order_pins.remove_record,&mp4_renderer_scene_order_pins.flush}){const auto at=mp4_native_base+pin->rva;map_page(at);::memcpy(reinterpret_cast<void*>(at),pin->prefix,16);}
 const auto global=mp4_native_base+mp4_renderer_scene_order_pins.singleton;map_page(global);scene=allocate(0x100);write(reinterpret_cast<void*>(global),0,reinterpret_cast<uintptr_t>(scene));records=allocate(64*24);boxes=allocate(64*24);visibility=allocate(64);vtable=allocate(32);
 for(unsigned i=0;i<5;++i){objects[i]=allocate(0x1d0);gos[i]=allocate(16);write(gos[i],8,int32_t(900+i));write(objects[i],0,reinterpret_cast<uintptr_t>(vtable));write(objects[i],8,int32_t(100+i));write(objects[i],0x30,reinterpret_cast<uintptr_t>(gos[i]));write(objects[i],0x38,reinterpret_cast<uintptr_t>(vtable));write(objects[i],0xfc,uint32_t(400+i));write(objects[i],0x128,uint32_t(7));write(objects[i],0x1b4,uint8_t(1));write(objects[i],0x1b5,uint8_t(1));const uintptr_t iface=reinterpret_cast<uintptr_t>(objects[i])+0x38;::memcpy(data[i],&iface,8);for(unsigned k=8;k<24;++k)data[i][k]=uint8_t(10*i+k);for(unsigned k=0;k<24;++k)aabbs[i][k]=uint8_t(20*i+k);status[i]=uint8_t(i%4);}
 mp4_native_profile.native_sha256=mp4_renderer_scene_order_pins.sha256;
}
void order(std::initializer_list<unsigned>ids){const uint64_t count=ids.size();const uintptr_t arrays[]={reinterpret_cast<uintptr_t>(records),reinterpret_cast<uintptr_t>(boxes),reinterpret_cast<uintptr_t>(visibility)};for(unsigned k=0;k<3;++k){write(scene,0x88+k*32,arrays[k]);write(scene,0x98+k*32,count);write(scene,0xa0+k*32,uint64_t(64*2));}size_t at=0;for(auto id:ids){::memcpy(records+24*at,data[id],24);::memcpy(boxes+24*at,aabbs[id],24);visibility[at]=status[id];write(objects[id],0x168,static_cast<int32_t>(at++));}}
void reset(){source=fenced=restore_ok=true;mp4_renderer_scene_order_context={5,7,fence,restoration};write(scene,0xf0,uintptr_t(0));write(scene,0xf8,uint32_t(0));write(scene,0x58,uint64_t(0));write(scene,0x78,uint64_t(0));order({0,1,2,3});}
int main(){setup();unsigned cases=0;using R=mp4ro::Result;
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok&&s.verify()==R::ok&&s.restore(11)==R::ok);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({0,2,3,1});assert(s.verify()==R::failed&&s.restore(11)==R::ok);for(unsigned i=0;i<4;++i){assert(!::memcmp(records+24*i,data[i],24)&&!::memcmp(boxes+24*i,aabbs[i],24)&&visibility[i]==status[i]);}++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({3,2,1,0});boxes[0]^=17;uint8_t changed[24]{};::memcpy(changed,boxes,24);assert(s.restore(11)==R::ok&&!::memcmp(boxes+3*24,changed,24));++cases;}
 {reset();write(scene,0xf0,uintptr_t(1));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::unsupported);++cases;}
 {reset();write(scene,0xf8,uint32_t(1));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::unsupported);++cases;}
 {reset();write(scene,0x58,uint64_t(1));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::unsupported);++cases;}
 {reset();write(scene,0x78,uint64_t(1));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::unsupported);++cases;}
 {reset();write(scene,0xb8,uint64_t(3));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::unsupported);++cases;}
 {reset();write(records,24,uintptr_t(0));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::stale);++cases;}
 {reset();write(objects[2],0x168,int32_t(3));mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::stale);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({0,1,2});assert(s.restore(11)==R::waiting);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({0,4,2,3});assert(s.restore(11)==R::waiting);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({0,2,1,3});fenced=false;assert(s.restore(11)==R::stale);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);order({0,2,1,3});restore_ok=false;assert(s.restore(11)==R::unsupported);++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);write(objects[2],0x128,uint32_t(9));assert(s.restore(11)==R::waiting);write(objects[2],0x128,uint32_t(7));++cases;}
 {reset();mp4ro::Scope s;assert(s.capture(mp4_renderer_scene_order_api(),5,7)==R::ok);auto*promoted=allocate(64*24);::memcpy(promoted,records,4*24);write(scene,0x88,reinterpret_cast<uintptr_t>(promoted));assert(s.verify()==R::ok);++cases;}
 std::printf("%u concrete RendererScene order cases passed; native jobs/restore capability providers modeled\n",cases);
}
