#include <cassert>
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include <initializer_list>
#include <sys/mman.h>
struct Region{uintptr_t start=0;size_t bytes=0;};std::vector<Region>regions;
const void*new_arena=nullptr;bool arena_mapped=true,refresh_ok=true;unsigned refreshes=0;
bool mp4_actor_refresh_maps(){++refreshes;if(refresh_ok)arena_mapped=true;return refresh_ok;}
bool mp4_actor_mapped(const void*p,size_t n,bool){if(p==new_arena&&!arena_mapped)return false;const auto at=reinterpret_cast<uintptr_t>(p);for(const auto&r:regions)if(n&&at>=r.start&&at+n>=at&&at+n<=r.start+r.bytes)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p||!mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof v,false))return false;::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return true;}
template<class T>void write(void*p,size_t at,T v){assert(mp4_actor_mapped(static_cast<uint8_t*>(p)+at,sizeof v,true));::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}
bool thread=true,type=true,mp4_source_verified=true,root_lost=false;uint8_t renderer[24]{},native[0x200]{},block[16]{};
uintptr_t mp4_native_base=0x20000000;std::atomic<bool>mp4_native_clock_source_ready{true};struct{const char*native_sha256=nullptr;}mp4_native_profile;
bool game_call(){return thread;}bool mp4_type_is(void*p,const char*n){return type&&p==renderer&&!::strcmp(n,"UnityEngine.Renderer");}
bool mp4_alive(void*p){uintptr_t n=0;return mp4_actor_field(p,16,n)&&n;}
std::map<uint32_t,void*>roots;uint32_t sequence=0;uint32_t mp4_retain(void*p){roots[++sequence]=p;return sequence;}
void*weak_get(uint32_t r){return root_lost?nullptr:roots[r];}void weak_free(uint32_t r){assert(roots.erase(r)==1);}
bool mp4_native_mapped(uintptr_t p,size_t n,unsigned flags){return flags==5&&mp4_actor_mapped(reinterpret_cast<void*>(p),n,false);}
#include "actor-global-mpb-presence-host.inc"
void setup(){
 std::map<uintptr_t,bool>pages;for(const auto*pin:{&mp4_global_block_native.has,&mp4_global_block_native.get,&mp4_global_block_native.set}){
  const auto at=mp4_native_base+pin->rva,page=at&~uintptr_t(4095);if(!pages[page]){void*p=mmap(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(p==reinterpret_cast<void*>(page));regions.push_back({page,4096});pages[page]=true;}
  ::memcpy(reinterpret_cast<void*>(at),pin->prefix,16);
 }
 regions.push_back({reinterpret_cast<uintptr_t>(renderer),sizeof renderer});regions.push_back({reinterpret_cast<uintptr_t>(native),sizeof native});regions.push_back({reinterpret_cast<uintptr_t>(block),sizeof block});
 mp4_native_profile.native_sha256=mp4_global_block_native.sha256;
}
void reset(){assert(roots.empty());thread=type=mp4_source_verified=true;root_lost=false;new_arena=nullptr;arena_mapped=refresh_ok=true;refreshes=0;mp4_native_clock_source_ready=true;write(renderer,16,reinterpret_cast<uintptr_t>(native));write(native,8,int32_t(41));write(native,0x138,uintptr_t(0));mp4_native_profile.native_sha256=mp4_global_block_native.sha256;}
int main(){setup();unsigned cases=0;bool present=true;
 {reset();assert(mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());++cases;}
 {reset();write(native,0x138,reinterpret_cast<uintptr_t>(block));assert(mp4_actor_global_block_presence(renderer,-1,&present)&&present&&roots.empty());++cases;}
 {reset();assert(!mp4_actor_global_block_presence(renderer,0,&present)&&!present&&roots.empty());++cases;}
 {reset();type=false;assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());++cases;}
 {reset();mp4_native_clock_source_ready=false;assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present);++cases;}
 {reset();mp4_native_profile.native_sha256="wrong";assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present);++cases;}
 {reset();write(native,8,int32_t(0));assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());++cases;}
 {reset();write(renderer,16,uintptr_t(0));assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());++cases;}
 {reset();root_lost=true;assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());++cases;}
 {reset();const auto at=mp4_native_base+mp4_global_block_native.has.rva;const uint8_t saved=*reinterpret_cast<uint8_t*>(at);*reinterpret_cast<uint8_t*>(at)^=1;assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&roots.empty());*reinterpret_cast<uint8_t*>(at)=saved;++cases;}
 {reset();write(native,0x138,reinterpret_cast<uintptr_t>(block));new_arena=block;arena_mapped=false;assert(mp4_actor_global_block_presence(renderer,-1,&present)&&present&&refreshes==1);++cases;}
 {reset();new_arena=native;arena_mapped=false;assert(mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&refreshes==1);++cases;}
 {reset();write(native,0x138,reinterpret_cast<uintptr_t>(block));new_arena=block;arena_mapped=refresh_ok=false;assert(!mp4_actor_global_block_presence(renderer,-1,&present)&&!present&&refreshes==1&&roots.empty());++cases;}
 std::printf("%u concrete global MPB presence cases passed; native memory/code provider modeled\n",cases);
}
