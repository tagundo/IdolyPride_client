"""Real C++ MP4 session -> Python broker IPC, with fake Unity and encoder APIs.

The production session header and production game adapter execute unchanged.
Only the platform codec/GPU/Unity method callbacks are synthetic; these tests
verify wire identity, scheduling, PCM mixing, backpressure and ownership. They
do not establish a playable MP4 or actual device decode/render correctness.
"""
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time

import pytest

from idoly_local import mp4_audio_broker as broker_module
from idoly_local.mp4_audio_broker import MP4AudioBroker
from test_mp4_audio_broker import make_store, eventually
from test_mp4_audio_bundle import NAME, bundle, masked
from test_mp4_game_adapter import SOURCE as ADAPTER_SOURCE
from test_shared_resource_store import Response

ROOT = Path(__file__).resolve().parents[1]

# Reuse the separate adapter test's managed-heap fake, not a copy of session
# logic. Override selected callbacks through the actual production Api table.
PRELUDE = """
#include <initializer_list>
#include <new>
#include <cstddef>
#include <cstdint>
#include <cmath>
#include <cstdarg>
#include <cstring>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#include <fstream>
#include <iostream>
#include <thread>
const char* fault_case="";
bool foreign_created=false;
int host_openat(int directory,const char* name,int flags,...){
    int mode=0;va_list arguments;va_start(arguments,flags);
    if(flags&O_CREAT){mode=va_arg(arguments,int);}va_end(arguments);
    const size_t length=std::strlen(name);
    bool pcm=!std::strcmp(fault_case,"foreign_pcm")&&length>=4&&!std::strcmp(name+length-4,".pcm");
    bool temporary=!std::strcmp(fault_case,"foreign_tmp")&&length>=4&&!std::strcmp(name+length-4,".tmp");
    if(!foreign_created&&(flags&O_EXCL)&&(pcm||temporary)){
        int foreign=::openat(directory,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
        if(foreign<0)return -1;
        const char text[]="FOREIGN_FILE_MUST_SURVIVE";
        if(::write(foreign,text,sizeof(text)-1)!=static_cast<ssize_t>(sizeof(text)-1)){::close(foreign);return -1;}
        ::close(foreign);foreign_created=true;errno=EEXIST;return -1;
    }
    return (flags&O_CREAT) ? ::openat(directory,name,flags,mode) : ::openat(directory,name,flags);
}
#define openat host_openat
"""
BASE = ADAPTER_SOURCE.split("int main(){", 1)[0].replace(
    '#include "mp4_game_adapter.hpp"', '#include "mp4_runtime.hpp"')
