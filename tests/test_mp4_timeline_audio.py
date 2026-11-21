"""Compile the production selected-timeline audio ownership and clock guard.

This models original API boundaries and typed layouts, not Unity execution.
The pinned native and cached-asset audits independently prove their contracts.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_timeline_audio.hpp"
#include <cassert>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <stdexcept>
#include <vector>
using namespace idoly_mp4_timeline_audio;
struct Object {
    alignas(16) unsigned char bytes[512]{};
    std::string type,name; bool live=true,null_data=false;
    size_t reported=0; double duration=122;
    Object *asset=nullptr,*go=nullptr,*tracks=nullptr,*clips=nullptr;
    bool muted=false,active=true;
    std::vector<void*> entries;
    void* p(){return bytes;}
};
std::vector<std::unique_ptr<Object>> heap;
std::map<void*,Object*> lookup;
std::map<std::pair<void*,int>,std::pair<bool,Object*>> references;
int reference_calls=0;bool throw_reference=false;
Object* make(const char* type,const char* name="") {
    heap.emplace_back(new Object);auto* o=heap.back().get();o->type=type;o->name=name;lookup[o->p()]=o;return o;
}
template<class T>void put(Object* o,size_t offset,T v){std::memcpy(o->bytes+offset,&v,sizeof v);}
Object* array(const char* type,std::initializer_list<Object*> entries) {
    auto* o=make(type);for(auto* e:entries)o->entries.push_back(e?e->p():nullptr);o->reported=o->entries.size();return o;
}
bool type(void* p,const char* name){auto i=lookup.find(p);return i!=lookup.end()&&i->second->type==name;}
bool live(void* p){auto i=lookup.find(p);return i!=lookup.end()&&i->second->live;}
size_t length(void* p){assert(lookup.count(p));return lookup[p]->reported;}
void* data(void* p){assert(lookup.count(p));auto* o=lookup[p];return o->null_data?nullptr:o->entries.data();}
void* asset(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Playables.PlayableDirector"));auto* o=lookup[p]->asset;return o?o->p():nullptr;}
void* tracks(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Timeline.TimelineAsset"));auto* o=lookup[p]->tracks;return o?o->p():nullptr;}
void* clips(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Timeline.ControlTrack"));auto* o=lookup[p]->clips;return o?o->p():nullptr;}
void* name(void* p,Method* m){assert(!m&&lookup.count(p));return p;}
size_t utf8(void* p,char* out,size_t size){assert(lookup.count(p));const auto& n=lookup[p]->name;if(n.size()<size)std::memcpy(out,n.c_str(),n.size()+1);return n.size();}
void* reference(void* p,PropertyName4 id,bool* valid,Method* m) {
    ++reference_calls;if(throw_reference)throw std::runtime_error("original reference failed");assert(!m&&valid&&type(p,"UnityEngine.Playables.PlayableDirector"));
    auto i=references.find({p,id.id});if(i==references.end()){*valid=false;return nullptr;}
    *valid=i->second.first;return i->second.second?i->second.second->p():nullptr;
}
void* game_object(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Playables.PlayableDirector"));auto* o=lookup[p]->go;return o?o->p():nullptr;}
bool muted(void* p,Method* m){assert(!m&&lookup.count(p));return lookup[p]->muted;}
bool active(void* p,Method* m){assert(!m&&lookup.count(p));return lookup[p]->active;}
double duration(void* p,Method* m){assert(!m&&type(p,"UnityEngine.Playables.PlayableDirector"));return lookup[p]->duration;}
Api api(){return {{type,live,length,data,asset,tracks,nullptr,nullptr},clips,name,utf8,reference,game_object,muted,duration,active};}
Object *timeline,*list,*owned_array,*master,*audio,*other,*control_track,*control_clip,*control_asset,*root_tracks,*audio_tracks,*bgm,*voice;
void director(Object*& out,const char* n) {
    out=make("UnityEngine.Playables.PlayableDirector",n);out->go=make("UnityEngine.GameObject",n);
    out->asset=make("UnityEngine.Timeline.TimelineAsset");out->asset->tracks=array("UnityEngine.Timeline.TrackAsset[]",{});
}
Object* add_control(Object* from,Object* to,int key) {
    auto* track=make("UnityEngine.Timeline.ControlTrack");auto* clip=make("UnityEngine.Timeline.TimelineClip");
    auto* control=make("UnityEngine.Timeline.ControlPlayableAsset");put(clip,0x28,control->p());
    put(clip,0x18,0.0);put(clip,0x20,0.0);put(clip,0x30,122.0);put(clip,0x38,1.0);
    put(control,0x18,int32_t(key));put(control,0x38,uint8_t(1));
    track->clips=array("UnityEngine.Timeline.TimelineClip[]",{clip});
    references[{from->p(),key}]={true,to->go};
    auto* output=from->asset->tracks;output->entries.push_back(track->p());output->reported=output->entries.size();
    return track;
}
void setup() {
    timeline=make("Solis.Common.Live.SolisLiveTimelineController");director(master,"Master");director(audio,"Audio");director(other,"Unused");
    list=make("System.Collections.Generic.List`1");owned_array=array("UnityEngine.Playables.PlayableDirector[]",{master,audio,other});
    put(list,0x10,owned_array->p());put(list,0x18,int32_t(3));put(timeline,0x20,master->p());put(timeline,0x28,list->p());
    bgm=make("UnityEngine.Timeline.AudioTrack","BGM");voice=make("UnityEngine.Timeline.AudioTrack","Voice");
    audio_tracks=array("UnityEngine.Timeline.TrackAsset[]",{bgm,voice});audio->asset->tracks=audio_tracks;
    control_track=add_control(master,audio,17);control_clip=lookup[control_track->clips->entries[0]];
    control_asset=lookup[field<void*>(control_clip->p(),0x28)];root_tracks=master->asset->tracks;
}
int main(int argc,char** argv) {
    assert(argc==2);std::string s=argv[1];setup();auto calls=api();double root_duration=122;
    bool success=s=="actual_bittersweet_echo"||s=="identity_child"||s=="direct_master"||s=="multi_hop"||s=="default_reference"||s=="invalid_reference_uses_default"
        ||s=="duplicate_owned_entries"||s=="null_unused_asset"||s=="unrelated_unsupported_control"||s=="duration_roundoff"
        ||s=="inactive_unrelated"||s=="silent_voice_no_clip_read"||s=="unrelated_audio_name";
    if(s=="actual_bittersweet_echo"){root_duration=111.5;master->duration=111.5;audio->duration=111.49999999999899;other->duration=111.5;put(control_clip,0x30,111.5);}
    if(s=="direct_master"){master->asset->tracks=audio_tracks;audio->asset->tracks=array("UnityEngine.Timeline.TrackAsset[]",{});}
    if(s=="multi_hop"){references[{master->p(),17}]={true,other->go};add_control(other,audio,18);}
    if(s=="default_reference"||s=="invalid_reference_uses_default"){
        references[{master->p(),17}]={false,s=="default_reference"?nullptr:master->go};put(control_asset,0x20,audio->go->p());
    }
    if(s=="valid_null_does_not_use_default"){references[{master->p(),17}]={true,nullptr};put(control_asset,0x20,audio->go->p());}
    if(s=="duplicate_owned_entries"){owned_array->entries={audio->p(),master->p(),audio->p()};}
    if(s=="null_unused_asset")other->asset=nullptr;
    if(s=="unrelated_unsupported_control"){auto* tr=add_control(master,other,18);auto* c=lookup[tr->clips->entries[0]];put(c,0x18,3.0);}
    if(s=="duration_roundoff"){audio->duration=121.9999999999;put(control_clip,0x30,121.9999999999);}
    if(s=="silent_voice_no_clip_read")voice->muted=true;
    if(s=="unrelated_audio_name"){auto* tr=make("UnityEngine.Timeline.AudioTrack","SE");audio_tracks->entries.push_back(tr->p());audio_tracks->reported++;}
    if(s=="inactive_audio")audio->active=false;
    if(s=="inactive_unrelated")other->active=false;
    if(s=="inactive_ancestor"){references[{master->p(),17}]={true,other->go};add_control(other,audio,18);other->active=false;}
    if(s=="reference_throws")throw_reference=true;
    if(s=="dead_audio_track")bgm->live=false;
    if(s=="dead_control_track")control_track->live=false;
    if(s=="missing_api")calls.director_get_reference=nullptr;
    if(s=="nan_duration")root_duration=std::numeric_limits<double>::quiet_NaN();
    if(s=="zero_duration")root_duration=0;
    if(s=="long_duration")root_duration=901;
    if(s=="untyped_owned_list")list->type="Other";
    if(s=="invalid_owner_go")other->go->type="Other";
    if(s=="dead_owner_go")other->go->live=false;
    if(s=="missing_master_asset")master->asset=nullptr;
    if(s=="wrong_asset_type")audio->asset->type="Other";
    if(s=="dead_asset")audio->asset->live=false;
    if(s=="wrong_track_array")audio_tracks->type="Other";
    if(s=="large_track_array")audio_tracks->reported=257;
    if(s=="null_track_array_data")audio_tracks->null_data=true;
    if(s=="empty_track_name")voice->name="";
    if(s=="long_track_name")voice->name=std::string(32,'x');
    if(s=="duplicate_bgm")voice->name="BGM";
    if(s=="too_many_audio_tracks"){for(int i=0;i<32;++i)audio_tracks->entries.push_back(voice->p());audio_tracks->reported=audio_tracks->entries.size();}
    if(s=="missing_bgm")bgm->name="SE";
    if(s=="wrong_control_array")control_track->clips->type="Other";
    if(s=="large_control_array")control_track->clips->reported=65;
    if(s=="null_control_data")control_track->clips->null_data=true;
    if(s=="wrong_control_clip")control_clip->type="Other";
    if(s=="wrong_control_asset")control_asset->type="Other";
    if(s=="dead_control_asset")control_asset->live=false;
    if(s=="wrong_reference_type"){references[{master->p(),17}]={true,bgm};}
    if(s=="dead_reference"){auto* go=make("UnityEngine.GameObject");go->live=false;references[{master->p(),17}]={true,go};}
    if(s=="external_reference"){references[{master->p(),17}]={true,make("UnityEngine.GameObject")};}
    if(s=="ambiguous_game_object")other->go=audio->go;
    if(s=="muted_control")control_track->muted=true;
    if(s=="prefab_control")put(control_asset,0x28,other->go->p());
    if(s=="update_disabled")put(control_asset,0x38,uint8_t(0));
    if(s=="hierarchy_control")put(control_asset,0x3a,uint8_t(1));
    if(s=="offset_control")put(control_clip,0x18,2.0);
    if(s=="clip_in_control")put(control_clip,0x20,2.0);
    if(s=="scaled_control")put(control_clip,0x38,0.5);
    if(s=="nan_clock")put(control_clip,0x38,std::numeric_limits<double>::quiet_NaN());
    if(s=="short_control")put(control_clip,0x30,121.0);
    if(s=="short_child")audio->duration=121;
    if(s=="nan_child")audio->duration=std::numeric_limits<double>::quiet_NaN();
    if(s=="control_blend")put(control_clip,0x58,1.0);
    if(s=="control_ease")put(control_clip,0x48,1.0);
    if(s=="nan_blend")put(control_clip,0x60,std::numeric_limits<double>::quiet_NaN());
    if(s=="duplicate_clock")add_control(master,audio,18);
    if(s=="clock_cycle"){root_tracks->entries.clear();root_tracks->reported=0;add_control(other,audio,18);add_control(audio,other,19);}
    auto result=scan(timeline->p(),root_duration,calls);
    if(success) {
        assert(result.ok()&&result.count==2);
        assert(result.tracks[0].track==bgm->p()&&!std::strcmp(result.tracks[0].name,"BGM"));
        assert(result.tracks[1].track==voice->p()&&!std::strcmp(result.tracks[1].name,"Voice"));
        assert(result.tracks[0].director==(s=="direct_master"?master:audio)->p());
        assert(result.tracks[1].director==result.tracks[0].director);
        if(s=="direct_master")assert(reference_calls==0);
    } else {
        assert(!result.ok()&&std::strcmp(result.error,"none"));
        if(s=="offset_control"||s=="clip_in_control"||s=="scaled_control"||s=="nan_clock"||s=="short_control"||s=="short_child"||s=="nan_child")assert(!std::strcmp(result.error,"audio_control_clock_unsupported"));
        if(s=="valid_null_does_not_use_default"||s=="external_reference")assert(!std::strcmp(result.error,"selected_audio_clock_not_owned"));
        if(s=="clock_cycle")assert(!std::strcmp(result.error,"audio_control_clock_cycle"));
        if(s=="duplicate_clock")assert(!std::strcmp(result.error,"ambiguous_audio_control_clock"));
    }
}
'''


@pytest.fixture(scope="module")
def audio_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    build = tmp_path_factory.mktemp("mp4-timeline-audio")
    source = build / "audio.cpp"
    source.write_text(SOURCE)
    executable = build / "audio"
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I",
         str(ROOT / "client-presentation/native"), str(source), "-o", str(executable)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize("scenario", [
    "identity_child", "actual_bittersweet_echo", "inactive_audio", "inactive_ancestor", "inactive_unrelated", "direct_master", "multi_hop", "default_reference",
    "invalid_reference_uses_default", "duplicate_owned_entries", "null_unused_asset",
    "unrelated_unsupported_control", "duration_roundoff", "silent_voice_no_clip_read",
    "unrelated_audio_name", "missing_api", "nan_duration", "zero_duration", "long_duration",
    "untyped_owned_list", "invalid_owner_go", "dead_owner_go", "missing_master_asset",
    "wrong_asset_type", "dead_asset", "wrong_track_array", "large_track_array",
    "null_track_array_data", "empty_track_name", "long_track_name", "duplicate_bgm",
    "too_many_audio_tracks", "missing_bgm", "wrong_control_array", "large_control_array",
    "null_control_data", "wrong_control_clip", "wrong_control_asset", "dead_control_asset",
    "wrong_reference_type", "dead_reference", "external_reference", "ambiguous_game_object",
    "valid_null_does_not_use_default", "muted_control", "prefab_control", "update_disabled",
    "hierarchy_control", "offset_control", "clip_in_control", "scaled_control", "nan_clock",
    "short_control", "short_child", "nan_child", "control_blend", "control_ease", "nan_blend",
    "duplicate_clock", "clock_cycle", "reference_throws", "dead_audio_track", "dead_control_track",
])
def test_audio_owner_and_identity_control_clock(audio_binary, scenario):
    result = subprocess.run([str(audio_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
