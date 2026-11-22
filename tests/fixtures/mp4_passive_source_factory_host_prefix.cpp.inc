#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <cassert>
#include <map>
#include <thread>
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "typed-host.hpp"
#include "passive-scope.hpp"
namespace mp4world=mp4_director_maintenance::world;
struct Method{};
namespace mp4game {struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace pin{struct Entry{uintptr_t rva=0;uint8_t bytes[16]{};};Entry font_strong,weak_get,weak_free,object_alive,object_class,class_name,class_namespace;}
uintptr_t image_base=0x1000,mp4_native_base=0x2000;std::atomic<bool>mp4_native_clock_source_ready{true};
struct{mp4game::Binding main_thread,instance_id;}mp4_shader_lineage_pins;
struct{mp4game::Binding graph_valid;}mp4_profile;
struct{mp4game::Binding playable_valid,playable_graph_get;}mp4_actor_profile;
mp4_director_birth::SourcePins mp4_child_birth_pins;
struct{unsigned depth=0;}mp4_raw_original_operation;
using Graph=mp4world::AnimationGraph;using Playable=mp4_director_birth::Playable;
using Object=mp4_source_factory::Object;
struct Class{alignas(8)uint8_t b[0x1a8]{};};
struct Obj{Class*klass=nullptr;uintptr_t monitor=0,native=0;int32_t id=0;const char*type=nullptr;};
struct Slot{uint8_t pad[32]{};uint32_t version=2,padding=0;uintptr_t native=0;};
struct Native{uint8_t pad[16]{};uintptr_t back=0;uint8_t extra[64]{};};
thread_local bool actual_thread_owner=true;
struct Model{bool main=true,established=false,gateway=true,refresh=true,alive=true,wrongGraph=false,throw_original=false,inside=false;std::atomic<unsigned>calls{0},queries{0},bindings{0},foreign_calls{0};unsigned establishes=0,maps=0,next=0;std::map<uint32_t,void*>roots;Class klass,goClass;Native assetNative,goNative,graphNative,nodeNative;Slot graph,node;Obj asset,go;uintptr_t method=0,method_storage=0;int mode=0;}model;
uint32_t strong(void*p,bool){const auto id=++model.next;model.roots[id]=p;return id;}
void*target(uint32_t id){auto it=model.roots.find(id);return it==model.roots.end()?nullptr:it->second;}
void release(uint32_t id){assert(model.roots.erase(id)==1);}
bool alive(void*p,Method*){bool rooted=false;for(auto item:model.roots)rooted|=item.second==p;assert(rooted);return p&&model.alive;}
void*klass(void*p){return ((Obj*)p)->klass;}
const char*name(void*){return "TimelineAsset";}
const char*space(void*){return "UnityEngine.Timeline";}
auto font_strong=strong;auto weak_get=target;auto weak_free=release;auto object_alive=alive;auto object_class=klass;auto class_name=name;auto class_namespace=space;
bool main_thread(Method*){++model.queries;return model.main&&actual_thread_owner;}
int32_t instance_id(void*p,Method*){bool rooted=false;for(auto item:model.roots)rooted|=item.second==p;assert(rooted);return ((Obj*)p)->id;}
bool graph_valid(Graph*g,Method*){assert(model.established);return g->handle==(uintptr_t)&model.graph&&g->version==2;}
bool playable_valid(Playable*p,Method*){assert(model.established);return p->handle==(uintptr_t)&model.node&&p->version==2;}
void playable_graph(Playable*,Graph*out,Method*){*out={(uintptr_t)&model.graph+(model.wrongGraph?1u:0u),2,0};}
bool game_call(bool establish=false){if(!actual_thread_owner)return false;if(establish){++model.establishes;model.established=true;}return model.established;}
bool mp4_mapped(uintptr_t at,size_t n,bool){return at&&n;}
bool mp4_actor_mapped(const void*p,size_t n,bool){return p&&n;}
bool mp4_actor_refresh_maps(){++model.maps;return model.refresh&&model.established;}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){if(!p)return false;std::memcpy(&out,(uint8_t*)p+offset,sizeof out);return true;}
bool mp4_exact_type(void*p,const char*t){return p&&!std::strcmp(((Obj*)p)->type,t);}
bool mp4_alive(void*p){return object_alive(p,nullptr);}
bool mp4_prefix(const mp4game::Binding&p){return p.rva&& !std::memcmp((void*)(image_base+p.rva),p.prefix,16);}
uint32_t mp4_retain(void*p){return font_strong(p,false);}
struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;uint32_t pad=0;uint64_t a=0,b=0;};
// The actual world namespace already defines its DirectorGraphIdentity.
bool mp4_child_native_owner(void*,const mp4_director_birth::SourceTuple&t){return t.director==0x777&&t.asset==(uintptr_t)&model.asset&&t.game_object==(uintptr_t)&model.go&&t.method==model.method&&t.klass==(uintptr_t)&model.klass;}
bool mp4_child_publication(const mp4_director_birth::SourceTuple&t,Graph g,mp4world::DirectorGraphIdentity*out,Playable*root){if(!mp4_child_native_owner(nullptr,t)||!graph_valid(&g,nullptr))return false;*out={(uintptr_t)&model.graphNative,g.handle,2,0,0,0};*root={(uintptr_t)&model.node,2,0};return true;}
Playable mp4_source_factory_observe(void*,Graph,void*,const void*,uintptr_t);
bool mp4_source_factory_context(Graph,mp4_source_factory::Context*);
Playable original(void*a,Graph graph,void*go,const void*method){++model.calls;assert(a==&model.asset&&go==&model.go&&method==(void*)(model.method+(model.mode==7?1u:0u)));if(!actual_thread_owner)++model.foreign_calls;mp4_source_factory::Context context{};const bool observed=mp4_source_factory_context(graph,&context);if(actual_thread_owner&&(model.mode==0||model.mode>=20))assert(observed);else assert(!observed);if(observed)assert(context.image.asset.object==(uintptr_t)a&&context.image.graph_native==(uintptr_t)&model.graphNative);if(model.throw_original)throw 42;return {(uintptr_t)&model.node,2,0};}
mp4_director_birth::FactoryFn mp4_child_factory_original=original;
void foreign_observe(){std::thread worker([]{actual_thread_owner=false;Graph graph{(uintptr_t)&model.graph,2,0};(void)mp4_source_factory_observe(&model.asset,graph,&model.go,(void*)model.method,image_base+mp4_child_birth_pins.internal_return);});worker.join();}
bool mp4_source_factory_gateway_current(mp4_director_birth::FactoryFn f){const auto count=++model.bindings;if(actual_thread_owner&&model.mode==23&&count==2)foreign_observe();return model.gateway&&f==original;}
template<class T>void bind(T f,mp4game::Binding&b){b.rva=(uintptr_t)f-image_base;std::memcpy(b.prefix,(void*)f,16);}
template<class T>void bind(T f,pin::Entry&b){b.rva=(uintptr_t)f-image_base;std::memcpy(b.bytes,(void*)f,16);}
