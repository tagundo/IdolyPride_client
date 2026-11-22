#include "mp4_actor_state.hpp"
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <array>
#include <vector>
#include <string>
#include <map>
#include <memory>
#include <initializer_list>
struct Class;
struct Blob {std::array<unsigned char,1024> memory{};Class*klass=nullptr;bool alive=true;std::vector<void*>items;};
struct Field {size_t offset=0;uint32_t flags=0;Class*declared=nullptr;void*value=nullptr;};
struct Class:Blob {std::string name;Class*parent=nullptr;std::map<std::string,Field>fields;};
std::vector<std::unique_ptr<Blob>> objects;
std::vector<std::unique_ptr<Class>> classes;
std::map<void*,Blob*> memory;
Class*cls(const char*n,Class*parent=nullptr){auto p=std::make_unique<Class>();p->name=n;p->parent=parent;auto*r=p.get();memory[r]=r;classes.push_back(std::move(p));return r;}
Blob*obj(Class*c){auto p=std::make_unique<Blob>();p->klass=c;auto*r=p.get();memory[r]=r;objects.push_back(std::move(p));return r;}
template<class T>void put(void*p,size_t at,T value){assert(memory.count(p)&&at+sizeof(T)<=1024);std::memcpy(memory[p]->memory.data()+at,&value,sizeof(T));}
bool live=true,thread=true,prefix=true,mutate_queue=false,mutate_static=false;
void*queue_for_mutation=nullptr,*method_for_mutation=nullptr;Field*static_for_mutation=nullptr;
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto i=memory.find(p);if(i==memory.end()||at+sizeof(T)>1024)return false;
 std::memcpy(&out,i->second->memory.data()+at,sizeof(T));
 if(mutate_queue&&p==method_for_mutation&&at==32){uint32_t v=0;std::memcpy(&v,memory[queue_for_mutation]->memory.data()+28,4);put(queue_for_mutation,28,v+1);mutate_queue=false;}
 return true;}
void*object_class(void*p){auto i=memory.find(p);return i==memory.end()?nullptr:i->second->klass;}
bool mp4_type_is(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));for(;c;c=c->parent)if(c->name==n)return true;return false;}
bool mp4_exact_type(void*p,const char*n){auto*c=static_cast<Class*>(object_class(p));return c&&c->name==n;}
bool mp4_alive(void*p){return memory.count(p)&&memory[p]->alive;}
bool mp4_actor_mapped(const void*p,size_t,bool){return p!=nullptr;}
size_t mp4_array_length(void*p){assert(memory.count(p));return memory[p]->items.size();}
void*mp4_array_data(void*p){assert(memory.count(p));return memory[p]->items.data();}
bool mp4_actor_list(void*p,void***out,size_t*n,size_t maximum){void*a=nullptr;int32_t count=0;if(!mp4_actor_field(p,16,a)||!a||!mp4_actor_field(p,24,count)||count<0||size_t(count)>maximum||!mp4_type_is(a,"System.Array")||size_t(count)>mp4_array_length(a))return false;*out=static_cast<void**>(mp4_array_data(a));*n=size_t(count);return true;}
uint32_t next_root=0;std::map<uint32_t,void*>roots;
uint32_t mp4_retain(void*p){roots[++next_root]=p;return next_root;}
void*weak_get(uint32_t t){auto i=roots.find(t);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t t){assert(roots.erase(t)==1);}
struct Mp4ActorTempRoot {uint32_t h=0;explicit Mp4ActorTempRoot(void*p):h(p?mp4_retain(p):0){}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return h?weak_get(h):nullptr;}};
Field*find_field(Class*c,const char*n){for(;c;c=c->parent){auto i=c->fields.find(n);if(i!=c->fields.end())return &i->second;}return nullptr;}
void*field(void*k,const char*n){return find_field(static_cast<Class*>(k),n);}
void*field_type(void*p){return static_cast<Field*>(p)->declared;}void*class_type(void*p){return p;}
void*(*font_field)(void*,const char*)=field;void*(*font_field_type)(void*)=field_type;void*(*font_class_type)(void*)=class_type;
uint32_t field_flags(void*p){return static_cast<Field*>(p)->flags;}size_t field_offset(void*p){return static_cast<Field*>(p)->offset;}
void field_get(void*p,void*out){std::memcpy(out,&static_cast<Field*>(p)->value,sizeof(void*));}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};struct Layout{uint32_t player_binder=88,binder_actors=64;};}
struct Mp4SrpPins{mp4game::Binding manager,pipeline,controller,outline,actor,foot,frame,outline_begin,outline_update,aabb,foot_apply,add,invoke,camera_type,active_enabled,object_equal;}mp4_srp_pins;
struct{mp4game::Binding field_flags,field_offset,field_static_get,write_barrier;}mp4_cam_profile;
struct{struct{uint32_t actor_extensions=64;}fields;}mp4_actor_profile;
uintptr_t image_base=0;
bool mp4_source_verified=true,mp4_actor_source_verified=true;
bool game_call(){return thread;}bool mp4_prefix(const mp4game::Binding&){return prefix;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
std::map<uintptr_t,Class*> resolved;
void*mp4_resolved_type_class(const mp4game::Binding&p,const char*,const char*){if(mutate_static&&p.rva==mp4_srp_pins.outline.rva){static_for_mutation->value=nullptr;mutate_static=false;}auto i=resolved.find(p.rva);return i==resolved.end()?nullptr:i->second;}
struct Mp4SceneWitness{void*player=nullptr,*controller=nullptr,*camera=nullptr;uint64_t generation=7;};
struct Mp4OriginalRendererSource{Mp4SceneWitness scene{};void*asset=nullptr;};
Mp4SceneWitness current_scene{};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.controller==b.controller&&a.camera==b.camera&&a.generation==b.generation;}
namespace idoly_mp4_runtime{struct Game{bool selected_scene_witness(Mp4SceneWitness&w){w=current_scene;return live;}}game;}