HARNESS = r'''
#undef openat
namespace session_core = idoly_mp4_runtime;
int sample_rate=48000,fps=30,loads=0,data_calls=0,retries=0,destroy_retries=0;
double selected_duration=1.0001;
std::string scenario,output_root,last_bundle;
std::vector<void*> selected_tracks;
std::map<void*,std::vector<void*>> scheduled_clips;
std::vector<std::string> loaded_bundles;
std::vector<std::array<int,3>> read_offsets;
std::vector<double> submitted_times;
std::vector<float> camera_deltas;
unsigned delayed_ticks=0;
bool was_cancelled=false,private_lifetime_verified=false;
bool cancel_marker_written=false;
unsigned suspension_checks=0,source_wait_checks=0;
bool source_geometry_valid=true;
bool session_source_geometry(void* controller,int32_t* width,int32_t* height){assert(controller==ptr(camera_controller));if(!source_geometry_valid)return false;*width=16;*height=16;return true;}
double session_duration(void*,Method*){return selected_duration;}
int32_t session_samples(void*,Method*){return sample_rate*2;}
int32_t session_rate(void*,Method*){return sample_rate;}
void session_brain_update(void* object,Method*){
    float delta=0;assert(object==ptr(brain)&&session_core::camera_delta_override(object,&delta));
    assert(std::isfinite(delta)&&(delta==-1||delta>0));
    float other=0;assert(!session_core::camera_delta_override(ptr(bgm),&other));
    camera_deltas.push_back(delta);
}
bool session_camera_clock_ok(){return true;}
void* session_tracks(void*,Method*){auto* a=make("array");a->array_kind=1;a->pointers=selected_tracks;return ptr(a);}
void* session_clips(void* object,Method*){auto* a=make("array");a->array_kind=1;a->pointers=scheduled_clips.at(object);return ptr(a);}
void* session_load_bundle(void* path,Method*){
    std::string value=objects.at(path)->name;last_bundle=value;loaded_bundles.push_back(value);++loads;
    int fd=open(value.c_str(),O_RDONLY|O_NOFOLLOW);struct stat info{};
    assert(fd>=0&&fstat(fd,&info)==0&&(info.st_mode&0777)==0400&&info.st_nlink==1);
    char magic[8]{};assert(read(fd,magic,8)==8&&!memcmp(magic,"UnityFS",7));close(fd);
    done=scenario!="cancel_load";return ptr(request);
}
bool session_get_data(void* object,void* array,int32_t offset,Method*){
    assert(object==ptr(private_clip));auto& values=objects.at(array)->floats;
    const int frames=static_cast<int>(values.size()/2);assert(frames>0&&frames<=8192);
    assert(offset>=0&&offset<=sample_rate*2-frames);
    read_offsets.push_back({loads,offset,frames});++data_calls;
    for(int i=0;i<frames;++i){
        if(scenario=="overlap")values[static_cast<size_t>(i)*2]=values[static_cast<size_t>(i)*2+1]=loads==1?.6f:-.4f;
        else if(scenario=="silent")values[static_cast<size_t>(i)*2]=values[static_cast<size_t>(i)*2+1]=0;
        else {float value=static_cast<float>(offset+i)*.00001f;values[static_cast<size_t>(i)*2]=value;values[static_cast<size_t>(i)*2+1]=-value*.5f;}
    }return true;
}
void session_unload(void* object,bool all,Method* method){
    assert(done&&!last_bundle.empty()&&access(last_bundle.c_str(),F_OK)==0);
    private_lifetime_verified=true;unload(object,all,method);
}
void connect_scene(){
    setup();if(!camera_track)camera_track=make(".CinemachineTrack");if(!brain)brain=make("Cinemachine.CinemachineBrain");
    write(presenter,0xe0,ptr(player));write(player,0x38,ptr(controller));write(controller,0x20,ptr(director));
    write(player,0x28,ptr(bgm));write(player,0x30,ptr(voice));
    write(camera_controller,0x50,ptr(camera));write(camera_controller,0xa0,ptr(wrapper));write(wrapper,0x10,ptr(rt));
    auto* playable=make("UnityEngine.Timeline.AudioPlayableAsset");
    auto* mixer=make("UnityEngine.Timeline.AudioMixerProperties");
    auto* properties=make("UnityEngine.Timeline.AudioClipProperties");
    write(mixer,0x10,scenario=="overlap"?2.f:.5f);write(properties,0x10,1.f);
    write(track,0xa0,ptr(mixer));write(clip,0x28,ptr(playable));write(playable,0x18,ptr(source_clip));
    write(playable,0x28,ptr(properties));write(clip,0x18,.1);write(clip,0x20,.2);
    write(clip,0x30,scenario=="overlap"?.5:.6);write(clip,0x38,1.0);write(clip,0x58,-1.0);write(clip,0x60,-1.0);
    selected_tracks={ptr(track),ptr(camera_track)};scheduled_clips[ptr(track)]={ptr(clip)};
    if(scenario=="overlap"){
        auto* voice_track=make("UnityEngine.Timeline.AudioTrack","Voice");
        auto* voice_clip=make("UnityEngine.Timeline.TimelineClip");
        auto* voice_playable=make("UnityEngine.Timeline.AudioPlayableAsset");
        auto* voice_mixer=make("UnityEngine.Timeline.AudioMixerProperties");
        auto* voice_properties=make("UnityEngine.Timeline.AudioClipProperties");
        write(voice_mixer,0x10,1.f);write(voice_properties,0x10,1.f);
        write(voice_track,0xa0,ptr(voice_mixer));write(voice_clip,0x28,ptr(voice_playable));
        write(voice_playable,0x18,ptr(source_clip));write(voice_playable,0x28,ptr(voice_properties));
        write(voice_clip,0x18,.1);write(voice_clip,0x20,0.0);write(voice_clip,0x30,.5);
        write(voice_clip,0x38,1.0);write(voice_clip,0x58,-1.0);write(voice_clip,0x60,-1.0);
        selected_tracks.push_back(ptr(voice_track));scheduled_clips[ptr(voice_track)]={ptr(voice_clip)};
    }
    write(brain,0x30,int32_t(1));write(brain,0x34,int32_t(0));
    bgm_volume=voice_volume=1.f;time_value=.37;mode=0;shader=4;custom=false;
}
struct FakeEncoder {IDMP4EncoderConfig config{};std::string pcm,partial,final;
    uint64_t frames=0;uint32_t phase=IDMP4_ENCODING;unsigned destroy_calls=0;bool retry=true;};
extern "C" IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig* c,char*,size_t){
    assert(c&&c->abi_version==1&&c->width==16&&c->height==16&&c->audio_channels==2);
    assert(c->audio_sample_rate==static_cast<uint32_t>(sample_rate));
    assert(c->audio_sample_frames==static_cast<uint64_t>(std::llround(selected_duration*sample_rate)));
    auto* e=new FakeEncoder;e->config=*c;e->pcm=c->pcm_f32_path;e->partial=c->partial_path;e->final=c->final_path;
    int input=open(e->pcm.c_str(),O_RDONLY|O_NOFOLLOW);assert(input>=0);
    int output=open((output_root+"/observed.pcm").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);assert(output>=0);
    char bytes[4096];ssize_t n=0;while((n=read(input,bytes,sizeof(bytes)))>0)assert(write(output,bytes,static_cast<size_t>(n))==n);assert(n==0);
    close(input);close(output);
    int partial=open(e->partial.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);assert(partial>=0);
    assert(write(partial,"FAKE_SESSION_CODEC",18)==18);close(partial);return e;
}
extern "C" int IDMP4EncoderAppendFrame(IDMP4EncoderHandle value,const uint8_t* rgba,size_t row,uint64_t index){
    auto* e=static_cast<FakeEncoder*>(value);assert(index==e->frames&&row==64&&rgba[0]==15&&rgba[3]==255);
    assert(std::fabs(time_value-static_cast<double>(index)/fps)<1e-6);
    if(scenario=="encoder_failure"&&index==2)return IDMP4_ERROR;
    if(e->retry){e->retry=false;++retries;return IDMP4_RETRY;}
    e->retry=true;submitted_times.push_back(time_value);++e->frames;return IDMP4_ACCEPTED;
}
extern "C" int IDMP4EncoderPoll(IDMP4EncoderHandle value,IDMP4EncoderStatus* s){
    auto* e=static_cast<FakeEncoder*>(value);assert(s&&s->abi_version==1);
    s->phase=e->phase;s->submitted_frames=s->encoded_frames=e->frames;
    s->audio_frames=e->config.audio_sample_frames;s->bytes_written=18+e->frames;return IDMP4_ACCEPTED;
}
extern "C" int IDMP4EncoderFinish(IDMP4EncoderHandle value){
    auto* e=static_cast<FakeEncoder*>(value);assert(e->frames==e->config.video_frame_count);
    assert(rename(e->partial.c_str(),e->final.c_str())==0);e->phase=IDMP4_COMPLETED;return IDMP4_ACCEPTED;
}
extern "C" void IDMP4EncoderCancel(IDMP4EncoderHandle value){
    auto* e=static_cast<FakeEncoder*>(value);e->phase=IDMP4_CANCELLED;unlink(e->partial.c_str());
}
extern "C" int IDMP4EncoderDestroy(IDMP4EncoderHandle value){
    auto* e=static_cast<FakeEncoder*>(value);
    assert(e->phase==IDMP4_COMPLETED||e->phase==IDMP4_CANCELLED);
    assert(access(e->pcm.c_str(),F_OK)==0);
    if(e->destroy_calls++<2){++destroy_retries;return IDMP4_RETRY;}delete e;return IDMP4_ACCEPTED;
}
void check_suspension(bool cancel_parked=false){
    const auto stage=session_core::job.stage;const uint64_t frame=session_core::job.frame,mixed=session_core::job.mixed;
    const size_t clip_index=session_core::job.clip;const int before_data=data_calls,before_loads=loads;
    const size_t before_frames=submitted_times.size();const int before_graph=graph_steps,before_actor=actor_steps;
    const double before_time=time_value;char state[2048]{};
    std::thread requester([]{IDMP4SessionSuspend(IDMP4_PAUSE_LIFECYCLE_BACKGROUND);});requester.join();
    assert(IDMP4SessionStatus(state,sizeof(state))&&std::strstr(state,"\"phase\":\"pausing\"")
        &&std::strstr(state,"\"paused\":false")&&std::strstr(state,"\"pause_requested\":true"));
    // No managed method may run on the host thread, including while paused.
    std::thread invalid([]{IDMP4SessionSuspend(99);});invalid.join();
    for(unsigned i=0;i<6;++i){
        // Simulate suspension longer than both watchdogs without sleeping.
        session_core::job.activity=session_core::milliseconds()-180000;
        session_core::on_unity_tick();
        assert(session_core::job.stage==stage&&session_core::job.frame==frame&&session_core::job.mixed==mixed
            &&session_core::job.clip==clip_index&&data_calls==before_data&&loads==before_loads
            &&submitted_times.size()==before_frames&&graph_steps==before_graph&&actor_steps==before_actor
            &&time_value==before_time);
        assert(IDMP4SessionStatus(state,sizeof(state))&&std::strstr(state,"\"phase\":\"paused\"")
            &&std::strstr(state,"\"paused\":true")&&std::strstr(state,"\"pause_reason\":\"lifecycle_background\""));
        if(i==2&&scenario=="pause_capture_arrives"){
            auto* pass=make("VL.Rendering.VLCapturePass");auto* rendering=make("RenderingData");
            write(rendering,0x90,ptr(camera));write(rendering,0x158,uint8_t(1));
            session_core::capture_pass_did_execute(ptr(pass),ptr(rendering));
            session_core::camera_did_render(ptr(camera));
            assert(session_core::job.captured&&session_core::job.frame==frame);
        }
    }
    if(cancel_parked){IDMP4SessionCancel();was_cancelled=true;}
    else {
        std::thread resumed([]{IDMP4SessionResume();IDMP4SessionResume();});resumed.join();
        assert(IDMP4SessionStatus(state,sizeof(state))&&!std::strstr(state,"\"phase\":\"paused\"")
            &&std::strstr(state,"\"pause_requested\":false")&&std::strstr(state,"\"pause_reason\":\"none\""));
    }
    ++suspension_checks;
}
int main(int argc,char** argv){
    assert(argc==9);const char* directory=argv[1];uint64_t epoch=std::strtoull(argv[2],nullptr,10);
    output_root=argv[4];int platform=std::atoi(argv[5]);sample_rate=std::atoi(argv[6]);fps=std::atoi(argv[7]);scenario=argv[8];fault_case=argv[8];
    connect_scene();Api selected=api();selected.director_get_duration=session_duration;
    selected.audio_clip_samples=session_samples;selected.audio_clip_frequency=session_rate;
    selected.timeline_get_tracks=session_tracks;selected.track_get_clips=session_clips;
    selected.bundle_load_file_async=session_load_bundle;selected.audio_clip_get_data=session_get_data;
    selected.bundle_unload=session_unload;
    selected.brain_manual_update=session_brain_update;selected.camera_clock_ok=session_camera_clock_ok;
    if(scenario=="source_lost_before_begin")selected.source_geometry=session_source_geometry;
    session_core::install_game_api(selected,Layout{});session_core::observe_presenter(ptr(presenter));session_core::observe_camera_controller(ptr(camera_controller));
    session_core::on_unity_tick();
    bool configured=session_core::configure(directory,epoch,argv[3],output_root.c_str(),platform);
    if(!configured){std::printf("{\"configured\":false}\n");return 0;}
    assert(session_core::start({static_cast<uint32_t>(fps),1,1,16000000,192000}));
    if(scenario=="source_lost_before_begin"){
        const int graphs=graph_steps,actors=actor_steps,before_loads=loads,before_data=data_calls;const double before=time_value;
        source_geometry_valid=false;
        for(int i=0;i<4;++i){
            session_core::on_unity_tick();char waiting[2048]{};
            assert(session_core::start_pending&&session_core::control_busy&&!session_core::busy_stage());
            assert(graph_steps==graphs&&actor_steps==actors&&loads==before_loads&&data_calls==before_data&&time_value==before);
            assert(IDMP4SessionStatus(waiting,sizeof(waiting))&&std::strstr(waiting,"\"ready\":false")&&std::strstr(waiting,"\"readiness_error\":\"selected_capture_geometry_not_ready\""));
            ++source_wait_checks;
        }
        source_geometry_valid=true;
    }
    if(scenario=="pause_before_start"||scenario=="pause_before_start_cancel")
        check_suspension(scenario=="pause_before_start_cancel");
    auto* pass=make("VL.Rendering.VLCapturePass");auto* rendering=make("RenderingData");
    write(rendering,0x90,ptr(camera));write(rendering,0x158,uint8_t(1));
    uint64_t deadline=session_core::milliseconds()+15000;
    do{
        if(!suspension_checks){
            using S=session_core::Stage;const auto s=session_core::job.stage;
            const bool pause=(scenario=="pause_audio_response"&&s==S::audio_response)
                ||(scenario=="pause_audio_load"&&s==S::audio_load)
                ||(scenario=="pause_audio_mix"&&s==S::audio_mix)
                ||(scenario=="pause_audio_finalize"&&s==S::audio_finalize)
                ||(scenario=="pause_frame_request"&&s==S::frame_request)
                ||(scenario=="pause_frame_wait"&&s==S::frame_wait)
                ||(scenario=="pause_frame_submit"&&s==S::frame_submit&&session_core::job.frame==2)
                ||(scenario=="pause_cancel"&&s==S::frame_submit&&session_core::job.frame==2);
            if(pause)check_suspension(scenario=="pause_cancel");
            if(scenario=="pause_before_ack"&&s==S::frame_wait){
                IDMP4SessionSuspend(IDMP4_PAUSE_SURFACE_UNAVAILABLE);
                session_core::job.activity=session_core::milliseconds()-180000;
                // The original engine stops before acknowledging. Its first
                // resumed tick must not time out an otherwise owned capture.
                IDMP4SessionResume();++suspension_checks;
            }
        }
        session_core::on_unity_tick();
        if(session_core::job.stage==session_core::Stage::frame_wait&&!session_core::job.captured){
            if(!suspension_checks&&(scenario=="pause_capture_pending"||scenario=="pause_capture_arrives"))
                check_suspension();
            if(scenario=="capture_missing")session_core::job.activity=session_core::milliseconds()-6000;
            else {session_core::capture_pass_did_execute(ptr(pass),ptr(rendering));session_core::camera_did_render(ptr(camera));}
        }
        if(scenario=="cancel_load"&&session_core::job.stage==session_core::Stage::audio_load&&!was_cancelled){session_core::cancel();was_cancelled=true;}
        if(scenario=="cancel_response"&&session_core::job.stage==session_core::Stage::audio_response&&!was_cancelled){session_core::cancel();was_cancelled=true;}
        if(scenario=="cancel_response"&&was_cancelled&&!cancel_marker_written&&session_core::job.stage==session_core::Stage::retiring){
            assert(session_core::job.pending_broker&&loads==0&&mode==0&&std::fabs(time_value-.37)<1e-9);
            int marker=open((output_root+"/cancel-observed").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
            assert(marker>=0&&write(marker,"WAITING_FOR_BROKER",18)==18);close(marker);cancel_marker_written=true;
        }
        if(scenario=="cancel_load"&&was_cancelled&&!done){assert(access(last_bundle.c_str(),F_OK)==0);if(++delayed_ticks==25)done=true;}
        timespec pause{0,1000000};nanosleep(&pause,nullptr);
        if(session_core::milliseconds()>deadline)return 3;
    }while(session_core::control_busy||session_core::busy_stage());
    for(unsigned i=0;i<30;++i){session_core::on_unity_tick();timespec pause{0,1000000};nanosleep(&pause,nullptr);}
    assert(mode==0&&std::fabs(time_value-.37)<1e-9&&bgm_volume==1&&voice_volume==1&&!custom&&actor_mode==1);
    int32_t brain_mode=-1,brain_blend=-1;std::memcpy(&brain_mode,brain->mem.data()+0x30,4);std::memcpy(&brain_blend,brain->mem.data()+0x34,4);
    assert(brain_mode==1&&brain_blend==0);float outside=0;assert(!session_core::camera_delta_override(ptr(brain),&outside));
    for(const auto& path:loaded_bundles)assert(access(path.c_str(),F_OK)!=0);
    char status[2048]{};assert(session_core::status(status,sizeof(status)));
    std::printf("{\"configured\":true,\"source_wait_checks\":%u,\"session\":%s,\"loads\":%d,\"unloads\":%d,\"data_calls\":%d,\"retries\":%d,\"destroy_retries\":%d,\"graph_steps\":%d,\"actor_steps\":%d,\"private_lifetime_verified\":%s,\"delayed_ticks\":%u,\"suspension_checks\":%u,\"times\":[",
        source_wait_checks,status,loads,unloads,data_calls,retries,destroy_retries,graph_steps,actor_steps,private_lifetime_verified?"true":"false",delayed_ticks,suspension_checks);
    for(size_t i=0;i<submitted_times.size();++i)std::printf("%s%.12f",i?",":"",submitted_times[i]);
    std::printf("],\"camera_deltas\":[");
    for(size_t i=0;i<camera_deltas.size();++i)std::printf("%s%.12f",i?",":"",camera_deltas[i]);
    std::printf("],\"offsets\":[");
    for(size_t i=0;i<read_offsets.size();++i)std::printf("%s[%d,%d,%d]",i?",":"",read_offsets[i][0],read_offsets[i][1],read_offsets[i][2]);
    std::puts("]}");session_core::game.reset_observations();assert(handles.empty());session_core::close_configuration(session_core::configured);return 0;
}
'''


