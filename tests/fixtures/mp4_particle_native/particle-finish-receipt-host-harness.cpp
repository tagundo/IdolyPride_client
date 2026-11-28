#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <vector>
#include <memory>
#include <sys/mman.h>
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

struct Mp4ParticleStateNativePin{uintptr_t rva;uint8_t prefix[16];};
constexpr Mp4ParticleStateNativePin mp4_particle_state_android{0xe23d84,{0xfe,0xf,0x1d,0xf8,0xf6,0x57,0x1,0xa9,0xf4,0x4f,0x2,0xa9,0x9,0xb0,0x41,0x39}};
constexpr Mp4ParticleStateNativePin mp4_particle_state_ios{0x1367d48,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x1,0xa9,0xfd,0x7b,0x2,0xa9,0xfd,0x83,0x0,0x91}};
#ifdef IDOLY_DARWIN_BRIDGE
constexpr const auto&mp4_particle_state_pin=mp4_particle_state_ios;
#else
constexpr const auto&mp4_particle_state_pin=mp4_particle_state_android;
#endif
// Actual native ABI: the 352-byte public PlaybackState is returned via X8 on
// both AArch64 originals; the managed Injected wrapper copies 0x160 bytes.
struct Mp4ParticleStateNativeValue {uint8_t bytes[352];};
static_assert(sizeof(Mp4ParticleStateNativeValue)==352,"actual native PlaybackState result");

bool mp4_native_mapped(uintptr_t at,size_t n,unsigned flags){return (flags==5||flags==4)&&mp4_actor_mapped(reinterpret_cast<void*>(at),n,false);}
void map_page(uintptr_t at){const auto page=at&~uintptr_t(4095);for(const auto&r:regions)if(r.first==page&&r.bytes==4096)return;void*p=mmap(reinterpret_cast<void*>(page),4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(p==reinterpret_cast<void*>(page));regions.push_back({page,4096});}
bool exclusion_ok=true,lose_after_call=false,change_after_call=false;unsigned original_calls=0;

// Exact original GetPlaybackState completion receipt. Scheduler exclusion is a
// separate mandatory producer/phase capability supplied by the actual native
// admission barrier; neither Clock.held nor this getter receipt grants it.
struct Mp4ParticleFinishOwner{void*managed=nullptr;uintptr_t native=0,particles=0,parameters=0,state=0,modules=0;
 int32_t instance=0;uint64_t capture=0;};
bool mp4_particle_finish_same(const Mp4ParticleFinishOwner&a,const Mp4ParticleFinishOwner&b){return a.managed==b.managed&&a.native==b.native
 &&a.particles==b.particles&&a.parameters==b.parameters&&a.state==b.state&&a.modules==b.modules&&a.instance==b.instance&&a.capture==b.capture;}
struct Mp4ParticleFinishReceipt{Mp4ParticleFinishOwner owner{};uint64_t serial=0,exclusion=0;};
struct Mp4ParticleFinishContext{
 bool(*exclusion_current)(const Mp4ParticleFinishOwner&,uint64_t)=nullptr;
}mp4_particle_finish_context;
uint64_t mp4_particle_finish_serial=0;
Mp4ParticleFinishReceipt mp4_particle_finish_receipts[256]{};
size_t mp4_particle_finish_receipt_count=0;
bool mp4_particle_finish_source(void*managed,Mp4ParticleFinishOwner*out){if(!out||!game_call()||!mp4_stage_owner(nullptr)||!mp4_actor_clock_held(nullptr)
 ||!mp4_native_base||!mp4_native_profile.native_sha256||::strcmp(mp4_native_profile.native_sha256,mp4_particle_manager_pins.sha256)
 ||!mp4_type_is(managed,"UnityEngine.ParticleSystem")||!mp4_alive(managed))return false;
 *out={};
 idoly_mp4_stage::Owner public_owner{};uint64_t capture=0;bool public_restored=false;
 if(!mp4_stage_particles.snapshot_receipt(managed,&public_owner,&capture,&public_restored)||public_owner.particle!=managed||!capture)return false;
 Mp4ParticleFinishOwner o{};o.managed=managed;o.capture=capture;uintptr_t table=0;
 if(!mp4_actor_field(managed,16,o.native)||!mp4_particle_native_state_mapped(o.native,0xa8)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0,table)||table!=mp4_native_base+mp4_particle_manager_pins.vtable
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),8,o.instance)||!o.instance
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x38,o.particles)||!mp4_particle_native_state_mapped(o.particles,0x18)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x40,o.parameters)||!mp4_particle_native_state_mapped(o.parameters,0x40)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x48,o.state)||!mp4_particle_native_state_mapped(o.state,0x220)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x50,o.modules)||!mp4_particle_native_state_mapped(o.modules,0x12b0))return false;
 *out=o;return true;
}
bool mp4_particle_finish_entry_current(){const auto at=mp4_native_base+mp4_particle_state_pin.rva;
 return at&&mp4_native_mapped(at,16,5)&&!::memcmp(reinterpret_cast<void*>(at),mp4_particle_state_pin.prefix,16);}