struct Method{};
Mp4OriginalRendererSource source_for_host{};
bool mp4_original_renderer_source_detail(Mp4OriginalRendererSource& out){out=source_for_host;return live;}
bool held_now=true,entered_now=true;int writes=0;
bool host_held(void*){return held_now;}
bool host_entered(void*,idoly_mp4_srp::Operation,void*,void*){return entered_now;}
int32_t camera_type(void*,Method*){return 1;}
bool camera_active(void*,Method*){return true;}
bool object_equal(void*a,void*b,Method*){return a==b;}
void barrier(void*,void**target,void*value){++writes;*target=value;}

#include <atomic>
#include <stdexcept>
Class *delegate_class,*array_class,*delegate_array,*action_class,*event_class,*queue_class,*actor_class,*foot_class,*outline_class,*controller_class,*manager_class,*pipeline_class;
Blob *controller,*player,*camera,*actor,*foot,*outline,*queue,*actor_list,*actor_array,*foot_list,*foot_array,*frame_delegate,*outline_delegate,*method_frame,*method_aabb,*method_foot;
Blob*method(uintptr_t entry,Class*owner,uint8_t argc){auto*m=obj(nullptr);put(m,0,entry);put(m,8,entry);put(m,32,static_cast<void*>(owner));put(m,82,argc);return m;}
Blob*callback(Class*type,void*target,uintptr_t entry,Blob*m){auto*d=obj(type);put(d,16,entry);put(d,24,entry);put(d,32,target);put(d,40,static_cast<void*>(m));put(d,64,target);return d;}
Blob*array(Class*c,std::initializer_list<void*>items){auto*a=obj(c);a->items=items;return a;}
Blob*list(Class*c,Blob*a,int count=-1){auto*l=obj(c);put(l,16,static_cast<void*>(a));put(l,24,int32_t(count<0?a->items.size():count));put(l,28,uint32_t(1));return l;}

