// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Persistent logical MV jobs. No Unity/managed objects, filenames supplied by
// clients, or encoder state are serialized. A single host owner must serialize
// calls; immutable at() views remain valid only until the next mutation.
#ifndef IDOLY_DARWIN_BRIDGE
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/file.h>
#if defined(__linux__)
#include <sys/syscall.h>
#endif
#include <errno.h>
#include <initializer_list>
#include <new>
#else
extern "C" { int* __error(); int linkat(int,const char*,int,const char*,int); int flock(int,int); }
namespace idoly_mp4_queue_placement { struct Address { void* value; }; }
inline void*operator new(size_t,idoly_mp4_queue_placement::Address address)noexcept{return address.value;}
inline void operator delete(void*,idoly_mp4_queue_placement::Address)noexcept{}
#endif
#include "mp4_output_policy.hpp"

namespace idoly_mp4_queue {
constexpr size_t max_jobs=8, max_actors=32, max_assets=16, name_capacity=193;
constexpr size_t max_wire_bytes=1024*1024, header_bytes=104;
enum class State : uint32_t { pending=1,running=2,paused=3,completed=4,failed=5,cancelled=6,interrupted=7 };
enum class Error { ok,not_open,invalid_argument,invalid_descriptor,invalid_options,full,not_found,
    invalid_state,busy,random_failed,unsafe_storage,changed_storage,corrupt,profile_mismatch,io,durability_uncertain };
inline const char* error_code(Error e) {
    switch(e){case Error::ok:return "none";case Error::not_open:return "queue_not_open";
    case Error::invalid_argument:return "invalid_argument";case Error::invalid_descriptor:return "invalid_mv_descriptor";
    case Error::invalid_options:return "invalid_export_options";case Error::full:return "queue_full";
    case Error::not_found:return "job_not_found";case Error::invalid_state:return "invalid_job_state";
    case Error::busy:return "queue_busy";case Error::random_failed:return "random_unavailable";
    case Error::unsafe_storage:return "unsafe_queue_storage";case Error::changed_storage:return "queue_storage_changed";
    case Error::corrupt:return "queue_corrupt";case Error::profile_mismatch:return "queue_profile_mismatch";
    case Error::durability_uncertain:return "queue_durability_uncertain";default:return "queue_io_failed";}
}
inline const char* state_name(State s) { switch(s){case State::pending:return "pending";case State::running:return "running";
    case State::paused:return "paused";case State::completed:return "completed";case State::failed:return "failed";
    case State::cancelled:return "cancelled";default:return "interrupted";} }
struct Actor {
    char character_id[name_capacity]{};
    char descriptor_name[name_capacity]{};
    int32_t actor_index=0,track_index=0,audience_amount=0,psyllium_color_type=0;
    uint32_t asset_count=0;char assets[max_assets][name_capacity]{};
    int32_t collider_type=0,render_layer_base=0;
    uint8_t humanoid=0,trigger=0,auto_blink_disabled=0,use_adv_settings=0,name_is_null=0;
};
struct PhotoCostume {
    char costume_id[name_capacity]{},hair_id[name_capacity]{};
};
struct PhotoSelection {
    // 0 is the original OutGame scene; 1 is normal master-data Photography.
    // Keep this logical transition distinct from its resolved render assets.
    uint32_t source_kind=0;
    uint8_t is_preview=0,is_original=0,screen_transition=0;
    char stage_id[name_capacity]{},music_id[name_capacity]{};
    uint32_t actor_count=0;PhotoCostume actors[max_actors]{};
};
struct Descriptor {
    char stage_asset[name_capacity]{},timeline_asset[name_capacity]{};
    uint32_t actor_count=0;Actor actors[max_actors]{};
    // OutGameLivePlayerParam; detached actors with GameObjects are unsupported.
    int32_t stage_max_capacity=0;
    uint8_t detach_actors_on_player_destroyed=0;
    PhotoSelection photo{};
};
struct Graphics {
    int64_t revision=0;uint8_t custom_graphics=0;
    int32_t quality=0,target_fps=0;float render_scale=1;
    int32_t max_buffer_pixel=4096,aa_mode=-1,shadow_resolution=0;
    uint8_t expand_photography=0;
};
struct Options { uint32_t fps_num=30,fps_den=1,codec=1,video_bitrate=16000000,audio_bitrate=192000,width=0,height=0;
    uint32_t output_width=0,output_height=0;Graphics graphics{}; };
struct Job {
    char id[33]{},output_id[33]{};Descriptor descriptor{};Options options{};
    State state=State::pending;uint32_t attempts=0;char error[65]{},pause_reason[65]{};
};
struct Store { uint64_t generation=0;uint32_t count=0;Job jobs[max_jobs]{}; };
using Random=bool(*)(void*,uint8_t*,size_t);
namespace detail {
template<class T>inline T*allocate(){void*memory=malloc(sizeof(T));if(!memory)return nullptr;
#ifdef IDOLY_DARWIN_BRIDGE
    return new(idoly_mp4_queue_placement::Address{memory})T{};
#else
    return new(memory)T{};
#endif
}
// Reconstruct plain value storage directly at its destination. Assigning a
// large T{} can materialize the full value on a small Unity callback stack;
// placement construction preserves member defaults without that temporary.
template<class T>inline void reset_value(T& value){
    static_assert(__is_trivially_copyable(T),"reset_value requires plain value storage");
    value.~T();
#ifdef IDOLY_DARWIN_BRIDGE
    new(idoly_mp4_queue_placement::Address{&value})T{};
#else
    new(static_cast<void*>(&value))T{};
#endif
}
#ifdef IDOLY_DARWIN_BRIDGE
constexpr int rd=0,wr=1,rw=2,create=0x200,exclusive=0x800,nofollow=0x100,directory=0x100000,nonblock=4;
inline int error_number(){return *__error();}
#else
constexpr int rd=O_RDONLY,wr=O_WRONLY,rw=O_RDWR,create=O_CREAT,exclusive=O_EXCL,nofollow=O_NOFOLLOW,directory=O_DIRECTORY,nonblock=O_NONBLOCK;
inline int error_number(){return errno;}
#endif
inline bool random(void*,uint8_t* bytes,size_t count){
#ifdef IDOLY_DARWIN_BRIDGE
    arc4random_buf(bytes,count);return true;
#else
    int fd=::open("/dev/urandom",rd|nofollow);if(fd<0)return false;
    size_t at=0;while(at<count){long n=::read(fd,bytes+at,count-at);if(n<0&&error_number()==EINTR)continue;if(n<=0){::close(fd);return false;}at+=static_cast<size_t>(n);}::close(fd);return true;
#endif
}
inline size_t length(const char* s,size_t cap){if(!s)return cap;size_t n=0;while(n<cap&&s[n])++n;return n;}
inline bool hex(const char* s,size_t n){if(length(s,n+1)!=n)return false;for(size_t i=0;i<n;++i)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return false;return true;}
inline bool name(const char* s){size_t n=length(s,name_capacity);if(!n||n>=name_capacity)return false;for(size_t i=0;i<n;++i){const char c=s[i];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.'))return false;}return true;}
inline bool display_name(const char*s){size_t n=length(s,name_capacity);if(n>=name_capacity)return false;for(size_t i=0;i<n;){uint32_t c=static_cast<uint8_t>(s[i++]);if(c<0x80){if(c<0x20||c==0x7f)return false;continue;}unsigned extra;uint32_t minimum;if(c>=0xc2&&c<=0xdf){extra=1;minimum=0x80;c&=0x1f;}else if(c>=0xe0&&c<=0xef){extra=2;minimum=0x800;c&=0x0f;}else if(c>=0xf0&&c<=0xf4){extra=3;minimum=0x10000;c&=7;}else return false;if(extra>n-i)return false;for(unsigned k=0;k<extra;++k){uint32_t tail=static_cast<uint8_t>(s[i++]);if((tail&0xc0)!=0x80)return false;c=(c<<6)|(tail&0x3f);}if(c<minimum||c>0x10ffff||(c>=0xd800&&c<=0xdfff)||(c>=0x80&&c<0xa0))return false;}return true;}
inline bool code(const char* s){size_t n=length(s,65);if(!n||n>=65)return false;for(size_t i=0;i<n;++i)if(!((s[i]>='a'&&s[i]<='z')||(s[i]>='0'&&s[i]<='9')||s[i]=='_'))return false;return true;}
inline bool empty_photo_name(const char* value){for(size_t i=0;i<name_capacity;++i)if(value[i])return false;return true;}
inline bool photo(const PhotoSelection& p,uint32_t actor_count){
    if(p.source_kind>1||p.is_preview>1||p.is_original>1||p.screen_transition>1||p.actor_count>max_actors)return false;
    if(p.source_kind==0){
        if(p.is_preview||p.is_original||p.screen_transition||p.actor_count
            ||!empty_photo_name(p.stage_id)||!empty_photo_name(p.music_id))return false;
    }else if(!name(p.stage_id)||!name(p.music_id)||p.actor_count!=actor_count
        ||!p.actor_count||(!p.screen_transition&&p.is_original))return false;
    for(size_t i=0;i<max_actors;++i){
        if(i<p.actor_count){if(!name(p.actors[i].costume_id)||!name(p.actors[i].hair_id))return false;}
        else if(!empty_photo_name(p.actors[i].costume_id)||!empty_photo_name(p.actors[i].hair_id))return false;
    }
    return true;
}
inline bool descriptor(const Descriptor& d){if(!name(d.stage_asset)||!name(d.timeline_asset)||!d.actor_count||d.actor_count>max_actors||d.detach_actors_on_player_destroyed>1||!photo(d.photo,d.actor_count))return false;
    for(size_t i=0;i<d.actor_count;++i){const Actor& a=d.actors[i];if(!name(a.character_id)||!display_name(a.descriptor_name)||a.name_is_null>1||(a.name_is_null&&a.descriptor_name[0])||!a.asset_count||a.asset_count>max_assets||a.humanoid>1||a.trigger>1||a.auto_blink_disabled>1||a.use_adv_settings>1||(a.collider_type!=0&&a.collider_type!=1))return false;
        for(size_t j=0;j<a.asset_count;++j)if(!name(a.assets[j]))return false;
        for(size_t j=0;j<i;++j)if(d.actors[j].actor_index==a.actor_index||d.actors[j].track_index==a.track_index)return false;
    }return true;}
inline bool graphics(const Graphics&g){return g.revision>=0&&g.custom_graphics<=1&&g.expand_photography<=1
    &&(g.quality==0||g.quality==10||g.quality==20||g.quality==30||g.quality==40||g.quality==100)
    &&(g.target_fps==0||g.target_fps==30||g.target_fps==60||g.target_fps==90||g.target_fps==120)
    &&__builtin_isfinite(g.render_scale)&&g.render_scale>=.25f&&g.render_scale<=2.f
    &&g.max_buffer_pixel>=256&&g.max_buffer_pixel<=4096&&!(g.max_buffer_pixel&1)&&g.aa_mode>=-1&&g.aa_mode<=2
    &&(g.shadow_resolution==0||g.shadow_resolution==512||g.shadow_resolution==1024||g.shadow_resolution==2048||g.shadow_resolution==4096);}
inline bool options(const Options& o){return o.fps_den==1&&idoly_mp4_output::supported_fps(o.fps_num)&&(o.codec==1||o.codec==2)
    &&o.video_bitrate>=100000&&o.video_bitrate<=200000000&&o.audio_bitrate==192000
    &&o.width>=16&&o.height>=16&&o.width<=16384&&o.height<=16384
    &&idoly_mp4_output::requested_dimensions(o.output_width,o.output_height)&&graphics(o.graphics);}
inline bool safe_file_stat(const struct stat& s){return (s.st_mode&0170000)==0100000&&(s.st_mode&0777)==0600&&s.st_uid==geteuid()&&s.st_nlink==1&&s.st_size>=0&&static_cast<uint64_t>(s.st_size)<=max_wire_bytes;}
inline bool safe_file(int fd,struct stat& s){return fd>=0&&::fstat(fd,&s)==0&&safe_file_stat(s);}
inline int install_new(int directory,const char* temporary,const char* journal){
#if defined(__linux__)
    // Android's untrusted-app SELinux policy forbids hard links, including
    // app-private files. Use the kernel no-replace rename rather than the
    // libc renameat2 symbol, which was added only in Android API 30.
    // Unsupported kernels/filesystems must fail; never overwrite a new owner.
    return static_cast<int>(::syscall(SYS_renameat2,directory,temporary,directory,journal,1U));
#else
    const int result=::linkat(directory,temporary,directory,journal,0);
    if(result==0)::unlinkat(directory,temporary,0);
    return result;
#endif
}
inline bool same(const struct stat&a,const struct stat&b){
    if(a.st_dev!=b.st_dev||a.st_ino!=b.st_ino||a.st_uid!=b.st_uid||a.st_mode!=b.st_mode||a.st_nlink!=b.st_nlink||a.st_size!=b.st_size)return false;
#if defined(IDOLY_DARWIN_BRIDGE) || defined(__APPLE__)
    return a.st_mtimespec.tv_sec==b.st_mtimespec.tv_sec&&a.st_mtimespec.tv_nsec==b.st_mtimespec.tv_nsec&&a.st_ctimespec.tv_sec==b.st_ctimespec.tv_sec&&a.st_ctimespec.tv_nsec==b.st_ctimespec.tv_nsec;
#else
    return a.st_mtim.tv_sec==b.st_mtim.tv_sec&&a.st_mtim.tv_nsec==b.st_mtim.tv_nsec&&a.st_ctim.tv_sec==b.st_ctim.tv_sec&&a.st_ctim.tv_nsec==b.st_ctim.tv_nsec;
#endif
}
inline void put32(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=static_cast<uint8_t>(n>>(i*8));}
inline void put64(uint8_t*p,uint64_t n){for(unsigned i=0;i<8;++i)p[i]=static_cast<uint8_t>(n>>(i*8));}
inline uint32_t get32(const uint8_t*p){uint32_t n=0;for(unsigned i=0;i<4;++i)n|=uint32_t(p[i])<<(i*8);return n;}
inline uint64_t get64(const uint8_t*p){uint64_t n=0;for(unsigned i=0;i<8;++i)n|=uint64_t(p[i])<<(i*8);return n;}
inline uint64_t checksum(const uint8_t*p,size_t n,uint64_t hash=14695981039346656037ULL){for(size_t i=0;i<n;++i){hash^=p[i];hash*=1099511628211ULL;}return hash;}
struct Writer {
    uint8_t* bytes;size_t cap,at=0;bool ok=true;
    void raw(const void* p,size_t n){if(!ok||n>cap-at){ok=false;return;}memcpy(bytes+at,p,n);at+=n;}
    void u32(uint32_t n){uint8_t b[4];put32(b,n);raw(b,4);}
    void u64(uint64_t n){uint8_t b[8];put64(b,n);raw(b,8);}
    void str(const char*s,size_t cap){size_t n=length(s,cap);if(n>=cap||n>65535){ok=false;return;}uint8_t b[2]={static_cast<uint8_t>(n),static_cast<uint8_t>(n>>8)};raw(b,2);raw(s,n);}
};
struct Reader {
    const uint8_t* bytes;size_t cap,at=0;bool ok=true;
    void raw(void*p,size_t n){if(!ok||n>cap-at){ok=false;return;}memcpy(p,bytes+at,n);at+=n;}
    uint32_t u32(){uint8_t b[4]{};raw(b,4);return get32(b);}
    uint64_t u64(){uint8_t b[8]{};raw(b,8);return get64(b);}
    void str(char*s,size_t cap){uint8_t b[2]{};raw(b,2);size_t n=size_t(b[0])|(size_t(b[1])<<8);if(!ok||n>=cap){ok=false;return;}raw(s,n);if(ok){for(size_t i=0;i<n;++i)if(!s[i]){ok=false;return;}s[n]=0;}}
};
inline void encode(Writer&w,const Job&j,uint32_t version=3){
    if(version<1||version>3||!descriptor(j.descriptor)||(version<3&&j.descriptor.photo.source_kind)){
        w.ok=false;return;
    }
    w.str(j.id,33);w.str(j.output_id,33);w.u32(static_cast<uint32_t>(j.state));w.u32(j.attempts);w.str(j.error,65);w.str(j.pause_reason,65);
    const Options&o=j.options;for(uint32_t v:{o.fps_num,o.fps_den,o.codec,o.video_bitrate,o.audio_bitrate,o.width,o.height})w.u32(v);
    if(version>=2){w.u32(o.output_width);w.u32(o.output_height);}
    const Graphics&g=o.graphics;w.u64(static_cast<uint64_t>(g.revision));w.u32(g.custom_graphics);w.u32(static_cast<uint32_t>(g.quality));w.u32(static_cast<uint32_t>(g.target_fps));uint32_t scale=0;memcpy(&scale,&g.render_scale,4);w.u32(scale);w.u32(static_cast<uint32_t>(g.max_buffer_pixel));w.u32(static_cast<uint32_t>(g.aa_mode));w.u32(static_cast<uint32_t>(g.shadow_resolution));w.u32(g.expand_photography);
    const Descriptor&d=j.descriptor;w.str(d.stage_asset,name_capacity);w.str(d.timeline_asset,name_capacity);w.u32(static_cast<uint32_t>(d.stage_max_capacity));w.u32(d.detach_actors_on_player_destroyed);w.u32(d.actor_count);
    for(size_t i=0;i<d.actor_count;++i){const Actor&a=d.actors[i];w.str(a.character_id,name_capacity);w.str(a.descriptor_name,name_capacity);for(int32_t v:{a.actor_index,a.track_index,a.audience_amount,a.psyllium_color_type,a.collider_type,a.render_layer_base})w.u32(static_cast<uint32_t>(v));w.u32(a.humanoid);w.u32(a.trigger);w.u32(a.auto_blink_disabled);w.u32(a.use_adv_settings);w.u32(a.name_is_null);w.u32(a.asset_count);for(size_t k=0;k<a.asset_count;++k)w.str(a.assets[k],name_capacity);}
    if(version>=3){
        const PhotoSelection&p=d.photo;w.u32(p.source_kind);w.u32(p.is_preview);w.u32(p.is_original);w.u32(p.screen_transition);
        w.str(p.stage_id,name_capacity);w.str(p.music_id,name_capacity);w.u32(p.actor_count);
        for(size_t i=0;i<p.actor_count;++i){w.str(p.actors[i].costume_id,name_capacity);w.str(p.actors[i].hair_id,name_capacity);}
    }
}
inline bool decode(Reader&r,Job&j,uint32_t version=3){
    if(version<1||version>3)return false;
    r.str(j.id,33);r.str(j.output_id,33);uint32_t s=r.u32();if(s<1||s>7)return false;j.state=static_cast<State>(s);j.attempts=r.u32();r.str(j.error,65);r.str(j.pause_reason,65);
    Options&o=j.options;o.fps_num=r.u32();o.fps_den=r.u32();o.codec=r.u32();o.video_bitrate=r.u32();o.audio_bitrate=r.u32();o.width=r.u32();o.height=r.u32();
    if(version>=2){o.output_width=r.u32();o.output_height=r.u32();}
    else {o.output_width=o.output_height=0;}
    Graphics&g=o.graphics;g.revision=static_cast<int64_t>(r.u64());uint32_t custom=r.u32();g.quality=static_cast<int32_t>(r.u32());g.target_fps=static_cast<int32_t>(r.u32());uint32_t scale=r.u32();memcpy(&g.render_scale,&scale,4);g.max_buffer_pixel=static_cast<int32_t>(r.u32());g.aa_mode=static_cast<int32_t>(r.u32());g.shadow_resolution=static_cast<int32_t>(r.u32());uint32_t expanded=r.u32();if(custom>1||expanded>1)return false;g.custom_graphics=static_cast<uint8_t>(custom);g.expand_photography=static_cast<uint8_t>(expanded);
    Descriptor&d=j.descriptor;reset_value(d.photo);r.str(d.stage_asset,name_capacity);r.str(d.timeline_asset,name_capacity);d.stage_max_capacity=static_cast<int32_t>(r.u32());uint32_t detach=r.u32();if(detach>1)return false;d.detach_actors_on_player_destroyed=static_cast<uint8_t>(detach);d.actor_count=r.u32();if(d.actor_count>max_actors)return false;
    for(size_t i=0;i<d.actor_count;++i){Actor&a=d.actors[i];r.str(a.character_id,name_capacity);r.str(a.descriptor_name,name_capacity);a.actor_index=static_cast<int32_t>(r.u32());a.track_index=static_cast<int32_t>(r.u32());a.audience_amount=static_cast<int32_t>(r.u32());a.psyllium_color_type=static_cast<int32_t>(r.u32());a.collider_type=static_cast<int32_t>(r.u32());a.render_layer_base=static_cast<int32_t>(r.u32());uint32_t human=r.u32(),trigger=r.u32(),blink=r.u32(),adv=r.u32(),isnull=r.u32();if(human>1||trigger>1||blink>1||adv>1||isnull>1)return false;a.humanoid=static_cast<uint8_t>(human);a.trigger=static_cast<uint8_t>(trigger);a.auto_blink_disabled=static_cast<uint8_t>(blink);a.use_adv_settings=static_cast<uint8_t>(adv);a.name_is_null=static_cast<uint8_t>(isnull);a.asset_count=r.u32();if(a.asset_count>max_assets)return false;for(size_t k=0;k<a.asset_count;++k)r.str(a.assets[k],name_capacity);}
    if(version>=3){
        PhotoSelection&p=d.photo;p.source_kind=r.u32();uint32_t preview=r.u32(),original=r.u32(),screen=r.u32();
        if(preview>1||original>1||screen>1)return false;
        p.is_preview=static_cast<uint8_t>(preview);p.is_original=static_cast<uint8_t>(original);p.screen_transition=static_cast<uint8_t>(screen);
        r.str(p.stage_id,name_capacity);r.str(p.music_id,name_capacity);p.actor_count=r.u32();if(p.actor_count>max_actors)return false;
        for(size_t i=0;i<p.actor_count;++i){r.str(p.actors[i].costume_id,name_capacity);r.str(p.actors[i].hair_id,name_capacity);}
    }
    return r.ok&&hex(j.id,32)&&(!j.output_id[0]||hex(j.output_id,32))&&descriptor(d)&&options(o)
        &&(!j.error[0]||code(j.error))&&(!j.pause_reason[0]||code(j.pause_reason))
        &&(j.state!=State::pending||!j.output_id[0])
        &&(j.state==State::pending||j.state==State::cancelled||(j.attempts&&j.output_id[0]));
}
} // namespace detail

class Queue {
public:
    explicit Queue(Random random=nullptr,void* context=nullptr):random_(random?random:detail::random),random_context_(context){}
    ~Queue(){close();}
    Queue(const Queue&)=delete;Queue&operator=(const Queue&)=delete;
    Error open(const char* path,const char* profile){
        close();clear_storage_error();if(!path||path[0]!='/'||!detail::hex(profile,64))return Error::invalid_argument;
        directory_=::open(path,detail::rd|detail::nofollow|detail::directory);struct stat d{};
        if(directory_<0||::fstat(directory_,&d)!=0||(d.st_mode&0170000)!=0040000||(d.st_mode&0777)!=0700||d.st_uid!=geteuid()){close();return Error::unsafe_storage;}
        lock_=::openat(directory_,".queue-v1.lock",detail::rw|detail::create|detail::nofollow|detail::nonblock,0600);
        struct stat lock_identity{};if(!detail::safe_file(lock_,lock_identity)||lock_identity.st_size!=0){close();return Error::unsafe_storage;}
        // LOCK_EX | LOCK_NB have the same public values on Darwin and Linux.
        if(::flock(lock_,2|4)!=0){close();return Error::busy;}
        state_=detail::allocate<Store>();if(!state_){storage_failed("allocate_state",12);close();return Error::io;}memcpy(profile_,profile,65);
        int fd=::openat(directory_,filename(),detail::rd|detail::nofollow|detail::nonblock);
        if(fd<0){if(detail::error_number()!=2){close();return Error::unsafe_storage;}return Error::ok;}
        struct stat s{};if(!detail::safe_file(fd,s)||s.st_size<static_cast<int64_t>(header_bytes)){::close(fd);close();return Error::corrupt;}
        size_t n=static_cast<size_t>(s.st_size);uint8_t* bytes=static_cast<uint8_t*>(malloc(n));if(!bytes){storage_failed("allocate_wire",12);::close(fd);close();return Error::io;}
        size_t at=0;while(at<n){long got=::read(fd,bytes+at,n-at);if(got<0&&detail::error_number()==4)continue;if(got<=0)break;at+=static_cast<size_t>(got);}uint8_t tail=0;long extra=::read(fd,&tail,1);struct stat after{};
        bool stable=::fstat(fd,&after)==0&&detail::same(s,after);::close(fd);
        Error result=Error::corrupt;
        const uint32_t version=detail::get32(bytes+8);
        if(at==n&&extra==0&&stable&&memcmp(bytes,"IDMPQ001",8)==0&&(version==1||version==2||version==3)&&detail::get32(bytes+12)==header_bytes
            &&detail::get32(bytes+92)==n-header_bytes&&detail::get32(bytes+88)<=max_jobs
            &&detail::get64(bytes+96)==detail::checksum(bytes+header_bytes,n-header_bytes,detail::checksum(bytes,96))){
            if(memcmp(bytes+16,profile_,64)!=0)result=Error::profile_mismatch;
            else {state_->generation=detail::get64(bytes+80);state_->count=detail::get32(bytes+88);detail::Reader r{bytes+header_bytes,n-header_bytes};bool valid=true;size_t active=0;
                for(size_t i=0;i<state_->count&&valid;++i){valid=detail::decode(r,state_->jobs[i],version);for(size_t j=0;j<i&&valid;++j)if(!strcmp(state_->jobs[i].id,state_->jobs[j].id)||(state_->jobs[i].output_id[0]&&!strcmp(state_->jobs[i].output_id,state_->jobs[j].output_id)))valid=false;if(state_->jobs[i].state==State::running||state_->jobs[i].state==State::paused)++active;}
                if(valid&&r.ok&&r.at==r.cap&&active<=1){identity_=s;has_journal_=true;result=Error::ok;}
            }
        }free(bytes);if(result!=Error::ok){close();return result;}
        bool recover=false;for(size_t i=0;i<state_->count;++i)if(state_->jobs[i].state==State::running||state_->jobs[i].state==State::paused)recover=true;
        if(recover){Store*next=clone();if(!next){close();return Error::io;}for(size_t i=0;i<next->count;++i)if(next->jobs[i].state==State::running||next->jobs[i].state==State::paused){next->jobs[i].state=State::interrupted;snprintf(next->jobs[i].error,65,"process_interrupted");next->jobs[i].pause_reason[0]=0;}result=commit(next);if(result!=Error::ok){close();return result;}}
        return Error::ok;
    }
    void close(){if(lock_>=0)::close(lock_);lock_=-1;if(directory_>=0)::close(directory_);directory_=-1;if(state_)free(state_);state_=nullptr;has_journal_=false;blocked_=false;profile_[0]=0;}
    size_t count()const{return state_?state_->count:0;}
    const char* storage_stage()const{return storage_stage_;}
    int storage_errno()const{return storage_errno_;}
    uint64_t generation()const{return state_?state_->generation:0;}
    const Job* at(size_t i)const{return state_&&i<state_->count?&state_->jobs[i]:nullptr;}
    const Job* find(const char*id)const{int i=index(id);return i<0?nullptr:&state_->jobs[i];}
    Error enqueue(const Descriptor&d,const Options&o,char out[33]){
        if(!state_||blocked_)return Error::not_open;
        if(!detail::descriptor(d))return Error::invalid_descriptor;
        if(!detail::options(o))return Error::invalid_options;
        if(state_->count==max_jobs)return Error::full;
        char id[33]{};if(!new_id(id))return Error::random_failed;Store*next=clone();if(!next)return Error::io;Job&j=next->jobs[next->count++];detail::reset_value(j);j.descriptor=d;j.options=o;j.state=State::pending;memcpy(j.id,id,33);Error e=commit(next);if(e==Error::ok&&out)memcpy(out,id,33);return e;
    }
    Error claim_next(char out[33]){
        if(!state_||blocked_)return Error::not_open;
        for(size_t i=0;i<state_->count;++i)if(active(state_->jobs[i]))return Error::busy;
        size_t pick=state_->count;for(size_t i=0;i<state_->count;++i)if(state_->jobs[i].state==State::pending){pick=i;break;}if(pick==state_->count)return Error::not_found;
        char output[33]{};if(!new_id(output))return Error::random_failed;Store*next=clone();if(!next)return Error::io;Job&j=next->jobs[pick];if(j.attempts==0xffffffffU){free(next);return Error::invalid_state;}++j.attempts;j.state=State::running;memcpy(j.output_id,output,33);j.error[0]=j.pause_reason[0]=0;char id[33];memcpy(id,j.id,33);Error e=commit(next);if(e==Error::ok&&out)memcpy(out,id,33);return e;
    }
    Error finish(const char*id){return transition(id,State::completed,nullptr);}
    Error fail(const char*id,const char*code){if(!detail::code(code))return Error::invalid_argument;return transition(id,State::failed,code);}
    Error pause(const char*id,const char*reason){if(!detail::code(reason))return Error::invalid_argument;return transition(id,State::paused,reason);}
    Error resume(const char*id){return transition(id,State::running,nullptr);}
    // Call for active jobs only after the renderer has acknowledged cancellation.
    Error cancel(const char*id){return transition(id,State::cancelled,nullptr);}
    Error retry(const char*id){return transition(id,State::pending,nullptr);}
    Error remove(const char*id){if(!state_||blocked_)return Error::not_open;int i=index(id);if(i<0)return Error::not_found;if(active(state_->jobs[i]))return Error::busy;Store*next=clone();if(!next)return Error::io;for(size_t k=static_cast<size_t>(i)+1;k<next->count;++k)next->jobs[k-1]=next->jobs[k];--next->count;detail::reset_value(next->jobs[next->count]);return commit(next);}
    Error move(const char*id,size_t target){if(!state_||blocked_)return Error::not_open;int i=index(id);if(i<0)return Error::not_found;if(target>=state_->count)return Error::invalid_argument;if(state_->jobs[i].state!=State::pending)return Error::invalid_state;if(target==static_cast<size_t>(i))return Error::ok;Store*next=clone();if(!next)return Error::io;Job*saved=detail::allocate<Job>();if(!saved){storage_failed("allocate_store",12);free(next);return Error::io;}*saved=next->jobs[i];if(target<static_cast<size_t>(i))for(size_t k=static_cast<size_t>(i);k>target;--k)next->jobs[k]=next->jobs[k-1];else for(size_t k=static_cast<size_t>(i);k<target;++k)next->jobs[k]=next->jobs[k+1];next->jobs[target]=*saved;free(saved);return commit(next);}
private:
    // Keep the owned path/lock stable while the checked header advances to v3.
    // Old jobs migrate only on the next ordinary transactional mutation.
    static const char*filename(){return "queue-v1.bin";}
    static bool active(const Job&j){return j.state==State::running||j.state==State::paused;}
    int index(const char*id)const{if(!state_||!detail::hex(id,32))return -1;for(size_t i=0;i<state_->count;++i)if(!strcmp(id,state_->jobs[i].id))return static_cast<int>(i);return -1;}
    void clear_storage_error(){storage_stage_="none";storage_errno_=0;}
    void storage_failed(const char* stage,int number){storage_stage_=stage;storage_errno_=number>0&&number<=4095?number:0;}
    Store*clone(){clear_storage_error();Store*n=detail::allocate<Store>();if(n)*n=*state_;else storage_failed("allocate_store",12);return n;}
    bool new_id(char out[33]){for(unsigned attempt=0;attempt<8;++attempt){uint8_t raw[16];if(!random_(random_context_,raw,16))return false;static const char digits[]="0123456789abcdef";for(size_t i=0;i<16;++i){out[2*i]=digits[raw[i]>>4];out[2*i+1]=digits[raw[i]&15];}out[32]=0;bool unique=true;for(size_t i=0;i<state_->count;++i)if(!strcmp(out,state_->jobs[i].id)||!strcmp(out,state_->jobs[i].output_id))unique=false;if(unique)return true;}return false;}
    bool current(){int fd=::openat(directory_,filename(),detail::rd|detail::nofollow|detail::nonblock);if(fd<0)return !has_journal_&&detail::error_number()==2;struct stat s{};bool good=has_journal_&&detail::safe_file(fd,s)&&detail::same(identity_,s);::close(fd);return good;}
    Error commit(Store*next){
        if(!state_||blocked_){free(next);return Error::not_open;}if(!current()){free(next);return Error::changed_storage;}if(state_->generation==~uint64_t(0)){free(next);return Error::invalid_state;}next->generation=state_->generation+1;
        clear_storage_error();uint8_t*bytes=static_cast<uint8_t*>(malloc(max_wire_bytes));if(!bytes){storage_failed("allocate_wire",12);free(next);return Error::io;}memset(bytes,0,header_bytes);detail::Writer w{bytes+header_bytes,max_wire_bytes-header_bytes};for(size_t i=0;i<next->count;++i)detail::encode(w,next->jobs[i]);if(!w.ok){free(bytes);free(next);return Error::invalid_descriptor;}
        memcpy(bytes,"IDMPQ001",8);detail::put32(bytes+8,3);detail::put32(bytes+12,header_bytes);memcpy(bytes+16,profile_,64);detail::put64(bytes+80,next->generation);detail::put32(bytes+88,next->count);detail::put32(bytes+92,static_cast<uint32_t>(w.at));detail::put64(bytes+96,detail::checksum(bytes+header_bytes,w.at,detail::checksum(bytes,96)));size_t length=header_bytes+w.at;
        uint8_t nonce[16];if(!random_(random_context_,nonce,16)){free(bytes);free(next);return Error::random_failed;}char temp[64];static const char alphabet[]="0123456789abcdef";memcpy(temp,".queue-",7);for(size_t i=0;i<16;++i){temp[7+i*2]=alphabet[nonce[i]>>4];temp[8+i*2]=alphabet[nonce[i]&15];}memcpy(temp+39,".tmp",5);
        int fd=::openat(directory_,temp,detail::wr|detail::create|detail::exclusive|detail::nofollow,0600);struct stat owned{};bool created=false;
        if(fd<0)storage_failed("open_temp",detail::error_number());
        else if(::fstat(fd,&owned)!=0)storage_failed("stat_temp",detail::error_number());
        else created=true;
        size_t at=0;
        while(created&&at<length){long n=::write(fd,bytes+at,length-at);if(n<0&&detail::error_number()==4)continue;if(n<=0){storage_failed("write_temp",n<0?detail::error_number():0);break;}at+=static_cast<size_t>(n);}
        free(bytes);bool good=created&&at==length;struct stat ready{};
        if(good&&::fsync(fd)!=0){storage_failed("sync_temp",detail::error_number());good=false;}
        if(good&&::fstat(fd,&ready)!=0){storage_failed("validate_temp",detail::error_number());good=false;}
        if(good&&!detail::safe_file_stat(ready)){storage_failed("validate_temp",0);good=false;}
        if(fd>=0)::close(fd);
        Error result=Error::io;if(good&&!current())result=Error::changed_storage;
        else if(good){
            const int moved=has_journal_?::renameat(directory_,temp,directory_,filename()):detail::install_new(directory_,temp,filename());
            if(moved!=0){const int number=detail::error_number();storage_failed(has_journal_?"replace_journal":"install_new",number);if(!has_journal_&&number==17)result=Error::changed_storage;}
            else {
                int now=::openat(directory_,filename(),detail::rd|detail::nofollow|detail::nonblock);struct stat identity{};bool installed=false;
                if(now<0)storage_failed("validate_installed",detail::error_number());
                else if(::fstat(now,&identity)!=0)storage_failed("validate_installed",detail::error_number());
                else if(!detail::safe_file_stat(identity)||identity.st_dev!=ready.st_dev||identity.st_ino!=ready.st_ino)storage_failed("validate_installed",0);
                else installed=true;
                if(now>=0)::close(now);
                if(installed){free(state_);state_=next;next=nullptr;identity_=identity;has_journal_=true;if(::fsync(directory_)==0)result=Error::ok;else {storage_failed("sync_directory",detail::error_number());blocked_=true;result=Error::durability_uncertain;}}
                else {blocked_=true;result=Error::durability_uncertain;}
            }
        }
        if(created){int check=::openat(directory_,temp,detail::rd|detail::nofollow|detail::nonblock);struct stat s{};bool ours=check>=0&&::fstat(check,&s)==0&&s.st_dev==owned.st_dev&&s.st_ino==owned.st_ino;if(check>=0)::close(check);if(ours)::unlinkat(directory_,temp,0);}if(next)free(next);return result;
    }
    Error transition(const char*id,State target,const char*message){
        if(!state_||blocked_)return Error::not_open;
        int i=index(id);if(i<0)return Error::not_found;const State from=state_->jobs[i].state;bool valid=false;
        switch(target){case State::running:valid=from==State::paused;break;case State::paused:valid=from==State::running;break;
        case State::completed:case State::failed:valid=from==State::running||from==State::paused;break;
        case State::cancelled:valid=from==State::pending||from==State::running||from==State::paused;break;
        case State::pending:valid=from==State::failed||from==State::cancelled||from==State::interrupted;break;default:break;}
        if(!valid)return Error::invalid_state;
        Store*next=clone();if(!next)return Error::io;Job&j=next->jobs[i];j.state=target;j.error[0]=j.pause_reason[0]=0;if(target==State::pending)j.output_id[0]=0;if(target==State::failed)snprintf(j.error,65,"%s",message);if(target==State::paused)snprintf(j.pause_reason,65,"%s",message);return commit(next);
    }
    int directory_=-1,lock_=-1;Store*state_=nullptr;char profile_[65]{};struct stat identity_{};bool has_journal_=false,blocked_=false;Random random_;void*random_context_;
    const char* storage_stage_="none";int storage_errno_=0;
};
} // namespace idoly_mp4_queue
