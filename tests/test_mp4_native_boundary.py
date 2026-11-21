"""Execute the production native boundary with synthetic Unity/GPU/codec APIs.

The actual Runtime coordinator, frame schedule and native clock scope execute.
The callback model verifies transaction order and lifetime; it does not run an
original PlayerLoop, physical GPU, real MP4 encoder, or device file picker.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"


def definition(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + (";" if source[end:end + 1] == ";" else "")


PRELUDE = r'''
#include "mp4_engine_clock.hpp"
#include "mp4_game_adapter.hpp"
#include "mp4_encoder_api.h"
#include "mp4_session_api.h"
#include "mp4_output_policy.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
using Result=idoly_mp4_game::Result;
using Snapshot=idoly_mp4_game::Snapshot;
static constexpr size_t path_capacity=4096;
std::vector<std::string> events;
std::vector<uint64_t> grants,accepted,offered,body_ticks;
std::vector<uint8_t> offered_pixels;
struct Manager {alignas(8) unsigned char bytes[0x200]{};} first_manager,second_manager;
void* current_manager=&first_manager;
double wall=1000.;
unsigned kernel_calls=0,finished_calls=0,cancel_calls=0,destroy_calls=0,cleanup_calls=0;
unsigned detach_calls=0,attest_calls=0,post_verify_calls=0,post_release_calls=0,ordinary_frames=0,post_root_drops=0;
int detach_waits=0,post_verify_waits=0,post_release_waits=0;
bool interception_detached=false,post_identity_current=true,post_verify_fails=false;
bool reenter_verify=false,reenter_release=false,require_natural_receipt=false;
uint64_t fake_milliseconds=1000;
uint64_t milliseconds(){return fake_milliseconds;}
void retire();
bool finish_file_exists=false,audio_retired=true,bundle_retired=true;
bool world_owned=true,prepare_wait=false,grant_fail=false,inject_f8_on_accept=false;
bool cancel_on_append=false,pause_on_append=false;
const char* scene_error="none";
bool native_pause_during_kernel=false;
uint64_t prepared_tick=~uint64_t(0);
uint64_t published_tick=~uint64_t(0);
bool partial_grant_failure=false;
bool lose_owner_after_grant=false,lose_clock_after_grant=false;
bool render_armed=false,fail_outer_render=false;
bool defer_render=false,defer_prewarm=false;
std::string throw_phase;int throw_count=0;
void original_fault(const char* phase){if(throw_phase==phase&&throw_count){--throw_count;throw std::runtime_error("synthetic original callback failure");}}
int encoder_retries=0,readback_waits=0,destroy_waits=0;
uint8_t gpu_pixel=0;
void* camera_token=reinterpret_cast<void*>(0x9876);
template<class T>T load(void* p,size_t at){T v{};std::memcpy(&v,static_cast<unsigned char*>(p)+at,sizeof v);return v;}
template<class T>void store(void* p,size_t at,T v){std::memcpy(static_cast<unsigned char*>(p)+at,&v,sizeof v);}
bool current(void* p){return p==current_manager;}
void original_kernel(void* p,double timestamp){
    assert(p==current_manager&&timestamp==wall);++kernel_calls;events.push_back("kernel");
    original_fault("kernel");
    store(p,0xc8,load<uint64_t>(p,0xc8)+1);
    if(native_pause_during_kernel)store(p,0xf8,uint8_t{1});
}
idoly_mp4_engine_clock::Scope native_engine_clock;
// ACTUAL_TYPES
Job job;
pthread_mutex_t control_mutex=PTHREAD_MUTEX_INITIALIZER;
bool cancel_pending=false,pause_acknowledged=false,reset_watchdog_pending=false;
bool control_busy=true,installed=true,native_scene_installed=true;
bool last_admission_verified=false;
PublicStatus published=[](){PublicStatus value{};value.ready=true;return value;}();
char readiness_error[192]{};
int requested_pause_reason=IDMP4_PAUSE_NONE;
uint64_t capture_acks=0;
uint64_t selected_identity=0x91827;
int context_token=13;
void* native_scene_context=&context_token;
NativeSceneControl native_scene_control;
struct {bool source_valid=true;} native_observation;
unsigned queue_invalidations=0;
void invalidate_queue_selection_locked(const char* reason){assert(std::string(reason)=="source_handoff_failed");++queue_invalidations;events.push_back("invalidate-queue");}
void refresh_native_observation(bool=false){original_fault("observation");} // Synthetic diagnostic sink.
void increment_counter(uint64_t& value){++value;}
void progress(){++job.activity;}
void publish(){}
void stable_error(const char* value){std::snprintf(job.status.error,sizeof job.status.error,"%s",value);}
void phase(const char* value){std::snprintf(job.status.phase,sizeof job.status.phase,"%s",value);events.push_back(std::string("phase:")+value);}
bool busy_stage(){return job.stage!=Stage::idle;}
struct FakeGame {
    bool own=true,source=true,pending=true,capture_pending=false,paused=true,logical=false,saved_paused=true;
    uint64_t generation=77;
    double time=0,saved_time=.37,shader_time=0;
    int capture_waits=0,start_waits=0,begin_waits=0,restore_waits=0,quiet_waits=0,abandon_waits=0,cleanup_waits=0;
    int width=16,height=16;
    unsigned restores=0,abandons=0,captures=0,reads=0,starts=0,shader_steps=0,resource_releases=0;
    std::string error="fake_game_failure";
    bool automatic()const{return own;}
    bool observe_source(double& seconds,bool& flag)const{seconds=time;flag=paused;return source;}
    bool selected_scene_witness(idoly_mp4_game::SceneWitness& value)const{original_fault("scene-witness");value.camera=camera_token;value.generation=generation;return source;}
    bool owned_primary_scene_current()const{return own&&source;}
    bool restoration_source_current()const{return source;}
    bool source_handoff_failed(void* receiver) noexcept {if(receiver!=camera_token||!own)return false;source=false;++generation;return true;}
    uint64_t owned_scene_generation()const{return generation;}
    bool restoration_pending()const{return pending;}
    const char* last_error()const{return error.c_str();}
    Result begin_automatic(){events.push_back("begin");own=pending=true;if(begin_waits){--begin_waits;return Result::waiting;}return Result::ok;}
    Result start_automatic(){events.push_back("start");++starts;if(start_waits){--start_waits;return Result::waiting;}time=0;paused=false;return Result::ok;}
    Result prepare_restore(){events.push_back("restore-fence");if(!source)return Result::stale;assert(native_engine_clock.held());if(quiet_waits){--quiet_waits;return Result::waiting;}return Result::ok;}
    bool logical_restored()const{return logical;}
    Result restore_logical(){
        if(logical)return Result::ok;
        events.push_back("restore");assert(native_engine_clock.active()&&native_engine_clock.held()&&native_engine_clock.restoring());
        assert(load<double>(current_manager,0x60)==60.);
        original_fault("restore");
        if(restore_waits){--restore_waits;return Result::waiting;}
        ++restores;time=saved_time;paused=saved_paused;logical=true;return Result::ok;
    }
    void detach_restore_globals(){
        events.push_back("detach-game-globals");
        if(logical)assert(native_engine_clock.active()&&native_engine_clock.held());
    }
    Result release_restored(){return restore();}
    Result restore(){
        if(!own&&!pending)return Result::ok;
        events.push_back("release-resources");
        assert(logical&&!native_engine_clock.active()&&interception_detached);
        if(cleanup_waits){--cleanup_waits;return Result::waiting;}
        ++resource_releases;own=pending=false;return Result::ok;
    }
    Result abandon_automatic(const char*){events.push_back("abandon");++abandons;if(abandon_waits){--abandon_waits;return Result::waiting;}own=pending=false;return Result::stale;}
    Result request_capture(){
        events.push_back("capture-request");if(capture_waits){--capture_waits;return Result::waiting;}
        ++captures;capture_pending=true;return Result::ok;
    }
    void discard_capture(){capture_pending=false;events.push_back("discard");}
    void observe_capture_pass(void*,const void*){original_fault("capture-pass");}
    Result capture_geometry(int32_t& w,int32_t& h){w=width;h=height;return Result::ok;}
    bool after_camera(void* camera){original_fault("after-camera");return capture_pending&&camera==camera_token&&source;}
    Result validate_automatic_frame(double seconds){
        events.push_back("validate");original_fault("validate");return source&&std::fabs(time-seconds)<1e-6?Result::ok:Result::failed;
    }
    Result prepare_automatic_frame(double seconds){++shader_steps;shader_time=seconds;events.push_back("shader-step");original_fault("shader");return source?Result::ok:Result::stale;}
    Result readback_rgba(uint8_t* dst,size_t capacity,size_t& count,int32_t& w,int32_t& h){
        events.push_back("readback");original_fault("readback");if(readback_waits){--readback_waits;return Result::waiting;}
        assert(capture_pending);++reads;std::memset(dst,gpu_pixel,capacity);count=capacity;w=width;h=height;
        capture_pending=false;return Result::ok;
    }
} game;
Result admission(void* ctx){assert(ctx==native_scene_context);events.push_back("admit");return world_owned?Result::ok:Result::unsupported;}
void revoke(void* ctx){assert(ctx==native_scene_context);render_armed=false;prepared_tick=published_tick=~uint64_t(0);events.push_back("revoke");}
void restore_globals(void* ctx){assert(ctx==native_scene_context);events.push_back("restore-globals");}
void abandon_globals(void* ctx){assert(ctx==native_scene_context);events.push_back("abandon-globals");}
Result prepare_render(void* ctx,uint64_t tick){assert(ctx==native_scene_context&&native_engine_clock.have_tick()&&native_engine_clock.tick()==tick);render_armed=true;events.push_back("arm-render");return Result::ok;}
Result hold(void* ctx){assert(ctx==native_scene_context&&native_engine_clock.held());if(!world_owned)return Result::stale;prepared_tick=published_tick=~uint64_t(0);events.push_back("hold");return Result::ok;}
Result prepare(void* ctx,uint64_t tick,double seconds){
    assert(ctx==native_scene_context&&native_engine_clock.held());assert(seconds==tick/60.);
    events.push_back("prepare:"+std::to_string(tick));if(prepare_wait)return Result::waiting;prepared_tick=tick;original_fault("prepare");return Result::ok;
}
Result grant(void* ctx,uint64_t tick){
    assert(ctx==native_scene_context&&native_engine_clock.have_tick()&&native_engine_clock.tick()==tick&&prepared_tick==tick);
    events.push_back("grant:"+std::to_string(tick));original_fault("grant");if(grant_fail)return Result::failed;
    grants.push_back(tick);prepared_tick=~uint64_t(0);published_tick=tick;
    if(lose_owner_after_grant){world_owned=false;game.source=false;return Result::failed;}
    if(lose_clock_after_grant){store(current_manager,0xfc,.5f);return Result::failed;}
    if(partial_grant_failure)return Result::failed;
    original_fault("after-grant");return Result::ok;
}
bool restorable(void* ctx){assert(ctx==native_scene_context);events.push_back("world");return world_owned;}
const char* error_code(void* ctx){assert(ctx==native_scene_context);return scene_error;}
void attest(void* ctx,bool* camera_audio,bool* dependents){
    assert(ctx==native_scene_context&&native_engine_clock.active()&&native_engine_clock.held()&&game.logical&&game.restores==1&&!interception_detached);
    ++attest_calls;assert(attest_calls==1);events.push_back("attest-checkpoint");*camera_audio=*dependents=true;
}
Result detach_after_restore(void* ctx){
    assert(ctx==native_scene_context);
    if(game.logical)assert(native_engine_clock.active()&&native_engine_clock.held());
    ++detach_calls;events.push_back("detach");
    if(detach_waits){--detach_waits;return Result::waiting;}
    interception_detached=true;return Result::ok;
}
Result verify_post_restore(void* ctx){
    assert(ctx==native_scene_context&&!native_engine_clock.active()&&interception_detached);
    ++post_verify_calls;events.push_back("post-verify");
    if(reenter_verify){reenter_verify=false;retire();assert(post_root_drops==0);}
    original_fault("post-verify");
    if(post_verify_waits){--post_verify_waits;return Result::waiting;}
    if(require_natural_receipt&&ordinary_frames<2)return Result::waiting;
    if(post_verify_fails||!post_identity_current){scene_error="post_source_identity_changed";return Result::stale;}
    return Result::ok;
}
Result release_post_restore(void* ctx){
    // Cleanup uses retained old roots, including after its source changed or
    // acquisition failed. It never asks Game.owned_primary_scene_current().
    assert(ctx==native_scene_context&&!native_engine_clock.active());
    ++post_release_calls;events.push_back("post-release");
    if(reenter_release){reenter_release=false;retire();assert(post_root_drops==0);}
    original_fault("post-release");
    if(post_release_waits){--post_release_waits;return Result::waiting;}
    ++post_root_drops;assert(post_root_drops==1);return Result::ok;
}
IDMP4EncoderHandle create_encoder(const IDMP4EncoderConfig* c,char*,size_t){assert(c->width==16&&c->height==16);return &context_token;}
int append_encoder(IDMP4EncoderHandle value,const uint8_t* pixels,size_t row,uint64_t frame){
    assert(value==&context_token&&row==64&&frame==accepted.size());events.push_back("append:"+std::to_string(frame));
    original_fault("append");
    offered.push_back(frame);offered_pixels.push_back(*pixels);
    if(encoder_retries){--encoder_retries;return IDMP4_RETRY;}
    accepted.push_back(frame);
    if(cancel_on_append){cancel_on_append=false;cancel_pending=true;}
    if(pause_on_append){pause_on_append=false;requested_pause_reason=IDMP4_PAUSE_USER;}
    if(inject_f8_on_accept){inject_f8_on_accept=false;store(current_manager,0xf8,uint8_t{1});}
    return IDMP4_ACCEPTED;
}
int poll_encoder(IDMP4EncoderHandle,IDMP4EncoderStatus* s){s->phase=IDMP4_COMPLETED;return IDMP4_ACCEPTED;}
int finish_encoder(IDMP4EncoderHandle){++finished_calls;finish_file_exists=true;events.push_back("finish");return IDMP4_ACCEPTED;}
void cancel_encoder(IDMP4EncoderHandle){++cancel_calls;events.push_back("cancel");}
int destroy_encoder(IDMP4EncoderHandle){assert(!native_engine_clock.active());++destroy_calls;if(destroy_waits){--destroy_waits;return IDMP4_RETRY;}return IDMP4_ACCEPTED;}
bool retire_pending_audio(){assert(!native_engine_clock.active());events.push_back("audio-retire");return audio_retired;}
bool cleanup_bundle(){assert(!native_engine_clock.active());++cleanup_calls;events.push_back("bundle-cleanup");return bundle_retired;}
void unlink_owned(int,const char*,const struct stat&){assert(false&&"No final video may be removed by retirement");}
void close_configuration(Configuration&){events.push_back("config-close");}
// ACTUAL_FUNCTIONS
void seed_manager(Manager& manager){
    for(size_t at:{size_t(0x30),size_t(0x38),size_t(0x60),size_t(0x68),size_t(0x90),size_t(0x98)})store(&manager,at,60.);
    for(size_t at:{size_t(0x40),size_t(0x70),size_t(0xa0)})store(&manager,at,100.);
    store(&manager,0x48,.02f);store(&manager,0xfc,1.f);store(&manager,0xe0,940.);store(&manager,0xe8,900.);
}
void initialize(unsigned fps){
    seed_manager(first_manager);seed_manager(second_manager);assert(native_engine_clock.install({current,original_kernel}));
    assert(native_engine_clock.acquire(current_manager,wall,60));
    job.options.fps_num=fps;job.automatic=job.scene_acquired=true;job.stage=Stage::frame_request;
    job.generation=19;job.source_generation=game.generation;job.total_frames=3;job.rate=48000;job.total_audio=4800;
    job.acquired_source_valid=true;job.acquired_source_identity=selected_identity;
    job.acquired_source_time=game.saved_time;job.acquired_source_paused=true;
    job.prewarm_completed=true;
    job.api={create_encoder,append_encoder,poll_encoder,finish_encoder,cancel_encoder,destroy_encoder};
    native_scene_control.admit=admission;native_scene_control.prepare_step=prepare;native_scene_control.attest=attest;
    native_scene_control.error=error_code;
    native_scene_control.hold=hold;native_scene_control.grant=grant;native_scene_control.source_clock_restorable=restorable;
    native_scene_control.revoke_grants=revoke;
    native_scene_control.prepare_render=prepare_render;
    native_scene_control.restore_globals_before_source_change=restore_globals;
    native_scene_control.abandon_globals=abandon_globals;
    native_scene_control.detach_after_restore=detach_after_restore;
    native_scene_control.verify_post_restore=verify_post_restore;
    native_scene_control.release_post_restore=release_post_restore;
    assert(native_scene_control.valid());
}
bool boundary(bool acknowledge=true){
    const auto before=grants.size();wall+=.01;
    const bool result=native_render_boundary(current_manager,wall);
    if(!native_engine_clock.active()){
        ++ordinary_frames;events.push_back("ordinary-loop");
        if(game.source&&!game.paused)game.time+=.01;
    }
    if(grants.size()!=before&&published_tick!=~uint64_t(0)){
        body_ticks.push_back(published_tick);game.time=published_tick/60.;gpu_pixel=uint8_t(published_tick+10);events.push_back("player-loop");
    }
    if(const uint64_t generation=claim_native_prewarm_render()){
        if(!defer_prewarm)complete_native_prewarm_render(generation,true);
    }
    if(render_armed&&!defer_render&&job.schedule.next_tick()){
        const uint64_t tick=job.schedule.next_tick()-1;
        if(const uint64_t generation=native_simulation_render_generation(tick)){
            if(acknowledge&&job.capture_requested&&job.stage==Stage::frame_wait)camera_did_render(camera_token);
            complete_native_simulation_render(generation,tick,!fail_outer_render);
        }
        render_armed=false;
    }
    return result;
}
size_t position(const std::vector<std::string>& values,const std::string& value){auto i=std::find(values.begin(),values.end(),value);assert(i!=values.end());return size_t(i-values.begin());}
void finish_and_restore(){
    assert(job.stage==Stage::finishing&&finished_calls==1);
    encoder_poll();assert(job.stage==Stage::retiring&&job.terminal_success);
    boundary();assert(job.scene_restored&&!native_engine_clock.active()&&game.restores==1&&game.paused&&game.time==.37);
    retire();assert(job.stage==Stage::idle&&finish_file_exists&&!job.rgba&&!job.encoder);
}
'''

DRIVER = r'''
int main(int argc,char**argv){
    assert(argc==2);const std::string s=argv[1];const unsigned fps=s=="thirty"?30:60;initialize(fps);
    if(s.rfind("post_",0)==0){
        job.stage=Stage::retiring;job.terminal_success=true;finish_file_exists=true;
        job.encoder=&context_token;job.rgba=static_cast<uint8_t*>(std::calloc(1024,1));job.rgba_capacity=1024;
        if(s=="post_partial_acquire"){
            game.own=game.pending=false;job.scene_acquired=false;
            boundary();assert(!native_engine_clock.active()&&!job.logical_checkpoint_valid);
            retire();assert(job.stage==Stage::idle&&post_verify_calls==0&&post_release_calls==1&&post_root_drops==1);
            assert(!job.restoration_verified);return 0;
        }
        post_verify_waits=1;
        if(s=="post_playing_progress"){game.saved_paused=false;job.acquired_source_paused=false;require_natural_receipt=true;}
        if(s=="post_resource_wait")game.cleanup_waits=2;
        if(s=="post_long_resource_wait")game.cleanup_waits=3;
        if(s=="post_detach_wait")detach_waits=2;
        if(s=="post_verify_wait"||s=="post_source_change")post_verify_waits=2;
        if(s=="post_verify_timeout")post_verify_waits=100000;
        if(s=="post_release_retry")post_release_waits=2;
        if(s=="post_verify_throw"){throw_phase="post-verify";throw_count=1;}
        if(s=="post_release_throw"){throw_phase="post-release";throw_count=1;}
        if(s=="post_reentry")reenter_verify=reenter_release=true;
        if(s=="post_error_precedence"){stable_error("encoder_frame_rejected");job.terminal_success=false;post_verify_fails=true;}
        events.clear();boundary();
        if(s=="post_detach_wait"){
            assert(job.logical_checkpoint_done&&job.logical_checkpoint_valid&&!job.scene_detached&&native_engine_clock.held());
            assert(game.restores==1&&attest_calls==1&&game.resource_releases==0);
            boundary();assert(!job.scene_detached&&native_engine_clock.held()&&game.restores==1);
            boundary();assert(job.scene_detached&&detach_calls==3);
        }
        assert(job.logical_checkpoint_done&&job.logical_checkpoint_valid&&job.scene_detached&&!native_engine_clock.active());
        assert(game.restores==1&&attest_calls==1&&job.restored_source_time==.37);
        assert(!job.camera_audio_restored&&!job.restoration_verified);
        assert(job.post_verify_done==(s=="post_verify_throw"));
        assert(position(events,"attest-checkpoint")<position(events,"detach"));
        assert(position(events,"detach")<position(events,"release-resources"));
        if(s=="post_direct_service_reentry"){
            reenter_verify=reenter_release=true;
            assert(service_post_restore());
            assert(post_verify_calls==2&&post_release_calls==1&&post_root_drops==1);
            retire();assert(job.stage==Stage::idle&&job.restoration_verified);return 0;
        }
        if(s=="post_playing_progress"){
            assert(game.time>.37&&!game.paused);retire();
            assert(job.stage==Stage::retiring&&!job.post_verify_done&&!job.restoration_verified&&!native_engine_clock.active());
            const double checkpoint=job.restored_source_time;boundary();assert(game.time>checkpoint&&ordinary_frames>=2);
            retire();assert(job.stage==Stage::idle&&job.restoration_verified&&job.restored_source_time==checkpoint&&game.restores==1);
            assert(post_verify_calls==3&&post_root_drops==1);return 0;
        }
        if(s=="post_resource_wait"){
            assert(game.pending&&game.resource_releases==0&&post_verify_calls==1);
            retire();assert(job.stage==Stage::retiring&&!native_engine_clock.active()&&game.restores==1&&post_verify_calls==1);
            boundary();retire();assert(job.stage==Stage::retiring&&!native_engine_clock.active());
            boundary();retire();assert(job.stage==Stage::idle&&game.resource_releases==1&&post_verify_calls==2&&post_root_drops==1);return 0;
        }
        if(s=="post_long_resource_wait"){
            assert(game.pending&&post_verify_calls==1&&post_root_drops==0);
            ++fake_milliseconds;boundary();
            assert(game.pending&&!native_engine_clock.active()&&post_verify_calls==2&&job.post_verified&&post_root_drops==1);
            fake_milliseconds+=20000;boundary();
            assert(game.pending&&!native_engine_clock.active()&&post_verify_calls==2&&std::string(job.status.restoration_error)=="none");
            boundary();retire();assert(job.stage==Stage::idle&&job.restoration_verified&&game.restores==1&&post_root_drops==1);return 0;
        }
        if(s=="post_ready_after_timeout")fake_milliseconds+=20000;
        retire();
        if(s=="post_source_change"){
            assert(job.stage==Stage::retiring&&!job.post_verify_done);
            game.source=false;++game.generation;game.time=9;post_identity_current=false;
            const auto kernels=kernel_calls;boundary();retire();
            assert(kernel_calls==kernels+1&&job.stage==Stage::idle&&!job.restoration_verified&&job.restored_source_time==.37);
            assert(game.time==9&&game.restores==1&&post_root_drops==1);return 0;
        }
        if(s=="post_verify_timeout"){
            assert(job.stage==Stage::retiring&&!job.post_verify_done&&post_root_drops==0);
            fake_milliseconds+=16000;const auto kernels=kernel_calls;boundary();retire();
            assert(kernel_calls==kernels+1&&job.stage==Stage::idle&&job.post_verify_done&&!job.post_verified&&post_root_drops==1);
            assert(std::string(job.status.restoration_error)=="source_audio_restoration_timeout");return 0;
        }
        if(s=="post_verify_wait"){
            assert(job.stage==Stage::retiring&&!job.restoration_verified&&post_root_drops==0);
            boundary();retire();assert(job.stage==Stage::idle&&job.restoration_verified&&post_verify_calls==3);return 0;
        }
        if(s=="post_release_retry"){
            assert(job.stage==Stage::retiring&&job.post_verify_done&&job.post_verified&&!job.post_release_done&&post_root_drops==0);
            boundary();retire();assert(job.stage==Stage::retiring&&post_verify_calls==2&&post_release_calls==2);
            boundary();retire();assert(job.stage==Stage::idle&&post_verify_calls==2&&post_release_calls==3&&post_root_drops==1);return 0;
        }
        if(s=="post_release_throw"){
            assert(job.stage==Stage::retiring&&post_root_drops==0&&!job.post_release_done);
            boundary();retire();assert(job.stage==Stage::idle&&post_verify_calls==2&&post_release_calls==2&&post_root_drops==1&&!job.terminal_success);
            assert(std::string(job.status.restoration_error)=="source_audio_release_exception");return 0;
        }
        if(s=="post_verify_throw"){
            assert(job.stage==Stage::idle&&job.post_verify_done&&!job.post_verified&&!job.restoration_verified&&post_root_drops==1);
            assert(std::string(job.status.restoration_error)=="source_audio_verification_exception");return 0;
        }
        if(s=="post_error_precedence"){
            assert(job.stage==Stage::idle&&!job.terminal_success&&!job.restoration_verified);
            assert(std::string(job.status.error)=="encoder_frame_rejected"&&std::string(job.status.restoration_error)=="post_source_identity_changed");return 0;
        }
        assert(job.stage==Stage::idle&&job.restoration_verified&&post_verify_calls==2&&post_release_calls==1&&post_root_drops==1&&finish_file_exists);
        if(s=="post_ready_after_timeout")assert(std::string(job.status.restoration_error)=="none"&&job.terminal_success);
        return 0;
    }
    if(s=="handoff_failure"||s=="foreign_handoff_failure"){
        boundary();const auto tick_count=grants.size();events.clear();
        observe_source_handoff_failed(s=="handoff_failure"?camera_token:reinterpret_cast<void*>(0x77));
        if(s=="foreign_handoff_failure"){
            assert(published.ready&&native_observation.source_valid&&queue_invalidations==0);
            assert(!job.cancel_encoder_pending&&!job.clock_lost&&job.stage==Stage::frame_wait&&game.source);
            assert(events.empty());
            for(int i=0;i<10&&job.stage!=Stage::finishing;++i)boundary();
            finish_and_restore();return 0;
        }
        assert(!published.ready&&!native_observation.source_valid&&queue_invalidations==1);
        assert(job.stage==Stage::retiring&&job.clock_lost&&job.cancel_encoder_pending&&!job.terminal_success);
        assert(!render_armed&&prepared_tick==~uint64_t(0)&&published_tick==~uint64_t(0));
        assert(events==std::vector<std::string>({"revoke","abandon-globals","invalidate-queue"})&&cancel_calls==0);
        assert(std::string(published.error)=="source_handoff_failed");
        boundary();assert(grants.size()==tick_count&&cancel_calls==1&&!job.cancel_encoder_pending);
        assert(job.scene_restored&&!native_engine_clock.active()&&game.restores==0&&game.abandons==1);
        retire();assert(job.stage==Stage::idle&&!finish_file_exists&&cancel_calls==1);return 0;
    }
    if(s=="prewarm_wait"||s=="prewarm_resource_wait"){
        job.stage=Stage::render_setup;job.prewarm_completed=false;defer_prewarm=true;
        boundary();assert(job.stage==Stage::frame_request&&job.prewarm_inflight&&!job.auto_started&&grants.empty());
        boundary();assert(!job.auto_started&&grants.empty());
        complete_native_prewarm_render(job.generation+1,true);assert(job.prewarm_inflight);
        if(s=="prewarm_resource_wait"){
            release_native_prewarm_render_claim(job.generation+1);assert(job.prewarm_inflight);
            release_native_prewarm_render_claim(job.generation);
            assert(!job.prewarm_inflight&&job.prewarm_requested&&!job.prewarm_completed);
            release_native_prewarm_render_claim(job.generation); // Duplicate cannot erase a retry.
            assert(job.prewarm_requested);
            boundary();assert(job.prewarm_inflight&&!job.auto_started&&grants.empty());
        }
        complete_native_prewarm_render(job.generation,true);boundary();assert(job.auto_started&&grants.size()==1);
        for(int i=0;i<10&&job.stage!=Stage::finishing;++i)boundary();
        finish_and_restore();return 0;
    }
    if(s=="render_wait"||s=="outer_render_failure"){
        defer_render=s=="render_wait";fail_outer_render=s=="outer_render_failure";
        boundary();assert(grants.size()==1&&accepted.empty());
        if(fail_outer_render){
            assert(job.stage==Stage::retiring&&capture_acks==1&&!job.have_rendered_tick);
            boundary();assert(job.scene_restored);retire();return 0;
        }
        boundary();assert(grants.size()==1&&body_ticks.size()==1&&!job.have_rendered_tick);
        complete_native_simulation_render(job.generation+1,0,true);assert(!job.have_rendered_tick);
        defer_render=false;boundary();assert(grants.size()==1&&job.have_rendered_tick&&job.rendered_ticks==1);
        for(int i=0;i<10&&job.stage!=Stage::finishing;++i)boundary();
        finish_and_restore();return 0;
    }
    if(s=="throw_after_camera"||s=="throw_validate"||s=="throw_capture_pass"||s=="throw_scene_witness"||s=="throw_observation"||s=="idle_observer_failure"){
        boundary(false);assert(job.stage==Stage::frame_wait&&!job.captured&&grants.size()==1);
        if(s=="throw_after_camera")throw_phase="after-camera";
        else if(s=="throw_validate")throw_phase="validate";
        else if(s=="throw_scene_witness")throw_phase="scene-witness";
        else if(s=="throw_observation")throw_phase="observation";
        else throw_phase="capture-pass";
        throw_count=1;
        if(s=="idle_observer_failure")job.stage=Stage::idle;
        if(throw_phase=="capture-pass")capture_pass_did_execute(nullptr,nullptr);
        else camera_did_render(camera_token);
        assert(kernel_calls==1&&grants.size()==1&&accepted.empty());
        if(s=="idle_observer_failure"){
            assert(job.stage==Stage::idle&&!published.ready&&!native_observation.source_valid
                &&std::string(readiness_error)=="original_observation_exception");return 0;
        }
        if(s=="throw_scene_witness"||s=="throw_observation"){
            assert(job.stage==Stage::frame_wait&&job.captured&&!native_observation.source_valid);
            for(int i=0;i<10&&job.stage!=Stage::finishing;++i)boundary();
            finish_and_restore();return 0;
        }
        assert(job.stage==Stage::retiring&&!job.terminal_success&&native_engine_clock.held()
            &&published_tick==~uint64_t(0)&&!game.capture_pending);
        boundary();assert(job.scene_restored&&!native_engine_clock.active());retire();return 0;
    }
    if(s=="partial_grant_failure"||s=="throw_prepare"||s=="throw_shader"||s=="throw_grant"||s=="throw_after_grant"||s=="throw_kernel"){
        if(s=="partial_grant_failure")partial_grant_failure=true;
        else {throw_phase=s.substr(6);if(throw_phase=="after_grant")throw_phase="after-grant";throw_count=1;}
        boundary();assert(job.stage==Stage::retiring&&body_ticks.empty()&&accepted.empty()&&!job.terminal_success);
        assert(kernel_calls==(s=="throw_prepare"?0U:1U));
        boundary();assert(job.scene_restored&&!native_engine_clock.active());retire();return 0;
    }
    if(s=="partial_grant_owner_lost"||s=="partial_grant_clock_lost"){
        lose_owner_after_grant=s=="partial_grant_owner_lost";
        lose_clock_after_grant=s=="partial_grant_clock_lost";
        boundary();
        // Fence/hold can no longer run. Pure revocation must still prevent a
        // later callback from consuming the partially published worker grant.
        assert(job.stage==Stage::retiring&&grants.size()==1&&body_ticks.empty()
            &&published_tick==~uint64_t(0)&&prepared_tick==~uint64_t(0)&&accepted.empty());
        boundary();assert(job.scene_restored&&!native_engine_clock.active()&&game.abandons==1&&game.restores==0);
        if(lose_clock_after_grant)assert(load<float>(current_manager,0xfc)==.5f);
        retire();return 0;
    }
    if(s=="acquire_then_render"||s=="acquire_wait"||s=="admission_failure"){
        assert(native_engine_clock.restore(current_manager,wall,true));
        game.own=game.pending=false;game.time=.37;job.scene_acquired=false;job.stage=Stage::scene_acquire;
        job.acquired_source_valid=job.prewarm_completed=false;
        if(s=="admission_failure"){
            world_owned=false;boundary();assert(job.stage==Stage::retiring&&!native_engine_clock.active()&&!game.own);
            boundary();assert(job.scene_restored&&game.restores==0&&game.abandons==0&&grants.empty());retire();return 0;
        }
        if(s=="acquire_wait")game.begin_waits=2;
        boundary();
        if(s=="acquire_wait"){
            assert(!job.scene_acquired&&native_engine_clock.active()&&native_engine_clock.held());
            boundary();assert(!job.scene_acquired&&grants.empty());boundary();
        }
        assert(job.scene_acquired&&job.stage==Stage::audio_setup&&grants.empty()&&!native_engine_clock.have_tick());
        assert(job.acquired_source_valid&&job.acquired_source_identity==selected_identity
            &&job.acquired_source_time==.37&&job.acquired_source_paused);
        job.stage=Stage::render_setup;boundary();
        assert(job.stage==Stage::frame_request&&game.captures==1&&!job.capture_requested&&grants.empty());
        for(unsigned i=0;i<12&&job.stage!=Stage::finishing;++i)boundary();
        assert(accepted==std::vector<uint64_t>({0,1,2})&&game.reads==3&&game.captures==4);
        assert(kernel_calls==(s=="acquire_wait"?7U:5U));finish_and_restore();return 0;
    }
    if(s=="world_lost_before_tick"){
        world_owned=false;job.stage=Stage::retiring;job.terminal_cancel=true;
        boundary();assert(job.scene_restored&&game.restores==0&&game.abandons==1&&grants.empty());retire();return 0;
    }
    if(s=="start_wait")game.start_waits=2;
    if(s=="capture_wait")game.capture_waits=1;
    if(s=="prepare_wait")prepare_wait=true;
    if(s=="prepare_wait"){
        boundary();assert(grants.empty()&&!native_engine_clock.have_tick());prepare_wait=false;
    }
    if(s=="start_wait"){
        boundary();boundary();assert(grants.empty()&&kernel_calls==2&&!native_engine_clock.owned_loop_quiescent());
    }
    boundary(s!="camera_wait"&&s!="wrong_camera"&&s!="wrong_time"&&s!="generation_changed");
    assert(grants==std::vector<uint64_t>{0});
    if(s=="capture_wait"){
        assert(!job.capture_requested&&job.schedule.awaiting_frame());boundary();assert(grants.size()==1&&job.capture_requested);
    }
    if(s=="camera_wait"){
        for(int i=0;i<3;++i)boundary(false);
        assert(grants.size()==1&&accepted.empty()&&game.reads==0&&kernel_calls==1);
        camera_did_render(camera_token);
    }
    if(s=="wrong_camera"){
        camera_did_render(reinterpret_cast<void*>(0x777));assert(!job.captured);
        camera_did_render(camera_token);assert(job.captured);
    }
    if(s=="wrong_time"){
        game.time=.22;camera_did_render(camera_token);
        assert(job.stage==Stage::retiring&&accepted.empty()&&!job.captured);boundary();retire();return 0;
    }
    if(s=="generation_changed"){
        ++game.generation;game.source=false;game.time=9;camera_did_render(camera_token);assert(!job.captured);
        boundary();assert(job.scene_restored&&game.abandons==1&&game.restores==0&&game.time==9&&accepted.empty());retire();return 0;
    }
    if(s=="source_changed"||s=="manager_changed"||s=="settings_changed"){
        if(s=="source_changed"){++game.generation;game.source=false;game.time=9;}
        Manager previous=first_manager;
        if(s=="manager_changed")current_manager=&second_manager;
        if(s=="settings_changed")store(current_manager,0xfc,.5f);
        boundary();assert(job.scene_restored&&game.abandons==1&&game.restores==0&&accepted.empty());
        if(s=="manager_changed")assert(!std::memcmp(&first_manager,&previous,sizeof previous));
        if(s=="settings_changed")assert(load<float>(current_manager,0xfc)==.5f);
        retire();return 0;
    }
    if(s=="abandon_wait"){
        ++game.generation;game.source=false;game.time=9;game.abandon_waits=2;
        boundary();assert(!job.scene_restored&&!native_engine_clock.active()&&game.pending&&job.encoder);
        retire();assert(job.stage==Stage::retiring&&job.encoder&&job.rgba);
        boundary();assert(!job.scene_restored&&!native_engine_clock.active()&&game.pending);
        boundary();assert(job.scene_restored&&game.abandons==3&&game.restores==0&&game.time==9);
        retire();return 0;
    }
    if(s=="cancel"){
        cancel_pending=true;boundary();assert(job.scene_restored&&game.restores==1&&grants.size()==1&&accepted.empty());retire();return 0;
    }
    if(s=="cancel_during_append"||s=="pause_during_append"){
        cancel_on_append=s=="cancel_during_append";pause_on_append=s=="pause_during_append";
        boundary();assert(accepted.size()==1&&grants.size()==1&&native_engine_clock.tick()==0);
        if(s=="cancel_during_append"){
            assert(job.stage==Stage::retiring);boundary();retire();return 0;
        }
        assert(pause_acknowledged);requested_pause_reason=IDMP4_PAUSE_NONE;pause_acknowledged=false;
        for(int i=0;i<10&&job.stage!=Stage::finishing;++i)boundary();
        finish_and_restore();return 0;
    }
    if(s=="pause"){
        requested_pause_reason=IDMP4_PAUSE_USER;boundary();assert(pause_acknowledged&&grants.size()==1&&accepted.empty());
        requested_pause_reason=IDMP4_PAUSE_NONE;pause_acknowledged=false;
    }
    if(s=="readback_wait")readback_waits=2;
    if(s=="readback_wait"){
        boundary();boundary();assert(grants.size()==1&&accepted.empty()&&game.reads==0&&kernel_calls==1);
    }
    if(s=="retry")encoder_retries=3;
    if(s=="retry"){
        for(int i=0;i<3;++i)boundary();
        assert(grants.size()==1&&accepted.empty()&&game.reads==1&&kernel_calls==1);
        assert(offered_pixels.size()==3&&offered_pixels[0]==10&&offered_pixels[1]==10&&offered_pixels[2]==10);
    }
    if(s=="f8_after_accept")inject_f8_on_accept=true;
    if(s=="throw_readback"||s=="throw_append"){
        throw_phase=s.substr(6);throw_count=1;boundary();
        assert(job.stage==Stage::retiring&&grants.size()==1&&accepted.empty()&&kernel_calls==1&&!job.terminal_success);
        boundary();assert(job.scene_restored&&!native_engine_clock.active());retire();return 0;
    }
    events.clear();boundary();
    if(s=="f8_after_accept"){
        assert(job.frame==1&&job.schedule.accepted_frames()==1&&job.schedule.next_tick()==1);
        assert(grants.size()==1&&native_engine_clock.tick()==0&&kernel_calls==1);
        assert(game.shader_time==0); // Rejected proposals cannot expose a future shader clock.
        store(current_manager,0xf8,uint8_t{0});events.clear();boundary();
        assert(grants==std::vector<uint64_t>({0,1}));
    }else{
        if(s=="retry"){
            assert(std::find(events.begin(),events.end(),"readback")==events.end()&&game.reads==1);
            assert(offered_pixels==std::vector<uint8_t>({10,10,10,10}));
        }else assert(position(events,"readback")<position(events,"append:0"));
        assert(position(events,"append:0")<position(events,"kernel"));
        assert(position(events,"kernel")<position(events,"grant:1"));
    }
    for(unsigned i=0;i<20&&job.stage!=Stage::finishing;++i)boundary();
    assert(job.stage==Stage::finishing&&accepted==std::vector<uint64_t>({0,1,2}));
    const std::vector<uint64_t> expected=fps==30?std::vector<uint64_t>{0,1,2,3,4}:std::vector<uint64_t>{0,1,2};
    assert(grants==expected&&game.reads==3&&finished_calls==1);
    assert(kernel_calls==expected.size()+(s=="start_wait"?2:0));
    assert(job.rendered_ticks==expected.size());
    if(s=="restore_time_mismatch"){
        game.saved_time=.45;encoder_poll();boundary();
        assert(job.scene_restored&&!job.restoration_verified&&!job.terminal_success&&job.restored_source_valid
            &&job.restored_source_time==.45&&std::string(job.status.error)=="source_restoration_checkpoint_failed"
            &&std::string(job.status.restoration_error)=="source_restoration_checkpoint_failed");
        retire();assert(finish_file_exists);return 0;
    }
    if(s=="throw_restore"){
        encoder_poll();assert(job.terminal_success);throw_phase="restore";throw_count=1;
        boundary();assert(!job.terminal_success&&job.stage==Stage::retiring);
        boundary();assert(job.scene_restored&&!native_engine_clock.active()&&game.restores==0&&game.abandons==1);
        retire();assert(finish_file_exists);return 0;
    }
    if(s=="restore_wait"||s=="restore_fence_wait"||s=="world_lost_before_restore"){
        encoder_poll();assert(job.terminal_success&&job.stage==Stage::retiring);
        if(s=="restore_wait")game.restore_waits=2;
        if(s=="restore_fence_wait")game.quiet_waits=2;
        if(s=="world_lost_before_restore")world_owned=false;
        boundary();
        if(s=="world_lost_before_restore"){
            assert(job.scene_restored&&game.abandons==1&&game.restores==0&&!job.terminal_success);retire();return 0;
        }
        assert(!job.scene_restored&&native_engine_clock.active()&&job.terminal_success&&job.rgba&&job.encoder);
        retire();assert(job.stage==Stage::retiring&&job.rgba&&job.encoder&&destroy_calls==0);
        boundary();assert(!job.scene_restored&&job.terminal_success);boundary();
        assert(job.scene_restored&&job.terminal_success&&!native_engine_clock.active());retire();return 0;
    }
    if(s=="async_cleanup"){
        encoder_poll();boundary();assert(job.scene_restored&&!native_engine_clock.active());
        audio_retired=false;retire();assert(job.stage==Stage::retiring&&job.encoder&&job.rgba);
        audio_retired=true;bundle_retired=false;retire();assert(job.stage==Stage::retiring&&!job.encoder&&job.rgba);
        bundle_retired=true;retire();assert(job.stage==Stage::idle&&finish_file_exists);return 0;
    }
    finish_and_restore();
}
'''


@pytest.fixture(scope="module")
def boundary_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source = (NATIVE / "mp4_runtime.hpp").read_text()
    types = "\n".join(definition(source, name) for name in (
        "struct Configuration", "struct Options", "struct PublicStatus", "struct EncoderApi",
        "enum class Stage", "struct NativeSceneControl"))
    types += source.split("// BEGIN_MP4_NATIVE_FRAME_SCHEDULE", 1)[1].split("// END_MP4_NATIVE_FRAME_SCHEDULE", 1)[0]
    types += definition(source, "struct Job")
    functions = "\n".join(definition(source, name) for name in (
        "inline const char* native_scene_error", "inline void terminal(const char* error", "inline void export_observer_failed", "inline bool prepare_frame_output", "inline void capture_pass_did_execute", "inline void camera_did_render",
        "inline bool native_render_job_current", "inline uint64_t claim_native_prewarm_render", "inline void release_native_prewarm_render_claim", "inline void complete_native_prewarm_render", "inline uint64_t native_simulation_render_generation", "inline void complete_native_simulation_render", "inline void observe_source_handoff_failed", "inline void service_deferred_encoder_cancel",
        "inline void encoder_poll", "inline void restoration_failure", "inline bool service_post_restore", "inline void retire"))
    functions += source.split("// BEGIN_MP4_NATIVE_BOUNDARY", 1)[1].split("// END_MP4_NATIVE_BOUNDARY", 1)[0]
    code = PRELUDE.replace("// ACTUAL_TYPES", types).replace("// ACTUAL_FUNCTIONS", functions) + DRIVER
    directory = tmp_path_factory.mktemp("mp4-native-boundary")
    path, binary = directory / "boundary.cpp", directory / "boundary"
    path.write_text(code)
    built = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(NATIVE),
                            str(path), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "post_playing_progress", "post_paused", "post_resource_wait", "post_long_resource_wait", "post_direct_service_reentry", "post_detach_wait", "post_verify_wait", "post_source_change", "post_verify_timeout", "post_ready_after_timeout", "post_verify_throw", "post_release_throw", "post_release_retry", "post_reentry", "post_error_precedence", "post_partial_acquire",
    "acquire_then_render", "acquire_wait", "admission_failure", "world_lost_before_tick", "prewarm_wait", "prewarm_resource_wait", "render_wait", "outer_render_failure", "handoff_failure", "foreign_handoff_failure",
    "partial_grant_failure", "partial_grant_owner_lost", "partial_grant_clock_lost", "throw_prepare", "throw_shader", "throw_grant", "throw_after_grant", "throw_kernel", "throw_readback", "throw_append", "throw_restore",
    "throw_after_camera", "throw_validate", "throw_capture_pass", "throw_scene_witness", "throw_observation", "idle_observer_failure",
    "sixty", "thirty", "start_wait", "prepare_wait", "capture_wait", "camera_wait", "wrong_camera", "wrong_time",
    "generation_changed", "source_changed", "manager_changed", "settings_changed", "abandon_wait", "cancel", "pause",
    "cancel_during_append", "pause_during_append",
    "readback_wait", "retry", "f8_after_accept", "restore_wait", "restore_time_mismatch", "restore_fence_wait", "world_lost_before_restore", "async_cleanup",
])
def test_production_native_boundary_transaction_and_restoration(boundary_binary, scenario):
    ran = subprocess.run([str(boundary_binary), scenario], capture_output=True, text=True, timeout=5)
    assert ran.returncode == 0, ran.stdout + ran.stderr


ACTOR_CLOCK_DRIVER = r'''
#include "mp4_engine_clock.hpp"
struct NativeManager {alignas(8) uint8_t bytes[0x200]{};} manager;
idoly_mp4_engine_clock::Scope engine_clock;
unsigned native_calls=0;
bool manager_current(void* value){return value==&manager;}
void native_original(void* value,double){assert(value==&manager);++native_calls;}
template<class T>void native_put(size_t at,T value){std::memcpy(manager.bytes+at,&value,sizeof value);}
int main(){
    for(size_t at:{size_t(0x30),size_t(0x38),size_t(0x60),size_t(0x68),size_t(0x90),size_t(0x98)})native_put(at,60.);
    for(size_t at:{size_t(0x40),size_t(0x70),size_t(0xa0)})native_put(at,100.);
    native_put(0x48,.02f);native_put(0xfc,1.f);native_put(0xe0,940.);native_put(0xe8,900.);
    assert(engine_clock.install({manager_current,native_original})&&engine_clock.acquire(&manager,1000.,60));
    Fixture fixture;f=&fixture;Scope actor;auto api_table=api();
    api_table.clock_held=[](void*){return engine_clock.active()&&engine_clock.held();};
    api_table.clock_granted=[](void*,uint64_t logical){
        return logical&&engine_clock.active()&&!engine_clock.restoring()
            &&engine_clock.have_tick()&&engine_clock.tick()==logical-1;
    };
    assert(actor.configure(api_table,&f->gate,&f->owner,1,f,17));
    assert(actor.quiesce()==Result::ok&&actor.capture()==Result::ok&&actor.prepare()==Result::ok);
    assert(warm(actor)==Result::ok&&f->body_calls==180);
    assert(engine_clock.set_owned_loop_quiescent(true));
    assert(actor.prepare_grant(1)==Result::ok);
    assert(actor.commit_grant(1)==Result::waiting); // Tick0 must actually be consumed.
    assert(engine_clock.native_tick(&manager,1000.01,{true,0}));
    assert(actor.commit_grant(1)==Result::ok);
    f->gate.invoke_managed(solver,f->job,nullptr,nullptr);
    f->gate.invoke_burst(burst_solver,f->job,nullptr,1,nullptr,0);
    assert(f->body_calls==181&&native_calls==1);
    assert(engine_clock.hold_for_boundary(&manager,1000.02)&&actor.hold_frame()==Result::ok);
    assert(actor.prepare_grant(2)==Result::ok);native_put(0xf8,uint8_t{1});
    assert(!engine_clock.native_tick(&manager,1000.02,{true,1}));
    assert(actor.commit_grant(2)==Result::waiting&&native_calls==1);
    f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==181);
    assert(actor.hold_frame()==Result::ok);native_put(0xf8,uint8_t{0});
    assert(engine_clock.hold_for_boundary(&manager,1000.03)&&actor.prepare_grant(2)==Result::ok);
    assert(engine_clock.native_tick(&manager,1000.03,{true,1})&&!engine_clock.held());
    const int fences=f->completions;
    assert(actor.commit_grant(2)==Result::ok&&f->completions==fences);
    f->gate.invoke_managed(solver,f->job,nullptr,nullptr);assert(f->body_calls==182&&native_calls==2);
    assert(actor.restore()==Result::waiting); // Capture/restore still require held clocks.
    assert(engine_clock.hold_for_boundary(&manager,1000.04)&&actor.hold_frame()==Result::ok);
    assert(engine_clock.rebase_for_restore(&manager,1000.04,true));
    f->root_clock=11.2;for(auto& node:f->nodes)node.time=11.2;
    assert(actor.restore()==Result::ok&&actor.release(true)==Result::ok&&f->roots.empty());
    assert(engine_clock.restore(&manager,1000.04,true)&&!engine_clock.active()&&native_calls==2);
}
'''


def test_real_clock_and_actor_scopes_commit_after_native_f8_retry(tmp_path):
    from test_mp4_actor_state import SOURCE as actor_source

    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    source, binary = tmp_path / "actor_clock.cpp", tmp_path / "actor_clock"
    source.write_text(actor_source.split("int main(", 1)[0] + ACTOR_CLOCK_DRIVER)
    built = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(NATIVE),
                            str(source), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
