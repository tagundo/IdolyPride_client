#pragma once
#include "shared_cache_core.hpp"

// Included inside bridge.cpp's private namespace, after the generic read helper.
namespace sc = idoly::presentation::shared_cache;
pthread_mutex_t shared_mutex=PTHREAD_MUTEX_INITIALIZER;
sc::Index shared_index;
sc::Pending shared_pending[sc::pending_limit];
char shared_directory[769]{};
uint64_t shared_epoch=0,shared_queued=0,shared_prepared=0,shared_replayed=0,shared_fallback=0,shared_hits=0,shared_capacity_fallback=0;
int shared_root_directory=-1,shared_request_directory=-1,shared_response_directory=-1;
std::atomic<bool> shared_hooks_ready{false},shared_mode_ready{false},shared_worker_started{false};
std::atomic<uintptr_t> shared_thread{0};
uintptr_t shared_image_base=0;
bool (*shared_setup_original)(void *,bool,Method *);
int32_t (*shared_is_cached_original)(void *,void *,void *,void *,Method *);
void *(*shared_file_path_original)(void *,void *,void *,void *,Method *);
void (*shared_pre_download_original)(void *,void *,void *,void *,bool,Method *);
VoidMethod shared_downloader_update_original;
void (*shared_settings_set)(void *,uint8_t,Method *);
void *(*shared_bundle_item)(void *,void *,Method *);
void *(*shared_resource_item)(void *,void *,Method *);
void *(*shared_resource_filename)(void *,void *,Method *);
void *(*shared_string_new)(const char *);
uint32_t (*shared_strong_new)(void *,bool);
void *(*shared_handle_get)(uint32_t);
void (*shared_handle_free)(uint32_t);
void *(*shared_object_class)(void *);
const char *(*shared_class_name)(void *);
const char *(*shared_class_namespace)(void *);

#ifdef IDOLY_DARWIN_BRIDGE
inline constexpr int shared_rdonly=0,shared_wronly=1,shared_nonblock=4,shared_create=0x200,
    shared_exclusive=0x800,shared_directory_flag=0x100000,shared_no_follow=0x100,shared_cloexec=0x1000000;
#else
inline constexpr int shared_rdonly=O_RDONLY,shared_wronly=O_WRONLY,shared_nonblock=O_NONBLOCK,
    shared_create=O_CREAT,shared_exclusive=O_EXCL,shared_directory_flag=O_DIRECTORY,
    shared_no_follow=O_NOFOLLOW,shared_cloexec=O_CLOEXEC;
