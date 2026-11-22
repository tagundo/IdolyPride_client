#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cassert>
#include <atomic>
#include <thread>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>
#define IDOLY_DARWIN_BRIDGE 1
using Method=void;
struct Region{uintptr_t start;size_t bytes;};std::vector<Region>regions;
uintptr_t image_base=0,mp4_native_base=0;bool mp4_source_verified=true;
std::atomic<bool>mp4_native_clock_source_ready{true};thread_local bool on_thread=true;
bool game_call(){return on_thread;}
bool mp4_mapped(uintptr_t at,size_t n,bool){for(const auto&r:regions)if(at>=r.start&&at+n>=at&&at+n<=r.start+r.bytes)return true;return false;}
template<class T>T read(void*p,size_t at){T result{};std::memcpy(&result,static_cast<uint8_t*>(p)+at,sizeof result);return result;}
namespace pin{struct Entry{const char*name;uintptr_t rva;uint8_t bytes[16];uintptr_t gateway,slot,relay_in,relay_out;};}
namespace mp4game{struct Binding{uintptr_t rva;uint8_t prefix[16];};}
std::atomic<unsigned>ordinary_calls{0},withdrawals{0},suppress_calls{0};int32_t original_property=0;void*original_texture=nullptr;uintptr_t observed_lr=0;bool suppress_result=false,inside_current=false;
bool mp4_capture_native_frontend_current();
namespace idoly_mp4_capture_publication{struct Request{static bool suppress(int32_t,void*,uintptr_t lr){++suppress_calls;observed_lr=lr;inside_current=mp4_capture_native_frontend_current();return suppress_result;}};}
void mp4_capture_production_foreign()noexcept{++withdrawals;}
void original(int32_t p,void*t){original_property=p;original_texture=t;++ordinary_calls;}
bool mp4_gpu_host_read(void*,uintptr_t p,void*out,size_t n){if(!game_call()||!mp4_mapped(p,n,false))return false;std::memcpy(out,reinterpret_cast<void*>(p),n);return true;}
struct{uintptr_t icall_slot=0xa91b680;}mp4_capture_production_profile;
struct{mp4game::Binding shader_property_id{};}mp4_stage_profile;
void*mp4_string_new(const char*s){assert(!std::strcmp(s,"_VLCapturedTexture"));return reinterpret_cast<void*>(0x99);}
struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*x):p(x){}void*get()const{return p;}};
bool property_pin=true;bool mp4_prefix(const mp4game::Binding&){return property_pin;}
int32_t property(void*p,Method*){assert(p==reinterpret_cast<void*>(0x99));return 57;}
// NATIVE_PINS
// NATIVE_HOST
uint8_t*area=nullptr;constexpr size_t area_bytes=0xac00000;
uint32_t branch(uintptr_t from,uintptr_t to){const auto delta=static_cast<intptr_t>(to)-static_cast<intptr_t>(from);assert(!(delta&3)&&delta>=-(1ll<<27)&&delta<(1ll<<27));return 0x14000000u|(static_cast<uint32_t>(delta/4)&0x3ffffffu);}
void page(uintptr_t rva){const auto at=(image_base+rva)&~uintptr_t(4095);for(const auto&r:regions)if(r.start==at)return;assert(!mprotect(reinterpret_cast<void*>(at),4096,PROT_READ|PROT_WRITE));regions.push_back({at,4096});}
void put(uintptr_t rva,const void*p,size_t n){page(rva);assert(mp4_mapped(image_base+rva,n,false));std::memcpy(reinterpret_cast<void*>(image_base+rva),p,n);}
template<class T>void put(uintptr_t rva,T x){put(rva,&x,sizeof x);}
pin::Entry entry{};
void setup(){if(!area){void*p=mmap(nullptr,area_bytes,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE,-1,0);assert(p!=MAP_FAILED);area=static_cast<uint8_t*>(p);image_base=reinterpret_cast<uintptr_t>(area);mp4_native_base=image_base;}
 on_thread=mp4_source_verified=property_pin=true;mp4_native_clock_source_ready=true;ordinary_calls=withdrawals=suppress_calls=0;suppress_result=inside_current=false;observed_lr=0;
 mp4_capture_native_original=original;mp4_capture_native_published=false;mp4_capture_native_watch_ready=false;mp4_capture_native_watch_property.store(0);
 mp4_capture_native_static_entry=nullptr;mp4_capture_native_readers=mp4_capture_native_write_serial=0;mp4_capture_native_untracked=0;mp4_capture_native_depth=0;
 entry={"Shader::SetGlobalTextureImpl",mp4_capture_native_ios_pin.rva,{},0x9788500,0xab8de00,140577364,140577368};std::memcpy(entry.bytes,mp4_capture_native_ios_pin.original,16);
 put(entry.rva,mp4_capture_native_ios_pin.original,24);put(entry.rva,branch(entry.rva,entry.relay_in));put(entry.relay_in,branch(entry.relay_in,entry.gateway));put(entry.relay_out,branch(entry.relay_out,entry.rva+4));
 const intptr_t pages=static_cast<intptr_t>(entry.slot>>12)-static_cast<intptr_t>(entry.gateway>>12);uint32_t displaced=0;std::memcpy(&displaced,entry.bytes,4);
 uint32_t code[]={0x90000010u|((static_cast<uint32_t>(pages)&3)<<29)|(((static_cast<uint32_t>(pages)>>2)&0x7ffff)<<5),0x91000210u|static_cast<uint32_t>((entry.slot&0xfff)<<10),0xc8dffe10u,0xb4000050u,0xd61f0200u,displaced,branch(entry.gateway+24,entry.relay_out)};
 put(entry.gateway,code,sizeof code);put(entry.slot,reinterpret_cast<uintptr_t>(mp4_capture_native_hook));put(mp4_capture_production_profile.icall_slot,uintptr_t(0));
 // The source-current host checks the actual owned original gateway address;
 // CPU invocation tests then use original() directly without calling ARM bytes.
 mp4_capture_native_original=reinterpret_cast<Mp4CaptureNativeOriginal>(image_base+entry.gateway+20);
 mp4_stage_profile.shader_property_id.rva=reinterpret_cast<uintptr_t>(property)-image_base;
}
bool bind(){return mp4_capture_native_install_static(entry);}
void forward_mode(){mp4_capture_native_original=original;}
int main(){unsigned cases=0;
 {setup();assert(bind()&&mp4_capture_native_frontend_current());++cases;}
 {setup();assert(bind());put(mp4_capture_production_profile.icall_slot,image_base+entry.rva);assert(mp4_capture_native_frontend_current());++cases;}
 {setup();assert(bind());put(mp4_capture_production_profile.icall_slot,uintptr_t(0x1234));assert(!mp4_capture_native_frontend_current());++cases;}
 for(unsigned i=0;i<8;++i){setup();assert(bind());const uintptr_t locations[]={entry.rva,entry.rva+20,entry.gateway,entry.gateway+20,entry.gateway+24,entry.slot,entry.relay_in,entry.relay_out};put(locations[i],uint32_t(0));assert(!mp4_capture_native_frontend_current());++cases;}
 {setup();++entry.relay_in;assert(!bind()&&!mp4_capture_native_published.load());++cases;}
 {setup();entry.bytes[8]^=1;assert(!bind());++cases;}
 {setup();assert(bind());mp4_source_verified=false;assert(!mp4_capture_native_frontend_current());++cases;}
 {setup();assert(bind());mp4_native_clock_source_ready=false;assert(!mp4_capture_native_frontend_current());++cases;}
 {setup();assert(bind());mp4_capture_native_readers=1;assert(!mp4_capture_native_quiescent()&&!mp4_capture_native_frontend_current());mp4_capture_native_readers=0;++cases;}
 {setup();assert(bind());{Mp4CaptureNativeReader r;assert(!mp4_capture_native_quiescent()&&mp4_capture_native_frontend_current());{Mp4CaptureNativeReader nested;assert(!mp4_capture_native_frontend_current());}assert(mp4_capture_native_frontend_current());}assert(mp4_capture_native_quiescent());++cases;}
 {setup();assert(bind());mp4_capture_native_untracked=1;assert(!mp4_capture_native_quiescent()&&!mp4_capture_native_frontend_current());++cases;}
 {setup();assert(bind());int32_t id=0;assert(mp4_capture_native_property(&id)&&id==57&&mp4_capture_native_watch_ready.load());++cases;}
 {setup();assert(bind());property_pin=false;int32_t id=0;assert(!mp4_capture_native_property(&id)&&!mp4_capture_native_watch_ready.load());++cases;}
 {setup();assert(bind());mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(58);int32_t id=0;assert(!mp4_capture_native_property(&id));++cases;}
 {setup();forward_mode();mp4_capture_native_hook(-71,reinterpret_cast<void*>(0x123456));assert(ordinary_calls==1&&suppress_calls==1&&original_property==-71&&original_texture==reinterpret_cast<void*>(0x123456)&&observed_lr&&!withdrawals&&!mp4_capture_native_write_serial&&mp4_capture_native_quiescent());++cases;}
 {setup();forward_mode();mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(57);mp4_capture_native_hook(57,reinterpret_cast<void*>(0x123456));assert(ordinary_calls==1&&withdrawals==1&&mp4_capture_native_write_serial==1);++cases;}
 {setup();forward_mode();mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(57);mp4_capture_native_hook(58,nullptr);assert(ordinary_calls==1&&!withdrawals&&!mp4_capture_native_write_serial);++cases;}
 {setup();forward_mode();mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(57);suppress_result=true;mp4_capture_native_hook(57,nullptr);assert(!ordinary_calls&&!withdrawals&&!mp4_capture_native_write_serial&&suppress_calls==1&&mp4_capture_native_quiescent());++cases;}
 {setup();forward_mode();mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(57);mp4_capture_native_write_serial=~uint64_t(0);mp4_capture_native_hook(57,nullptr);assert(ordinary_calls==1&&mp4_capture_native_untracked&&mp4_capture_native_write_serial==~uint64_t(0));++cases;}
 {setup();forward_mode();mp4_capture_native_readers=~uint64_t(0);mp4_capture_native_hook(58,nullptr);assert(ordinary_calls==1&&mp4_capture_native_untracked&&mp4_capture_native_readers==~uint64_t(0));mp4_capture_native_readers=0;++cases;}
 {setup();forward_mode();mp4_capture_native_depth=~uint32_t(0);mp4_capture_native_hook(58,nullptr);assert(ordinary_calls==1&&mp4_capture_native_untracked&&!mp4_capture_native_readers&&mp4_capture_native_depth==~uint32_t(0));mp4_capture_native_depth=0;++cases;}
 {setup();forward_mode();mp4_capture_native_watch_ready=true;mp4_capture_native_watch_property.store(57);std::thread worker([]{on_thread=false;mp4_capture_native_hook(57,reinterpret_cast<void*>(0x111));});worker.join();assert(ordinary_calls==1&&withdrawals==1&&mp4_capture_native_write_serial==1&&mp4_capture_native_quiescent());++cases;}
 std::printf("%u native publication host cases; ARM gateway execution and Request suppression decision modeled\n",cases);assert(!munmap(area,area_bytes));
}
