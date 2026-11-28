"""Exercise the shipping Fresh authored-video clock guards with modeled leaves.

The fixture represents the original full-song Master Control -> external
Monitor Director -> VideoTrack topology. Public API, current-source and GC
receipts are explicit test leaves; these checks do not execute Unity, decode
video, or demonstrate an exported game MP4.
"""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>

using Method = void;
struct Object {
 std::array<unsigned char, 192> bytes{};
 bool alive=true, muted=false;
 size_t unreadable=static_cast<size_t>(-1);
};
template<class T>void write(Object&object,size_t offset,const T&value){
 assert(offset+sizeof(T)<=object.bytes.size());
 std::memcpy(object.bytes.data()+offset,&value,sizeof(T));
}
template<class T>bool mp4_actor_field(void*pointer,size_t offset,T&value){
 if(!pointer)return false;
 auto&object=*static_cast<Object*>(pointer);
 if(!object.alive||object.unreadable==offset||offset+sizeof(T)>object.bytes.size())return false;
 std::memcpy(&value,object.bytes.data()+offset,sizeof(T));return true;
}
namespace mp4camp {struct RenderLayout {static constexpr size_t video_track_loop=32;};}
namespace mp4game {struct Layout {size_t clip_asset=0x10;};}
struct Director {void*track=nullptr,*binding=nullptr;};
struct Api {
 bool track_muted_hierarchy(void*track,Method*)const{return !track||static_cast<Object*>(track)->muted;}
 void*director_get_binding(void*director,void*track,Method*)const{
  if(!director)return nullptr;
  const auto&d=*static_cast<Director*>(director);return d.track==track?d.binding:nullptr;
 }
}mp4_api;
struct Mp4FreshControlRoster {
 struct Node {void*director=nullptr;bool controlled=false;};
 struct Control {size_t parent=0;bool muted=false,update=true;double timing[8]{};};
 struct Edge {size_t child=0,control=0;};
 Node nodes[129]{};Control controls[129]{};Edge edges[129]{};
 size_t count=0,control_count=0,edge_count=0;bool ready=false;
 uint64_t source_identity=0,source_revision=0;
};
struct Host {Mp4FreshControlRoster*roster=nullptr;}mp4_fresh_host;
bool on_game_thread=true,retained_roots_alive=true,source_topology_current=true;
uint64_t selected_identity=19,selected_revision=41;
size_t current_receipts=0;
bool game_call(){return on_game_thread;}
bool mp4_fresh_control_roster_current(const Mp4FreshControlRoster&r){
 ++current_receipts;
 return retained_roots_alive&&source_topology_current&&r.count<=129
  &&r.control_count<=129&&r.edge_count<=129
  &&selected_identity==r.source_identity&&selected_revision==r.source_revision;
}

// ACTUAL_PROGRAM_STATE
// ACTUAL_IDENTITY_TIME
// ACTUAL_CLOCK_PATH
// ACTUAL_PROGRAM_CURRENT

struct Fixture {
 static constexpr double duration=95.1;
 static constexpr size_t monitor=7; // External Monitor is beyond the seven flat source Directors.
 Mp4FreshControlRoster roster{};
 Director directors[129]{};
 Object track{},clip{},asset{},player{},image{},foreign{};
 Fixture(){
  mp4_fresh_video_program=Mp4FreshVideoProgram{};
  on_game_thread=retained_roots_alive=source_topology_current=true;
  selected_identity=19;selected_revision=41;current_receipts=0;
  roster.ready=true;roster.count=8;roster.control_count=roster.edge_count=1;
  roster.source_identity=selected_identity;roster.source_revision=selected_revision;
  for(size_t i=0;i<roster.count;++i)roster.nodes[i].director=&directors[i];
  roster.nodes[monitor].controlled=true;
  roster.controls[0].parent=0;
  identity(roster.controls[0].timing);
  roster.edges[0]={monitor,0};
  mp4_fresh_host.roster=&roster;
  auto&p=mp4_fresh_video_program;p.ready=true;p.count=1;p.duration=duration;
  auto&t=p.tracks[0];t.node=monitor;t.track=&track;t.clip=&clip;t.asset=&asset;
  t.player=&player;t.image=&image;t.loop=1;identity(t.timing);
  write(track,mp4camp::RenderLayout::video_track_loop,t.loop);
  write(clip,mp4game::Layout{}.clip_asset,t.asset);
  const size_t offsets[]={0x18,0x30,0x20,0x38,0x48,0x50,0x58,0x60};
  for(size_t i=0;i<8;++i)write(clip,offsets[i],t.timing[i]);
  for(size_t i=0;i<2;++i){write(clip,0x94+i*4,t.extrapolation_mode[i]);write(clip,0xa0+i*8,t.extrapolation[i]);}
  directors[monitor]={&track,&player};
 }
 static void identity(double*t){for(size_t i=0;i<8;++i)t[i]=0;t[1]=duration;t[3]=1;}
};

