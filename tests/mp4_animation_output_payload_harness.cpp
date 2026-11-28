#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <cassert>
#include <string>
struct Method{};
namespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};struct Owner{void*actor=nullptr;void*animator=nullptr;Handle graph{},output{};};}
namespace mp4world {using AnimationOutput=mp4actor::Handle;struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
struct Binding{uintptr_t rva=0;};
struct{Binding output_type;}mp4_world_profile;
struct{Binding output_target,playable_graph_get;}mp4_actor_profile;
struct{struct{uintptr_t vtable=0;}outputs[1];}mp4_director_profile;
uintptr_t image_base=0,mp4_native_base=0;bool mp4_output_calls_verified=true;uint32_t mp4_output_types[1]{1};
struct F {unsigned char actor[64]{},animator[64]{},output[0xe0]{},source[64]{};uintptr_t table[8]{};mp4actor::Handle graph{111,2,0},source_handle{},output_handle{222,2,0};void*userdata=nullptr;bool game=true,actor_type=true,animator_type=true,alive=true,mapped=true,registry=true,handle=true,type=true,target=true,source_ok=true,graph_ok=true,weak=true,table_mapped=true;int target_tag=0;};static F*f;
bool game_call(){return f->game;}bool mp4_type_is(void*,const char*){return f->actor_type;}bool mp4_exact_type(void*,const char*){return f->animator_type;}bool mp4_alive(void*){return f->alive;}
bool mp4_actor_mapped(void*p,size_t n,bool){return f->mapped&&p==f->output&&n<=sizeof(f->output);}bool mp4_native_mapped(uintptr_t p,size_t n,size_t){return f->table_mapped&&p==reinterpret_cast<uintptr_t>(f->table)&&n<=sizeof(f->table);}
template<class T>bool mp4_actor_field(void*p,size_t off,T&v){struct Region{void*p;size_t n;};const Region regions[]={{f->animator,sizeof(f->animator)},{f->output,sizeof(f->output)},{f->source,sizeof(f->source)}};for(auto&r:regions)if(r.p==p&&off+sizeof(T)<=r.n){std::memcpy(&v,static_cast<unsigned char*>(p)+off,sizeof(v));return true;}return false;}
bool mp4_director_output_handle(const mp4world::DirectorGraphIdentity&,uintptr_t n,mp4world::AnimationOutput*out){*out=f->output_handle;return f->handle&&n==reinterpret_cast<uintptr_t>(f->output);}void*weak_get(uint32_t){return f->weak?&f->target_tag:nullptr;}
bool mp4_director_output_userdata(const mp4world::DirectorGraphIdentity&,uintptr_t,void**u){*u=f->userdata;return true;}bool mp4_director_output_source(mp4world::AnimationOutput,mp4actor::Handle*s){*s=f->source_handle;return f->source_ok;}bool mp4_scene_registry_current_graph(uintptr_t,uintptr_t,uint32_t){return f->registry;}
void*type_call(mp4world::AnimationOutput*,Method*){return f->type?&f->target_tag:nullptr;}void*target_call(mp4actor::Handle*,Method*){return f->target?f->animator:nullptr;}void graph_call(mp4actor::Handle*,mp4actor::Handle*out,Method*){*out=f->graph;if(!f->graph_ok)out->version+=2;}
#include "mp4-animation-output-payload.hpp.inc"
template<class T>void put(void*p,size_t at,T v){std::memcpy(static_cast<unsigned char*>(p)+at,&v,sizeof(v));}
int main(int argc,char**argv){assert(argc==2);F fixture;f=&fixture;std::string c=argv[1];
 const uintptr_t slots[]={0x72e4a0,0x8e9150,0x8e9168,0x8e917c,0x8e39b0,0x8e3928,0x8e3a78,0x8e3984};for(size_t i=0;i<8;++i)f->table[i]=slots[i];
 mp4_world_profile.output_type.rva=reinterpret_cast<uintptr_t>(type_call);mp4_actor_profile.output_target.rva=reinterpret_cast<uintptr_t>(target_call);mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(graph_call);mp4_director_profile.outputs[0].vtable=reinterpret_cast<uintptr_t>(f->table);
 put(f->animator,16,uintptr_t(1234));put(f->output,0,reinterpret_cast<uintptr_t>(f->table));put(f->output,0x40,1.0f);put(f->output,0x44,int32_t(0));put(f->output,0xd0,uintptr_t(1234));put(f->output,0xd8,uint32_t(1));put(f->output,0xdc,uint32_t(0));put(f->source,0x28,uintptr_t(5678));f->source_handle={reinterpret_cast<uintptr_t>(f->source),2,0};
 mp4actor::Owner owner{f->actor,f->animator,f->graph,f->output_handle};mp4world::DirectorGraphIdentity identity{444,111,2};bool expected=false;
 if(c=="stable")expected=true;else if(c=="game")f->game=false;else if(c=="unverified")mp4_output_calls_verified=false;else if(c=="actor_type")f->actor_type=false;else if(c=="animator_type")f->animator_type=false;else if(c=="dead")f->alive=false;else if(c=="graph_slot")++identity.slot;else if(c=="graph_version")identity.version+=2;else if(c=="handle")f->handle=false;else if(c=="type")f->type=false;else if(c=="target")f->target=false;else if(c=="mapped")f->mapped=false;else if(c=="table")f->table[2]=0;else if(c=="userdata")f->userdata=f->actor;else if(c=="source")f->source_ok=false;else if(c=="source_graph")f->graph_ok=false;else if(c=="native_target")put(f->output,0xd0,uintptr_t(99));else if(c=="native_source")put(f->source,0x28,uintptr_t(0));else if(c=="nan")put(f->output,0x40,std::nanf(""));else if(c=="port")put(f->output,0x44,int32_t(256));else if(c=="stream")put(f->output,0xd8,uint32_t(2));else if(c=="sorting")put(f->output,0xdc,uint32_t(65536));else if(c=="registry")f->registry=false;else if(c=="table_mapping")f->table_mapped=false;else if(c=="zero_weight"){put(f->output,0x40,0.0f);expected=true;}else if(c=="port_minus_one"){put(f->output,0x44,int32_t(-1));expected=true;}else assert(false);
 idoly_mp4_animation_output::View out{};out.native_output=999;assert(mp4_actor_animation_output_payload(owner,identity,reinterpret_cast<uintptr_t>(f->output),out)==expected);if(expected){assert(out.native_target==1234&&out.native_source==5678&&out.native_output==reinterpret_cast<uintptr_t>(f->output));}else assert(out.native_output==0);
}