// Kept as a concrete platform call, not a replaceable invocation/provider.
// The accepted original's actual352-byte aggregate return uses AAPCS64 X8.
// TEST-ONLY modeled native completion. The concrete production invocation
// above is separately source-pinned; this fixture does not execute ARM native.
Mp4ParticleStateNativeValue mp4_particle_finish_original(uintptr_t self){assert(self==reinterpret_cast<uintptr_t>(native));++original_calls;write(native,0x6c,uint8_t(0));if(lose_after_call)exclusion_ok=false;if(change_after_call)write(native,8,int32_t(9));return {};}

bool mp4_particle_finish_issue(void*managed,uint64_t exclusion,Mp4ParticleFinishReceipt*out){
 if(!out||!exclusion||!mp4_particle_finish_context.exclusion_current||mp4_particle_finish_serial==~uint64_t(0))return false;
 *out={};
 Mp4ParticleFinishOwner before{},after{};if(!mp4_particle_finish_source(managed,&before)||!mp4_particle_finish_entry_current()
 ||!mp4_particle_finish_context.exclusion_current(before,exclusion))return false;
 size_t slot=mp4_particle_finish_receipt_count;for(size_t i=0;i<mp4_particle_finish_receipt_count;++i)
  if(mp4_particle_finish_receipts[i].owner.managed==managed){slot=i;break;}
 if(slot>=256)return false;
 // Invalidate the previous receipt BEFORE the actual call, including all
 // failure/changed-identity paths. No stale successful call can be reused.
 mp4_particle_finish_receipts[slot]={};
 const auto value=mp4_particle_finish_original(before.native);volatile uint8_t sampled=value.bytes[0];(void)sampled;
 uint8_t pending=1;if(!mp4_particle_finish_source(managed,&after)||!mp4_particle_finish_same(before,after)
 ||!mp4_particle_finish_entry_current()||!mp4_actor_field(reinterpret_cast<void*>(before.native),0x6c,pending)||pending
 ||!mp4_particle_finish_context.exclusion_current(after,exclusion))return false;
 Mp4ParticleFinishReceipt proof{after,++mp4_particle_finish_serial,exclusion};mp4_particle_finish_receipts[slot]=proof;
 if(slot==mp4_particle_finish_receipt_count)++mp4_particle_finish_receipt_count;
 *out=proof;return true;
}
bool mp4_particle_finish_current(const Mp4ParticleFinishReceipt&receipt){if(!receipt.serial||!receipt.exclusion||!mp4_particle_finish_context.exclusion_current)return false;
 Mp4ParticleFinishOwner current{};uint8_t pending=1;
 if(!mp4_particle_finish_source(receipt.owner.managed,&current)||!mp4_particle_finish_same(current,receipt.owner)||!mp4_particle_finish_entry_current()
 ||!mp4_actor_field(reinterpret_cast<void*>(current.native),0x6c,pending)||pending
 ||!mp4_particle_finish_context.exclusion_current(current,receipt.exclusion))return false;
 for(size_t i=0;i<mp4_particle_finish_receipt_count;++i){const auto&saved=mp4_particle_finish_receipts[i];
  if(saved.serial==receipt.serial&&saved.exclusion==receipt.exclusion&&mp4_particle_finish_same(saved.owner,receipt.owner))return true;}
 return false;
}
void mp4_particle_finish_reset(){for(size_t i=0;i<mp4_particle_finish_receipt_count;++i)mp4_particle_finish_receipts[i]={};mp4_particle_finish_receipt_count=0;
 // Process-monotonic serial is deliberately NOT reset by a same-epoch retry.
}

