// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Owned-scene offline MV export. UI calls only enqueue commands; every Unity
// object access stays on its original update/render thread. No screen recorder,
// microphone, child encoder process, or replacement game/audio decoder.
#ifndef IDOLY_DARWIN_BRIDGE
#include <pthread.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <dlfcn.h>
#include <atomic>
#else
extern "C" {
void* malloc(size_t); void free(void*);
long pread(int,void*,size_t,int64_t); long pwrite(int,const void*,size_t,int64_t);
int ftruncate(int,int64_t); void* dlsym(void*,const char*);
}
#endif
#include "mp4_encoder_api.h"
#include "mp4_session_api.h"
#include "mp4_game_adapter.hpp"
#include "mp4_engine_clock.hpp"
#include "mp4_selection_capture.hpp"
#include "mp4_game_profile.hpp"
#include "mp4_output_policy.hpp"

namespace idoly_mp4_runtime {
static idoly_mp4_engine_clock::Scope native_engine_clock;
static std::atomic<bool> native_engine_clock_installed{false};
// Published only by the completed owned frame coordinator. Dependency
// helpers alone cannot enable export or fall back to the old manual loop.
static bool (*native_owned_boundary)(void*,double)=nullptr;
static uint64_t native_entries=0;
inline bool native_render_boundary(void*,double);
inline bool install_native_clock(idoly_mp4_engine_clock::Api api){
    if(native_engine_clock_installed.load(std::memory_order_acquire)||!native_engine_clock.install(api))return false;
    native_engine_clock_installed.store(true,std::memory_order_release);return true;
}
inline bool native_clock_available(){return native_engine_clock_installed.load(std::memory_order_acquire);}
inline idoly_mp4_engine_clock::Scope& native_clock_scope(){return native_engine_clock;}
inline bool native_clock_tick(void* manager,double wall){
    if(!native_clock_available())return false;
    if(native_entries<9007199254740991ULL)++native_entries;
    // Passive installation is transparent. The owned frame coordinator is
    // connected only after scene/dependent-state and worker coverage validate.
    // This wrapper owns the native call; the bridge must never call it again
    // when an active scope reports a lifecycle/ownership error.
    return native_owned_boundary?native_owned_boundary(manager,wall):native_engine_clock.native_tick(manager,wall);
}
using idoly_mp4_game::Api;
using idoly_mp4_game::Layout;
using idoly_mp4_game::Result;
using idoly_mp4_game::AudioClipProgram;
using idoly_mp4_game::Snapshot;
static constexpr size_t path_capacity=4096;
#ifdef IDOLY_DARWIN_BRIDGE
static constexpr int rd=0,wr=1,rw=2,create=0x200,exclusive=0x800,nofollow=0x100,directory=0x100000,nonblock=4;
#else
static constexpr int rd=O_RDONLY,wr=O_WRONLY,rw=O_RDWR,create=O_CREAT,exclusive=O_EXCL,nofollow=O_NOFOLLOW,directory=O_DIRECTORY,nonblock=O_NONBLOCK;
#endif
struct EncoderApi {
    IDMP4EncoderHandle (*create)(const IDMP4EncoderConfig*,char*,size_t)=nullptr;
    int (*append)(IDMP4EncoderHandle,const uint8_t*,size_t,uint64_t)=nullptr;
    int (*poll)(IDMP4EncoderHandle,IDMP4EncoderStatus*)=nullptr;
    int (*finish)(IDMP4EncoderHandle)=nullptr;
    void (*cancel)(IDMP4EncoderHandle)=nullptr;
    int (*destroy)(IDMP4EncoderHandle)=nullptr;
    bool valid()const{return create&&append&&poll&&finish&&cancel&&destroy;}
};
inline EncoderApi platform_encoder() {
    EncoderApi api{};
#ifdef IDOLY_DARWIN_BRIDGE
    // The Objective-C host owns the OS codec; the SDK-free presentation dylib
    // has no undefined references to host/framework implementation symbols.
    void* scope=reinterpret_cast<void*>(static_cast<intptr_t>(-2));
    api.create=reinterpret_cast<decltype(api.create)>(dlsym(scope,"IDMP4EncoderCreate"));
    api.append=reinterpret_cast<decltype(api.append)>(dlsym(scope,"IDMP4EncoderAppendFrame"));
    api.poll=reinterpret_cast<decltype(api.poll)>(dlsym(scope,"IDMP4EncoderPoll"));
    api.finish=reinterpret_cast<decltype(api.finish)>(dlsym(scope,"IDMP4EncoderFinish"));
    api.cancel=reinterpret_cast<decltype(api.cancel)>(dlsym(scope,"IDMP4EncoderCancel"));
    api.destroy=reinterpret_cast<decltype(api.destroy)>(dlsym(scope,"IDMP4EncoderDestroy"));
#else
    api={IDMP4EncoderCreate,IDMP4EncoderAppendFrame,IDMP4EncoderPoll,IDMP4EncoderFinish,IDMP4EncoderCancel,IDMP4EncoderDestroy};
#endif
    return api;
}
inline uint64_t milliseconds() {
    timespec now{};
#ifdef IDOLY_DARWIN_BRIDGE
    clock_gettime(6,&now); // CLOCK_MONOTONIC on Darwin.
#else
    clock_gettime(CLOCK_MONOTONIC,&now);
#endif
    return static_cast<uint64_t>(now.tv_sec)*1000+static_cast<uint64_t>(now.tv_nsec)/1000000;
}
inline bool random_bytes(uint8_t* output,size_t count) {
#ifdef IDOLY_DARWIN_BRIDGE
    arc4random_buf(output,count);return true;
#else
    int fd=open("/dev/urandom",rd);if(fd<0)return false;
    size_t offset=0;while(offset<count){long n=read(fd,output+offset,count-offset);if(n<=0){close(fd);return false;}offset+=static_cast<size_t>(n);}
    close(fd);return true;
#endif
}
inline void hex(const uint8_t* bytes,size_t count,char* output) {
    static const char alphabet[]="0123456789abcdef";
    for(size_t i=0;i<count;++i){output[i*2]=alphabet[bytes[i]>>4];output[i*2+1]=alphabet[bytes[i]&15];}output[count*2]=0;
}
inline bool decode_capability(const char* text,uint8_t* output) {
    if(!text||strlen(text)!=32)return false;
    for(size_t i=0;i<16;++i){unsigned value=0;for(size_t j=0;j<2;++j){char c=text[i*2+j];if(c>='0'&&c<='9')value=value*16+static_cast<unsigned>(c-'0');else if(c>='a'&&c<='f')value=value*16+static_cast<unsigned>(c-'a'+10);else return false;}output[i]=static_cast<uint8_t>(value);}return true;
}
inline void put16(uint8_t* p,uint16_t x){p[0]=static_cast<uint8_t>(x);p[1]=static_cast<uint8_t>(x>>8);}
inline void put32(uint8_t* p,uint32_t x){for(unsigned i=0;i<4;++i)p[i]=static_cast<uint8_t>(x>>(i*8));}
inline void put64(uint8_t* p,uint64_t x){for(unsigned i=0;i<8;++i)p[i]=static_cast<uint8_t>(x>>(i*8));}
inline uint64_t get64(const uint8_t* p){uint64_t x=0;for(unsigned i=0;i<8;++i)x|=static_cast<uint64_t>(p[i])<<(i*8);return x;}
inline bool private_directory(int fd){struct stat s{};return fd>=0&&fstat(fd,&s)==0&&(s.st_mode&0170000)==0040000&&(s.st_mode&0777)==0700&&s.st_uid==geteuid();}
inline bool private_file(int fd,int64_t maximum){struct stat s{};return fd>=0&&fstat(fd,&s)==0&&(s.st_mode&0170000)==0100000&&(s.st_mode&0077)==0&&s.st_uid==geteuid()&&s.st_nlink==1&&s.st_size>=0&&s.st_size<=maximum;}
inline void unlink_owned(int directory_fd,const char* name,const struct stat& owned){int fd=openat(directory_fd,name,rd|nofollow|nonblock);struct stat current{};bool same=fd>=0&&fstat(fd,&current)==0&&current.st_dev==owned.st_dev&&current.st_ino==owned.st_ino&&current.st_uid==owned.st_uid&&current.st_mode==owned.st_mode&&(current.st_mode&0170000)==0100000&&current.st_nlink==1;if(fd>=0)close(fd);if(same)unlinkat(directory_fd,name,0);}
inline bool safe_root(const char* value) {
    if(!value||value[0]!='/'||strlen(value)>=path_capacity-128)return false;
    // Components come from the trusted app host, but reject lexical aliases.
    const char* c=value;while(*c){if(static_cast<unsigned char>(*c)<32)return false;++c;}
    return !strstr(value,"/../")&&!strstr(value,"/./")&&!strstr(value,"//");
}
inline bool join_path(char* destination,size_t capacity,const char* root,const char* member){size_t a=strlen(root),b=strlen(member);if(a>=capacity||b>=capacity-a||a+b+2>capacity)return false;memcpy(destination,root,a);destination[a]='/';memcpy(destination+a+1,member,b+1);return true;}
inline bool exact_read(int fd,uint8_t* dst,size_t count){size_t at=0;while(at<count){long n=read(fd,dst+at,count-at);if(n<=0)return false;at+=static_cast<size_t>(n);}uint8_t tail;return read(fd,&tail,1)==0;}
inline bool exact_write(int fd,const uint8_t* src,size_t count){size_t at=0;while(at<count){long n=write(fd,src+at,count-at);if(n<=0)return false;at+=static_cast<size_t>(n);}return true;}
inline bool transfer_at(int fd,void* bytes,size_t count,int64_t offset,bool writing){
    // All PCM callers supply at most 8192 stereo float frames. Bound both the
    // buffer span and signed file position before any pointer/offset addition.
    constexpr size_t maximum=8192*2*sizeof(float);
    if(fd<0||(!bytes&&count)||count>maximum||offset<0
        ||static_cast<uint64_t>(offset)>0x7fffffffffffffffULL-count)return false;
    size_t at=0,remaining=count;
    while(remaining){
        const long n=writing?pwrite(fd,static_cast<uint8_t*>(bytes)+at,remaining,offset+static_cast<int64_t>(at))
            :pread(fd,static_cast<uint8_t*>(bytes)+at,remaining,offset+static_cast<int64_t>(at));
        if(n<=0||static_cast<uint64_t>(n)>remaining)return false;
        const size_t completed=static_cast<size_t>(n);at+=completed;remaining-=completed;
    }
    return true;
}

struct Configuration {
    char broker[path_capacity]{},output[path_capacity]{};
    uint64_t epoch=0;uint8_t capability[16]{};int platform=0;
    int root=-1,req=-1,rsp=-1,prepared=-1,exports=-1;
};
inline void close_configuration(Configuration& c){for(int*fd:{&c.root,&c.req,&c.rsp,&c.prepared,&c.exports})if(*fd>=0){close(*fd);*fd=-1;}}
struct Options{uint32_t fps_num=30,fps_den=1,codec=1,bitrate=16000000,audio_bitrate=192000,output_width=0,output_height=0;};
struct PublicStatus {
    char phase[24]="idle",id[33]{},error[192]="none";
    char restoration_error[96]="none";
    uint64_t frames=0,total_frames=0,audio=0,total_audio=0,bytes=0;
    uint32_t width=0,height=0,fps_num=30,fps_den=1,source_width=0,source_height=0,video_codec=1,video_bitrate=0;
    bool ready=false,pausable=false;
};
static pthread_mutex_t control_mutex=PTHREAD_MUTEX_INITIALIZER;
static Configuration configured;
static Options pending_options;
static PublicStatus published;
static char readiness_error[96]="open_selected_mv_first";
// Readonly selection is independent of offline admission and render ownership.
static bool selected_mv=false;
static char selection_error[96]="open_selected_mv_first";
static uint32_t selected_source_width=0,selected_source_height=0;
struct ControllerDiscovery {
    char reason[96]="selected_render_controller_missing";
    char source[24]="none";
    idoly_mp4_timeline_camera::Counters counts{};
    uint32_t candidates=0;
};
static ControllerDiscovery controller_discovery;
inline void observe_controller_discovery(const char* reason,const char* source,
        const idoly_mp4_timeline_camera::Counters& counts={},uint32_t candidates=0){
    pthread_mutex_lock(&control_mutex);
    snprintf(controller_discovery.reason,sizeof(controller_discovery.reason),"%s",reason);
    snprintf(controller_discovery.source,sizeof(controller_discovery.source),"%s",source);
    controller_discovery.counts=counts;controller_discovery.candidates=candidates;
    pthread_mutex_unlock(&control_mutex);
}
static bool configured_valid=false,start_pending=false,cancel_pending=false,control_busy=false;
static uint64_t start_wait_started=0;
static bool queue_scene_owned=false;
static char pending_queue_output[33]{},pending_queue_exports[path_capacity]{};
static int pending_queue_exports_fd=-1;
static uint32_t pending_queue_width=0,pending_queue_height=0;
// Host threads only write requests. The Unity tick acknowledges suspension
// before touching another original Unity action; pending work remains intact.
static int requested_pause_reason=IDMP4_PAUSE_NONE;
static bool pause_acknowledged=false,reset_watchdog_pending=false;
static uint64_t unity_ticks=0,capture_acks=0;
inline void increment_counter(uint64_t& value){if(value<9007199254740991ULL)++value;}
static idoly_mp4_game::GameAdapter game;
static idoly_mp4_selection::Capture selection;
struct NativeSceneControl {
    Result (*admit)(void*)=nullptr;
    Result (*prepare_step)(void*,uint64_t,double)=nullptr;
    void (*attest)(void*,bool*,bool*)=nullptr;
    const char* (*error)(void*)=nullptr;
    // Main-thread operations on the exact retained scene. hold must finish
    // the previously authorized jobs before closing its worker grant; grant
    // receives a zero-based simulation tick (not an output frame index) and
    // authorizes one step without evaluating a graph itself. A host with a
    // nonzero serial API must map tick+1 with an overflow check.
    Result (*hold)(void*)=nullptr;
    Result (*grant)(void*,uint64_t)=nullptr;
    // Ownership alone is insufficient when rebasing global fixed time. The
    // verified scene host must also close the concrete physics dependencies.
    bool (*source_clock_restorable)(void*)=nullptr;
    // Pure scalar/atomic cancellation of future permits, even after clock or
    // scene ownership is lost. This is NOT a native-job completion fence.
    void (*revoke_grants)(void*)=nullptr;
    // Arm only an unrendered, already accepted tick. This must not reopen
    // simulation/Brain/Actor grants while capture setup waits under held time.
    Result (*prepare_render)(void*,uint64_t)=nullptr;
    // End temporary global/RNG/render-reference leases before an original
    // replacement initializer runs. Separate from pure grant revocation.
    void (*restore_globals_before_source_change)(void*)=nullptr;
    // Scalar-only invalidation after a failed synchronous handoff. It MUST
    // NOT retry a Unity setter/owner query or let an old finally write globals
    // after original replacement initialization. Keep unresolved resources.
    void (*abandon_globals)(void*)=nullptr;
    // Detach every global/interception lease before any resource or natural
    // Audio WAIT. Post callbacks own their roots independently of Scene and
    // Playback scopes and must remain callable after those scopes retire.
    Result (*detach_after_restore)(void*)=nullptr;
    Result (*verify_post_restore)(void*)=nullptr;
    Result (*release_post_restore)(void*)=nullptr;
    bool valid()const{return admit&&prepare_step&&attest&&error&&hold&&grant&&source_clock_restorable&&revoke_grants&&prepare_render&&restore_globals_before_source_change&&abandon_globals&&detach_after_restore&&verify_post_restore&&release_post_restore;}
};
static NativeSceneControl native_scene_control;
static void* native_scene_context=nullptr;
static bool native_scene_installed=false,native_scene_required=false;
// Fresh mode owns a disposable original scene and restores logical selection
// by another original load. It never publishes legacy restoration receipts.
struct FreshSceneApi {
    void* context=nullptr;
    bool (*available)(void*)=nullptr;
    Result (*save_origin)(void*)=nullptr;
    Result (*admit)(void*)=nullptr;
    Result (*acquire)(void*,const idoly_mp4_game::SceneWitness&,uint64_t)=nullptr;
    Result (*start)(void*)=nullptr;
    bool (*current)(void*)=nullptr;
    Result (*hold)(void*)=nullptr;
    Result (*prepare_step)(void*,uint64_t,double)=nullptr;
    Result (*grant)(void*,uint64_t)=nullptr;
    Result (*prepare_render)(void*,uint64_t)=nullptr;
    // Retire decoder work and restore its saved controls while the actual
    // native clock is still held. WAIT retains that clock and source custody.
    // A terminal result leaves no decoder cleanup requiring a clock grant.
    Result (*prepare_finish)(void*)=nullptr;
    // WAIT owns async original reload and may retain its independent Listener
    // mute lease. Every terminal return has released all leases, even failure.
    Result (*finish)(void*)=nullptr;
    const char* (*audio_source_error)(void*,void*,float*)=nullptr;
    const char* (*error)(void*)=nullptr;
    // Revoke future per-tick permits at every boundary. This reversible
    // scalar operation neither withdraws scene ownership nor completes jobs.
    void (*withdraw)(void*)=nullptr;
    bool valid()const{return context&&available&&save_origin&&admit&&acquire&&start&&current&&hold
        &&prepare_step&&grant&&prepare_render&&prepare_finish&&finish&&audio_source_error&&error&&withdraw;}
};
struct FreshFactoryReceipt {uint64_t serial=0,identity=0;void*presenter=nullptr,*player=nullptr;};
struct FreshFactoryRequest {uint64_t serial=0,identity=0;void*player=nullptr;};
static FreshSceneApi fresh_scene_api;
static std::atomic<bool> fresh_scene_installed{false};
static bool fresh_scene_available=false;
inline bool fresh_factory_receipt(FreshFactoryReceipt*);
inline bool fresh_factory_request(void*,FreshFactoryRequest*);
inline bool fresh_factory_request_scope(FreshFactoryRequest*);
inline Result fresh_prepare_start();
inline void fresh_release_start();
inline const char* fresh_start_error();
inline const char* fresh_start_restore_error();
inline bool native_fresh_render_boundary(void*,double);
inline const char* fresh_scene_error(const char*fallback){
    const char*value=fresh_scene_api.error?fresh_scene_api.error(fresh_scene_api.context):nullptr;
    return value&&value[0]&&strcmp(value,"none")?value:fallback;
}
inline void require_native_scene_pipeline(){native_scene_required=true;}
inline const char* native_scene_error(const char* fallback){
    const char* code=native_scene_control.error?native_scene_control.error(native_scene_context):nullptr;
    if(!code||!code[0]||!strcmp(code,"none"))return fallback;
    for(size_t i=0;;++i){
        if(i>=95)return fallback;
        const char c=code[i];if(!c)return code;
        if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'))return fallback;
    }
}
static uint64_t selected_identity=0;
// Invalidation is scalar-only so lifecycle/host callbacks never enter Unity
// or acquire the queue owner lock while holding the control lock.
static uint64_t queue_selection_generation=1;
static char queue_selection_reason[65]="selected_mv_snapshot_missing";
static void* observed_presenter_scope=nullptr; // Compared only on Unity.
static void* observed_camera_controller_scope=nullptr;
inline void invalidate_queue_selection_locked(const char* reason){
    if(queue_selection_generation)queue_selection_generation=queue_selection_generation==~uint64_t(0)?0:queue_selection_generation+1;
    snprintf(queue_selection_reason,sizeof(queue_selection_reason),"%s",queue_selection_generation?reason:"selection_generation_exhausted");
}
inline void invalidate_queue_selection(const char* reason="selected_mv_snapshot_invalidated"){
    pthread_mutex_lock(&control_mutex);invalidate_queue_selection_locked(reason);pthread_mutex_unlock(&control_mutex);
}
inline void queue_tick();
inline void queue_refresh_candidate(Result readiness);
inline Result probe_selection_source();
static bool installed=false;
enum class Stage{idle,begin,scene_acquire,audio_setup,render_setup,audio_request,audio_response,audio_load,audio_mix,audio_finalize,frame_request,frame_wait,frame_submit,finishing,retiring};
// BEGIN_MP4_NATIVE_FRAME_SCHEDULE
// The simulation proposal and the encoder acknowledgment are separate commits.
// A rejected native clock grant must never roll back a previously accepted
// frame, and an encoder retry must never consume a new simulation tick.
class FrameSchedule {
public:
    struct Proposal { bool advance=false;uint64_t tick=0;int64_t frame=-1; };
    bool reset(uint64_t generation,uint32_t fps,uint64_t frames){
        *this=FrameSchedule{};
        if(!generation||!idoly_mp4_output::supported_fps(fps)||!frames||frames>0x7fffffffffffffffULL)return false;
        const uint32_t hz=idoly_mp4_output::simulation_hz(fps);
        const uint64_t step=hz/fps;
        if(frames-1>~uint64_t(0)/step)return false;
        generation_=generation;frames_=frames;step_=step;simulation_hz_=hz;last_tick_=(frames-1)*step;return true;
    }
    Proposal propose(uint64_t generation)const{
        if(generation!=generation_||!generation_||pending_||accepted_==frames_||next_tick_>last_tick_)return {};
        return {true,next_tick_,next_tick_%step_?int64_t(-1):static_cast<int64_t>(next_tick_/step_)};
    }
    bool commit(uint64_t generation,const Proposal& proposal){
        const Proposal expected=propose(generation);
        if(!expected.advance||!proposal.advance||proposal.tick!=expected.tick||proposal.frame!=expected.frame)return false;
        ++next_tick_;
        if(proposal.frame>=0){pending_=true;pending_frame_=static_cast<uint64_t>(proposal.frame);pixels_=false;}
        return true;
    }
    bool readback_received(uint64_t generation,uint64_t frame){
        if(generation!=generation_||!pending_||pixels_||frame!=pending_frame_)return false;
        pixels_=true;return true;
    }
    bool encoder_accepted(uint64_t generation,uint64_t frame){
        if(generation!=generation_||!pending_||!pixels_||frame!=pending_frame_||frame!=accepted_)return false;
        ++accepted_;pending_=pixels_=false;return true;
    }
    bool awaiting_frame()const{return pending_;}
    bool pixels_received()const{return pending_&&pixels_;}
    bool complete()const{return generation_&&accepted_==frames_;}
    uint64_t accepted_frames()const{return accepted_;}
    uint64_t next_tick()const{return next_tick_;}
    uint64_t generation()const{return generation_;}
    uint32_t simulation_hz()const{return simulation_hz_;}
    double tick_seconds(uint64_t tick)const{return simulation_hz_?static_cast<double>(tick)/simulation_hz_:0.;}
private:
    uint64_t generation_=0,frames_=0,step_=0,last_tick_=0,next_tick_=0,accepted_=0,pending_frame_=0;
    uint32_t simulation_hz_=0;
    bool pending_=false,pixels_=false;
};
// END_MP4_NATIVE_FRAME_SCHEDULE
struct Job {
    Configuration config{};Options options{};Snapshot snapshot{};PublicStatus status{};
    Stage stage=Stage::idle;EncoderApi api{};IDMP4EncoderHandle encoder=nullptr;
    char pcm_path[path_capacity]{},partial_path[path_capacity]{},final_path[path_capacity]{},pcm_name[48]{};
    char request_hex[33]{},request_name[48]{},response_name[48]{},bundle_name[48]{},bundle_path[path_capacity]{};
    uint8_t request_id[16]{};size_t clip=0;
    uint64_t total_audio=0,total_frames=0,frame=0,mixed=0,start_sample=0,source_offset=0,clip_frames=0;
    uint32_t rate=0;int pcm=-1;uint8_t*rgba=nullptr;size_t rgba_capacity=0;
    float source[8192*2]{},mixed_pcm[8192*2]{};
    uint64_t activity=0,last_encoder_progress=0;
    struct stat pcm_identity{},bundle_identity{};
    uint64_t finalized_audio=0;
    uint32_t expected_width=0,expected_height=0;
    FrameSchedule schedule{};
    uint64_t generation=0,source_generation=0;
    uint64_t acquired_source_identity=0;
    double acquired_source_time=0;
    bool acquired_source_valid=false,acquired_source_paused=false;
    uint64_t restored_source_identity=0;
    double restored_source_time=0;
    bool restored_source_valid=false,restored_source_paused=false;
    uint64_t last_rendered_tick=0,rendered_ticks=0;
    uint64_t fresh_render_tick=0;
    bool fresh_render_ready=false;
    bool have_rendered_tick=false,prewarm_requested=false,prewarm_inflight=false,prewarm_completed=false;
    const char*fresh_wait_error=nullptr;uint64_t fresh_stage_wait_started=0;
    bool automatic=false,fresh=false,fresh_started=false,fresh_pre_finish_settled=false,fresh_finish_settled=false,scene_acquired=false,auto_started=false,capture_requested=false,
        scene_restored=false,clock_lost=false,restoration_verified=false,
        clock_settings_restored=false,camera_audio_restored=false,dependent_state_restored=false;
    bool logical_checkpoint_done=false,logical_checkpoint_valid=false,logical_camera_audio=false,
        scene_detached=false,post_verify_done=false,post_verified=false,post_release_done=false;
    uint64_t post_wait_started=0;
    bool cancel_encoder_pending=false,media_finalized=false;
    bool pcm_owned=false,bundle_owned=false,pending_broker=false,audible_energy=false,captured=false,terminal_success=false,terminal_cancel=false;
};
static Job job;
// BEGIN_MP4_EXPORT_FAILURE_TRACE
// Bounded scalar diagnostics only. Readers never invoke Unity or providers.
static constexpr size_t trace_capacity=16,trace_modules=20;
struct ExportTraceEvent{uint64_t sequence=0,frame=0,tick=0;char stage[96]{},code[96]{};};
struct ExportTrace{ExportTraceEvent events[trace_capacity]{};size_t count=0,next=0;uint64_t sequence=0;
 char current_stage[96]="not_started",last_error[96]="none";uint8_t modules[trace_modules]{};};
static pthread_mutex_t trace_mutex=PTHREAD_MUTEX_INITIALIZER;
static ExportTrace export_trace;
inline void trace_code(char*out,size_t size,const char*value){
 if(!out||!size)return;
 size_t i=0;for(;value&&value[i]&&i+1<size;++i){const unsigned char c=static_cast<unsigned char>(value[i]);
  out[i]=((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_')?static_cast<char>(c):'_';}
 out[i]=0;if(!i)snprintf(out,size,"unknown");
}
inline const char* trace_stage(Stage stage){
 switch(stage){case Stage::idle:return "idle";case Stage::begin:return "begin";case Stage::scene_acquire:return "scene_acquire";
 case Stage::audio_setup:return "audio_setup";case Stage::render_setup:return "render_setup";case Stage::audio_request:return "audio_request";
 case Stage::audio_response:return "audio_response";case Stage::audio_load:return "audio_load";case Stage::audio_mix:return "audio_mix";
 case Stage::audio_finalize:return "audio_finalize";case Stage::frame_request:return "frame_request";case Stage::frame_wait:return "frame_readback";
 case Stage::frame_submit:return "encoder_append";case Stage::finishing:return "encoder_finish_save";case Stage::retiring:return "restore_retire";}
 return "unknown";
}
inline void diagnostic_event(const char*stage,const char*code,uint64_t frame=0,uint64_t tick=0,bool failure=false){
 char safe_stage[96]{},safe_code[96]{};trace_code(safe_stage,sizeof safe_stage,stage);trace_code(safe_code,sizeof safe_code,code);
 pthread_mutex_lock(&trace_mutex);auto&t=export_trace;
 snprintf(t.current_stage,sizeof t.current_stage,"%s",safe_stage);
 if(failure)snprintf(t.last_error,sizeof t.last_error,"%s",safe_code);
 if(t.count){const auto&last=t.events[(t.next+trace_capacity-1)%trace_capacity];
  if(!strcmp(last.stage,safe_stage)&&!strcmp(last.code,safe_code)&&last.frame==frame&&last.tick==tick){pthread_mutex_unlock(&trace_mutex);return;}}
 if(t.sequence<9007199254740991ULL){auto&e=t.events[t.next];e={};e.sequence=++t.sequence;e.frame=frame>9007199254740991ULL?9007199254740991ULL:frame;e.tick=tick>9007199254740991ULL?9007199254740991ULL:tick;
  snprintf(e.stage,sizeof e.stage,"%s",safe_stage);snprintf(e.code,sizeof e.code,"%s",safe_code);
  t.next=(t.next+1)%trace_capacity;if(t.count<trace_capacity)++t.count;}
 pthread_mutex_unlock(&trace_mutex);
}
inline void diagnostic_job_event(const char*code,bool failure=false){
 diagnostic_event(trace_stage(job.stage),code,job.frame,job.schedule.next_tick()?job.schedule.next_tick()-1:0,failure);
}
inline void diagnostic_module(size_t index,bool bound,const char*missing,bool selected=true){
 if(index>=trace_modules)return;
 pthread_mutex_lock(&trace_mutex);const uint8_t value=bound?2:1;const bool changed=export_trace.modules[index]!=value;
 export_trace.modules[index]=value;pthread_mutex_unlock(&trace_mutex);
 if(changed&&!bound&&selected)diagnostic_event("bindings",missing,0,0,true);
}
inline size_t diagnostics(char*out,size_t capacity){
 if(!out||!capacity)return 0;
 ExportTrace t{};pthread_mutex_lock(&trace_mutex);t=export_trace;pthread_mutex_unlock(&trace_mutex);
 int n=snprintf(out,capacity,"{\"pipeline_mode\":\"%s\",\"export_trace\":{\"schema\":1,\"current_stage\":\"%s\",\"last_error\":\"%s\",\"events\":[",fresh_scene_installed.load(std::memory_order_acquire)?"fresh_original_scene":"legacy_owned_scene",t.current_stage,t.last_error);
 if(n<=0||static_cast<size_t>(n)>=capacity){out[0]=0;return 0;}size_t at=static_cast<size_t>(n);
 for(size_t i=0;i<t.count;++i){const auto&e=t.events[(t.next+trace_capacity-t.count+i)%trace_capacity];
  n=snprintf(out+at,capacity-at,"%s{\"sequence\":%llu,\"stage\":\"%s\",\"code\":\"%s\",\"frame\":%llu,\"tick\":%llu}",i?",":"",
   static_cast<unsigned long long>(e.sequence),e.stage,e.code,static_cast<unsigned long long>(e.frame),static_cast<unsigned long long>(e.tick));
  if(n<=0||static_cast<size_t>(n)>=capacity-at){out[0]=0;return 0;}at+=static_cast<size_t>(n);}
 static constexpr const char*names[trace_modules]={"native_scene_control","scene_parts","final_playback_handoff","pending_journal","frame_coordinator",
 "default_images","monitor_ui","video_coordinator","proflare_source","particle_renderer","graphics_program","srp_mutations","audio_frontends",
 "managed_observers","native_director_gateway","capture_queue","initial_gpu_fence","render_hold","native_clock","game_api"};
 n=snprintf(out+at,capacity-at,"],\"modules\":{");if(n<=0||static_cast<size_t>(n)>=capacity-at){out[0]=0;return 0;}at+=static_cast<size_t>(n);
 for(size_t i=0;i<trace_modules;++i){n=snprintf(out+at,capacity-at,"%s\"%s\":%s",i?",":"",names[i],t.modules[i]==2?"true":"false");
  if(n<=0||static_cast<size_t>(n)>=capacity-at){out[0]=0;return 0;}at+=static_cast<size_t>(n);}
 n=snprintf(out+at,capacity-at,"}}}");if(n<=0||static_cast<size_t>(n)>=capacity-at){out[0]=0;return 0;}return at+static_cast<size_t>(n);
}
// END_MP4_EXPORT_FAILURE_TRACE

static uint64_t next_job_generation=1;
struct NativeObservation {
    uint64_t loop=0,identity=0,tick=0,accepted=0,acquired_identity=0;
    uint64_t restored_identity=0;
    uint64_t rendered_ticks=0;
    uint32_t render_width=0,render_height=0;
    double source_time=0,acquired_time=0,restored_time=0;
    bool source_valid=false,source_paused=false,photography=false,active=false,rendered=false,
        clock_owned=false,clock_held=false,has_tick=false,restored=false,
        clock_restored=false,camera_audio=false,dependents=false,world=false,
        acquired_valid=false,acquired_paused=false,restored_valid=false,restored_paused=false;
};
static NativeObservation native_observation;
// Read-only source admission evidence is independent of enabling rendering.
// HTTP only reads this cached copy; it never calls Unity or a component probe.
struct NativeSceneDiagnosticPart {int32_t result=-1;char error[96]="not_probed";};
struct NativeSceneDiagnostics {
    bool available=false;
    uint64_t identity=0,loop=0;
    NativeSceneDiagnosticPart parts[4]{}; // Actor, Camera, Stage, World.
};
using NativeSceneDiagnosticProbe=void(*)(void*,NativeSceneDiagnostics*);
static NativeSceneDiagnosticProbe native_diagnostic_probe=nullptr;
static void* native_diagnostic_context=nullptr;
static NativeSceneDiagnostics native_diagnostics;
inline bool install_native_scene_diagnostic_probe(void* context,NativeSceneDiagnosticProbe probe){
    if(!context||!probe)return false;
    pthread_mutex_lock(&control_mutex);
    const bool vacant=!native_diagnostic_probe;
    if(vacant){native_diagnostic_context=context;native_diagnostic_probe=probe;}
    const bool same=native_diagnostic_context==context&&native_diagnostic_probe==probe;
    pthread_mutex_unlock(&control_mutex);return same;
}
inline void refresh_native_diagnostics(bool source_valid,uint64_t identity,bool active){
    if(active||fresh_scene_installed.load(std::memory_order_acquire))return; // The legacy deep-state probe is unselected in fresh mode.
    static bool sampled=false,sampled_source_valid=false;
    static uint64_t sampled_at=0,sampled_identity=0,sampled_generation=0;
    NativeSceneDiagnosticProbe probe=nullptr;void* context=nullptr;uint64_t generation=0;
    pthread_mutex_lock(&control_mutex);
    probe=native_diagnostic_probe;context=native_diagnostic_context;generation=queue_selection_generation;
    pthread_mutex_unlock(&control_mutex);
    const uint64_t now=milliseconds();
    if(sampled&&source_valid==sampled_source_valid&&identity==sampled_identity&&generation==sampled_generation&&now>=sampled_at&&now-sampled_at<250)return;
    NativeSceneDiagnostics next{};
    if(source_valid&&probe&&context){
        try{probe(context,&next);}
        catch(...){next={};for(auto&part:next.parts)snprintf(part.error,sizeof(part.error),"diagnostic_observer_exception");}
    }else for(auto&part:next.parts)snprintf(part.error,sizeof(part.error),"%s",source_valid?"diagnostic_probe_unavailable":"selected_source_not_ready");
    next.identity=identity;next.loop=native_entries;
    // Bound and escape the only strings crossing from host diagnostics to JSON.
    for(auto&part:next.parts){
        part.error[sizeof(part.error)-1]=0;
        for(char* c=part.error;*c;++c)if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='_'))*c='_';
    }
    pthread_mutex_lock(&control_mutex);const NativeSceneDiagnostics previous=native_diagnostics;native_diagnostics=next;pthread_mutex_unlock(&control_mutex);
    static constexpr const char*providers[]={"actor_admission","camera_admission","stage_admission","world_admission"};
    for(size_t i=0;i<4;++i)if(next.parts[i].result!=previous.parts[i].result||strcmp(next.parts[i].error,previous.parts[i].error))
        diagnostic_event(providers[i],next.parts[i].error,0,0,next.parts[i].result!=0);
    sampled=true;sampled_source_valid=source_valid;sampled_at=now;sampled_identity=identity;sampled_generation=generation;
}
static bool last_admission_verified=false;
inline bool busy_stage();
inline void refresh_native_observation(bool rendered=false){
    NativeObservation next{};
    next.source_valid=installed&&game.observe_source(next.source_time,next.source_paused);
    next.photography=game.scene_kind()==idoly_mp4_game::SceneKind::photography;
    next.identity=selected_identity;next.loop=native_entries;next.active=job.automatic&&busy_stage();next.rendered=rendered;
    next.clock_owned=native_engine_clock.active();next.clock_held=native_engine_clock.held();
    next.has_tick=job.automatic&&job.schedule.next_tick()>0;
    next.tick=next.has_tick?job.schedule.next_tick()-1:0;next.accepted=job.schedule.accepted_frames();
    next.render_width=job.status.source_width;next.render_height=job.status.source_height;
    next.rendered_ticks=job.rendered_ticks;
    next.restored=job.restoration_verified;next.clock_restored=job.clock_settings_restored;
    next.camera_audio=job.camera_audio_restored;next.dependents=job.dependent_state_restored;
    next.world=!fresh_scene_installed.load(std::memory_order_acquire)&&last_admission_verified;
    next.acquired_valid=job.acquired_source_valid;next.acquired_identity=job.acquired_source_identity;
    next.acquired_time=job.acquired_source_time;next.acquired_paused=job.acquired_source_paused;
    next.restored_valid=job.restored_source_valid;next.restored_identity=job.restored_source_identity;
    next.restored_time=job.restored_source_time;next.restored_paused=job.restored_source_paused;
    refresh_native_diagnostics(next.source_valid,next.identity,next.active);
    pthread_mutex_lock(&control_mutex);native_observation=next;pthread_mutex_unlock(&control_mutex);
}
inline bool busy_stage(){return job.stage!=Stage::idle;}
inline void publish(){static Stage previous=Stage::idle;if(previous!=job.stage){previous=job.stage;diagnostic_job_event("stage_entered");}pthread_mutex_lock(&control_mutex);const bool ready=published.ready;published=job.status;published.ready=ready;published.pausable=job.stage!=Stage::idle&&job.stage!=Stage::finishing&&job.stage!=Stage::retiring;pthread_mutex_unlock(&control_mutex);}
inline void progress(){job.activity=milliseconds();}
inline void phase(const char* value){snprintf(job.status.phase,sizeof(job.status.phase),"%s",value);progress();publish();}
inline void stable_error(const char* value){size_t at=0;for(;value&&value[at]&&at<sizeof(job.status.error)-1;++at){char c=value[at];job.status.error[at]=((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_')?c:'_';}job.status.error[at]=0;if(!at)snprintf(job.status.error,sizeof(job.status.error),"export_failed");diagnostic_job_event(job.status.error,true);}
inline void publish_prestart_failure(const char*error,const char*output=nullptr,bool cancelled=false){
    if(busy_stage())return;
    job.status=PublicStatus{};
    if(output)snprintf(job.status.id,sizeof(job.status.id),"%s",output);
    stable_error(error);
    snprintf(job.status.phase,sizeof(job.status.phase),"%s",cancelled?"cancelled":"failed");
    diagnostic_event("start",job.status.error,0,0,true);publish();
}
inline void terminal(const char*,bool);
inline void export_observer_failed(){
    if(!busy_stage()){
        pthread_mutex_lock(&control_mutex);published.ready=false;native_observation.source_valid=false;
        snprintf(readiness_error,sizeof(readiness_error),"%s","original_observation_exception");pthread_mutex_unlock(&control_mutex);return;
    }
    job.terminal_success=false;stable_error("original_callback_exception");
    if(job.automatic&&native_scene_control.revoke_grants)native_scene_control.revoke_grants(native_scene_context);
    try{terminal("original_callback_exception",false);}catch(...){job.stage=Stage::retiring;}
    try{
        if(job.automatic&&native_engine_clock.active()){
            if(native_engine_clock.hold_for_boundary(native_engine_clock.latest_manager(),native_engine_clock.last_wall_timestamp())
                &&job.scene_acquired){
                if(job.fresh)fresh_scene_api.hold(fresh_scene_api.context);
                else native_scene_control.hold(native_scene_context);
            }
        }
    }catch(...){job.clock_lost=true;}
    game.discard_capture();
}
inline bool active_broker() {
    int fd=openat(job.config.root,"active",rd|nofollow|nonblock);uint8_t raw[16]{};
    const bool good=private_file(fd,16)&&exact_read(fd,raw,sizeof(raw))&&!memcmp(raw,"IDMPACT1",8)&&get64(raw+8)==job.config.epoch;
    if(fd>=0)close(fd);
    return good;
}
inline bool cleanup_bundle(){if(!game.private_audio_quiescent())return false;if(job.bundle_owned){unlink_owned(job.config.prepared,job.bundle_name,job.bundle_identity);job.bundle_owned=false;}return true;}
inline void terminal(const char* error,bool cancelled=false) {
    if(job.stage==Stage::idle||job.stage==Stage::retiring)return;
    if(job.automatic&&native_scene_control.revoke_grants)native_scene_control.revoke_grants(native_scene_context);
    job.terminal_success=false;job.terminal_cancel=cancelled;stable_error(error);
    if(!job.automatic&&game.restore()!=Result::ok)stable_error(game.last_error());
    if(job.encoder)job.api.cancel(job.encoder);
    job.stage=Stage::retiring;phase(cancelled?"cancelling":"failed");
}
inline bool valid_options(const Options& o){return o.fps_den==1&&idoly_mp4_output::supported_fps(o.fps_num)&&(o.codec==1||o.codec==2)&&idoly_mp4_output::bitrate(o.bitrate)&&o.audio_bitrate==192000&&idoly_mp4_output::requested_dimensions(o.output_width,o.output_height);}
// Typed outer URP hooks call these on Unity only. Neither CapturePass nor an
// arbitrary end-camera notification can consume a render ticket. An output
// tick waits for its capture request before its FIRST draw; held retries reuse
// that image and never run dithering/grain/history a second time.
inline bool native_render_job_current(){
    if(!installed||!job.automatic||!job.scene_acquired||!busy_stage()||job.stage==Stage::retiring
        ||job.clock_lost||!native_engine_clock.active()||job.source_generation!=game.owned_scene_generation())return false;
    pthread_mutex_lock(&control_mutex);
    const bool allowed=!cancel_pending&&requested_pause_reason==IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&control_mutex);return allowed;
}
inline uint64_t claim_native_prewarm_render(){
    if(!native_render_job_current()||job.auto_started||!job.prewarm_requested||job.prewarm_inflight
        ||(job.stage!=Stage::render_setup&&job.stage!=Stage::frame_request)||!native_engine_clock.held()
        ||(job.fresh&&(!job.fresh_render_ready||job.fresh_render_tick)))return 0;
    job.prewarm_requested=false;job.prewarm_inflight=true;return job.generation;
}
// A typed outer render hook can wait for a previous private GPU resource fence
// before it has called the original renderer. Return that unconsumed claim;
// WAIT is neither a completed prewarm nor a failed draw. Never call this after
// entering the original outer renderer, which instead owes complete(...).
inline void release_native_prewarm_render_claim(uint64_t generation){
    if(generation!=job.generation||!job.prewarm_inflight)return;
    job.prewarm_inflight=false;
    if(job.automatic&&job.scene_acquired&&!job.auto_started&&job.stage!=Stage::retiring
        &&job.source_generation==game.owned_scene_generation())job.prewarm_requested=true;
}
inline void complete_native_prewarm_render(uint64_t generation,bool succeeded){
    if(generation!=job.generation||!job.prewarm_inflight)return;
    job.prewarm_inflight=false;
    if(!succeeded){terminal("selected_camera_prewarm_failed");return;}
    if(job.stage==Stage::retiring)return;
    if(job.source_generation!=game.owned_scene_generation()){terminal("selected_scene_changed");return;}
    job.prewarm_completed=true;progress();
}
inline uint64_t native_simulation_render_generation(uint64_t tick){
    if(!native_render_job_current()||!job.auto_started||!job.schedule.next_tick()
        ||tick!=job.schedule.next_tick()-1||!native_engine_clock.have_tick()||native_engine_clock.tick()!=tick
        ||(job.have_rendered_tick&&job.last_rendered_tick==tick)
        ||(job.fresh&&(!job.fresh_render_ready||job.fresh_render_tick!=tick)))return 0;
    if(job.schedule.awaiting_frame()&&!job.capture_requested)return 0;
    return job.generation;
}
inline void complete_native_simulation_render(uint64_t generation,uint64_t tick,bool succeeded){
    if(generation!=job.generation||!job.automatic||!job.auto_started||job.stage==Stage::retiring)return;
    if(!succeeded){terminal("selected_camera_render_failed");return;}
    if(job.have_rendered_tick&&job.last_rendered_tick==tick)return; // Outer/end-camera deduplication.
    if(job.source_generation!=game.owned_scene_generation()||!job.schedule.next_tick()
        ||tick!=job.schedule.next_tick()-1||tick!=job.rendered_ticks){terminal("native_render_tick_out_of_order");return;}
    job.have_rendered_tick=true;job.last_rendered_tick=tick;++job.rendered_ticks;progress();
}
inline Result probe_readiness(Snapshot& snapshot,bool force_native_admission=true){
    // Only Unity calls this function. The full native admission allocates
    // original component/PlayerLoop arrays and traverses owned state islands;
    // do not repeat that work at display frame rate while merely showing UI.
    // Snapshot/geometry/queue graphics remain fresh on every idle observation.
    // A start and the native acquisition boundary ALWAYS run fresh admission.
    static bool admission_known=false;
    static uint64_t admission_at=0,admission_generation=0,admission_identity=0;
    static Result admission_result=Result::waiting;
    static char admission_error[96]="selected_scene_admission_failed";
    Result result=game.snapshot(snapshot,fresh_scene_installed.load(std::memory_order_acquire));const char* error=result==Result::ok?"none":game.last_error();
    if(result!=Result::ok)admission_known=false;
    if(fresh_scene_installed.load(std::memory_order_acquire)){
        if(result==Result::ok&&!fresh_scene_available){result=Result::unsupported;error=fresh_scene_error("fresh_scene_unavailable");}
    }
    if(result==Result::ok&&native_scene_required&&!native_scene_installed&&!fresh_scene_installed.load(std::memory_order_acquire)){
        result=Result::unsupported;error="offline_pipeline_not_verified";
        diagnostic_event("pipeline","native_scene_control_unbound",0,0,true);
    }
    if(result==Result::ok&&native_scene_installed&&!fresh_scene_installed.load(std::memory_order_acquire)){
        pthread_mutex_lock(&control_mutex);
        const uint64_t generation=queue_selection_generation,identity=selected_identity;
        pthread_mutex_unlock(&control_mutex);
        const uint64_t now=milliseconds();
        if(force_native_admission||!admission_known||admission_generation!=generation
            ||admission_identity!=identity||now<admission_at||now-admission_at>=250){
            admission_known=false; // An original callback exception must not revive an older positive.
            admission_result=native_scene_control.admit(native_scene_context);
            snprintf(admission_error,sizeof(admission_error),"%s",admission_result==Result::ok?"none":
                native_scene_error("selected_scene_admission_failed"));
            admission_at=now;admission_generation=generation;admission_identity=identity;admission_known=true;
        }
        result=admission_result;error=admission_error;
        last_admission_verified=result==Result::ok;
    }
    int32_t width=0,height=0;
    if(result==Result::ok&&game.has_source_geometry_probe()){
        result=game.source_geometry(width,height);
        if(result!=Result::ok)error=result==Result::waiting?"selected_capture_geometry_not_ready":"selected_capture_geometry_unsupported";
    }
    if(result==Result::ok&&!game.has_source_geometry_probe())game.source_geometry(width,height);
    pthread_mutex_lock(&control_mutex);published.ready=result==Result::ok;
    if(result!=Result::ok&&!strcmp(error,"selected_render_controller_missing")
        &&strcmp(controller_discovery.reason,"none"))error=controller_discovery.reason;
    // This is an observed original render texture, never a Screen estimate.
    published.source_width=result==Result::ok&&idoly_mp4_output::source_dimensions(width,height)?static_cast<uint32_t>(width):selected_mv?selected_source_width:0;
    published.source_height=result==Result::ok&&published.source_width?static_cast<uint32_t>(height):selected_mv?selected_source_height:0;
    snprintf(readiness_error,sizeof(readiness_error),"%s",error);pthread_mutex_unlock(&control_mutex);
    return result;
}
inline bool configure(const char* broker,uint64_t epoch,const char*cap,const char*output,int platform){
    if(!safe_root(broker)||!safe_root(output)||epoch==0||epoch>9007199254740991ULL||(platform!=1&&platform!=2))return false;
    Configuration next{};if(!decode_capability(cap,next.capability))return false;
    snprintf(next.broker,sizeof(next.broker),"%s",broker);snprintf(next.output,sizeof(next.output),"%s",output);next.epoch=epoch;next.platform=platform;
    char expected_output[path_capacity]{};if(!join_path(expected_output,sizeof(expected_output),broker,"exports"))return false;
    if(strcmp(output,expected_output))return false;
    next.root=open(broker,rd|directory|nofollow);next.exports=openat(next.root,"exports",rd|directory|nofollow);
    next.req=openat(next.root,"req",rd|directory|nofollow);next.rsp=openat(next.root,"rsp",rd|directory|nofollow);next.prepared=openat(next.root,"prepared",rd|directory|nofollow);
    if(!private_directory(next.root)||!private_directory(next.req)||!private_directory(next.rsp)||!private_directory(next.prepared)||!private_directory(next.exports)){close_configuration(next);return false;}
    pthread_mutex_lock(&control_mutex);
    if(control_busy||start_pending){pthread_mutex_unlock(&control_mutex);close_configuration(next);return false;}
    const bool replaced=!configured_valid||configured.epoch!=next.epoch||configured.platform!=next.platform
        ||strcmp(configured.broker,next.broker)||strcmp(configured.output,next.output)||memcmp(configured.capability,next.capability,16);
    close_configuration(configured);configured=next;configured_valid=true;
    if(replaced)invalidate_queue_selection_locked("server_configuration_changed");
    pthread_mutex_unlock(&control_mutex);return true;
}
inline bool start(Options options,bool queued=false){pthread_mutex_lock(&control_mutex);bool ok=configured_valid&&!control_busy&&!start_pending&&(queued||!queue_scene_owned)&&published.ready&&valid_options(options);if(ok){if(!queued){pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;pending_queue_width=pending_queue_height=0;}diagnostic_event("start","accepted");pending_options=options;start_pending=true;start_wait_started=0;cancel_pending=false;control_busy=true;published.pausable=true;pause_acknowledged=false;snprintf(published.phase,sizeof(published.phase),"preparing_audio");snprintf(published.error,sizeof(published.error),"none");}else diagnostic_event("start",!configured_valid?"session_not_configured":control_busy||start_pending?"export_already_owned":!published.ready?readiness_error:"invalid_export_options",0,0,true);pthread_mutex_unlock(&control_mutex);return ok;}
inline void cancel(){pthread_mutex_lock(&control_mutex);if(control_busy)cancel_pending=true;pthread_mutex_unlock(&control_mutex);}
inline void suspend(int reason){
    if(reason<IDMP4_PAUSE_LIFECYCLE_BACKGROUND||reason>IDMP4_PAUSE_USER)return;
    pthread_mutex_lock(&control_mutex);requested_pause_reason=reason;pthread_mutex_unlock(&control_mutex);
}
inline void resume(){
    pthread_mutex_lock(&control_mutex);
    // A lifecycle can stop the original engine before its next tick. Reset
    // deadlines even if no tick was available to acknowledge the request.
    if(requested_pause_reason!=IDMP4_PAUSE_NONE||pause_acknowledged)reset_watchdog_pending=true;
    requested_pause_reason=IDMP4_PAUSE_NONE;pause_acknowledged=false;
    pthread_mutex_unlock(&control_mutex);
}
inline const char* pause_reason_name(int reason){
    switch(reason){case IDMP4_PAUSE_LIFECYCLE_BACKGROUND:return "lifecycle_background";
        case IDMP4_PAUSE_SURFACE_UNAVAILABLE:return "surface_unavailable";
        case IDMP4_PAUSE_USER:return "user_paused";default:return "none";}
}
inline void install_game_api(const Api& api,const Layout& layout){if(installed||busy_stage())return;installed=game.set_api(api,layout)&&selection.set_api(api);}
inline idoly_mp4_playback::ClockState native_clock_state(){
    return {native_engine_clock.active(),native_engine_clock.held()};
}
inline bool install_dependent_api(
        idoly_mp4_playback::OriginalApi<idoly_mp4_game::PlayableGraph> original,
        idoly_mp4_playback::Dependents dependents,void* context,
        idoly_mp4_playback::ShaderLeaseApi shader){
    // Installation is a main-thread publication of verified original calls.
    // It must preserve the observed MV and cannot replace an active owner.
    pthread_mutex_lock(&control_mutex);
    const bool available=installed&&native_clock_available()&&!control_busy&&!start_pending&&!busy_stage();
    const bool result=available&&game.install_dependent_api(original,dependents,context,native_clock_state,shader);
    pthread_mutex_unlock(&control_mutex);return result;
}
inline bool install_native_scene_api(
        idoly_mp4_playback::OriginalApi<idoly_mp4_game::PlayableGraph> original,
        idoly_mp4_playback::Dependents dependents,void* context,NativeSceneControl controls,
        idoly_mp4_playback::ShaderLeaseApi shader){
    // Partial dependency installations never enable the new render loop.
    if(!context||!controls.valid()||native_scene_installed)return false;
    if(!install_dependent_api(original,dependents,context,shader))return false;
    native_scene_control=controls;native_scene_context=context;
    native_owned_boundary=native_render_boundary;native_scene_installed=true;return true;
}
inline bool install_fresh_scene_api(const FreshSceneApi&api){
    if(!api.valid()||fresh_scene_installed.load(std::memory_order_acquire)||!installed||!native_clock_available()
        ||busy_stage()||control_busy||start_pending)return false;
    if(!game.install_fresh_audio_validation(api.context,api.audio_source_error))return false;
    fresh_scene_api=api;
    native_diagnostics=NativeSceneDiagnostics{};last_admission_verified=false;
    native_owned_boundary=native_fresh_render_boundary;
    fresh_scene_installed.store(true,std::memory_order_release);return true;
}
inline void observe_presenter(void* presenter){if(installed){
    if(native_scene_installed&&presenter&&presenter!=observed_presenter_scope&&game.automatic())
        native_scene_control.restore_globals_before_source_change(native_scene_context);
    game.observe_presenter(presenter);void* scope=game.selected_presenter();const uint64_t identity=selection.identity(game.selected_player());
    pthread_mutex_lock(&control_mutex);
    if(scope!=observed_presenter_scope||(identity&&selected_identity&&identity!=selected_identity))
        invalidate_queue_selection_locked("selected_mv_selection_changed");
    observed_presenter_scope=scope;selected_identity=identity;pthread_mutex_unlock(&control_mutex);
}}
inline void observe_presenter_ended(void* presenter){
    if(!installed)return;
    const bool selected=game.selected_presenter()==presenter;
    if(native_scene_installed&&game.owns_automatic_source_raw(presenter))
        native_scene_control.restore_globals_before_source_change(native_scene_context);
    game.release_shader_lease_for_scene(presenter);
    game.observe_presenter_ended(presenter);
    if(selected){pthread_mutex_lock(&control_mutex);selected_identity=0;observed_presenter_scope=nullptr;published.ready=false;
        selected_mv=false;selected_source_width=selected_source_height=0;snprintf(selection_error,sizeof(selection_error),"selected_mv_ended");
        invalidate_queue_selection_locked("selected_mv_ended");
        controller_discovery=ControllerDiscovery{};
        snprintf(controller_discovery.reason,sizeof(controller_discovery.reason),"%s","selected_mv_ended");
        snprintf(readiness_error,sizeof(readiness_error),"%s","selected_mv_ended");pthread_mutex_unlock(&control_mutex);}
}
inline void observe_source_will_change(void* source){
    if(!installed||!source)return;
    if(native_scene_installed&&game.owns_automatic_source_raw(source))
        native_scene_control.restore_globals_before_source_change(native_scene_context);
    // Return the owned global shader baseline before the original lifecycle
    // method can initialize a replacement scene. Generation invalidation is
    // scalar-only; it must not make this old lease outlive the new scene.
    game.release_shader_lease_for_scene(source);
    game.invalidate_owned_scene(source);
    pthread_mutex_lock(&control_mutex);selected_mv=false;selected_source_width=selected_source_height=0;
    snprintf(selection_error,sizeof(selection_error),"selected_mv_reinitializing");invalidate_queue_selection_locked("selected_mv_reinitializing");pthread_mutex_unlock(&control_mutex);
}
// A pre-initialize observer is auxiliary to the original game lifecycle. If
// it throws, the typed host forwards the original exactly once and calls this
// pure poison path. No Unity restoration/GC/encoder action runs in this catch.
inline void observe_source_handoff_failed(void* source) noexcept {
    const bool owned=game.source_handoff_failed(source);
    if(!owned)return; // Unrelated lifecycle observers cannot poison this MV.
    if(native_scene_installed){
        try{native_scene_control.revoke_grants(native_scene_context);}catch(...){}
        try{native_scene_control.abandon_globals(native_scene_context);}catch(...){}
    }
    if(job.automatic&&busy_stage()){
        job.clock_lost=true;job.terminal_success=false;job.terminal_cancel=false;
        job.cancel_encoder_pending=true;job.stage=Stage::retiring;
        stable_error("source_handoff_failed");
        snprintf(job.status.phase,sizeof(job.status.phase),"%s","failed");
    }
    pthread_mutex_lock(&control_mutex);
    if(job.automatic&&busy_stage())published=job.status;
    published.ready=false;native_observation.source_valid=false;
    invalidate_queue_selection_locked("source_handoff_failed");
    snprintf(readiness_error,sizeof(readiness_error),"%s","source_handoff_failed");
    pthread_mutex_unlock(&control_mutex);
}
inline void observe_player_initializing(void* player,void* param){if(installed){observe_source_will_change(player);selection.observe(player,param);}}
inline void observe_photography_initializing(void* player,void* data,void* descriptors){if(installed){observe_source_will_change(player);selection.observe_photography(player,data,descriptors);}}
inline void observe_photography_transition(void* player,void* transition){
    if(!installed)return;
    selection.attach_photography_transition(player,transition);
    if(fresh_scene_installed.load(std::memory_order_acquire)){FreshFactoryRequest request{};(void)fresh_factory_request(player,&request);}
    const uint64_t identity=selection.identity(game.selected_player());
    pthread_mutex_lock(&control_mutex);if(identity&&selected_identity&&identity!=selected_identity)
        invalidate_queue_selection_locked("selected_mv_selection_changed");
    selected_identity=identity;pthread_mutex_unlock(&control_mutex);
}
inline void observe_camera_controller(void* camera){if(installed){
    if(native_scene_installed&&camera&&camera!=observed_camera_controller_scope&&game.automatic())
        native_scene_control.restore_globals_before_source_change(native_scene_context);
    game.observe_camera_controller(camera);observed_camera_controller_scope=camera;
}}
inline void capture_pass_did_execute(void* pass,const void*data){try{if(installed)game.observe_capture_pass(pass,data);}catch(...){export_observer_failed();}}
inline void camera_did_render(void*camera){try{const bool preparing=job.automatic&&job.stage==Stage::render_setup
        &&!job.auto_started&&job.capture_requested&&(job.prewarm_inflight||job.prewarm_completed)
        &&job.source_generation==game.owned_scene_generation();
    if(installed&&(job.stage==Stage::frame_wait||preparing)&&!job.captured
    &&(!job.automatic||preparing||(job.capture_requested&&job.schedule.awaiting_frame()
        &&job.source_generation==game.owned_scene_generation()))&&game.after_camera(camera)){
    if(job.automatic&&!preparing&&game.validate_automatic_frame(static_cast<double>(job.frame)*job.options.fps_den/job.options.fps_num)!=Result::ok){
        terminal(game.last_error());return;
    }
    job.captured=true;pthread_mutex_lock(&control_mutex);increment_counter(capture_acks);pthread_mutex_unlock(&control_mutex);}}catch(...){export_observer_failed();}
    try{if(installed){idoly_mp4_game::SceneWitness witness{};
        if(game.selected_scene_witness(witness)&&witness.camera==camera)refresh_native_observation(true);
    }}catch(...){pthread_mutex_lock(&control_mutex);native_observation.source_valid=false;pthread_mutex_unlock(&control_mutex);}
}
inline bool camera_delta_override(void*brain,float*delta){return installed&&game.camera_delta_override(brain,delta);}

inline bool begin_job() {
    pthread_mutex_lock(&control_mutex);
    if(!start_pending){pthread_mutex_unlock(&control_mutex);return false;}
    idoly_mp4_queue::detail::reset_value(job);job.options=pending_options;job.config=configured;
    job.config.root=dup(configured.root);job.config.req=dup(configured.req);job.config.rsp=dup(configured.rsp);job.config.prepared=dup(configured.prepared);job.config.exports=dup(configured.exports);
    if(pending_queue_output[0]){
        snprintf(job.status.id,sizeof(job.status.id),"%s",pending_queue_output);
        close(job.config.exports);job.config.exports=dup(pending_queue_exports_fd);
        snprintf(job.config.output,sizeof(job.config.output),"%s",pending_queue_exports);
        job.expected_width=pending_queue_width;job.expected_height=pending_queue_height;
        pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;
    }
    start_pending=false;job.stage=Stage::begin;job.fresh=fresh_scene_installed.load(std::memory_order_acquire);
    job.automatic=native_scene_required||job.fresh;
    if(next_job_generation){job.generation=next_job_generation;next_job_generation=next_job_generation==~uint64_t(0)?0:next_job_generation+1;}
    pthread_mutex_unlock(&control_mutex);
    if(!job.generation){terminal("export_generation_exhausted");return true;}
    job.api=platform_encoder();job.status.fps_num=job.options.fps_num;job.status.fps_den=job.options.fps_den;job.status.video_codec=job.options.codec;
    if(!job.status.id[0]){uint8_t id[16]{};if(!random_bytes(id,sizeof(id))){terminal("random_unavailable");return true;}hex(id,sizeof(id),job.status.id);}
    if(!job.api.valid()){terminal("platform_encoder_unavailable");return true;}
    if(!active_broker()){terminal("audio_broker_retired");return true;}
    if(probe_readiness(job.snapshot)!=Result::ok){terminal(readiness_error);return true;}
    if(job.automatic){job.stage=Stage::scene_acquire;phase("preparing_audio");return true;}
    if(game.begin_manual()!=Result::ok){terminal(game.last_error());return true;}
    job.stage=Stage::audio_setup;return true;
}
inline void setup_audio_job(){
    int32_t source_width=0,source_height=0;const Result geometry=game.source_geometry(source_width,source_height);
    uint32_t output_width=job.options.output_width,output_height=job.options.output_height;
    if(geometry==Result::ok&&!idoly_mp4_output::resolved_dimensions(source_width,source_height,output_width,output_height,output_width,output_height)){
        terminal("output_geometry_invalid");return;
    }
    const bool normalize_odd=geometry==Result::ok&&((source_width&1)||(source_height&1));
    if(job.options.output_width||normalize_odd){
        if(!output_width||!output_height){terminal("output_render_geometry_unavailable");return;}
        if(game.set_output_geometry(output_width,output_height)!=Result::ok){terminal(game.last_error());return;}
        job.expected_width=output_width;job.expected_height=output_height;
    }
    for(size_t i=0;i<job.snapshot.audio.count;++i){const auto& c=job.snapshot.audio.clips[i];if(!c.muted&&c.track_gain*c.clip_gain*c.source_gain>0){if(!job.rate)job.rate=static_cast<uint32_t>(c.sample_rate);if(job.rate!=static_cast<uint32_t>(c.sample_rate)){terminal("mixed_sample_rates_unsupported");return;}}}
    if(!job.rate){terminal("selected_mv_has_no_audible_music");return;}
    job.total_audio=static_cast<uint64_t>(__builtin_llround(job.snapshot.duration_seconds*job.rate));
    job.total_frames=(job.total_audio*job.options.fps_num+static_cast<uint64_t>(job.rate)*job.options.fps_den-1)/(static_cast<uint64_t>(job.rate)*job.options.fps_den);
    if(!job.total_audio||!job.total_frames||job.total_audio>static_cast<uint64_t>(job.rate)*900){terminal("audio_duration_invalid");return;}
    job.status.total_audio=job.total_audio;job.status.total_frames=job.total_frames;
    snprintf(job.pcm_name,sizeof(job.pcm_name),"%s.pcm",job.status.id);
    char partial_name[48]{},final_name[48]{};
    snprintf(partial_name,sizeof(partial_name),"%s.partial.mp4",job.status.id);
    snprintf(final_name,sizeof(final_name),"%s.mp4",job.status.id);
    if(!join_path(job.pcm_path,sizeof(job.pcm_path),job.config.output,job.pcm_name)
        ||!join_path(job.partial_path,sizeof(job.partial_path),job.config.output,partial_name)
        ||!join_path(job.final_path,sizeof(job.final_path),job.config.output,final_name)){terminal("export_path_too_long");return;}
    job.pcm=openat(job.config.exports,job.pcm_name,rw|create|exclusive|nofollow,0600);
    job.pcm_owned=job.pcm>=0&&fstat(job.pcm,&job.pcm_identity)==0;
    if(job.pcm<0||ftruncate(job.pcm,static_cast<int64_t>(job.total_audio*8))!=0){terminal("pcm_file_create_failed");return;}
    job.stage=Stage::audio_request;phase("preparing_audio");
}
inline bool request_audio() {
    if(!cleanup_bundle())return false;
    while(job.clip<job.snapshot.audio.count){const auto& c=job.snapshot.audio.clips[job.clip];if(!c.muted&&c.track_gain*c.clip_gain*c.source_gain>0)break;++job.clip;}
    if(job.clip==job.snapshot.audio.count){job.stage=Stage::audio_finalize;progress();return true;}
    const auto& c=job.snapshot.audio.clips[job.clip];
    job.start_sample=static_cast<uint64_t>(__builtin_llround(c.start_seconds*job.rate));
    job.source_offset=static_cast<uint64_t>(__builtin_llround(c.clip_in_seconds*job.rate));
    job.clip_frames=static_cast<uint64_t>(__builtin_llround(c.duration_seconds*job.rate));job.mixed=0;
    if(job.start_sample>=job.total_audio||job.source_offset>=static_cast<uint64_t>(c.samples)){terminal("audio_clip_range_invalid");return false;}
    if(job.clip_frames>job.total_audio-job.start_sample)job.clip_frames=job.total_audio-job.start_sample;
    // The original Timeline may deliberately hold silence after its clip end.
    if(job.clip_frames>static_cast<uint64_t>(c.samples)-job.source_offset)job.clip_frames=static_cast<uint64_t>(c.samples)-job.source_offset;
    size_t name_length=strlen(c.clip_name);if(!name_length||name_length>192||!random_bytes(job.request_id,16)){terminal("audio_request_invalid");return false;}
    hex(job.request_id,16,job.request_hex);snprintf(job.request_name,sizeof(job.request_name),"%s.req",job.request_hex);snprintf(job.response_name,sizeof(job.response_name),"%s.rsp",job.request_hex);
    uint8_t wire[260]{};memcpy(wire,"IDMPAUD1",8);put16(wire+8,1);wire[10]=static_cast<uint8_t>(job.config.platform);put64(wire+12,job.config.epoch);memcpy(wire+20,job.config.capability,16);memcpy(wire+36,job.request_id,16);put16(wire+52,static_cast<uint16_t>(name_length));wire[54]=static_cast<uint8_t>(c.channels);put32(wire+56,static_cast<uint32_t>(c.sample_rate));put64(wire+60,static_cast<uint64_t>(c.samples));memcpy(wire+68,c.clip_name,name_length);
    char temporary[48]{};snprintf(temporary,sizeof(temporary),"%s.tmp",job.request_hex);
    int fd=openat(job.config.req,temporary,wr|create|exclusive|nofollow,0600);
    struct stat owned{};const bool created=fd>=0&&fstat(fd,&owned)==0;
    const bool ok=created&&exact_write(fd,wire,68+name_length)&&fsync(fd)==0;if(fd>=0)close(fd);
    if(!ok||renameat(job.config.req,temporary,job.config.req,job.request_name)!=0){if(created)unlink_owned(job.config.req,temporary,owned);terminal("audio_request_write_failed");return false;}
    job.pending_broker=true;
    job.stage=Stage::audio_response;progress();return true;
}
// 0 is pending, 1 is the exact owned response, -1 is an untrusted record.
inline int read_audio_response(uint8_t& status) {
    int fd=openat(job.config.rsp,job.response_name,rd|nofollow|nonblock);if(fd<0)return 0;
    struct stat response_identity{};uint8_t raw[52]{};const bool valid=fstat(fd,&response_identity)==0&&private_file(fd,52)&&(response_identity.st_mode&0777)==0600&&exact_read(fd,raw,sizeof(raw))&&!memcmp(raw,"IDMPARS1",8)&&raw[8]==1&&raw[9]==0&&raw[10]<=4&&raw[11]==0&&get64(raw+12)==job.config.epoch&&!memcmp(raw+20,job.config.capability,16)&&!memcmp(raw+36,job.request_id,16);close(fd);
    if(!valid)return -1;
    unlink_owned(job.config.rsp,job.response_name,response_identity);
    job.pending_broker=false;status=raw[10];return 1;
}
inline bool register_prepared_bundle() {
    char name[48]{};snprintf(name,sizeof(name),"%s.bundle",job.request_hex);int fd=openat(job.config.prepared,name,rd|nofollow|nonblock);
    struct stat prepared_identity{};
    const bool file_ok=private_file(fd,96*1024*1024+65536)&&fstat(fd,&prepared_identity)==0&&prepared_identity.st_size>0&&(prepared_identity.st_mode&0777)==0400;if(fd>=0)close(fd);if(!file_ok)return false;
    job.bundle_identity=prepared_identity;job.bundle_owned=true;snprintf(job.bundle_name,sizeof(job.bundle_name),"%s",name);
    char prepared_root[path_capacity]{};
    return join_path(prepared_root,sizeof(prepared_root),job.config.broker,"prepared")&&join_path(job.bundle_path,sizeof(job.bundle_path),prepared_root,name);
}
inline void poll_audio_response() {
    uint8_t status=0;int response=read_audio_response(status);if(!response)return;
    if(response<0){job.pending_broker=false;terminal("invalid_audio_broker_response");return;}
    if(status!=0){terminal(status==1?"selected_music_not_in_manifest":status==4?"selected_music_format_unsupported":"audio_preparation_failed");return;}
    if(!register_prepared_bundle()){terminal("private_audio_file_invalid");return;}
    Result r=game.begin_private_audio(job.bundle_path,job.snapshot.audio.clips[job.clip]);
    if(r!=Result::waiting&&r!=Result::ok){terminal(game.last_error());return;}job.stage=Stage::audio_load;progress();
}
inline bool retire_pending_audio() {
    if(!job.pending_broker)return true;
    // Stop retires the producer capability. Otherwise wait for the bounded
    // preparation, even after cancellation, so its late clone is not orphaned.
    if(!active_broker()){job.pending_broker=false;return true;}
    uint8_t status=0;int response=read_audio_response(status);if(!response)return false;
    if(response<0){job.pending_broker=false;job.terminal_success=job.terminal_cancel=false;stable_error("invalid_audio_broker_response");return true;}
    if(status!=0)return true;
    // Unity never opened this late result. Register only the exact immutable
    // inode; ordinary cleanup still waits for original-Unity quiescence.
    if(!register_prepared_bundle()){job.terminal_success=job.terminal_cancel=false;stable_error("private_audio_file_invalid");}
    return true;
}
inline void mix_audio() {
    const auto& clip=job.snapshot.audio.clips[job.clip];
    const uint64_t remaining=job.clip_frames-job.mixed;const int32_t frames=static_cast<int32_t>(remaining>8192?8192:remaining);
    if(!frames){game.close_private_audio();++job.clip;job.stage=Stage::audio_request;progress();return;}
    const auto r=game.read_audio_chunk(static_cast<int32_t>(job.source_offset+job.mixed),frames,job.source,8192*2);
    if(r==Result::waiting)return;
    if(r!=Result::ok){terminal(game.last_error());return;}
    const size_t bytes=static_cast<size_t>(frames)*8;const int64_t offset=static_cast<int64_t>((job.start_sample+job.mixed)*8);
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,false)){terminal("pcm_read_failed");return;}
    const float gain=clip.track_gain*clip.clip_gain*clip.source_gain;
    for(int32_t i=0;i<frames;++i)for(int channel=0;channel<2;++channel){size_t target=static_cast<size_t>(i)*2+static_cast<size_t>(channel);float value=job.mixed_pcm[target]+job.source[static_cast<size_t>(i)*static_cast<size_t>(clip.channels)+static_cast<size_t>(clip.channels==1?0:channel)]*gain;if(!__builtin_isfinite(value)){terminal("audio_mix_nonfinite");return;}job.mixed_pcm[target]=value;}
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,true)){terminal("pcm_write_failed");return;}
    job.mixed+=static_cast<uint64_t>(frames);job.status.audio=job.start_sample+job.mixed;progress();publish();
}
inline void finalize_audio() {
    uint64_t remaining=job.total_audio-job.finalized_audio;size_t frames=static_cast<size_t>(remaining>8192?8192:remaining);
    if(!frames){if(!job.audible_energy){terminal("selected_music_is_silent");return;}if(fsync(job.pcm)!=0){terminal("pcm_sync_failed");return;}close(job.pcm);job.pcm=-1;job.stage=job.automatic?Stage::render_setup:Stage::frame_request;phase("rendering");return;}
    size_t bytes=frames*8;int64_t offset=static_cast<int64_t>(job.finalized_audio*8);
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,false)){terminal("pcm_read_failed");return;}
    for(size_t i=0;i<frames*2;++i){float value=job.mixed_pcm[i];if(!__builtin_isfinite(value)){terminal("audio_mix_nonfinite");return;}if(value>0.000000001f||value< -0.000000001f)job.audible_energy=true;job.mixed_pcm[i]=value>1?1:value< -1?-1:value;}
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,true)){terminal("pcm_write_failed");return;}
    job.finalized_audio+=frames;job.status.audio=job.finalized_audio;progress();publish();
}
inline bool prepare_frame_output(){
    int32_t width=0,height=0;if(game.capture_geometry(width,height)!=Result::ok){terminal(game.last_error());return false;}
    if((job.expected_width&&job.expected_width!=static_cast<uint32_t>(width))
        ||(job.expected_height&&job.expected_height!=static_cast<uint32_t>(height))){terminal("queued_capture_geometry_changed");return false;}
    if(!idoly_mp4_output::source_dimensions(static_cast<uint32_t>(width),static_cast<uint32_t>(height))){terminal("capture_geometry_not_supported");return false;}
    if(job.status.source_width&&(job.status.source_width!=static_cast<uint32_t>(width)||job.status.source_height!=static_cast<uint32_t>(height))){terminal("capture_geometry_changed");return false;}
    job.status.source_width=static_cast<uint32_t>(width);job.status.source_height=static_cast<uint32_t>(height);
    job.status.width=job.options.output_width?job.options.output_width:static_cast<uint32_t>(width)&~1U;
    job.status.height=job.options.output_height?job.options.output_height:static_cast<uint32_t>(height)&~1U;
    job.status.video_codec=job.options.codec;
    job.status.video_bitrate=idoly_mp4_output::resolved_bitrate(job.options.bitrate,job.status.width,job.status.height,job.options.fps_num,job.options.codec);
    if(!job.status.video_bitrate){terminal("invalid_export_options");return false;}
    const size_t needed=static_cast<size_t>(width)*static_cast<size_t>(height)*4;
    if(!job.rgba){job.rgba=static_cast<uint8_t*>(malloc(needed));job.rgba_capacity=needed;if(!job.rgba){terminal("frame_buffer_allocation_failed");return false;}}
    if(job.rgba_capacity!=needed){terminal("frame_buffer_geometry_changed");return false;}
    if(job.status.width!=static_cast<uint32_t>(width)||job.status.height!=static_cast<uint32_t>(height)){
        terminal("output_render_geometry_mismatch");return false;
    }
    if(!job.encoder){IDMP4EncoderConfig c{};c.struct_size=sizeof(c);c.abi_version=1;c.width=job.status.width;c.height=job.status.height;c.fps_num=job.options.fps_num;c.fps_den=job.options.fps_den;c.video_codec=job.options.codec;c.video_bitrate=job.status.video_bitrate;c.audio_sample_rate=job.rate;c.audio_channels=2;c.audio_bitrate=job.options.audio_bitrate;c.audio_sample_frames=job.total_audio;c.video_frame_count=job.total_frames;c.pcm_f32_path=job.pcm_path;c.partial_path=job.partial_path;c.final_path=job.final_path;char error[192]{};job.encoder=job.api.create(&c,error,sizeof(error));if(!job.encoder){terminal(error);return false;}}
    return true;
}
inline void request_frame() {
    if(job.frame>=job.total_frames){if(!job.encoder||job.api.finish(job.encoder)<0){terminal("encoder_finish_rejected");return;}job.stage=Stage::finishing;phase("finishing");return;}
    const double time=static_cast<double>(job.frame)*job.options.fps_den/job.options.fps_num;
    if(game.evaluate(time)!=Result::ok||game.request_capture()!=Result::ok){terminal(game.last_error());return;}
    if(!prepare_frame_output())return;
    job.captured=false;job.stage=Stage::frame_wait;progress();publish();
}
inline void encoder_poll() {
    if(!job.encoder)return;
    IDMP4EncoderStatus s{};s.struct_size=sizeof(s);s.abi_version=1;
    if(job.api.poll(job.encoder,&s)<0){terminal("encoder_status_failed");return;}
    job.status.bytes=s.bytes_written;
    uint64_t count=s.encoded_frames+s.audio_frames;
    if(count!=job.last_encoder_progress){job.last_encoder_progress=count;progress();}
    if(s.phase==IDMP4_FAILED){terminal(s.error_code);return;}
    if(s.phase==IDMP4_CANCELLED&&job.stage!=Stage::retiring){terminal("encoder_cancelled",true);return;}
    if(s.phase==IDMP4_COMPLETED&&job.stage==Stage::finishing){job.media_finalized=true;job.terminal_success=true;job.stage=Stage::retiring;
        if(!job.automatic&&game.restore()!=Result::ok){job.terminal_success=false;stable_error(game.last_error());}phase("finishing");}
}
inline void service_deferred_encoder_cancel(){
    if(!job.cancel_encoder_pending)return;
    if(job.encoder)job.api.cancel(job.encoder);
    job.cancel_encoder_pending=false;
}
inline void restoration_failure(const char* reason){
    diagnostic_event("source_restore",reason,job.frame,job.schedule.next_tick()?job.schedule.next_tick()-1:0,true);
    job.terminal_success=false;
    if(!job.status.restoration_error[0]||!strcmp(job.status.restoration_error,"none")){
        size_t at=0;
        for(;reason&&reason[at]&&at<sizeof(job.status.restoration_error)-1;++at){
            const char c=reason[at];job.status.restoration_error[at]=
                ((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_')?c:'_';
        }
        job.status.restoration_error[at]=0;
        if(!at)snprintf(job.status.restoration_error,sizeof(job.status.restoration_error),"restoration_failed");
    }
    // An encoder failure or explicit cancellation remains the primary cause.
    if(!job.status.error[0]||!strcmp(job.status.error,"none"))stable_error(job.status.restoration_error);
}
inline bool service_post_restore(){
    static bool running=false;
    if(running)return false;
    struct Guard{bool& value;explicit Guard(bool& v):value(v){value=true;}~Guard(){value=false;}} guard(running);
    if(!job.automatic||job.fresh)return true;
    if(!job.scene_detached)return false;
    if(!job.post_verify_done){
        if(!job.logical_checkpoint_valid){job.post_verify_done=true;job.post_verified=false;}
        else {
            const uint64_t now=milliseconds();
            if(!job.post_wait_started)job.post_wait_started=now;
            Result result=Result::failed;
            try{result=native_scene_control.verify_post_restore(native_scene_context);}
            catch(...){job.post_verify_done=true;restoration_failure("source_audio_verification_exception");}
            if(!job.post_verify_done){
                if(result==Result::waiting){
                    // A latched successful natural receipt wins over elapsed
                    // wall time; only a still-missing receipt can time out.
                    if(now<job.post_wait_started||now-job.post_wait_started<=15000)return false;
                    job.post_verify_done=true;restoration_failure("source_audio_restoration_timeout");
                }else {
                    job.post_verify_done=true;job.post_verified=result==Result::ok;
                    if(!job.post_verified)restoration_failure(native_scene_error("source_audio_restoration_failed"));
                }
            }
        }
    }
    job.camera_audio_restored=job.logical_checkpoint_valid&&job.logical_camera_audio&&job.post_verified;
    job.restoration_verified=job.logical_checkpoint_valid&&job.clock_settings_restored
        &&job.camera_audio_restored&&job.dependent_state_restored;
    if(!job.post_release_done){
        Result released=Result::failed;
        try{released=native_scene_control.release_post_restore(native_scene_context);}
        catch(...){restoration_failure("source_audio_release_exception");return false;}
        // A failure does not prove that retained native-reader/GC duties were
        // discharged. Remain busy until the independent owner returns OK.
        if(released!=Result::ok){
            if(released!=Result::waiting)restoration_failure(native_scene_error("source_audio_release_failed"));
            return false;
        }
        job.post_release_done=true;
    }
    return true;
}
inline void retire() {
    static bool running=false;
    if(running)return;
    struct Guard{bool& value;explicit Guard(bool& v):value(v){value=true;}~Guard(){value=false;}} guard(running);
    if(job.automatic&&!job.scene_restored&&!(job.fresh&&job.fresh_finish_settled))return;
    service_deferred_encoder_cancel();
    if(game.restoration_pending()){
        const Result restored=game.restore();
        if(restored!=Result::ok&&restored!=Result::waiting){
            restoration_failure(game.last_error());
        }
        // An owned native job or an asynchronous restoration step can outlive
        // the UI's cancel/finish request. Retain its scene roots and buffers;
        // a new job cannot inherit resources still owned by this one.
        if(game.restoration_pending())return;
    }
    if(!service_post_restore())return;
    if(!retire_pending_audio())return;
    if(job.encoder){const int result=job.api.destroy(job.encoder);if(result==IDMP4_RETRY)return;if(result<0)restoration_failure("encoder_cleanup_failed");job.encoder=nullptr;}
    if(!cleanup_bundle())return; // Original Unity async bundle IO must finish first.
    if(job.pcm>=0){close(job.pcm);job.pcm=-1;}
    if(job.pcm_owned)unlink_owned(job.config.exports,job.pcm_name,job.pcm_identity);
    if(job.rgba){free(job.rgba);job.rgba=nullptr;}
    close_configuration(job.config);
    if(job.fresh)fresh_release_start();
    job.stage=Stage::idle;
    phase((job.terminal_success||(job.fresh&&job.media_finalized))?"completed":job.terminal_cancel?"cancelled":"failed");
    pthread_mutex_lock(&control_mutex);control_busy=false;cancel_pending=false;pthread_mutex_unlock(&control_mutex);
}
// BEGIN_MP4_NATIVE_BOUNDARY
struct NativeBoundaryCall {bool called=false;};
static NativeBoundaryCall* active_boundary_call=nullptr;
inline bool native_boundary_clock_tick(void* manager,double wall,idoly_mp4_engine_clock::Grant grant={}){
    if(active_boundary_call){
        if(active_boundary_call->called){terminal("native_clock_double_dispatch");return false;}
        active_boundary_call->called=true;
    }
    return native_engine_clock.native_tick(manager,wall,grant);
}
// All source restoration runs at the same native boundary as simulation.
// Quality.Update only services commands, private audio and encoder completion.
inline Result restore_owned_scene(void* manager,double wall){
    if(job.scene_restored)return Result::ok;
    if(!job.automatic)return Result::invalid;
    auto& clock=native_engine_clock;
    if(!job.logical_checkpoint_done){
        if(clock.active()&&!clock.hold_for_boundary(manager,wall))job.clock_lost=true;
        if(!clock.active())job.clock_lost=true;
        Result result=Result::ok;
        if(game.automatic()&&!job.clock_lost){
            result=game.prepare_restore();
            if(result==Result::waiting)return result;
            if(result!=Result::ok){job.clock_lost=true;restoration_failure(game.last_error());}
            if(!job.clock_lost){
                const bool owned=game.owned_primary_scene_current()
                    &&native_scene_control.source_clock_restorable(native_scene_context);
                if(!owned||!clock.rebase_for_restore(manager,wall,true))job.clock_lost=true;
            }
            if(!job.clock_lost){
                result=game.restore_logical();
                if(result==Result::waiting)return result;
                if(result!=Result::ok){job.clock_lost=true;restoration_failure(game.last_error());}
            }
            if(!job.clock_lost&&result==Result::ok){
                // Historical evidence: all snapshots are compared while the
                // source clock is held. Ordinary source progress after detach
                // must never be compared against these old time/history bytes.
                native_scene_control.attest(native_scene_context,&job.logical_camera_audio,&job.dependent_state_restored);
                job.restored_source_valid=game.observe_source(job.restored_source_time,job.restored_source_paused);
                job.restored_source_identity=selected_identity;
                job.logical_checkpoint_valid=job.scene_acquired&&job.logical_camera_audio&&job.dependent_state_restored
                    &&job.restored_source_valid&&job.acquired_source_valid
                    &&job.restored_source_identity==job.acquired_source_identity
                    &&job.restored_source_paused==job.acquired_source_paused
                    &&std::fabs(job.restored_source_time-job.acquired_source_time)<=.0001;
                if(!job.logical_checkpoint_valid)restoration_failure("source_restoration_checkpoint_failed");
            }
        }
        job.logical_checkpoint_done=true;
        if(job.clock_lost)restoration_failure("native_clock_or_scene_ownership_lost");
    }
    if(!job.scene_detached){
        // This is also owed after partial capture, cancellation and source
        // loss. An old resource reader may WAIT, but no global loop lease may
        // be retained for that WAIT. The host detaches before resource release.
        game.detach_restore_globals();
        const Result detached=native_scene_control.detach_after_restore(native_scene_context);
        if(detached!=Result::ok){
            if(detached!=Result::waiting){
                job.clock_lost=true;restoration_failure(native_scene_error("native_scene_detach_failed"));
                // Never leave a replacement scene frozen on a failed detach.
                if(clock.active())clock.restore(manager,wall,false);
            }
            return Result::waiting;
        }
        const bool safe=!job.clock_lost&&job.logical_checkpoint_valid&&game.restoration_source_current();
        if(clock.active())job.clock_settings_restored=clock.restore(manager,wall,safe)&&safe;
        if(!job.clock_settings_restored&&job.logical_checkpoint_valid)
            restoration_failure("source_clock_restoration_failed");
        job.scene_detached=!clock.active();
        if(!job.scene_detached)return Result::waiting;
        job.post_wait_started=milliseconds();
    }
    // Arm/poll the independent natural Audio observer immediately. A GPU
    // cleanup WAIT must not keep fresh source callbacks in private-silent mode
    // or consume this entire timeout before the observer is first allowed.
    (void)service_post_restore();
    // Cleanup-only continuation. No rebase, rebuild, held-clock query or old
    // setter is permitted after this point, even over an arbitrary GPU WAIT.
    if(game.restoration_pending()){
        const Result released=job.clock_lost||!job.logical_checkpoint_valid
            ?game.abandon_automatic("native_clock_or_scene_ownership_lost"):game.restore();
        if(released!=Result::ok&&released!=Result::waiting)restoration_failure(game.last_error());
        if(game.restoration_pending())return Result::waiting;
    }
    job.scene_restored=true;
    return Result::ok;
}
inline bool native_capture_request(){
    if(job.capture_requested)return true;
    const Result capture=game.request_capture();
    if(capture==Result::waiting)return false;
    if(capture!=Result::ok){terminal(game.last_error());return false;}
    if(!prepare_frame_output())return false;
    job.capture_requested=true;job.captured=false;job.stage=Stage::frame_wait;
    progress();return true;
}
inline bool native_command_hold(){
    pthread_mutex_lock(&control_mutex);
    const bool cancelled=cancel_pending,paused=requested_pause_reason!=IDMP4_PAUSE_NONE;
    if(paused&&!cancelled){pause_acknowledged=true;reset_watchdog_pending=true;}
    pthread_mutex_unlock(&control_mutex);
    if(cancelled)terminal("cancelled_by_user",true);
    return cancelled||paused;
}
inline bool native_abort_after_clock(void* manager,double wall,const char* error){
    native_scene_control.revoke_grants(native_scene_context);
    terminal(error);
    if(native_engine_clock.active()&&native_engine_clock.hold_for_boundary(manager,wall)){
        const Result held=native_scene_control.hold(native_scene_context);
        if(held!=Result::ok&&held!=Result::waiting)job.clock_lost=true;
    }else job.clock_lost=true;
    return false;
}
inline bool native_render_boundary_impl(void* manager,double wall){
    auto& clock=native_engine_clock;
    // This function owns the sole call to the original clock kernel. None of
    // its callers may retry the original when this function returns false.
    if(!job.automatic||!busy_stage())return native_boundary_clock_tick(manager,wall);
    // Close every prior/future permit before any clock/source check can fail.
    // A partial aggregate commit must not leave a worker or Mono callback
    // authorized just because quiescence later rejects a changed owner.
    native_scene_control.revoke_grants(native_scene_context);
    pthread_mutex_lock(&control_mutex);
    const bool cancelled=cancel_pending;
    const bool paused=requested_pause_reason!=IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&control_mutex);
    if(cancelled)terminal("cancelled_by_user",true);
    if(clock.active()&&!clock.hold_for_boundary(manager,wall)){
        job.clock_lost=true;terminal(clock.error());
    }
    if(job.scene_acquired&&!job.clock_lost&&job.stage!=Stage::retiring){
        if(job.source_generation!=game.owned_scene_generation()||!game.owned_primary_scene_current())
            terminal("selected_scene_changed");
        else {
            const Result hold=native_scene_control.hold(native_scene_context);
            if(hold==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(hold!=Result::ok)terminal(native_scene_error("selected_dependent_hold_failed"));
        }
    }
    if(job.stage==Stage::retiring){
        service_deferred_encoder_cancel();
        restore_owned_scene(manager,wall);
        return native_boundary_clock_tick(manager,wall);
    }
    if(paused){
        pthread_mutex_lock(&control_mutex);
        pause_acknowledged=true;reset_watchdog_pending=true;
        pthread_mutex_unlock(&control_mutex);
        return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage==Stage::scene_acquire){
        if(!clock.active()){
            const Result admission=native_scene_control.admit(native_scene_context);
            last_admission_verified=admission==Result::ok;
            if(admission==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(admission!=Result::ok){terminal(native_scene_error("selected_scene_admission_failed"));return native_boundary_clock_tick(manager,wall);}
            if(!clock.acquire(manager,wall,idoly_mp4_output::simulation_hz(job.options.fps_num))){
                if(!strcmp(clock.error(),"engine_clock_engine_paused"))return native_boundary_clock_tick(manager,wall);
                terminal(clock.error());return native_boundary_clock_tick(manager,wall);
            }
        }
        if(!job.acquired_source_valid){
            if(!game.observe_source(job.acquired_source_time,job.acquired_source_paused))
                return native_boundary_clock_tick(manager,wall);
            job.acquired_source_identity=selected_identity;job.acquired_source_valid=true;
        }
        const Result acquired=game.begin_automatic();
        if(acquired==Result::ok){
            job.scene_acquired=true;job.source_generation=game.owned_scene_generation();
            job.stage=Stage::audio_setup;progress();
        }else if(acquired!=Result::waiting)terminal(game.last_error());
        return native_boundary_clock_tick(manager,wall);
    }
    if(!clock.active()){
        job.clock_lost=true;terminal("native_clock_ownership_lost");
        restore_owned_scene(manager,wall);return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage==Stage::render_setup){
        // Materialize/verify the real capture target before consuming frame0.
        // Its request remains pending until a genuine prewarm draw and
        // ReadPixels return retire it. Discard alone cannot complete the
        // Adapter's readback duty, even though these pixels are not encoded.
        if(!job.capture_requested){
            const Result requested=game.request_capture();
            if(requested==Result::ok){
                if(prepare_frame_output()){
                    job.capture_requested=true;job.captured=false;
                    job.prewarm_completed=false;job.prewarm_requested=true;progress();
                }
            }else if(requested!=Result::waiting)terminal(game.last_error());
            return native_boundary_clock_tick(manager,wall);
        }
        if(!job.prewarm_completed||job.prewarm_inflight||!job.captured)
            return native_boundary_clock_tick(manager,wall);
        size_t count=0;int32_t width=0,height=0;
        const Result readback=game.readback_rgba(job.rgba,job.rgba_capacity,count,width,height);
        if(readback==Result::waiting)return native_boundary_clock_tick(manager,wall);
        if(readback!=Result::ok)terminal(game.last_error());
        else if(count!=job.rgba_capacity||static_cast<uint32_t>(width)!=job.status.width
            ||static_cast<uint32_t>(height)!=job.status.height)terminal("native_prewarm_capture_identity_changed");
        else {job.capture_requested=job.captured=false;job.stage=Stage::frame_request;progress();}
        return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage!=Stage::frame_request&&job.stage!=Stage::frame_wait&&job.stage!=Stage::frame_submit)
        return native_boundary_clock_tick(manager,wall);
    if(!job.auto_started){
        if(!job.prewarm_completed||job.prewarm_inflight||job.prewarm_requested)
            return native_boundary_clock_tick(manager,wall);
        const Result started=game.start_automatic();
        if(started==Result::waiting)return native_boundary_clock_tick(manager,wall);
        if(started!=Result::ok){terminal(game.last_error());return native_boundary_clock_tick(manager,wall);}
        if(!native_scene_control.source_clock_restorable(native_scene_context)
            ||!job.schedule.reset(job.generation,job.options.fps_num,job.total_frames)
            ||!clock.set_owned_loop_quiescent(true)){
            terminal("owned_simulation_not_verified");return native_boundary_clock_tick(manager,wall);
        }
        job.auto_started=true;progress();
    }
    if(job.schedule.next_tick()){
        const double previous=job.schedule.tick_seconds(job.schedule.next_tick()-1);
        if(game.validate_automatic_frame(previous)!=Result::ok){terminal(game.last_error());return native_boundary_clock_tick(manager,wall);}
        const uint64_t tick=job.schedule.next_tick()-1;
        if(!job.have_rendered_tick||job.last_rendered_tick!=tick){
            if(job.schedule.awaiting_frame()&&!job.capture_requested)native_capture_request();
            if(job.stage!=Stage::retiring&&native_simulation_render_generation(tick)){
                const Result ready=native_scene_control.prepare_render(native_scene_context,tick);
                if(ready!=Result::ok&&ready!=Result::waiting)terminal(native_scene_error("selected_render_prepare_failed"));
            }
            return native_boundary_clock_tick(manager,wall);
        }
    }
    if(job.schedule.awaiting_frame()){
        if(!job.capture_requested){
            native_capture_request();return native_boundary_clock_tick(manager,wall);
        }
        if(!job.schedule.pixels_received()){
            if(!job.captured)return native_boundary_clock_tick(manager,wall);
            size_t count=0;int32_t width=0,height=0;
            const Result readback=game.readback_rgba(job.rgba,job.rgba_capacity,count,width,height);
            if(readback==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(readback!=Result::ok){terminal(game.last_error());return native_boundary_clock_tick(manager,wall);}
            if(count!=job.rgba_capacity||static_cast<uint32_t>(width)!=job.status.width
                ||static_cast<uint32_t>(height)!=job.status.height
                ||!job.schedule.readback_received(job.generation,job.frame)){
                terminal("native_capture_identity_changed");return native_boundary_clock_tick(manager,wall);
            }
            job.stage=Stage::frame_submit;progress();
        }
        const int append=job.api.append(job.encoder,job.rgba,static_cast<size_t>(job.status.width)*4,job.frame);
        if(append==IDMP4_RETRY)return native_boundary_clock_tick(manager,wall);
        if(append!=IDMP4_ACCEPTED||!job.schedule.encoder_accepted(job.generation,job.frame)){
            terminal("encoder_frame_rejected");return native_boundary_clock_tick(manager,wall);
        }
        ++job.frame;job.status.frames=job.frame;job.captured=job.capture_requested=false;
        job.stage=Stage::frame_request;progress();
        if(job.schedule.complete()){
            if(job.api.finish(job.encoder)<0)terminal("encoder_finish_rejected");
            else {job.stage=Stage::finishing;phase("finishing");}
            return native_boundary_clock_tick(manager,wall);
        }
    }
    if(native_command_hold())return native_boundary_clock_tick(manager,wall);
    const auto proposal=job.schedule.propose(job.generation);
    if(!proposal.advance)return native_boundary_clock_tick(manager,wall);
    const double seconds=job.schedule.tick_seconds(proposal.tick);
    if(!native_scene_control.source_clock_restorable(native_scene_context)){
        terminal("native_world_ownership_lost");return native_boundary_clock_tick(manager,wall);
    }
    const Result prepared=native_scene_control.prepare_step(native_scene_context,proposal.tick,seconds);
    if(prepared==Result::waiting)return native_boundary_clock_tick(manager,wall);
    if(prepared!=Result::ok){
        terminal(native_scene_error("selected_step_prepare_failed"));return native_boundary_clock_tick(manager,wall);
    }
    if(native_command_hold()){
        native_scene_control.hold(native_scene_context);
        return native_boundary_clock_tick(manager,wall);
    }
    const bool advanced=native_boundary_clock_tick(manager,wall,{true,proposal.tick});
    if(!advanced){
        if(strcmp(clock.error(),"engine_clock_engine_paused")){job.clock_lost=true;terminal(clock.error());}
        else {
            native_scene_control.hold(native_scene_context);
        }
        // No schedule or Actor serial was consumed. The next attempt prepares
        // this same proposal after the native engine can accept it again.
        return false;
    }
    if(!job.schedule.commit(job.generation,proposal)){
        return native_abort_after_clock(manager,wall,"native_simulation_grant_failed");
    }
    if(game.prepare_automatic_frame(seconds)!=Result::ok){
        return native_abort_after_clock(manager,wall,game.last_error());
    }
    if(native_scene_control.grant(native_scene_context,proposal.tick)!=Result::ok){
        return native_abort_after_clock(manager,wall,native_scene_error("native_simulation_grant_failed"));
    }
    if(proposal.frame>=0){
        if(static_cast<uint64_t>(proposal.frame)!=job.frame)return native_abort_after_clock(manager,wall,"native_frame_order_mismatch");
        native_capture_request();
        if(job.stage==Stage::retiring)return native_abort_after_clock(manager,wall,job.status.error);
    }
    if(native_simulation_render_generation(proposal.tick)){
        const Result ready=native_scene_control.prepare_render(native_scene_context,proposal.tick);
        if(ready!=Result::ok&&ready!=Result::waiting)
            return native_abort_after_clock(manager,wall,native_scene_error("selected_render_prepare_failed"));
    }
    publish();return true;
}
inline bool native_render_boundary(void* manager,double wall){
    if(active_boundary_call){terminal("native_clock_reentered");return false;}
    NativeBoundaryCall call{};active_boundary_call=&call;bool result=false;
    try{result=native_render_boundary_impl(manager,wall);}
    catch(...){
        const bool restoring=job.stage==Stage::retiring;
        if(restoring)restoration_failure("original_callback_exception");
        else {job.terminal_success=false;stable_error("original_callback_exception");}
        try{native_scene_control.revoke_grants(native_scene_context);}catch(...){job.clock_lost=true;}
        if(restoring)job.clock_lost=true;
        try{terminal("original_callback_exception");}catch(...){
            job.terminal_success=false;job.stage=Stage::retiring;
            if(restoring)restoration_failure("original_callback_exception");else stable_error("original_callback_exception");
        }
        try{
            if(native_engine_clock.active()){
                if(native_engine_clock.hold_for_boundary(manager,wall)&&job.scene_acquired)
                    native_scene_control.hold(native_scene_context);
            }
        }catch(...){job.clock_lost=true;}
        if(!call.called){try{result=native_boundary_clock_tick(manager,wall);}catch(...){result=false;job.clock_lost=true;}}
    }
    active_boundary_call=nullptr;
    try{refresh_native_observation();}catch(...){
        pthread_mutex_lock(&control_mutex);native_observation.source_valid=false;pthread_mutex_unlock(&control_mutex);
    }
    return result;
}
// END_MP4_NATIVE_BOUNDARY

// BEGIN_MP4_FRESH_NATIVE_BOUNDARY
// Explicit disposable-original-scene protocol. These callbacks owe real
// current writer gates and render completion, not old history restoration.
inline void fresh_stage_wait(const char*timeout){
    const uint64_t now=milliseconds();
    if(!job.fresh_wait_error||strcmp(job.fresh_wait_error,timeout)||!job.fresh_stage_wait_started){job.fresh_wait_error=timeout;job.fresh_stage_wait_started=now;}
    if(now>=job.fresh_stage_wait_started&&now-job.fresh_stage_wait_started>15000)terminal(timeout);
}
inline void fresh_stage_ready(const char*timeout){
    if(job.fresh_wait_error&&!strcmp(job.fresh_wait_error,timeout)){job.fresh_wait_error=nullptr;job.fresh_stage_wait_started=0;}
}
inline bool native_fresh_render_boundary_impl(void*manager,double wall){
    auto&clock=native_engine_clock;auto&api=fresh_scene_api;
    if(!job.fresh||!busy_stage())return native_boundary_clock_tick(manager,wall);
    job.fresh_render_ready=false;
    api.withdraw(api.context);
    pthread_mutex_lock(&control_mutex);
    const bool cancelled=cancel_pending,paused=requested_pause_reason!=IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&control_mutex);
    if(cancelled)terminal("cancelled_by_user",true);
    if(clock.active()&&!clock.hold_for_boundary(manager,wall)){
        job.clock_lost=true;terminal(clock.error());
    }
    if(job.scene_acquired&&!job.clock_lost&&job.stage!=Stage::retiring){
        if(!api.current(api.context)||job.source_generation!=game.owned_scene_generation()
            ||!game.owned_primary_scene_current())terminal("fresh_scene_changed");
        else{
            const Result held=api.hold(api.context);
            if(held==Result::waiting){fresh_stage_wait("fresh_source_hold_timeout");return native_boundary_clock_tick(manager,wall);}
            fresh_stage_ready("fresh_source_hold_timeout");
            if(held!=Result::ok)terminal(fresh_scene_error("fresh_hold_failed"));
        }
    }
    if(job.stage==Stage::retiring){
        service_deferred_encoder_cancel();
        if(!job.scene_detached){
            // Complete the actual fresh writers before disposing their graph.
            // A replaced scene never authorizes a stale property write.
            if(job.scene_acquired&&!job.clock_lost&&api.current(api.context)){
                const Result held=api.hold(api.context);
                if(held==Result::waiting)return native_boundary_clock_tick(manager,wall);
                if(held!=Result::ok){job.clock_lost=true;restoration_failure(fresh_scene_error("fresh_hold_failed"));}
            }
            if(!job.fresh_pre_finish_settled){
                const Result prepared=api.prepare_finish(api.context);
                if(prepared==Result::waiting)return native_boundary_clock_tick(manager,wall);
                job.fresh_pre_finish_settled=true;
                if(prepared!=Result::ok)restoration_failure(fresh_scene_error("fresh_decoder_cleanup_failed"));
            }
            const Result released=game.end_fresh();
            if(released==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(released!=Result::ok)restoration_failure(game.last_error());
            // Keep virtual absolute time coherent, restore only owned global
            // clock controls, and never copy a former scene's native history.
            job.clock_settings_restored=!clock.active()||clock.restore(manager,wall,false);
            if(!job.clock_settings_restored)restoration_failure("fresh_clock_release_failed");
            job.scene_detached=!clock.active();
            if(!job.scene_detached)return native_boundary_clock_tick(manager,wall);
        }
        // finish detaches shader/render globals before original End, then
        // awaits a real reload of logical selection/time/pause. An independent
        // Listener mute lease may span that reload and ends on every terminal
        // result. Natural clock ticks permit the original async loader.
        if(!job.fresh_finish_settled){
            const Result finished=api.finish(api.context);
            if(finished==Result::waiting)return native_boundary_clock_tick(manager,wall);
            job.fresh_finish_settled=true;job.scene_restored=finished==Result::ok;
            if(!job.scene_restored)restoration_failure(fresh_scene_error("fresh_logical_restore_failed"));
            progress();
        }
        return native_boundary_clock_tick(manager,wall);
    }
    if(paused){
        job.fresh_wait_error=nullptr;job.fresh_stage_wait_started=0;
        pthread_mutex_lock(&control_mutex);pause_acknowledged=true;reset_watchdog_pending=true;pthread_mutex_unlock(&control_mutex);
        return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage==Stage::scene_acquire){
        if(!clock.active()){
            const Result admitted=api.admit(api.context);
            if(admitted==Result::waiting){fresh_stage_wait("fresh_scene_admission_timeout");return native_boundary_clock_tick(manager,wall);}
            fresh_stage_ready("fresh_scene_admission_timeout");
            if(admitted!=Result::ok){terminal(fresh_scene_error("fresh_factory_not_verified"));return native_boundary_clock_tick(manager,wall);}
            if(!clock.acquire(manager,wall,idoly_mp4_output::simulation_hz(job.options.fps_num))){
                if(strcmp(clock.error(),"engine_clock_engine_paused"))terminal(clock.error());else fresh_stage_wait("fresh_native_clock_acquire_timeout");
                return native_boundary_clock_tick(manager,wall);
            }
            fresh_stage_ready("fresh_native_clock_acquire_timeout");
            diagnostic_event("fresh_clock","acquired");
        }
        const Result begun=game.begin_fresh();
        if(begun!=Result::ok){if(begun!=Result::waiting)terminal(game.last_error());else fresh_stage_wait("fresh_scene_source_timeout");return native_boundary_clock_tick(manager,wall);}
        fresh_stage_ready("fresh_scene_source_timeout");
        idoly_mp4_game::SceneWitness witness{};
        if(!game.selected_scene_witness(witness)){terminal("fresh_scene_witness_missing");return native_boundary_clock_tick(manager,wall);}
        const Result acquired=api.acquire(api.context,witness,job.generation);
        if(acquired==Result::ok){
            fresh_stage_ready("fresh_scene_acquire_timeout");
            job.scene_acquired=true;job.source_generation=game.owned_scene_generation();
            job.stage=Stage::audio_setup;progress();
        }else if(acquired!=Result::waiting)terminal(fresh_scene_error("fresh_acquire_failed"));
        else fresh_stage_wait("fresh_scene_acquire_timeout");
        return native_boundary_clock_tick(manager,wall);
    }
    if(!clock.active()){
        job.clock_lost=true;terminal("fresh_clock_ownership_lost");return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage==Stage::render_setup){
        if(!job.fresh_started){
            const Result started=api.start(api.context);
            if(started==Result::waiting){fresh_stage_wait("fresh_scene_start_timeout");return native_boundary_clock_tick(manager,wall);}
            fresh_stage_ready("fresh_scene_start_timeout");
            if(started!=Result::ok){terminal(fresh_scene_error("fresh_start_failed"));return native_boundary_clock_tick(manager,wall);}
            const Result adopted=game.start_fresh();
            if(adopted!=Result::ok){if(adopted!=Result::waiting)terminal(game.last_error());else fresh_stage_wait("fresh_scene_graph_adoption_timeout");return native_boundary_clock_tick(manager,wall);}
            fresh_stage_ready("fresh_scene_graph_adoption_timeout");
            job.fresh_started=true;
        }
        if(!job.capture_requested){
            const Result requested=game.request_capture();
            if(requested==Result::ok){diagnostic_event("fresh_capture","first_request_returned");if(prepare_frame_output()){
                job.capture_requested=true;job.captured=false;job.prewarm_completed=false;job.prewarm_requested=true;progress();}}
            else if(requested!=Result::waiting)terminal(game.last_error());
            return native_boundary_clock_tick(manager,wall);
        }
        if(!job.prewarm_completed){
            const Result ready=api.prepare_render(api.context,0);
            if(ready==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(ready!=Result::ok){terminal(fresh_scene_error("fresh_prewarm_prepare_failed"));return native_boundary_clock_tick(manager,wall);}
            job.fresh_render_tick=0;job.fresh_render_ready=true;
        }
        if(!job.prewarm_completed||job.prewarm_inflight||!job.captured)return native_boundary_clock_tick(manager,wall);
        size_t count=0;int32_t width=0,height=0;
        const Result read=game.readback_rgba(job.rgba,job.rgba_capacity,count,width,height);
        if(read==Result::waiting)return native_boundary_clock_tick(manager,wall);
        if(read!=Result::ok)terminal(game.last_error());
        else if(count!=job.rgba_capacity||uint32_t(width)!=job.status.width||uint32_t(height)!=job.status.height)
            terminal("fresh_prewarm_capture_identity_changed");
        else{job.capture_requested=job.captured=false;job.stage=Stage::frame_request;progress();}
        return native_boundary_clock_tick(manager,wall);
    }
    if(job.stage!=Stage::frame_request&&job.stage!=Stage::frame_wait&&job.stage!=Stage::frame_submit)
        return native_boundary_clock_tick(manager,wall);
    if(!job.auto_started){
        if(!job.prewarm_completed||!job.fresh_started||!api.current(api.context)
            ||!job.schedule.reset(job.generation,job.options.fps_num,job.total_frames)
            ||!clock.set_owned_loop_quiescent(true)){
            terminal("fresh_writer_gates_not_current");return native_boundary_clock_tick(manager,wall);
        }
        job.auto_started=true;progress();
    }
    if(job.schedule.next_tick()){
        const uint64_t previous_tick=job.schedule.next_tick()-1;
        if(game.validate_automatic_frame(job.schedule.tick_seconds(previous_tick))!=Result::ok){
            terminal(game.last_error());return native_boundary_clock_tick(manager,wall);}
        if(!job.have_rendered_tick||job.last_rendered_tick!=previous_tick){
            if(job.schedule.awaiting_frame()&&!job.capture_requested)native_capture_request();
            if(job.stage!=Stage::retiring){
                const Result ready=api.prepare_render(api.context,previous_tick);
                if(ready==Result::ok){job.fresh_render_tick=previous_tick;job.fresh_render_ready=true;}
                else if(ready!=Result::waiting)terminal(fresh_scene_error("fresh_render_prepare_failed"));}
            return native_boundary_clock_tick(manager,wall);
        }
    }
    if(job.schedule.awaiting_frame()){
        if(!job.capture_requested){native_capture_request();return native_boundary_clock_tick(manager,wall);}
        if(!job.schedule.pixels_received()){
            if(!job.captured)return native_boundary_clock_tick(manager,wall);
            size_t count=0;int32_t width=0,height=0;
            const Result read=game.readback_rgba(job.rgba,job.rgba_capacity,count,width,height);
            if(read==Result::waiting)return native_boundary_clock_tick(manager,wall);
            if(read!=Result::ok){terminal(game.last_error());return native_boundary_clock_tick(manager,wall);}
            if(count!=job.rgba_capacity||uint32_t(width)!=job.status.width||uint32_t(height)!=job.status.height
                ||!job.schedule.readback_received(job.generation,job.frame)){
                terminal("fresh_capture_identity_changed");return native_boundary_clock_tick(manager,wall);}
            job.stage=Stage::frame_submit;progress();
        }
        const int appended=job.api.append(job.encoder,job.rgba,size_t(job.status.width)*4,job.frame);
        if(appended==IDMP4_RETRY)return native_boundary_clock_tick(manager,wall);
        if(appended!=IDMP4_ACCEPTED||!job.schedule.encoder_accepted(job.generation,job.frame)){
            terminal("encoder_frame_rejected");return native_boundary_clock_tick(manager,wall);}
        ++job.frame;job.status.frames=job.frame;job.capture_requested=job.captured=false;
        job.stage=Stage::frame_request;progress();
        if(job.schedule.complete()){
            if(job.api.finish(job.encoder)<0)terminal("encoder_finish_rejected");
            else{job.stage=Stage::finishing;phase("finishing");}
            return native_boundary_clock_tick(manager,wall);
        }
    }
    if(native_command_hold())return native_boundary_clock_tick(manager,wall);
    const auto proposal=job.schedule.propose(job.generation);
    if(!proposal.advance)return native_boundary_clock_tick(manager,wall);
    const double seconds=job.schedule.tick_seconds(proposal.tick);
    const Result prepared=api.prepare_step(api.context,proposal.tick,seconds);
    if(prepared==Result::waiting)return native_boundary_clock_tick(manager,wall);
    if(prepared!=Result::ok){terminal(fresh_scene_error("fresh_step_prepare_failed"));return native_boundary_clock_tick(manager,wall);}
    if(native_command_hold()){api.withdraw(api.context);return native_boundary_clock_tick(manager,wall);}
    const bool advanced=native_boundary_clock_tick(manager,wall,{true,proposal.tick});
    if(!advanced){
        api.withdraw(api.context);
        if(strcmp(clock.error(),"engine_clock_engine_paused")){job.clock_lost=true;terminal(clock.error());}
        return false;
    }
    if(!job.schedule.commit(job.generation,proposal)||game.prepare_automatic_frame(seconds)!=Result::ok){
        api.withdraw(api.context);terminal("fresh_simulation_grant_failed");return false;}
    if(api.grant(api.context,proposal.tick)!=Result::ok){api.withdraw(api.context);terminal(fresh_scene_error("fresh_simulation_grant_failed"));return false;}
    if(proposal.frame>=0){
        if(uint64_t(proposal.frame)!=job.frame){api.withdraw(api.context);terminal("native_frame_order_mismatch");return false;}
        native_capture_request();
    }
    if(job.stage!=Stage::retiring){
        const Result ready=api.prepare_render(api.context,proposal.tick);
        if(ready==Result::ok){job.fresh_render_tick=proposal.tick;job.fresh_render_ready=true;}
        else if(ready!=Result::waiting){api.withdraw(api.context);terminal(fresh_scene_error("fresh_render_prepare_failed"));return false;}}
    publish();return true;
}
inline bool native_fresh_render_boundary(void*manager,double wall){
    if(active_boundary_call){terminal("native_clock_reentered");return false;}
    NativeBoundaryCall call{};active_boundary_call=&call;bool result=false;
    struct BoundaryExit{~BoundaryExit(){active_boundary_call=nullptr;}}exit;
    try{result=native_fresh_render_boundary_impl(manager,wall);}
    catch(...){
        try{fresh_scene_api.withdraw(fresh_scene_api.context);}catch(...){}
        try{if(job.stage==Stage::retiring)restoration_failure("fresh_original_callback_exception");
            else terminal("fresh_original_callback_exception");}
        catch(...){job.terminal_success=false;job.stage=Stage::retiring;}
        if(!call.called)try{result=native_boundary_clock_tick(manager,wall);}catch(...){job.clock_lost=true;}
    }
    try{refresh_native_observation();}catch(...){}
    return result;
}
// END_MP4_FRESH_NATIVE_BOUNDARY

inline void on_unity_tick_impl() {
    if(!installed)return;
    static bool running=false;
    if(running)return;
    struct TickGuard{bool& value;explicit TickGuard(bool& v):value(v){value=true;}~TickGuard(){value=false;}} tick_guard(running);
    struct ObserveExit {~ObserveExit(){try{refresh_native_observation();}catch(...){pthread_mutex_lock(&control_mutex);native_observation.source_valid=false;pthread_mutex_unlock(&control_mutex);}}} observe_exit;
    queue_tick();
    pthread_mutex_lock(&control_mutex);
    increment_counter(unity_ticks);
    const bool should_cancel=cancel_pending;
    if(should_cancel&&start_pending&&!busy_stage()&&!fresh_scene_installed.load(std::memory_order_acquire)){
        // A parked start has acquired no Unity or encoder state yet.
        start_pending=false;control_busy=false;cancel_pending=false;pause_acknowledged=false;
        job.status=PublicStatus{};
        if(pending_queue_output[0])snprintf(job.status.id,sizeof(job.status.id),"%s",pending_queue_output);
        pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;
        snprintf(job.status.phase,sizeof(job.status.phase),"cancelled");
        snprintf(job.status.error,sizeof(job.status.error),"cancelled_by_user");
        const bool ready=published.ready;published=job.status;published.ready=ready;
        pthread_mutex_unlock(&control_mutex);return;
    }
    const bool can_park=start_pending||(busy_stage()&&job.stage!=Stage::finishing&&job.stage!=Stage::retiring);
    if(requested_pause_reason!=IDMP4_PAUSE_NONE&&!should_cancel&&can_park){
        if(!job.automatic)pause_acknowledged=true;
        reset_watchdog_pending=true;
        pthread_mutex_unlock(&control_mutex);return;
    }
    const bool reset_watchdog=reset_watchdog_pending;
    reset_watchdog_pending=false;pause_acknowledged=false;
    pthread_mutex_unlock(&control_mutex);
    if(reset_watchdog&&busy_stage())progress();
    game.maintenance();
    if(!busy_stage()){
        // Immediate Start follows the same original forced-load protocol as
        // Queue Run. Host threads only accepted the command above.
        if(start_pending&&fresh_scene_installed.load(std::memory_order_acquire)){
            const Result prepared=fresh_prepare_start();
            if(prepared==Result::waiting)return;
            if(prepared!=Result::ok){
                char output[33]{};const char*error=fresh_start_error();
                pthread_mutex_lock(&control_mutex);
                start_pending=control_busy=false;
                const bool cancelled=cancel_pending;cancel_pending=false;
                snprintf(output,sizeof(output),"%s",pending_queue_output);
                pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;
                pthread_mutex_unlock(&control_mutex);
                publish_prestart_failure(cancelled?"cancelled_by_user":error,output,cancelled);
                snprintf(job.status.restoration_error,sizeof(job.status.restoration_error),"%s",fresh_start_restore_error());publish();return;
            }
        }
        pthread_mutex_lock(&control_mutex);const bool force_admission=start_pending;pthread_mutex_unlock(&control_mutex);
        Result selected=probe_selection_source();
        // A missing camera fallback may be populated by the ordinary source
        // snapshot. Admission failure must never erase a positive selection.
        queue_refresh_candidate(selected);
        Snapshot ready{};const Result readiness=probe_readiness(ready,force_admission);
        if(selected!=Result::ok&&readiness==Result::ok){selected=probe_selection_source();queue_refresh_candidate(selected);}
        pthread_mutex_lock(&control_mutex);const bool pending=start_pending;pthread_mutex_unlock(&control_mutex);
        if(pending&&readiness==Result::waiting){
            const uint64_t now=milliseconds();
            if(reset_watchdog||!start_wait_started)start_wait_started=now;
            // A resumed Android player can need several original render ticks
            // to rebuild its target. Starting must not fail in that interval.
            if(now>=start_wait_started&&now-start_wait_started<=15000)return;
        }else start_wait_started=0;
        begin_job();if(!busy_stage())return;
    }
    // Read once more after begin_job: a host command may arrive while its
    // bounded original Unity setup runs. Never interrupt an original method.
    pthread_mutex_lock(&control_mutex);const bool cancel_after_begin=cancel_pending;pthread_mutex_unlock(&control_mutex);
    if(cancel_after_begin)terminal("cancelled_by_user",true);
    if(job.stage==Stage::frame_wait&&!job.captured&&job.activity&&milliseconds()-job.activity>5000)
        terminal("selected_camera_capture_timeout");
    if(job.stage!=Stage::retiring&&job.activity&&milliseconds()-job.activity>120000)terminal("export_progress_timeout");
    if(job.stage!=Stage::retiring&&!active_broker())terminal("audio_broker_retired");
    encoder_poll();
    switch(job.stage){
        case Stage::audio_setup:setup_audio_job();break;
        case Stage::audio_request:request_audio();break;
        case Stage::audio_response:poll_audio_response();break;
        case Stage::audio_load:{Result r=game.poll_private_audio();if(r==Result::ok){job.stage=Stage::audio_mix;progress();}else if(r!=Result::waiting)terminal(game.last_error());break;}
        case Stage::audio_mix:{uint64_t began=milliseconds();for(unsigned chunk=0;chunk<4&&job.stage==Stage::audio_mix;++chunk){mix_audio();if(milliseconds()-began>=8)break;}break;}
        case Stage::audio_finalize:{uint64_t began=milliseconds();for(unsigned chunk=0;chunk<4&&job.stage==Stage::audio_finalize;++chunk){finalize_audio();if(milliseconds()-began>=8)break;}break;}
        case Stage::frame_request:if(!job.automatic)request_frame();break;
        case Stage::frame_wait:if(!job.automatic&&job.captured){size_t count=0;int32_t w=0,h=0;Result r=game.readback_rgba(job.rgba,job.rgba_capacity,count,w,h);if(r==Result::ok){
            if(static_cast<uint32_t>(w)!=job.status.source_width||static_cast<uint32_t>(h)!=job.status.source_height||count!=job.rgba_capacity){terminal("capture_geometry_changed");break;}
            job.stage=Stage::frame_submit;progress();}else if(r!=Result::waiting)terminal(game.last_error());}break;
        case Stage::frame_submit:{if(job.automatic)break;int r=job.api.append(job.encoder,job.rgba,static_cast<size_t>(job.status.width)*4,job.frame);if(r==IDMP4_ACCEPTED){++job.frame;job.status.frames=job.frame;job.stage=Stage::frame_request;progress();}else if(r!=IDMP4_RETRY)terminal("encoder_frame_rejected");break;}
        case Stage::finishing:break;
        case Stage::retiring:retire();break;
        default:break;
    }
    publish();
}
inline void on_unity_tick(){
    try{on_unity_tick_impl();}
    catch(...){export_observer_failed();publish();}
}
inline size_t status(char*buffer,size_t capacity){
    if(!buffer||!capacity)return 0;
    pthread_mutex_lock(&control_mutex);
    const PublicStatus s=published;char readiness[96]{},selection_reason[96]{};
    snprintf(readiness,sizeof(readiness),"%s",readiness_error);
    snprintf(selection_reason,sizeof(selection_reason),"%s",selection_error);const bool selected=selected_mv;
    const ControllerDiscovery discovery=controller_discovery;
    const NativeObservation observed=native_observation;
    const NativeSceneDiagnostics diagnostics=native_diagnostics;
    const uint64_t ticks=unity_ticks,acks=capture_acks;
    const bool requested=control_busy&&s.pausable&&requested_pause_reason!=IDMP4_PAUSE_NONE,paused=requested&&pause_acknowledged;
    const int reason=requested?requested_pause_reason:IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&control_mutex);
    const char* current_phase=requested?(paused?"paused":"pausing"):s.phase;
    char observation[2048]{},diagnostic_json[768]{},tick[32]="null";
    const int diagnostic_count=snprintf(diagnostic_json,sizeof(diagnostic_json),
        "{\"schema\":1,\"available\":%s,\"source_identity\":\"%016llx\",\"playerloop_frame\":%llu,"
        "\"actor\":{\"result\":%d,\"error\":\"%s\"},\"camera\":{\"result\":%d,\"error\":\"%s\"},"
        "\"stage\":{\"result\":%d,\"error\":\"%s\"},\"world\":{\"result\":%d,\"error\":\"%s\"}}",
        diagnostics.available?"true":"false",static_cast<unsigned long long>(diagnostics.identity),static_cast<unsigned long long>(diagnostics.loop),
        diagnostics.parts[0].result,diagnostics.parts[0].error,diagnostics.parts[1].result,diagnostics.parts[1].error,
        diagnostics.parts[2].result,diagnostics.parts[2].error,diagnostics.parts[3].result,diagnostics.parts[3].error);
    if(diagnostic_count<=0||static_cast<size_t>(diagnostic_count)>=sizeof(diagnostic_json))return 0;
    if(observed.has_tick)snprintf(tick,sizeof(tick),"%llu",static_cast<unsigned long long>(observed.tick));
    const int observed_count=snprintf(observation,sizeof(observation),
        "{\"schema\":1,\"pipeline\":\"owned_native_clock\",\"source_valid\":%s,\"playerloop_frame\":%llu,"
        "\"source_kind\":\"%s\",\"source_identity\":\"%016llx\",\"source_time\":%.17g,\"source_paused\":%s,"
        "\"acquired_source_valid\":%s,\"acquired_source_identity\":\"%016llx\",\"acquired_source_time\":%.17g,\"acquired_source_paused\":%s,"
        "\"render_width\":%u,\"render_height\":%u,"
        "\"rendered_simulation_ticks\":%llu,"
        "\"restored_source_valid\":%s,\"restored_source_identity\":\"%016llx\",\"restored_source_time\":%.17g,\"restored_source_paused\":%s,"
        "\"sample_phase\":\"%s\",\"coordinator_active\":%s,\"native_clock_owned\":%s,\"native_clock_held\":%s,\"simulation_tick\":%s,"
        "\"accepted_frames\":%llu,\"source_restored\":%s,\"clock_settings_restored\":%s,"
        "\"camera_audio_restored\":%s,\"dependent_state_restored\":%s,\"world_admission\":\"%s\"}",
        observed.source_valid?"true":"false",static_cast<unsigned long long>(observed.loop),
        observed.source_valid&&observed.photography?"photography_3d":"unavailable",static_cast<unsigned long long>(observed.identity),
        observed.source_time,observed.source_paused?"true":"false",
        observed.acquired_valid?"true":"false",static_cast<unsigned long long>(observed.acquired_identity),observed.acquired_time,observed.acquired_paused?"true":"false",
        observed.render_width,observed.render_height,
        static_cast<unsigned long long>(observed.rendered_ticks),
        observed.restored_valid?"true":"false",static_cast<unsigned long long>(observed.restored_identity),observed.restored_time,observed.restored_paused?"true":"false",
        observed.rendered?"rendered":"control",observed.active?"true":"false",
        observed.clock_owned?"true":"false",observed.clock_held?"true":"false",tick,
        static_cast<unsigned long long>(observed.accepted),observed.restored?"true":"false",observed.clock_restored?"true":"false",
        observed.camera_audio?"true":"false",observed.dependents?"true":"false",observed.world?"verified":"unverified");
    if(observed_count<=0||static_cast<size_t>(observed_count)>=sizeof(observation))return 0;
    int n=snprintf(buffer,capacity,"{\"schema\":1,\"pipeline_mode\":\"%s\",\"unity_ticks\":%llu,\"capture_acks\":%llu,\"ready\":%s,\"readiness_error\":\"%s\",\"selected_mv\":%s,\"selection_error\":\"%s\",\"phase\":\"%s\",\"paused\":%s,\"pause_requested\":%s,\"pause_reason\":\"%s\",\"resume_phase\":\"%s\",\"export_id\":\"%s\",\"error_code\":\"%s\",\"restoration_error\":\"%s\",\"frames\":%llu,\"total_frames\":%llu,\"audio_frames\":%llu,\"total_audio_frames\":%llu,\"width\":%u,\"height\":%u,\"source_width\":%u,\"source_height\":%u,\"video_codec\":%u,\"video_bitrate\":%u,\"fps_num\":%u,\"fps_den\":%u,\"bytes_written\":%llu,\"controller_discovery\":{\"reason\":\"%s\",\"source\":\"%s\",\"listed_directors\":%u,\"unique_directors\":%u,\"assets\":%u,\"output_tracks\":%u,\"camera_tracks\":%u,\"null_assets\":%u,\"candidate_controllers\":%u},\"observation\":%s,\"scene_diagnostics\":%s}",
        fresh_scene_installed.load(std::memory_order_acquire)?"fresh_original_scene":"legacy_owned_scene",static_cast<unsigned long long>(ticks),static_cast<unsigned long long>(acks),s.ready?"true":"false",readiness,selected?"true":"false",selection_reason,current_phase,
        paused?"true":"false",requested?"true":"false",pause_reason_name(reason),requested?s.phase:"none",s.id,s.error,s.restoration_error,
        static_cast<unsigned long long>(s.frames),static_cast<unsigned long long>(s.total_frames),
        static_cast<unsigned long long>(s.audio),static_cast<unsigned long long>(s.total_audio),s.width,s.height,s.source_width,s.source_height,
        s.video_codec,s.video_bitrate,s.fps_num,s.fps_den,static_cast<unsigned long long>(s.bytes),
        discovery.reason,discovery.source,discovery.counts.listed_directors,discovery.counts.unique_directors,
        discovery.counts.assets,discovery.counts.output_tracks,discovery.counts.camera_tracks,discovery.counts.null_assets,discovery.candidates,observation,diagnostic_json);
    return n>0&&static_cast<size_t>(n)<capacity?static_cast<size_t>(n):0;
}
} // namespace idoly_mp4_runtime

#include "mp4_queue_runtime.hpp"

extern "C" IDMP4_SESSION_API int IDMP4SessionConfigure(const char*b,uint64_t e,const char*c,const char*o,int p){return idoly_mp4_runtime::configure(b,e,c,o,p)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4SessionStart(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a){return idoly_mp4_runtime::start({n,d,c,v,a})?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4SessionStartV2(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a,uint32_t w,uint32_t h){return idoly_mp4_runtime::start({n,d,c,v,a,w,h})?0:-1;}
extern "C" IDMP4_SESSION_API size_t IDMP4SessionStatus(char*b,size_t c){return idoly_mp4_runtime::status(b,c);}
extern "C" IDMP4_SESSION_API size_t IDMP4SessionDiagnostics(char*b,size_t c){return idoly_mp4_runtime::diagnostics(b,c);}
extern "C" IDMP4_SESSION_API void IDMP4SessionCancel(){idoly_mp4_runtime::cancel();}
extern "C" IDMP4_SESSION_API void IDMP4SessionSuspend(int reason){idoly_mp4_runtime::suspend(reason);}
extern "C" IDMP4_SESSION_API void IDMP4SessionResume(){idoly_mp4_runtime::resume();}
extern "C" IDMP4_SESSION_API int IDMP4SessionReady(){pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);bool ready=idoly_mp4_runtime::published.ready;pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);return ready?1:0;}
extern "C" IDMP4_SESSION_API int IDMP4SessionSelectionReady(){pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);const bool selected=idoly_mp4_runtime::selected_mv;pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);return selected?1:0;}
