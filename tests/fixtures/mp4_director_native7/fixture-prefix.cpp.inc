#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cassert>
#include <cstring>
#include <atomic>
#include <vector>
#include <thread>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>
#define IDOLY_DARWIN_BRIDGE 1
namespace mp4world{struct AnimationGraph{uintptr_t handle=0;uint32_t version=0,pad=0;};struct CodeBinding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace mp4_bootstrap{enum class BootstrapRole:uint8_t{enqueue,append_a,append_b,collect,deferred_a,deferred_b,graph_create,factory};enum class BootstrapImage:uint8_t{engine,game};struct BootstrapPin{BootstrapRole role;BootstrapImage image;uintptr_t rva;uint8_t original[24];};}
namespace pin{struct Entry{const char*name;uintptr_t rva;uint8_t bytes[16];uintptr_t gateway,slot,relay_in,relay_out;};}
namespace mp4_director_maintenance{
using EnqueueFn=void(*)(void*,uint32_t,const mp4world::AnimationGraph*);using AppendFn=void(*)(void*,const mp4world::AnimationGraph*);
using CollectFn=void(*)(void*,void*);using ResetFn=void(*)(void*);using ManagerFn=void(*)(void*);
struct Originals{EnqueueFn enqueue=nullptr;AppendFn append[2]{};CollectFn collect=nullptr;ResetFn reset=nullptr;ManagerFn deferred[2]{};};
}
namespace mp4_director_birth{using CreateFn=void*(*)(void*,uintptr_t);struct Playable{uintptr_t handle;uint32_t version,pad;};using FactoryFn=Playable(*)(void*,mp4world::AnimationGraph,void*,const void*);}
thread_local bool main_thread=true;bool game_call(){return main_thread;}
uintptr_t image_base=0,mp4_native_base=0;bool mp4_source_verified=true;
std::atomic<bool>mp4_native_clock_source_ready{true},mp4_child_driving_rejected{false};
namespace idoly_mp4_runtime{enum class Stage{idle,running,retiring};struct{uint64_t generation=31;Stage stage=Stage::running;bool terminal_success=true;}job;unsigned errors=0;void stable_error(const char*){++errors;}}
unsigned captures_withdrawn=0;void mp4_root_capture_withdraw(){++captures_withdrawn;}
struct Region{uintptr_t begin;size_t bytes;};std::vector<Region>regions;
bool mp4_mapped(uintptr_t at,size_t bytes,bool){for(const auto&r:regions)if(at>=r.begin&&at+bytes>=at&&at+bytes<=r.begin+r.bytes)return true;return false;}
bool mp4_native_mapped(uintptr_t at,size_t bytes,int){return mp4_mapped(at,bytes,true);}
template<class T>T read(void*p,size_t at){T out{};std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return out;}
std::atomic<unsigned>calls[6];bool throw_original=false;uintptr_t seen_a=0,seen_b=0;uint32_t seen_op=0;
void original_enqueue(void*a,uint32_t op,const mp4world::AnimationGraph*g){++calls[0];seen_a=reinterpret_cast<uintptr_t>(a);seen_b=reinterpret_cast<uintptr_t>(g);seen_op=op;if(throw_original)throw std::runtime_error("original");}
void original_append_a(void*a,const mp4world::AnimationGraph*g){++calls[1];seen_a=reinterpret_cast<uintptr_t>(a);seen_b=reinterpret_cast<uintptr_t>(g);if(throw_original)throw std::runtime_error("original");}
void original_append_b(void*a,const mp4world::AnimationGraph*g){++calls[2];seen_a=reinterpret_cast<uintptr_t>(a);seen_b=reinterpret_cast<uintptr_t>(g);if(throw_original)throw std::runtime_error("original");}
void original_collect(void*a,void*b){++calls[3];seen_a=reinterpret_cast<uintptr_t>(a);seen_b=reinterpret_cast<uintptr_t>(b);if(throw_original)throw std::runtime_error("original");}
void original_da(void*a){++calls[4];seen_a=reinterpret_cast<uintptr_t>(a);if(throw_original)throw std::runtime_error("original");}
void original_db(void*a){++calls[5];seen_a=reinterpret_cast<uintptr_t>(a);if(throw_original)throw std::runtime_error("original");}
struct FakeHost{struct Journal{bool on=false;bool active(){return on;}}j;Journal&journal(){return j;}unsigned entered[6]{};bool routes_current(){return true;}
void enqueue(void*a,uint32_t op,const mp4world::AnimationGraph*g){++entered[0];original_enqueue(a,op,g);}
void append(unsigned i,void*a,const mp4world::AnimationGraph*g){++entered[i+1];(i?original_append_b:original_append_a)(a,g);}
void collect(void*a,void*b){++entered[3];original_collect(a,b);}
void deferred(unsigned i,void*a){++entered[i+4];(i?original_db:original_da)(a);}
}mp4_child_pending_host;
mp4_director_birth::CreateFn mp4_child_graph_create_original=nullptr;
void*mp4_child_graph_create_hook(void*,uintptr_t){return nullptr;}
bool factory_current=true;
mp4_director_birth::Playable factory(void*,mp4world::AnimationGraph,void*,const void*){return {};}
bool mp4_source_factory_gateway_current(mp4_director_birth::FactoryFn p){return p==factory&&factory_current;}
struct AudioPin{uintptr_t rva;uint8_t original[24];};const AudioPin mp4_audio_native_source_pins[]={{0x100,{1}},{0x200,{2}}};bool audio_current=true;
bool mp4_audio_native_hooks_current(){return audio_current;}