@pytest.fixture(scope="module")
def session_executable(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Host C++ compiler required for the actual MP4 session")
    root = tmp_path_factory.mktemp("mp4-session-host")
    source, binary = root / "session.cpp", root / "session"
    source.write_text(PRELUDE + BASE + HARNESS)
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.fixture
def run_session(tmp_path, session_executable, monkeypatch):
    resources = []
    def run(scenario="single", *, rate=48000, fps=30, platform="android", output=None, corrupt=None, retired=False, fifo_active=False):
        body = masked(bundle(platform=13 if platform=="android" else 9,
            audio_values={"frequency":rate,"length":2.0}), NAME)
        entered, release=threading.Event(),threading.Event()
        delayed_calls=[]
        def delayed_fetch(url, **_):
            delayed_calls.append(url);entered.set();assert release.wait(5)
            return Response(body)
        store, cache, record, calls, original = make_store(tmp_path, body, platform=platform,
            fetcher=delayed_fetch if scenario=="cancel_response" else None)
        if scenario=="cancel_response":
            calls=delayed_calls
        broker = MP4AudioBroker(store, tmp_path)
        resources.append((broker, store, cache))
        configuration = broker.configuration()
        if corrupt:
            def bad_response(request, status):
                if corrupt=="fifo":
                    os.mkfifo(Path(configuration["directory"])/"rsp"/(request.request_id.hex()+".rsp"),0o600)
                    return
                capability = bytes(16) if corrupt=="capability" else broker._capability
                request_id = bytes(16) if corrupt=="request_id" else request.request_id
                epoch = broker._epoch+1 if corrupt=="epoch" else broker._epoch
                raw = broker_module.RESPONSE.pack(broker_module.RESPONSE_MAGIC,1,status,0,epoch,capability,request_id)
                broker._publish("rsp", request.request_id.hex()+".rsp", raw,0o600)
            monkeypatch.setattr(broker,"_respond",bad_response)
        if retired:
            broker.close()
        if fifo_active:
            active=Path(configuration["directory"])/"active"
            active.unlink();os.mkfifo(active,0o600)
        final_root = str(output or configuration["export_directory"])
        began=time.monotonic()
        arguments=[str(session_executable), configuration["directory"], str(configuration["epoch"]),
            configuration["capability"], final_root, "1" if platform=="android" else "2", str(rate), str(fps), scenario]
        if scenario=="cancel_response":
            process=subprocess.Popen(arguments,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                assert entered.wait(3)
                eventually(lambda:(Path(final_root)/"cancel-observed").is_file())
                assert process.poll() is None and not list((Path(configuration["directory"])/"prepared").iterdir())
            finally:
                release.set()
            stdout,stderr=process.communicate(timeout=20)
            completed=subprocess.CompletedProcess(arguments,process.returncode,stdout,stderr)
        else:
            completed = subprocess.run(arguments,capture_output=True,text=True,timeout=20)
        assert completed.returncode == 0, completed.stderr
        observed = json.loads(completed.stdout)
        observed.update(configuration=configuration, broker=broker, record=record, calls=calls,
            store=store, cache=cache, original=original, elapsed=time.monotonic()-began)
        return observed
    yield run
    for broker, store, cache in resources:
        broker.close(); store.close(); cache.close()
        eventually(lambda broker=broker: not broker._fds)


@pytest.mark.parametrize("rate,fps,platform", [(48000,30,"android"),(44100,60,"android"),(48000,60,"ios")])
def test_actual_session_ipc_offsets_lead_tail_rational_clock_and_backpressure(run_session, rate, fps, platform):
    observed = run_session(rate=rate, fps=fps, platform=platform)
    session, configuration = observed["session"], observed["configuration"]
    total = round(1.0001*rate); count = math.ceil(total*fps/rate)
    assert session["phase"]=="completed" and session["error_code"]=="none"
    assert session["frames"]==session["total_frames"]==count
    assert session["total_audio_frames"]==total
    assert observed["loads"]==observed["unloads"]==1 and observed["private_lifetime_verified"]
    assert observed["retries"]==count and observed["destroy_retries"]==2
    assert observed["graph_steps"]==count-1
    assert observed["actor_steps"]==count-1
    # Unity's PlayableGraph Evaluate ABI takes float delta; encoder PTS still
    # comes from the exact frame index/fps rather than this observed clock.
    assert observed["times"]==pytest.approx([index/fps for index in range(count)], abs=1e-7)
    assert observed["camera_deltas"][0]==observed["camera_deltas"][-1]==-1
    assert observed["camera_deltas"][1:-1]==pytest.approx([1/fps]*(count-1),abs=1e-8)
    exports=Path(configuration["export_directory"])
    raw=(exports/"observed.pcm").read_bytes()
    assert len(raw)==total*8
    values=list(struct.iter_unpack("<ff",raw))
    start, source, frames=round(.1*rate),round(.2*rate),round(.6*rate)
    for index,(left,right) in enumerate(values):
        sample=(source+index-start)*.00001*.5 if start<=index<start+frames else 0
        assert left==pytest.approx(sample,abs=2e-7) and right==pytest.approx(-sample*.5,abs=2e-7)
    offsets=observed["offsets"]
    assert offsets[0]==[1,source,min(8192,frames)]
    assert sum(item[2] for item in offsets)==frames and all(0<item[2]<=8192 for item in offsets)
    assert len(list(exports.glob("*.mp4")))==1 and not list(exports.glob("*.partial.mp4"))
    assert not list(exports.glob("*.pcm")) or list(exports.glob("*.pcm"))==[exports/"observed.pcm"]
    assert list((Path(configuration["directory"])/"rsp").iterdir())==[]
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)
    canonical=observed["cache"].root/observed["record"].cache_key[:2]/(observed["record"].cache_key+".bin")
    assert canonical.read_bytes()==observed["original"] and len(observed["calls"])==1


def test_overlapping_tracks_accumulate_before_one_final_clamp(run_session):
    observed=run_session("overlap")
    assert observed["session"]["phase"]=="completed" and observed["loads"]==observed["unloads"]==2
    raw=(Path(observed["configuration"]["export_directory"])/"observed.pcm").read_bytes()
    samples=list(struct.iter_unpack("<ff",raw))
    for index,(left,right) in enumerate(samples):
        expected=.8 if 4800<=index<28800 else 0
        assert left==pytest.approx(expected,abs=1e-6) and right==pytest.approx(expected,abs=1e-6)
    assert len(observed["calls"])==1
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)


