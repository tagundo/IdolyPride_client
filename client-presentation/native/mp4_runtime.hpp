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
#include "mp4_selection_capture.hpp"
#include "mp4_game_profile.hpp"
#include "mp4_output_policy.hpp"

namespace idoly_mp4_runtime {
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
inline bool transfer_at(int fd,void* bytes,size_t count,int64_t offset,bool writing){size_t at=0;while(at<count){long n=writing?pwrite(fd,static_cast<uint8_t*>(bytes)+at,count-at,offset+static_cast<int64_t>(at)):pread(fd,static_cast<uint8_t*>(bytes)+at,count-at,offset+static_cast<int64_t>(at));if(n<=0)return false;at+=static_cast<size_t>(n);}return true;}

struct Configuration {
    char broker[path_capacity]{},output[path_capacity]{};
    uint64_t epoch=0;uint8_t capability[16]{};int platform=0;
    int root=-1,req=-1,rsp=-1,prepared=-1,exports=-1;
};
inline void close_configuration(Configuration& c){for(int*fd:{&c.root,&c.req,&c.rsp,&c.prepared,&c.exports})if(*fd>=0){close(*fd);*fd=-1;}}
struct Options{uint32_t fps_num=30,fps_den=1,codec=1,bitrate=16000000,audio_bitrate=192000,output_width=0,output_height=0;};
struct PublicStatus {
    char phase[24]="idle",id[33]{},error[192]="none";
    uint64_t frames=0,total_frames=0,audio=0,total_audio=0,bytes=0;
    uint32_t width=0,height=0,fps_num=30,fps_den=1,source_width=0,source_height=0,video_codec=1,video_bitrate=0;
    bool ready=false,pausable=false;
};
static pthread_mutex_t control_mutex=PTHREAD_MUTEX_INITIALIZER;
static Configuration configured;
static Options pending_options;
static PublicStatus published;
static char readiness_error[96]="open_selected_mv_first";
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
static uint64_t selected_identity=0;
inline void queue_tick();
static bool installed=false;
enum class Stage{idle,begin,audio_request,audio_response,audio_load,audio_mix,audio_finalize,frame_request,frame_wait,frame_submit,finishing,retiring};
struct Job {
    Configuration config{};Options options{};Snapshot snapshot{};PublicStatus status{};
    Stage stage=Stage::idle;EncoderApi api{};IDMP4EncoderHandle encoder=nullptr;
    char pcm_path[path_capacity]{},partial_path[path_capacity]{},final_path[path_capacity]{},pcm_name[48]{};
    char request_hex[33]{},request_name[48]{},response_name[48]{},bundle_name[48]{},bundle_path[path_capacity]{};
    uint8_t request_id[16]{};size_t clip=0;
    uint64_t total_audio=0,total_frames=0,frame=0,mixed=0,start_sample=0,source_offset=0,clip_frames=0;
    uint32_t rate=0;int pcm=-1;uint8_t*rgba=nullptr,*output_rgba=nullptr;size_t rgba_capacity=0,output_capacity=0;
    float source[8192*2]{},mixed_pcm[8192*2]{};
    uint64_t activity=0,last_encoder_progress=0;
    struct stat pcm_identity{},bundle_identity{};
    uint64_t finalized_audio=0;
    uint32_t expected_width=0,expected_height=0;
    bool pcm_owned=false,bundle_owned=false,pending_broker=false,audible_energy=false,captured=false,terminal_success=false,terminal_cancel=false;
};
static Job job;
inline bool busy_stage(){return job.stage!=Stage::idle;}
inline void publish(){pthread_mutex_lock(&control_mutex);const bool ready=published.ready;published=job.status;published.ready=ready;published.pausable=job.stage!=Stage::idle&&job.stage!=Stage::finishing&&job.stage!=Stage::retiring;pthread_mutex_unlock(&control_mutex);}
inline void progress(){job.activity=milliseconds();}
inline void phase(const char* value){snprintf(job.status.phase,sizeof(job.status.phase),"%s",value);progress();publish();}
inline void stable_error(const char* value){size_t at=0;for(;value&&value[at]&&at<sizeof(job.status.error)-1;++at){char c=value[at];job.status.error[at]=((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_')?c:'_';}job.status.error[at]=0;if(!at)snprintf(job.status.error,sizeof(job.status.error),"export_failed");}
inline bool active_broker() {
    int fd=openat(job.config.root,"active",rd|nofollow|nonblock);uint8_t raw[16]{};
    const bool good=private_file(fd,16)&&exact_read(fd,raw,sizeof(raw))&&!memcmp(raw,"IDMPACT1",8)&&get64(raw+8)==job.config.epoch;
    if(fd>=0)close(fd);
    return good;
}
inline bool cleanup_bundle(){if(!game.private_audio_quiescent())return false;if(job.bundle_owned){unlink_owned(job.config.prepared,job.bundle_name,job.bundle_identity);job.bundle_owned=false;}return true;}
inline void terminal(const char* error,bool cancelled=false) {
    if(job.stage==Stage::idle||job.stage==Stage::retiring)return;
    job.terminal_success=false;job.terminal_cancel=cancelled;stable_error(error);
    game.restore();if(job.encoder)job.api.cancel(job.encoder);
    job.stage=Stage::retiring;phase(cancelled?"cancelling":"failed");
}
inline bool valid_options(const Options& o){return o.fps_den==1&&(o.fps_num==30||o.fps_num==60)&&(o.codec==1||o.codec==2)&&idoly_mp4_output::bitrate(o.bitrate)&&o.audio_bitrate==192000&&idoly_mp4_output::requested_dimensions(o.output_width,o.output_height);}
inline Result probe_readiness(Snapshot& snapshot){
    Result result=game.snapshot(snapshot);const char* error=result==Result::ok?"none":game.last_error();
    int32_t width=0,height=0;
    if(result==Result::ok&&game.has_source_geometry_probe()){
        result=game.source_geometry(width,height);
        if(result!=Result::ok)error=result==Result::waiting?"selected_capture_geometry_not_ready":"selected_capture_geometry_unsupported";
    }
    if(result==Result::ok&&!game.has_source_geometry_probe())game.source_geometry(width,height);
    pthread_mutex_lock(&control_mutex);published.ready=result==Result::ok;
    // This is an observed original render texture, never a Screen estimate.
    published.source_width=result==Result::ok&&idoly_mp4_output::source_dimensions(width,height)?static_cast<uint32_t>(width):0;
    published.source_height=published.source_width?static_cast<uint32_t>(height):0;
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
    close_configuration(configured);configured=next;configured_valid=true;pthread_mutex_unlock(&control_mutex);return true;
}
inline bool start(Options options,bool queued=false){pthread_mutex_lock(&control_mutex);bool ok=configured_valid&&!control_busy&&!start_pending&&(queued||!queue_scene_owned)&&published.ready&&valid_options(options);if(ok){if(!queued){pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;pending_queue_width=pending_queue_height=0;}pending_options=options;start_pending=true;start_wait_started=0;cancel_pending=false;control_busy=true;published.pausable=true;pause_acknowledged=false;snprintf(published.phase,sizeof(published.phase),"preparing_audio");snprintf(published.error,sizeof(published.error),"none");}pthread_mutex_unlock(&control_mutex);return ok;}
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
inline void observe_presenter(void* presenter){if(installed){game.observe_presenter(presenter);pthread_mutex_lock(&control_mutex);selected_identity=selection.identity(game.selected_player());pthread_mutex_unlock(&control_mutex);}}
inline void observe_player_initializing(void* player,void* param){if(installed)selection.observe(player,param);}
inline void observe_camera_controller(void* camera){if(installed)game.observe_camera_controller(camera);}
inline void capture_pass_did_execute(void* pass,const void*data){if(installed)game.observe_capture_pass(pass,data);}
inline void camera_did_render(void*camera){if(installed&&job.stage==Stage::frame_wait&&!job.captured&&game.after_camera(camera)){job.captured=true;pthread_mutex_lock(&control_mutex);increment_counter(capture_acks);pthread_mutex_unlock(&control_mutex);}}
inline bool camera_delta_override(void*brain,float*delta){return installed&&game.camera_delta_override(brain,delta);}

inline bool begin_job() {
    pthread_mutex_lock(&control_mutex);
    if(!start_pending){pthread_mutex_unlock(&control_mutex);return false;}
    job=Job{};job.options=pending_options;job.config=configured;
    job.config.root=dup(configured.root);job.config.req=dup(configured.req);job.config.rsp=dup(configured.rsp);job.config.prepared=dup(configured.prepared);job.config.exports=dup(configured.exports);
    if(pending_queue_output[0]){
        snprintf(job.status.id,sizeof(job.status.id),"%s",pending_queue_output);
        close(job.config.exports);job.config.exports=dup(pending_queue_exports_fd);
        snprintf(job.config.output,sizeof(job.config.output),"%s",pending_queue_exports);
        job.expected_width=pending_queue_width;job.expected_height=pending_queue_height;
        pending_queue_output[0]=pending_queue_exports[0]=0;pending_queue_exports_fd=-1;
    }
    start_pending=false;job.stage=Stage::begin;pthread_mutex_unlock(&control_mutex);
    job.api=platform_encoder();job.status.fps_num=job.options.fps_num;job.status.fps_den=job.options.fps_den;job.status.video_codec=job.options.codec;
    if(!job.status.id[0]){uint8_t id[16]{};if(!random_bytes(id,sizeof(id))){terminal("random_unavailable");return true;}hex(id,sizeof(id),job.status.id);}
    if(!job.api.valid()){terminal("platform_encoder_unavailable");return true;}
    if(!active_broker()){terminal("audio_broker_retired");return true;}
    if(probe_readiness(job.snapshot)!=Result::ok){terminal(readiness_error);return true;}
    if(game.begin_manual()!=Result::ok){terminal(game.last_error());return true;}
    if(job.options.output_width){
        const Result resized=game.set_output_geometry(job.options.output_width,job.options.output_height);
        if(resized==Result::ok){job.expected_width=job.options.output_width;job.expected_height=job.options.output_height;}
        else if(resized!=Result::unsupported){terminal(game.last_error());return true;}
    }
    for(size_t i=0;i<job.snapshot.audio.count;++i){const auto& c=job.snapshot.audio.clips[i];if(!c.muted&&c.track_gain*c.clip_gain*c.source_gain>0){if(!job.rate)job.rate=static_cast<uint32_t>(c.sample_rate);if(job.rate!=static_cast<uint32_t>(c.sample_rate)){terminal("mixed_sample_rates_unsupported");return true;}}}
    if(!job.rate){terminal("selected_mv_has_no_audible_music");return true;}
    job.total_audio=static_cast<uint64_t>(__builtin_llround(job.snapshot.duration_seconds*job.rate));
    job.total_frames=(job.total_audio*job.options.fps_num+static_cast<uint64_t>(job.rate)*job.options.fps_den-1)/(static_cast<uint64_t>(job.rate)*job.options.fps_den);
    if(!job.total_audio||!job.total_frames||job.total_audio>static_cast<uint64_t>(job.rate)*900){terminal("audio_duration_invalid");return true;}
    job.status.total_audio=job.total_audio;job.status.total_frames=job.total_frames;
    snprintf(job.pcm_name,sizeof(job.pcm_name),"%s.pcm",job.status.id);
    char partial_name[48]{},final_name[48]{};
    snprintf(partial_name,sizeof(partial_name),"%s.partial.mp4",job.status.id);
    snprintf(final_name,sizeof(final_name),"%s.mp4",job.status.id);
    if(!join_path(job.pcm_path,sizeof(job.pcm_path),job.config.output,job.pcm_name)
        ||!join_path(job.partial_path,sizeof(job.partial_path),job.config.output,partial_name)
        ||!join_path(job.final_path,sizeof(job.final_path),job.config.output,final_name)){terminal("export_path_too_long");return true;}
    job.pcm=openat(job.config.exports,job.pcm_name,rw|create|exclusive|nofollow,0600);
    job.pcm_owned=job.pcm>=0&&fstat(job.pcm,&job.pcm_identity)==0;
    if(job.pcm<0||ftruncate(job.pcm,static_cast<int64_t>(job.total_audio*8))!=0){terminal("pcm_file_create_failed");return true;}
    job.stage=Stage::audio_request;phase("preparing_audio");return true;
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
    if(!frames){if(!job.audible_energy){terminal("selected_music_is_silent");return;}if(fsync(job.pcm)!=0){terminal("pcm_sync_failed");return;}close(job.pcm);job.pcm=-1;job.stage=Stage::frame_request;phase("rendering");return;}
    size_t bytes=frames*8;int64_t offset=static_cast<int64_t>(job.finalized_audio*8);
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,false)){terminal("pcm_read_failed");return;}
    for(size_t i=0;i<frames*2;++i){float value=job.mixed_pcm[i];if(!__builtin_isfinite(value)){terminal("audio_mix_nonfinite");return;}if(value>0.000000001f||value< -0.000000001f)job.audible_energy=true;job.mixed_pcm[i]=value>1?1:value< -1?-1:value;}
    if(!transfer_at(job.pcm,job.mixed_pcm,bytes,offset,true)){terminal("pcm_write_failed");return;}
    job.finalized_audio+=frames;job.status.audio=job.finalized_audio;progress();publish();
}
inline void request_frame() {
    if(job.frame>=job.total_frames){if(!job.encoder||job.api.finish(job.encoder)<0){terminal("encoder_finish_rejected");return;}job.stage=Stage::finishing;phase("finishing");return;}
    const double time=static_cast<double>(job.frame)*job.options.fps_den/job.options.fps_num;
    if(game.evaluate(time)!=Result::ok||game.request_capture()!=Result::ok){terminal(game.last_error());return;}
    int32_t width=0,height=0;if(game.capture_geometry(width,height)!=Result::ok){terminal(game.last_error());return;}
    if((job.expected_width&&job.expected_width!=static_cast<uint32_t>(width))
        ||(job.expected_height&&job.expected_height!=static_cast<uint32_t>(height))){terminal("queued_capture_geometry_changed");return;}
    if(!idoly_mp4_output::source_dimensions(static_cast<uint32_t>(width),static_cast<uint32_t>(height))){terminal("capture_geometry_not_supported");return;}
    if(job.status.source_width&&(job.status.source_width!=static_cast<uint32_t>(width)||job.status.source_height!=static_cast<uint32_t>(height))){terminal("capture_geometry_changed");return;}
    job.status.source_width=static_cast<uint32_t>(width);job.status.source_height=static_cast<uint32_t>(height);
    job.status.width=job.options.output_width?job.options.output_width:static_cast<uint32_t>(width)&~1U;
    job.status.height=job.options.output_height?job.options.output_height:static_cast<uint32_t>(height)&~1U;
    job.status.video_codec=job.options.codec;
    job.status.video_bitrate=idoly_mp4_output::resolved_bitrate(job.options.bitrate,job.status.width,job.status.height,job.options.fps_num,job.options.codec);
    if(!job.status.video_bitrate){terminal("invalid_export_options");return;}
    const size_t needed=static_cast<size_t>(width)*static_cast<size_t>(height)*4;
    if(!job.rgba){job.rgba=static_cast<uint8_t*>(malloc(needed));job.rgba_capacity=needed;if(!job.rgba){terminal("frame_buffer_allocation_failed");return;}}
    if((job.status.width!=static_cast<uint32_t>(width)||job.status.height!=static_cast<uint32_t>(height))&&!job.output_rgba){
        job.output_capacity=static_cast<size_t>(job.status.width)*job.status.height*4;
        job.output_rgba=static_cast<uint8_t*>(malloc(job.output_capacity));
        if(!job.output_rgba){terminal("output_buffer_allocation_failed");return;}
    }
    if(!job.encoder){IDMP4EncoderConfig c{};c.struct_size=sizeof(c);c.abi_version=1;c.width=job.status.width;c.height=job.status.height;c.fps_num=job.options.fps_num;c.fps_den=job.options.fps_den;c.video_codec=job.options.codec;c.video_bitrate=job.status.video_bitrate;c.audio_sample_rate=job.rate;c.audio_channels=2;c.audio_bitrate=job.options.audio_bitrate;c.audio_sample_frames=job.total_audio;c.video_frame_count=job.total_frames;c.pcm_f32_path=job.pcm_path;c.partial_path=job.partial_path;c.final_path=job.final_path;char error[192]{};job.encoder=job.api.create(&c,error,sizeof(error));if(!job.encoder){terminal(error);return;}}
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
    if(s.phase==IDMP4_COMPLETED&&job.stage==Stage::finishing){job.terminal_success=true;job.stage=Stage::retiring;game.restore();phase("finishing");}
}
inline void retire() {
    if(!retire_pending_audio())return;
    if(job.encoder){const int result=job.api.destroy(job.encoder);if(result==IDMP4_RETRY)return;if(result<0){stable_error("encoder_cleanup_failed");job.terminal_success=false;}job.encoder=nullptr;}
    if(!cleanup_bundle())return; // Original Unity async bundle IO must finish first.
    if(job.pcm>=0){close(job.pcm);job.pcm=-1;}
    if(job.pcm_owned)unlink_owned(job.config.exports,job.pcm_name,job.pcm_identity);
    if(job.rgba){free(job.rgba);job.rgba=nullptr;}
    if(job.output_rgba){free(job.output_rgba);job.output_rgba=nullptr;}
    close_configuration(job.config);
    job.stage=Stage::idle;phase(job.terminal_success?"completed":job.terminal_cancel?"cancelled":"failed");
    pthread_mutex_lock(&control_mutex);control_busy=false;cancel_pending=false;pthread_mutex_unlock(&control_mutex);
}
inline void on_unity_tick() {
    if(!installed)return;
    queue_tick();
    pthread_mutex_lock(&control_mutex);
    increment_counter(unity_ticks);
    const bool should_cancel=cancel_pending;
    if(should_cancel&&start_pending&&!busy_stage()){
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
        pause_acknowledged=true;reset_watchdog_pending=true;
        pthread_mutex_unlock(&control_mutex);return;
    }
    const bool reset_watchdog=reset_watchdog_pending;
    reset_watchdog_pending=false;pause_acknowledged=false;
    pthread_mutex_unlock(&control_mutex);
    if(reset_watchdog&&busy_stage())progress();
    game.maintenance();
    if(!busy_stage()){
        Snapshot ready{};const Result readiness=probe_readiness(ready);
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
        case Stage::audio_request:request_audio();break;
        case Stage::audio_response:poll_audio_response();break;
        case Stage::audio_load:{Result r=game.poll_private_audio();if(r==Result::ok){job.stage=Stage::audio_mix;progress();}else if(r!=Result::waiting)terminal(game.last_error());break;}
        case Stage::audio_mix:{uint64_t began=milliseconds();for(unsigned chunk=0;chunk<4&&job.stage==Stage::audio_mix;++chunk){mix_audio();if(milliseconds()-began>=8)break;}break;}
        case Stage::audio_finalize:{uint64_t began=milliseconds();for(unsigned chunk=0;chunk<4&&job.stage==Stage::audio_finalize;++chunk){finalize_audio();if(milliseconds()-began>=8)break;}break;}
        case Stage::frame_request:request_frame();break;
        case Stage::frame_wait:if(job.captured){size_t count=0;int32_t w=0,h=0;Result r=game.readback_rgba(job.rgba,job.rgba_capacity,count,w,h);if(r==Result::ok){
            if(static_cast<uint32_t>(w)!=job.status.source_width||static_cast<uint32_t>(h)!=job.status.source_height||count!=job.rgba_capacity){terminal("capture_geometry_changed");break;}
            if(job.output_rgba&&!idoly_mp4_output::resample_rgba(job.rgba,count,static_cast<uint32_t>(w),static_cast<uint32_t>(h),job.output_rgba,job.output_capacity,job.status.width,job.status.height)){terminal("output_resize_failed");break;}
            job.stage=Stage::frame_submit;progress();}else if(r!=Result::waiting)terminal(game.last_error());}break;
        case Stage::frame_submit:{int r=job.api.append(job.encoder,job.output_rgba?job.output_rgba:job.rgba,static_cast<size_t>(job.status.width)*4,job.frame);if(r==IDMP4_ACCEPTED){++job.frame;job.status.frames=job.frame;job.stage=Stage::frame_request;progress();}else if(r!=IDMP4_RETRY)terminal("encoder_frame_rejected");break;}
        case Stage::finishing:break;
        case Stage::retiring:retire();break;
        default:break;
    }
    publish();
}
inline size_t status(char*buffer,size_t capacity){
    if(!buffer||!capacity)return 0;
    pthread_mutex_lock(&control_mutex);
    const PublicStatus s=published;char readiness[96]{};snprintf(readiness,sizeof(readiness),"%s",readiness_error);
    const uint64_t ticks=unity_ticks,acks=capture_acks;
    const bool requested=control_busy&&s.pausable&&requested_pause_reason!=IDMP4_PAUSE_NONE,paused=requested&&pause_acknowledged;
    const int reason=requested?requested_pause_reason:IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&control_mutex);
    const char* current_phase=requested?(paused?"paused":"pausing"):s.phase;
    int n=snprintf(buffer,capacity,"{\"schema\":1,\"unity_ticks\":%llu,\"capture_acks\":%llu,\"ready\":%s,\"readiness_error\":\"%s\",\"phase\":\"%s\",\"paused\":%s,\"pause_requested\":%s,\"pause_reason\":\"%s\",\"resume_phase\":\"%s\",\"export_id\":\"%s\",\"error_code\":\"%s\",\"frames\":%llu,\"total_frames\":%llu,\"audio_frames\":%llu,\"total_audio_frames\":%llu,\"width\":%u,\"height\":%u,\"source_width\":%u,\"source_height\":%u,\"video_codec\":%u,\"video_bitrate\":%u,\"fps_num\":%u,\"fps_den\":%u,\"bytes_written\":%llu}",
        static_cast<unsigned long long>(ticks),static_cast<unsigned long long>(acks),s.ready?"true":"false",readiness,current_phase,
        paused?"true":"false",requested?"true":"false",pause_reason_name(reason),requested?s.phase:"none",s.id,s.error,
        static_cast<unsigned long long>(s.frames),static_cast<unsigned long long>(s.total_frames),
        static_cast<unsigned long long>(s.audio),static_cast<unsigned long long>(s.total_audio),s.width,s.height,s.source_width,s.source_height,
        s.video_codec,s.video_bitrate,s.fps_num,s.fps_den,static_cast<unsigned long long>(s.bytes));
    return n>0&&static_cast<size_t>(n)<capacity?static_cast<size_t>(n):0;
}
} // namespace idoly_mp4_runtime

#include "mp4_queue_runtime.hpp"

extern "C" IDMP4_SESSION_API int IDMP4SessionConfigure(const char*b,uint64_t e,const char*c,const char*o,int p){return idoly_mp4_runtime::configure(b,e,c,o,p)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4SessionStart(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a){return idoly_mp4_runtime::start({n,d,c,v,a})?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4SessionStartV2(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a,uint32_t w,uint32_t h){return idoly_mp4_runtime::start({n,d,c,v,a,w,h})?0:-1;}
extern "C" IDMP4_SESSION_API size_t IDMP4SessionStatus(char*b,size_t c){return idoly_mp4_runtime::status(b,c);}
extern "C" IDMP4_SESSION_API void IDMP4SessionCancel(){idoly_mp4_runtime::cancel();}
extern "C" IDMP4_SESSION_API void IDMP4SessionSuspend(int reason){idoly_mp4_runtime::suspend(reason);}
extern "C" IDMP4_SESSION_API void IDMP4SessionResume(){idoly_mp4_runtime::resume();}
extern "C" IDMP4_SESSION_API int IDMP4SessionReady(){pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);bool ready=idoly_mp4_runtime::published.ready;pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);return ready?1:0;}
