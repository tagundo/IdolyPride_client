#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>
#include <string>
using Method=void;
namespace mp4game {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace mp4world {
struct AnimationGraph{uintptr_t handle=0;uint32_t version=0,padding=0;};
struct AnimatorBindingLayout{static constexpr size_t data=0x168,count=0x178,capacity=0x180,registration_flags=0x194,record_bytes=0x28;};
}
namespace mp4actor {struct StateLayout{size_t cached_ptr=16,native_animator_job=0x238;};}
struct Object{alignas(16)uint8_t bytes[1024]{};const char*type=nullptr;};
Object animator{},go{},native{},storage{};
bool thread_ok=true,source_ok=true,pins_ok=true,bound=false,root_motion=false,keep_state=false,write_defaults=false;
bool enabled=true,active=false,controller=false,avatar=false,graph_present=false,swap_native=false;
int mode=0,culling=0,queries=0,graph_queries=0;
uintptr_t image_base=0;
bool mp4_source_verified=true,mp4_actor_source_verified=true;
void*ref(Object&o){return o.bytes;}
template<class T>void put(Object&o,size_t at,T value){std::memcpy(o.bytes+at,&value,sizeof value);}
bool game_call(){return thread_ok;}
bool mp4_prefix(const mp4game::Binding&b){return pins_ok&&b.rva;}
bool mp4_actor_mapped(void*p,size_t n,bool){auto a=reinterpret_cast<uintptr_t>(p);for(auto*o:{&animator,&go,&native,&storage}){auto s=reinterpret_cast<uintptr_t>(ref(*o));if(a>=s&&a-s<=1024&&n<=1024-(a-s))return true;}return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto s=reinterpret_cast<uintptr_t>(p);if(s+at<s||!mp4_actor_mapped(reinterpret_cast<void*>(s+at),sizeof out,false))return false;std::memcpy(&out,reinterpret_cast<void*>(s+at),sizeof out);return true;}
bool mp4_exact_type(void*p,const char*t){Object*o=p==ref(animator)?&animator:p==ref(go)?&go:nullptr;return o&&o->type&&!std::strcmp(o->type,t);}
bool mp4_alive(void*p){uintptr_t v=0;return mp4_actor_field(p,16,v)&&v;}
void*get_go(void*,Method*){++queries;return ref(go);}
void*get_controller(void*,Method*){++queries;return controller?ref(storage):nullptr;}
void*get_avatar(void*,Method*){++queries;return avatar?ref(storage):nullptr;}
bool get_bound(void*,Method*){++queries;return bound;}
bool get_root_motion(void*,Method*){++queries;return root_motion;}
bool get_keep(void*,Method*){++queries;return keep_state;}
bool get_defaults(void*,Method*){++queries;return write_defaults;}
bool get_enabled(void*,Method*){++queries;return enabled;}
bool get_active(void*,Method*){++queries;return active;}
int get_mode(void*,Method*){++queries;return mode;}
int get_culling(void*,Method*){++queries;return culling;}
void get_graph(void*,mp4world::AnimationGraph*out,Method*){++queries;++graph_queries;*out={graph_present?19u:0u,graph_present?3u:0u,0};if(swap_native&&graph_queries==2)put(animator,16,reinterpret_cast<uintptr_t>(ref(storage)));}
bool original_graph_valid(mp4world::AnimationGraph*p,Method*){++queries;return p->handle;}
mp4game::Binding pin(void*p){return{reinterpret_cast<uintptr_t>(p),{}};}
struct{mp4game::Binding root_motion=pin(reinterpret_cast<void*>(get_root_motion)),keep_state=pin(reinterpret_cast<void*>(get_keep)),write_defaults=pin(reinterpret_cast<void*>(get_defaults));}mp4_dormant_animator_pins;
struct{mp4game::Binding animator_graph=pin(reinterpret_cast<void*>(get_graph)),animator_controller=pin(reinterpret_cast<void*>(get_controller)),animator_bound=pin(reinterpret_cast<void*>(get_bound)),animator_mode=pin(reinterpret_cast<void*>(get_mode)),graph_valid=pin(reinterpret_cast<void*>(original_graph_valid));}mp4_world_profile;
struct{mp4game::Binding animator_avatar=pin(reinterpret_cast<void*>(get_avatar)),animator_culling_get=pin(reinterpret_cast<void*>(get_culling)),animator_active=pin(reinterpret_cast<void*>(get_active));}mp4_actor_profile;
struct{mp4game::Binding component_object=pin(reinterpret_cast<void*>(get_go)),component_enabled=pin(reinterpret_cast<void*>(get_enabled));}mp4_cam_profile;
template<class F>F mp4_cam_call(const mp4game::Binding&b){return reinterpret_cast<F>(b.rva);}
bool current(void*c,void*a,void*g){return c==&source_ok&&source_ok&&a==ref(animator)&&g==ref(go);}
void setup(){animator.type="UnityEngine.Animator";go.type="UnityEngine.GameObject";put(animator,16,reinterpret_cast<uintptr_t>(ref(native)));put(go,16,uintptr_t(202));}