@pytest.mark.parametrize("boundary", ["before_start", "audio_response", "audio_load", "audio_mix",
    "audio_finalize", "frame_request", "frame_wait", "frame_submit", "before_ack",
    "capture_pending", "capture_arrives"])
def test_lifecycle_pause_preserves_pending_work_clock_pts_and_watchdogs(run_session, boundary):
    observed=run_session("pause_"+boundary)
    session=observed["session"]
    assert observed["suspension_checks"]==1 and session["phase"]=="completed"
    assert session["error_code"]=="none" and session["paused"] is False
    assert session["pause_requested"] is False and session["pause_reason"]=="none"
    count=math.ceil(round(1.0001*48000)*30/48000)
    assert session["frames"]==count and observed["graph_steps"]==count-1
    assert observed["times"]==pytest.approx([index/30 for index in range(count)],abs=1e-7)
    assert observed["loads"]==observed["unloads"]==1 and observed["private_lifetime_verified"]
    assert observed["offsets"][0]==[1,9600,8192]
    assert sum(item[2] for item in observed["offsets"])==28800
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)


def test_cancel_overrides_suspension_without_submitting_pending_frame(run_session):
    observed=run_session("pause_cancel")
    assert observed["suspension_checks"]==1 and observed["session"]["phase"]=="cancelled"
    assert observed["session"]["error_code"]=="cancelled_by_user"
    assert observed["session"]["paused"] is False and observed["session"]["pause_requested"] is False
    assert observed["times"]==pytest.approx([0,1/30],abs=1e-7)
    assert observed["loads"]==observed["unloads"]==1 and observed["private_lifetime_verified"]
    assert not list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)


