"""Actual Fresh UpdateVideo wrapper/predicate with typed source/GC leaves modeled.

The native hook installer has its separate source/gateway tests. This verifies
the shipping selective forwarding body, not decoder execution or a DSP fence.
"""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
using Method=void;
namespace mp4actor {struct Handle {uintptr_t handle=0;uint32_t version=0,padding=0;};}
struct Mp4ChildDrivingFrameData {uint8_t bytes[64]{};};
struct Script {void*player=nullptr;uint8_t recording=0;bool typed=true,player_field=true,recording_field=true;};
struct Frames {int abandoned=0;void abandon(){++abandoned;}};
struct Identity {void*player=nullptr;};
struct Entry {Frames frames;Identity identity;void*script=nullptr;bool active=false,current=true,dropped=false;};
Entry mp4_fresh_videos[16];size_t mp4_fresh_video_count=1;
std::atomic<void*>mp4_fresh_video_scripts[16];std::atomic<bool>mp4_fresh_withdrawn{false};
bool owner=true,selected=true,callbacks=true,retain_ok=true;
int retained=0,metadata_reads=0,original_calls=0,queued_decoder_steps=0;
int family=0;void*opaque_player=reinterpret_cast<void*>(123);mp4actor::Handle opaque_handle{77,8,0};Mp4ChildDrivingFrameData opaque_frame;
void*last_original=nullptr;bool last_prepare=false;double last_time=-1;Method*last_method=nullptr;
namespace mp4camp {struct RenderLayout {static constexpr size_t video_mixer_videoplayer=16,video_mixer_isrecording=32;};struct Types {int video_mixer=1;};}
mp4camp::Types mp4_cam_types;mp4camp::Types type_names_;
namespace mp4camp {const Types&type_names=type_names_;}
bool game_call(){return owner;}
bool mp4_fresh_current(void*){return selected;}
bool mp4_fresh_video_callbacks_ready(){return callbacks;}
bool mp4_video_exact(void*p,int,int){++metadata_reads;return p&&static_cast<Script*>(p)->typed;}
bool mp4_root_track_field(void*p,const char*name,size_t offset){
 ++metadata_reads;auto*s=static_cast<Script*>(p);
 if(!std::strcmp(name,"VideoPlayer"))return offset==16&&s->player_field;
 if(!std::strcmp(name,"IsRecording"))return offset==32&&s->recording_field;
 assert(false);return false;
}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){
 ++metadata_reads;auto*s=static_cast<Script*>(p);
 if constexpr(sizeof(T)==sizeof(void*)){if(offset!=16)return false;std::memcpy(&out,&s->player,sizeof(T));}
 else{if(offset!=32)return false;std::memcpy(&out,&s->recording,sizeof(T));}
 return true;
}
bool mp4_fresh_video_current(void*p,const Identity&){return selected&&callbacks&&static_cast<Entry*>(p)->current;}
bool mp4_fresh_keep(void*){++retained;return retain_ok;}
// PREDICATE
using Mp4FreshVideoUpdateSink=bool(*)(void*,bool,double);
std::atomic<Mp4FreshVideoUpdateSink>mp4_fresh_video_update_sink{nullptr};
void original(void*s,bool prepare,double time,Method*method){++original_calls;++queued_decoder_steps;last_original=s;last_prepare=prepare;last_time=time;last_method=method;}
using Update=void(*)(void*,bool,double,Method*);Update mp4_video_update_original=original;
void original_loop(void*s,void*player,Method*m){assert(player==opaque_player);original(s,false,0,m);}
void original_play(void*s,mp4actor::Handle h,Mp4ChildDrivingFrameData frame,Method*m){
 assert(h.handle==opaque_handle.handle&&h.version==opaque_handle.version&&std::memcmp(&frame,&opaque_frame,sizeof frame)==0);original(s,false,0,m);
}
using Loop=void(*)(void*,void*,Method*);Loop mp4_video_loop_original=original_loop;
using Play=void(*)(void*,mp4actor::Handle,Mp4ChildDrivingFrameData,Method*);Play mp4_video_behaviour_play_original=original_play;
// WRAPPER
void invoke(void*s,bool prepare,double time,Method*method){
 if(family==0)mp4_video_update_hook(s,prepare,time,method);
 else if(family==1)mp4_video_loop_hook(s,opaque_player,method);
 else mp4_video_behaviour_play_hook(s,opaque_handle,opaque_frame,method);
}
int main(int argc,char**argv){assert(argc==3);std::string mode=argv[1];family=std::string(argv[2])=="update"?0:std::string(argv[2])=="loop"?1:2;
 for(size_t i=0;i<64;++i)opaque_frame.bytes[i]=static_cast<uint8_t>(128+i);
 int vp=1,foreign=2;Script ours{&vp},other{&foreign};auto&e=mp4_fresh_videos[0];e.active=true;e.identity.player=&vp;
 mp4_fresh_video_update_sink.store(mp4_fresh_video_suppress);
 if(mode=="ordinary"||mode=="foreign_unknown"){
  if(mode=="foreign_unknown")owner=false;
  invoke(&other,true,4.25,reinterpret_cast<Method*>(9));
  assert(original_calls==1&&queued_decoder_steps==1&&retained==0&&!mp4_fresh_withdrawn);
  assert(last_original==&other&&last_method==reinterpret_cast<Method*>(9));
  if(family==0)assert(last_prepare&&last_time==4.25);
  if(!owner)assert(metadata_reads==0);
  return 0;
 }
 if(mode=="unknown_withdrawn"){selected=false;invoke(&ours,false,0,nullptr);assert(original_calls==1&&retained==0&&!mp4_fresh_withdrawn);return 0;}
 if(mode=="recording")ours.recording=1;
 if(mode=="recording_schema_lost")ours.recording_field=false;
 if(mode=="retain_failed")retain_ok=false;
 invoke(&ours,false,0,nullptr);
 assert(original_calls==0&&queued_decoder_steps==0);
 if(mode=="recording"||mode=="recording_schema_lost"||mode=="retain_failed"){
  assert(e.frames.abandoned&&mp4_fresh_withdrawn&&!e.script);return 0;
 }
 assert(e.script==&ours&&retained==1&&mp4_fresh_video_scripts[0].load()==&ours&&!mp4_fresh_withdrawn);
 if(mode=="known_stale")e.current=false;
 if(mode=="known_recording")e.current=false;
 if(mode=="foreign_known")owner=false;
 if(mode=="other_script_same_player")other.player=&vp;
 if(mode=="detached")mp4_fresh_video_update_sink.store(nullptr);
 const int reads=metadata_reads;
 invoke(mode=="other_script_same_player"?static_cast<void*>(&other):static_cast<void*>(&ours),true,.008333333333333,nullptr);
 if(mode=="detached"){assert(original_calls==1&&queued_decoder_steps==1);return 0;}
 assert(original_calls==0&&queued_decoder_steps==0&&retained==1);
 if(mode=="known_stale"||mode=="known_recording"||mode=="foreign_known"||mode=="other_script_same_player")assert(mp4_fresh_withdrawn);
 else assert(!mp4_fresh_withdrawn);
 if(mode=="foreign_known")assert(metadata_reads==reads);
 if(mode=="same_120hz_target"){
  for(int i=0;i<120;++i)invoke(&ours,false,static_cast<double>(i)/120,nullptr);
  assert(original_calls==0&&queued_decoder_steps==0&&!mp4_fresh_withdrawn&&retained==1);
 }
}
'''


def _function(text, name):
    begin = text.index(name)
    brace = text.index("{", begin)
    depth = 1
    at = brace + 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[begin:at]


@pytest.fixture(scope="module")
def suppression_binary(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ host compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    assert "// BEGIN_MP4_FRESH_VIDEO_UPDATE_SUPPRESSION" in bridge, "Shipping Fresh Video command ownership is missing"
    predicate = bridge.split("// BEGIN_MP4_FRESH_VIDEO_UPDATE_SUPPRESSION", 1)[1].split("// END_MP4_FRESH_VIDEO_UPDATE_SUPPRESSION", 1)[0]
    wrapper = "\n".join(_function(bridge, "void " + name + "(") for name in (
        "mp4_video_update_hook", "mp4_video_loop_hook", "mp4_video_behaviour_play_hook"))
    folder = tmp_path_factory.mktemp("fresh-video-update")
    source, binary = folder / "update.cpp", folder / "update"
    source.write_text(SOURCE.replace("// PREDICATE", predicate).replace("// WRAPPER", wrapper))
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(source), "-o", str(binary)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", [
    "owned", "ordinary", "same_120hz_target", "known_stale", "known_recording", "foreign_known",
    "foreign_unknown", "other_script_same_player", "unknown_withdrawn", "recording",
    "recording_schema_lost", "retain_failed", "detached",
])
@pytest.mark.parametrize("family", ["update", "loop", "play"])
def test_shipping_selective_video_update_forwarding(suppression_binary, case, family):
    result = subprocess.run([str(suppression_binary), case, family], capture_output=True, text=True, timeout=15,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                 "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stdout + result.stderr
