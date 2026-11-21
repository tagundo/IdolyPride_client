"""Original GameTime protocol, with explicit held-clock/dependent-state proofs.

The protocol is production code; original native graph/job/GPU execution is not
claimed by the synthetic state callbacks. The optional original audit rebuilds
every committed binding from the pinned clients rather than a copied table.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/"client-presentation/native"
HARNESS=r'''
#include "mp4_playback_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
#include <vector>
namespace p=idoly_mp4_playback;
struct Graph {void* handle=nullptr;int version=0,padding=0;};
struct Scene {
    int player=0,director=0;bool owner=true,playing=true,paused=false;
    int state=1,mode=0,version=1;double time=13.25;
    int history=37,saved_history=0;float volume=.6f,saved_volume=0;
    unsigned sets=0,evaluates=0,rebuilds=0,captures=0,prepares=0,resets=0,restores=0,releases=0,quiesces=0;
    unsigned pending_jobs=1;bool quiesce_ready=true;
    bool fence=true,reset_ready=true,restore_ready=true,release_ready=true,rebuild_ready=true,exclusive=true;
    bool source_ready=true;unsigned verifications=0;bool fail_reset=false,old_valid=false;bool released_owned=true;
    std::string switch_on;std::vector<std::string> calls;
} s;
void primary(){assert(s.owner&&"no original scene read/write after identity loss");}
void event(const char* name){
    primary();s.calls.emplace_back(name);
    if(s.switch_on==name){s.owner=false;s.state=0;s.mode=2;s.time=77;s.history=88;s.volume=.8f;s.playing=false;s.paused=true;}
}
int32_t state(void*,void*){primary();return s.state;}
int32_t mode(void*,void*){primary();return s.mode;}
void setmode(void*,int32_t value,void*){primary();s.mode=value;event("mode");}
double time(void*,void*){primary();return s.time;}
void settime(void*,double value,void*){primary();++s.sets;s.time=value;event("time");}
void evaluate(void*,void*){primary();++s.evaluates;s.history=-200;event("evaluate");}
void graph(void*,Graph* value,void*){primary();*value={&s.director,s.version,0};}
bool valid(Graph* value,void*){return value->handle==&s.director&&(value->version==s.version||s.old_valid);}
void play(void*,void*){primary();s.state=1;event("play");}
void pause(void*,void*){primary();s.state=0;event("pause");}
void resume(void*,void*){primary();s.state=1;event("resume");}
void rebuild(void*,void*){primary();assert(!s.pending_jobs);++s.rebuilds;if(s.rebuild_ready){++s.version;s.history=0;}event("rebuild");}
bool playing(void*,void*){primary();return s.playing;}
bool paused(void*,void*){primary();return s.paused;}
void setplaying(void*,bool value,void*){primary();s.playing=value;event("playing_flag");}
void setpaused(void*,bool value,void*){primary();s.paused=value;event("paused_flag");}
bool current(void* context){assert(context==&s);return s.owner;}
p::Result quiesce(void*){primary();++s.quiesces;if(!s.quiesce_ready)return p::Result::waiting;s.pending_jobs=0;event("quiesce");return p::Result::ok;}
p::Result capture(void*){primary();assert(!s.pending_jobs);++s.captures;if(!s.fence)return p::Result::waiting;s.saved_history=s.history;s.saved_volume=s.volume;event("capture");return p::Result::ok;}
p::Result prepare(void*){primary();++s.prepares;s.volume=0;event("prepare");return p::Result::ok;}
p::Result reset(void*){primary();++s.resets;if(!s.reset_ready)return p::Result::waiting;if(s.fail_reset)return p::Result::unsupported;s.history=0;event("reset");return p::Result::ok;}
p::Result restore(void*){primary();++s.restores;if(!s.restore_ready)return p::Result::waiting;s.history=s.saved_history;s.volume=s.saved_volume;event("restore");return p::Result::ok;}
p::Result release(void*,bool owned){++s.releases;s.released_owned=owned;if(!s.release_ready)return p::Result::waiting;s.calls.emplace_back("release");return p::Result::ok;}
p::Result verify_source(void*){primary();++s.verifications;assert(s.time==13.25&&s.history==s.saved_history&&s.volume==s.saved_volume);assert(!s.calls.empty()&&(s.verifications>1||s.calls.back()=="paused_flag"));return s.source_ready?p::Result::ok:p::Result::waiting;}
const char* dependent_error(void*){return s.fail_reset?"actor_history_unverified":"actor_fence_pending";}
p::OriginalApi<Graph> api(){
    p::OriginalApi<Graph> a{};a.director_state=state;a.director_mode=mode;a.director_set_mode=setmode;
    a.director_time=time;a.director_set_time=settime;a.director_evaluate=evaluate;a.director_graph=graph;a.graph_valid=valid;
    a.director_play=play;a.director_pause=pause;a.director_resume=resume;a.director_rebuild=rebuild;
    a.player_playing=playing;a.player_paused=paused;a.player_set_playing=setplaying;a.player_set_paused=setpaused;return a;
}
p::Dependents dependents(){return {current,quiesce,capture,prepare,reset,restore,release,dependent_error,verify_source};}
int main(int argc,char** argv){
    assert(argc==2);std::string scenario=argv[1];p::Scope<Graph> scope;
    if(scenario=="paused"){s.state=0;s.paused=true;}
    if(scenario=="not_started"){s.state=0;s.playing=false;}
    const int source_state=s.state,source_mode=s.mode;const bool source_playing=s.playing,source_paused=s.paused;
    auto a=api();auto d=dependents();if(scenario=="missing_dependency")d.capture=nullptr;
    if(scenario=="missing_quiesce")d.quiesce=nullptr;
    if(scenario=="missing_source_verify")d.verify_source_restored=nullptr;
    if(scenario=="missing_api")a.director_rebuild=nullptr;
    assert(scope.install(a,d));
    if(scenario=="clock_unowned"||scenario=="clock_not_held"){
        assert(scope.acquire(&s.player,&s.director,&s,{scenario!="clock_unowned",false})==p::Result::waiting);
        assert(!scope.active()&&s.calls.empty()&&s.captures==0);return 0;
    }
    if(scenario=="missing_dependency"||scenario=="missing_api"||scenario=="missing_quiesce"||scenario=="missing_source_verify"){
        assert(scope.acquire(&s.player,&s.director,&s,{true,true})==p::Result::unsupported);
        assert(!scope.active()&&s.calls.empty()&&s.captures==0);return 0;
    }
    if(scenario=="capture_wait"||scenario=="cancel_capture")s.fence=false;
    if(scenario=="quiesce_wait")s.quiesce_ready=false;
    if(scenario=="owner_capture")s.switch_on="capture";
    auto result=scope.acquire(&s.player,&s.director,&s,{true,true});
    if(scenario=="quiesce_wait"){
        assert(result==p::Result::waiting&&scope.active()&&s.captures==0&&s.pending_jobs==1&&s.prepares==0);
        s.quiesce_ready=true;result=scope.acquire(&s.player,&s.director,&s,{true,true});
    }
    if(scenario=="owner_capture"){
        assert(result==p::Result::stale&&scope.active());assert(scope.restore({false,false})==p::Result::stale&&!scope.active());
        assert(!s.released_owned&&s.time==77&&s.history==88&&s.volume==.8f);return 0;
    }
    if(scenario=="capture_wait"||scenario=="cancel_capture"){
        assert(result==p::Result::waiting&&scope.active()&&s.time==13.25&&s.state==source_state&&s.volume==.6f&&s.prepares==0);
        if(scenario=="cancel_capture"){assert(scope.restore({true,true})==p::Result::ok&&!scope.active()&&s.sets==0&&s.rebuilds==0);return 0;}
        s.fence=true;result=scope.acquire(&s.player,&s.director,&s,{true,true});assert(s.captures==2);
    }
    assert(result==p::Result::ok&&scope.phase()==p::Phase::held&&s.state==0&&s.paused&&s.volume==0);
    assert(scope.snapshot().state==source_state&&scope.snapshot().time==13.25);
    if(scenario=="cancel_held"){assert(scope.restore({true,true})==p::Result::ok&&!scope.active());assert(s.time==13.25&&s.state==source_state&&s.history==37&&s.volume==.6f);return 0;}
    if(scenario=="rebuild_wait")s.rebuild_ready=false;
    if(scenario=="reset_wait"||scenario=="reset_graph_changed")s.reset_ready=false;
    if(scenario=="reset_unsupported")s.fail_reset=true;
    if(scenario=="owner_rebuild")s.switch_on="rebuild";
    result=scope.start({true,true});
    if(scenario=="owner_rebuild"){
        assert(result==p::Result::stale&&scope.restore({false,false})==p::Result::stale&&!scope.active());
        assert(!s.released_owned&&s.time==77&&s.history==88);return 0;
    }
    if(scenario=="rebuild_wait"){
        assert(result==p::Result::waiting&&s.rebuilds==1&&s.resets==0);s.rebuild_ready=true;result=scope.start({true,true});assert(s.rebuilds==2);
    }
    if(scenario=="reset_wait"){
        assert(result==p::Result::waiting&&s.rebuilds==1&&s.sets==0);s.reset_ready=true;result=scope.start({true,true});assert(s.rebuilds==1);
    }
    if(scenario=="reset_graph_changed"){
        // A native fence/reset can wait while another original callback
        // replaces this same director's graph. Do not call reset again.
        assert(result==p::Result::waiting&&s.resets==1);++s.version;s.reset_ready=true;
        assert(scope.start({true,true})==p::Result::stale&&s.resets==1);
        assert(scope.restore({true,true})==p::Result::stale&&!scope.active()&&!s.released_owned);return 0;
    }
    if(scenario=="reset_unsupported"){
        assert(result==p::Result::unsupported&&!std::strcmp(scope.error(),"actor_history_unverified"));
        assert(scope.restore({true,true})==p::Result::ok&&!scope.active()&&s.history==37&&s.time==13.25);return 0;
    }
    assert(result==p::Result::ok&&scope.playing()&&s.mode==1&&s.state==1&&s.playing&&!s.paused&&s.time==0);
    const auto sets=s.sets,evaluates=s.evaluates;
    for(int frame=0;frame<120;++frame){s.time=frame/60.;assert(scope.validate_frame(s.time)==p::Result::ok);s.history=frame;}
    assert(s.sets==sets&&s.evaluates==evaluates&&sets==1&&evaluates==0);
    if(scenario=="abandon"||scenario=="abandon_wait"){
        const auto calls=s.calls.size();const auto quiesces=s.quiesces,rebuilds=s.rebuilds;
        s.owner=false;s.time=88;s.history=99;
        if(scenario=="abandon_wait"){
            s.release_ready=false;assert(scope.abandon()==p::Result::waiting&&scope.active());s.release_ready=true;
        }
        assert(scope.abandon()==p::Result::stale&&!scope.active()&&!s.released_owned);
        assert(s.quiesces==quiesces&&s.rebuilds==rebuilds&&s.calls.size()==calls+1&&s.time==88&&s.history==99);
        assert(scope.abandon()==p::Result::ok);return 0;
    }
    if(scenario=="wrong_time"){assert(scope.validate_frame(9)==p::Result::failed&&!std::strcmp(scope.error(),"original_playback_frame_time_mismatch"));}
    if(scenario=="changed_graph"){
        ++s.version;s.time=66;s.history=77;s.volume=.9f;
        assert(scope.validate_frame(0)==p::Result::stale);
        const auto before=s.calls.size();assert(scope.restore({true,true})==p::Result::stale&&!scope.active());
        assert(s.calls.size()==before+1&&!s.released_owned&&s.time==66&&s.history==77&&s.volume==.9f);return 0;
    }
    if(scenario=="changed_owner"){
        s.owner=false;s.time=66;s.history=77;s.volume=.9f;assert(scope.restore({false,false})==p::Result::stale&&!scope.active());
        assert(!s.released_owned&&s.time==66&&s.history==77&&s.volume==.9f);return 0;
    }
    if(scenario=="restore_wait")s.restore_ready=false;
    if(scenario=="source_verify_wait")s.source_ready=false;
    if(scenario=="restore_quiesce_wait"){s.quiesce_ready=false;s.pending_jobs=3;}
    if(scenario=="release_wait")s.release_ready=false;
    if(scenario=="owner_restore_evaluate")s.switch_on="evaluate";
    result=scope.restore({true,true});
    if(scenario=="restore_quiesce_wait"){
        assert(result==p::Result::waiting&&scope.active()&&s.pending_jobs==3&&s.rebuilds==1&&s.restores==0);
        s.quiesce_ready=true;result=scope.restore({true,true});assert(!s.pending_jobs);
    }
    if(scenario=="owner_restore_evaluate"){
        assert(result==p::Result::stale&&!scope.active()&&!s.released_owned&&s.history==88&&s.time==77);return 0;
    }
    if(scenario=="restore_wait"){
        assert(result==p::Result::waiting&&scope.active()&&s.rebuilds==2&&s.restores==1);
        s.restore_ready=true;result=scope.restore({true,true});assert(s.rebuilds==2&&s.restores==2);
    }
    if(scenario=="source_verify_wait"){
        assert(result==p::Result::waiting&&scope.active()&&s.rebuilds==2&&s.restores==1&&s.verifications==1);
        const auto prior=s.calls.size();s.source_ready=true;result=scope.restore({true,true});
        assert(s.calls.size()==prior+2&&s.rebuilds==2&&s.restores==1&&s.verifications==2);
    }
    if(scenario=="release_wait"){
        assert(result==p::Result::waiting&&scope.active()&&s.rebuilds==2&&s.restores==1);
        const auto prior=s.calls.size();s.release_ready=true;result=scope.restore({true,true});
        assert(s.calls.size()==prior+1&&s.rebuilds==2&&s.restores==1&&s.releases==2);
    }
    assert(result==p::Result::ok&&!scope.active()&&s.time==13.25&&s.state==source_state&&s.mode==source_mode);
    assert(s.playing==source_playing&&s.paused==source_paused&&s.history==37&&s.volume==.6f&&s.released_owned);
    assert(scope.restore({false,false})==p::Result::ok);
}
'''


@pytest.fixture(scope="module")
def playback_binary(tmp_path_factory):
    compiler=shutil.which("c++")or shutil.which("g++")or shutil.which("clang++")
    if not compiler:pytest.skip("C++ compiler required")
    directory=tmp_path_factory.mktemp("mp4-playback-state");source=directory/"state.cpp";binary=directory/"state"
    source.write_text(HARNESS)
    built=subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-I",str(NATIVE),str(source),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    return binary


@pytest.mark.parametrize("scenario",["playing","paused","not_started","abandon","abandon_wait","clock_unowned","clock_not_held",
    "missing_dependency","missing_api","missing_quiesce","missing_source_verify","source_verify_wait","quiesce_wait","capture_wait","cancel_capture","cancel_held","owner_capture",
    "rebuild_wait","reset_wait","reset_graph_changed","reset_unsupported","owner_rebuild","wrong_time","changed_graph",
    "changed_owner","restore_quiesce_wait","restore_wait","release_wait","owner_restore_evaluate"])
def test_original_game_time_held_clock_dependent_closure_and_restoration(playback_binary,scenario):
    ran=subprocess.run([str(playback_binary),scenario],capture_output=True,text=True,timeout=5)
    assert ran.returncode==0,ran.stdout+ran.stderr


def generator():
    sys.path.insert(0,str(ROOT/"tools"))
    spec=importlib.util.spec_from_file_location("mp4_playback_profile_audit",ROOT/"tools/audit_mp4_playback_state.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_profile_is_deterministically_embedded_and_uses_original_byte_flags():
    audit=generator();profile=json.loads((NATIVE/"mp4_playback_state_profile.json").read_text())
    source=(NATIVE/"mp4_playback_state.hpp").read_text()
    assert audit.render(profile["platforms"])in source
    assert len(audit.SELECT)==9
    for platform in ("android","ios"):
        p=profile["platforms"][platform]
        assert set(p["methods"])==set(audit.SELECT)
        assert [row["offset"]for row in p["fields"].values()]==[0x70,0x71,0x72]
        assert {key:row["value"]for key,row in p["enums"].items()}=={"game_time":1,"paused":0,"playing":1}
        assert p["scope"]["automatic_export_permitted_without_verified_dependent_state"]is False
        assert "Stop"not in [row["name"]for row in p["methods"].values()]


@pytest.mark.parametrize("platform",["android","ios"])
def test_playback_bindings_match_complete_originals_when_supplied(platform):
    directory=os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:pytest.skip("Set IDOLY_MP4_ORIGINALS_DIR for actual original audit")
    audit=generator();base=Path(directory)
    constructor=audit.OriginalAndroid if platform=="android"else audit.Original
    metadata,native=("android-metadata.dat","android-native.so")if platform=="android"else("ios-metadata.dat","ios-native.bin")
    actual=audit.profile(constructor((base/metadata).read_bytes(),(base/native).read_bytes()),platform)
    expected=json.loads((NATIVE/"mp4_playback_state_profile.json").read_text())["platforms"][platform]
    assert actual==expected