def test_cancel_parked_start_never_acquires_unity_or_audio_resources(run_session):
    observed=run_session("pause_before_start_cancel")
    assert observed["suspension_checks"]==1 and observed["session"]["phase"]=="cancelled"
    assert observed["session"]["error_code"]=="cancelled_by_user"
    assert observed["loads"]==observed["unloads"]==observed["data_calls"]==0
    assert observed["graph_steps"]==observed["actor_steps"]==0 and observed["times"]==[]
    assert observed["calls"]==[]


def test_cancel_waits_for_original_async_bundle_load_before_owned_file_retirement(run_session):
    observed=run_session("cancel_load")
    assert observed["session"]["phase"]=="cancelled" and observed["session"]["error_code"]=="cancelled_by_user"
    assert observed["loads"]==observed["unloads"]==1 and observed["data_calls"]==0
    assert observed["delayed_ticks"]==25 and observed["private_lifetime_verified"]
    assert not list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)


def test_cancel_before_unity_load_waits_for_late_real_broker_response_and_releases_clone_quota(run_session):
    observed=run_session("cancel_response")
    assert observed["session"]["phase"]=="cancelled" and observed["session"]["error_code"]=="cancelled_by_user"
    assert observed["loads"]==observed["unloads"]==observed["data_calls"]==0
    assert len(observed["calls"])==1
    root=Path(observed["configuration"]["directory"])
    assert list((root/"rsp").iterdir())==[] and list((root/"prepared").iterdir())==[]
    assert not list((root/"exports").glob("*.mp4")) and not list((root/"exports").glob("*.pcm"))
    eventually(lambda:observed["broker"].status()["prepared_files"]==0)
    assert observed["broker"].status()["prepared_bytes"]==0