#endif
uint64_t shared_clock_ms() {
    timespec value{};
#ifdef IDOLY_DARWIN_BRIDGE
    if (clock_gettime(6,&value)) return 0;
#else
    if (clock_gettime(CLOCK_MONOTONIC,&value)) return 0;
#endif
    return static_cast<uint64_t>(value.tv_sec)*1000+static_cast<uint64_t>(value.tv_nsec)/1000000;
}
uintptr_t shared_current_thread() {
#ifdef IDOLY_DARWIN_BRIDGE
    return reinterpret_cast<uintptr_t>(pthread_self());
#else
    return static_cast<uintptr_t>(pthread_self());
#endif
}
bool shared_game_thread() { return shared_thread.load(std::memory_order_acquire)==shared_current_thread(); }
bool shared_class_is(void *object,const char *space,const char *name) {
    if (!object||!shared_object_class) return false;
    void *klass=shared_object_class(object);if (!klass) return false;
    const char *actual_name=shared_class_name(klass),*actual_space=shared_class_namespace(klass);
    return actual_name&&actual_space&&!std::strcmp(actual_name,name)&&!std::strcmp(actual_space,space);
}
bool shared_ascii(void *string,char *output,size_t capacity) {
    if (!string||!output||capacity<2) return false;
    const int32_t length=read<int32_t>(string,0x10);
    if (length<=0||static_cast<size_t>(length)>=capacity) return false;
    for (int32_t i=0;i<length;++i) {
        const uint16_t c=read<uint16_t>(string,0x14+static_cast<size_t>(i)*2);
        if (c<33||c>126) return false;
        output[i]=static_cast<char>(c);
    }
    output[length]=0;return true;
}
bool shared_item_key(void *item,uint8_t kind,sc::Key &key) {
    if (!shared_class_is(item,"Octo.Data","Item")) return false;
    key.kind=kind;key.upload=read<uint32_t>(item,0x50);key.generation=read<uint64_t>(item,0x48);
    const int32_t size=read<int32_t>(item,0x28);if (size<=0) return false;key.size=static_cast<uint32_t>(size);
    std::memcpy(key.object,static_cast<const char *>(item)+0x20,6);
    std::memcpy(key.md5,static_cast<const char *>(item)+0x30,16);return key.valid();
}
bool shared_request_identity(void *bucket,void *filename,void *item,sc::Key &key) {
    char sdk_bucket[8],sdk_file[sc::max_filename+1];
    if (!shared_ascii(bucket,sdk_bucket,sizeof sdk_bucket)||std::strlen(sdk_bucket)!=7
            ||(sdk_bucket[0]!='A'&&sdk_bucket[0]!='R')
            ||!shared_item_key(item,sdk_bucket[0]=='A'?1:2,key)
            ||std::memcmp(sdk_bucket+1,key.object,6)||!shared_ascii(filename,sdk_file,sizeof sdk_file)) return false;
    if (!sc::filename_valid(sdk_file,std::strlen(sdk_file),key)) return false;
    std::memcpy(key.filename,sdk_file,sizeof sdk_file);return true;
}
bool shared_stamp_matches(const sc::Receipt &receipt) {
    // Follow the deliberately named private view, then inspect the actual raw
    // inode. No read, hash, Python/GIL or network operation occurs on Unity.
    const int fd=open(receipt.path,shared_rdonly|shared_nonblock|shared_cloexec);
    if (fd<0) return false;
    struct stat info{};const bool read_ok=fstat(fd,&info)==0;close(fd);
    if (!read_ok) return false;
#ifdef IDOLY_DARWIN_BRIDGE
    const int64_t modified=info.st_mtimespec.tv_sec*1000000000ll+info.st_mtimespec.tv_nsec;
    const int64_t changed=info.st_ctimespec.tv_sec*1000000000ll+info.st_ctimespec.tv_nsec;
#else
    const int64_t modified=info.st_mtim.tv_sec*1000000000ll+info.st_mtim.tv_nsec;
    const int64_t changed=info.st_ctim.tv_sec*1000000000ll+info.st_ctim.tv_nsec;
#endif
    return static_cast<uint64_t>(info.st_dev)==receipt.device&&static_cast<uint64_t>(info.st_ino)==receipt.inode
        &&static_cast<uint64_t>(info.st_size)==receipt.size&&static_cast<uint32_t>(info.st_mode)==receipt.mode
        &&static_cast<uint32_t>(info.st_nlink)==receipt.links&&receipt.links==1
        &&(receipt.mode&0170000u)==0100000u&&!(receipt.mode&0222u)
        &&modified==receipt.modified_ns&&changed==receipt.changed_ns;
}
bool shared_lookup(const sc::Key &key,sc::Receipt &receipt,bool continuation=false) {
    pthread_mutex_lock(&shared_mutex);
    const bool found=shared_epoch&&(shared_index.find(shared_epoch,key,receipt)
        ||(continuation&&shared_index.find(shared_epoch,key,receipt,true)));
    pthread_mutex_unlock(&shared_mutex);
    if (!found||!shared_stamp_matches(receipt)) return false;
    pthread_mutex_lock(&shared_mutex);++shared_hits;pthread_mutex_unlock(&shared_mutex);return true;
}
bool shared_private_directory(int fd) {
    struct stat info{};
    return fd>=0&&!fstat(fd,&info)&&(info.st_mode&0170000u)==0040000u
        &&!(info.st_mode&077u)&&info.st_uid==geteuid();
}
bool shared_broker_active(int directory,uint64_t epoch) {
    if (directory<0) return false;
    const int fd=openat(directory,"active",shared_rdonly|shared_no_follow|shared_nonblock|shared_cloexec);
    if (fd<0) return false;
    struct stat info{};uint8_t marker[17]{};
    const bool metadata=!fstat(fd,&info)&&(info.st_mode&0170000u)==0100000u
        &&(info.st_mode&0777u)==0600u&&info.st_nlink==1&&info.st_uid==geteuid()&&info.st_size==16;
    const long count=metadata?::read(fd,marker,sizeof marker):-1;close(fd);
    return count==16&&!std::memcmp(marker,"IDRSACT1",8)&&sc::get(marker+8,8)==epoch;
}
bool shared_write_request(int directory,const sc::Pending &job) {
    uint8_t packet[sc::request_size+sc::max_filename];
#ifdef IDOLY_DARWIN_BRIDGE
    constexpr uint8_t platform=2;
#else
    constexpr uint8_t platform=1;
#endif
    const size_t filename_length=std::strlen(job.filename);
    if (!sc::encode_request(packet,platform,job.key,job.token,job.epoch,job.filename,filename_length)) return false;
    char temporary[48],final[48];std::snprintf(temporary,sizeof temporary,"%s.tmp",job.basename);
    std::snprintf(final,sizeof final,"%s.req",job.basename);
    const int fd=openat(directory,temporary,shared_wronly|shared_create|shared_exclusive|shared_no_follow|shared_cloexec,0600);
    if (fd<0) return false;
    const size_t size=sc::request_size+filename_length;
    size_t used=0;bool okay=true;
    while (used<size) { const long n=::write(fd,packet+used,size-used);if (n<=0) {okay=false;break;}used+=static_cast<size_t>(n); }
    if (okay) okay=fsync(fd)==0;
    close(fd);
    if (okay) okay=renameat(directory,temporary,directory,final)==0;
    if (!okay) unlinkat(directory,temporary,0);
    return okay;
}
bool shared_response_tail(const sc::Receipt &receipt,const sc::Pending &job) {
    char tail[sc::max_filename+10];std::snprintf(tail,sizeof tail,"/%c%.6s/%s",job.key.kind==1?'A':'R',job.key.object,job.filename);
    const size_t length=std::strlen(receipt.path),ending=std::strlen(tail);
    return length>ending&&!std::strcmp(receipt.path+length-ending,tail);
}
// 0 absent, 1 valid ready, -1 terminal failure. Only worker calls this.
int shared_read_response(int directory,const sc::Pending &job,const char *session,sc::Receipt &receipt) {
    char filename[48];std::snprintf(filename,sizeof filename,"%s.rsp",job.basename);
    const int fd=openat(directory,filename,shared_rdonly|shared_no_follow|shared_nonblock|shared_cloexec);
    if (fd<0) return 0;
    struct stat info{};
    if (fstat(fd,&info)||(info.st_mode&0170000u)!=0100000u||(info.st_mode&0777u)!=0600u
            ||info.st_nlink!=1||info.st_uid!=geteuid()||info.st_size<static_cast<int64_t>(sc::response_size)
            ||static_cast<uint64_t>(info.st_size)>sc::response_size+sc::max_path) {
        close(fd);unlinkat(directory,filename,0);return -1;
    }
    uint8_t packet[sc::response_size+sc::max_path+1];size_t used=0;bool okay=true;
    for (;;) {
        const long n=::read(fd,packet+used,sizeof packet-used);
        if (n==0) break;
        if (n<0) {okay=false;break;}
        used+=static_cast<size_t>(n);
        if (used==sizeof packet) {okay=false;break;}
    }
    close(fd);unlinkat(directory,filename,0);
    return okay&&sc::decode_response(packet,used,job.token,job.epoch,job.key,session,receipt)
        &&shared_response_tail(receipt,job)&&shared_stamp_matches(receipt)?1:-1;
}
void *shared_worker(void *) {
    for (;;) {
        int root=-1,request=-1,response=-1;uint64_t epoch=0;char directory[sizeof shared_directory]{};bool pending_work=false;
        pthread_mutex_lock(&shared_mutex);
        epoch=shared_epoch;
        for (const auto &slot:shared_pending) if (slot.stage==sc::Stage::queued||slot.stage==sc::Stage::waiting) {pending_work=true;break;}
        if (pending_work) {
            if (shared_root_directory>=0) root=dup(shared_root_directory);
            if (shared_request_directory>=0) request=dup(shared_request_directory);
            if (shared_response_directory>=0) response=dup(shared_response_directory);
            std::memcpy(directory,shared_directory,sizeof directory);
            if (root<0||request<0||response<0) for (auto &slot:shared_pending)
                if (slot.epoch==epoch&&(slot.stage==sc::Stage::queued||slot.stage==sc::Stage::waiting)) slot.stage=sc::Stage::complete;
        }
        pthread_mutex_unlock(&shared_mutex);
        const bool live=pending_work&&shared_broker_active(root,epoch);
        if (request>=0&&response>=0) for (size_t index=0;index<sc::pending_limit;++index) {
            sc::Pending job;bool submit=false,waiting=false;
            pthread_mutex_lock(&shared_mutex);
            auto &slot=shared_pending[index];
            if (slot.epoch==epoch&&slot.stage==sc::Stage::queued) {
                arc4random_buf(slot.token,16);constexpr char hex[]="0123456789abcdef";
                for (size_t j=0;j<16;++j) {slot.basename[j*2]=hex[slot.token[j]>>4];slot.basename[j*2+1]=hex[slot.token[j]&15];}
                slot.basename[32]=0;slot.started_ms=shared_clock_ms();slot.stage=sc::Stage::waiting;submit=true;
            }
            waiting=slot.epoch==epoch&&slot.stage==sc::Stage::waiting;if (waiting) job=slot;
            pthread_mutex_unlock(&shared_mutex);
            if (!waiting) continue;
            sc::Receipt receipt;int result=0;
            if (!live) result=-1;
            else if (submit&&!shared_write_request(request,job)) result=-1;
            else result=shared_read_response(response,job,directory,receipt);
            const uint64_t now=shared_clock_ms();
            if (!result&&(!now||!job.started_ms||now-job.started_ms>300000)) result=-1;
            if (!result) continue;
            pthread_mutex_lock(&shared_mutex);
            if (slot.stage==sc::Stage::waiting&&slot.epoch==epoch&&!std::memcmp(slot.token,job.token,16)) {
                slot.prepared=result==1&&shared_index.insert(epoch,slot.key,receipt);
                if (result==1&&!slot.prepared) ++shared_capacity_fallback;
                if (slot.prepared) ++shared_prepared;
                slot.stage=sc::Stage::complete;
            }
            pthread_mutex_unlock(&shared_mutex);
        }
        if (request>=0) close(request);
        if (response>=0) close(response);
        if (root>=0) close(root);
        timespec pause{0,pending_work?20000000:100000000};nanosleep(&pause,nullptr);
    }
    return nullptr;
}
bool shared_configure(const char *directory,uint64_t epoch) {
    if (!directory||directory[0]!='/'||!epoch||epoch>9007199254740991ull) return false;
    size_t count=0;while (directory[count]&&count<sizeof shared_directory) ++count;
    if (count<2||count>=sizeof shared_directory||directory[count-1]=='/') return false;
    for (size_t i=0;i<count;++i) if (directory[i]=='\n'||directory[i]=='\r'||directory[i]=='\\') return false;
    const int root=open(directory,shared_rdonly|shared_directory_flag|shared_no_follow|shared_cloexec);
    if (!shared_private_directory(root)) {if (root>=0) close(root);return false;}
    const int requests=openat(root,"req",shared_rdonly|shared_directory_flag|shared_no_follow|shared_cloexec);
    const int responses=openat(root,"rsp",shared_rdonly|shared_directory_flag|shared_no_follow|shared_cloexec);
    if (!shared_private_directory(requests)||!shared_private_directory(responses)) {
        if (requests>=0) close(requests);
        if (responses>=0) close(responses);
        close(root);
        return false;
    }
    pthread_mutex_lock(&shared_mutex);
    if (shared_epoch==epoch&&!std::strcmp(shared_directory,directory)
            &&shared_worker_started.load(std::memory_order_acquire)) {
        pthread_mutex_unlock(&shared_mutex);close(requests);close(responses);close(root);return true;
    }
    if (shared_root_directory>=0) close(shared_root_directory);
    if (shared_request_directory>=0) close(shared_request_directory);
    if (shared_response_directory>=0) close(shared_response_directory);
    shared_root_directory=root;shared_request_directory=requests;shared_response_directory=responses;shared_epoch=epoch;
    std::memcpy(shared_directory,directory,count+1);
    for (auto &slot:shared_pending) if (slot.stage!=sc::Stage::empty) {slot.prepared=false;slot.stage=sc::Stage::complete;}
    pthread_mutex_unlock(&shared_mutex);
    if (!shared_worker_started.exchange(true)) {
        pthread_t worker;
        if (pthread_create(&worker,nullptr,shared_worker,nullptr)) {shared_worker_started.store(false);return false;}
        pthread_detach(worker);
    }
    return true;
}
void shared_cache_load_calls() {
    shared_image_base=image_base;
#define SHARED_BIND(variable,entry) variable=reinterpret_cast<decltype(variable)>(shared_image_base+pin::entry.rva)
    SHARED_BIND(shared_settings_set,shared_settings_set);SHARED_BIND(shared_bundle_item,shared_bundle_item);
    SHARED_BIND(shared_resource_item,shared_resource_item);SHARED_BIND(shared_resource_filename,shared_resource_filename);
    SHARED_BIND(shared_string_new,shared_string_new);SHARED_BIND(shared_strong_new,font_strong);
    SHARED_BIND(shared_handle_get,weak_get);SHARED_BIND(shared_handle_free,weak_free);
    SHARED_BIND(shared_object_class,object_class);SHARED_BIND(shared_class_name,class_name);SHARED_BIND(shared_class_namespace,class_namespace);
#undef SHARED_BIND
}
bool shared_setup_hook(void *settings,bool reset,Method *method) {
    pthread_mutex_lock(&shared_mutex);const bool configured=shared_epoch!=0;pthread_mutex_unlock(&shared_mutex);
    const bool enable=configured&&shared_worker_started.load(std::memory_order_acquire)
        &&shared_hooks_ready.load(std::memory_order_acquire)
        &&shared_class_is(settings,"Octo","OctoFullSettings");
    if (enable) {shared_thread.store(shared_current_thread(),std::memory_order_release);shared_settings_set(settings,2,nullptr);}
    const bool result=shared_setup_original(settings,reset,method);
    shared_mode_ready.store(enable&&result,std::memory_order_release);return result;
}
int32_t shared_is_cached_hook(void *self,void *bucket,void *filename,void *item,Method *method) {
    sc::Key key;sc::Receipt receipt;
    if (shared_mode_ready.load(std::memory_order_acquire)&&shared_game_thread()
            &&shared_request_identity(bucket,filename,item,key)&&shared_lookup(key,receipt)) return 3;
    return shared_is_cached_original(self,bucket,filename,item,method);
}
void *shared_file_path_hook(void *self,void *bucket,void *filename,void *item,Method *method) {
    sc::Key key;sc::Receipt receipt;
    if (shared_mode_ready.load(std::memory_order_acquire)&&shared_game_thread()
            &&shared_request_identity(bucket,filename,item,key)&&shared_lookup(key,receipt,true)) return shared_string_new(receipt.path);
    return shared_file_path_original(self,bucket,filename,item,method);
}
void shared_release(const sc::Arguments &arguments) {
    const uint32_t handles[]={arguments.loader,arguments.name,arguments.complete,arguments.progress};
    for (uint32_t handle:handles) if (handle) shared_handle_free(handle);
}
void shared_pre_download_hook(void *loader,void *name,void *complete,void *progress,bool auto_delete,Method *method) {
    if (!shared_mode_ready.load(std::memory_order_acquire)||!shared_game_thread()||!loader||!name||!complete) {
        shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;
    }
    uint8_t kind=0;void *item=nullptr;
    if (shared_class_is(loader,"Octo.Loader","OctoAssetBundleLoader")) {kind=1;item=shared_bundle_item(loader,name,nullptr);}
    else if (shared_class_is(loader,"Octo.Loader","OctoResourceLoader")) {kind=2;item=shared_resource_item(loader,name,nullptr);}
    sc::Key key;sc::Receipt receipt;char filename[sc::max_filename+1]{};
    if (!kind||!shared_item_key(item,kind,key)) {shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;}
    if (kind==1) {
        constexpr char hex[]="0123456789abcdef";
        for (size_t i=0;i<16;++i) {filename[i*2]=hex[key.md5[i]>>4];filename[i*2+1]=hex[key.md5[i]&15];}
    } else if (!shared_ascii(shared_resource_filename(loader,item,nullptr),filename,sizeof filename)) {
        shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;
    }
    if (!sc::filename_valid(filename,std::strlen(filename),key)) {shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;}
    std::memcpy(key.filename,filename,sizeof filename);
    if (shared_lookup(key,receipt)) {shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;}
    sc::Arguments arguments;
    arguments.loader=shared_strong_new(loader,false);arguments.name=shared_strong_new(name,false);
    arguments.complete=shared_strong_new(complete,false);arguments.progress=progress?shared_strong_new(progress,false):0;
    arguments.method=method;arguments.auto_delete=auto_delete;
    if (!arguments.loader||!arguments.name||!arguments.complete||(progress&&!arguments.progress)) {
        shared_release(arguments);shared_pre_download_original(loader,name,complete,progress,auto_delete,method);return;
    }
    bool queued=false;
    pthread_mutex_lock(&shared_mutex);
    if (shared_epoch&&shared_worker_started.load(std::memory_order_acquire)) for (auto &slot:shared_pending) if (slot.stage==sc::Stage::empty) {
        slot={};slot.key=key;slot.arguments=arguments;slot.epoch=shared_epoch;
        std::memcpy(slot.filename,filename,sizeof filename);slot.stage=sc::Stage::queued;++shared_queued;queued=true;break;
    }
    if (!queued) ++shared_capacity_fallback;
    pthread_mutex_unlock(&shared_mutex);
    if (!queued) {shared_release(arguments);shared_pre_download_original(loader,name,complete,progress,auto_delete,method);}
}
void shared_downloader_update_hook(void *self,Method *method) {
    shared_downloader_update_original(self,method);
    if (!shared_game_thread()) return;
    for (unsigned budget=0;budget<8;++budget) {
        sc::Pending job;bool found=false;
        pthread_mutex_lock(&shared_mutex);
        for (auto &slot:shared_pending) if (slot.stage==sc::Stage::complete) {job=slot;slot={};found=true;break;}
        if (found) {++shared_replayed;if (!job.prepared||job.epoch!=shared_epoch) ++shared_fallback;}
        pthread_mutex_unlock(&shared_mutex);if (!found) break;
        void *loader=shared_handle_get(job.arguments.loader),*name=shared_handle_get(job.arguments.name);
        void *complete=shared_handle_get(job.arguments.complete),*progress=job.arguments.progress?shared_handle_get(job.arguments.progress):nullptr;
        // A strong handle remains valid through synchronous callbacks/re-entry.
        // On errors or epoch changes the exact original SDK fallback is used.
        try {shared_pre_download_original(loader,name,complete,progress,job.arguments.auto_delete,job.arguments.method);}
        catch (...) {shared_release(job.arguments);throw;}
        shared_release(job.arguments);
    }
}
size_t shared_status_json(char *output,size_t capacity) {
    if (!output||!capacity) return 0;
    pthread_mutex_lock(&shared_mutex);size_t active=0;
    for (const auto &slot:shared_pending) if (slot.stage!=sc::Stage::empty) ++active;
    const int length=std::snprintf(output,capacity,
        "{\"schema\":1,\"hooks_ready\":%s,\"configured\":%s,\"direct_reads\":%s,\"epoch\":%llu,"
        "\"queued\":%llu,\"prepared\":%llu,\"replayed\":%llu,\"fallbacks\":%llu,\"hits\":%llu,\"pending\":%llu,"
        "\"capacity_fallbacks\":%llu,\"index_entries\":%llu,\"index_limit\":8192,\"session_prefix_limit\":32,\"pending_limit\":64}",
        shared_hooks_ready.load(std::memory_order_acquire)?"true":"false",shared_epoch?"true":"false",
        shared_mode_ready.load(std::memory_order_acquire)?"true":"false",static_cast<unsigned long long>(shared_epoch),
        static_cast<unsigned long long>(shared_queued),static_cast<unsigned long long>(shared_prepared),
        static_cast<unsigned long long>(shared_replayed),static_cast<unsigned long long>(shared_fallback),
        static_cast<unsigned long long>(shared_hits),static_cast<unsigned long long>(active),
        static_cast<unsigned long long>(shared_capacity_fallback),static_cast<unsigned long long>(shared_index.entry_count));
    pthread_mutex_unlock(&shared_mutex);
    return length>=0&&static_cast<size_t>(length)<capacity?static_cast<size_t>(length):0;
}
