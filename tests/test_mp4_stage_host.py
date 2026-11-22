"""Execute shipping Stage rebuild transactions with typed dependency stubs.

This deliberately extracts the real bridge functions; it does not execute a
second Python model of their authorization logic or claim a Unity/GPU result.
"""
import os
import re
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = source.index(name + '(')
    # Typed hook prototypes may precede their production definition.
    while source.index(';', start) < source.index('{', start):
        start = source.index(name + '(', start + len(name) + 1)
    start = source.rfind('\n', 0, start) + 1
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
            if not depth:
                return source[start:end + 1]
    raise AssertionError('Unclosed shipping function: ' + name)


PREFIX = r'''
#include "mp4_stage_state.hpp"
#include "mp4_playback_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
namespace mp4stage=idoly_mp4_stage;
namespace idoly_mp4_runtime {
struct Game {
    idoly_mp4_playback::Phase phase=idoly_mp4_playback::Phase::starting;
    bool rebuilding=true;
    idoly_mp4_playback::Phase automatic_rebuild_phase()const{return phase;}
    bool automatic_rebuild_in_progress()const{return rebuilding;}
} game;
}
struct Host {
    struct Source {void* director=nullptr;} source;
    bool configured=false,invalidated=false,rebuild_expected=false,rebuilding=false;
    bool start_rebuilt=false,restore_rebuilt=false;
    const char* error="none";
} mp4_stage_host;
int director,foreign_director,original_calls=0,control_checks=0,inventory_checks=0;
bool owner=true,held=true,controls=true,inventory=true;
bool mp4_stage_owner(void*){return owner&&!mp4_stage_host.invalidated;}
bool mp4_stage_clock_held(void*){return held;}
bool mp4_stage_refresh_controls(){++control_checks;return controls;}
bool mp4_stage_refresh_inventory(){++inventory_checks;return inventory;}
uintptr_t image_base=0;
void original(void* selected,void*){assert(selected==&director);++original_calls;}
'''

MAIN = r'''
int main(int argc,char** argv){
    assert(argc==2);std::string mode=argv[1];auto& h=mp4_stage_host;
    h.configured=true;h.source.director=&director;h.rebuild_expected=true;
    image_base=reinterpret_cast<uintptr_t>(&original)-idoly_mp4_playback::android_profile.director_rebuild.rva;
    if(mode=="unowned")h.configured=false;
    if(mode=="foreign")h.source.director=&foreign_director;
    if(mode=="missing_guard")idoly_mp4_runtime::game.rebuilding=false;
    if(mode=="playing")idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::playing;
    if(mode=="not_held")held=false;
    if(mode=="changed_owner")owner=false;
    if(mode=="no_ticket")h.rebuild_expected=false;
    if(mode=="remap_failed")controls=false;
    if(mode=="inventory_failed")inventory=false;
    mp4_stage_original_rebuild(&director,nullptr);
    if(mode=="unowned"){
        assert(original_calls==1&&!h.invalidated&&!control_checks&&!inventory_checks);return 0;
    }
    if(mode=="foreign"||mode=="missing_guard"||mode=="playing"||mode=="not_held"||mode=="changed_owner"||mode=="no_ticket"){
        assert(!original_calls&&h.invalidated&&!control_checks&&!inventory_checks);return 0;
    }
    assert(original_calls==1&&control_checks==1);
    if(mode=="remap_failed"||mode=="inventory_failed"){
        assert(h.invalidated&&!h.rebuilding);return 0;
    }
    assert(!h.invalidated&&!h.rebuilding&&h.start_rebuilt&&!h.rebuild_expected);
    if(mode=="duplicate_start"){
        mp4_stage_original_rebuild(&director,nullptr);
        assert(h.invalidated&&original_calls==1);return 0;
    }
    idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::restoring;
    mp4_stage_original_rebuild(&director,nullptr);
    assert(!h.invalidated&&h.restore_rebuilt&&original_calls==2);
    mp4_stage_original_rebuild(&director,nullptr);
    assert(h.invalidated&&original_calls==2);return 0;
}
'''


@pytest.fixture(scope='module')
def host_binary(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler required')
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    bodies = '\n'.join(function(source, name) for name in (
        'mp4_stage_before_original_rebuild', 'mp4_stage_after_original_rebuild',
        'mp4_stage_original_rebuild'))
    directory = tmp_path_factory.mktemp('stage-host')
    cpp = directory / 'host.cpp'
    binary = directory / 'host'
    cpp.write_text(PREFIX + bodies + MAIN)
    result = subprocess.run([
        compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I', str(ROOT / 'client-presentation/native'), str(cpp), '-o', str(binary)
    ], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', [
    'start_restore', 'duplicate_start', 'unowned', 'foreign', 'missing_guard',
    'playing', 'not_held', 'changed_owner', 'no_ticket', 'remap_failed',
    'inventory_failed'])