@pytest.mark.parametrize("field", ["capability","request_id","epoch"])
def test_response_identity_cannot_mix_jobs_or_sessions(run_session, field):
    observed=run_session(corrupt=field)
    assert observed["session"]["phase"]=="failed"
    assert observed["session"]["error_code"]=="invalid_audio_broker_response" and observed["loads"]==0
    assert not list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))


def test_retired_broker_fails_without_waiting_for_response_timeout(run_session):
    observed=run_session(retired=True)
    assert observed["session"]["phase"]=="failed" and observed["session"]["error_code"]=="audio_broker_retired"
    assert observed["loads"]==0 and observed["calls"]==[]


def test_fifo_response_is_rejected_without_blocking_unity_or_deleting_foreign_record(run_session):
    observed=run_session(corrupt="fifo")
    assert observed["session"]["phase"]=="failed" and observed["loads"]==0
    assert observed["session"]["error_code"]=="invalid_audio_broker_response" and observed["elapsed"]<5
    replies=list((Path(observed["configuration"]["directory"])/"rsp").glob("*.rsp"))
    assert len(replies)==1 and replies[0].is_fifo()


def test_fifo_active_marker_is_rejected_without_blocking_unity(run_session):
    observed=run_session(fifo_active=True)
    assert observed["session"]["phase"]=="failed" and observed["session"]["error_code"]=="audio_broker_retired"
    assert observed["elapsed"]<5 and observed["loads"]==0 and observed["calls"]==[]



