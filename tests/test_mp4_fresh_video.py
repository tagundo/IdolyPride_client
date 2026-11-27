"""Disposable original-video requests with modeled typed decoder/API leaves.

These execute the production protocol, not a decoder or GPU. Original native
Update's transfer/event/drain ordering is established by the separate ARM audit.
"""
from pathlib import Path
import os
import shutil
import subprocess
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include "video_frame.inc"
#include "fresh_video.inc"
namespace fv=idoly_mp4_fresh_video;
fv::Identity id{reinterpret_cast<void*>(1),reinterpret_cast<void*>(2),3,4,5,6};
fv::Scope scope;fv::State state{id,reinterpret_cast<void*>(7),8,0,false,true,false,true};
bool current_=true,drained=true,decode=true,seek_event=true,frame_event=true,initial_event=true;
bool configured_ok=true,prepare_ok=true,publish_ok=true,throw_pump=false,throw_set=false;
bool pending_prepare=false,pending_seek=false,wrong_event=false,mutate=false;
int configurations=0,prepares=0,seeks=0,steps=0,pumps=0,published=0,pauses=0;
bool can_step_=true,pending_step=false;
bool initial_texture=true;
bool original_pending=false;int original_delay=0;int64_t original_frame=-1;
double reference=-1;int64_t pending_frame=-1;fv::Clip clip{30,2,60,true};
bool current(void*,const fv::Identity& x){return current_&&fv::same(id,x);}
bool read(void*,const fv::Identity& x,fv::State*out){assert(fv::same(id,x));*out=state;return true;}
bool adopt_prepared=false;
bool configure(void*,const fv::Identity& x,const fv::Clip&){assert(fv::same(id,x));++configurations;state.configured=true;if(adopt_prepared)return configured_ok;state.prepared=false;state.frame=-1;state.texture=nullptr;state.texture_native=0;return configured_ok;}
bool prepare(void*,const fv::Identity&){++prepares;pending_prepare=true;return prepare_ok;}
bool pause(void*,const fv::Identity&){++pauses;state.paused=state.prepared;state.playing=false;return true;}
bool ref(void*,const fv::Identity&,double t){reference=t;return true;}
bool set(void*,const fv::Identity&,int64_t frame){++seeks;pending_seek=true;pending_frame=frame;state.frame=frame;if(throw_set)throw std::runtime_error("original set_frame");return true;}
bool pump(void*,const fv::Identity&){
 ++pumps;if(throw_pump)throw std::runtime_error("original native Update");
 if(pending_prepare){pending_prepare=false;state.prepared=true;state.texture=initial_texture?reinterpret_cast<void*>(7):nullptr;state.texture_native=initial_texture?8:0;state.frame=initial_texture?0:-1;scope.on_prepared(id);if(initial_event)scope.on_frame_ready(id,0);}
 // A legitimate earlier Timeline callback can queue Video-only work before
 // this poll. The actual native Update transfers it and invokes FrameReady.
 if(original_pending&&original_delay--==0){original_pending=false;state.frame=original_frame;scope.on_frame_ready(id,original_frame);}
 if(pending_seek&&decode){pending_seek=false;state.texture=reinterpret_cast<void*>(7);state.texture_native=8;state.frame=pending_frame;if(seek_event&&!pending_step)scope.on_seek_completed(id);if(frame_event)scope.on_frame_ready(id,wrong_event?pending_frame+1:pending_frame);pending_step=false;}
 if(mutate)current_=false;
 return drained;
}
bool publish(void*,const fv::Identity&,void*texture,uintptr_t native){assert(texture==state.texture&&native==state.texture_native);++published;return publish_ok;}
bool can_step(void*,const fv::Identity&){return can_step_;}
bool step(void*,const fv::Identity&){++steps;pending_seek=true;pending_step=true;pending_frame=state.frame+1;return true;}
fv::Api api(){return {nullptr,current,read,configure,prepare,pause,ref,set,pump,publish};}
fv::Result ready(double t){auto result=scope.request(t);for(int i=0;i<6&&result==fv::Result::waiting;++i)result=scope.request(t);return result;}
int main(int argc,char**argv){assert(argc==2);std::string s=argv[1];auto calls=api();
 if(s=="bad_api"){calls.pump=nullptr;assert(!scope.bind(calls,id,clip));return 0;}
 if(s=="bad_identity"){auto bad=id;bad.player_native=0;assert(!scope.bind(calls,bad,clip));return 0;}
 if(s=="bad_clip"){clip.rate=0;assert(!scope.bind(calls,id,clip));return 0;}
 if(s=="nonloop")clip.loop=false;
 if(s=="fractional")clip.rate=29.97;
 if(s=="initial_no_event"||s=="one_frame_unproven")initial_event=false;
 if(s=="prepared_without_texture"){initial_texture=false;initial_event=false;}
 if(s=="one_frame_unproven")clip.frames=1;
 if(s=="step"||s=="step_unsupported"){calls.can_step=can_step;calls.step=step;can_step_=s=="step";}
 assert(scope.bind(calls,id,clip));assert(!scope.bind(calls,id,clip));
 if(s=="configure_failed"){configured_ok=false;assert(scope.prepare()==fv::Result::failed&&configurations==1);return 0;}
 if(s=="prepare_failed"){prepare_ok=false;assert(scope.prepare()==fv::Result::failed&&prepares==1);return 0;}
 if(s=="adopt_prepared"){
  // Redroid runs 26-33: a new Prepare under the hold never completed. A player
  // the original scene already prepared (and is playing) keeps its decoder;
  // no Prepare is issued and frame 0 is proven by real seek/FrameReady receipts.
  adopt_prepared=true;state.prepared=true;state.playing=true;state.paused=false;state.frame=5;
  auto result=scope.prepare();for(int i=0;i<4&&result==fv::Result::waiting;++i)result=scope.prepare();
  assert(result==fv::Result::ready&&prepares==0&&configurations==1&&seeks>=1&&state.paused&&!state.playing);
  assert(ready(0)==fv::Result::ready&&scope.accepted_frame()==0&&published==1);return 0;
 }
 if(s=="native_not_returned"){drained=false;assert(scope.prepare()==fv::Result::failed&&published==0);return 0;}
 if(s=="native_throws"){throw_pump=true;assert(scope.prepare()==fv::Result::failed&&published==0);return 0;}
 if(s=="one_frame_unproven"){assert(scope.prepare()==fv::Result::failed&&published==0&&seeks==0);return 0;}
 if(s=="prepared_without_texture"){
  assert(scope.prepare()==fv::Result::waiting&&seeks==1&&pending_frame==0&&published==0);
  assert(scope.prepare()==fv::Result::ready&&seeks==1&&state.frame==0&&state.texture);
  assert(ready(0)==fv::Result::ready&&scope.accepted_frame()==0&&seeks==1&&published==1);return 0;
 }
 if(s=="initial_no_event"){
  assert(scope.prepare()==fv::Result::waiting&&seeks==1&&pending_frame==1&&published==0);
  assert(scope.prepare()==fv::Result::ready&&seeks==1&&state.frame==1);
  assert(ready(0)==fv::Result::ready&&scope.accepted_frame()==0&&seeks==2&&published==1);return 0;
 }
 assert(scope.prepare()==fv::Result::ready&&prepares==1&&configurations==1&&state.paused&&!state.playing);
 if(s=="original_advance_same_target"||s=="original_advance_second_pump"){
  assert(ready(0)==fv::Result::ready&&scope.accepted_frame()==0&&seeks==0&&published==1);
  const auto prior=scope.receipt();original_pending=true;original_frame=1;original_delay=s=="original_advance_second_pump"?1:0;
  assert(scope.request(1.0/120)==fv::Result::waiting&&seeks==1&&published==1&&scope.inflight());
  assert(!original_pending&&pending_frame==0&&state.frame==0); // set_frame is not a transfer receipt.
  assert(ready(1.0/120)==fv::Result::ready&&scope.accepted_frame()==0&&scope.receipt()>prior
      &&seeks==1&&published==2&&prepares==1&&configurations==1);return 0;
 }
 if(s=="step"||s=="step_unsupported"){
  assert(ready(0)==fv::Result::ready&&seeks==0);
  assert(ready(1.0/30)==fv::Result::ready&&scope.accepted_frame()==1);
  assert(steps==(can_step_?1:0)&&seeks==(can_step_?0:1));return 0;
 }
 if(s=="wrong_identity_event"){auto bad=id;++bad.job;assert(!scope.on_frame_ready(bad,0)&&!scope.on_seek_completed(bad)&&!scope.on_prepared(bad));}
 if(s=="initial_zero"||s=="same_frame"){
  assert(ready(0)==fv::Result::ready&&scope.receipt()&&seeks==0&&published==1);
  const auto receipt=scope.receipt();assert(ready(1.0/120)==fv::Result::ready&&scope.receipt()==receipt&&seeks==0&&published==2);return 0;
 }
 if(s=="source_lost"){current_=false;assert(scope.request(.5)==fv::Result::stale&&published==0);return 0;}
 if(s=="abandon"){scope.abandon();assert(scope.request(.5)==fv::Result::invalid&&published==0);return 0;}
 if(s=="negative_time"){assert(scope.request(-1)==fv::Result::invalid&&seeks==0);return 0;}
 if(s=="get_frame_is_not_transfer")decode=false;
 if(s=="missing_seek_event")seek_event=false;
 if(s=="missing_frame_event")frame_event=false;
 if(s=="wrong_frame_event")wrong_event=true;
 if(s=="set_throws")throw_set=true;
 if(s=="publish_failed")publish_ok=false;
 if(s=="source_changes_in_native")mutate=true;
 const double t=s=="nonloop"?3:s=="fractional"?1:s=="loop"?2.5:.5;
 auto result=scope.request(t);
 if(s=="set_throws"){assert(result==fv::Result::failed&&seeks==1&&published==0);return 0;}
 if(s=="source_changes_in_native"){assert(result==fv::Result::stale&&published==0);return 0;}
 assert(result==fv::Result::waiting&&seeks==1&&published==0);
 if(s=="changed_request"){assert(scope.request(1)==fv::Result::invalid&&seeks==1);return 0;}
 result=ready(t);
 if(s=="get_frame_is_not_transfer"||s=="missing_seek_event"||s=="missing_frame_event"||s=="wrong_frame_event"){
  assert(result==fv::Result::waiting&&scope.inflight()&&seeks==1&&published==0&&scope.receipt()==0);return 0;
 }
 if(s=="publish_failed"){assert(result==fv::Result::stale&&published==1);return 0;}
 assert(result==fv::Result::ready&&!scope.inflight()&&scope.receipt()==1&&published==1&&seeks==1);
 assert(scope.accepted_frame()==(s=="nonloop"?59:s=="fractional"?29:15));
 if(s=="nonloop")assert(reference==59.0/30);
 if(s=="loop")assert(reference==.5);
}
'''


@pytest.fixture(scope="module")
def fresh_video_binary(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ host compiler required")
    folder = tmp_path_factory.mktemp("fresh-video")
    header = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    for marker, name in (("MP4_VIDEO_FRAME", "video_frame.inc"),
                         ("MP4_FRESH_VIDEO_FRAME", "fresh_video.inc")):
        fragment = header.split("// BEGIN_" + marker + "\n", 1)[1].split("// END_" + marker, 1)[0]
        (folder / name).write_text(fragment)
    source, binary = folder / "video.cpp", folder / "video"
    source.write_text(SOURCE)
    compiled = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                               "-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-I", str(folder),
                               str(source), "-o", str(binary)], capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return binary


@pytest.mark.parametrize("case", [
    "normal", "adopt_prepared", "initial_zero", "same_frame", "fractional", "loop", "nonloop", "bad_api",
    "bad_identity", "bad_clip", "configure_failed", "prepare_failed", "native_not_returned",
    "native_throws", "wrong_identity_event", "source_lost", "abandon", "negative_time",
    "get_frame_is_not_transfer", "missing_seek_event", "missing_frame_event", "wrong_frame_event",
    "set_throws", "publish_failed", "source_changes_in_native", "changed_request",
    "initial_no_event", "one_frame_unproven", "step", "step_unsupported",
    "original_advance_same_target", "original_advance_second_pump",
    "prepared_without_texture",
])
def test_actual_fresh_video_protocol(fresh_video_binary, case):
    result = subprocess.run([str(fresh_video_binary), case], capture_output=True, text=True,
                            timeout=15, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                            "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_can_step_pins_match_original_instance_boolean_method():
    directory = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:
        pytest.skip("Set IDOLY_MP4_ORIGINALS_DIR to audit actual originals")
    sys.path.insert(0, str(ROOT / "tools"))
    from audit_mp4_game import OriginalAndroid
    from audit_mp4_ios_game import Original
    header = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    for platform, constructor, metadata, native in (
        ("android", OriginalAndroid, "android-metadata.dat", "android-native.so"),
        ("ios", Original, "ios-metadata.dat", "ios-native.bin"),
    ):
        original = constructor((Path(directory) / metadata).read_bytes(), (Path(directory) / native).read_bytes())
        method = original.method("UnityEngine.Video.VideoPlayer", "get_canStep", 0, ())
        assert not method["static"] and method["return"] == "System.Boolean"
        expected = method["rva"] + ",{" + ",".join(f"0x{x:02x}" for x in bytes.fromhex(method["prefix"])) + "}," + method["registration_pointer_slot"]
        actual = re.search(r"StepBinding " + platform + r"_can_step=\{(.*?)\};", header).group(1)
        assert actual == expected


def test_unprepared_player_is_not_paused_every_poll():
    # Redroid runs 26-31: ~8 native pumps a second, the player stayed
    # configured+paused and never prepared while every poll paused it.
    source = (Path(__file__).resolve().parents[1] / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    bank = source[source.index("// BEGIN_MP4_FRESH_VIDEO_FRAME"):]
    assert "return pause_allowed_?api_.pause(api_.context,identity_):api_.current(api_.context,identity_);" in bank
    prepare = bank[bank.index("    Result prepare()noexcept {"):]
    prepare = prepare[:prepare.index("fresh_video_prepare_wait")]
    assert "api_.pause(" not in prepare and "hold_paused()" in prepare


def test_unprepared_video_is_dropped_after_a_bounded_wait():
    # Redroid runs 26-34: the MV's video player never prepared under the hold;
    # the export continues without that screen after 20 s instead of failing.
    bridge = (Path(__file__).resolve().parents[1] / "client-presentation/native/bridge.cpp").read_text()
    prepare = bridge[bridge.index("Mp4FreshResult mp4_fresh_video_prepare_all(){"):]
    prepare = prepare[:prepare.index("\n}\n")]
    assert "mp4_fresh_video_drop_after_ms" in prepare and '"dropped_unprepared"' in prepare
    assert "st.prepared)continue;" in prepare  # a prepared player is never dropped
    assert "constexpr uint64_t mp4_fresh_video_drop_after_ms=20000;" in bridge
    frames = bridge[bridge.index("Mp4FreshResult mp4_fresh_video_frame_all(double seconds){"):]
    assert "if(e.dropped)continue;" in frames[:frames.index("\n}\n")]
