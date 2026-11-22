"""Production listener lease and exact original method pins, without DSP models.

The lease tests model only typed public getter/setter calls. Actual Unity output
silence and complete MV encoding require execution in the original runtime.
"""
from pathlib import Path
import hashlib
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"
SOURCE = r'''
#include "mp4_timeline_audio.hpp"
#include <cassert>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
using namespace idoly_mp4_timeline_audio;
float value=.375f;bool bindings=true,reject=false;int sets=0,gets=0;
int throw_get=0,throw_set=0;bool throw_after=false,lose_after_set=false;
bool current(void* p){assert(p==&value);return bindings;}
float get(void* p){assert(p==&value);if(++gets==throw_get)throw std::runtime_error("original get");return value;}
void set(void* p,float v){assert(p==&value);++sets;if(sets==throw_set&&!throw_after)throw std::runtime_error("original set");if(!reject)value=v;if(lose_after_set)bindings=false;if(sets==throw_set&&throw_after)throw std::runtime_error("partial original set");}
ListenerApi api(){return {&value,current,get,set};}
struct Source {float pitch=1,spatial=0,pan=0;bool enabled=true,mute=false,loop=false,throw_probe=false;void*clip=nullptr,*mixer=nullptr;int current_calls=0;bool change=false;} source;
bool pcm_current(void* c,void* p){assert(c==&source&&p==&source);return !(source.change&&++source.current_calls==2);}
float pcm_pitch(void*,void*){return source.pitch;}float pcm_spatial(void*,void*){return source.spatial;}float pcm_pan(void*,void*){return source.pan;}
bool pcm_enabled(void*,void*){if(source.throw_probe)throw std::runtime_error("original property");return source.enabled;}
bool pcm_mute(void*,void*){return source.mute;}bool pcm_loop(void*,void*){return source.loop;}
void* pcm_clip(void*,void*){return source.clip;}void* pcm_mixer(void*,void*){return source.mixer;}
int main(int argc,char** argv){assert(argc==2);std::string s=argv[1];ListenerLease lease;
 if(s.rfind("pcm_",0)==0){
  SourcePcmApi p{&source,pcm_current,pcm_pitch,pcm_mute,pcm_loop,pcm_spatial,pcm_pan,pcm_mixer,pcm_clip,pcm_enabled};
  if(s=="pcm_disabled")source.enabled=false;
  if(s=="pcm_mute")source.mute=true;
  if(s=="pcm_loop")source.loop=true;
  if(s=="pcm_pitch")source.pitch=.5f;
  if(s=="pcm_spatial")source.spatial=.5f;
  if(s=="pcm_pan")source.pan=.5f;
  if(s=="pcm_nan_pitch")source.pitch=std::numeric_limits<float>::quiet_NaN();
  if(s=="pcm_nan_spatial")source.spatial=std::numeric_limits<float>::quiet_NaN();
  if(s=="pcm_nan_pan")source.pan=std::numeric_limits<float>::quiet_NaN();
  if(s=="pcm_clip")source.clip=&value;
  if(s=="pcm_mixer")source.mixer=&value;
  if(s=="pcm_changed")source.change=true;
  if(s=="pcm_exception")source.throw_probe=true;
  if(s=="pcm_api")p.pitch=nullptr;
  const char* error=source_pcm_error(p,s=="pcm_null"?nullptr:&source);
  assert((error==nullptr)==(s=="pcm_supported")&&sets==0);
  if(error)assert(std::strncmp(error,"fresh_audio_source_",19)==0);
  return 0;
 }
 auto calls=api();
 if(s=="missing_api"){calls.set_volume=nullptr;assert(lease.begin(calls,7)==ListenerResult::invalid&&!lease.active()&&!sets);return 0;}
 if(s=="zero_token"){assert(lease.begin(calls,0)==ListenerResult::invalid&&!lease.active()&&!sets);return 0;}
 if(s=="source_wait"){bindings=false;assert(lease.begin(calls,7)==ListenerResult::waiting&&!lease.active()&&!sets);bindings=true;}
 if(s=="invalid_volume"){value=std::numeric_limits<float>::quiet_NaN();assert(lease.begin(calls,7)==ListenerResult::failed&&!lease.active()&&!sets);return 0;}
 if(s=="get_throws"){throw_get=1;assert(lease.begin(calls,7)==ListenerResult::failed&&!lease.active()&&!sets);return 0;}
 if(s=="already_silent")value=0;
 if(s=="setter_throws_before"||s=="setter_throws_after"){throw_set=1;throw_after=s=="setter_throws_after";assert(lease.begin(calls,7)==ListenerResult::failed&&lease.active());throw_set=0;auto r=lease.finish(7);assert(r==(throw_after?ListenerResult::ok:ListenerResult::stale));assert(!lease.active()&&value==.375f);return 0;}
 if(s=="rejected_mute"){reject=true;assert(lease.begin(calls,7)==ListenerResult::stale&&lease.active());assert(lease.finish(7)==ListenerResult::stale&&!lease.active()&&value==.375f&&sets==1);return 0;}
 assert(lease.begin(calls,7)==ListenerResult::ok&&lease.active()&&lease.token()==7&&value==0&&sets==1);
 if(s=="wrong_token"){assert(lease.verify(9)==ListenerResult::invalid&&lease.finish(9)==ListenerResult::invalid&&lease.active()&&sets==1);}
 if(s=="duplicate_begin"){assert(lease.begin(calls,7)==ListenerResult::ok&&sets==1);assert(lease.begin(calls,8)==ListenerResult::invalid&&sets==1);}
 if(s=="superseded"){value=.75f;assert(lease.verify(7)==ListenerResult::stale);assert(lease.finish(7)==ListenerResult::stale&&!lease.active()&&value==.75f&&sets==1);return 0;}
 if(s=="verify_wait"||s=="finish_wait"){bindings=false;assert(lease.verify(7)==ListenerResult::waiting);assert(lease.finish(7)==ListenerResult::waiting&&lease.active()&&sets==1);bindings=true;}
 if(s=="verify_throws"){throw_get=gets+1;assert(lease.verify(7)==ListenerResult::failed&&lease.active());throw_get=0;}
 if(s=="restore_throws_before"||s=="restore_throws_after"){throw_set=2;throw_after=s=="restore_throws_after";assert(lease.finish(7)==ListenerResult::failed&&lease.active());throw_set=0;assert(lease.finish(7)==ListenerResult::ok&&!lease.active()&&value==.375f);assert(sets==(throw_after?2:3));return 0;}
 if(s=="restore_rejected"){reject=true;assert(lease.finish(7)==ListenerResult::failed&&lease.active()&&value==0);reject=false;}
 if(s=="restore_source_wait"){lose_after_set=true;assert(lease.finish(7)==ListenerResult::waiting&&lease.active()&&value==.375f);lose_after_set=false;bindings=true;assert(lease.finish(7)==ListenerResult::ok&&!lease.active()&&sets==2);return 0;}
 assert(lease.verify(7)==(s=="restore_rejected"?ListenerResult::invalid:ListenerResult::ok));
 assert(lease.finish(7)==ListenerResult::ok&&!lease.active()&&value==(s=="already_silent"?0:.375f));
 const int done=sets;assert(lease.finish(7)==ListenerResult::ok&&sets==done);
}
'''