def test_configure_rejects_an_unrelated_private_output_directory(run_session, tmp_path):
    foreign=tmp_path/"unrelated-private";foreign.mkdir(mode=0o700)
    observed=run_session(output=foreign)
    assert observed["configured"] is False and list(foreign.iterdir())==[]


def test_encoder_rejection_preserves_cleanup_and_original_scene(run_session):
    observed=run_session("encoder_failure")
    assert observed["session"]["phase"]=="failed" and observed["session"]["error_code"]=="encoder_frame_rejected"
    assert observed["loads"]==observed["unloads"]==1
    assert not list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))
    eventually(lambda: observed["broker"].status()["prepared_files"]==0)


def test_missing_owned_camera_ack_fails_promptly_and_restores_the_scene(run_session):
    observed=run_session("capture_missing")
    assert observed["session"]["phase"]=="failed"
    assert observed["session"]["error_code"]=="selected_camera_capture_timeout"
    assert observed["session"]["frames"]==0 and observed["elapsed"]<5
    assert observed["private_lifetime_verified"] and observed["loads"]==observed["unloads"]==1
    root=Path(observed["configuration"]["export_directory"])
    assert not list(root.glob("*.mp4"))
    assert [path.name for path in root.glob("*.pcm")]==["observed.pcm"]


