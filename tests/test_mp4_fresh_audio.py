"""Production listener lease and exact original method pins, without DSP models.

The lease tests model only typed public getter/setter calls. Actual Unity output
silence and complete MV encoding require execution in the original runtime.
"""
from pathlib import Path
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
from zipfile import ZipFile

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
struct Mixer {int master_object=0,bgm_object=0,voice_object=0,foreign_object=0,foreign_mixer=0;
 float master=-6.0206f,bus=-12.0412f;bool current=true,missing=false,throw_probe=false;
 bool change=false,change_identity=false,bad_conversion=false;int reads=0;} mixer;
bool mixer_current(void*c){assert(c==&mixer);return mixer.current;}
void* mixer_object(void*){return &mixer.master_object;}
void* mixer_bgm(void*){return mixer.change_identity&&mixer.reads?&mixer.foreign_object:&mixer.bgm_object;}
void* mixer_voice(void*){return &mixer.voice_object;}
void* mixer_owner(void*,void*g){return g==&mixer.foreign_mixer?&mixer.foreign_mixer:&mixer.master_object;}
bool mixer_float(void*,void*m,const char*n,float*v){assert(m==&mixer.master_object);
 if(mixer.throw_probe)throw std::runtime_error("original mixer property");
 ++mixer.reads;if(mixer.missing)return false;
 assert(!std::strcmp(n,"Master_Volume")||!std::strcmp(n,"BGM_Volume")||!std::strcmp(n,"Voice_Volume"));
 *v=!std::strcmp(n,"Master_Volume")?mixer.master:mixer.bus;
 if(mixer.change&&mixer.reads>2)*v+=1;
 return true;}
