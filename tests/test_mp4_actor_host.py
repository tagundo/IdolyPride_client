"""Production host selection/memory/mode guards over an explicit fake heap.

Original native instruction/profile tests are separate. These cases do not
claim live Unity, GPU, Burst selection or whole-scene restoration coverage.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    at = opening + 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


@pytest.fixture(scope='module')
def host_binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    bridge = (NATIVE / 'bridge.cpp').read_text()
    selected = [
        'bool mp4_actor_map_add(', 'bool mp4_actor_refresh_maps(', 'bool mp4_actor_mapped(const void* value',
        'template<class T> bool mp4_actor_field(', 'bool mp4_actor_list(',
        'bool mp4_actor_owner(', 'void* mp4_actor_transforms(',
        'bool mp4_actor_graph_mode(mp4actor::Handle* handle',
        'void mp4_actor_withdraw_interception() noexcept',
        'void mp4_actor_scene_will_change(', 'void mp4_actor_process_hook(', 'void mp4_actor_burst_hook(',
        '[[maybe_unused]] mp4actor::Result mp4_actor_grant(']
    actual = '\n'.join(function(bridge, signature) for signature in selected)
    prefix = r'''
#include "mp4_actor_state.hpp"
#include "mp4_actor_state_profile.hpp"
#include "mp4_game_adapter.hpp"
#include "mp4_game_bindings.hpp"
#include <atomic>
#include <array>
#include <cassert>
#include <cstdio>
#include <map>
#include <memory>
#include <string>
#include <vector>
namespace mp4actor=idoly_mp4_actor;namespace mp4game=idoly_mp4_game;
using Method=const void;
auto mp4_actor_profile=mp4actor::android_actor_profile;auto mp4_profile=mp4game::android_game_profile;
uintptr_t image_base=0;bool on_main=true,source_current=true,mp4_actor_source_verified=true;
bool game_call(){return on_main;}
struct Range{uintptr_t begin=0,end=0;unsigned protection=0;};Range mp4_actor_ranges[4096]{};size_t mp4_actor_range_count=0;
struct Object{alignas(16) std::array<unsigned char,1024> memory{};std::string type;};
std::vector<std::unique_ptr<Object>> heap;std::map<void*,Object*> objects;
void* make(const char* type){auto obj=std::make_unique<Object>();obj->type=type;void* raw=obj->memory.data();objects[raw]=obj.get();heap.push_back(std::move(obj));return raw;}
template<class T>T read(void* p,size_t at){T value{};memcpy(&value,static_cast<unsigned char*>(p)+at,sizeof value);return value;}
template<class T>void put(void* p,size_t at,T value){memcpy(static_cast<unsigned char*>(p)+at,&value,sizeof value);}
bool mp4_type_is(void* p,const char* type){auto it=objects.find(p);if(it==objects.end())return false;const auto& actual=it->second->type;return actual==type||(!strcmp(type,"System.Array")&&actual.size()>2&&actual.substr(actual.size()-2)=="[]");}
bool mp4_alive(void* p){return objects.count(p);}
size_t mp4_array_length(void* p){return read<uintptr_t>(p,0x18);}
void* mp4_array_data(void* p){return static_cast<unsigned char*>(p)+0x20;}
uint32_t mp4_actor_transform_type_handle=7;void* type_object=reinterpret_cast<void*>(0x1234);
void* weak_get(uint32_t value){return value==7?type_object:nullptr;}
bool mp4_actor_selected_source(void*){return source_current;}
struct FakeScope{uint64_t last=0;mp4actor::Result commit_grant(uint64_t n){last=n;return mp4actor::Result::ok;}};
struct Host{void* player=nullptr;void* presenter=nullptr;uint64_t epoch=0;bool invalidated=false;FakeScope scope;}mp4_actor_host;
mp4actor::MonoGate mp4_actor_mono_gate;mp4actor::WorkerGate mp4_actor_gate;mp4actor::ManagedProcess mp4_actor_process_original=nullptr;mp4actor::BurstExecute mp4_actor_burst_original=nullptr;
void* actor_object=nullptr;void* game_object=nullptr;void* result_array=nullptr;unsigned components_calls=0;
void* get_game_object(void* actor,Method*){assert(actor==actor_object);return game_object;}
void* components(void* object,void* type,bool search,bool recursive,bool inactive,bool reverse,void* list,Method*){
    assert(object==game_object&&type==type_object&&search&&recursive&&inactive&&!reverse&&!list);++components_calls;return result_array;
}
uintptr_t node_address=0;bool native_valid=true;
bool valid_graph(mp4actor::Handle* h,void*){return native_valid&&h->handle==node_address&&h->version==9;}
unsigned managed_calls=0,burst_calls=0;void* expected_job=nullptr;
void managed(void* job,const void* stream,const void* method){assert(job==expected_job&&stream==reinterpret_cast<void*>(2)&&method==reinterpret_cast<void*>(3));++managed_calls;}
void burst(void* job,const void* stream,intptr_t tag,void* ranges,int32_t index){assert(job==expected_job&&stream==reinterpret_cast<void*>(2)&&tag==1&&ranges==reinterpret_cast<void*>(4)&&index==5);++burst_calls;}
'''
    driver = r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
    if(mode=="grant_mapping"){
        assert(mp4_actor_grant(nullptr,0)==mp4actor::Result::ok&&mp4_actor_host.scope.last==1);
        assert(mp4_actor_grant(nullptr,9)==mp4actor::Result::ok&&mp4_actor_host.scope.last==10);
        assert(mp4_actor_grant(nullptr,~uint64_t(0))==mp4actor::Result::invalid&&mp4_actor_host.scope.last==10);return 0;
    }
    if(mode=="worker_lifecycle"){
        alignas(16) unsigned char job[0x168]{};uintptr_t key=0x1122;memcpy(job+0x28,&key,8);
        expected_job=job;mp4_actor_process_original=managed;mp4_actor_burst_original=burst;
        mp4_actor_process_hook(job,reinterpret_cast<void*>(2),reinterpret_cast<void*>(3));assert(managed_calls==1);
        auto identity=mp4actor::key_from_original_job(job);assert(mp4_actor_gate.publish(&identity,1,7,true)==mp4actor::GateResult::ok);
        mp4_actor_process_hook(job,reinterpret_cast<void*>(2),reinterpret_cast<void*>(3));assert(managed_calls==1);
        assert(mp4_actor_gate.grant(1,7,true)==mp4actor::GateResult::ok);
        mp4_actor_burst_hook(job,reinterpret_cast<void*>(2),1,reinterpret_cast<void*>(4),5);assert(burst_calls==1);
        mp4_actor_process_hook(job,reinterpret_cast<void*>(2),reinterpret_cast<void*>(3));assert(managed_calls==1);
        mp4_actor_host.player=reinterpret_cast<void*>(99);mp4_actor_host.presenter=reinterpret_cast<void*>(100);mp4_actor_host.epoch=7;
        mp4_actor_scene_will_change(nullptr);mp4_actor_scene_will_change(reinterpret_cast<void*>(101));assert(!mp4_actor_host.invalidated);
        mp4_actor_scene_will_change(reinterpret_cast<void*>(99));assert(mp4_actor_host.invalidated&&mp4_actor_gate.pending_retirement_epoch()==7);
        mp4_actor_process_hook(job,reinterpret_cast<void*>(2),reinterpret_cast<void*>(3));assert(managed_calls==2);return 0;
    }
    assert(mp4_actor_refresh_maps());
    if(mode.rfind("mode_",0)==0){
        alignas(16) unsigned char node[0x40]{},graph[0x40]{};node_address=reinterpret_cast<uintptr_t>(node);
        put(node,0x28,reinterpret_cast<uintptr_t>(graph));put(graph,0x18,int32_t(1));
        mp4_profile.graph_valid.rva=reinterpret_cast<uintptr_t>(&valid_graph);
        mp4actor::Handle handle{node_address,9,0};int32_t result=-9;
        assert(mp4_actor_graph_mode(&handle,&result)&&result==1);
        if(mode=="mode_live"){for(int32_t i=0;i<4;++i){put(graph,0x18,i);assert(mp4_actor_graph_mode(&handle,&result)&&result==i);}return 0;}
        if(mode=="mode_invalid")put(graph,0x18,int32_t(4));
        if(mode=="mode_negative")put(graph,0x18,int32_t(-1));
        if(mode=="mode_version")handle.version=8;
        if(mode=="mode_thread")on_main=false;
        if(mode=="mode_source")mp4_actor_source_verified=false;
        if(mode=="mode_native_invalid")native_valid=false;
        if(mode=="mode_unmapped")put(node,0x28,uintptr_t(1));
        assert(!mp4_actor_graph_mode(&handle,&result));return 0;
    }
    if(mode=="components_flags"||mode=="components_wrong_array"){
        actor_object=make("VL.Core.VLActorController");game_object=make("UnityEngine.GameObject");
        result_array=make(mode=="components_flags"?"UnityEngine.Transform[]":"UnityEngine.Component[]");
        mp4_actor_profile.get_game_object.rva=reinterpret_cast<uintptr_t>(&get_game_object);
        mp4_actor_profile.get_components_internal.rva=reinterpret_cast<uintptr_t>(&components);
        assert(mp4_actor_transforms(actor_object)==(mode=="components_flags"?result_array:nullptr));assert(components_calls==1);return 0;
    }
    auto list=[](void* value){void* array=make("System.Object[]");put(array,0x18,uintptr_t(1));put(array,0x20,value);
        void* container=make("System.Collections.Generic.List`1");put(container,0x10,array);put(container,0x18,int32_t(1));return container;};
    const auto& f=mp4_actor_profile.fields;mp4actor::Owner own{};
    own.actor=make("VL.Core.VLActorController");own.extension=make("VL.VLActorActorSwing");own.builder=make("ActorSwing.ActorSwingBuilder");
    own.rig=make("ActorSwing.ActorSwingRig");own.animator=make("UnityEngine.Animator");
    own.graph={11,12,0};own.playable={21,22,0};own.output={31,32,0};
    void* animation=make("VL.VLAnimationClipPlayer");void* binder=make("Solis.Common.Live.SolisLiveBinder");
    mp4_actor_host.player=make("Solis.Common.SolisLivePlayer");put(mp4_actor_host.player,0x58,binder);put(binder,0x40,list(own.actor));
    put(own.actor,f.actor_player,animation);put(own.actor,f.actor_animator,own.animator);put(own.actor,f.actor_extensions,list(own.extension));
    put(own.extension,f.extension_player,animation);put(own.extension,f.extension_rig,own.rig);put(own.extension,f.extension_builder,own.builder);
    put(own.builder,f.builder_rig,own.rig);put(own.builder,f.builder_playable,own.playable);put(own.builder,f.builder_output,own.output);
    put(animation,f.player_animator,own.animator);put(animation,f.player_graph,own.graph);
    assert(mp4_actor_owner(nullptr,own));
    if(mode=="owner_valid")return 0;
    if(mode=="owner_source")source_current=false;
    else if(mode=="owner_member")put(binder,0x40,list(make("VL.Core.VLActorController")));
    else if(mode=="owner_extension")put(own.actor,f.actor_extensions,list(make("VL.VLActorActorSwing")));
    else if(mode=="owner_rig")put(own.builder,f.builder_rig,make("ActorSwing.ActorSwingRig"));
    else if(mode=="owner_graph")put(animation,f.player_graph,mp4actor::Handle{11,13,0});
    else if(mode=="owner_playable")put(own.builder,f.builder_playable,mp4actor::Handle{21,23,0});
    else if(mode=="owner_output")put(own.builder,f.builder_output,mp4actor::Handle{31,33,0});
    else if(mode=="owner_animator")put(animation,f.player_animator,make("UnityEngine.Animator"));
    else assert(false);
    assert(!mp4_actor_owner(nullptr,own));
}
'''
    folder = tmp_path_factory.mktemp('mp4-actor-real-host')
    source, binary = folder / 'host.cpp', folder / 'host'
    source.write_text(prefix + actual + driver)
    result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(NATIVE), str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', ['grant_mapping', 'worker_lifecycle', 'mode_live', 'mode_invalid', 'mode_negative',
    'mode_version', 'mode_thread', 'mode_source', 'mode_native_invalid', 'mode_unmapped',
    'components_flags', 'components_wrong_array', 'owner_valid', 'owner_source', 'owner_member',
    'owner_extension', 'owner_rig', 'owner_graph', 'owner_playable', 'owner_output', 'owner_animator'])
def test_actual_host_selection_lifetime_and_native_mode_are_strict(host_binary, mode):
    result = subprocess.run([str(host_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_photography_replacement_restores_shader_before_original_or_data_replacement():
    bridge=(NATIVE/'bridge.cpp').read_text()
    for signature,original in (("Mp4UniTask mp4_photography_initialize_hook(","mp4_photography_initialize_original("),
                               ("Mp4UniTask mp4_photography_player_initialize_hook(","mp4_photography_player_initialize_original(")):
        body=function(bridge,signature)
        assert body.index('mp4_scene_will_change(self)')<body.index('observe_source_will_change(self)')<body.index(original)
    body=function(bridge,'Mp4UniTask mp4_photography_player_initialize_hook(')
    assert body.index('observe_source_will_change(self)')<body.index('mp4_normalize_photography_descriptors(data)')