def test_all_silent_music_is_not_reported_as_a_successful_soundtrack(run_session):
    observed=run_session("silent")
    assert observed["session"]["phase"]=="failed" and observed["session"]["error_code"]=="selected_music_is_silent"
    assert not list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))


@pytest.mark.parametrize("scenario,phase,directory,suffix", [
    ("foreign_pcm","pcm_file_create_failed","export_directory",".pcm"),
    ("foreign_tmp","audio_request_write_failed","directory",".tmp")])
def test_failed_exclusive_file_creation_never_deletes_foreign_files(run_session, scenario, phase, directory, suffix):
    observed=run_session(scenario)
    assert observed["session"]["phase"]=="failed" and observed["session"]["error_code"]==phase
    root=Path(observed["configuration"][directory])
    if scenario=="foreign_tmp":
        root=root/"req"
    files=list(root.glob("*"+suffix))
    assert len(files)==1 and files[0].read_bytes()==b"FOREIGN_FILE_MUST_SURVIVE"
    assert observed["calls"]==[]


def test_start_waits_for_temporarily_lost_original_render_target(run_session):
    observed = run_session("source_lost_before_begin")
    assert observed["source_wait_checks"] == 4
    assert observed["session"]["phase"] == "completed"
    assert observed["session"]["readiness_error"] == "none"
    assert observed["session"]["frames"] == observed["session"]["total_frames"]
    assert observed["loads"] == observed["unloads"] == 1
    assert len(list(Path(observed["configuration"]["export_directory"]).glob("*.mp4"))) == 1
