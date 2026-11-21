"""Exercise child audio ownership through the production export adapter.

The graph shape/times follow the manifest-verified tln_live_thrx-006 audit.
Unity, managed heap and GPU/codec callbacks remain synthetic.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_game_adapter import SOURCE

ROOT=Path(__file__).resolve().parents[1]
BASE,MAIN=SOURCE.split('int main(){',1)
CONNECT=MAIN.split('Api selected_api=api();',1)[0]
DRIVER=r'''
Obj *camera_child,*audio_child,*camera_asset,*audio_asset,*voice_track,*voice_props,*audio_control,*audio_control_clip;
std::map<void*,void*> selected_assets,selected_game_objects;
std::map<void*,std::vector<void*>> selected_tracks,selected_clips;
std::map<int32_t,void*> control_references;
std::map<void*,bool> enabled;
unsigned voice_clip_reads=0;bool reject_voice_handle=false,voice_muted=false;
void* nested_asset(void* value,Method*){auto i=selected_assets.find(value);return i==selected_assets.end()?nullptr:i->second;}
void* nested_tracks(void* value,Method*){auto* a=make("UnityEngine.Timeline.TrackAsset[]");a->array_kind=1;a->pointers=selected_tracks[value];return ptr(a);}
void* nested_clips(void* value,Method*){if(value==ptr(voice_track))++voice_clip_reads;auto* a=make("UnityEngine.Timeline.TimelineClip[]");a->array_kind=1;a->pointers=selected_clips[value];return ptr(a);}
void* nested_binding(void* owner,void* tr,Method*){return owner==ptr(camera_child)&&tr==ptr(camera_track)?ptr(brain):nullptr;}
void* nested_reference(void* owner,PropertyName4 key,bool* valid,Method*){assert(owner==ptr(director));auto i=control_references.find(key.id);*valid=i!=control_references.end();return *valid?i->second:nullptr;}
void* nested_game_object(void* owner,Method*){return selected_game_objects[owner];}
bool nested_active(void* value,Method*){auto i=enabled.find(value);return i==enabled.end()||i->second;}
bool nested_muted(void* value,Method*){return value==ptr(voice_track)?voice_muted:track_muted(value,nullptr);}
double nested_duration(void* value,Method*){return value==ptr(audio_child)?111.49999999999899:111.5;}
int32_t nested_samples(void*,Method*){return 48000*112;}
uint32_t nested_retain(void* value){return reject_voice_handle&&value==ptr(voice_track)?0:retain(value);}
Obj* arr(const char* kind,std::vector<void*> values){auto* a=make(kind);a->array_kind=1;a->pointers=std::move(values);return a;}
Obj* audio_clip_(const char* name_,double start,double in,double duration_){
    auto* value=make("UnityEngine.Timeline.TimelineClip");auto* asset_=make("UnityEngine.Timeline.AudioPlayableAsset");
    auto* props=make("UnityEngine.Timeline.AudioClipProperties");write(props,0x10,1.f);
    write(value,0x18,start);write(value,0x20,in);write(value,0x30,duration_);write(value,0x38,1.0);
    write(value,0x58,-1.0);write(value,0x60,-1.0);write(value,0x28,ptr(asset_));
    write(asset_,0x18,ptr(make("UnityEngine.AudioClip",name_)));write(asset_,0x28,ptr(props));return value;
}
void connect_scene(){
'''+CONNECT+r'''
    camera_child=make("UnityEngine.Playables.PlayableDirector");audio_child=make("UnityEngine.Playables.PlayableDirector");
    camera_asset=make("UnityEngine.Timeline.TimelineAsset");audio_asset=make("UnityEngine.Timeline.TimelineAsset");
    selected_assets={{ptr(director),ptr(timeline)},{ptr(camera_child),ptr(camera_asset)},{ptr(audio_child),ptr(audio_asset)}};
    selected_game_objects={{ptr(director),ptr(make("UnityEngine.GameObject","MasterTimeline"))},
        {ptr(camera_child),ptr(make("UnityEngine.GameObject","Camera"))},{ptr(audio_child),ptr(make("UnityEngine.GameObject","Audio"))}};
    selected_tracks[ptr(camera_asset)]={ptr(camera_track)};
    auto* source_list=objects.at(*reinterpret_cast<void**>(controller->mem.data()+0x28));
    auto* source_items=arr("UnityEngine.Playables.PlayableDirector[]",{ptr(director),ptr(camera_child),ptr(audio_child)});
    write(source_list,0x10,ptr(source_items));write(source_list,0x18,int32_t(3));
    const char* names[]={"Actor","Camera","Audio","Light","EquipmentController","Effect","Gobo","Monitor","Other"};
    for(int i=0;i<9;++i){
        auto* tr=make("UnityEngine.Timeline.ControlTrack",names[i]);auto* control_=make("UnityEngine.Timeline.ControlPlayableAsset");
        auto* cl=make("UnityEngine.Timeline.TimelineClip");write(cl,0x18,0.0);write(cl,0x20,0.0);write(cl,0x30,111.5);write(cl,0x38,1.0);
        write(cl,0x58,-1.0);write(cl,0x60,-1.0);write(cl,0x28,ptr(control_));
        const int32_t key=-641984113+i;write(control_,0x18,key);write(control_,0x38,uint8_t(1));
        control_references[key]=i==1?selected_game_objects[ptr(camera_child)]:i==2?selected_game_objects[ptr(audio_child)]:ptr(make("UnityEngine.GameObject",names[i]));
        if(i==2){audio_control=control_;audio_control_clip=cl;}
        selected_tracks[ptr(timeline)].push_back(ptr(tr));selected_clips[ptr(tr)]={ptr(cl)};
    }
    voice_track=make("UnityEngine.Timeline.AudioTrack","Voice");voice_props=make("UnityEngine.Timeline.AudioMixerProperties");write(voice_props,0x10,1.f);write(voice_track,0xa0,ptr(voice_props));
    selected_tracks[ptr(audio_asset)]={ptr(track),ptr(voice_track)};
    selected_clips[ptr(track)]={ptr(audio_clip_("sud_music_short_thrx-006",2.9,0.33333333333333304,107.47414652506515))};
    selected_clips[ptr(voice_track)]={ptr(audio_clip_("sud_se_live_cheers-mix-l",0,0,6.729416666666666)),
        ptr(audio_clip_("sud_se_live_cheers-clap-l",94.607374999999,0,16.892625))};
    bgm_volume=voice_volume=1;
}
bool rooted(void* target_){for(const auto& h:handles)if(h.second==target_)return true;return false;}
int main(int argc,char** argv){
    assert(argc==2);const std::string scenario=argv[1];connect_scene();Api api_=api();
    api_.director_get_asset=nested_asset;api_.timeline_get_tracks=nested_tracks;api_.track_get_clips=nested_clips;
    api_.director_get_binding=nested_binding;api_.director_get_reference=nested_reference;
    api_.component_game_object=nested_game_object;api_.track_muted_hierarchy=nested_muted;api_.active_enabled=nested_active;
    api_.director_get_duration=nested_duration;api_.audio_clip_samples=nested_samples;api_.retain=nested_retain;
    if(scenario=="silent_voice"){write(voice_props,0x10,0.f);selected_clips.erase(ptr(voice_track));}
    if(scenario=="muted_voice_hierarchy"){voice_muted=true;selected_clips.erase(ptr(voice_track));}
    if(scenario=="silent_voice_clips"||scenario=="audible_voice_missing"){
        for(auto* p:selected_clips[ptr(voice_track)]){
            auto* c=objects.at(p);auto* a=objects.at(*reinterpret_cast<void**>(c->mem.data()+0x28));
            write(a,0x18,static_cast<void*>(nullptr));
            if(scenario=="silent_voice_clips")write(objects.at(*reinterpret_cast<void**>(a->mem.data()+0x28)),0x10,0.f);
        }
    }
    if(scenario=="handle_failure")reject_voice_handle=true;
    GameAdapter game(api_);clock_game=&game;game.observe_presenter(ptr(presenter));game.observe_camera_controller(ptr(camera_controller));Snapshot snapshot{};
    const Result captured=game.snapshot(snapshot);
    if(scenario=="audible_voice_missing"||scenario=="handle_failure"){
        assert(captured==(scenario=="handle_failure"?Result::failed:Result::waiting));
        assert(!rooted(ptr(track))&&!rooted(ptr(voice_track)));
        assert(game.begin_manual()==Result::stale&&mode==0&&time_value==13.25);game.reset_observations();assert(handles.empty());return 0;
    }
    assert(captured==Result::ok&&snapshot.duration_seconds==111.5);
    const bool silent=scenario=="silent_voice"||scenario=="muted_voice_hierarchy"||scenario=="silent_voice_clips";
    assert(snapshot.audio.count==(silent?1:3));
    assert(snapshot.audio.clips[0].start_seconds==2.9&&snapshot.audio.clips[0].clip_in_seconds==0.33333333333333304);
    if(scenario=="silent_voice"||scenario=="muted_voice_hierarchy")assert(voice_clip_reads==0);
    if(!silent)assert(!std::strcmp(snapshot.audio.clips[1].clip_name,"sud_se_live_cheers-mix-l")&&snapshot.audio.clips[1].track_gain==1&&snapshot.audio.clips[1].source_gain==1);
    assert(rooted(ptr(audio_child))&&rooted(ptr(audio_asset))&&rooted(ptr(track))&&rooted(ptr(voice_track)));
    if(scenario=="changed_audio_reference"||scenario=="reused_during_manual"){
        if(scenario=="reused_during_manual")assert(game.begin_manual()==Result::ok);
        control_references[*reinterpret_cast<int32_t*>(audio_control->mem.data()+0x18)]=ptr(make("UnityEngine.GameObject","Unrelated"));
    }
    if(scenario=="changed_audio_control_time")write(audio_control_clip,0x18,0.25);
    if(scenario=="changed_audio_asset")selected_assets[ptr(audio_child)]=ptr(make("UnityEngine.Timeline.TimelineAsset"));
    if(scenario=="inactive_audio_child")enabled[ptr(audio_child)]=false;
    if(scenario=="failed_snapshot"){
        auto* c=objects.at(selected_clips[ptr(track)][0]);write(c,0x38,2.0);assert(game.snapshot(snapshot)==Result::unsupported);write(c,0x38,1.0);
        assert(!rooted(ptr(track))&&!rooted(ptr(voice_track)));
    }
    if(scenario=="reused_during_manual"){
        time_value=9;mode=2;bgm_volume=.3f;voice_volume=.7f;custom=true;shader=77;
        assert(game.evaluate(1)==Result::stale);assert(game.restore()==Result::ok);
        assert(time_value==9&&mode==2&&bgm_volume==.3f&&voice_volume==.7f&&shader==77);
    }else if(scenario=="changed_audio_reference"||scenario=="changed_audio_control_time"||scenario=="changed_audio_asset"||scenario=="inactive_audio_child"||scenario=="failed_snapshot"){
        assert(game.begin_manual()==Result::stale&&mode==0&&time_value==13.25&&bgm_volume==1&&voice_volume==1);
    }else{
        assert(game.begin_manual()==Result::ok&&mode==3&&bgm_volume==0&&voice_volume==0);
        if(scenario=="snapshot_while_manual"){
            Snapshot unused{};assert(game.snapshot(unused)==Result::invalid&&!std::strcmp(game.last_error(),"export_already_owns_scene"));
        }
        assert(game.evaluate(2.9)==Result::ok&&std::fabs(time_value-2.9)<1e-6);assert(game.restore()==Result::ok);
        assert(time_value==13.25&&mode==0&&bgm_volume==1&&voice_volume==1);
    }
    game.reset_observations();assert(handles.empty());
}
'''

@pytest.fixture(scope='module')
def nested_audio_adapter(tmp_path_factory):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    build=tmp_path_factory.mktemp('mp4-nested-audio-adapter');source=build/'audio.cpp';source.write_text(BASE+'\n'+DRIVER);binary=build/'audio'
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('scenario',['actual_bittersweet_echo','silent_voice','muted_voice_hierarchy','silent_voice_clips','audible_voice_missing','handle_failure','changed_audio_reference','changed_audio_control_time','changed_audio_asset','inactive_audio_child','failed_snapshot','reused_during_manual','snapshot_while_manual'])
def test_nested_audio_adapter_clock_lifetime_and_silence(nested_audio_adapter,scenario):
    result=subprocess.run([str(nested_audio_adapter),scenario],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
