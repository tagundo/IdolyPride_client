"""Run the production Photo navigation protocol with a collecting fake runtime.

This extracts bridge functions rather than recreating their state machine. No
Unity scene, downloader, or physical device is executed by this fixture.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = source.index(name + "(")
    start = source.rfind("\n", 0, start) + 1
    begin = source.index("{", start)
    depth, end = 1, begin + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PRELUDE = r'''
#include "mp4_replay.hpp"
#include <cassert>
#include <atomic>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using Method=const void;
struct Class {const char* name;};
struct Object {
    alignas(uintptr_t) unsigned char raw[0x100]{};
    bool alive=true,marked=false,active=true,native_alive=true;
    std::string role;
    std::map<size_t,Object*> refs;
};
std::vector<std::unique_ptr<Object>> heap;
std::vector<Object*> static_roots,engine_roots;
std::map<uint32_t,Object*> handles;
std::vector<std::string> events;
uint32_t serial=1;
Class manager_class{"Solis.Common.SolisSceneManager"},wrong_class{"Wrong.Manager"};
Class transition_class{"Solis.Photography.Data.PhotographyLiveTransitionData"};
Class source_class{"Async.Source"},targets_class{"Download.Targets"};
Class presenter_class{"Solis.Photography.PhotographyLivePresenter"},mode_class{"Photo.Mode"},player_class{"Photo.Player"};
int instance_field,scene_field,allow_field,status_method,awaiter_method,result_method;
Object *current_manager=nullptr,*last_source=nullptr,*last_targets=nullptr,*last_data=nullptr;
int32_t scene_index=17,task_state=0;
uint8_t allow_load=1;
bool on_unity_thread=true,mp4_api_installed=true,mp4_photography_verified=true;
bool throw_probe=false,throw_targets=false,throw_pre_download=false,throw_status=false,throw_result=false,throw_set=false,throw_load=false;
bool targets_missing=false,source_null=false,task_value=true,factory_failure=false;
bool dispatch_is_paused=false,tick_cancel_command=false,tick_pause_command=false;
int retain_calls=0,retain_fail_at=-1,probe_calls=0,build_calls=0,targets_calls=0,preload_calls=0,status_calls=0,awaiter_calls=0,result_calls=0,set_calls=0,load_calls=0;
constexpr int16_t task_token=0x4321;

template<class T>T read(void* ptr,size_t offset){auto* o=static_cast<Object*>(ptr);assert(o&&o->alive);T v{};std::memcpy(&v,o->raw+offset,sizeof v);return v;}
template<class T>void write(Object* o,size_t offset,T value){assert(o&&o->alive);std::memcpy(o->raw+offset,&value,sizeof value);}
void ref(Object* o,size_t offset,Object* value){write(o,offset,value);o->refs[offset]=value;}
void mark(Object* o){if(!o||!o->alive||o->marked)return;o->marked=true;for(auto& r:o->refs)mark(r.second);}
void collect(){for(auto& o:heap)o->marked=false;for(auto* o:static_roots)mark(o);for(auto* o:engine_roots)mark(o);for(auto& h:handles)mark(h.second);for(auto& o:heap)if(!o->marked)o->alive=false;}
Object* allocate(Class* c,const char* role){collect();auto p=std::make_unique<Object>();Object* o=p.get();write(o,0,c);o->role=role;heap.push_back(std::move(p));return o;}
Object* permanent(Class* c,const char* role){Object* o=allocate(c,role);static_roots.push_back(o);return o;}
uint32_t mp4_retain(void* p){if(!p)return 0;auto* o=static_cast<Object*>(p);assert(o->alive);++retain_calls;if(retain_calls==retain_fail_at)return 0;handles[serial]=o;return serial++;}
void* weak_get(uint32_t h){auto i=handles.find(h);return i==handles.end()?nullptr:i->second;}
void weak_free(uint32_t h){assert(handles.erase(h)==1);collect();}
void* object_class(void* p){return read<Class*>(p,0);}
bool mp4_alive(void* p){return p&&static_cast<Object*>(p)->alive&&static_cast<Object*>(p)->native_alive;}
bool mp4_type_is(void* p,const char* name){return mp4_alive(p)&&!std::strcmp(static_cast<Class*>(object_class(p))->name,name);}
bool mp4_exact_type(void* p,const char* name){return mp4_type_is(p,name);}
bool game_call(bool=false){return on_unity_thread;}
bool mp4_prepare_runtime(){return mp4_api_installed&&on_unity_thread;}
// Native Actor/GL installers are separate services. This navigation fixture
// supplies their unavailable result and grants no graph or GPU capability.
bool mp4_prepare_actor_types(){return false;}
bool mp4_install_animation_root(){assert(false);return false;}
std::atomic<bool>mp4_gl_observer_published{false};
bool mp4_install_gl_observer(){return false;}

struct Factory {
    uint32_t owned=0;
    void clear(){if(owned)weak_free(owned);owned=0;}
    void* build_transition(const idoly_mp4_queue::PhotoSelection& p){assert(p.source_kind==1);++build_calls;events.push_back("build");clear();if(factory_failure)return nullptr;last_data=allocate(&transition_class,"transition");owned=mp4_retain(last_data);assert(owned);return last_data;}
    const char* error()const{return "fixture_factory_selection_failed";}
} factory;
Factory& mp4_photography_factory(){return factory;}
struct Weak {Object* value=nullptr;void* get(bool=false)const{return mp4_alive(value)?value:nullptr;}} mp4_photography_presenter;
namespace idoly_mp4_runtime {
uint64_t milliseconds(){return 1;}
// Observe diagnostics without changing navigation, GC custody or readiness.
void diagnostic_event(const char*stage,const char*code,uint64_t=0,uint64_t=0,bool=false){assert(stage&&code);}
struct Game {Object* selected=nullptr;bool built=false;void* selected_player(){return built?selected:nullptr;}} game;
void observe_presenter(void* p){assert(mp4_type_is(p,"Solis.Photography.PhotographyLivePresenter"));}
void observe_photography_transition(void* p,void* transition){assert(p==game.selected&&mp4_alive(transition));}
void observe_camera_controller(void*){assert(false);}
void on_unity_tick();
}
bool active_enabled(void* p,Method*){return mp4_alive(p)&&static_cast<Object*>(p)->active;}
struct Api {bool(*active_enabled)(void*,Method*)=nullptr;} mp4_api{active_enabled};
void* mp4_selected_controller(void*){return nullptr;}
'''


AFTER_STRUCTS = r'''
bool dispatch_paused(){return dispatch_is_paused;}
namespace idoly_mp4_runtime {void on_unity_tick(){if(tick_cancel_command){mp4_photography_cancel();tick_cancel_command=false;}dispatch_is_paused=tick_pause_command;}}
void static_get(const void* field,void* out){++probe_calls;if(throw_probe)throw std::runtime_error("static probe");if(field==&instance_field)std::memcpy(out,&current_manager,sizeof current_manager);else if(field==&scene_field)std::memcpy(out,&scene_index,sizeof scene_index);else if(field==&allow_field)std::memcpy(out,&allow_load,sizeof allow_load);else assert(false);}
void* download_targets(void* value,Method* info){assert(!info&&value==last_data&&mp4_alive(value));++targets_calls;events.push_back("targets");if(throw_targets)throw std::runtime_error("targets");if(targets_missing)return nullptr;last_targets=allocate(&targets_class,"targets");ref(last_targets,0x10,last_data);return last_targets;}
Mp4PhotographyBoolTask pre_download(void* targets,idoly_mp4_replay::CancellationToken8 ct,bool blocking,Method* info){assert(targets==last_targets&&mp4_alive(targets)&&ct.source==nullptr&&!blocking&&!info);++preload_calls;events.push_back("preload");if(throw_pre_download)throw std::runtime_error("preload");Mp4PhotographyBoolTask t{};t.result=task_value;t.padding=0x7a;t.token=task_token;if(!source_null){last_source=allocate(&source_class,"task-source");ref(last_source,0x10,last_targets);t.source=last_source;if(task_state==0)engine_roots.push_back(last_source);}return t;}
void validate_task(const Mp4PhotographyBoolTask* task){assert(task->token==task_token&&task->padding==0x7a);assert(reinterpret_cast<const uint8_t*>(task)[8]==task->result);int16_t token=0;std::memcpy(&token,reinterpret_cast<const uint8_t*>(task)+10,sizeof token);assert(token==task_token);if(task->source)assert(task->source==last_source&&mp4_alive(task->source));}
int32_t task_status(Mp4PhotographyBoolTask* task,Method* info){assert(info==&status_method);validate_task(task);++status_calls;events.push_back("status");if(throw_status)throw std::runtime_error("status");return task->source?task_state:1;}
Mp4PhotographyBoolTask task_awaiter(Mp4PhotographyBoolTask* task,Method* info){assert(info==&awaiter_method);validate_task(task);++awaiter_calls;events.push_back("awaiter");return *task;}
bool task_result(Mp4PhotographyBoolTask* task,Method* info){assert(info==&result_method);validate_task(task);assert(!task->source||task_state!=0);++result_calls;events.push_back("result");if(throw_result||(task->source&&(task_state==2||task_state==3)))throw std::runtime_error("task result");return task->source?task_value:task->result;}
void set_data(void* manager,void* data,Method* info){assert(!info&&manager==current_manager&&mp4_alive(manager)&&data==last_data&&mp4_alive(data));++set_calls;events.push_back("set-data");if(throw_set)throw std::runtime_error("set-data");ref(static_cast<Object*>(manager),0x28,static_cast<Object*>(data));}
void load_scene(void* manager,int32_t scene,int32_t mode,Method* info){assert(!info&&manager==current_manager&&scene==scene_index&&mode==0);assert(read<Object*>(manager,0x28)==last_data);assert(!events.empty()&&events.back()=="set-data");++load_calls;events.push_back("load");if(throw_load)throw std::runtime_error("load");}
void finish(int32_t status,bool value){task_state=status;task_value=value;engine_roots.clear();collect();}
void original_built_generation(bool built,bool newer){if(newer)++mp4_photography_navigation.generation;idoly_mp4_runtime::game.built=built;mp4_observe_photography_presenter();}
void setup(){
    current_manager=permanent(&manager_class,"manager");
    auto& n=mp4_photography_navigation;n.manager_class=&manager_class;n.instance_field=&instance_field;n.scene_field=&scene_field;n.allow_field=&allow_field;n.static_get=static_get;n.set_data=set_data;n.load_scene=load_scene;n.download_targets=download_targets;n.pre_download=pre_download;n.task_status=task_status;n.task_awaiter=task_awaiter;n.task_result=task_result;n.status_info=&status_method;n.awaiter_info=&awaiter_method;n.result_info=&result_method;n.dispatch_paused=dispatch_paused;n.configured=true;n.generation=5;std::strcpy(n.error,"none");
    Object* presenter=permanent(&presenter_class,"presenter");Object* mode=permanent(&mode_class,"mode");Object* player=permanent(&player_class,"player");Object* transition=permanent(&transition_class,"observed-transition");ref(presenter,0x30,mode);ref(mode,0x30,transition);mp4_photography_presenter.value=presenter;idoly_mp4_runtime::game.selected=player;
}
idoly_mp4_queue::PhotoSelection selection(){idoly_mp4_queue::PhotoSelection p{};p.source_kind=1;return p;}
void inputs_released(){const auto& n=mp4_photography_navigation;assert(!n.manager_handle&&!n.transition_handle&&!n.targets_handle&&!n.source_handle);assert(!n.task.source);assert(handles.size()==(factory.owned?1u:0u));}
void error(const char* text){assert(!std::strcmp(mp4_photography_navigation.error,text));}
void probe(const std::string& mode){
    if(mode=="unverified")mp4_photography_verified=false;else if(mode=="unconfigured")mp4_photography_navigation.configured=false;else if(mode=="api")mp4_api_installed=false;else if(mode=="thread")on_unity_thread=false;else if(mode=="pending")mp4_photography_navigation.pending=true;else if(mode=="failed")mp4_photography_navigation.failed=true;else if(mode=="missing-manager")current_manager=nullptr;else if(mode=="wrong-manager")write(current_manager,0,&wrong_class);else if(mode=="dead-manager")current_manager->native_alive=false;else if(mode=="allow-false")allow_load=0;else if(mode=="allow-invalid")allow_load=2;else if(mode=="scene-negative")scene_index=-1;else if(mode=="scene-overflow")scene_index=65536;else if(mode=="throws")throw_probe=true;else assert(false);
    for(int i=0;i<3;++i)assert(!mp4_photography_can_route());assert(build_calls==0&&preload_calls==0&&set_calls==0&&load_calls==0&&heap.size()==5&&handles.empty());
}
void success(const std::string& mode){
    source_null=mode=="immediate";assert(mp4_photography_can_route());assert(mp4_photography_open(selection()));assert(preload_calls==1&&load_calls==0);assert(!mp4_photography_open(selection())&&build_calls==1);auto& n=mp4_photography_navigation;
    if(!source_null){collect();assert(last_source->alive&&last_targets->alive&&last_data->alive);for(int i=0;i<3;++i)mp4_advance_photography_navigation();assert(result_calls==0&&load_calls==0);finish(1,true);}
    mp4_advance_photography_navigation();assert(result_calls==1&&awaiter_calls==1&&set_calls==1&&load_calls==1&&n.pending&&n.phase==2);assert(n.task_consumed);error("none");inputs_released();
    for(int i=0;i<3;++i)mp4_advance_photography_navigation();assert(result_calls==1&&load_calls==1&&!mp4_photography_can_route());
    original_built_generation(true,false);assert(n.pending);original_built_generation(false,true);assert(n.pending);original_built_generation(true,false);assert(!n.pending&&mp4_photography_can_route());
}
void recoverable(const std::string& mode){
    if(mode=="source-null-false"){source_null=true;task_value=false;}assert(mp4_photography_open(selection()));
    if(mode=="false")finish(1,false);else if(mode=="fault")finish(2,false);else if(mode=="task-cancel")finish(3,false);else if(mode=="get-result-throw"){throw_result=true;finish(1,true);}else if(mode=="status-throw"){throw_status=true;finish(1,true);}else if(mode=="invalid-status")finish(8,true);else assert(mode=="source-null-false");
    mp4_advance_photography_navigation();assert(load_calls==0&&set_calls==0&&!mp4_photography_navigation.pending&&!mp4_photography_navigation.failed);inputs_released();
    const char* expected=(mode=="false"||mode=="source-null-false")?"photography_asset_preparation_failed":mode=="invalid-status"?"photography_asset_task_status_invalid":"photography_asset_preparation_exception";error(expected);assert(mp4_photography_can_route());error(expected);
    int previous=result_calls;for(int i=0;i<3;++i)mp4_advance_photography_navigation();assert(result_calls==previous);assert(previous==((mode=="status-throw"||mode=="invalid-status")?0:1));
    // A failed preload must allow a fresh manual retry rather than latching.
    throw_result=throw_status=false;source_null=true;task_value=true;assert(mp4_photography_open(selection()));mp4_advance_photography_navigation();assert(load_calls==1&&result_calls==previous+1);inputs_released();
}
void cancel(const std::string& mode){
    if(mode=="before-open"){mp4_photography_cancel();assert(!mp4_photography_navigation.cancel_requested);source_null=true;assert(mp4_photography_open(selection()));}
    else {assert(mp4_photography_open(selection()));mp4_photography_cancel();assert(mp4_photography_navigation.cancel_requested);for(int i=0;i<3;++i)mp4_advance_photography_navigation();assert(result_calls==0&&load_calls==0);finish(mode=="fault-after-cancel"?2:1,true);}
    if(mode=="before-open")mp4_photography_cancel();mp4_advance_photography_navigation();assert(result_calls==1&&load_calls==0&&!mp4_photography_navigation.pending&&!mp4_photography_navigation.failed);error("none");inputs_released();assert(mp4_photography_can_route());mp4_advance_photography_navigation();assert(result_calls==1);
}
void scope_changed(const std::string& mode){
    assert(mp4_photography_open(selection()));finish(1,true);
    if(mode=="generation")++mp4_photography_navigation.generation;else if(mode=="generation-built"){original_built_generation(true,true);assert(mp4_photography_navigation.pending&&mp4_photography_navigation.phase==1);}else if(mode=="manager")current_manager=permanent(&manager_class,"new-manager");else if(mode=="allow")allow_load=0;else if(mode=="scene")scene_index=-1;else if(mode=="manager-dead")current_manager->native_alive=false;else if(mode=="manager-class")write(current_manager,0,&wrong_class);else if(mode=="probe-throw")throw_probe=true;else assert(false);
    mp4_advance_photography_navigation();assert(result_calls==1&&load_calls==0&&set_calls==0&&!mp4_photography_navigation.pending&&!mp4_photography_navigation.failed);inputs_released();error(mode=="probe-throw"?"photography_navigation_probe_exception":"photography_navigation_scope_changed");mp4_advance_photography_navigation();assert(result_calls==1);
}
void load_failure(const std::string& mode){
    source_null=true;throw_load=mode=="load";throw_set=mode=="set";assert(mp4_photography_open(selection()));mp4_advance_photography_navigation();auto& n=mp4_photography_navigation;assert(n.failed&&!n.pending&&result_calls==1);inputs_released();error("photography_scene_load_exception");assert(!mp4_photography_can_route());
    original_built_generation(true,false);assert(n.failed);original_built_generation(false,true);assert(n.failed);original_built_generation(true,false);assert(!n.failed&&mp4_photography_can_route());error("none");
    throw_load=throw_set=false;assert(mp4_photography_open(selection()));mp4_advance_photography_navigation();assert(!n.failed&&n.pending&&result_calls==2);inputs_released();
}
void open_failure(const std::string& mode){
    if(mode=="factory")factory_failure=true;else if(mode=="targets-null")targets_missing=true;else if(mode=="targets-throw")throw_targets=true;else if(mode=="predownload-throw")throw_pre_download=true;else if(mode=="manager-handle")retain_fail_at=2;else if(mode=="transition-handle")retain_fail_at=3;else if(mode=="targets-handle")retain_fail_at=4;else if(mode=="source-handle")retain_fail_at=5;else assert(false);
    assert(!mp4_photography_open(selection()));assert(set_calls==0&&load_calls==0);inputs_released();const auto& n=mp4_photography_navigation;assert(!n.pending);
    if(mode=="source-handle"){assert(n.failed&&!mp4_photography_can_route()&&last_source->alive);error("photography_asset_task_handle_failed");finish(1,true);mp4_advance_photography_navigation();assert(result_calls==0&&load_calls==0);original_built_generation(true,true);assert(mp4_photography_can_route());}
    else {assert(!n.failed&&mp4_photography_can_route());if(mode=="factory")error("fixture_factory_selection_failed");else if(mode=="manager-handle"||mode=="transition-handle")error("photography_navigation_handle_failed");else if(mode=="targets-null"||mode=="targets-handle")error("photography_asset_targets_unavailable");else error("photography_asset_preparation_exception");}
}
void prepared_roots(){const auto& n=mp4_photography_navigation;assert(n.pending&&n.phase==3&&n.task_consumed&&!n.source_handle&&!n.targets_handle&&!n.task.source&&n.manager_handle&&n.transition_handle);assert(handles.size()==3&&last_data->alive&&!last_targets->alive);if(last_source)assert(!last_source->alive);assert(result_calls==1&&load_calls==0);}
void paused(const std::string& mode){
    const bool asynchronous=mode=="async"||mode=="cancel-prepared";source_null=!asynchronous;dispatch_is_paused=true;assert(mp4_photography_open(selection()));
    if(asynchronous){for(int i=0;i<3;++i)mp4_advance_photography_navigation();assert(result_calls==0&&load_calls==0);finish(1,true);}mp4_advance_photography_navigation();prepared_roots();const int polls=status_calls;
    for(int i=0;i<3;++i)mp4_advance_photography_navigation();prepared_roots();assert(status_calls==polls&&!mp4_photography_can_route());
    if(mode=="cancel-prepared"){mp4_photography_cancel();mp4_advance_photography_navigation();assert(!mp4_photography_navigation.pending&&load_calls==0&&result_calls==1);inputs_released();error("none");assert(mp4_photography_can_route());}
    else {dispatch_is_paused=false;mp4_advance_photography_navigation();assert(load_calls==1&&set_calls==1&&result_calls==1&&status_calls==polls);inputs_released();mp4_advance_photography_navigation();assert(load_calls==1&&result_calls==1);}
}
void same_tick_commands(const std::string& mode){source_null=true;assert(mp4_photography_open(selection()));if(mode=="cancel")tick_cancel_command=true;else if(mode=="pause")tick_pause_command=true;else assert(false);mp4_unity_tick();assert(result_calls==1&&load_calls==0);if(mode=="cancel"){assert(!mp4_photography_navigation.pending&&mp4_photography_can_route());inputs_released();}else{prepared_roots();tick_pause_command=false;mp4_unity_tick();assert(load_calls==1&&result_calls==1);inputs_released();}}
int main(int argc,char** argv){assert(argc==3);setup();const std::string group=argv[1],mode=argv[2];if(group=="probe")probe(mode);else if(group=="success")success(mode);else if(group=="recoverable")recoverable(mode);else if(group=="cancel")cancel(mode);else if(group=="scope")scope_changed(mode);else if(group=="load-failure")load_failure(mode);else if(group=="open-failure")open_failure(mode);else if(group=="paused")paused(mode);else if(group=="tick-commands")same_tick_commands(mode);else assert(false);mp4_release_photography_navigation_inputs();factory.clear();engine_roots.clear();collect();assert(handles.empty());}
'''


@pytest.fixture(scope="module")
def navigation_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    structs = bridge.split("struct Mp4PhotographyBoolTask", 1)[1].split("char mp4_photography_binding_error", 1)[0]
    block = bridge.split("// BEGIN_MP4_PHOTOGRAPHY_NAVIGATION", 1)[1].split("// END_MP4_PHOTOGRAPHY_NAVIGATION", 1)[0]
    observer = function(bridge, "mp4_observe_photography_presenter")
    tick = function(bridge, "mp4_unity_tick")
    source = PRELUDE + "\nstruct Mp4PhotographyBoolTask" + structs + "\n" + block + "\n" + observer + "\n" + tick + "\n" + AFTER_STRUCTS
    build = tmp_path_factory.mktemp("mp4-photography-navigation")
    cpp, executable = build / "navigation.cpp", build / "navigation"
    cpp.write_text(source)
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
         "-I", str(ROOT / "client-presentation/native"), str(cpp), "-o", str(executable)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


SCENARIOS = {
    "probe": ["unverified", "unconfigured", "api", "thread", "pending", "failed", "missing-manager",
              "wrong-manager", "dead-manager", "allow-false", "allow-invalid", "scene-negative", "scene-overflow", "throws"],
    "success": ["immediate", "asynchronous"],
    "recoverable": ["source-null-false", "false", "fault", "task-cancel", "get-result-throw", "status-throw", "invalid-status"],
    "cancel": ["before-open", "pending", "fault-after-cancel"],
    "scope": ["generation", "generation-built", "manager", "allow", "scene", "manager-dead", "manager-class", "probe-throw"],
    "load-failure": ["set", "load"],
    "open-failure": ["factory", "targets-null", "targets-throw", "predownload-throw",
                     "manager-handle", "transition-handle", "targets-handle", "source-handle"],
    "paused": ["immediate", "async", "cancel-prepared"],
    "tick-commands": ["cancel", "pause"],
}


@pytest.mark.parametrize("group,scenario", [(g, s) for g, ss in SCENARIOS.items() for s in ss])
def test_original_photography_navigation_protocol(navigation_binary, group, scenario):
    result = subprocess.run([str(navigation_binary), group, scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
