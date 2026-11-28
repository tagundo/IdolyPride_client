#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstddef>
#include <map>
#include <stdexcept>
#include <string>
#include "private_volume.inc"
namespace pv=idoly_mp4_private_volume;
struct Object {void* refs[32]{};int mode=2;};
struct Curve{int key=19;int texture=71;bool dirty=true;};
struct Host {
 Object manager,camera,ambient[9],private_objects[4];Curve source_curve,private_curve;
 std::map<uint32_t,void*> roots;uint32_t next=0;uint64_t epoch=5;
 bool source=true,fenced=true,create_ok=true,clone_ok=true,created=false,disposed=false,update_throw=false,clone_throw=false;
 bool throw_set=false,throw_mode=false,source_change_in_update=false,readonly_change=false;
 uint32_t fail_retain=0;int updates=0,clones=0,disposals=0,writes=0,queries=0,source_queries=0;
 void* update_stack=nullptr;static Host* h;
 Host(){h=this;unsigned k=0;for(auto o:{16,24,32,40,48,56,64,72})manager.refs[o/8]=&ambient[k++];camera.refs[120/8]=&ambient[k];}
 pv::Api api(){pv::Api a{};a.context=this;
 a.owner_thread=[](){return true;};a.current=[](void* c,uint64_t e){auto& s=*static_cast<Host*>(c);++s.source_queries;return s.source&&s.epoch==e;};
 a.routes_verified=[](void*){return true;};a.source_inputs_current=[](void* c,void*){return static_cast<Host*>(c)->source;};
 a.retain=[](void* p)->uint32_t{auto& s=*h;const auto key=++s.next;if(key==s.fail_retain)return 0;s.roots[key]=p;return key;};
 a.target=[](uint32_t k)->void*{auto i=h->roots.find(k);return i==h->roots.end()?nullptr:i->second;};
 a.release=[](uint32_t k){assert(h->roots.erase(k)==1);};
 a.reference=[](void* o,uint32_t f,void** v){++h->queries;assert(f%8==0&&f/8<32);*v=static_cast<Object*>(o)->refs[f/8];return true;};
 a.reference_set=[](void* o,uint32_t f,void* v){++h->writes;static_cast<Object*>(o)->refs[f/8]=v;if(h->throw_set){h->throw_set=false;throw std::runtime_error("after write");}};
 a.mode=[](void* o,int32_t* v){*v=static_cast<Object*>(o)->mode;return true;};
 a.mode_set=[](void* o,int32_t v){static_cast<Object*>(o)->mode=v;if(h->throw_mode){h->throw_mode=false;throw std::runtime_error("mode after write");}};
 a.manager_type=[](void* p){return p==&h->manager;};a.camera_type=[](void* p){return p==&h->camera;};
 a.create_frame=[](void* c,void*,pv::Frame* f){auto& s=*static_cast<Host*>(c);s.created=true;s.disposed=false;
   *f={&s.private_objects[0],&s.private_objects[1],&s.private_objects[2],&s.private_objects[3]};return s.create_ok;};
 a.frame_owned=[](void* c,const pv::Frame* f){auto& s=*static_cast<Host*>(c);return s.created&&!s.disposed&&f->stack==&s.private_objects[0]
   &&f->sorted==&s.private_objects[1]&&f->sort_needed==&s.private_objects[2]&&f->colliders==&s.private_objects[3];};
 a.frame_fenced=[](void* c,const pv::Frame*){return static_cast<Host*>(c)->fenced;};
 a.dispose_frame=[](void* c,const pv::Frame*){auto& s=*static_cast<Host*>(c);assert(s.created&&!s.disposed);s.disposed=true;++s.disposals;return true;};
 a.update_original=[](void* c,void* cam){auto& s=*static_cast<Host*>(c);assert(cam==&s.camera&&s.camera.mode==0&&!s.camera.refs[15]);
   assert(s.manager.refs[2]==&s.private_objects[0]&&s.manager.refs[9]==&s.private_objects[0]);
   ++s.updates;s.update_stack=s.manager.refs[2];s.private_objects[0].refs[0]=&s.source_curve;
   if(s.source_change_in_update){s.source=false;++s.epoch;}
   if(s.readonly_change)s.manager.refs[5]=&s.private_objects[3];
   if(s.update_throw)throw std::runtime_error("update");};
 a.privatize_payloads=[](void* c,void* stack){auto& s=*static_cast<Host*>(c);assert(stack==&s.private_objects[0]);++s.clones;
   if(s.clone_throw)throw std::runtime_error("clone");
   if(!s.clone_ok)return false;
   s.private_curve=s.source_curve;s.private_curve.texture=0;s.private_curve.dirty=true;
   s.private_objects[0].refs[0]=&s.private_curve;return true;};return a;}
 bool original_refs()const {unsigned k=0;for(auto o:{16,24,32,40,48,56,64,72})if(manager.refs[o/8]!=&ambient[k++])return false;
   return camera.refs[15]==&ambient[k]&&camera.mode==2;}
};Host* Host::h=nullptr;
int main(int argc,char** argv){assert(argc==2);std::string scenario=argv[1];Host h;pv::Scope scope;
 assert(scope.configure(h.api(),5,&h.manager,&h.camera));uint64_t token=42;
 if(scenario=="create_failure")h.create_ok=false;
 if(scenario=="root_failure")h.fail_retain=h.next+2;
 if(scenario=="ref_write_throw")h.throw_set=true;
 if(scenario=="mode_write_throw")h.throw_mode=true;
 if(scenario=="update_throw")h.update_throw=true;
 if(scenario=="clone_throw")h.clone_throw=true;
 if(scenario=="clone_failure")h.clone_ok=false;
 if(scenario=="source_change_update")h.source_change_in_update=true;
 if(scenario=="readonly_change")h.readonly_change=true;
 const auto begun=scope.begin_draw(&token);
 if(scenario=="create_failure"||scenario=="root_failure"||scenario=="ref_write_throw"||scenario=="mode_write_throw"
   ||scenario=="update_throw"||scenario=="clone_throw"||scenario=="clone_failure"||scenario=="source_change_update"||scenario=="readonly_change"){
   assert(begun!=pv::Result::ok&&!token&&!scope.active());
   if(scenario!="readonly_change")assert(h.original_refs());
   else assert(h.manager.refs[5]==&h.private_objects[3]); // Real unrelated change is preserved.
   assert(scope.cleanup()==pv::Result::ok&&h.roots.empty()&&h.disposals==1);return 0;
 }
 assert(begun==pv::Result::ok&&token&&scope.active()&&scope.prepared()&&h.updates==1&&h.clones==1);
 assert(h.camera.mode==1&&h.camera.refs[15]==&h.private_objects[0]);
 // Natural cached UpdateVolumeFramework only copies the cached private ref;
 // original ReplaceData/OverrideData is not called a second time.
 h.manager.refs[2]=h.camera.refs[15];auto* curve=static_cast<Curve*>(h.private_objects[0].refs[0]);
 curve->texture=81;curve->dirty=false;assert(h.source_curve.texture==71&&h.source_curve.dirty);
 assert(!scope.end_draw(token+1)&&scope.active());
 if(scenario=="handoff_abandoned"){
   const int reads=h.queries,writes=h.writes,source_reads=h.source_queries;
   scope.abandon_globals();h.source=false;++h.epoch;
   assert(!scope.active()&&!scope.globals_withdrawn()&&!scope.end_draw(token)&&scope.cleanup()==pv::Result::waiting);
   assert(h.queries==reads&&h.writes==writes&&h.source_queries==source_reads);
   assert(h.disposals==0&&!h.roots.empty()&&h.camera.refs[15]==&h.private_objects[0]);return 0;
 }else if(scenario=="nested_unowned"){
   assert(scope.suspend(token)&&h.original_refs()&&scope.suspended());
   h.manager.refs[2]=&h.ambient[8];h.camera.refs[15]=&h.ambient[0];h.camera.mode=0;
   assert(scope.resume(token)&&scope.active()&&!scope.suspended());
   assert(h.updates==1&&h.clones==1);assert(scope.end_draw(token));
   assert(h.manager.refs[2]==&h.ambient[8]&&h.camera.refs[15]==&h.ambient[0]&&h.camera.mode==0);
 }else if(scenario=="source_handoff"){
   assert(scope.before_source_change()&&h.original_refs());h.source=false;++h.epoch;
   h.manager.refs[2]=&h.ambient[8];const int queries=h.queries;
   assert(!scope.end_draw(token)&&h.queries==queries); // Stale finally never reads/writes new scene.
   assert(h.manager.refs[2]==&h.ambient[8]);
 }else if(scenario=="reference_superseded"){
   h.manager.refs[2]=&h.ambient[8];assert(!scope.end_draw(token)&&!scope.active());
   assert(h.manager.refs[2]==&h.ambient[8]);
 }else if(scenario=="mode_superseded"){
   h.camera.mode=0;assert(!scope.end_draw(token)&&h.camera.mode==0&&!scope.active());
 }else if(scenario=="source_lost"){
   h.source=false;assert(!scope.end_draw(token)&&h.original_refs()&&!scope.active());
 }else{
   assert(scope.end_draw(token)&&scope.end_draw(token)&&scope.globals_withdrawn()&&h.original_refs());
   if(scenario=="gpu_wait"){
     h.fenced=false;uint64_t next=99;assert(scope.begin_draw(&next)==pv::Result::waiting&&!next&&h.updates==1);
     assert(scope.cleanup()==pv::Result::waiting&&!h.roots.empty()&&h.disposals==0);
     h.fenced=true;
   }else if(scenario=="next_draw"){
     uint64_t next=0;assert(scope.begin_draw(&next)==pv::Result::ok&&next!=token&&h.updates==2&&h.disposals==1);
     assert(!scope.end_draw(token)&&scope.active());assert(scope.end_draw(next));
   }
 }
 assert(scope.cleanup()==pv::Result::ok&&h.roots.empty()&&!scope.active());
 assert(h.disposals==(scenario=="next_draw"?2:1));
 if(scenario=="two_jobs"){
   ++h.epoch;assert(scope.configure(h.api(),h.epoch,&h.manager,&h.camera));uint64_t next=0;
   assert(scope.begin_draw(&next)==pv::Result::ok&&next>token&&!scope.end_draw(token));
   assert(scope.end_draw(next)&&scope.cleanup()==pv::Result::ok&&h.roots.empty()&&h.disposals==2);
 }
 return 0;
}
