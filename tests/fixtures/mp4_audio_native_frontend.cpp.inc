#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cassert>
#include <cstring>
#include <atomic>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>
#define IDOLY_DARWIN_BRIDGE 1
namespace pin{struct Entry{const char*name;uintptr_t rva;uint8_t bytes[16];uintptr_t gateway,slot,relay_in,relay_out;};}
struct Region{uintptr_t begin;size_t bytes;};std::vector<Region>regions;
uintptr_t image_base=0,mp4_native_base=0;bool thread=true,mp4_source_verified=true;
std::atomic<bool>mp4_native_clock_source_ready{true},mp4_audio_published{false};
bool game_call(){return thread;}
bool mp4_mapped(uintptr_t at,size_t bytes,bool){for(const auto&r:regions)if(at>=r.begin&&at+bytes>=at&&at+bytes<=r.begin+r.bytes)return true;return false;}
template<class T>T read(void*p,size_t at){T out{};std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return out;}
unsigned abandoned=0,canonical=0,processed=0;void*seen=nullptr;
void mp4_audio_abandon_globals(){++abandoned;mp4_audio_published=false;}
void mp4_audio_outer_invoke(void(*original)(void*),void*p){++canonical;seen=p;if(original)original(p);}
void mp4_audio_outer_process(void(*original)(void*),void*p){++processed;seen=p;if(original)original(p);}
// SOURCE_PINS
// NATIVE_FRONTENDS
void original(void*p){seen=p;}
constexpr size_t bytes=0xac00000;uint8_t*area=nullptr;pin::Entry entries[2]{};
void page(uintptr_t rva){const auto p=(image_base+rva)&~uintptr_t(4095);for(const auto&r:regions)if(r.begin==p)return;assert(!mprotect(reinterpret_cast<void*>(p),4096,PROT_READ|PROT_WRITE));regions.push_back({p,4096});}
void put(uintptr_t rva,const void*data,size_t count){page(rva);assert(mp4_mapped(image_base+rva,count,false));std::memcpy(reinterpret_cast<void*>(image_base+rva),data,count);}
template<class T>void put(uintptr_t rva,T data){put(rva,&data,sizeof data);}
uint32_t branch(uintptr_t from,uintptr_t to){const auto d=static_cast<intptr_t>(to)-static_cast<intptr_t>(from);assert(!(d&3)&&d>=-(1ll<<27)&&d<(1ll<<27));return 0x14000000u|(static_cast<uint32_t>(d/4)&0x3ffffffu);}
void setup(){if(!area){auto*p=mmap(nullptr,bytes,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_NORESERVE,-1,0);assert(p!=MAP_FAILED);area=static_cast<uint8_t*>(p);image_base=mp4_native_base=reinterpret_cast<uintptr_t>(p);}
 thread=mp4_source_verified=true;mp4_native_clock_source_ready=true;mp4_audio_published=false;mp4_audio_frontends_published=false;abandoned=canonical=processed=0;seen=nullptr;
 for(size_t i=0;i<2;++i){const auto&p=mp4_audio_native_ios_pins[i];auto&e=entries[i];e={i?"source":"canonical",p.rva,{},0x9788500+i*32,0xab8de00+i*8,p.relay,p.relay+4};std::memcpy(e.bytes,p.original,16);mp4_audio_native_entries[i]=nullptr;
  put(e.rva,p.original,24);put(e.rva,branch(e.rva,e.relay_in));put(e.relay_in,branch(e.relay_in,e.gateway));put(e.relay_out,branch(e.relay_out,e.rva+4));
  const auto pages=static_cast<intptr_t>(e.slot>>12)-static_cast<intptr_t>(e.gateway>>12);uint32_t displaced=0;std::memcpy(&displaced,e.bytes,4);
  const uint32_t code[]={0x90000010u|((static_cast<uint32_t>(pages)&3)<<29)|(((static_cast<uint32_t>(pages)>>2)&0x7ffff)<<5),0x91000210u|static_cast<uint32_t>((e.slot&0xfff)<<10),0xc8dffe10u,0xb4000050u,0xd61f0200u,displaced,branch(e.gateway+24,e.relay_out)};
  put(e.gateway,code,sizeof code);put(e.slot,reinterpret_cast<uintptr_t>(i?mp4_audio_source_process_hook:mp4_audio_canonical_hook));
 }
 mp4_audio_canonical_original=reinterpret_cast<Mp4AudioNativeOriginal>(image_base+entries[0].gateway+20);
 mp4_audio_source_process_original=reinterpret_cast<Mp4AudioNativeOriginal>(image_base+entries[1].gateway+20);
}
bool bind(){return mp4_audio_native_install_static(entries[0],entries[1]);}
int main(){unsigned cases=0;
 {setup();assert(bind()&&mp4_audio_native_hooks_current());++cases;}
 for(unsigned index=0;index<2;++index)for(unsigned at=0;at<8;++at){setup();assert(bind());const auto&e=entries[index];const uintptr_t locations[]={e.rva,e.rva+20,e.gateway,e.gateway+20,e.gateway+24,e.slot,e.relay_in,e.relay_out};put(locations[at],uint32_t(0));assert(!mp4_audio_native_hooks_current());++cases;}
 {setup();entries[0].bytes[9]^=1;assert(!bind()&&!mp4_audio_frontends_published);++cases;}
 {setup();entries[1].relay_in+=8;assert(!bind());++cases;}
 {setup();assert(bind()&&!mp4_audio_native_install_static(entries[0],entries[1]));++cases;}
 {setup();assert(bind());mp4_source_verified=false;assert(!mp4_audio_native_hooks_current());++cases;}
 {setup();assert(bind());mp4_native_clock_source_ready=false;assert(!mp4_audio_native_hooks_current());++cases;}
 {setup();assert(bind());thread=false;assert(!mp4_audio_native_hooks_current());++cases;}
 {setup();assert(bind());mp4_native_base+=8;assert(!mp4_audio_native_hooks_current());mp4_native_base=image_base;++cases;}
 {setup();mp4_audio_canonical_original=original;mp4_audio_canonical_hook(reinterpret_cast<void*>(0x111));assert(canonical==1&&!processed&&!abandoned&&seen==reinterpret_cast<void*>(0x111));++cases;}
 {setup();mp4_audio_source_process_original=original;mp4_audio_source_process_hook(reinterpret_cast<void*>(0x222));assert(processed==1&&!canonical&&!abandoned&&seen==reinterpret_cast<void*>(0x222));++cases;}
 {setup();mp4_audio_canonical_original=original;mp4_audio_published=true;mp4_audio_canonical_hook(nullptr);assert(canonical==1&&abandoned==1&&!mp4_audio_published);++cases;}
 {setup();mp4_audio_source_process_original=original;mp4_audio_published=true;mp4_audio_source_process_hook(nullptr);assert(processed==1&&abandoned==1&&!mp4_audio_published);++cases;}
 {setup();thread=false;mp4_audio_published=true;mp4_audio_canonical_original=original;mp4_audio_canonical_hook(nullptr);assert(canonical==1&&!abandoned&&mp4_audio_published);++cases;}
 printf("%u actual Audio frontend cases; ARM gateways/Outer leaf calls modeled\n",cases);assert(!munmap(area,bytes));
}
