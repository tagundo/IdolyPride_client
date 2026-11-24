"""Exercise the shipping disposable-scene export protocol.

Unity factories, managed objects, graphics and native clock originals are
explicit host fixtures. A playable host-codec artifact proves protocol output,
not original-game rendering, Vulkan execution or an Android device export.
"""
from pathlib import Path
import json
import math
import shutil
import struct
import subprocess

import pytest

from test_mp4_replay import HARNESS as REPLAY_FIXTURE
from test_mp4_native_boundary import definition
from test_android_mp4_controller import method as java_method, SOURCE as ANDROID_EXPORT
from test_mp4_session import BASE, PRELUDE, HARNESS as SESSION_FIXTURE
from test_mp4_queue_runtime import QUEUE as ROUTER_FIXTURE
from test_mp4_audio_broker import make_store, eventually
from test_mp4_audio_bundle import NAME, bundle, masked
from idoly_local.mp4_audio_broker import MP4AudioBroker


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"


REPLAY_DRIVER = r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];Host host;h=&host;
 {
  Replay replay(api());Descriptor selected=descriptor('a');
  uint64_t request=99;const Descriptor foreign=descriptor('b');
  assert(!replay.fresh_request(selected,12,&request)&&request==0&&!replay.fresh_dispatch_serial());
  assert(replay.observe(h->old,h->oldplayer,selected,11));
  assert(replay.begin(selected,0,true));
  assert(!replay.fresh_request(selected,12,&request)&&request==0&&!replay.fresh_dispatch_serial());
  replay.tick(0);
  assert(h->ends==1&&h->opens==0&&replay.phase()==Phase::waiting_for_close&&!replay.fresh_ready());
  assert(!replay.fresh_request(selected,12,&request)&&request==0&&!replay.fresh_dispatch_serial());
  replay.tick(1);assert(h->ends==1&&h->consumed==0&&!replay.ready_load_serial());
  if(mode=="failure_custody"){
   replay.tick(60001);assert(replay.phase()==Phase::failed&&std::string(replay.error())=="previous_mv_close_timeout");
   assert(h->roots[h->source]>0&&!replay.settle_failure()&&!replay.reset()&&!replay.begin(selected,60002,true)&&!replay.set_api(api()));
   assert(h->ends==1&&h->opens==0&&h->consumed==0&&h->roots[h->source]>0);
   h->status=1;h->busy=true;assert(!replay.settle_failure()&&h->consumed==1&&h->roots[h->source]==0);
   assert(!replay.reset()&&h->consumed==1&&h->opens==0);
   h->busy=false;assert(replay.settle_failure()&&replay.settle_failure()&&h->consumed==1);
   assert(replay.reset()&&h->handles.empty());return 0;
  }
  if(mode=="cancel_close")replay.cancel();
  h->status=1;h->top=h->home;replay.tick(2);
  assert(h->consumed==1&&h->ends==1);
  if(mode=="cancel_close"){
   assert(replay.phase()==Phase::cancelled&&!replay.fresh_ready()&&!h->opens&&!replay.ready_load_serial());
  }else{
   assert(replay.phase()==Phase::waiting_for_open&&h->opens==1);verify_constructed(selected);
   const uint64_t dispatched=replay.fresh_dispatch_serial();assert(dispatched);
   assert(!replay.fresh_request(selected,11,&request)&&request==0);
   assert(!replay.fresh_request(foreign,12,&request)&&request==0);
   assert(!replay.fresh_request(selected,0,&request)&&request==0&&!replay.fresh_request(selected,12,nullptr));
   assert(replay.fresh_request(selected,12,&request)&&request==dispatched);
   if(mode=="request_cancel_open"){
    replay.cancel();assert(replay.fresh_request(selected,12,&request)&&request==dispatched);
    assert(!replay.fresh_request(selected,13,&request)&&request==0);
    h->top=h->old;assert(replay.observe(h->old,h->oldplayer,selected,12));replay.tick(3);
    assert(replay.phase()==Phase::cancelled&&replay.fresh_dispatch_serial()==dispatched);
    assert(replay.fresh_request(selected,12,&request)&&request==dispatched&&!replay.fresh_request(foreign,12,&request));
    assert(replay.reset());
    assert(!replay.fresh_request(selected,12,&request)&&request==0);return 0;
   }
   if(mode=="request_failed_open"){
    h->oldplayer->ready=false;assert(replay.observe(h->old,h->oldplayer,selected,12));replay.tick(300003);
    assert(replay.phase()==Phase::failed&&std::string(replay.error())=="queued_mv_load_timeout"&&replay.settle_failure());
    assert(replay.fresh_dispatch_serial()==dispatched&&replay.fresh_request(selected,12,&request)&&request==dispatched);
    assert(!replay.fresh_request(selected,13,&request)&&request==0&&!replay.fresh_request(foreign,12,&request));
    assert(replay.reset()&&!replay.fresh_request(selected,12,&request)&&!request&&!replay.fresh_dispatch_serial());return 0;
   }
   h->top=h->old;replay.tick(3);
   assert(replay.phase()==Phase::waiting_for_open&&!replay.fresh_ready());
   // Same pooled pointers and descriptor are insufficient. The original
   // initializer must publish a new associated selection identity.
   assert(replay.observe(h->old,h->oldplayer,selected,11));replay.tick(4);
   assert(replay.phase()==Phase::waiting_for_open&&!replay.ready_load_serial());
   h->oldplayer->ready=false;assert(replay.observe(h->old,h->oldplayer,selected,12));replay.tick(5);
   assert(replay.phase()==Phase::waiting_for_open&&!replay.fresh_ready());
   h->oldplayer->ready=true;replay.tick(6);
   assert(replay.phase()==Phase::ready&&replay.fresh_ready()&&replay.ready_identity()==12);
   const uint64_t first=replay.ready_load_serial();assert(first);
   assert(replay.fresh_request(selected,12,&request)&&request==dispatched&&replay.fresh_dispatch_serial()==dispatched);
   assert(!replay.fresh_request(selected,13,&request)&&request==0&&!replay.fresh_request(foreign,12,&request));
   replay.tick(7);assert(replay.ready_load_serial()==first&&h->consumed==1&&h->opens==1);
   if(mode=="receipt_latched"){
    assert(replay.observe(h->old,h->oldplayer,selected,13));
    assert(!replay.fresh_ready()&&!replay.ready_load_serial()&&replay.ready_identity()==12);
   }
   if(mode=="reload"){
    assert(replay.begin(selected,8,true));replay.tick(8);
    assert(h->ends==2&&!replay.fresh_ready()&&!replay.ready_load_serial());
    h->top=h->home;replay.tick(9);assert(h->opens==2&&h->consumed==2);
    h->top=h->old;assert(replay.observe(h->old,h->oldplayer,selected,13));replay.tick(10);
    assert(replay.fresh_ready()&&replay.ready_load_serial()>first&&replay.ready_identity()==13);
   }
  }
  assert(replay.reset());
  assert(!replay.fresh_dispatch_serial()&&!replay.fresh_request(selected,12,&request)&&request==0);
 }
 assert(h->handles.empty());
}
'''


@pytest.fixture(scope="module")
def fresh_replay_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    directory = tmp_path_factory.mktemp("fresh-replay")
    source, binary = directory / "replay.cpp", directory / "replay"
    source.write_text(REPLAY_FIXTURE.split("int main(", 1)[0] + REPLAY_DRIVER)
    built = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(NATIVE),
         str(source), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("scenario", ["fresh", "cancel_close", "reload", "receipt_latched", "failure_custody", "request_cancel_open", "request_failed_open"])
def test_force_fresh_executes_original_close_and_requires_new_initializer(fresh_replay_binary, scenario):
    result = subprocess.run([str(fresh_replay_binary), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


# Reuse only the instrumented original API leaves. The entire Runtime,
# GameAdapter, native clock, selection cache and Replay come from the shipping
# headers. No substitute session or Fresh state machine is supplied here.
UNITY_LEAVES = SESSION_FIXTURE.split("struct FakeEncoder", 1)[0]
ROUTER_LEAVES = ROUTER_FIXTURE.split("void pump(){", 1)[0]

FRESH_DRIVER = r'''
#include <sys/wait.h>
namespace rtcore=idoly_mp4_runtime;
struct ClockManager{alignas(8) unsigned char bytes[0x200]{};}clock_manager;
double native_wall=1000.;unsigned kernel_calls=0,readpixels_calls=0,pass_calls=0,finish_waits=0;
unsigned prepare_calls=0,grant_calls=0,render_calls=0,withdraw_calls=0,save_calls=0;
uint64_t prepared_tick=~uint64_t(0),granted_tick=~uint64_t(0),render_tick=~uint64_t(0);
bool render_armed=false,host_acquired=false,host_started=false,restoring=false,restored=false;
unsigned hold_waits=0,backpressure_calls=0,encoder_finishes=0,encoder_cancels=0;
unsigned prewarm_render_waits=0,tick_render_waits=0,render_wait_count=0;
unsigned prepare_finish_waits=0,prepare_finish_wait_count=0;
unsigned save_cleanup_waits=0,save_cleanup_wait_count=0,save_cleanup_calls=0;
unsigned request_checks=0,renewed_wait_checks=0;uint64_t export_request_serial=0;
bool partial_origin_state=false,mixer_changed=false;
unsigned ordinary_play_calls=0;
void ordinary_play_or_resume(void*selected_director,Method*){assert(selected_director==ptr(director));++ordinary_play_calls;mode=1;}
uint64_t fresh_watch=0;idoly_mp4_game::SceneWitness host_source{};
qm::Descriptor saved_descriptor{};double saved_source_time=.37;int saved_mode=0;
replay::Replay restoration_replay;
template<class T>T clock_read(size_t at){T value{};std::memcpy(&value,clock_manager.bytes+at,sizeof value);return value;}
template<class T>void clock_write(size_t at,T value){std::memcpy(clock_manager.bytes+at,&value,sizeof value);}
bool clock_current(void*value){return value==&clock_manager;}
void clock_original(void*value,double wall){assert(clock_current(value)&&wall==native_wall);++kernel_calls;clock_write(0xc8,clock_read<uint64_t>(0xc8)+1);}
void setup_clock(){
 for(size_t at:{size_t(0x30),size_t(0x38),size_t(0x60),size_t(0x68),size_t(0x90),size_t(0x98)})clock_write(at,60.);
 for(size_t at:{size_t(0x40),size_t(0x70),size_t(0xa0)})clock_write(at,100.);
 clock_write(0x48,.02f);clock_write(0xfc,1.f);clock_write(0xe0,940.);clock_write(0xe8,900.);
 assert(rtcore::install_native_clock({clock_current,clock_original}));
}
bool fresh_available(void*ctx){return ctx==&clock_manager&&rtcore::installed&&rtcore::native_clock_available();}
Result fresh_save(void*ctx){
 assert(fresh_available(ctx));++save_calls;saved_source_time=time_value;saved_mode=mode;
 if(scenario=="queue_save_origin_timeout"||scenario=="direct_save_origin_timeout")return Result::waiting;
 if(scenario=="queue_save_origin_partial_wait"||scenario=="direct_save_origin_partial_wait"){
  partial_origin_state=true;custom=true;shader=7.7f;save_cleanup_waits=2;
  return Result::unsupported;
 }
 if(scenario=="queue_save_origin_reject"||scenario=="direct_save_origin_reject")return Result::unsupported;
 return rtcore::selection.selected(ptr(player),saved_descriptor);
}
double fresh_duration(void*object,Method*method){
 if(scenario=="queue_snapshot_reject"&&opened==1&&!restoring)return std::numeric_limits<double>::quiet_NaN();
 return session_duration(object,method);
}
bool fresh_source_geometry(void*controller,int32_t*width,int32_t*height){
 if(scenario=="queue_snapshot_timeout"&&opened==1&&!restoring)return false;
 return queue_source_geometry(controller,width,height);
}
bool same_source(){
 idoly_mp4_game::SceneWitness current{};
 return host_acquired&&rtcore::game.selected_scene_witness(current)&&current.generation==host_source.generation
  &&current.player==host_source.player&&current.presenter==host_source.presenter&&current.camera==host_source.camera;
}
Result fresh_admit(void*){if(scenario=="admission_timeout")return Result::waiting;rtcore::FreshFactoryReceipt receipt{};return rtcore::fresh_factory_receipt(&receipt)&&receipt.serial&&receipt.identity?Result::ok:Result::waiting;}
Result fresh_acquire(void*,const idoly_mp4_game::SceneWitness&w,uint64_t job){
 rtcore::FreshFactoryReceipt receipt{};assert(rtcore::fresh_factory_receipt(&receipt)&&receipt.player==w.player&&job);
 if(scenario=="acquire_timeout")return Result::waiting;
 host_source=w;fresh_watch=job;host_acquired=true;return same_source()?Result::ok:Result::stale;
}
Result fresh_start(void*){
 if(!same_source())return Result::stale;
 assert(rtcore::native_clock_scope().held());
 if(scenario=="start_timeout")return Result::waiting;
 if(!host_started){mode=1;time_value=0;host_started=true;}
 return Result::ok;
}
bool fresh_current(void*){return same_source()&&fresh_watch==rtcore::job.generation;}
Result fresh_hold(void*){
 if(!fresh_current(nullptr))return Result::stale;
 assert(rtcore::native_clock_scope().held());
 if(hold_waits){--hold_waits;return Result::waiting;}return Result::ok;
}
Result fresh_prepare(void*,uint64_t tick,double seconds){
 if(!fresh_current(nullptr)||!rtcore::native_clock_scope().held())return Result::stale;
 assert(std::fabs(seconds-double(tick)/rtcore::native_clock_scope().simulation_hz())<1e-12);
 prepared_tick=tick;++prepare_calls;return Result::ok;
}
Result fresh_grant(void*,uint64_t tick){
 assert(fresh_current(nullptr)&&prepared_tick==tick&&rtcore::native_clock_scope().tick()==tick);
 granted_tick=tick;prepared_tick=~uint64_t(0);++grant_calls;return Result::ok;
}
Result fresh_render(void*,uint64_t tick){
 assert(fresh_current(nullptr)&&rtcore::native_clock_scope().active());
 assert(rtcore::native_clock_scope().have_tick()?rtcore::native_clock_scope().tick()==tick:tick==0);
 unsigned&waits=rtcore::job.auto_started?tick_render_waits:prewarm_render_waits;
 if(waits){
  assert(!rtcore::job.fresh_render_ready&&render_calls==0);
  assert(rtcore::job.auto_started?(grant_calls==1&&rtcore::job.schedule.next_tick()==1&&pass_calls==1):(grant_calls==0&&pass_calls==0));
  --waits;++render_wait_count;return Result::waiting;
 }
 render_tick=tick;render_armed=true;return Result::ok;
}
void fresh_withdraw(void*){prepared_tick=granted_tick=~uint64_t(0);render_armed=false;++withdraw_calls;}
const char*fresh_error(void*){
 if(scenario.find("save_origin")!=std::string::npos)return "fresh_audio_source_mixer_unsupported";
 return scenario=="restore_failure"?"fixture_restore_verification_failed":"none";
}
const char*fresh_audio(void*,void*source,float*mixer_gain){
 assert(mixer_gain);*mixer_gain=scenario=="mixer_gain_halved"||(scenario=="mixer_gain_changed"&&!mixer_changed)?.5f:1.f;
 return source==ptr(bgm)||source==ptr(voice)?nullptr:"fixture_audio_source_unknown";
}
Result fresh_prepare_finish(void*){
 if(prepare_finish_waits){assert(rtcore::native_clock_scope().active()&&rtcore::native_clock_scope().held()&&rtcore::game.fresh());--prepare_finish_waits;++prepare_finish_wait_count;return Result::waiting;}
 return Result::ok;
}
Result fresh_finish(void*){
 assert(!rtcore::native_clock_scope().active());
 if(scenario.find("save_origin")!=std::string::npos){
  ++save_cleanup_calls;assert(!opened&&!closed&&!host_started&&!grant_calls&&!readpixels_calls);
  custom=false;shader=4;bgm_volume=voice_volume=1;partial_origin_state=false;
  if(save_cleanup_waits){--save_cleanup_waits;++save_cleanup_wait_count;return Result::waiting;}
  restored=true;return Result::ok;
 }
 if(restored)return Result::ok;
 if(!restoring){
  // Model the exact original global/audio setters before starting an actual
  // second Replay. Async navigation itself remains the production Replay.
  custom=false;shader=4;bgm_volume=voice_volume=1;
  qm::Descriptor current{};const auto selected=rtcore::selection.selected(ptr(player),current);
  if(selected!=Result::ok)return selected;
  assert(restoration_replay.observe(ptr(presenter),ptr(player),current,rtcore::selection.identity(ptr(player))));
  assert(restoration_replay.begin(saved_descriptor,rtcore::milliseconds(),true));restoring=true;
 }
 qm::Descriptor current{};
 if(rtcore::selection.selected(ptr(player),current)==Result::ok)
  (void)restoration_replay.observe(ptr(presenter),ptr(player),current,rtcore::selection.identity(ptr(player)));
 restoration_replay.tick(rtcore::milliseconds());++finish_waits;
 if(!restoration_replay.fresh_ready())return Result::waiting;
 assert(rtcore::selection.identity(ptr(player))==restoration_replay.ready_identity());
 time_value=saved_source_time;mode=saved_mode;host_acquired=false;host_started=false;restored=true;
 assert(restoration_replay.reset());return scenario=="restore_failure"?Result::failed:Result::ok;
}
void fresh_readpixels(void*p,const Rect*r,int32_t x,int32_t y,bool mip,Method*m){
 ++readpixels_calls;assert(rtcore::game.capture_worker_snapshot().readback_active);
 if(scenario=="throw_readpixels"&&rtcore::job.auto_started)throw std::runtime_error("modeled ReadPixels original");
 readpixels(p,r,x,y,mip,m);
}
void*fresh_pixels(void*,Method*){
 auto*array=make("byte[]");array->array_kind=3;array->bytes.resize(size_t(capture_width)*capture_height*4);
 const uint8_t frame=uint8_t(rtcore::job.frame);
 for(size_t at=0;at<array->bytes.size();at+=4){array->bytes[at]=uint8_t(20+frame*3);array->bytes[at+1]=uint8_t(90+frame);array->bytes[at+2]=170;array->bytes[at+3]=255;}
 return ptr(array);
}
struct HostEncoder{IDMP4EncoderConfig config{};std::string pcm,partial,final,raw;FILE*file=nullptr;uint64_t frames=0;uint32_t phase=IDMP4_ENCODING;bool retry=true;std::vector<uint8_t>pending;};
extern "C" IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig*c,char*,size_t){
 assert(c&&c->width==16&&c->height==16&&c->fps_num==unsigned(fps)&&c->video_frame_count);
 auto*encoder=new HostEncoder;encoder->config=*c;encoder->pcm=c->pcm_f32_path;encoder->partial=c->partial_path;encoder->final=c->final_path;encoder->raw=encoder->final+".rgba";
 if(scenario=="mixer_gain_normal"||scenario=="mixer_gain_halved"){
  FILE*source=fopen(c->pcm_f32_path,"rb"),*target=fopen((output_root+"/observed.pcm").c_str(),"wb");assert(source&&target);
  uint8_t buffer[4096];size_t copied=0,count=0;while((count=fread(buffer,1,sizeof buffer,source))){assert(fwrite(buffer,1,count,target)==count);copied+=count;}
  assert(!ferror(source)&&copied==c->audio_sample_frames*8&&fclose(source)==0&&fclose(target)==0);
 }
 encoder->file=fopen(encoder->raw.c_str(),"wb");assert(encoder->file);return encoder;
}
extern "C" int IDMP4EncoderAppendFrame(IDMP4EncoderHandle value,const uint8_t*pixels,size_t row,uint64_t index){
 auto*encoder=static_cast<HostEncoder*>(value);assert(index==encoder->frames&&row==64);
 const size_t bytes=row*encoder->config.height;
 assert(std::fabs(time_value-double(index)/fps)<1e-6&&pixels[0]==uint8_t(20+index*3)&&pixels[1]==uint8_t(90+index));
 if(encoder->retry){encoder->pending.assign(pixels,pixels+bytes);encoder->retry=false;++backpressure_calls;return IDMP4_RETRY;}
 assert(encoder->pending.size()==bytes&&!std::memcmp(encoder->pending.data(),pixels,bytes));
 assert(fwrite(pixels,1,bytes,encoder->file)==bytes);encoder->pending.clear();encoder->retry=true;++encoder->frames;return IDMP4_ACCEPTED;
}
extern "C" int IDMP4EncoderPoll(IDMP4EncoderHandle value,IDMP4EncoderStatus*s){auto*e=static_cast<HostEncoder*>(value);s->phase=e->phase;s->submitted_frames=s->encoded_frames=e->frames;s->audio_frames=e->config.audio_sample_frames;return IDMP4_ACCEPTED;}
extern "C" int IDMP4EncoderFinish(IDMP4EncoderHandle value){
 auto*e=static_cast<HostEncoder*>(value);assert(e->frames==e->config.video_frame_count);assert(fclose(e->file)==0);e->file=nullptr;
 if(scenario=="real_mp4"||scenario=="restore_failure"){
  const std::string dimensions=std::to_string(e->config.width)+"x"+std::to_string(e->config.height),rate=std::to_string(fps),samples=std::to_string(e->config.audio_sample_rate),frames=std::to_string(e->frames);
  pid_t child=fork();assert(child>=0);
  if(child==0){execlp("ffmpeg","ffmpeg","-v","error","-y","-f","rawvideo","-pixel_format","rgba","-video_size",dimensions.c_str(),"-framerate",rate.c_str(),"-i",e->raw.c_str(),"-f","f32le","-ar",samples.c_str(),"-ac","2","-i",e->pcm.c_str(),"-c:v","libx264rgb","-preset","ultrafast","-crf","0","-c:a","aac","-b:a","192k","-frames:v",frames.c_str(),"-f","mp4",e->partial.c_str(),static_cast<char*>(nullptr));_exit(127);}
  int status=0;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
 }else{FILE*file=fopen(e->partial.c_str(),"wb");assert(file);fputs("HOST_PROTOCOL_FIXTURE",file);fclose(file);}
 assert(rename(e->partial.c_str(),e->final.c_str())==0);e->phase=IDMP4_COMPLETED;++encoder_finishes;return IDMP4_ACCEPTED;
}
extern "C" void IDMP4EncoderCancel(IDMP4EncoderHandle value){auto*e=static_cast<HostEncoder*>(value);if(e->file){fclose(e->file);e->file=nullptr;}e->phase=IDMP4_CANCELLED;unlink(e->partial.c_str());++encoder_cancels;}
extern "C" int IDMP4EncoderDestroy(IDMP4EncoderHandle value){auto*e=static_cast<HostEncoder*>(value);assert(!e->file);delete e;return IDMP4_ACCEPTED;}
void emit_capture(){
 assert(clock_game==&rtcore::game);uint8_t scratch[1024]{};size_t bytes=0;int32_t width=0,height=0;
 assert(rtcore::game.readback_rgba(scratch,sizeof scratch,bytes,width,height)==Result::waiting);
 auto*pass=make("VL.Rendering.VLCapturePass");auto*data=make("RenderingData");
 write(data,0x90,ptr(camera));write(data,0x158,uint8_t(1));
 // Wrong identifier and wrong camera cannot acknowledge the pending image.
 write(pass,0x88,uint64_t(99));rtcore::capture_pass_did_execute(ptr(pass),ptr(data));rtcore::camera_did_render(ptr(camera));assert(!rtcore::job.captured);
 write(pass,0x88,uint64_t(0));++pass_calls;rtcore::capture_pass_did_execute(ptr(pass),ptr(data));rtcore::camera_did_render(ptr(voice));assert(!rtcore::job.captured);
 rtcore::camera_did_render(ptr(camera));rtcore::camera_did_render(ptr(camera));assert(rtcore::job.captured);
}
struct Mp4RenderContext{void*pointer=nullptr;};
using Mp4RenderCamera=void(*)(Mp4RenderContext,void*,Method*);
struct{bool active=false,detached=false;idoly_mp4_game::SceneWitness source{};uint64_t tick=0;unsigned render_depth=0;const char*error="none";}mp4_fresh_host;
Api mp4_api{};unsigned isolated_draws=0,shader_rebases=0;
bool mp4_fresh_current(void*){return fresh_current(nullptr);}
bool mp4_shader_lease_set_time(void*owner,float seconds){
 assert(owner==&mp4_fresh_host&&fresh_current(nullptr));++shader_rebases;shader_set(seconds,nullptr);return true;
}
struct RenderIsolationLeaf{
 template<class F>bool isolate_preview(const F&draw){++isolated_draws;draw();return true;}
 template<class F>bool isolate_render(uintptr_t owner,const F&draw){assert(owner==reinterpret_cast<uintptr_t>(ptr(camera)));++isolated_draws;draw();return true;}
 const char*error()const{return "none";}
}mp4_actor_mono_gate;
void mp4_particle_render_observed(Mp4RenderCamera original,Mp4RenderContext context,void*selected_camera,Method*method){original(context,selected_camera,method);}
// SHIPPING_FRESH_RENDER_CALL
void fresh_original_render(Mp4RenderContext,void*selected_camera,Method*){
 assert(selected_camera==ptr(camera)&&custom&&std::fabs(double(shader)-time_value)<1e-6);
 if(rtcore::job.auto_started)++render_calls;
 if(rtcore::job.capture_requested)emit_capture();
}
void pump_fresh(){
 if(close_ticks)--close_ticks;
 if(open_ticks&&!--open_ticks){
  void*param=opening_param;opening_param=nullptr;select_param(param);time_value=0;
  if(scenario=="factory_request"){
   rtcore::FreshFactoryRequest request{99,99,ptr(player)};
   if(opened==1&&!restoring){
    assert(rtcore::immediate_replay().phase()==replay::Phase::waiting_for_open);
    assert(rtcore::fresh_factory_request(ptr(player),&request)&&request.player==ptr(player));
    assert(request.identity==rtcore::selection.identity(ptr(player))&&request.serial==rtcore::immediate_replay().fresh_dispatch_serial());
    export_request_serial=request.serial;++request_checks;
    rtcore::FreshFactoryRequest scope{};assert(rtcore::fresh_factory_request_scope(&scope)&&scope.serial==request.serial&&scope.identity==request.identity&&scope.player==request.player);
    // A restoration/other Replay cannot authorize an exporting initializer.
    assert(!rtcore::queue_active_id[0]);rtcore::queue_active_id[0]='x';
    assert(!rtcore::fresh_factory_request(ptr(player),&request)&&!request.serial&&!request.identity&&!request.player);
    rtcore::queue_active_id[0]=0;
   }else assert(!rtcore::fresh_factory_request(ptr(player),&request)&&!request.serial&&!request.identity&&!request.player);
  }
 }
 if(router_top==presenter&&alive(ptr(presenter)))rtcore::observe_presenter(ptr(presenter));
 rtcore::on_unity_tick();native_wall+=.001;
 if(scenario=="factory_request"&&export_request_serial&&!restoring&&rtcore::immediate_replay().fresh_ready()){
  rtcore::FreshFactoryRequest request{};assert(rtcore::fresh_factory_request(ptr(player),&request)&&request.serial==export_request_serial);++request_checks;
  rtcore::FreshFactoryRequest scope{};assert(rtcore::fresh_factory_request_scope(&scope)&&scope.serial==request.serial&&scope.identity==request.identity&&scope.player==request.player);
 }
 const uint64_t before=rtcore::job.schedule.next_tick();
 const bool result=rtcore::native_clock_tick(&clock_manager,native_wall);(void)result;
 if(granted_tick!=~uint64_t(0)){
  assert(rtcore::job.schedule.next_tick()==before+1);time_value=double(granted_tick)/rtcore::native_clock_scope().simulation_hz();
 }
 if(host_acquired&&!rtcore::job.scene_detached){
  mp4_fresh_host.active=true;mp4_fresh_host.source=host_source;mp4_fresh_host.tick=render_tick==~uint64_t(0)?0:render_tick;
  // A late ordinary Timeline update may overwrite CustomTime. The shipping
  // render callback must rebase it immediately before every actual original.
  shader=9.9f;assert(mp4_fresh_render_call(fresh_original_render,{&clock_manager},ptr(camera),nullptr));
 }
}
int main(int argc,char**argv){
 assert(argc==7);scenario=argv[5];fps=std::atoi(argv[6]);sample_rate=48000;selected_duration=.1001;output_root=argv[4];
 if(scenario=="render_wait")prewarm_render_waits=tick_render_waits=3;
 if(scenario=="prepare_finish_wait")prepare_finish_waits=3;
 router_scene=make("SceneSystem");router_home=make("HomeScreen");router_state=make("LiveState");
 connect_scene();Api selected=api();selected.director_get_duration=fresh_duration;selected.audio_clip_samples=session_samples;selected.audio_clip_frequency=session_rate;
 selected.timeline_get_tracks=session_tracks;selected.track_get_clips=session_clips;selected.bundle_load_file_async=session_load_bundle;selected.audio_clip_get_data=session_get_data;selected.bundle_unload=session_unload;
 selected.automatic_playback.director_play=ordinary_play_or_resume;selected.automatic_playback.director_resume=ordinary_play_or_resume;
 selected.texture2d_read_pixels_injected=fresh_readpixels;selected.texture2d_raw_data=fresh_pixels;selected.source_geometry=fresh_source_geometry;
 rtcore::install_game_api(selected,Layout{});mp4_api=selected;clock_game=&rtcore::game;setup_clock();
 rtcore::install_queue_api(replay_api(),graphics_snapshot,graphics_apply,idoly_mp4_game::android_original_sha256,graphics_revision);
 assert(restoration_replay.set_api(replay_api()));select_param(make_selection("A"));time_value=.037;
 assert(IDMP4SessionConfigure(argv[1],std::strtoull(argv[2],nullptr,10),argv[3],argv[4],1)==0);
 rtcore::FreshSceneApi host{};host.context=&clock_manager;host.available=fresh_available;host.save_origin=fresh_save;host.admit=fresh_admit;host.acquire=fresh_acquire;
 host.start=fresh_start;host.current=fresh_current;host.hold=fresh_hold;host.prepare_step=fresh_prepare;host.grant=fresh_grant;host.prepare_render=fresh_render;host.prepare_finish=fresh_prepare_finish;host.finish=fresh_finish;host.audio_source_error=fresh_audio;host.error=fresh_error;host.withdraw=fresh_withdraw;
 assert(rtcore::install_fresh_scene_api(host));rtcore::require_native_scene_pipeline();
 if(scenario=="factory_request"){
  rtcore::FreshFactoryRequest request{99,99,ptr(player)};
  assert(!rtcore::fresh_factory_request(ptr(player),&request)&&!request.serial&&!request.identity&&!request.player);
  assert(!rtcore::fresh_factory_request(nullptr,&request)&&!rtcore::fresh_factory_request(ptr(player),nullptr));
  assert(!rtcore::fresh_factory_request_scope(&request)&&!request.serial&&!request.identity&&!request.player);
 }
 const bool queue_failure=scenario.rfind("queue_",0)==0;
 const bool stage_timeout=scenario=="admission_timeout"||scenario=="acquire_timeout"||scenario=="start_timeout";
 if(queue_failure||stage_timeout||scenario.rfind("direct_save_origin",0)==0){
  std::string queue_root=output_root+"-queue";std::string queue_id;
  if(queue_failure){
   assert(mkdir(queue_root.c_str(),0700)==0);
   assert(IDMP4QueueConfigure(queue_root.c_str(),output_root.c_str())==0);rtcore::on_unity_tick();
   assert(IDMP4QueueEnqueue(unsigned(fps),1,1,16000000,192000)==0);queue_id=rtcore::queue_last_added;
   assert(IDMP4QueueRun()==0);
  }else{
   rtcore::on_unity_tick();assert(IDMP4SessionStart(unsigned(fps),1,1,16000000,192000)==0);
  }
  bool deadline_advanced=false;
  for(unsigned attempt=0;attempt<1000;++attempt){
   if(!deadline_advanced&&(scenario=="queue_save_origin_timeout"||scenario=="queue_snapshot_timeout")&&rtcore::queue_prepare_wait_started){
    const auto now=rtcore::milliseconds();assert(now>15001);rtcore::queue_prepare_wait_started=now-15001;deadline_advanced=true;
   }
   if(!deadline_advanced&&scenario=="direct_save_origin_timeout"&&rtcore::fresh_immediate_wait_started){const auto now=rtcore::milliseconds();assert(now>15001);rtcore::fresh_immediate_wait_started=now-15001;deadline_advanced=true;}
   if(!deadline_advanced&&stage_timeout&&rtcore::job.fresh_stage_wait_started){const auto now=rtcore::milliseconds();assert(now>15001);rtcore::job.fresh_stage_wait_started=now-15001;deadline_advanced=true;}
   pump_fresh();
   timespec pause{0,1000000};nanosleep(&pause,nullptr);
   if(queue_failure&&save_cleanup_wait_count&&!restored){
    const auto*draining=rtcore::queue_store().find(queue_id.c_str());
    assert(draining&&draining->state==qm::State::running&&rtcore::queue_running&&!rtcore::queue_export_started);
    assert(!std::strcmp(rtcore::job.status.phase,"failed")&&!std::strcmp(rtcore::job.status.error,"fresh_audio_source_mixer_unsupported"));
    assert(!partial_origin_state&&!custom&&shader==4);
   }
   if(queue_failure){const auto*row=rtcore::queue_store().find(queue_id.c_str());assert(row);if(row->state==qm::State::failed&&!rtcore::queue_running)break;}
   else if(!rtcore::start_pending&&!rtcore::control_busy&&!rtcore::busy_stage())break;
  }
  const char*expected=scenario=="queue_snapshot_reject"?"unsupported_selected_duration":(scenario=="queue_save_origin_timeout"||scenario=="direct_save_origin_timeout")?"fresh_origin_save_timeout":scenario=="queue_snapshot_timeout"?"queued_scene_readiness_timeout":scenario=="admission_timeout"?"fresh_scene_admission_timeout":scenario=="acquire_timeout"?"fresh_scene_acquire_timeout":scenario=="start_timeout"?"fresh_scene_start_timeout":"fresh_audio_source_mixer_unsupported";
  char native_status[4096]{},queue_status[16384]{};assert(IDMP4SessionStatus(native_status,sizeof native_status));
  if(queue_failure){
   assert(IDMP4QueueStatus(queue_status,sizeof queue_status));const auto*row=rtcore::queue_store().find(queue_id.c_str());
   assert(row&&row->state==qm::State::failed&&!std::strcmp(row->error,expected)&&row->attempts==1);
   assert(!rtcore::queue_running&&!rtcore::queue_active_id[0]&&!rtcore::queue_export_started&&!std::strcmp(rtcore::queue_error,expected));
  }
  assert(!rtcore::control_busy&&!rtcore::start_pending&&!rtcore::busy_stage()&&!rtcore::native_clock_scope().active());
  assert(((scenario=="queue_save_origin_timeout"||scenario=="direct_save_origin_timeout")?save_calls>=2:save_calls==1)&&restored&&!partial_origin_state&&!custom&&shader==4&&mode==saved_mode&&time_value==saved_source_time);
  assert(!host_started&&!ordinary_play_calls&&!grant_calls&&!raw_captures&&!readpixels_calls&&!encoder_finishes&&!encoder_cancels);
  if(scenario.find("save_origin")!=std::string::npos){assert(!opened&&!closed&&save_cleanup_calls);if(scenario.find("partial_wait")!=std::string::npos)assert(save_cleanup_wait_count==2&&save_cleanup_calls>=3);}
  else assert(opened==2&&closed==2);
  assert(!std::strcmp(rtcore::job.status.phase,"failed")&&!std::strcmp(rtcore::job.status.error,expected));
  // Idle observations and UI polling may refresh readiness but must retain
  // the terminal error and must not turn into ordinary playback/retry.
  for(unsigned idle=0;idle<12;++idle)pump_fresh();
  assert(!std::strcmp(rtcore::job.status.phase,"failed")&&!std::strcmp(rtcore::job.status.error,expected));
  assert(IDMP4SessionStatus(native_status,sizeof native_status));if(queue_failure)assert(IDMP4QueueStatus(queue_status,sizeof queue_status));
  std::printf("{\"session\":%s,\"queue\":%s,\"save_calls\":%u,\"cleanup_waits\":%u,\"opened\":%d,\"closed\":%d,\"ordinary_play_calls\":%u}\n",native_status,queue_failure?queue_status:"null",save_calls,save_cleanup_wait_count,opened,closed,ordinary_play_calls);
  rtcore::queue_replay().reset();rtcore::immediate_replay().reset();rtcore::selection.reset();rtcore::game.reset_observations();
  rtcore::queue_store().close();if(rtcore::queue_exports>=0)close(rtcore::queue_exports);rtcore::close_configuration(rtcore::configured);assert(handles.empty());return 0;
 }
 rtcore::on_unity_tick();if(IDMP4SessionStart(unsigned(fps),1,1,16000000,192000)!=0){char diagnostic[8192]{};rtcore::status(diagnostic,sizeof diagnostic);std::fprintf(stderr,"%s\n",diagnostic);assert(false&&"fresh start rejected");}
 bool interrupted=false;uint64_t limit=rtcore::milliseconds()+15000;unsigned iterations=0;
 unsigned renewal_stage=0,healthy_grants=0;uint64_t second_wait_started=0;
 do{
  if(!interrupted&&rtcore::job.fresh&&rtcore::job.auto_started&&rtcore::job.capture_requested&&rtcore::job.captured){
   if(scenario=="cancel"){IDMP4SessionCancel();interrupted=true;}
   if(scenario=="hold_wait"){hold_waits=3;interrupted=true;}
   if(scenario=="source_gain_changed"){bgm_volume=.5f;interrupted=true;}
   if(scenario=="mixer_gain_changed"){mixer_changed=true;interrupted=true;}
   if(scenario=="hold_wait_renewed"&&renewal_stage==0){hold_waits=1;renewal_stage=1;}
  }
  if(scenario=="hold_wait_renewed"&&renewal_stage==3&&grant_calls>=healthy_grants+2){
   hold_waits=1;second_wait_started=rtcore::milliseconds();renewal_stage=4;
  }
  const bool expecting_hold_wait=hold_waits>0;const auto grants_before=grant_calls,renders_before=render_calls,reads_before=readpixels_calls;
  pump_fresh();timespec pause{0,1000000};nanosleep(&pause,nullptr);
  if(scenario=="hold_wait_renewed"){
   if(expecting_hold_wait){assert(grant_calls==grants_before&&render_calls==renders_before&&readpixels_calls==reads_before);++renewed_wait_checks;}
   if(renewal_stage==1&&rtcore::job.fresh_stage_wait_started){
    assert(!std::strcmp(rtcore::job.fresh_wait_error,"fresh_source_hold_timeout"));
    // Advance the first genuine stall's elapsed interval without sleeping.
    // Its subsequent OK boundary must retire this stale deadline.
    rtcore::job.fresh_stage_wait_started=rtcore::milliseconds()-15001;renewal_stage=2;
   }else if(renewal_stage==2){
    assert(!rtcore::job.fresh_stage_wait_started&&!rtcore::job.fresh_wait_error);healthy_grants=grant_calls;renewal_stage=3;
   }else if(renewal_stage==4){
    assert(rtcore::job.fresh_stage_wait_started>=second_wait_started&&!std::strcmp(rtcore::job.fresh_wait_error,"fresh_source_hold_timeout"));renewal_stage=5;
   }else if(renewal_stage==5){assert(!rtcore::job.fresh_stage_wait_started&&!rtcore::job.fresh_wait_error);renewal_stage=6;}
  }
  if(++iterations==1000||rtcore::milliseconds()>=limit){char diagnostic[8192]{};rtcore::status(diagnostic,sizeof diagnostic);std::fprintf(stderr,"%s opened=%d closed=%d begin=%u acquire=%d started=%d restored=%d immediate=%d pending=%d\n",diagnostic,opened,closed,save_calls,host_acquired,host_started,restored,int(rtcore::immediate_replay().phase()),rtcore::start_pending);}
  assert(rtcore::milliseconds()<limit);
 }while(rtcore::control_busy||rtcore::busy_stage()||rtcore::start_pending);
 char status[2048]{};assert(rtcore::status(status,sizeof status));
 // The pending cleanup join is appended to the separate diagnostics ABI.
 {char diag[16384]{};const size_t dn=rtcore::diagnostics(diag,sizeof diag);assert(dn&&dn==strlen(diag)&&diag[dn-1]=='}');
  assert(strstr(diag,"\"session_progress\":{\"job_stage\":\"idle\",\"cleanup_stage\":\"none\",\"cleanup_wait_ms\":0,\"boundary_entries\":"));}
 assert(save_calls==1&&opened==2&&closed==2&&restored&&!host_acquired&&!rtcore::native_clock_scope().active());
 assert(time_value==saved_source_time&&mode==saved_mode&&!custom&&bgm_volume==1&&voice_volume==1);
 if(scenario=="cancel"||scenario=="throw_readpixels"||scenario=="source_gain_changed"||scenario=="mixer_gain_changed")assert(encoder_cancels==1&&!encoder_finishes);
 else assert(encoder_finishes==1&&backpressure_calls==rtcore::job.status.total_frames);
 assert(isolated_draws==shader_rebases&&isolated_draws==render_calls+1);
 if(scenario=="prepare_finish_wait")assert(prepare_finish_wait_count==3);
 if(scenario=="factory_request"){
  rtcore::FreshFactoryRequest request{};assert(request_checks>1&&export_request_serial&&!rtcore::fresh_factory_request(ptr(player),&request));
  assert(!rtcore::fresh_factory_request_scope(&request)&&!request.serial&&!request.identity&&!request.player);
 }
 if(scenario=="hold_wait_renewed")assert(renewal_stage==6&&renewed_wait_checks==2);
 std::printf("{\"session\":%s,\"opened\":%d,\"closed\":%d,\"readpixels\":%u,\"passes\":%u,\"ticks\":%u,\"renders\":%u,\"retries\":%u,\"finish_waits\":%u,\"render_waits\":%u,\"scene_restored\":%s,\"media_finalized\":%s}\n",status,opened,closed,readpixels_calls,pass_calls,grant_calls,render_calls,backpressure_calls,finish_waits,render_wait_count,rtcore::job.scene_restored?"true":"false",rtcore::job.media_finalized?"true":"false");
 rtcore::queue_replay().reset();rtcore::selection.reset();rtcore::game.reset_observations();rtcore::close_configuration(rtcore::configured);assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def fresh_runtime_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    directory = tmp_path_factory.mktemp("fresh-runtime")
    source, binary = directory / "fresh.cpp", directory / "fresh"
    bridge = (NATIVE / "bridge.cpp").read_text()
    render = definition(bridge, "bool mp4_fresh_render_call(Mp4RenderCamera original,")
    driver = FRESH_DRIVER.replace("// SHIPPING_FRESH_RENDER_CALL", render)
    source.write_text(PRELUDE + BASE + UNITY_LEAVES + ROUTER_LEAVES + driver)
    built = subprocess.run(
        [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-Wno-misleading-indentation", "-pthread", "-I", str(NATIVE), str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.fixture
def run_fresh(tmp_path, fresh_runtime_binary):
    resources = []

    def run(scenario="normal", fps=60):
        body = masked(bundle(audio_values={"frequency": 48000, "length": 2.0}), NAME)
        store, cache, *_ = make_store(tmp_path, body)
        broker = MP4AudioBroker(store, tmp_path)
        resources.append((broker, store, cache))
        config = broker.configuration()
        result = subprocess.run(
            [str(fresh_runtime_binary), config["directory"], str(config["epoch"]), config["capability"],
             config["export_directory"], scenario, str(fps)], capture_output=True, text=True, timeout=25)
        assert result.returncode == 0, result.stdout + result.stderr
        observed = json.loads(result.stdout)
        (Path(config["export_directory"]) / "protocol-observed.json").write_text(json.dumps(observed, indent=2) + "\n")
        observed["exports"] = Path(config["export_directory"])
        return observed

    yield run
    for broker, store, cache in resources:
        broker.close()
        store.close()
        cache.close()
        eventually(lambda: not broker._fds)


@pytest.mark.parametrize("fps", [30, 60, 120])
def test_shipping_fresh_runtime_virtual_ticks_capture_readback_backpressure_and_reload(run_fresh, fps):
    observed = run_fresh(fps=fps)
    status = observed["session"]
    frames = math.ceil(round(.1001 * 48000) * fps / 48000)
    assert status["phase"] == "completed" and status["error_code"] == "none"
    assert status["frames"] == status["total_frames"] == frames
    assert observed["retries"] == frames
    assert observed["readpixels"] == observed["passes"] == frames + 1
    assert observed["ticks"] == 1 + (frames - 1) * (2 if fps == 30 else 1)
    assert observed["renders"] == observed["ticks"]
    assert observed["opened"] == observed["closed"] == 2 and observed["finish_waits"] > 1


@pytest.mark.parametrize("scenario", [
    "queue_save_origin_reject", "queue_save_origin_partial_wait", "queue_snapshot_reject",
    "queue_save_origin_timeout", "queue_snapshot_timeout",
    "direct_save_origin_reject", "direct_save_origin_partial_wait", "direct_save_origin_timeout",
    "admission_timeout", "acquire_timeout", "start_timeout",
])
def test_actual_fresh_prepare_failure_is_terminal_preserves_error_and_never_autoplays(run_fresh, scenario):
    observed = run_fresh(scenario, fps=120)
    expected = {"queue_snapshot_reject": "unsupported_selected_duration", "queue_save_origin_timeout": "fresh_origin_save_timeout",
                "direct_save_origin_timeout": "fresh_origin_save_timeout", "queue_snapshot_timeout": "queued_scene_readiness_timeout",
                "admission_timeout": "fresh_scene_admission_timeout", "acquire_timeout": "fresh_scene_acquire_timeout",
                "start_timeout": "fresh_scene_start_timeout"}.get(scenario, "fresh_audio_source_mixer_unsupported")
    assert observed["session"]["phase"] == "failed"
    assert observed["session"]["error_code"] == expected
    if scenario in ("queue_save_origin_timeout", "direct_save_origin_timeout"):
        assert observed["save_calls"] >= 2
    else:
        assert observed["save_calls"] == 1
    assert observed["ordinary_play_calls"] == 0
    if scenario.startswith("queue_"):
        assert not observed["queue"]["running"] and observed["queue"]["error_code"] == expected
        job, = observed["queue"]["jobs"]
        assert job["state"] == "failed" and job["error_code"] == expected
        assert job["output_id"] == observed["session"]["export_id"] and job["output_id"]
    if "partial_wait" in scenario:
        assert observed["cleanup_waits"] == 2


@pytest.mark.parametrize("scenario", ["hold_wait", "hold_wait_renewed", "factory_request", "render_wait", "prepare_finish_wait", "cancel", "throw_readpixels", "source_gain_changed", "mixer_gain_changed"])
def test_shipping_fresh_runtime_waits_or_retires_real_partial_capture(run_fresh, scenario):
    observed = run_fresh(scenario, fps=120)
    assert observed["opened"] == observed["closed"] == 2
    status = observed["session"]
    if scenario in ("hold_wait", "hold_wait_renewed", "factory_request", "render_wait", "prepare_finish_wait"):
        assert status["phase"] == "completed" and observed["retries"] == status["total_frames"]
        if scenario == "render_wait":
            assert observed["render_waits"] == 6 and observed["renders"] == observed["ticks"] == status["total_frames"]
    elif scenario == "cancel":
        assert status["phase"] == "cancelled" and status["frames"] == 0
    elif scenario in ("source_gain_changed", "mixer_gain_changed"):
        assert status["phase"] == "failed" and status["frames"] == 0
        assert status["error_code"] == "fresh_scene_changed"
    else:
        assert status["phase"] == "failed" and status["frames"] == 0
        assert status["error_code"] == "fresh_original_callback_exception"


def test_shipping_fresh_mixer_gain_scales_actual_pcm_before_codec(run_fresh):
    baseline = run_fresh("mixer_gain_normal", fps=120)
    half = run_fresh("mixer_gain_halved", fps=120)
    raw = (baseline["exports"] / "observed.pcm").read_bytes()
    attenuated = (half["exports"] / "observed.pcm").read_bytes()
    assert baseline["session"]["phase"] == half["session"]["phase"] == "completed"
    assert len(raw) == len(attenuated) == baseline["session"]["total_audio_frames"] * 8
    expected = [sample[0] for sample in struct.iter_unpack("<f", raw)]
    actual = [sample[0] for sample in struct.iter_unpack("<f", attenuated)]
    assert any(value != 0 for value in expected)
    assert actual == pytest.approx([value * .5 for value in expected], abs=1e-8)


def verify_host_mp4(observed):
    status = observed["session"]
    path, = observed["exports"].glob("*.mp4")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=10)
    streams = json.loads(probe.stdout)["streams"]
    video, = [stream for stream in streams if stream["codec_type"] == "video"]
    audio, = [stream for stream in streams if stream["codec_type"] == "audio"]
    assert video["codec_name"] == "h264" and video["r_frame_rate"] == "120/1"
    assert int(video["nb_frames"]) == status["total_frames"]
    assert int(video["width"]) == int(video["height"]) == 16
    assert float(video["duration"]) == pytest.approx(status["total_frames"] / 120, abs=1e-5)
    assert audio["codec_name"] == "aac" and int(audio["sample_rate"]) == 48000
    assert float(audio["duration"]) == pytest.approx(status["total_audio_frames"] / 48000, abs=.001)
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=10).stdout
    frame_bytes = 16 * 16 * 3
    assert len(decoded) == frame_bytes * status["total_frames"]
    for index in range(status["total_frames"]):
        assert decoded[index * frame_bytes:index * frame_bytes + 3] == bytes((20 + index * 3, 90 + index, 170))
    return path


def test_fresh_runtime_emits_decodable_120fps_mp4_from_actual_accepted_pixels(run_fresh):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Host ffmpeg and ffprobe required")
    verify_host_mp4(run_fresh("real_mp4", fps=120))


@pytest.fixture(scope="module")
def android_save_ready(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac:
        candidates = list(Path("/workspace/.setup").glob("jdk*/usr/lib/jvm/*/bin/javac"))
        javac = str(candidates[0]) if candidates else None
    if not javac or not java:
        pytest.skip("JDK required to execute the actual Android Save gate")
    source = ANDROID_EXPORT.read_text()
    bodies = definition(source, "static final class SaveTarget {")
    bodies += "\n".join(java_method(source, name) for name in (
        "completedFile", "queuedSaveTarget", "sessionSaveTarget", "completedOutputs",
        "addCompleted", "currentSaveTarget", "hasCompletedOutput", "canSave"))
    fixture = r'''
package game.qualiarts.idolypride.localserver;
import java.io.*;import java.nio.file.*;import java.util.*;
public class SaveReadyHarness {
 static File exportRoot,persistentExportRoot;static boolean saving;static String pendingSaveId;
 static JSONObject last=new JSONObject(),lastQueue=new JSONObject();static Mp4CompletedExports completedExports;
 static class JSONObject{Map<String,Object>values=new HashMap<>();JSONObject put(String k,Object v){values.put(k,v);return this;}
  String optString(String k){Object v=values.get(k);return v==null?"":v.toString();}
  JSONArray optJSONArray(String k){return values.get(k)instanceof JSONArray?(JSONArray)values.get(k):null;}}
 static class JSONArray{ArrayList<JSONObject>values=new ArrayList<>();int length(){return values.size();}JSONObject optJSONObject(int i){return values.get(i);}}
 // ACTUAL_ANDROID_SAVE_METHODS
 public static void main(String[]args)throws Exception{
  exportRoot=new File(args[0]).getCanonicalFile();
  last.put("export_id",args[1]).put("phase",args[2]).put("error_code",args[3]).put("restoration_error",args[4]);
  if(!"completed".equals(args[2])||"none".equals(args[4]))throw new AssertionError("requires actual finalized/restore-failed session");
  File movie=completedFile(exportRoot,args[1]);long bytes=movie.length();
  if(!hasCompletedOutput()||!canSave()||!sessionSaveTarget().root.equals(exportRoot))throw new AssertionError("finalized MP4 must remain Save ready");
  saving=true;if(canSave())throw new AssertionError("active save must wait");saving=false;
  pendingSaveId=args[1];if(canSave())throw new AssertionError("pending document save must wait");pendingSaveId=null;
  if(!canSave()||movie.length()!=bytes)throw new AssertionError("save gate must retain movie");
  System.out.println("MovieSaveReady");
 }
}
'''.replace("// ACTUAL_ANDROID_SAVE_METHODS", bodies)
    directory = tmp_path_factory.mktemp("fresh-android-save")
    harness, registry = directory / "SaveReadyHarness.java", directory / "Mp4CompletedExports.java"
    harness.write_text(fixture)
    registry.write_text((ANDROID_EXPORT.parent / "Mp4CompletedExports.java").read_text())
    classes = directory / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(harness), str(registry)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    return [java, "-Xmx128m", "-cp", str(classes), "game.qualiarts.idolypride.localserver.SaveReadyHarness"]


def test_finalized_real_mp4_survives_restore_failure_and_actual_android_save_gate(run_fresh, android_save_ready):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Host ffmpeg and ffprobe required")
    observed = run_fresh("restore_failure", fps=120)
    status = observed["session"]
    assert status["phase"] == "completed" and observed["media_finalized"]
    assert not observed["scene_restored"]
    assert status["restoration_error"] == "fixture_restore_verification_failed"
    path = verify_host_mp4(observed)
    before = path.read_bytes()
    result = subprocess.run(android_save_ready + [str(path.parent), status["export_id"], status["phase"],
                                                 status["error_code"], status["restoration_error"]],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "MovieSaveReady" and path.read_bytes() == before
    (path.parent / "android-save-ready.txt").write_text(result.stdout)
