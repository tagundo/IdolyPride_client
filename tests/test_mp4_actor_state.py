"""Behavioral C++ tests for the production selected-actor deep-state scope.

The fixture models typed original APIs, managed roots and mapped native buffers.
It does not execute the original Unity engine or claim device validation.
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
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_actor;
struct Object {
    alignas(16) unsigned char bytes[2048]{};
    std::string type;
    bool live=true;
    Object* parent=nullptr;
    LocalPose pose{};
    std::vector<void*> elements;
    explicit Object(const char* name):type(name){}
    void* p(){return bytes;}
};
struct Region {void* pointer;size_t bytes;bool writable=true;};
struct Node {Handle handle{};double time=11.2;std::vector<Handle> inputs;bool valid=true;};
struct NativeList {uintptr_t data=0;int32_t length=1,capacity=2;};
struct Fixture {
    WorkerGate gate;
    std::vector<std::unique_ptr<Object>> heap;
    std::map<void*,Object*> objects;
    std::vector<Region> regions;
    std::map<uint32_t,void*> roots;
    uint32_t next_root=1;int new_roots=0,fail_root=0,completions=0,resets=0,body_calls=0,evals=0;
    Object *actor,*extension,*rig,*builder,*animator,*boxed,*array,*root,*bone,*outside;
    alignas(16) unsigned char job[actor_job_bytes]{};
    alignas(16) unsigned char native_animator[0x300]{};
    NativeList lists[4]{};
    std::vector<uint8_t> buffers[4];
    Node nodes[2];
    Owner owner{};
    int graph_mode=2,animator_mode=0,culling=0;
    double root_clock=11.2;
    bool held=true,routes=true,source=true,job_type=true,fence_pending=false;
    bool clip_advance=false,job_clock_advance=false,root_advance=false,replace_job=false;
    bool fail_zero=false,nonzero_pose=false,original_throw=false;
    Object* make(const char* type){
        heap.emplace_back(new Object(type));auto* o=heap.back().get();objects[o->p()]=o;
        regions.push_back({o->p(),sizeof(o->bytes),true});return o;
    }
    template<class T>void put(void* p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
    template<class T>T get(void* p,size_t at){T value{};std::memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof value);return value;}
    Fixture(){
        actor=make("VL.Core.VLActorController");extension=make("VL.VLActorActorSwing");
        rig=make("ActorSwing.ActorSwingRig");builder=make("ActorSwing.ActorSwingBuilder");
        animator=make("UnityEngine.Animator");boxed=make("ActorSwing.ActorSwingJob");
        array=make("UnityEngine.Transform[]");root=make("UnityEngine.Transform");
        bone=make("UnityEngine.Transform");outside=make("UnityEngine.Transform");
        bone->parent=root;root->pose={{1,2,3},{0,0,0,1},{1,1,1}};
        bone->pose={{4,5,6},{0,0,1,0},{2,2,2}};
        array->elements={root->p(),bone->p()};
        std::memset(job,0x19,sizeof(job));
        for(size_t i=0;i<4;++i){
            buffers[i].resize(row_strides[i]*2,static_cast<uint8_t>(0x30+i));
            lists[i].data=reinterpret_cast<uintptr_t>(buffers[i].data());
            regions.push_back({&lists[i],sizeof lists[i],true});
            regions.push_back({buffers[i].data(),buffers[i].size(),true});
            put(job,list_header_offsets[i],reinterpret_cast<uintptr_t>(&lists[i]));
        }
        const float time=7.25;put(job,actor_job_time,time);
        std::memcpy(boxed->bytes+16,job,actor_job_bytes);
        put(rig->p(),0x50,boxed->p());put(rig->p(),0x58,uint8_t{1});
        put(animator->p(),0x10,reinterpret_cast<uintptr_t>(native_animator));
        put(native_animator,0x238,uint64_t{91});put(native_animator,0x240,int32_t{4});
        regions.push_back({job,sizeof job,true});regions.push_back({native_animator,sizeof native_animator,true});
        nodes[0].handle={0x1000,3,0};nodes[1].handle={0x2000,4,0};nodes[0].inputs={nodes[1].handle};
        owner={actor->p(),extension->p(),rig->p(),builder->p(),animator->p(),{0x3000,7,0},{0x4000,9,0},{0x5000,11,0}};
    }
    Object* object(void* p){auto i=objects.find(p);return i==objects.end()?nullptr:i->second;}
    bool same(Handle a,Handle b){return a.handle==b.handle&&a.version==b.version;}
    Node* node(Handle h){for(auto& n:nodes)if(same(h,n.handle))return &n;return nullptr;}
    bool mapped(const void* p,size_t size,bool writable){
        const auto a=reinterpret_cast<uintptr_t>(p);
        if(!p||size>max_snapshot_bytes)return false;
        for(const auto& r:regions){const auto b=reinterpret_cast<uintptr_t>(r.pointer);
            if(a>=b&&a-b<=r.bytes&&size<=r.bytes-(a-b)&&(!writable||r.writable))return true;}
        if(p==array->elements.data()&&size<=array->elements.size()*sizeof(void*)&&!writable)return true;
        return false;
    }
};
Fixture* f=nullptr;
bool current(void* ctx,const Owner& o){
    assert(ctx==f);return f->source&&o.actor==f->owner.actor&&o.extension==f->owner.extension
        &&o.rig==f->owner.rig&&o.builder==f->owner.builder&&o.animator==f->owner.animator
        &&f->same(o.graph,f->owner.graph)&&f->same(o.playable,f->owner.playable)&&f->same(o.output,f->owner.output);
}
bool held(void* ctx){assert(ctx==f);return f->held;}
bool routes(void* ctx){assert(ctx==f);return f->routes;}
Result zero_pose(void* ctx){
    assert(ctx==f);f->root_clock=0;for(auto& n:f->nodes)n.time=0;
    f->bone->pose.position={90,91,92};
    if(f->nonzero_pose)f->root_clock=1;
    return f->fail_zero?Result::failed:Result::ok;
}
double root_time(void* ctx){assert(ctx==f);return f->root_clock;}
bool mapped(const void* p,size_t n,bool write){return f->mapped(p,n,write);}
bool type(void* p,const char* name){auto* o=f->object(p);return o&&o->type==name;}
bool alive(void* p){auto* o=f->object(p);assert(o);return o->live;}
uint32_t retain(void* p,bool pinned){assert(!pinned&&f->object(p));if(++f->new_roots==f->fail_root)return 0;const auto id=f->next_root++;f->roots[id]=p;return id;}
void* target(uint32_t id){auto i=f->roots.find(id);return i==f->roots.end()?nullptr:i->second;}
void release(uint32_t id){assert(f->roots.erase(id)==1);}
void* output(Handle* h,Method* m){assert(!m);return f->same(*h,f->owner.output)?f->animator->p():nullptr;}
void* job_type(Handle* h,Method* m){assert(!m&&f->same(*h,f->owner.playable));return f->job_type?f->boxed->p():nullptr;}
bool is_job(void* p){return p==f->boxed->p();}
void* job_data(Handle* h,Method* m){assert(!m&&f->same(*h,f->owner.playable));return f->replace_job?f->boxed->bytes+16:f->job;}
int32_t mode(void* p,Method* m){assert(!m&&p==f->animator->p());return f->animator_mode;}
int32_t culling(void* p,Method* m){assert(!m&&p==f->animator->p());return f->culling;}
void complete(void* p,Method* m){
    assert(!m&&p==f->native_animator+0x238);++f->completions;
    if(!f->fence_pending){f->put(p,0,uint64_t{0});f->put(p,8,int32_t{0});}
}
void reset_dynamic(void* p,Method* m){
    assert(!m&&p==f->rig->p());++f->resets;
    f->buffers[0][0xbc]=0x71;
    if(f->original_throw)throw std::runtime_error("original reset");
}
void reset_breast(void* p,Method* m){assert(!m&&p==f->rig->p());++f->resets;f->buffers[2][0x2c]=0x72;}
bool graph_valid(Handle* h,Method* m){assert(!m);return f->same(*h,f->owner.graph);}
bool graph_mode(Handle* h,int32_t* value){assert(f->same(*h,f->owner.graph));*value=f->graph_mode;return true;}
void graph_mode_set(Handle* h,int32_t v,Method* m){assert(!m&&f->same(*h,f->owner.graph));f->graph_mode=v;}
void solver(void* job,const void*,const void*){
    assert(job==f->job);++f->body_calls;f->buffers[0][0xbc]=static_cast<uint8_t>(f->body_calls);
    f->buffers[2][0x2c]=static_cast<uint8_t>(f->body_calls+1);f->bone->pose.position.x=float(f->body_calls);
    if(f->job_clock_advance){const float t=f->get<float>(job,actor_job_time)+.1f;f->put(job,actor_job_time,t);}
}
void burst_solver(void* job,const void* stream,intptr_t tag,void* ranges,int32_t index){
    assert(tag==1&&ranges==nullptr&&index==0);solver(job,stream,nullptr);
}
void evaluate(Handle* h,float delta,Method* m){
    assert(!m&&f->same(*h,f->owner.graph)&&delta==0&&f->graph_mode==3);++f->evals;
    // Both original typed routes share one grant, including a copied receiver.
    f->gate.invoke_managed(solver,f->job,nullptr,nullptr);
    f->gate.invoke_burst(burst_solver,f->job,nullptr,1,nullptr,0);
    if(f->clip_advance)f->nodes[1].time+=.01;
    if(f->root_advance)f->root_clock+=.01;
}
int32_t root_count(Handle* h,Method* m){assert(!m&&f->same(*h,f->owner.graph));return 1;}
void get_root(Handle* h,int32_t index,Handle* out,Method* m){assert(!m&&index==0&&f->same(*h,f->owner.graph));*out=f->nodes[0].handle;}
bool playable_valid(Handle* h,Method* m){assert(!m);return f->same(*h,f->owner.playable)||(f->node(*h)&&f->node(*h)->valid);}
int32_t input_count(Handle* h,Method* m){assert(!m&&f->node(*h));return int32_t(f->node(*h)->inputs.size());}
void input(Handle* h,int32_t index,Handle* out,Method* m){assert(!m&&f->node(*h));*out=f->node(*h)->inputs.at(size_t(index));}
double time(Handle* h,Method* m){assert(!m&&f->node(*h));return f->node(*h)->time;}
void* root_transform(void* p,Method* m){assert(!m&&p==f->actor->p());return f->root->p();}
void* transforms(void* p){assert(p==f->actor->p());return f->array->p();}
size_t length(void* p){assert(p==f->array->p());return f->array->elements.size();}
void* data(void* p){assert(p==f->array->p());return f->array->elements.data();}
void* parent(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));return f->object(p)->parent?f->object(p)->parent->p():nullptr;}
void position(void* p,Vector3* out,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));*out=f->object(p)->pose.position;}
void rotation(void* p,Quaternion* out,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));*out=f->object(p)->pose.rotation;}
void scale(void* p,Vector3* out,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));*out=f->object(p)->pose.scale;}
void set_position_rotation(void* p,const Vector3* pos,const Quaternion* rot,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));f->object(p)->pose.position=*pos;f->object(p)->pose.rotation=*rot;}
void set_scale(void* p,const Vector3* value,Method* m){assert(!m&&type(p,"UnityEngine.Transform"));f->object(p)->pose.scale=*value;}
StateApi api(){return {current,held,routes,zero_pose,root_time,mapped,type,alive,retain,target,release,
    output,job_type,is_job,job_data,mode,culling,complete,reset_dynamic,reset_breast,
    graph_valid,graph_mode,graph_mode_set,evaluate,root_count,get_root,playable_valid,
    input_count,input,time,root_transform,transforms,length,data,parent,position,rotation,scale,
    set_position_rotation,set_scale};}
Result warm(Scope& scope){
    Result result=Result::waiting;for(int i=0;i<40&&result==Result::waiting;++i)result=scope.reset();return result;
}
int main(int argc,char** argv){
    assert(argc==2);const std::string s=argv[1];Fixture fixture;f=&fixture;Scope scope;StateApi a=api();
    if(s=="missing_api"){a.job_complete=nullptr;assert(!scope.configure(a,&f->gate,&f->owner,1,f,17));return 0;}
    if(s=="invalid_configure"){
        assert(!scope.configure(a,nullptr,&f->owner,1,f,17));assert(!scope.configure(a,&f->gate,nullptr,1,f,17));
        assert(!scope.configure(a,&f->gate,&f->owner,0,f,17));assert(!scope.configure(a,&f->gate,&f->owner,1,nullptr,17));
        assert(!scope.configure(a,&f->gate,&f->owner,1,f,0));return 0;
    }
    assert(scope.configure(a,&f->gate,&f->owner,1,f,17));
    if(s=="clock_not_held"){f->held=false;assert(scope.quiesce()==Result::waiting);assert(f->roots.empty()&&f->graph_mode==2);assert(scope.release(false)==Result::ok);return 0;}
    if(s=="routes_not_ready"){f->routes=false;assert(scope.quiesce()==Result::waiting);assert(f->roots.empty());assert(scope.release(false)==Result::ok);return 0;}
    if(s=="wrong_actor_type")f->actor->type="System.Object";
    if(s=="wrong_rig_job_type")f->boxed->type="System.Object";
    if(s=="wrong_native_job_type")f->job_type=false;
    if(s=="uninitialized")f->put(f->rig->p(),0x58,uint8_t{0});
    if(s=="animator_unscaled")f->animator_mode=2;
    if(s=="animator_culled")f->culling=1;
    if(s=="dead_rig")f->rig->live=false;
    if(s=="root_allocation_failure")f->fail_root=3;
    if(s=="native_list_negative")f->lists[0].length=-1;
    if(s=="native_list_capacity")f->lists[0].capacity=0;
    if(s=="native_list_huge")f->lists[0].capacity=int32_t(max_rows+1);
    if(s=="native_list_unmapped")f->lists[0].data=0x12345;
    if(s=="boxed_buffer_mismatch")f->put(f->boxed->bytes+16,0x28,uintptr_t{0x12345});
    const bool before_fail=s=="wrong_actor_type"||s=="wrong_rig_job_type"||s=="wrong_native_job_type"
        ||s=="uninitialized"||s=="animator_unscaled"||s=="animator_culled"||s=="dead_rig"
        ||s=="root_allocation_failure"||s=="native_list_negative"||s=="native_list_capacity"
        ||s=="native_list_huge"||s=="native_list_unmapped"||s=="boxed_buffer_mismatch";
    if(before_fail){assert(scope.quiesce()!=Result::ok);assert(scope.release(false)==Result::ok);assert(f->roots.empty());return 0;}
    if(s=="fence_pending"){
        f->fence_pending=true;assert(scope.quiesce()==Result::waiting);assert(f->graph_mode==2);
        f->fence_pending=false;assert(scope.quiesce()==Result::ok);
    }else assert(scope.quiesce()==Result::ok);
    assert(f->graph_mode==2&&f->completions>=1&&f->roots.size()==5);
    if(s=="pose_outside")f->bone->parent=f->outside;
    if(s=="pose_duplicate")f->array->elements[1]=f->root->p();
    if(s=="pose_wrong_array")f->array->type="UnityEngine.Component[]";
    if(s=="pose_nan")f->bone->pose.position.x=__builtin_nanf("");
    if(s=="pose_root_oom")f->fail_root=f->new_roots+1;
    const bool pose_fail=s=="pose_outside"||s=="pose_duplicate"||s=="pose_wrong_array"||s=="pose_nan"||s=="pose_root_oom";
    if(pose_fail){assert(scope.capture()!=Result::ok);assert(scope.release(true)==Result::ok);assert(f->roots.empty()&&f->graph_mode==2);return 0;}
    assert(scope.capture()==Result::ok&&f->roots.size()==6);assert(scope.prepare()==Result::ok);
    unsigned char old_job[actor_job_bytes];std::memcpy(old_job,f->job,sizeof old_job);
    const auto old_buffers=std::vector<std::vector<uint8_t>>{f->buffers[0],f->buffers[1],f->buffers[2],f->buffers[3]};
    const auto old_pose=f->bone->pose;
    if(s=="captured_release"){assert(scope.release(true)==Result::ok);assert(f->graph_mode==2&&f->roots.empty());return 0;}
    if(s=="clip_advances")f->clip_advance=true;
    if(s=="job_clock_advances")f->job_clock_advance=true;
    if(s=="root_advances")f->root_advance=true;
    if(s=="zero_pose_nonzero")f->nonzero_pose=true;
    if(s=="zero_pose_failure")f->fail_zero=true;
    const bool reset_fail=s=="clip_advances"||s=="job_clock_advances"||s=="root_advances"
        ||s=="zero_pose_nonzero"||s=="zero_pose_failure";
    const Result result=warm(scope);
    if(reset_fail)assert(result!=Result::ok);
    else {assert(result==Result::ok&&scope.warmed_steps()==180&&f->evals==180&&f->body_calls==180);
        assert(f->graph_mode==1&&f->gate.stats().duplicate_calls==180);}
    if(s=="grant"){
        assert(scope.grant(1)==Result::ok);f->gate.invoke_managed(solver,f->job,nullptr,nullptr);
        f->gate.invoke_burst(burst_solver,f->job,nullptr,1,nullptr,0);assert(f->body_calls==181);
        assert(scope.grant(1)==Result::invalid);assert(scope.grant(0)==Result::invalid);
        assert(scope.grant(2)==Result::ok);f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==182);
    }
    if(s=="hold_regrant_keeps_game_time"){
        assert(scope.quiesce()==Result::ok&&f->graph_mode==1);
        assert(scope.hold_frame()==Result::ok&&f->graph_mode==1);
        assert(scope.grant(1)==Result::ok&&f->graph_mode==1);
        f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==181);
        assert(scope.quiesce()==Result::ok&&f->graph_mode==1);
        assert(scope.grant(2)==Result::ok&&f->graph_mode==1);
        f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==182);
    }
    if(s=="external_mode_change"){
        f->graph_mode=3;
        assert(scope.quiesce()==Result::stale&&f->graph_mode==3);
        assert(scope.hold_frame()==Result::stale&&f->graph_mode==3);
        assert(scope.grant(1)==Result::stale&&f->graph_mode==3);
        assert(scope.release(false)==Result::ok&&f->graph_mode==3&&f->roots.empty());return 0;
    }
    if(s=="curve_pointer_changed")f->put(f->job,0x78,uintptr_t{0x123456});
    if(s=="map_pointer_changed")f->put(f->job,0xa8,uintptr_t{0x123456});
    if(s=="job_binding_changed")f->put(f->job,0x10,uint32_t{0x123456});
    if(s=="row_transform_binding_changed")f->put(f->buffers[0].data(),0x104,int32_t{13});
    if(s=="row_property_binding_changed")f->put(f->buffers[0].data(),0x138,int32_t{13});
    if(s=="row_scene_binding_changed")f->put(f->buffers[1].data(),0x64,int32_t{13});
    if(s=="row_readonly_choice_changed")f->put(f->buffers[2].data(),0x74,uint8_t{1});
    if(s=="row_chain_topology_changed")f->put(f->buffers[3].data(),0x70,int32_t{13});
    const bool binding_stale=s=="curve_pointer_changed"||s=="map_pointer_changed"||s=="job_binding_changed"
        ||s=="row_transform_binding_changed"||s=="row_property_binding_changed"||s=="row_scene_binding_changed"
        ||s=="row_readonly_choice_changed"||s=="row_chain_topology_changed";
    if(binding_stale){
        f->buffers[0][0xbc]=0xef;
        assert(scope.restore()==Result::stale&&f->buffers[0][0xbc]==0xef&&f->graph_mode==1);
        assert(scope.release(false)==Result::ok&&f->roots.empty());return 0;
    }
    if(s=="row_resolution_cache_preserved"){
        f->put(f->buffers[0].data(),0x100,uint32_t{77});
        f->put(f->buffers[0].data(),0x108,int32_t{42});
        f->put(f->buffers[0].data(),0x134,uint32_t{77});
        f->put(f->buffers[0].data(),0x13c,int32_t{41});
        f->put(f->buffers[1].data(),0x54,uint32_t{77});
        f->put(f->buffers[2].data(),0xcc,uint32_t{77});
    }
    if(s=="job_generation_changed")f->replace_job=true;
    if(s=="buffer_generation_changed")f->lists[0].capacity=1;
    if(s=="pose_parent_changed")f->bone->parent=f->outside;
    if(s=="source_changed")f->source=false;
    const bool stale=s=="job_generation_changed"||s=="buffer_generation_changed"||s=="pose_parent_changed"||s=="source_changed";
    if(stale){
        assert(scope.restore()==Result::stale);const int fences=f->completions;
        assert(scope.release(false)==Result::ok);assert(f->completions==fences&&f->roots.empty());return 0;
    }
    // Parent original root playback scope has re-applied the saved root time.
    f->root_clock=11.2;for(auto& node:f->nodes)node.time=11.2;
    assert(scope.restore()==Result::ok);
    assert(std::memcmp(old_job,f->job,sizeof old_job)==0);
    if(s=="row_resolution_cache_preserved"){
        assert(f->get<uint32_t>(f->buffers[0].data(),0x100)==77);
        assert(f->get<int32_t>(f->buffers[0].data(),0x108)==42);
        assert(f->get<uint32_t>(f->buffers[0].data(),0x134)==77);
        assert(f->get<int32_t>(f->buffers[0].data(),0x13c)==41);
        assert(f->get<uint32_t>(f->buffers[1].data(),0x54)==77);
        assert(f->get<uint32_t>(f->buffers[2].data(),0xcc)==77);
        assert(f->buffers[0][0xbc]==old_buffers[0][0xbc]&&f->buffers[2][0x2c]==old_buffers[2][0x2c]);
    }else for(size_t i=0;i<4;++i)assert(f->buffers[i]==old_buffers[i]);
    assert(std::memcmp(&old_pose,&f->bone->pose,sizeof old_pose)==0&&f->graph_mode==2);
    assert(scope.release(true)==Result::ok&&!scope.active()&&f->roots.empty());
    f->gate.invoke_managed(solver,f->job,nullptr,nullptr); // Ordinary viewer forwards after retirement.
}
'''


@pytest.fixture(scope="module")
def state_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    directory = tmp_path_factory.mktemp("mp4-actor-state")
    source = directory / "state.cpp"
    source.write_text(SOURCE)
    binary = directory / "state"
    built = subprocess.run(
        [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I",
         str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "complete_restore", "grant", "hold_regrant_keeps_game_time", "external_mode_change", "missing_api", "invalid_configure", "clock_not_held",
    "routes_not_ready", "wrong_actor_type", "wrong_rig_job_type", "wrong_native_job_type",
    "uninitialized", "animator_unscaled", "animator_culled", "dead_rig", "root_allocation_failure",
    "native_list_negative", "native_list_capacity", "native_list_huge", "native_list_unmapped",
    "boxed_buffer_mismatch", "fence_pending", "pose_outside", "pose_duplicate", "pose_wrong_array",
    "pose_nan", "pose_root_oom", "captured_release", "clip_advances", "job_clock_advances",
    "root_advances", "zero_pose_nonzero", "zero_pose_failure", "job_generation_changed",
    "buffer_generation_changed", "pose_parent_changed", "source_changed",
    "curve_pointer_changed", "map_pointer_changed", "job_binding_changed", "row_transform_binding_changed",
    "row_property_binding_changed", "row_scene_binding_changed", "row_readonly_choice_changed",
    "row_chain_topology_changed", "row_resolution_cache_preserved",
])
def test_selected_actor_deep_state_and_restore(state_binary, scenario):
    ran = subprocess.run([str(state_binary), scenario], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