bool exclusion(const Mp4ParticleFinishOwner&o,uint64_t lease){return exclusion_ok&&o.managed==managed&&o.capture==13&&lease==23;}
void finish_reset(){reset();mp4_particle_finish_reset();mp4_particle_finish_context={exclusion};exclusion_ok=true;lose_after_call=change_after_call=false;original_calls=0;const auto entry=mp4_native_base+mp4_particle_state_pin.rva;map_page(entry);::memcpy(reinterpret_cast<void*>(entry),mp4_particle_state_pin.prefix,16);}
int main(){setup();unsigned cases=0;
 {finish_reset();Mp4ParticleFinishReceipt r{};assert(mp4_particle_finish_issue(managed,23,&r)&&r.serial&&mp4_particle_finish_current(r)&&original_calls==1);++cases;}
 {finish_reset();write(native,0x6c,uint8_t(1));Mp4ParticleFinishReceipt r{};assert(mp4_particle_finish_issue(managed,23,&r)&&mp4_particle_finish_current(r)&&original_calls==1);++cases;}
 {finish_reset();Mp4ParticleFinishReceipt a{},b{};assert(mp4_particle_finish_issue(managed,23,&a)&&mp4_particle_finish_issue(managed,23,&b)&&b.serial>a.serial&&!mp4_particle_finish_current(a)&&mp4_particle_finish_current(b));++cases;}
 {finish_reset();exclusion_ok=false;Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!r.serial&&!original_calls);++cases;}
 {finish_reset();lose_after_call=true;Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!r.serial&&original_calls==1);++cases;}
 {finish_reset();Mp4ParticleFinishReceipt a{},b{};assert(mp4_particle_finish_issue(managed,23,&a));change_after_call=true;assert(!mp4_particle_finish_issue(managed,23,&b)&&!b.serial&&!mp4_particle_finish_current(a));++cases;}
 {finish_reset();Mp4ParticleFinishReceipt r{};assert(mp4_particle_finish_issue(managed,23,&r));public_capture=14;assert(!mp4_particle_finish_current(r));++cases;}
 {finish_reset();Mp4ParticleFinishReceipt r{};assert(mp4_particle_finish_issue(managed,23,&r));write(native,0x6c,uint8_t(1));assert(!mp4_particle_finish_current(r));++cases;}
 {finish_reset();Mp4ParticleFinishReceipt a{},b{};assert(mp4_particle_finish_issue(managed,23,&a));mp4_particle_finish_reset();assert(!mp4_particle_finish_current(a)&&mp4_particle_finish_issue(managed,23,&b)&&b.serial>a.serial);++cases;}
 {finish_reset();const auto saved=mp4_particle_finish_serial;mp4_particle_finish_serial=~uint64_t(0);Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!original_calls);mp4_particle_finish_serial=saved;++cases;}
 {finish_reset();mp4_particle_finish_receipt_count=256;Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!original_calls);mp4_particle_finish_receipt_count=0;++cases;}
 {finish_reset();const auto at=mp4_native_base+mp4_particle_state_pin.rva;write(reinterpret_cast<void*>(at),0,uint8_t(0));Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!original_calls);++cases;}
 {finish_reset();mp4_particle_finish_context.exclusion_current=nullptr;Mp4ParticleFinishReceipt r{};assert(!mp4_particle_finish_issue(managed,23,&r)&&!original_calls);++cases;}
 std::printf("%u native Finish receipt host control cases passed; ARM call and scheduling-exclusion provider modeled\n",cases);
}
