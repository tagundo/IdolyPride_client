"""Exact owned Mono scheduling and finite actor presentation restoration.

The C++ fixture exercises production code with typed fake Unity leaves. It is
not an original-engine, rendering, GPU, or encoder execution claim.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_actor_state.hpp"
#include <cassert>
#include <map>
#include <string>
#include <vector>
#include <stdexcept>
#include <memory>
using namespace idoly_mp4_actor;
struct Obj {alignas(16) uint8_t bytes[512]{};std::string type;bool live=true;std::vector<float> data;std::map<int,float> properties;std::string keywords;int queue=0;void* shader=nullptr;Bounds bounds{};Bounds skin_bounds{};bool explicit_bounds=true,offscreen=false,bounds_dirty=false;uintptr_t bounds_native=0;};
struct Fixture {
 MonoGate gate;PresentationScope scope;Obj node,array,material,renderer,mesh,other,shader,block,actor,foot,fft;
 std::vector<std::unique_ptr<Obj>> extra;std::map<int,std::map<int,float>> blocks;std::vector<uint8_t> native[5];int completed=0,destroyed=0,block_sets=0,block_gets=0,throw_block_set=0,throw_block_get=0;
 std::map<uint32_t,void*> roots;uint32_t next=1;RandomState random{{1,2,3,4}};
 PresentationInventory inventory{};bool source=true,held=true,thread=true,bad_schema=false;
 bool inventory_changed=false,drop_restore=false;int calls=0,initialized=0,writes=0,rng_gets=0,rng_sets=0;
 Vector2 offset{.2f,.3f};float highlight=.75f;std::vector<float> weights{.1f,.8f};
 void* current_mesh=nullptr;
 Fixture(){node.type="VL.VLActorFacialSystem";array.type="System.Single[]";material.type="UnityEngine.Material";
 renderer.type="UnityEngine.SkinnedMeshRenderer";mesh.type="UnityEngine.Mesh";other.type="UnityEngine.Mesh";
 shader.type="UnityEngine.Shader";block.type="UnityEngine.MaterialPropertyBlock";actor.type="VL.Core.VLActorController";foot.type="VL.VLActorFootShadow";fft.type="VL.VLActorTalkFFT";
 material.shader=shader.bytes;material.properties={{10,.5f},{20,.8f}};material.keywords="A B";material.queue=2450;renderer.bounds={{1,2,3},{4,5,6}};mesh.bounds={{7,8,9},{10,11,12}};mesh.data={1,2,3,4,5,6};
 block.properties={{30,.4f}};blocks[2]=block.properties;array.data={1,2,3};current_mesh=mesh.bytes;float v=.25f;std::memcpy(node.bytes+96,&v,4);
 void* p=array.bytes;std::memcpy(node.bytes+48,&p,8);}
 Obj* object(void* p){for(auto* o:{&node,&array,&material,&renderer,&mesh,&other,&shader,&block,&actor,&foot,&fft})if(p==o->bytes)return o;for(auto& o:extra)if(p==o->bytes)return o.get();return nullptr;}
 Obj* make(const char* type){extra.emplace_back(new Obj);extra.back()->type=type;return extra.back().get();}
};
Fixture* f=nullptr;
const ActorPresentationField fields[]={{96,4,false},{48,8,true}};
const ActorPresentationSchema schema={"VL.VLActorFacialSystem",{},fields,2};
bool current(void* p){assert(p==f);return f->source;}
bool held(void* p){assert(p==f);return f->held;}
bool thread(){return f->thread;}
void random_get(RandomState* p,Method* m){assert(!m);++f->rng_gets;*p=f->random;}
void random_set(const RandomState* p,Method* m){assert(!m);++f->rng_sets;f->random=*p;}
void callback(void*,Method*){++f->calls;f->random.words[0]+=7;}
void nested_second(void*,Method*){++f->calls;}
void derived_two(void* p,Method* m){++f->calls;f->gate.invoke(MonoPhase::actor_late,callback,p,m);f->gate.invoke(MonoPhase::actor_late,nested_second,p,m);f->gate.invoke(MonoPhase::actor_late,callback,p,m);}
void derived(void* p,Method* m){++f->calls;f->gate.invoke(MonoPhase::actor_late,callback,p,m);f->gate.invoke(MonoPhase::actor_late,callback,p,m);}
void throwing(void*,Method*){++f->calls;f->random.words[0]+=7;throw std::runtime_error("leaf");}
bool mapped(const void* p,size_t n,bool){for(auto* o:{&f->node,&f->array,&f->material,&f->renderer,&f->mesh,&f->other,&f->shader,&f->block,&f->actor,&f->foot,&f->fft}){
 uintptr_t a=reinterpret_cast<uintptr_t>(p),b=reinterpret_cast<uintptr_t>(o->bytes);if(a>=b&&a-b<=512&&n<=512-(a-b))return true;}
 for(auto& v:f->native){if(p==v.data()&&n<=v.size())return true;}
 for(auto& o:f->extra){uintptr_t a=reinterpret_cast<uintptr_t>(p),b=reinterpret_cast<uintptr_t>(o->bytes);if(a>=b&&a-b<=512&&n<=512-(a-b))return true;if(p==o->data.data()&&n<=o->data.size()*4)return true;}
 return p==f->array.data.data()&&n<=f->array.data.size()*4;}
bool is_type(void* p,const char* name){auto* o=f->object(p);return o&&(o->type==name||(std::string(name)=="UnityEngine.Renderer"&&o->type=="UnityEngine.SkinnedMeshRenderer"));}
bool alive(void* p){auto* o=f->object(p);return o&&o->live;}
void* klass(void* p){auto* o=f->object(p);return o?&o->type:nullptr;}
bool schema_matches(void* p,const ActorPresentationSchema& s){return !f->bad_schema&&is_type(p,s.type);}
uint32_t retain(void* p){if(!f->object(p))return 0;auto id=f->next++;f->roots[id]=p;return id;}
void* target(uint32_t id){auto at=f->roots.find(id);return at==f->roots.end()?nullptr:at->second;}
void release(uint32_t id){assert(f->roots.erase(id)==1);}
bool inventory(void*,PresentationInventory& i){i=f->inventory;if(f->inventory_changed)i.callback_count=0;return true;}
size_t length(void* p){auto* o=f->object(p);assert(o);return o->data.size()/(o->type=="UnityEngine.Vector3[]"?3:1);}
void* data(void* p){auto* o=f->object(p);assert(o);return o->data.data();}
void* blend_mesh(void* p,Method*){assert(p==f->renderer.bytes);return f->current_mesh;}
int32_t blend_count(void* p,Method*){assert(p==f->mesh.bytes||p==f->other.bytes);return int32_t(f->weights.size());}
float blend_get(void* p,int32_t i,Method*){assert(p==f->renderer.bytes);return f->weights.at(i);}
void blend_set(void* p,int32_t i,float v,Method*){assert(p==f->renderer.bytes);++f->writes;if(!f->drop_restore)f->weights.at(i)=v;}
float material_get(void* p){assert(p==f->material.bytes);return f->highlight;}
void material_set(void* p,float v){assert(p==f->material.bytes);++f->writes;if(!f->drop_restore)f->highlight=v;}
Vector2 offset_get(void* p,Method*){assert(p==f->material.bytes);return f->offset;}
void offset_set(void* p,Vector2 v,Method*){assert(p==f->material.bytes);++f->writes;if(!f->drop_restore)f->offset=v;}
void* shader_get(void* p,Method*){return f->object(p)->shader;}
void* material_new(void* shader){auto* o=f->make("UnityEngine.Material");o->shader=shader;return o->bytes;}
void material_copy(void* target,void* source,Method*){auto* t=f->object(target);auto* s=f->object(source);++f->writes;t->properties=s->properties;t->keywords=s->keywords;t->queue=s->queue;}
void material_destroy(void* p){f->object(p)->live=false;++f->destroyed;}
void* block_new(){return f->make("UnityEngine.MaterialPropertyBlock")->bytes;}
bool block_valid(void* p){auto* o=f->object(p);return o&&o->live;}
bool block_empty(void* p,Method*){return f->object(p)->properties.empty();}
void block_get(void* renderer,void* block,int32_t i,Method*){assert(renderer==f->renderer.bytes);if(++f->block_gets==f->throw_block_get)throw std::runtime_error("block get");f->object(block)->properties=f->blocks[i];}
void block_set(void* renderer,void* block,int32_t i,Method*){assert(renderer==f->renderer.bytes);++f->writes;if(++f->block_sets==f->throw_block_set)throw std::runtime_error("block set");f->blocks[i]=block?f->object(block)->properties:std::map<int,float>{};}
void bounds_get(void* p,Bounds* out,Method*){*out=f->object(p)->bounds;}
void bounds_set(void* p,const Bounds* v,Method*){++f->writes;auto*o=f->object(p);o->bounds=*v;o->skin_bounds=*v;o->explicit_bounds=true;o->bounds_dirty=false;}
bool bounds_capture(void*p,RendererBoundsImage*out){auto*o=f->object(p);if(!o||o->bounds_dirty)return false;
 *out={o->bounds_native?o->bounds_native:reinterpret_cast<uintptr_t>(o),1,17,o->bounds,o->skin_bounds,o->type=="UnityEngine.SkinnedMeshRenderer",o->explicit_bounds,o->offscreen};return true;}
bool bounds_current(void*p,const RendererBoundsImage*saved){auto*o=f->object(p);return o&&o->live&&saved&&(o->bounds_native?o->bounds_native:reinterpret_cast<uintptr_t>(o))==saved->native&&o->offscreen==saved->offscreen;}
bool bounds_restore(void*p,const RendererBoundsImage*saved){if(!bounds_current(p,saved))return false;auto*o=f->object(p);++f->writes;if(f->drop_restore)return true;o->bounds=saved->base;o->skin_bounds=saved->skin;o->explicit_bounds=saved->explicit_local;o->bounds_dirty=false;return true;}
bool bounds_verify(void*p,const RendererBoundsImage*saved){auto*o=f->object(p);return bounds_current(p,saved)&&o->explicit_bounds==saved->explicit_local&&!o->bounds_dirty&&!std::memcmp(&o->bounds,&saved->base,sizeof(Bounds))&&!std::memcmp(&o->skin_bounds,&saved->skin,sizeof(Bounds));}
void* vertices_get(void* p,Method*){auto* a=f->make("UnityEngine.Vector3[]");a->data=f->object(p)->data;return a->bytes;}
void vertices_set(void* p,void* v,Method*){++f->writes;f->object(p)->data=f->object(v)->data;}
void dispose_block(void* p,Method*){f->object(p)->live=false;}
void complete_aux(void* p,Method*){++f->completed;std::memset(p,0,16);}
NativeImagesApi image_api(){return {shader_get,material_new,material_copy,material_destroy,block_new,block_valid,block_empty,block_get,block_set,bounds_get,bounds_set,bounds_get,bounds_set,vertices_get,vertices_set,dispose_block,bounds_capture,bounds_current,bounds_restore,bounds_verify};}
void header(void* owner,size_t at,std::vector<uint8_t>& data,size_t size){void* p=data.data();int32_t length=1,allocator=1;assert(data.size()==size);std::memcpy(static_cast<uint8_t*>(owner)+at,&p,8);std::memcpy(static_cast<uint8_t*>(owner)+at+8,&length,4);std::memcpy(static_cast<uint8_t*>(owner)+at+12,&allocator,4);}
void build_native(){
 f->inventory.full_materials[0]=f->material.bytes;f->inventory.full_material_count=1;
 f->inventory.blocks[0]={f->renderer.bytes,f->block.bytes,2};f->inventory.block_count=1;
 f->inventory.bounds_renderers[0]=f->renderer.bytes;f->inventory.bounds_renderer_count=1;
 f->inventory.shadow_meshes[0]=f->mesh.bytes;f->inventory.shadow_mesh_count=1;
}
void init(void*,Method*){++f->initialized;}
MonoApi mono(){return {current,thread,random_get,random_set};}
PresentationApi api(){return {current,held,mapped,is_type,alive,klass,schema_matches,retain,target,release,inventory,length,data,
 blend_mesh,blend_count,blend_get,blend_set,material_get,material_set,offset_get,offset_set,init,mono()};}
void build(){auto& i=f->inventory;i.nodes[0]={f->node.bytes,&schema};i.node_count=1;
 i.arrays[0]=f->array.bytes;i.array_count=1;i.materials[0]=f->material.bytes;i.material_count=1;
 i.renderers[0]=f->renderer.bytes;i.renderer_count=1;i.callbacks[0]={f->node.bytes,MonoPhase::actor_late};i.callback_count=1;}
void configure(){build();assert(f->scope.configure(api(),&f->gate,f,11));assert(f->scope.capture()==Result::ok);}
float scalar(){float x;std::memcpy(&x,f->node.bytes+96,4);return x;}
void scalar(float x){std::memcpy(f->node.bytes+96,&x,4);}
int main(int argc,char** argv){assert(argc==2);Fixture fixture;f=&fixture;std::string c=argv[1];
 if(c.rfind("gate_",0)==0){MonoReceiver receivers[]={{f->node.bytes,MonoPhase::actor_late}};
  if(c=="gate_no_registry"){f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->calls==1);return 0;}
  assert(f->gate.publish(mono(),f,11,receivers,1));
  if(c=="gate_held"){f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(!f->calls);}
  else if(c=="gate_unowned"){f->gate.invoke(MonoPhase::actor_late,callback,f->other.bytes,nullptr);assert(f->calls==1&&f->random.words[0]==8);}
  else if(c=="gate_wrong_phase"){f->gate.invoke(MonoPhase::eye_late,callback,f->node.bytes,nullptr);assert(f->calls==1);}
  else if(c=="gate_bad_serial"){assert(!f->gate.grant(12,1));assert(!f->gate.grant(11,0));assert(f->gate.grant(11,1));assert(!f->gate.grant(11,1));}
  else if(c=="gate_preview_rng"){f->random.words[0]=100;assert(f->gate.isolate_preview([&]{assert(f->random.words[0]==1);f->random.words[0]=999;}));assert(f->random.words[0]==100);assert(f->gate.isolate([&]{assert(f->random.words[0]==1);}));}
  else if(c=="gate_render_rng"){f->random.words[0]=100;assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==1);f->random.words[0]+=10;}));assert(f->random.words[0]==100);assert(f->gate.grant(11,1));assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==1);f->random.words[0]+=10;}));assert(f->gate.revoke(11));assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==1);f->random.words[0]+=10;}));assert(f->gate.isolate([&]{assert(f->random.words[0]==11);}));assert(f->gate.grant(11,2));assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==11);f->random.words[0]+=10;}));assert(f->random.words[0]==100);}
  else if(c=="gate_render_keys"){assert(f->gate.grant(11,1));for(uintptr_t key=1;key<=2;++key)assert(f->gate.isolate_render(key,[&]{f->random.words[0]+=10;}));assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==1);f->random.words[0]+=10;}));assert(f->gate.isolate([&]{assert(f->random.words[0]==21);}));}
  else if(c=="gate_render_nested"){assert(f->gate.grant(11,1));assert(f->gate.isolate([&]{f->random.words[0]+=3;assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==4);f->random.words[0]+=10;}));assert(f->random.words[0]==14);}));assert(f->gate.isolate([&]{assert(f->random.words[0]==14);assert(f->gate.isolate_render(1,[&]{assert(f->random.words[0]==4);f->random.words[0]+=10;}));assert(f->random.words[0]==14);}));assert(f->random.words[0]==1);}
  else if(c=="gate_scene_rng_handoff"){f->random.words[0]=100;assert(!f->gate.isolate([&]{f->random.words[0]+=7;f->gate.restore_rng_before_source_change();assert(f->random.words[0]==100);f->gate.invalidate(11);f->source=false;f->random.words[0]+=5;}));assert(f->random.words[0]==105);}
  else if(c=="gate_render_scene_rng_handoff"){f->random.words[0]=100;assert(f->gate.grant(11,1));assert(!f->gate.isolate_render(1,[&]{f->random.words[0]+=7;f->gate.restore_rng_before_source_change();f->gate.invalidate(11);f->source=false;f->random.words[0]+=5;}));assert(f->random.words[0]==105);}
  else if(c=="gate_abandon_rng_handoff"){assert(!f->gate.isolate([&]{f->random.words[0]=44;const int gets=f->rng_gets,sets=f->rng_sets;f->thread=false;f->gate.abandon_rng_before_source_change();assert(f->rng_gets==gets&&f->rng_sets==sets);f->thread=true;f->random.words[0]=77;}));assert(f->random.words[0]==77&&!f->gate.grant(11,1));}
  else if(c=="gate_rng_suspend"){f->random.words[0]=100;assert(f->gate.isolate([&]{f->random.words[0]=7;RandomSuspension t;assert(f->gate.suspend_rng_for_unowned(t));assert(f->random.words[0]==100);f->random.words[0]=110;assert(f->gate.resume_rng_after_unowned(t));assert(f->random.words[0]==7);f->random.words[0]=9;}));assert(f->random.words[0]==110);assert(f->gate.isolate([&]{assert(f->random.words[0]==9);}));assert(f->random.words[0]==110);}
  else if(c=="gate_render_rng_suspend"){f->random.words[0]=100;assert(f->gate.grant(11,1));assert(f->gate.isolate_render(1,[&]{f->random.words[0]=7;RandomSuspension t,u;assert(f->gate.suspend_rng_for_unowned(t));f->random.words[0]=110;assert(f->gate.suspend_rng_for_unowned(u));f->random.words[0]=120;assert(f->gate.resume_rng_after_unowned(u));assert(f->random.words[0]==120);assert(f->gate.resume_rng_after_unowned(t));assert(f->random.words[0]==7);}));assert(f->random.words[0]==120);assert(f->gate.isolate([&]{assert(f->random.words[0]==7);}));}
  else if(c=="gate_rng_suspend_noop"){RandomSuspension t;const int gets=f->rng_gets,sets=f->rng_sets;assert(f->gate.suspend_rng_for_unowned(t)&&f->gate.resume_rng_after_unowned(t));assert(!t.active&&f->rng_gets==gets&&f->rng_sets==sets);}
  else if(c=="gate_rng_suspend_handoff"){f->random.words[0]=100;assert(!f->gate.isolate([&]{RandomSuspension t;assert(f->gate.suspend_rng_for_unowned(t));f->random.words[0]=110;const int sets=f->rng_sets;f->gate.restore_rng_before_source_change();assert(f->rng_sets==sets);f->gate.invalidate(11);f->source=false;f->random.words[0]=120;assert(!f->gate.resume_rng_after_unowned(t));}));assert(f->random.words[0]==120);}
  else if(c=="gate_rng_suspend_abandon"){f->random.words[0]=100;assert(!f->gate.isolate([&]{RandomSuspension t;assert(f->gate.suspend_rng_for_unowned(t));f->random.words[0]=110;const int gets=f->rng_gets,sets=f->rng_sets;f->gate.abandon_rng_before_source_change();assert(!f->gate.resume_rng_after_unowned(t));assert(f->rng_gets==gets&&f->rng_sets==sets);}));assert(f->random.words[0]==110);}
  else if(c=="gate_rng_suspend_order"){f->random.words[0]=100;assert(!f->gate.isolate([&]{RandomSuspension t,u;assert(f->gate.suspend_rng_for_unowned(t));assert(f->gate.suspend_rng_for_unowned(u));f->random.words[0]=120;const int sets=f->rng_sets;assert(!f->gate.resume_rng_after_unowned(t));assert(!f->gate.resume_rng_after_unowned(u));assert(f->rng_sets==sets);}));assert(f->random.words[0]==120);}
  else if(c=="gate_rng_suspend_unbalanced"){f->random.words[0]=100;assert(!f->gate.isolate([&]{RandomSuspension t;assert(f->gate.suspend_rng_for_unowned(t));f->random.words[0]=140;}));assert(f->random.words[0]==140);}
  else if(c=="gate_rng_suspend_exception"){f->random.words[0]=100;try{f->gate.isolate([&]{RandomSuspension t;assert(f->gate.suspend_rng_for_unowned(t));try{f->random.words[0]=150;throw std::runtime_error("nested");}catch(...){assert(f->gate.resume_rng_after_unowned(t));throw;}});assert(false);}catch(const std::runtime_error&){}assert(f->random.words[0]==150);}
  else if(c=="gate_derived_two"){assert(f->gate.grant(11,1));f->gate.invoke(MonoPhase::actor_late,derived_two,f->node.bytes,nullptr);assert(f->calls==3);f->gate.invoke(MonoPhase::actor_late,derived_two,f->node.bytes,nullptr);assert(f->calls==3);}
  else if(c=="gate_derived"){assert(f->gate.grant(11,1));f->gate.invoke(MonoPhase::actor_late,derived,f->node.bytes,nullptr);assert(f->calls==2);f->gate.invoke(MonoPhase::actor_late,derived,f->node.bytes,nullptr);assert(f->calls==2);}
  else if(c=="gate_once"){assert(f->gate.grant(11,1));f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->calls==1&&f->random.words[0]==1);}
  else if(c=="gate_ambient_rng"){assert(f->gate.grant(11,1));f->random.words[0]=100;f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->random.words[0]==100);assert(f->gate.grant(11,2));f->random.words[0]=300;f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->random.words[0]==300&&f->calls==2);}
  else if(c=="gate_exception_rng"){assert(f->gate.grant(11,1));f->random.words[0]=100;try{f->gate.invoke(MonoPhase::actor_late,throwing,f->node.bytes,nullptr);assert(false);}catch(const std::runtime_error&){}assert(f->random.words[0]==100&&!f->gate.current());}
  else if(c=="gate_nested_rng"){assert(f->gate.isolate([&]{f->random.words[0]=90;assert(f->gate.isolate([&]{assert(f->random.words[0]==90);f->random.words[0]=95;}));assert(f->random.words[0]==95);}));assert(f->random.words[0]==1);assert(f->gate.isolate([&]{assert(f->random.words[0]==95);}));}
  else if(c=="gate_source_loss"){assert(f->gate.grant(11,1));f->source=false;f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(!f->calls&&!f->gate.current());}
  else if(c=="gate_release_forwards"){f->gate.invalidate(11);f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->calls==1);}
  else if(c=="gate_wrong_thread"){assert(f->gate.grant(11,1));f->thread=false;f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(!f->calls);}
  else if(c=="gate_hold_revoke"){assert(f->gate.grant(11,1));assert(f->gate.hold(11));f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(!f->calls);}
  else {assert(false);}
  return 0;
 }
 if(c.rfind("native_",0)==0){build();build_native();auto a=api();a.images=image_api();a.aux_complete=complete_aux;
  if(c=="native_aux_buffers"||c=="native_aux_header_changed"){
   f->inventory.nodes[1]={f->actor.bytes,&android_presentation_schemas[0]};f->inventory.node_count=2;
   f->native[0].assign(212,0x31);f->native[1].assign(12,0x32);header(f->actor.bytes,144,f->native[0],212);header(f->actor.bytes,168,f->native[1],12);
  }
  if(c=="native_fft_source"||c=="native_fft_binds"){
   f->inventory.nodes[1]={f->fft.bytes,&android_presentation_schemas[3]};f->inventory.node_count=2;
   if(c=="native_fft_source"){void* p=f->other.bytes;std::memcpy(f->fft.bytes+80,&p,8);assert(!f->scope.configure(a,&f->gate,f,11)&&f->roots.empty());return 0;}
  }
  if(c=="native_bounds_missing_current"){a.images.renderer_bounds_current=nullptr;assert(!f->scope.configure(a,&f->gate,f,11)&&f->roots.empty());return 0;}
  if(c=="native_bounds_missing_restore"){a.images.renderer_bounds_restore=nullptr;assert(!f->scope.configure(a,&f->gate,f,11)&&f->roots.empty());return 0;}
  if(c=="native_bounds_automatic")f->renderer.explicit_bounds=false;
  if(c=="native_bounds_dirty_capture")f->renderer.bounds_dirty=true;
  if(c=="native_cpu_scratch")f->block.properties[99]=.6f;
  Obj* second_scratch=nullptr;
  if(c=="native_dual_cpu_scratch"){second_scratch=f->make("UnityEngine.MaterialPropertyBlock");second_scratch->properties={{71,.7f}};f->inventory.blocks[f->inventory.block_count++]={f->renderer.bytes,second_scratch->bytes,2};}
  assert(f->scope.configure(a,&f->gate,f,11));assert(f->scope.hold()==Result::ok);
  if(c=="native_partial_capture_failure"||c=="native_rollback_retry"){
   if(c=="native_partial_capture_failure")f->throw_block_get=2;else f->throw_block_set=2;
   try{f->scope.capture();assert(false);}catch(const std::runtime_error&){}
   f->throw_block_set=0;assert(f->scope.release(true)==Result::ok&&f->roots.empty()&&f->destroyed==1);assert(f->blocks[2][30]==.4f);return 0;
  }
  if(c=="native_bounds_dirty_capture"){assert(f->scope.capture()==Result::unsupported);assert(f->scope.release(false)==Result::ok&&f->roots.empty());return 0;}
  assert(f->scope.capture()==Result::ok);f->writes=0;
  if(c=="native_material"){f->material.properties={{10,9}};f->material.keywords="C D";f->material.queue=0;assert(f->scope.restore()==Result::ok);assert(f->material.properties[10]==.5f&&f->material.properties[20]==.8f&&f->material.keywords=="A B"&&f->material.queue==2450);}
  else if(c=="native_shader_changed"){f->material.shader=f->other.bytes;assert(f->scope.restore()==Result::stale&&!f->writes);}
  else if(c=="native_block"){f->block.properties={{50,9}};f->blocks[2]=f->block.properties;assert(f->scope.restore()==Result::ok);assert(f->blocks[2][30]==.4f&&f->block.properties[30]==.4f&&!f->block.properties.count(50));}
  else if(c=="native_fft_binds"){void* p=f->other.bytes;std::memcpy(f->fft.bytes+80,&p,8);assert(!f->scope.scalar_owner_current()&&f->scope.hold()==Result::stale&&!f->writes);}
  else if(c=="native_cpu_scratch"){f->block.properties={{88,8}};f->blocks[2]={{77,7}};assert(f->scope.restore()==Result::ok);assert(f->block.properties[99]==.6f&&!f->blocks[2].count(99)&&f->blocks[2][30]==.4f&&!f->block.properties.count(88));}
  else if(c=="native_dual_cpu_scratch"){f->block.properties={{88,8}};second_scratch->properties={{89,9}};f->blocks[2]={{77,7}};assert(f->scope.restore()==Result::ok);assert((f->block.properties==std::map<int,float>({{30,.4f}})&&second_scratch->properties==std::map<int,float>({{71,.7f}})&&f->blocks[2]==std::map<int,float>({{30,.4f}})));}
  else if(c=="native_restore_cpu_exception"){f->block.properties={{88,8}};f->blocks[2]={{77,7}};f->throw_block_get=f->block_gets+1;try{f->scope.restore();assert(false);}catch(const std::runtime_error&){}assert(f->blocks[2][30]==.4f);f->throw_block_get=0;assert(f->scope.restore()==Result::ok&&f->block.properties[30]==.4f);}
  else if(c=="native_block_destroyed"){f->block.live=false;assert(f->scope.restore()==Result::stale&&!f->writes);}
  else if(c=="native_bounds_automatic"){f->renderer.explicit_bounds=true;assert(f->scope.restore()==Result::ok&&!f->renderer.explicit_bounds);}
  else if(c=="native_bounds_replaced"){f->renderer.bounds_native=1234;assert(f->scope.restore()==Result::stale&&!f->writes);}
  else if(c=="native_bounds_offscreen_changed"){f->renderer.offscreen=true;assert(f->scope.restore()==Result::stale&&!f->writes);}
  else if(c=="native_bounds_dirty_current"){f->renderer.bounds_dirty=true;f->renderer.bounds={};assert(f->scope.restore()==Result::ok&&!f->renderer.bounds_dirty&&f->renderer.bounds.center.x==1);}
  else if(c=="native_bounds_two_caches"){f->renderer.bounds={};f->renderer.skin_bounds={{88,99,100},{1,2,3}};assert(f->scope.restore()==Result::ok&&f->renderer.bounds.center.x==1&&f->renderer.skin_bounds.center.x==0);}
  else if(c=="native_bounds_verify_failure"){f->renderer.bounds={};f->drop_restore=true;assert(f->scope.restore()==Result::failed);}
  else if(c=="native_bounds_mesh"){f->renderer.bounds={};f->mesh.bounds={};f->mesh.data={8,8,8};assert(f->scope.restore()==Result::ok);assert(f->renderer.bounds.center.x==1&&f->mesh.bounds.center.x==7&&f->mesh.data.size()==6&&f->mesh.data[0]==1);}
  else if(c=="native_aux_buffers"){f->native[0][200]=0x55;f->native[1][2]=0x56;assert(f->scope.restore()==Result::ok);assert(f->native[0][200]==0x31&&f->native[1][2]==0x32&&f->completed>=3);}
  else if(c=="native_aux_header_changed"){int32_t v=2;std::memcpy(f->actor.bytes+152,&v,4);assert(f->scope.restore()==Result::stale&&!f->writes);}
  else if(c=="native_abandon"){f->source=false;assert(f->scope.release(false)==Result::ok&&f->destroyed==1&&f->roots.empty());return 0;}
  else {assert(false);}
  assert(f->scope.release(false)==Result::ok&&f->destroyed==1&&f->roots.empty());return 0;
 }
 if(c=="face_reset"||c=="talk_reset"){
  build();const bool face=c=="face_reset";f->node.type=face?"VL.VLActorFacialSystem":"VL.VLActorTalk";
  f->inventory.nodes[0].schema=&android_presentation_schemas[face?1:2];
  if(face){float next=5,weight=.9f,scale=1;int state=2;std::memcpy(f->node.bytes+100,&next,4);std::memcpy(f->node.bytes+104,&weight,4);std::memcpy(f->node.bytes+80,&scale,4);std::memcpy(f->node.bytes+88,&state,4);f->node.bytes[92]=1;f->node.bytes[108]=1;}
  else{float time=17,weight=.8f;int index=3;std::memcpy(f->node.bytes+144,&time,4);std::memcpy(f->node.bytes+152,&time,4);std::memcpy(f->node.bytes+156,&weight,4);std::memcpy(f->node.bytes+140,&index,4);}
  assert(f->scope.configure(api(),&f->gate,f,11));assert(f->scope.capture()==Result::ok);assert(f->scope.reset_runtime_history()==Result::ok);
  if(face){float next=0,weight=1,scale=0;std::memcpy(&next,f->node.bytes+100,4);std::memcpy(&weight,f->node.bytes+104,4);std::memcpy(&scale,f->node.bytes+80,4);assert(next==-1&&weight==0&&scale==1&&!f->node.bytes[92]&&!f->node.bytes[108]);float authored=.4f;std::memcpy(f->node.bytes+104,&authored,4);assert(f->scope.reset_runtime_history()==Result::ok);std::memcpy(&weight,f->node.bytes+104,4);assert(weight==.4f);}
  else{float time=1;int index=0;std::memcpy(&time,f->node.bytes+144,4);std::memcpy(&index,f->node.bytes+140,4);assert(time==0&&index==3);}
  assert(f->scope.restore()==Result::ok);float time=0;std::memcpy(&time,f->node.bytes+(face?100:144),4);assert(time==(face?5:17));assert(f->scope.release(false)==Result::ok&&f->roots.empty());return 0;
 }
 if(c=="bad_schema"){build();f->bad_schema=true;assert(!f->scope.configure(api(),&f->gate,f,11));assert(f->roots.empty());return 0;}
 if(c=="missing_leaf"){build();auto a=api();a.blend_get=nullptr;assert(!f->scope.configure(a,&f->gate,f,11));return 0;}
 configure();
 if(c=="complete_restore"){scalar(.9f);f->array.data[0]=10;f->highlight=0;f->offset={7,8};f->weights={4,5};assert(f->scope.restore()==Result::ok);assert(scalar()==.25f&&f->array.data[0]==1&&f->highlight==.75f&&f->offset.x==.2f&&f->weights[1]==.8f);}
 else if(c=="init_once"){Owner o{};o.rig=f->node.bytes;assert(f->scope.initialize(&o,1)==Result::ok);assert(f->scope.initialize(&o,1)==Result::ok);assert(f->initialized==1);}
 else if(c=="held_callbacks"){f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(!f->calls);}
 else if(c=="grant_callbacks"){Owner o{};assert(f->scope.initialize(&o,1)==Result::ok);assert(f->scope.grant(1)==Result::ok);f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->calls==1);assert(f->scope.hold()==Result::ok);f->gate.invoke(MonoPhase::actor_late,callback,f->node.bytes,nullptr);assert(f->calls==1);}
 else if(c=="identity_changed"){void* p=f->other.bytes;std::memcpy(f->node.bytes+48,&p,8);scalar(.9f);assert(f->scope.restore()==Result::stale&&scalar()==.9f&&!f->writes);}
 else if(c=="mesh_changed"){f->current_mesh=f->other.bytes;scalar(.9f);assert(f->scope.restore()==Result::stale&&scalar()==.9f&&!f->writes);}
 else if(c=="material_destroyed"){f->material.live=false;assert(f->scope.restore()==Result::stale&&!f->writes);}
 else if(c=="inventory_changed"){f->inventory_changed=true;assert(f->scope.restore()==Result::stale&&!f->writes);}
 else if(c=="array_reallocated"){f->array.data.push_back(4);assert(f->scope.restore()==Result::stale&&!f->writes);}
 else if(c=="source_lost"){f->source=false;assert(f->scope.restore()==Result::stale&&!f->writes);}
 else if(c=="clock_unheld"){f->held=false;assert(f->scope.restore()==Result::stale&&!f->writes);}
 else if(c=="leaf_restore_rejected"){f->drop_restore=true;f->highlight=9;assert(f->scope.restore()==Result::failed);}
 else if(c=="abandon"){scalar(.9f);f->source=false;assert(f->scope.release(false)==Result::ok&&scalar()==.9f&&f->roots.empty());return 0;}
 else assert(false);
 assert(f->scope.release(false)==Result::ok&&f->roots.empty());return 0;
}
'''
CASES = ["gate_rng_suspend_unbalanced", "gate_rng_suspend_exception", "gate_rng_suspend", "gate_render_rng_suspend", "gate_rng_suspend_noop", "gate_rng_suspend_handoff", "gate_rng_suspend_abandon", "gate_rng_suspend_order", "gate_abandon_rng_handoff","gate_derived_two","gate_preview_rng", "gate_render_rng", "gate_render_keys", "gate_render_nested", "gate_scene_rng_handoff", "gate_render_scene_rng_handoff", "face_reset", "talk_reset", "native_fft_source", "native_fft_binds", "native_cpu_scratch", "native_dual_cpu_scratch", "native_partial_capture_failure", "native_rollback_retry", "native_restore_cpu_exception", "native_material", "native_shader_changed", "native_block", "native_block_destroyed", "native_bounds_mesh","native_bounds_automatic","native_bounds_missing_current","native_bounds_missing_restore","native_bounds_dirty_capture","native_bounds_replaced","native_bounds_offscreen_changed","native_bounds_dirty_current","native_bounds_two_caches","native_bounds_verify_failure", "native_aux_buffers", "native_aux_header_changed", "native_abandon", "gate_no_registry", "gate_derived", "gate_held", "gate_unowned", "gate_wrong_phase", "gate_bad_serial", "gate_once", "gate_ambient_rng", "gate_exception_rng", "gate_nested_rng", "gate_source_loss", "gate_release_forwards", "gate_wrong_thread", "gate_hold_revoke", "bad_schema", "missing_leaf", "complete_restore", "init_once", "held_callbacks", "grant_callbacks", "identity_changed", "mesh_changed", "material_destroyed", "inventory_changed", "array_reallocated", "source_lost", "clock_unheld", "leaf_restore_rejected", "abandon"]


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    directory = tmp_path_factory.mktemp("mp4-actor-presentation")
    source = directory / "presentation.cpp"
    source.write_text(SOURCE)
    output = directory / "presentation"
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("case", CASES)
def test_finite_actor_presentation_and_mono_gate(binary, case):
    result = subprocess.run([str(binary), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