int main(int argc,char**argv){
 assert(argc==2);const std::string test=argv[1];Fixture f;
 auto&p=mp4_fresh_video_program;auto&t=p.tracks[0];
 assert(mp4_fresh_video_identity_time(t.timing,p.duration));
 assert(mp4_fresh_video_clock_path(t.node,p.duration));
 assert(mp4_fresh_video_program_current());

 if(test=="full_song_external_monitor"){
  assert(t.node==7&&f.roster.nodes[7].director==&f.directors[7]);
  for(int tick=0;tick<11412;++tick)assert(mp4_fresh_video_program_current());
  assert(current_receipts>=11413);return 0;
 }
 if(test=="nested_control"){
  f.roster.nodes[1].controlled=true;f.roster.controls[0].parent=1;
  f.roster.controls[1].parent=0;Fixture::identity(f.roster.controls[1].timing);
  f.roster.edges[1]={1,1};f.roster.control_count=f.roster.edge_count=2;
  assert(mp4_fresh_video_clock_path(t.node,p.duration));assert(mp4_fresh_video_program_current());return 0;
 }
 if(test.rfind("identity_",0)==0){
  double timing[8];std::memcpy(timing,t.timing,sizeof(timing));
  if(test=="identity_clip_in")timing[2]=.25;
  else if(test=="identity_scale")timing[3]=1.25;
  else if(test=="identity_start")timing[0]=.01;
  else if(test=="identity_short_duration")timing[1]=Fixture::duration-.003;
  else if(test=="identity_ease_in")timing[4]=.1;
  else if(test=="identity_ease_out")timing[5]=.1;
  else if(test=="identity_blend_in")timing[6]=.1;
  else if(test=="identity_blend_out")timing[7]=.1;
  else if(test=="identity_nonfinite")timing[1]=std::numeric_limits<double>::quiet_NaN();
  else assert(false);
  assert(!mp4_fresh_video_identity_time(timing,p.duration));return 0;
 }

 if(test=="changed_binding")f.directors[7].binding=&f.foreign;
 else if(test=="changed_track_binding_key")f.directors[7].track=&f.foreign;
 else if(test=="changed_clip_asset")write(f.clip,0x10,static_cast<void*>(&f.foreign));
 else if(test=="changed_loop"){uint8_t loop=0;write(f.track,32,loop);}
 else if(test=="changed_clip_in")write(f.clip,0x20,.25);
 else if(test=="changed_scale")write(f.clip,0x38,1.25);
 else if(test=="changed_ease")write(f.clip,0x48,.1);
 else if(test=="changed_blend")write(f.clip,0x60,.1);
 else if(test=="changed_duration")write(f.clip,0x30,Fixture::duration+1);
 else if(test=="changed_extrapolation_mode"){int32_t mode=1;write(f.clip,0x94,mode);}
 else if(test=="changed_pre_extrapolation_mode"){int32_t mode=1;write(f.clip,0x98,mode);}
 else if(test=="changed_extrapolation_time")write(f.clip,0xa0,.1);
 else if(test=="changed_pre_extrapolation_time")write(f.clip,0xa8,.1);
 else if(test=="clip_field_unavailable")f.clip.unreadable=0x20;
 else if(test=="retired_clip")f.clip.alive=false;
 else if(test=="track_muted")f.track.muted=true;
 else if(test=="parent_clip_in")f.roster.controls[0].timing[2]=.25;
 else if(test=="parent_scale")f.roster.controls[0].timing[3]=.5;
 else if(test=="parent_ease")f.roster.controls[0].timing[5]=.1;
 else if(test=="parent_muted")f.roster.controls[0].muted=true;
 else if(test=="parent_update_disabled")f.roster.controls[0].update=false;
 else if(test=="missing_clock_parent")f.roster.edge_count=0;
 else if(test=="duplicate_clock_parent"){f.roster.edges[1]=f.roster.edges[0];f.roster.edge_count=2;}
 else if(test=="invalid_parent_index")f.roster.controls[0].parent=129;
 else if(test=="invalid_control_index")f.roster.edges[0].control=1;
 else if(test=="clock_cycle")f.roster.controls[0].parent=7;
 else if(test=="changed_source_identity")++selected_identity;
 else if(test=="changed_source_revision")++selected_revision;
 else if(test=="changed_source_topology")source_topology_current=false;
 else if(test=="lost_gc_root")retained_roots_alive=false;
 else if(test=="wrong_thread")on_game_thread=false;
 else if(test=="program_not_ready")p.ready=false;
 else if(test=="roster_not_ready")f.roster.ready=false;
 else if(test=="missing_roster")mp4_fresh_host.roster=nullptr;
 else if(test=="track_limit")p.count=17;
 else if(test=="invalid_video_node")t.node=f.roster.count;
 else assert(false);
 assert(!mp4_fresh_video_program_current());
}
'''


def _function(source, signature):
    """Copy a complete shipping function rather than restating its logic."""
    begin = source.index(signature)
    brace = source.index("{", begin)
    depth, at = 1, brace + 1
    while depth:
        depth += (source[at] == "{") - (source[at] == "}")
        at += 1
    return source[begin:at]


@pytest.fixture(scope="module")
def video_program_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    program = bridge.split("// BEGIN_MP4_FRESH_VIDEO_PROGRAM", 1)[1].split(
        "// END_MP4_FRESH_VIDEO_PROGRAM", 1)[0]
    state = program[:program.index("const Mp4FreshControlRoster::List*")]
    actual = {
        "// ACTUAL_PROGRAM_STATE": state,
        "// ACTUAL_IDENTITY_TIME": _function(program, "bool mp4_fresh_video_identity_time("),
        "// ACTUAL_CLOCK_PATH": _function(program, "bool mp4_fresh_video_clock_path("),
        "// ACTUAL_PROGRAM_CURRENT": _function(program, "bool mp4_fresh_video_program_current("),
    }
    harness = SOURCE
    for marker, implementation in actual.items():
        harness = harness.replace(marker, implementation)
    folder = tmp_path_factory.mktemp("fresh-video-program")
    source, binary = folder / "program.cpp", folder / "program"
    source.write_text(harness)
    built = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-g",
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
         str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", [
    "full_song_external_monitor", "nested_control",
    "identity_clip_in", "identity_scale", "identity_start", "identity_short_duration",
    "identity_ease_in", "identity_ease_out", "identity_blend_in", "identity_blend_out",
    "identity_nonfinite", "changed_binding", "changed_track_binding_key", "changed_clip_asset",
    "changed_loop", "changed_clip_in", "changed_scale", "changed_ease", "changed_blend",
    "changed_duration", "changed_extrapolation_mode", "changed_pre_extrapolation_mode",
    "changed_extrapolation_time", "changed_pre_extrapolation_time", "clip_field_unavailable",
    "retired_clip", "track_muted", "parent_clip_in", "parent_scale", "parent_ease",
    "parent_muted", "parent_update_disabled", "missing_clock_parent", "duplicate_clock_parent",
    "invalid_parent_index", "invalid_control_index", "clock_cycle", "changed_source_identity",
    "changed_source_revision", "changed_source_topology", "lost_gc_root", "wrong_thread",
    "program_not_ready", "roster_not_ready", "missing_roster", "track_limit", "invalid_video_node",
])
def test_shipping_authored_video_clock_program(video_program_binary, case):
    ran = subprocess.run(
        [str(video_program_binary), case], capture_output=True, text=True, timeout=15,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"})
    assert ran.returncode == 0, ran.stdout + ran.stderr