float mixer_volume(void*,float db){return mixer.bad_conversion?std::numeric_limits<float>::quiet_NaN():db==-80?0:std::pow(10.f,db*.05f);}
DefaultMixerApi mixer_api(){return {&mixer,mixer_current,mixer_object,mixer_bgm,mixer_voice,mixer_owner,mixer_float,mixer_volume};}
const char* pcm_route(void*,void*g,float*v){return default_mixer_gain(mixer_api(),g,v);}
const char* pcm_missing_gain(void*,void*,float*){return nullptr;}
int main(int argc,char** argv){assert(argc==2);std::string s=argv[1];ListenerLease lease;
 if(s.rfind("mixer_",0)==0){
  void*group=&mixer.bgm_object;float gain=-1;auto calls=mixer_api();
  if(s=="mixer_voice")group=&mixer.voice_object;
  // A same-named ADV BGMAudioMixer's group is still a distinct object.
  if(s=="mixer_adv_bgm")group=&mixer.foreign_object;
  if(s=="mixer_foreign_owner")group=&mixer.foreign_mixer;
  if(s=="mixer_unavailable")mixer.current=false;
  if(s=="mixer_missing")mixer.missing=true;
  if(s=="mixer_exception")mixer.throw_probe=true;
  if(s=="mixer_changed")mixer.change=true;
  if(s=="mixer_identity_changed")mixer.change_identity=true;
  if(s=="mixer_nan")mixer.bus=std::numeric_limits<float>::quiet_NaN();
  if(s=="mixer_below_floor")mixer.bus=-81;
  if(s=="mixer_above_unity")mixer.bus=1;
  if(s=="mixer_bad_conversion")mixer.bad_conversion=true;
  if(s=="mixer_zero_bus")mixer.bus=-80;
  if(s=="mixer_zero_master")mixer.master=-80;
  if(s=="mixer_api")calls.get_float=nullptr;
  const char*error=default_mixer_gain(calls,group,&gain);
  bool ok=s=="mixer_bgm"||s=="mixer_voice"||s=="mixer_zero_bus"||s=="mixer_zero_master";
  assert((error==nullptr)==ok&&sets==0);
  if(!ok)assert(gain==-1);
  else if(s=="mixer_zero_bus"||s=="mixer_zero_master")assert(gain==0);
  else assert(std::fabs(gain-.125f)<1e-6f);
  return 0;
 }
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
  if(s=="pcm_common_mixer"){source.mixer=&mixer.bgm_object;p.mixer_gain=pcm_route;}
  if(s=="pcm_mixer_no_gain"){source.mixer=&mixer.bgm_object;p.mixer_gain=pcm_missing_gain;}
  if(s=="pcm_changed")source.change=true;
  if(s=="pcm_exception")source.throw_probe=true;
  if(s=="pcm_api")p.pitch=nullptr;
  float route_gain=-1;
  const char* error=source_pcm_error(p,s=="pcm_null"?nullptr:&source,&route_gain);
  assert((error==nullptr)==(s=="pcm_supported"||s=="pcm_common_mixer")&&sets==0);
  if(!error)assert(std::fabs(route_gain-(s=="pcm_supported"?1:.125f))<1e-6f);
  else assert(route_gain==-1);
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
    "pcm_exception", "pcm_api", "pcm_null", "pcm_common_mixer", "pcm_mixer_no_gain",
    "mixer_bgm", "mixer_voice", "mixer_adv_bgm", "mixer_foreign_owner", "mixer_unavailable",
    "mixer_missing", "mixer_exception", "mixer_changed", "mixer_identity_changed", "mixer_nan",
    "mixer_below_floor", "mixer_above_unity", "mixer_bad_conversion", "mixer_zero_bus",
    "mixer_zero_master", "mixer_api",
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
        mixer_block = re.search(r"DefaultMixerProfile " + platform + r"_default_mixer_profile = \{(.*?)\n\};", header, re.S).group(1)
        for owner, name, signature, result, static in (
            ("Qua.Sound.DefaultMixer", "get_Mixer", (), "UnityEngine.Audio.AudioMixer", True),
            ("Qua.Sound.DefaultMixer", "get_BGM", (), "UnityEngine.Audio.AudioMixerGroup", True),
            ("Qua.Sound.DefaultMixer", "get_Voice", (), "UnityEngine.Audio.AudioMixerGroup", True),
            ("UnityEngine.Audio.AudioMixer", "GetFloat", ("System.String", "System.Single&"), "System.Boolean", False),
            ("UnityEngine.Audio.AudioMixerGroup", "get_audioMixer", (), "UnityEngine.Audio.AudioMixer", False),
            ("Qua.Sound.Utility.VolumeUtility", "LoudnessToVolume", ("System.Single",), "System.Single", True),
        ):
            method = original.method(owner, name, len(signature), signature)
            assert method["static"] == static and method["return"] == result
            pin = "{" + method["rva"] + ",{" + ",".join(f"0x{byte:02x}" for byte in bytes.fromhex(method["prefix"]))
            pin += "}," + method["registration_pointer_slot"] + "," + str(method["metadata_method_index"]) + "}"
            assert pin in mixer_block
        # The ordinary built-player source overrides serialized null output
        # groups. Verify the actual two getter -> setter call sequences which
        # caused log27's rejection, rather than only testing invented routes.
        calls = {
            "android": ((0x888DDD4, 0x87A3E98), (0x888DDE8, 0x8F30A90),
                        (0x888DDF4, 0x87A4090), (0x888DE08, 0x8F30A90)),
            "ios": ((0x6FEECF0, 0x6EDE2F8), (0x6FEED04, 0x77E13A8),
                    (0x6FEED10, 0x6EDE6D8), (0x6FEED24, 0x77E13A8)),
        }[platform]
        for call, target in calls:
            word = struct.unpack_from("<I", original.b, original.offset(call))[0]
            displacement = word & 0x3FFFFFF
            if displacement & (1 << 25):
                displacement -= 1 << 26
            assert word >> 26 == 0b100101 and call + 4 * displacement == target


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_actual_original_default_mixer_is_gain_only(platform):
    UnityPy = pytest.importorskip("UnityPy")
    directory = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:
        pytest.skip("Set IDOLY_MP4_ORIGINALS_DIR for pinned original assets")
    directory = Path(directory)
    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.57f1"
    if platform == "android":
        apk = Path(os.environ.get("IDOLY_MP4_ORIGINAL_ANDROID_APK", str(directory / "original-base.apk")))
        if not apk.is_file():
            pytest.skip("Pinned original Android APK is optional")
        members = {
            "assets/bin/Data/23a6d7406461147f3abcc2bb48590ac4":
                (944, "af1d8d12b0539d8768b6f4f8572cbfc5cafbeeac78a4cc373d3475e845f33cf1"),
            "assets/bin/Data/8803fb47121ac4d13b8343ac3a31beef":
                (688, "80c8c30ad146395e30fc87f897681d56d94e83e28f460882ebf55002b254128f"),
        }
        environments = []
        with ZipFile(apk) as archive:
            for name, (size, digest) in members.items():
                raw = archive.read(name)
                assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest
                environments.append(UnityPy.load(raw))
    else:
        resources = Path(os.environ.get("IDOLY_MP4_IOS_RESOURCES_ASSETS", str(
            directory.parent / "mp4-renderer-program-audit/ios-original-assets/resources.assets")))
        if not resources.is_file():
            pytest.skip("Pinned original iOS resources.assets is optional")
        raw = resources.read_bytes()
        assert len(raw) == 65784784
        assert hashlib.sha256(raw).hexdigest() == "decc41f679e31e4ff9708bea2f66b9bcbd53ff560aeeaa4c38092550c356a38b"
        environments = [UnityPy.load(raw)]
    controllers = {}
    for environment in environments:
        for obj in environment.objects:
            if obj.type.name != "AudioMixerController":
                continue
            tree = obj.read_typetree()
            assert tree["m_Name"] not in controllers
            controllers[tree["m_Name"]] = tree
    default = controllers["DefaultMixer"]
    constant = default["m_MixerConstant"]
    assert default["m_OutputGroup"]["m_PathID"] == 0
    assert constant["effects"] == constant["effectGUIDs"] == []
    assert constant["numSideChainBuffers"] == 0
    assert bytes(constant["groupNameBuffer"]).rstrip(b"\0").split(b"\0") == [b"Master", b"SE", b"Voice", b"BGM"]
    assert [group["parentConstantIndex"] for group in constant["groups"]] == [-1, 0, 0, 0]
    assert [group["volumeIndex"] for group in constant["groups"]] == [0, 2, 4, 6]
    assert [group["pitchIndex"] for group in constant["groups"]] == [1, 3, 5, 7]
    assert all(not group["mute"] and not group["solo"] for group in constant["groups"])
    assert len(constant["snapshots"]) == 1
    assert constant["snapshots"][0]["values"] == [0., 1., 0., 1., 0., 1., 0., 1.]
    assert constant["exposedParameterIndices"] == [6, 0, 2, 4]
    assert constant["exposedParameterNames"] == [2882008588, 4238877747, 381834625, 1640077164]
    # An ADV mixer also contains "BGM" in its name, but has a real enabled DSP
    # effect. Runtime admission must use original DefaultMixer group identity.
    adv = controllers["BGMAudioMixer"]["m_MixerConstant"]
    assert any(effect["type"] == 11 and not effect["bypass"] for effect in adv["effects"])
