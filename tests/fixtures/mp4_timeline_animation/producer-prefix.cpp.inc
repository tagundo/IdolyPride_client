#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cassert>
#include <map>
#include <vector>
#include <cmath>
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,pad=0;};}
namespace mp4world {using AnimationOutput=mp4actor::Handle;struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
namespace mp4_animation_factory {using Handle=mp4actor::Handle;struct Receipt{struct {uint64_t serial=1;}ticket;struct{uintptr_t clip=50;}input;};}
namespace mp4_animation_programme {using Handle=mp4actor::Handle;inline bool same(Handle a,Handle b){return a.handle==b.handle&&a.version==b.version;}struct Plan{Handle head{10,2,0};Handle node{20,2,0};uintptr_t track=2,asset=50;Handle playable{20,2,0},mixer{10,2,0};bool infinite=false;};inline bool contains(const Plan&p,Handle h){return same(p.node,h)||same(p.head,h);}inline bool runtime(const Plan&p,uintptr_t t,uintptr_t a,Handle h,Handle m,bool inf){return p.track==t&&p.asset==a&&same(p.playable,h)&&inf==p.infinite&&(inf||same(p.mixer,m));}}
struct Mp4TimelineContext {int phase=0;void*director=nullptr;mp4world::DirectorGraphIdentity identity{};};
enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};struct Mp4TimelineRuntime{void*element=reinterpret_cast<void*>(5),*clip=reinterpret_cast<void*>(6),*track=reinterpret_cast<void*>(2);mp4actor::Handle playable{20,2,0},mixer{10,2,0};uint8_t kind=0;};
struct Mp4AnimationProgrammeTarget{void*animator=reinterpret_cast<void*>(100);uintptr_t native=200;};struct Mp4AnimationPlanContext{const Mp4TimelineContext*timeline=nullptr;void*track=reinterpret_cast<void*>(2);Mp4AnimationProgrammeTarget target{};};struct Mp4AnimationCachedPlan{Mp4AnimationPlanContext context{};mp4_animation_programme::Plan plan{};};struct Mp4AnimationContextCache{Mp4AnimationCachedPlan plans[2]{};size_t count=1;}cache;
struct Mp4AnimationRuntimeRow{bool infinite=false;void*timeline_clip=reinterpret_cast<void*>(6);mp4actor::Handle playable{20,2,0},mixer{10,2,0};struct{uintptr_t track=2;}parent_input;};
struct Model{bool thread=true,current=true,recognized=true,cache=true,plan=true,phase=true,observation=true,output_program=true,output_handle=true,type=true,branch=true,origin=true,mapped=true;void*target=reinterpret_cast<void*>(100),*user=nullptr;uint64_t raw_user=0;uint32_t reference=77,stream=0,sorting=0;uintptr_t native_target=200,table=1000;float weight=1;int32_t port=0;Mp4AnimationRuntimeRow row{};}m;
bool game_call(){return m.thread;}bool mp4_timeline_current(const Mp4TimelineContext&){return m.current;}bool mp4_animation_native_recognized(mp4actor::Handle){return m.recognized;}Mp4AnimationContextCache*mp4_animation_context_cache(const Mp4TimelineContext&){return m.cache?&cache:nullptr;}bool mp4_animation_cached_current(Mp4AnimationCachedPlan&){return m.plan;}
struct StateRoutes{bool(*phase_closed)(const Mp4TimelineContext&,const Mp4AnimationProgrammeTarget&)=nullptr;}mp4_animation_state_routes;
bool phase(const Mp4TimelineContext&,const Mp4AnimationProgrammeTarget&){return m.phase;}
bool mp4_animation_runtime_observation(void*,mp4_animation_factory::Receipt*out,Mp4AnimationRuntimeRow*r){*out={};*r=m.row;return m.observation;}bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return mp4_animation_programme::same(a,b);}
struct Source{int track=1;}mp4_animation_factory_source;bool mp4_timeline_exact(void*p,int){return p==reinterpret_cast<void*>(2);}
bool mp4_animation_native_output_program(uintptr_t){return m.output_program;}bool mp4_director_output_handle(const mp4world::DirectorGraphIdentity&,uintptr_t,mp4world::AnimationOutput*out){*out={30,2,0};return m.output_handle;}
using Method=void;uintptr_t image_base=0,mp4_native_base=0;uint32_t mp4_output_types[3]={1,2,3};void*weak_get(uint32_t){return reinterpret_cast<void*>(1);}
void*output_type(mp4world::AnimationOutput*,Method*){return reinterpret_cast<void*>(m.type?1:2);}struct WorldProfile{struct{uintptr_t rva=0;}output_type;}mp4_world_profile;
void*output_target(mp4actor::Handle*,Method*){return m.target;}struct StateApi{void*(*output_target)(mp4actor::Handle*,Method*)=::output_target;};StateApi mp4_actor_state_api(){return {};}
bool mp4_timeline_output_branch(Mp4TimelineContext&,mp4world::AnimationOutput,mp4actor::Handle*out){*out={10,2,0};return m.branch;}
struct DirectorProfile{struct{uintptr_t vtable=1000;}outputs[1];}mp4_director_profile;
bool mp4_animation_factory_native(void*,uintptr_t*native,int32_t*id){*native=300;*id=77;return true;}bool mp4_actor_mapped(void*,size_t,bool){return m.mapped;}
template<class T>bool mp4_actor_field(void*,size_t offset,T&out){if(offset==0){uint64_t x=m.table;memcpy(&out,&x,sizeof(T));}else if(offset==0xd0){uint64_t x=m.native_target;memcpy(&out,&x,sizeof(T));}else if(offset==0x40)memcpy(&out,&m.weight,sizeof(T));else if(offset==0x44)memcpy(&out,&m.port,sizeof(T));else if(offset==0x48)memcpy(&out,&m.reference,sizeof(T));else if(offset==0xd8)memcpy(&out,&m.stream,sizeof(T));else if(offset==0xdc)memcpy(&out,&m.sorting,sizeof(T));else if(offset>=0x50&&offset<=0x60)memcpy(&out,&m.raw_user,sizeof(T));else return false;return true;}
bool mp4_director_output_userdata(const mp4world::DirectorGraphIdentity&,uintptr_t,void**out){*out=m.user;return true;}bool mp4_animation_plan_origin_current(void*){return m.origin;}
Mp4TimelineVerdict mp4_timeline_actor_node(const Mp4TimelineContext&,mp4actor::Handle,void*){return Mp4TimelineVerdict::unrecognized;}bool mp4_timeline_actor_userdata(const Mp4TimelineContext&,mp4actor::Handle,void*,void*){return false;}Mp4TimelineVerdict mp4_timeline_actor_runtime(const Mp4TimelineContext&,const Mp4TimelineRuntime&){return Mp4TimelineVerdict::unrecognized;}