def test_shipping_stage_rebuild_authorization(host_binary, mode):
    result = subprocess.run([str(host_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


GRAPH_PREFIX = r'''
#include "mp4_actor_state.hpp"
#include "mp4_stage_state.hpp"
#include <cassert>
#include <vector>
#include <string>
#include <cstring>
using Method=void;
namespace mp4actor=idoly_mp4_actor;
namespace mp4stage=idoly_mp4_stage;
namespace mp4game {struct PlayableGraph{void* handle=nullptr;int version=0,padding=0;};}
const auto& mp4_stage_profile=mp4stage::android_profile;
struct Mp4StagePath{uint16_t director=0,root=0,length=0,inputs[64]{};};
struct Host{
    void* directors[64]{};size_t director_count=1;
    size_t count=1;mp4stage::Owner owners[256]{};
    bool graph_receipt=false,rebuilding=false,configured=false;
    void* director_assets[64]{};uint64_t timeline_receipts[64]{};
    mp4actor::Handle graph_receipts[64]{};Mp4StagePath control_paths[256]{};
    void* current_producers[256]{};uint32_t source_seeds[256]{};
    const char* error="none";
}mp4_stage_host;
int director,timeline,other_timeline,particle,other_particle,prefab;
std::vector<void*> particle_objects{&particle,&other_particle},control_objects;
bool root_valid=true;size_t retained_particles=0;
bool mp4_alive(void*p){return p!=nullptr;}
bool mp4_stage_root(void*p){if(!p||!root_valid)return false;++retained_particles;return true;}
struct PC {uint8_t header[16]{};float first=0,second=0;uint32_t seed=71,pad=0;void* ps=&particle;} first,second,duplicate;
static_assert(offsetof(PC,ps)==0x20&&offsetof(PC,seed)==0x18,"Original source fields");
struct Node{std::vector<mp4actor::Handle>inputs;void*script=nullptr;bool valid=true;double time=2;}root,control;
std::vector<mp4actor::Handle> roots;
uintptr_t graph_id=100,image_base=0;uint64_t fingerprint=55;void*asset=&timeline;
mp4actor::Handle handle(Node* n){return {reinterpret_cast<uintptr_t>(n),7,0};}
Node* node(mp4actor::Handle*h){return reinterpret_cast<Node*>(h->handle);}
bool mp4_type_is(void*p,const char*n){
    if(!p)return false;
    if(std::strcmp(n,"UnityEngine.ParticleSystem")==0){for(auto*v:particle_objects)if(v==p)return true;return false;}
    if(std::strcmp(n,"UnityEngine.Timeline.PrefabControlPlayable")==0)return p==&prefab;
    if(std::strcmp(n,"UnityEngine.Timeline.ParticleControlPlayable")==0){for(auto*v:control_objects)if(v==p)return true;return p==&first||p==&second||p==&duplicate;}
    return false;
}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){std::memcpy(&out,static_cast<uint8_t*>(p)+offset,sizeof(T));return true;}
bool mp4_stage_tracks(void*,void*,uint64_t&out){out=fingerprint;return true;}
void*get_asset(void*,Method*){return asset;}
void get_graph(void*,mp4game::PlayableGraph*out,Method*){out->handle=reinterpret_cast<void*>(graph_id);out->version=7;}
struct GameApi{decltype(&get_asset)director_get_asset=get_asset;decltype(&get_graph)director_graph_injected=get_graph;}mp4_api;
bool valid_graph(mp4actor::Handle*h,Method*){return h->handle==graph_id;}
int root_count(mp4actor::Handle*,Method*){return static_cast<int>(roots.size());}
void get_root(mp4actor::Handle*,int i,mp4actor::Handle*out,Method*){*out=roots.at(i);}
bool valid(mp4actor::Handle*h,Method*){return h->handle&&node(h)->valid;}
int inputs(mp4actor::Handle*h,Method*){return static_cast<int>(node(h)->inputs.size());}
void input(mp4actor::Handle*h,int i,mp4actor::Handle*out,Method*){*out=node(h)->inputs.at(i);}
double get_playable_time(mp4actor::Handle*h,Method*){return node(h)->time;}
struct ActorApi{
    decltype(&valid_graph)graph_valid;decltype(&root_count)graph_root_count;decltype(&get_root)graph_root;
    decltype(&valid)playable_valid;decltype(&inputs)playable_input_count;decltype(&input)playable_input;
    decltype(&get_playable_time)playable_time;
};
ActorApi mp4_actor_state_api(){return {valid_graph,root_count,get_root,valid,inputs,input,get_playable_time};}
void* script(mp4actor::Handle*h,Method*){return node(h)->script;}
'''

GRAPH_MAIN = r'''
int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];auto& h=mp4_stage_host;
    h.directors[0]=&director;h.owners[0].particle=&particle;control.script=&first;
    roots={handle(&root)};root.inputs={mp4actor::Handle{},handle(&control)};
    image_base=reinterpret_cast<uintptr_t>(&script)-mp4_stage_profile.playable_script.rva;
    void* result[256]{};uint32_t seeds[256]{};
    if(mode.rfind("discover_",0)==0){
        h.count=0;
        if(mode=="discover_union")h.owners[h.count++].particle=&other_particle;
        if(mode=="discover_no_root")root_valid=false;
        if(mode=="discover_closed")h.graph_receipt=true;
        if(mode=="discover_configured")h.configured=true;
        if(mode=="discover_wrong_type")first.ps=&prefab;
        if(mode=="discover_capacity"){h.count=256;first.ps=&other_particle;}
        std::vector<PC>many(205);std::vector<int>systems(205);std::vector<Node>nodes(205);
        if(mode=="discover_205"){
            root.inputs.clear();
            for(size_t i=0;i<205;++i){many[i].ps=&systems[i];nodes[i].script=&many[i];
                particle_objects.push_back(&systems[i]);control_objects.push_back(&many[i]);root.inputs.push_back(handle(&nodes[i]));}
        }
        Node extra;extra.script=&duplicate;if(mode=="discover_ambiguous")root.inputs.push_back(handle(&extra));
        const bool accepted=mp4_stage_graph_controls(result,seeds,true);
        const bool expected=mode=="discover_one"||mode=="discover_union"||mode=="discover_205";
        assert(accepted==expected);
        if(accepted){assert(h.count==(mode=="discover_205"?205u:mode=="discover_union"?2u:1u));
            assert(retained_particles==(mode=="discover_205"?205u:1u));}
        return 0;
    }
    assert(mp4_stage_graph_controls(result,seeds));
    assert(result[0]==&first&&seeds[0]==71&&h.graph_receipt&&h.control_paths[0].length==1&&h.control_paths[0].inputs[0]==1);
    result[0]=nullptr;seeds[0]=0;h.rebuilding=true;graph_id=200;control.script=&second;
    if(mode=="outside_transaction")h.rebuilding=false;
    if(mode=="path_changed")root.inputs={handle(&control),mp4actor::Handle{}};
    if(mode=="asset_changed")asset=&other_timeline;
    if(mode=="source_changed")++fingerprint;
    if(mode=="prefab")control.script=&prefab;
    if(mode=="zero_seed")second.seed=0;
    if(mode=="outside_stage")second.ps=&other_particle;
    if(mode=="invalid_node")control.valid=false;
    Node extra;extra.script=&duplicate;
    if(mode=="multiple_producers")root.inputs.push_back(handle(&extra));
    const bool accepted=mp4_stage_graph_controls(result,seeds);
    if(mode!="authorized"){
        assert(!accepted);return 0;
    }
    assert(accepted&&result[0]==&second&&seeds[0]==71&&h.graph_receipts[0].handle==200);
    h.rebuilding=false;result[0]=nullptr;
    assert(mp4_stage_graph_controls(result,seeds)&&result[0]==&second);
    graph_id=300;result[0]=nullptr;
    assert(!mp4_stage_graph_controls(result,seeds));return 0;
}
'''


@pytest.fixture(scope='module')
def graph_binary(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler required')
    body = function((ROOT / 'client-presentation/native/bridge.cpp').read_text(), 'mp4_stage_graph_controls')
    directory = tmp_path_factory.mktemp('stage-graph')
    cpp = directory / 'graph.cpp'
    binary = directory / 'graph'
    cpp.write_text(GRAPH_PREFIX + body + GRAPH_MAIN)
    result = subprocess.run([
        compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I', str(ROOT / 'client-presentation/native'), str(cpp), '-o', str(binary)
    ], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', [
    'authorized', 'outside_transaction', 'path_changed', 'asset_changed',
    'source_changed', 'prefab', 'zero_seed', 'outside_stage', 'invalid_node',
    'multiple_producers', 'discover_one', 'discover_union', 'discover_205', 'discover_no_root', 'discover_closed',
    'discover_configured', 'discover_wrong_type', 'discover_capacity', 'discover_ambiguous'])
def test_shipping_stage_graph_path_and_asset_receipts(graph_binary, mode):
    result = subprocess.run([str(graph_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


INIT_PREFIX = r'''
#include <cmath>
#include <limits>
bool mp4_stage_zero_evaluation=true;
bool source_current=true,clock_held=true;
bool mp4_stage_owner(void*){return source_current;}
bool mp4_stage_clock_held(void*){return clock_held;}
'''

INIT_MAIN = r'''
int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];auto& h=mp4_stage_host;
    h.directors[0]=&director;h.owners[0]={&particle,&first,1};h.current_producers[0]=&second;h.source_seeds[0]=71;
    h.control_paths[0].length=1;h.control_paths[0].inputs[0]=1;h.graph_receipts[0]={graph_id,7,0};
    roots={handle(&root)};root.inputs={mp4actor::Handle{},handle(&control)};control.script=&second;second.first=-1;
    image_base=reinterpret_cast<uintptr_t>(&script)-mp4_stage_profile.playable_script.rva;
    void* producer=&second;float requested=2;bool restart=true;void* system=nullptr;
    if(mode=="outside_zero")mp4_stage_zero_evaluation=false;
    if(mode=="not_held")clock_held=false;
    if(mode=="source_lost")source_current=false;
    if(mode=="rebuilding")h.rebuilding=true;
    if(mode=="not_restart")restart=false;
    if(mode=="already_initialized")second.first=0;
    if(mode=="previous_nan")second.first=std::numeric_limits<float>::quiet_NaN();
    if(mode=="seed_changed")++second.seed;
    if(mode=="ps_changed")second.ps=&other_particle;
    if(mode=="wrong_producer")producer=&first;
    if(mode=="kind_live")h.owners[0].producer_kind=2;
    if(mode=="graph_changed")++h.graph_receipts[0].version;
    if(mode=="wrong_path")h.control_paths[0].inputs[0]=0;
    if(mode=="invalid_node")control.valid=false;
    if(mode=="script_changed")control.script=&first;
    if(mode=="local_time_changed")control.time=3;
    if(mode=="local_time_nan")control.time=std::numeric_limits<double>::quiet_NaN();
    if(mode=="requested_nan")requested=std::numeric_limits<float>::quiet_NaN();
    if(mode=="requested_too_large")requested=901;
    const bool accepted=mp4_stage_initialization_target(producer,requested,restart,&system);
    assert(accepted==(mode=="authored_clip_in"));assert(system==(accepted?&particle:nullptr));
    assert(!mp4_stage_initialization_target(producer,requested,restart,nullptr));return 0;
}
'''


@pytest.fixture(scope='module')
def initialization_binary(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler required')
    body = function((ROOT / 'client-presentation/native/bridge.cpp').read_text(), 'mp4_stage_initialization_target')
    directory = tmp_path_factory.mktemp('stage-initialization')
    cpp = directory / 'initialization.cpp'
    binary = directory / 'initialization'
    cpp.write_text(GRAPH_PREFIX + INIT_PREFIX + body + INIT_MAIN)
    result = subprocess.run([
        compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I', str(ROOT / 'client-presentation/native'), str(cpp), '-o', str(binary)
    ], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', [
    'authored_clip_in', 'outside_zero', 'not_held', 'source_lost', 'rebuilding',
    'not_restart', 'already_initialized', 'previous_nan', 'seed_changed',
    'ps_changed', 'wrong_producer', 'kind_live', 'graph_changed', 'wrong_path',
    'invalid_node', 'script_changed', 'local_time_changed', 'local_time_nan',
    'requested_nan', 'requested_too_large'])
def test_shipping_stage_authored_clip_in_initialization(initialization_binary, mode):
    result = subprocess.run([str(initialization_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


PSY_STATE_PREFIX = r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <map>
#include <string>
namespace mp4stage=idoly_mp4_stage;
uint8_t controller[0xb0]{};struct Buffer{uint8_t header[16]{};void*native=nullptr;}anchors[9];
struct Palette{size_t count=8;uint8_t data[128]{};}palette,replacement;
bool owner=true,held=true,mapped=true;uint32_t next_root=0,fail_at=0;
std::map<uint32_t,void*> roots;
bool mp4_stage_owner(void*){return owner;}
bool mp4_stage_clock_held(void*){return held;}
bool mp4_type_is(void*p,const char*name){if(!p)return false;if(std::strcmp(name,"UnityEngine.ComputeBuffer")==0){for(size_t i=3;i<9;++i)if(p==&anchors[i])return true;return false;}return (p==&palette||p==&replacement)&&std::strcmp(name,"UnityEngine.Vector4[]")==0;}
size_t mp4_array_length(void*p){return static_cast<Palette*>(p)->count;}
void*mp4_array_data(void*p){return static_cast<Palette*>(p)->data;}
bool mp4_actor_mapped(const void*,size_t,bool){return mapped;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
template<class T>bool mp4_stage_store(void*p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof(T));return true;}
uint32_t mp4_retain(void*p){if(++next_root==fail_at)return 0;roots[next_root]=p;return next_root;}
void*weak_get(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t n){assert(roots.erase(n)==1);}
'''

PSY_STATE_MAIN = r'''
int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];
    for(size_t i=0;i<36;++i)controller[mp4stage::Layout::psyllium_time+i]=static_cast<uint8_t>(i+5);
    for(size_t i=0;i<128;++i)palette.data[i]=static_cast<uint8_t>(i+19);
    for(size_t i=0;i<9;++i){anchors[i].native=reinterpret_cast<void*>(100+i);void* value=&anchors[i];mp4_stage_store(controller,mp4_stage_psy_anchors[i],value);}
    void* array=&palette;mp4_stage_store(controller,mp4stage::Layout::psyllium_color_array_field,array);
    mp4_stage_store(controller,mp4stage::Layout::psyllium_packed_color,uint32_t(71));
    mp4_stage_store(controller,mp4stage::Layout::psyllium_color_changed,false);
    if(mode=="bad_array")palette.count=7;
    if(mode=="unmapped")mapped=false;
    if(mode=="partial_root")fail_at=5;
    const auto capture=mp4_stage_psy_capture_state(nullptr,controller);
    if(mode=="bad_array"||mode=="unmapped"||mode=="partial_root"){
        assert(capture!=mp4stage::Result::ok);mp4_stage_psy_release_state(nullptr);assert(roots.empty());return 0;
    }
    assert(capture==mp4stage::Result::ok&&roots.size()==10);
    std::memset(controller+mp4stage::Layout::psyllium_time,29,36);std::memset(palette.data,32,128);
    mp4_stage_store(controller,mp4stage::Layout::psyllium_packed_color,uint32_t(88));
    mp4_stage_store(controller,mp4stage::Layout::psyllium_color_changed,true);
    if(mode=="palette_changed"){array=&replacement;mp4_stage_store(controller,mp4stage::Layout::psyllium_color_array_field,array);}
    if(mode=="anchor_changed"){array=&replacement;mp4_stage_store(controller,mp4_stage_psy_anchors[4],array);}
    if(mode=="buffer_disposed")anchors[4].native=nullptr;
    if(mode=="buffer_reused")anchors[4].native=reinterpret_cast<void*>(500);
    if(mode=="lost_owner")owner=false;
    if(mode=="not_held")held=false;
    uint8_t before[sizeof controller];std::memcpy(before,controller,sizeof controller);
    const auto restore=mp4_stage_psy_restore_state(nullptr,controller);
    if(mode!="normal"){
        assert(restore!=mp4stage::Result::ok&&!std::memcmp(before,controller,sizeof controller)&&palette.data[0]==32);
    }else{
        assert(restore==mp4stage::Result::ok);
        for(size_t i=0;i<36;++i)assert(controller[mp4stage::Layout::psyllium_time+i]==static_cast<uint8_t>(i+5));
        for(size_t i=0;i<128;++i)assert(palette.data[i]==static_cast<uint8_t>(i+19));
        uint32_t packed=0;bool dirty=true;mp4_actor_field(controller,mp4stage::Layout::psyllium_packed_color,packed);
        mp4_actor_field(controller,mp4stage::Layout::psyllium_color_changed,dirty);assert(packed==71&&!dirty);
    }
    mp4_stage_psy_release_state(nullptr);assert(roots.empty());return 0;
}
'''


@pytest.fixture(scope='module')
def psy_state_binary(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler required')
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    start = source.index('struct Mp4StagePsyState {')
    end = source.index('bool mp4_stage_psy_palette(', start)
    bodies = source[start:end] + '\n'.join(function(source, name) for name in (
        'mp4_stage_psy_palette', 'mp4_stage_psy_capture_state',
        'mp4_stage_psy_restore_state', 'mp4_stage_psy_release_state'))
    directory = tmp_path_factory.mktemp('stage-psyllium-state')
    cpp = directory / 'psyllium.cpp'
    binary = directory / 'psyllium'
    cpp.write_text(PSY_STATE_PREFIX + bodies + PSY_STATE_MAIN)
    result = subprocess.run([
        compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I', str(ROOT / 'client-presentation/native'), str(cpp), '-o', str(binary)
    ], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', [
    'normal', 'palette_changed', 'anchor_changed', 'lost_owner', 'not_held',
    'bad_array', 'unmapped', 'partial_root', 'buffer_disposed', 'buffer_reused'])
def test_shipping_psyllium_cpu_state(psy_state_binary, mode):
    result = subprocess.run([str(psy_state_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr

EQUIPMENT_RESTORE_PREFIX=r'''
#include "mp4_actor_state.hpp"
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <vector>
#include <stdexcept>
using Method=void;
namespace mp4actor=idoly_mp4_actor;
namespace mp4stage=idoly_mp4_stage;
const auto& mp4_stage_profile=mp4stage::android_profile;
'''
EQUIPMENT_RESTORE_STUBS=r'''
int receiver,mesh,renderer,light,transform,material,source_material,slot_snapshot=19,cpu_snapshot=18,cpu_source=7;
uint8_t laser[184]{},vertex[44]{},saved_vertex[44]{},stream[116]{};
bool owned=true,held=true,enabled=false,throw_copy=false,lose_owner_copy=false;int slot=5,material_value=9;int received=0;
float light_value=0;mp4actor::Bounds native_bounds{};uint8_t native_submesh[48]{};mp4actor::Quaternion native_rotation{};
std::vector<std::string> events;
bool vlb_restore_fails=false;mp4stage::Result mp4_stage_vlb_restore(){events.push_back("vlb_restore");return vlb_restore_fails?mp4stage::Result::stale:mp4stage::Result::ok;}
struct Host{void*receiver=nullptr;}mp4_stage_host;
bool mp4_equipment_targets_current(void*){return owned;}
bool mp4_stage_clock_held(void*){return held;}
template<class T>bool mp4_stage_store(void*p,size_t at,T value){assert(p==&receiver&&at==89);received=value;return true;}
void apply(void*p,mp4stage::EquipmentArrayView array,Method*){
 assert(p==&receiver&&array.data==stream);events.push_back("source_apply");vertex[0]=99;memset(laser+72,99,48);slot=99;cpu_source=99;material_value=99;
}
void upload(void*p,Method*){
 assert(p==laser&&vertex[0]==42&&laser[72]==43);events.push_back("source_upload");memset(native_submesh,99,48);native_bounds.center.x=99;enabled=true;
}
void submesh(void*p,int32_t index,Mp4StageSubmesh descriptor,int32_t flags,Method*){
 assert(p==&mesh&&index==0&&flags==8);events.push_back("submesh");memcpy(native_submesh,descriptor.bytes,48);
}
void renderer_enabled(void*p,bool value,Method*){assert(p==&renderer);events.push_back("enabled");enabled=value;}
void color(void*p,const void*rgba,Method*){assert(p==&light&&static_cast<const float*>(rgba)[0]==7);events.push_back("light_color");}
void intensity(void*p,float value,Method*){assert(p==&light);events.push_back("light_intensity");light_value=value;}
void rotation(void*p,const mp4actor::Quaternion*q,Method*){assert(p==&transform);events.push_back("rotation");native_rotation=*q;}
template<class F>F mp4_equipment_call(const mp4stage::Binding& binding){
 uintptr_t pointer=0;
 if(binding.rva==mp4_stage_profile.equipment_receiver_apply.rva)pointer=reinterpret_cast<uintptr_t>(&apply);
 if(binding.rva==mp4_stage_profile.equipment_laser_mesh_update.rva)pointer=reinterpret_cast<uintptr_t>(&upload);
 if(binding.rva==mp4_stage_profile.equipment_mesh_submesh_set.rva)pointer=reinterpret_cast<uintptr_t>(&submesh);
 if(binding.rva==mp4_stage_profile.equipment_renderer_enabled_set.rva)pointer=reinterpret_cast<uintptr_t>(&renderer_enabled);
 if(binding.rva==mp4_stage_profile.equipment_light_color_set.rva)pointer=reinterpret_cast<uintptr_t>(&color);
 if(binding.rva==mp4_stage_profile.equipment_light_intensity_set.rva)pointer=reinterpret_cast<uintptr_t>(&intensity);
 if(binding.rva==mp4_stage_profile.equipment_rotation_set.rva)pointer=reinterpret_cast<uintptr_t>(&rotation);
 assert(pointer);return reinterpret_cast<F>(pointer);
}
void bounds(void*p,const mp4actor::Bounds*b,Method*){assert(p==&mesh);events.push_back("bounds");native_bounds=*b;}
void material_copy(void*p,void*source,Method*){assert(p==&material&&source==&source_material);events.push_back("material");material_value=17;}
void block_set(void*p,void*source,int32_t index,Method*){
 assert(p==&renderer&&index==0);events.push_back("block_set");slot=source?*static_cast<int*>(source):0;
 if(lose_owner_copy&&source==&cpu_snapshot){slot=66;owned=false;}
 if(throw_copy&&source==&cpu_snapshot){throw_copy=false;throw std::runtime_error("setter changed then threw");}
}
void block_get(void*p,void*target,int32_t index,Method*){assert(p==&renderer&&index==0);events.push_back("block_get");*static_cast<int*>(target)=slot;}
'''
EQUIPMENT_RESTORE_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];auto&s=mp4_equipment_targets;s.started=s.captured=true;s.count=2;s.material_count=1;s.receiver_stream={stream,1,4};s.receiver_received=1;mp4_stage_host.receiver=&receiver;
 auto&t=s.targets[0];t.object=laser;t.kind=4;t.vertices={vertex,1,4};t.saved_vertices=saved_vertex;saved_vertex[0]=42;t.laser_cpu[0]=43;t.renderer=&renderer;t.mesh=&mesh;t.bounds.center.x=7;t.submesh[0]=8;t.transforms[0]=&transform;t.rotations[0].x=3;
 auto&l=s.targets[1];l.kind=1;l.light=&light;l.color[0]=7;l.intensity=11;
 auto&m=s.materials[0];m.material=&material;m.material_image=&source_material;m.renderer=&renderer;m.block=&cpu_source;m.cpu_image=&cpu_snapshot;m.slot_image=&slot_snapshot;
 s.images.mesh_bounds_set=bounds;s.images.material_copy=material_copy;s.images.block_set=block_set;s.images.block_get=block_get;
 if(mode=="owner_lost")owned=false;
 if(mode=="not_held")held=false;
 if(mode=="empty_slot")m.empty=true;
 if(mode=="setter_exception")throw_copy=true;
 if(mode=="superseded_slot")lose_owner_copy=true;
 if(mode=="vlb_failure")vlb_restore_fails=true;
 if(mode=="owner_lost"||mode=="not_held"){
  assert(mp4_equipment_targets_restore(nullptr)==mp4stage::Result::stale&&events.empty());return 0;
 }
 if(mode=="setter_exception"){
  bool caught=false;try{mp4_equipment_targets_restore(nullptr);}catch(const std::runtime_error&){caught=true;}
  assert(caught&&slot==19&&!m.slot_displaced);return 0;
 }
 auto result=mp4_equipment_targets_restore(nullptr);
 if(mode=="vlb_failure"){assert(result==mp4stage::Result::stale&&material_value==99&&events.back()=="vlb_restore");return 0;}
 if(mode=="superseded_slot"){
  assert(result==mp4stage::Result::stale&&slot==66&&cpu_source==99&&m.slot_displaced);return 0;
 }
 assert(result==mp4stage::Result::ok&&events.front()=="source_apply");
 assert(vertex[0]==42&&laser[72]==43&&native_bounds.center.x==7&&native_submesh[0]==8&&!enabled&&native_rotation.x==3);
 assert(light_value==11&&material_value==17&&cpu_source==18&&slot==(mode=="empty_slot"?0:19)&&received==1&&!m.slot_displaced);
 return 0;
}
'''

@pytest.fixture(scope='module')
def equipment_restore_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    start=source.index('namespace mp4stageimages=')
    end=source.index('template<class F> F mp4_equipment_call',start)
    types=source[start:end]
    bodies='\n'.join(function(source,name) for name in ('mp4_equipment_slot_restore','mp4_equipment_cpu_copy','mp4_equipment_targets_restore'))
    directory=tmp_path_factory.mktemp('stage-equipment-restore');cpp=directory/'restore.cpp';binary=directory/'restore'
    cpp.write_text(EQUIPMENT_RESTORE_PREFIX+types+EQUIPMENT_RESTORE_STUBS+bodies+EQUIPMENT_RESTORE_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','empty_slot','owner_lost','not_held','setter_exception','superseded_slot','vlb_failure'])
def test_shipping_equipment_native_restore(equipment_restore_binary,mode):
    result=subprocess.run([str(equipment_restore_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

EQUIPMENT_RECEIPT_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <map>
#include <vector>
using Method=void;
namespace mp4stage=idoly_mp4_stage;
const auto& mp4_stage_profile=mp4stage::android_profile;
uint8_t controller[128]{};int receiver,other_receiver,director,other_director;
std::vector<uint8_t> arrays[4];int replacement;
bool on_thread=true,verified=true,graph_valid=true,mapped=true;
bool mp4_stage_source_verified=true;uintptr_t image_base=0;
std::map<uint32_t,void*> handles;uint32_t serial=0;
uint32_t makeweak(void*p,bool){handles[++serial]=p;return serial;}
uint32_t(*weak_new)(void*,bool)=makeweak;
void*weak_get(uint32_t n){auto it=handles.find(n);return it==handles.end()?nullptr:it->second;}
void weak_free(uint32_t n){assert(handles.erase(n)==1);}
bool game_call(){return on_thread;}
bool valid_graph(void*p,Method*){assert(p==controller);return graph_valid;}
bool mp4_type_is(void*p,const char*n){
 if(!p)return false;
 if(std::strcmp(n,"Solis.Live.Equipment.LiveEquipmentController")==0)return p==controller;
 if(std::strcmp(n,"Solis.Live.Equipment.LiveEquipmentReceiver")==0)return p==&receiver||p==&other_receiver;
 if(std::strcmp(n,"UnityEngine.Playables.PlayableDirector")==0)return p==&director||p==&other_director;
 return false;
}
bool mp4_alive(void*){return true;}
bool mp4_actor_mapped(const void*,size_t,bool){return mapped;}
bool mp4_actor_refresh_maps(){return mapped;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
template<class T>void field(size_t at,T value){memcpy(controller+at,&value,sizeof(T));}
'''
EQUIPMENT_RECEIPT_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];field<void*>(32,&receiver);field<void*>(40,&director);field<uint8_t>(112,1);
 const int counts[]={256,256,256,1};
 for(size_t i=0;i<4;++i){arrays[i].resize(static_cast<size_t>(counts[i])*mp4stage::equipment_stride[i]);field(48+i*16,mp4stage::EquipmentArrayView{arrays[i].data(),counts[i],4});}
 image_base=reinterpret_cast<uintptr_t>(&valid_graph)-mp4_stage_profile.equipment_graph_valid.rva;
 if(mode=="unverified")mp4_stage_source_verified=false;
 if(mode=="foreign_thread")on_thread=false;
 if(mode=="no_graph")graph_valid=false;
 if(mode=="unmapped")mapped=false;
 mp4_stage_observe_equipment_late(controller);
 if(mode=="unverified"||mode=="foreign_thread"||mode=="no_graph"||mode=="unmapped"){
  assert(!mp4_stage_controller_receipted(controller)&&handles.empty());return 0;
 }
 assert(mp4_stage_controller_receipted(controller));
 if(mode=="pointer_changed"||mode=="refresh")field<void*>(48,&replacement);
 if(mode=="count_changed")field<int32_t>(56,255);
 if(mode=="zero_count")field<int32_t>(56,0);
 if(mode=="allocator_changed")field<int32_t>(60,3);
 if(mode=="receiver_changed")field<void*>(32,&other_receiver);
 if(mode=="director_changed")field<void*>(40,&other_director);
 if(mode=="initialized_changed")field<uint8_t>(112,0);
 if(mode=="graph_lost")graph_valid=false;
 if(mode=="weak_expired")handles.clear();
 if(mode=="original_failed")mp4_stage_invalidate_equipment_late(controller);
 if(mode=="normal"){assert(mp4_stage_controller_receipted(controller));return 0;}
 assert(!mp4_stage_controller_receipted(controller));
 if(mode=="refresh"){mp4_stage_observe_equipment_late(controller);assert(mp4_stage_controller_receipted(controller));}
 return 0;
}
'''

@pytest.fixture(scope='module')
def equipment_receipt_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    start=source.index('struct Mp4EquipmentReceipt{');end=source.index('bool mp4_stage_controller_image(',start)
    types=source[start:end]
    bodies='\n'.join(function(source,name)for name in ('mp4_stage_controller_image','mp4_stage_same_controller_image','mp4_stage_invalidate_equipment_late','mp4_stage_observe_equipment_late','mp4_stage_controller_receipted'))
    directory=tmp_path_factory.mktemp('stage-equipment-receipt');cpp=directory/'receipt.cpp';binary=directory/'receipt'
    cpp.write_text(EQUIPMENT_RECEIPT_PREFIX+types+bodies+EQUIPMENT_RECEIPT_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','unverified','foreign_thread','no_graph','unmapped','pointer_changed','count_changed','zero_count','allocator_changed','receiver_changed','director_changed','initialized_changed','graph_lost','weak_expired','original_failed','refresh'])
def test_shipping_equipment_controller_receipts(equipment_receipt_binary,mode):
    result=subprocess.run([str(equipment_receipt_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

VLB_LIST_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <cstdlib>
namespace mp4stage=idoly_mp4_stage;
struct Array{size_t count=0;int values[16]{};}old_items,new_items;
struct List{uint8_t header[16]{};void*items=&old_items;int32_t size=2,version=7;}list;
struct Type{uint64_t data=0;uint32_t bits=0,pad=0;};
struct Field{size_t offset=0;Type type{};}items_field{16,{0,29u<<16,0}},size_field{24,{0,8u<<16,0}},version_field{28,{0,8u<<16,0}};
struct Profile{mp4stage::Binding field_offset{};}mp4_actor_profile;
uintptr_t image_base=0;bool owned=true,root_ok=true,lose_in_barrier=false,mapped=true;int writes=0,roots=0;
struct State{size_t bytes=0;}mp4_vlb_state;
bool mp4_stage_vlb_current(){return owned;}
void*object_class(void*p){return p==&list?&list:nullptr;}
const char*class_name(void*){return "List`1";}const char*class_namespace(void*){return "System.Collections.Generic";}
void*font_field(void*,const char*n){if(!strcmp(n,"_items"))return &items_field;if(!strcmp(n,"_size"))return &size_field;if(!strcmp(n,"_version"))return &version_field;return nullptr;}
const void*font_field_type(void*p){return &static_cast<Field*>(p)->type;}
size_t offset(const void*p){return static_cast<const Field*>(p)->offset;}
bool mp4_actor_mapped(const void*,size_t,bool){return mapped;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
template<class T>bool mp4_stage_store(void*p,size_t at,T value){++writes;memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof(T));return true;}
bool mp4_type_is(void*p,const char*n){return (p==&old_items||p==&new_items)&&!strcmp(n,"System.Int32[]");}
size_t mp4_array_length(void*p){return static_cast<Array*>(p)->count;}
void*mp4_array_data(void*p){return static_cast<Array*>(p)->values;}
bool mp4_equipment_pin(void*,bool){++roots;return root_ok;}
void mp4_vlb_write_reference(void*owner,void**address,void*value){assert(owner==&list&&address==&list.items);++writes;*address=value;if(lose_in_barrier)owned=false;}
'''
VLB_LIST_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];old_items.count=2;old_items.values[0]=5;old_items.values[1]=6;new_items.count=8;
 image_base=reinterpret_cast<uintptr_t>(&offset)-mp4_actor_profile.field_offset.rva;
 if(mode=="wrong_type")items_field.type.bits=18u<<16;
 if(mode=="static_field")items_field.type.bits|=16;
 if(mode=="root_failure")root_ok=false;
 if(mode=="unmapped")mapped=false;
 Mp4VlbIndexImage image{};bool captured=mp4_vlb_list_image(&list,image,true);
 if(mode=="wrong_type"||mode=="static_field"||mode=="root_failure"||mode=="unmapped"){
  assert(!captured&&writes==0);if(image.saved)free(image.saved);return 0;
 }
 assert(captured&&roots==2&&image.capacity==2&&image.size==2&&image.version==7);
 old_items.values[0]=99;list.items=&new_items;list.size=3;list.version=10;
 if(mode=="owner_lost")owned=false;
 if(mode=="lost_in_barrier")lose_in_barrier=true;
 const bool restored=mp4_vlb_restore_list(image);
 if(mode=="owner_lost"){assert(!restored&&list.items==&new_items&&list.size==3&&writes==0);}
 else if(mode=="lost_in_barrier"){assert(!restored&&list.items==&old_items&&old_items.values[0]==99&&list.size==3&&writes==1);}
 else assert(restored&&list.items==&old_items&&old_items.values[0]==5&&old_items.values[1]==6&&list.size==2&&list.version==7&&writes==3);
 free(image.saved);return 0;
}
'''

@pytest.fixture(scope='module')
def vlb_list_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'bool mp4_vlb_restore_list('not in source:pytest.skip('VLB source host not merged yet')
    start=re.search(r'\bstruct Mp4VlbIndexImage\s*\{',source).start();end=source.index('struct Mp4VlbDrawImage',start)
    bodies='\n'.join(function(source,name)for name in ('mp4_vlb_field','mp4_vlb_list_image','mp4_vlb_restore_list'))
    directory=tmp_path_factory.mktemp('stage-vlb-list');cpp=directory/'list.cpp';binary=directory/'list'
    cpp.write_text(VLB_LIST_PREFIX+source[start:end]+bodies+VLB_LIST_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['growth','wrong_type','static_field','root_failure','unmapped','owner_lost','lost_in_barrier'])
def test_shipping_vlb_managed_index_array_restore(vlb_list_binary,mode):
    result=subprocess.run([str(vlb_list_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

VLB_BUFFER_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <stdexcept>
#include <cstdlib>
namespace mp4stage=idoly_mp4_stage;
struct Method{};
struct Array{size_t length=256;uint8_t rows[256*256]{};}snapshot;
struct Mp4VlbBatchImage{mp4stage::EquipmentArrayView properties{};void*saved_properties=nullptr;void*saved_gpu=nullptr;void*buffer=nullptr;};
struct State{size_t bytes=0;}mp4_vlb_state;
struct Profile{mp4stage::TypeBinding vlb_property_type{};mp4stage::Binding vlb_compute_readback{},vlb_compute_upload{};}mp4_stage_profile;
uint8_t cpu[256*256]{},gpu[256*256]{};bool owned=true,root_ok=true,allocation_ok=true,correct_type=true,read_throws=false,upload_throws=false;
int reads=0,uploads=0,roots=0;bool was_rooted=false;void*klass=&snapshot;
bool mp4_stage_vlb_current(){return owned;}
void*mp4_resolved_type_class(const mp4stage::TypeBinding&,const char*s,const char*n){assert(!strcmp(s,"VLB")&&!strcmp(n,"VLBProperty"));return klass;}
void*mp4_array_new(void*c,uintptr_t n){assert(c==klass&&n==256);return allocation_ok?&snapshot:nullptr;}
bool mp4_equipment_pin(void*p,bool native){assert(p==&snapshot&&!native);++roots;was_rooted=root_ok;return root_ok;}
bool mp4_type_is(void*p,const char*t){return p==&snapshot&&correct_type&&!strcmp(t,"VLB.VLBProperty[]");}
size_t mp4_array_length(void*p){assert(p==&snapshot);return snapshot.length;}
void*mp4_array_data(void*p){assert(p==&snapshot);return snapshot.rows;}
bool mp4_actor_mapped(const void*p,size_t n,bool writable){assert(p==snapshot.rows&&n==sizeof(cpu)&&writable);return true;}
void readback(void*b,void*a,int32_t m,int32_t c,int32_t n,int32_t stride,Method*){
 assert(b==gpu&&a==&snapshot&&was_rooted&&m==0&&c==0&&n==256&&stride==256);++reads;
 memcpy(snapshot.rows,gpu,sizeof(gpu));if(read_throws)throw std::runtime_error("readback");
}
void upload(void*b,void*data,int32_t m,int32_t c,int32_t n,int32_t stride,Method*){
 assert(b==gpu&&data==snapshot.rows&&m==0&&c==0&&n==256&&stride==256);++uploads;
 memcpy(gpu,data,sizeof(gpu));if(upload_throws)throw std::runtime_error("upload");
}
template<class F>F mp4_equipment_call(const mp4stage::Binding&b){return reinterpret_cast<F>(&b==&mp4_stage_profile.vlb_compute_readback?reinterpret_cast<void*>(&readback):reinterpret_cast<void*>(&upload));}
'''
VLB_BUFFER_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];memset(cpu,3,sizeof(cpu));memset(gpu,7,sizeof(gpu));
 Mp4VlbBatchImage b{};b.properties.data=cpu;b.buffer=gpu;
 if(mode=="root_failure")root_ok=false;
 if(mode=="allocation_failure")allocation_ok=false;
 if(mode=="wrong_type")correct_type=false;
 if(mode=="wrong_length")snapshot.length=255;
 if(mode=="readback_throw")read_throws=true;
 bool captured=false,caught=false;try{captured=mp4_vlb_capture_buffer(b);}catch(const std::runtime_error&){caught=true;}
 if(mode=="root_failure"||mode=="allocation_failure"||mode=="wrong_type"||mode=="wrong_length"){
  assert(!captured&&!caught&&reads==0&&uploads==0);free(b.saved_properties);return 0;
 }
 if(mode=="readback_throw"){assert(!captured&&caught&&reads==1&&uploads==0&&roots==1);free(b.saved_properties);return 0;}
 assert(captured&&!caught&&reads==1&&roots==1&&snapshot.rows[0]==7&&static_cast<uint8_t*>(b.saved_properties)[0]==3);
 memset(cpu,11,sizeof(cpu));memset(gpu,13,sizeof(gpu));
 if(mode=="owner_lost")owned=false;
 if(mode=="upload_throw")upload_throws=true;
 bool restored=false;try{restored=mp4_vlb_restore_buffer(b);}catch(const std::runtime_error&){caught=true;}
 if(mode=="owner_lost"){assert(!restored&&!caught&&uploads==0&&cpu[0]==11&&gpu[0]==13);}
 else if(mode=="upload_throw"){assert(!restored&&caught&&uploads==1&&cpu[0]==3&&gpu[0]==7);upload_throws=false;assert(mp4_vlb_restore_buffer(b)&&uploads==2);}
 else assert(restored&&!caught&&uploads==1&&cpu[0]==3&&gpu[0]==7);
 free(b.saved_properties);return 0;
}
'''

@pytest.fixture(scope='module')
def vlb_buffer_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'bool mp4_vlb_capture_buffer('not in source:pytest.skip('VLB source host not merged yet')
    bodies='\n'.join(function(source,name)for name in ('mp4_vlb_capture_buffer','mp4_vlb_restore_buffer'))
    directory=tmp_path_factory.mktemp('stage-vlb-buffer');cpp=directory/'buffer.cpp';binary=directory/'buffer'
    cpp.write_text(VLB_BUFFER_PREFIX+bodies+VLB_BUFFER_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['independent_images','root_failure','allocation_failure','wrong_type','wrong_length','readback_throw','owner_lost','upload_throw'])
def test_shipping_vlb_independent_gpu_and_cpu_images(vlb_buffer_binary,mode):
    result=subprocess.run([str(vlb_buffer_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

VLB_RECEIPT_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
namespace mp4stage=idoly_mp4_stage;
struct Camera{uint8_t bytes[16]{};}camera,foreign_camera;
struct Ref{uint8_t padding[128]{};void*camera=&::camera;uint8_t suffix[200]{};}reference;
struct Mp4VlbBatchImage{void*data=nullptr;void*buffer=nullptr;void*buffer_native=nullptr;mp4stage::EquipmentArrayView properties{};}current;
bool on_thread=true,source_verified=true,image_valid=true,can_root=true;bool mp4_stage_source_verified=true;int batch=0,other_batch=0;
void* roots[256]{};uint32_t next_root=1;
uint32_t make_weak(void*p,bool){if(!can_root)return 0;assert(next_root<256);roots[next_root]=p;return next_root++;}
auto weak_new=&make_weak;
void*weak_get(uint32_t h){return roots[h];}void weak_free(uint32_t h){roots[h]=nullptr;}
bool game_call(){return on_thread;}
bool mp4_actor_mapped(void*p,size_t n,bool writable){return p==&reference&&n==336&&!writable;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
bool mp4_type_is(void*p,const char*t){return (p==&camera||p==&foreign_camera)&&!strcmp(t,"UnityEngine.Camera");}
bool mp4_alive(void*p){return p==&camera||p==&foreign_camera;}
bool mp4_vlb_camera_image(void*b,void*c,Mp4VlbBatchImage&out,bool snapshot){assert(!snapshot);if(!image_valid||b!=&batch||c!=&camera)return false;out=current;return true;}
bool mp4_equipment_same_array(const mp4stage::EquipmentArrayView&a,const mp4stage::EquipmentArrayView&b){return a.data==b.data&&a.count==b.count&&a.allocator==b.allocator;}
'''
VLB_RECEIPT_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];current.data=&current;current.buffer=&roots;current.buffer_native=&batch;current.properties={&camera,256,4};
 if(mode=="wrong_thread")on_thread=false;
 if(mode=="source_unverified")mp4_stage_source_verified=false;
 if(mode=="root_failure")can_root=false;
 if(mode=="invalid_image")image_valid=false;
 mp4_stage_vlb_observe(&batch,nullptr,&reference,nullptr);
 bool recorded=mp4_vlb_receipted(&batch,&camera,current);
 if(mode=="wrong_thread"||mode=="source_unverified"||mode=="root_failure"||mode=="invalid_image"){assert(!recorded);return 0;}
 assert(recorded);
 if(mode=="invalidate")mp4_stage_vlb_invalidate(&batch,&reference);
 if(mode=="weak_expired")roots[mp4_vlb_receipts[0].batch]=nullptr;
 if(mode=="array_changed")current.properties.data=&other_batch;
 if(mode=="length_changed")current.properties.count=255;
 if(mode=="allocator_changed")current.properties.allocator=3;
 if(mode=="buffer_changed")current.buffer=&other_batch;
 if(mode=="native_changed")current.buffer_native=&other_batch;
 if(mode=="data_changed")current.data=&other_batch;
 if(mode=="refresh"){mp4_stage_vlb_invalidate(&batch,&reference);current.buffer_native=&other_batch;mp4_stage_vlb_observe(&batch,nullptr,&reference,nullptr);}
 assert(mp4_vlb_receipted(&batch,&camera,current)==(mode=="normal"||mode=="refresh"));
 assert(!mp4_vlb_receipted(&other_batch,&camera,current));assert(!mp4_vlb_receipted(&batch,&foreign_camera,current));return 0;
}
'''

@pytest.fixture(scope='module')
def vlb_receipt_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'bool mp4_vlb_receipted('not in source:pytest.skip('VLB source host not merged yet')
    start=re.search(r'\bstruct Mp4VlbReceipt\s*\{',source).start();end=source.index('bool mp4_vlb_kind(',start)
    bodies='\n'.join(function(source,name)for name in ('mp4_vlb_camera_pointer','mp4_stage_vlb_invalidate','mp4_stage_vlb_observe','mp4_vlb_receipted'))
    directory=tmp_path_factory.mktemp('stage-vlb-receipts');cpp=directory/'receipts.cpp';binary=directory/'receipts'
    cpp.write_text(VLB_RECEIPT_PREFIX+source[start:end]+bodies+VLB_RECEIPT_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','wrong_thread','source_unverified','root_failure','invalid_image','invalidate','weak_expired','array_changed','length_changed','allocator_changed','buffer_changed','native_changed','data_changed','refresh'])
def test_shipping_vlb_successful_original_callback_receipts(vlb_receipt_binary,mode):
    result=subprocess.run([str(vlb_receipt_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

VLB_PREPARE_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <stdexcept>
namespace mp4stage=idoly_mp4_stage;
struct Method{};
struct Mp4VlbBatchImage{mp4stage::EquipmentArrayView properties{};void*buffer=nullptr;void*block=nullptr;};
struct State{bool started=true,captured=true,prepared=false;size_t batch_count=1;Mp4VlbBatchImage batches[1]{};}mp4_vlb_state;
struct Profile{mp4stage::Binding vlb_compute_upload{},vlb_block_clear{};}mp4_stage_profile;
uint8_t cpu[256*256]{},gpu[256*256]{};bool block_empty=false,owned=true,held=true,throw_upload=false,lose_upload=false,lose_clear=false;
int uploads=0,clears=0;
bool mp4_stage_vlb_current(){return owned;}
bool mp4_stage_clock_held(void*){return held;}
void upload(void*b,void*data,int32_t m,int32_t c,int32_t n,int32_t stride,Method*){
 assert(b==gpu&&data==cpu&&m==0&&c==0&&n==256&&stride==256);++uploads;
 for(size_t i=0;i<sizeof(cpu);++i)assert(cpu[i]==0);
 memcpy(gpu,cpu,sizeof(gpu));if(lose_upload)owned=false;if(throw_upload)throw std::runtime_error("upload");
}
void clear(void*b,Method*){assert(b==&block_empty&&uploads==1);++clears;block_empty=true;if(lose_clear)owned=false;}
template<class F>F mp4_equipment_call(const mp4stage::Binding&b){return reinterpret_cast<F>(&b==&mp4_stage_profile.vlb_compute_upload?reinterpret_cast<void*>(&upload):reinterpret_cast<void*>(&clear));}
'''
VLB_PREPARE_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];memset(cpu,3,sizeof(cpu));memset(gpu,7,sizeof(gpu));
 auto&s=mp4_vlb_state;s.batches[0].properties.data=cpu;s.batches[0].buffer=gpu;s.batches[0].block=&block_empty;
 if(mode=="unowned")owned=false;
 if(mode=="unheld")held=false;
 if(mode=="uncaptured")s.captured=false;
 if(mode=="no_beams")s.started=false;
 if(mode=="upload_throw")throw_upload=true;
 if(mode=="lost_in_upload")lose_upload=true;
 if(mode=="lost_in_clear")lose_clear=true;
 bool caught=false;mp4stage::Result r=mp4stage::Result::invalid;
 try{r=mp4_stage_vlb_prepare();}catch(const std::runtime_error&){caught=true;}
 if(mode=="unowned"||mode=="unheld"||mode=="uncaptured")assert(r==mp4stage::Result::stale&&uploads==0&&clears==0&&cpu[0]==3&&gpu[0]==7&&!s.prepared);
 else if(mode=="no_beams")assert(r==mp4stage::Result::ok&&uploads==0&&clears==0&&cpu[0]==3&&gpu[0]==7);
 else if(mode=="upload_throw")assert(caught&&uploads==1&&clears==0&&cpu[0]==0&&gpu[0]==0&&!s.prepared);
 else if(mode=="lost_in_upload")assert(r==mp4stage::Result::stale&&uploads==1&&clears==0&&!block_empty&&!s.prepared);
 else if(mode=="lost_in_clear")assert(r==mp4stage::Result::stale&&uploads==1&&clears==1&&block_empty&&!s.prepared);
 else {assert(r==mp4stage::Result::ok&&uploads==1&&clears==1&&block_empty&&s.prepared);assert(mp4_stage_vlb_prepare()==mp4stage::Result::ok&&uploads==1&&clears==1);}
 return 0;
}
'''

@pytest.fixture(scope='module')
def vlb_prepare_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'mp4stage::Result mp4_stage_vlb_prepare('not in source:pytest.skip('VLB source host not merged yet')
    directory=tmp_path_factory.mktemp('stage-vlb-prepare');cpp=directory/'prepare.cpp';binary=directory/'prepare'
    cpp.write_text(VLB_PREPARE_PREFIX+function(source,'mp4_stage_vlb_prepare')+VLB_PREPARE_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','unowned','unheld','uncaptured','no_beams','upload_throw','lost_in_upload','lost_in_clear'])
def test_shipping_vlb_original_constructor_baseline(vlb_prepare_binary,mode):
    result=subprocess.run([str(vlb_prepare_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

VLB_CONFIG_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <limits>
namespace mp4stage=idoly_mp4_stage;
struct Profile{mp4stage::TypeBinding vlb_config_type{};}mp4_stage_profile;
uint8_t beam[304]{},config[160]{},other_config[160]{},klass[192]{},other_class[192]{};
void* singleton=config;void* other_static=config;void* live_class=klass;bool root_ok=true;int roots=0,queries=0;
template<class T>void put(void*p,size_t at,T value){memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof(T));}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!p)return false;memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof(T));return true;}
void*mp4_resolved_type_class(const mp4stage::TypeBinding&,const char*s,const char*n){assert(!strcmp(s,"VLB")&&!strcmp(n,"Config"));++queries;return live_class;}
void*object_class(void*p){return p==config||p==other_config?klass:nullptr;}
bool mp4_type_is(void*p,const char*t){return (p==config||p==other_config)&&!strcmp(t,"VLB.Config");}
bool mp4_alive(void*p){return p==config||p==other_config;}
bool mp4_equipment_pin(void*p,bool native){assert(p==config&&native);++roots;return root_ok;}
'''
VLB_CONFIG_MAIN=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];put(klass,mp4stage::Layout::vlb_config_static_fields,&singleton);
 put(config,16,reinterpret_cast<void*>(0x100));put(config,64,2.f);put(config,68,3.f);put(config,72,4.f);put(config,76,5.f);
 put(beam,mp4stage::Layout::vlb_beam_noise_mode,int32_t{1});put(beam,mp4stage::Layout::vlb_beam_noise_intensity,1.f);
 put(beam,mp4stage::Layout::vlb_beam_noise_scale_global,uint8_t{1});put(beam,mp4stage::Layout::vlb_beam_noise_velocity_global,uint8_t{1});
 if(mode=="local"){put(beam,176,uint8_t{0});put(beam,184,uint8_t{0});}
 if(mode=="noise_off")put(beam,168,int32_t{0});
 if(mode=="zero_intensity")put(beam,172,0.f);
 if(mode=="missing_singleton")singleton=nullptr;
 if(mode=="missing_class")live_class=nullptr;
 if(mode=="root_failure")root_ok=false;
 if(mode=="nonfinite")put(config,68,std::numeric_limits<float>::quiet_NaN());
 if(mode=="unused_scale")put(beam,176,uint8_t{0});
 Mp4VlbNoiseConfig saved{};bool captured=mp4_vlb_noise_config(beam,saved,true);
 if(mode=="missing_singleton"||mode=="missing_class"||mode=="root_failure"||mode=="nonfinite"){assert(!captured);return 0;}
 assert(captured);
 if(mode=="local"||mode=="noise_off"||mode=="zero_intensity"){
  assert(queries==0&&roots==0&&saved.used==0);singleton=nullptr;assert(mp4_vlb_noise_config_current(beam,saved)&&queries==0);return 0;
 }
 assert(queries==1&&roots==1);
 if(mode=="scale_changed"||mode=="unused_scale")put(config,64,8.f);
 if(mode=="velocity_changed")put(config,72,8.f);
 if(mode=="native_changed")put(config,16,reinterpret_cast<void*>(0x200));
 if(mode=="singleton_changed"){memcpy(other_config,config,sizeof(config));singleton=other_config;}
 if(mode=="static_block_changed")put(klass,184,&other_static);
 if(mode=="flag_changed")put(beam,184,uint8_t{0});
 bool current=mp4_vlb_noise_config_current(beam,saved);
 assert(current==(mode=="normal"||mode=="unused_scale"));return 0;
}
'''

@pytest.fixture(scope='module')
def vlb_config_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'bool mp4_vlb_noise_config('not in source:pytest.skip('VLB source host not merged yet')
    start=re.search(r'\bstruct Mp4VlbNoiseConfig\s*\{',source).start();end=source.index('struct Mp4VlbBeamImage',start)
    bodies='\n'.join(function(source,name)for name in ('mp4_vlb_noise_config','mp4_vlb_noise_config_current'))
    directory=tmp_path_factory.mktemp('stage-vlb-config');cpp=directory/'config.cpp';binary=directory/'config'
    cpp.write_text(VLB_CONFIG_PREFIX+source[start:end]+bodies+VLB_CONFIG_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','local','noise_off','zero_intensity','missing_singleton','missing_class','root_failure','nonfinite','unused_scale','scale_changed','velocity_changed','native_changed','singleton_changed','static_block_changed','flag_changed'])
def test_shipping_vlb_readonly_optional_global_noise_config(vlb_config_binary,mode):
    result=subprocess.run([str(vlb_config_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr

STAGE_WITHDRAW_PREFIX=r'''
#include "mp4_stage_state.hpp"
#include <atomic>
#include <cassert>
#include <string>
#include <stdexcept>
using Method=void;
namespace mp4stage=idoly_mp4_stage;
struct Mp4RenderContext{void*pointer=nullptr;};
std::atomic<bool>mp4_stage_lease_active{true},mp4_stage_foreign_dirty{false},ready{true};
bool main_thread=true,withdraw_inside=false,throw_original=false;int originals[6]{},scope_calls=0,owner_queries=0,ends=0,receipts=0,revokes=0,old_writes=0;
int native_source=1;void*source=&native_source;
bool game_call(){return main_thread;}
void mp4_stage_withdraw_interception()noexcept;
struct Particle{
 void revoke_grants(){++revokes;}
 bool allow_simulate(void*,float,bool,bool,bool){++scope_calls;return false;}
 bool allow_producer(void*,void*,float){++scope_calls;return false;}
 idoly_mp4_stage::Result begin_control_initialization(void*){++scope_calls;return idoly_mp4_stage::Result::invalid;}
 void end_control_initialization(void*){++ends;}
}mp4_stage_particles;
struct Equipment{void revoke_grants(){++revokes;}}mp4_stage_equipment;
struct Psy{
 void revoke_grants(){++revokes;}
 idoly_mp4_stage::Result begin_psyllium(void*,void*,idoly_mp4_stage::PsylliumTicket&t){++scope_calls;t.changed=true;return idoly_mp4_stage::Result::ok;}
 idoly_mp4_stage::Result end_psyllium(idoly_mp4_stage::PsylliumTicket&t){++ends;if(t.changed&&mp4_stage_lease_active.load())++old_writes;t={};return idoly_mp4_stage::Result::ok;}
 const char*error(){return "test_scope";}
}mp4_stage_psyllium;
struct Owner{uint32_t producer_kind=1;void*particle=nullptr;};
struct Source{void*player=nullptr;void*presenter=nullptr;};
struct Host{bool configured=true,invalidated=false;size_t count=1;Owner owners[1]{};void*current_producers[1]{};const char*error="none";Source source{};}mp4_stage_host;
bool mp4_stage_zero_evaluation=false;
bool mp4_stage_owner(void*){++owner_queries;return false;}
bool mp4_stage_initialization_target(void*,float,bool,void**){++owner_queries;return false;}
template<class T>bool mp4_actor_field(void*,size_t,T&out){out=source;return true;}
void finish(){if(withdraw_inside)mp4_stage_withdraw_interception();if(throw_original)throw std::runtime_error("original");}
void ps_original(void*self,float t,bool c,bool r,bool f,Method*){assert(self==source&&t==.25f&&c&&!r&&f);++originals[0];finish();}
void live_original(void*self,void*ps,float t,Method*){assert(self==source&&ps==source&&t==.25f);++originals[1];finish();}
void pc_original(void*self,float t,bool r,Method*){assert(self==source&&t==.25f&&r);++originals[2];finish();}
void psy_original(void*self,Mp4RenderContext,void*,Method*){assert(self==source);++originals[3];finish();}
void eq_original(void*self,Method*){assert(self==source);++originals[4];finish();}
void vlb_original(void*self,void*,void*,void*,Method*){assert(self==source);++originals[5];finish();}
auto mp4_particle_simulate_original=&ps_original;auto mp4_live_particle_simulate_original=&live_original;auto mp4_particle_control_simulate_original=&pc_original;
auto mp4_psyllium_execute_original=&psy_original;auto mp4_equipment_late_original=&eq_original;auto mp4_vlb_draw_original=&vlb_original;
enum class Mp4EquipmentDispatch:uint8_t{forward,skip,owned};enum class Mp4VlbDispatch:uint8_t{forward,skip,owned};
bool allow_owned=false;
Mp4EquipmentDispatch eq_begin(void*){++scope_calls;return allow_owned?Mp4EquipmentDispatch::owned:Mp4EquipmentDispatch::skip;}
void eq_end(void*,bool){++ends;}void eq_observe(void*){++receipts;}void eq_invalidate(void*){}
auto mp4_equipment_dispatch_begin=&eq_begin;auto mp4_equipment_dispatch_end=&eq_end;auto mp4_equipment_observe_late=&eq_observe;auto mp4_equipment_invalidate_late=&eq_invalidate;
Mp4VlbDispatch vlb_begin(void*,void*,void*,void*){++scope_calls;return allow_owned?Mp4VlbDispatch::owned:Mp4VlbDispatch::skip;}
void vlb_end(void*,bool){++ends;}void vlb_observe(void*,void*,void*,void*){++receipts;}void vlb_invalidate(void*,void*){}
auto mp4_vlb_begin=&vlb_begin;auto mp4_vlb_end=&vlb_end;auto mp4_vlb_observe=&vlb_observe;auto mp4_vlb_invalidate=&vlb_invalidate;
struct Mono{template<class F>bool isolate(F f){f();return true;}}mp4_actor_mono_gate;
void mp4_stage_equipment_isolation_failed(){assert(false);}
'''
STAGE_WITHDRAW_MAIN=r'''
void invoke_all(){
 mp4_particle_simulate_hook(source,.25f,true,false,true,nullptr);
 mp4_live_particle_simulate_hook(source,source,.25f,nullptr);
 mp4_particle_control_simulate_hook(source,.25f,true,nullptr);
 mp4_psyllium_execute_hook(source,{},source,nullptr);
 mp4_equipment_late_hook(source,nullptr);mp4_vlb_draw_hook(source,source,source,source,nullptr);
}
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];mp4_stage_host.source={source,source};mp4_stage_host.current_producers[0]=source;mp4_stage_host.owners[0].particle=source;
 if(mode=="foreign_active"||mode=="foreign_inactive")main_thread=false;
 if(mode=="foreign_inactive")mp4_stage_lease_active=false;
 if(mode=="selected_invalidate"){mp4_stage_invalidate(nullptr,source);assert(mp4_stage_host.invalidated&&!mp4_stage_lease_active&&revokes==3&&owner_queries==0);return 0;}
 if(mode=="foreign_invalidate"){int other=0;mp4_stage_invalidate(nullptr,&other);assert(!mp4_stage_host.invalidated&&mp4_stage_lease_active&&revokes==0&&owner_queries==0);return 0;}
 if(mode=="eq_unwind"||mode=="vlb_unwind"||mode=="eq_throw"||mode=="psy_unwind"){
  allow_owned=true;withdraw_inside=true;throw_original=mode=="eq_throw";bool caught=false;
  try{if(mode=="vlb_unwind")mp4_vlb_draw_hook(source,source,source,source,nullptr);else if(mode=="psy_unwind")mp4_psyllium_execute_hook(source,{},source,nullptr);else mp4_equipment_late_hook(source,nullptr);}catch(const std::runtime_error&){caught=true;}
  assert(!mp4_stage_lease_active&&revokes==3&&ends==1&&old_writes==0&&caught==throw_original);
  assert(originals[mode=="vlb_unwind"?5:mode=="psy_unwind"?3:4]==1);return 0;
 }
 if(mode=="withdrawn")mp4_stage_withdraw_interception();
 invoke_all();for(int n:originals)assert(n==1);
 assert(scope_calls==0&&owner_queries==0&&ends==0);
 assert(mp4_stage_foreign_dirty.load()==(mode=="foreign_active"));
 assert(mp4_stage_host.configured); // Snapshot/resource ownership remains retained.
 return 0;
}
'''

@pytest.fixture(scope='module')
def stage_withdraw_binary(tmp_path_factory):
    compiler=os.environ.get('CXX')or shutil.which('g++')or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    if 'bool mp4_stage_hooks_intercept('not in source:pytest.skip('Logical Stage withdrawal not merged yet')
    names=('mp4_stage_hooks_intercept','mp4_stage_withdraw_interception','mp4_stage_invalidate','mp4_particle_simulate_hook','mp4_live_particle_simulate_hook','mp4_particle_control_simulate_hook','mp4_psyllium_execute_hook','mp4_equipment_late_hook','mp4_vlb_draw_hook')
    bodies='\n'.join(function(source,name)for name in names)
    directory=tmp_path_factory.mktemp('stage-logical-withdraw');cpp=directory/'withdraw.cpp';binary=directory/'withdraw'
    cpp.write_text(STAGE_WITHDRAW_PREFIX+bodies+STAGE_WITHDRAW_MAIN)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['withdrawn','foreign_active','foreign_inactive','selected_invalidate','foreign_invalidate','eq_unwind','vlb_unwind','eq_throw','psy_unwind'])
def test_shipping_stage_logical_interception_withdrawal(stage_withdraw_binary,mode):
    result=subprocess.run([str(stage_withdraw_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.fixture(scope='module')
def union_inventory_binary(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler required')
    actual = function((ROOT / 'client-presentation/native/bridge.cpp').read_text(), 'mp4_stage_refresh_inventory')
    model = r'''
#include "mp4_stage_state.hpp"
#include <cassert>
#include <map>
#include <string>
#include <vector>
namespace mp4stage=idoly_mp4_stage;
struct Host{
 struct Source{void*environment=nullptr;}source;
 size_t count=205;mp4stage::Owner owners[256]{};bool environment_particles[256]{};void*producer_particles[256]{};
}mp4_stage_host;
struct Array{std::vector<void*>items;}environment_array,equipment_array;
int environment,root_component,equipment;bool graphs_current=true;std::map<uint32_t,void*>handles;uint32_t next_handle=1;
bool mp4_stage_owner(void*){return true;}
bool mp4_stage_refresh_controls(){return graphs_current;}
void*mp4_stage_children(void*c){return c==&environment?&environment_array:c==&root_component?&equipment_array:nullptr;}
uint32_t mp4_retain(void*p){handles[next_handle]=p;return next_handle++;}
void*weak_get(uint32_t h){return handles.at(h);}void weak_free(uint32_t h){assert(handles.erase(h)==1);}
bool mp4_stage_array(void*p,void***values,size_t*count,size_t limit){auto*a=static_cast<Array*>(p);*count=a->items.size();*values=a->items.data();return *count<=limit;}
// ACTUAL
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];auto&h=mp4_stage_host;
 int systems[206]{};h.source.environment=&environment;
 for(size_t i=0;i<205;++i){h.owners[i].particle=&systems[i];h.owners[i].producer_kind=1;}
 if(mode=="environment_subset"||mode=="environment_removed"||mode=="environment_duplicate"){
  h.environment_particles[0]=true;environment_array.items={&systems[0]};}
 if(mode=="environment_removed")environment_array.items.clear();
 if(mode=="environment_duplicate")environment_array.items.push_back(&systems[0]);
 if(mode=="environment_added")environment_array.items={&systems[205]};
 if(mode=="timeline_moved_into_environment")environment_array.items={&systems[0]};
 if(mode=="unproved_graph")graphs_current=false;
 if(mode=="equipment"||mode=="equipment_ambiguous"){
  for(size_t i=0;i<2;++i){h.owners[i].producer_kind=2;h.owners[i].producer=&equipment;h.producer_particles[i]=&root_component;}
  equipment_array.items={&systems[0],&systems[1]};
  if(mode=="equipment_ambiguous")equipment_array.items.push_back(&systems[2]);
 }
 const bool accepted=mp4_stage_refresh_inventory();
 assert(accepted==(mode=="timeline_205"||mode=="environment_subset"||mode=="equipment"));assert(handles.empty());
}
'''
    directory = tmp_path_factory.mktemp('stage-particle-union')
    source, binary = directory / 'union.cpp', directory / 'union'
    source.write_text(model.replace('// ACTUAL', actual))
    result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g', '-O1',
        '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-I', str(ROOT / 'client-presentation/native'),
        str(source), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', ['timeline_205', 'environment_subset', 'environment_removed',
    'environment_duplicate', 'environment_added', 'timeline_moved_into_environment', 'unproved_graph',
    'equipment', 'equipment_ambiguous'])
def test_actual_particle_union_keeps_distinct_producer_membership(union_inventory_binary, mode):
    result = subprocess.run([str(union_inventory_binary), mode], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