void initialize_source(){
 delegate_class=cls("System.Delegate");delegate_class->fields["delegates"]={120,0,nullptr,nullptr};array_class=cls("System.Array");delegate_array=cls("System.Delegate[]",array_class);delegate_class->fields["delegates"].declared=delegate_array;
 action_class=cls("UnityEngine.Events.UnityAction",delegate_class);event_class=cls("System.Action2",delegate_class);
 queue_class=cls("System.Collections.Generic.List`1");queue_class->fields["_version"]={28,0,nullptr,nullptr};
 actor_class=cls("VL.Core.VLActorController");foot_class=cls("VL.VLActorFootShadow");outline_class=cls("VL.VLOutline");controller_class=cls("VL.Rendering.VLSRPCameraController");manager_class=cls("UnityEngine.Rendering.RenderPipelineManager");pipeline_class=cls("UnityEngine.Rendering.Universal.UniversalRenderPipeline");
 Class*types[]={manager_class,pipeline_class,controller_class,outline_class,actor_class,foot_class};mp4game::Binding*bindings[]={&mp4_srp_pins.manager,&mp4_srp_pins.pipeline,&mp4_srp_pins.controller,&mp4_srp_pins.outline,&mp4_srp_pins.actor,&mp4_srp_pins.foot};for(size_t i=0;i<6;++i){bindings[i]->rva=i+1;resolved[i+1]=types[i];}
 mp4_srp_pins.frame.rva=101;mp4_srp_pins.outline_begin.rva=102;mp4_srp_pins.outline_update.rva=103;mp4_srp_pins.aabb.rva=104;mp4_srp_pins.foot_apply.rva=105;
 mp4_cam_profile.field_flags.rva=reinterpret_cast<uintptr_t>(field_flags);mp4_cam_profile.field_offset.rva=reinterpret_cast<uintptr_t>(field_offset);mp4_cam_profile.field_static_get.rva=reinterpret_cast<uintptr_t>(field_get);
 controller=obj(controller_class);player=obj(cls("Player"));camera=obj(cls("UnityEngine.Camera"));actor=obj(actor_class);foot=obj(foot_class);outline=obj(outline_class);
 put(controller,80,static_cast<void*>(camera));put(controller,148,uint8_t(1));controller_class->fields["_preCullFrameEvents"]={128,0,queue_class,nullptr};
 actor_array=array(cls("Actor[]",array_class),{actor});actor_list=list(queue_class,actor_array);auto*binder=obj(cls("Solis.Common.Live.SolisLiveBinder"));put(player,88,static_cast<void*>(binder));put(binder,64,static_cast<void*>(actor_list));
 foot_array=array(cls("Extension[]",array_class),{foot});foot_list=list(queue_class,foot_array);put(actor,64,static_cast<void*>(foot_list));
 method_frame=method(101,controller_class,2);method_aabb=method(104,actor_class,0);method_foot=method(105,foot_class,0);
 frame_delegate=callback(event_class,controller,101,method_frame);outline_delegate=callback(event_class,outline,102,method(102,outline_class,2));
 put(outline,32,1.f);put(outline,36,2.f);put(outline,40,3.f);
 auto*aabb=callback(action_class,actor,104,method_aabb);auto*shadow=callback(action_class,foot,105,method_foot);
 queue=list(queue_class,array(cls("UnityAction[]",array_class),{aabb,shadow}));put(controller,128,static_cast<void*>(queue));
 auto*asset=obj(cls("PipelineAsset"));auto*pipeline=obj(pipeline_class);put(manager_class,224,uint32_t(1));manager_class->fields["s_CurrentPipelineAsset"]={0,16,nullptr,asset};manager_class->fields["s_CurrentPipeline"]={24,16,nullptr,pipeline};
 const char*events[]={"beginFrameRendering","endFrameRendering","beginContextRendering","endContextRendering","beginCameraRendering","endCameraRendering"};for(size_t i=0;i<6;++i)manager_class->fields[events[i]]={32+i*8,16,event_class,nullptr};manager_class->fields[events[0]].value=frame_delegate;manager_class->fields[events[4]].value=outline_delegate;
 Mp4OriginalRendererSource source{};source.scene={player,controller,camera,7};source.asset=asset;current_scene=source.scene;

 source_for_host=source;
 queue_class->fields["_items"]={16,0,nullptr,nullptr};queue_class->fields["_size"]={24,0,nullptr,nullptr};
 void*backing=nullptr;assert(mp4_actor_field(queue,16,backing));memory[backing]->klass=cls("UnityEngine.Events.UnityAction[]",array_class);
 memory[backing]->items.resize(4);put(queue,24,int32_t(2));
 mp4_srp_pins.add.rva=106;mp4_srp_pins.invoke.rva=107;
 mp4_srp_pins.camera_type.rva=reinterpret_cast<uintptr_t>(camera_type);
 mp4_srp_pins.active_enabled.rva=reinterpret_cast<uintptr_t>(camera_active);
 mp4_srp_pins.object_equal.rva=reinterpret_cast<uintptr_t>(object_equal);
 mp4_cam_profile.write_barrier.rva=reinterpret_cast<uintptr_t>(barrier);
}

namespace mp4actor=idoly_mp4_actor;
mp4actor::MonoGate mp4_actor_mono_gate;
mp4actor::MonoCallback mp4_actor_late_original=nullptr,mp4_actor_derived_late_ref_original=nullptr,mp4_actor_derived_late_shared_original=nullptr;
struct Mp4RenderContext{void*pointer;};
using VoidMethod=void(*)(void*,Method*);using Mp4SrpAdd=void(*)(void*,void*,Method*);using Mp4SrpFrame=void(*)(void*,Mp4RenderContext,void*,Method*);
namespace idoly_mp4_runtime {
enum class Stage{render_setup,frame_request,retiring};
struct{uint64_t generation=9;bool auto_started=true,prewarm_requested=false,prewarm_inflight=false;Stage stage=Stage::frame_request;}job;
struct Clock{bool holding=true,have=true;uint64_t value=0;bool held()const{return holding;}bool have_tick()const{return have;}uint64_t tick()const{return value;}}native_engine_clock;
bool render_current=true,render_allowed=true;
bool native_render_job_current(){return render_current;}
uint64_t native_simulation_render_generation(uint64_t tick){return render_current&&render_allowed&&job.auto_started&&native_engine_clock.have_tick()&&tick==native_engine_clock.tick()?job.generation:0;}
}