@pytest.fixture(scope="module")
def listener_binary(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ host compiler required")
    folder = tmp_path_factory.mktemp("fresh-audio-listener")
    source, binary = folder / "listener.cpp", folder / "listener"
    source.write_text(SOURCE)
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                            "-I", str(NATIVE), str(source), "-o", str(binary)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", [
    "normal", "already_silent", "missing_api", "zero_token", "source_wait", "invalid_volume",
    "get_throws", "setter_throws_before", "setter_throws_after", "rejected_mute", "wrong_token",
    "duplicate_begin", "superseded", "verify_wait", "finish_wait", "verify_throws",
    "restore_throws_before", "restore_throws_after", "restore_rejected", "restore_source_wait",
    "pcm_supported", "pcm_disabled", "pcm_mute", "pcm_loop", "pcm_pitch", "pcm_spatial", "pcm_pan",
    "pcm_nan_pitch", "pcm_nan_spatial", "pcm_nan_pan", "pcm_clip", "pcm_mixer", "pcm_changed",
    "pcm_exception", "pcm_api", "pcm_null",
])
def test_listener_mute_and_global_cleanup_duty(listener_binary, case):
    result = subprocess.run([str(listener_binary), case], capture_output=True, text=True,
                            timeout=15, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                            "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_listener_pins_reproduce_actual_original_static_float_methods():
    directory = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:
        pytest.skip("Set IDOLY_MP4_ORIGINALS_DIR to audit actual original inputs")
    sys.path.insert(0, str(ROOT / "tools"))
    from audit_mp4_game import OriginalAndroid
    from audit_mp4_ios_game import Original
    header = (NATIVE / "mp4_timeline_audio.hpp").read_text()
    for platform, constructor, metadata, native in (
        ("android", OriginalAndroid, "android-metadata.dat", "android-native.so"),
        ("ios", Original, "ios-metadata.dat", "ios-native.bin"),
    ):
        original = constructor((Path(directory) / metadata).read_bytes(), (Path(directory) / native).read_bytes())
        block = re.search(r"ListenerProfile " + platform + r"_listener_profile = \{(.*?)\n\};", header, re.S).group(1)
        assert hashlib.sha256(original.b).hexdigest() in block
        assert hashlib.sha256(original.m).hexdigest() in block
        for name, signature, result in (("get_volume", (), "System.Single"),
                                         ("set_volume", ("System.Single",), "System.Void")):
            method = original.method("UnityEngine.AudioListener", name, len(signature), signature)
            assert method["static"] and method["return"] == result
            pin = "{" + method["rva"] + ",{" + ",".join(f"0x{byte:02x}" for byte in bytes.fromhex(method["prefix"]))
            pin += "}," + method["registration_pointer_slot"] + "," + str(method["metadata_method_index"]) + "}"
            assert pin in block
        source_block = re.search(r"SourcePcmProfile " + platform + r"_source_pcm_profile = \{(.*?)\n\};", header, re.S).group(1)
        for name, result in (("get_pitch", "System.Single"), ("get_mute", "System.Boolean"),
                             ("get_loop", "System.Boolean"), ("get_spatialBlend", "System.Single"),
                             ("get_panStereo", "System.Single"),
                             ("get_outputAudioMixerGroup", "UnityEngine.Audio.AudioMixerGroup"),
                             ("get_clip", "UnityEngine.AudioClip")):
            method = original.method("UnityEngine.AudioSource", name, 0, ())
            assert not method["static"] and method["return"] == result
            pin = "{" + method["rva"] + ",{" + ",".join(f"0x{byte:02x}" for byte in bytes.fromhex(method["prefix"]))
            pin += "}," + method["registration_pointer_slot"] + "," + str(method["metadata_method_index"]) + "}"
            assert pin in source_block
