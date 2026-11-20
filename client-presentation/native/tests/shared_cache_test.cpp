#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <pthread.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <ctime>
#include <dirent.h>
#include <string>
#include "../profile.hpp"

namespace pin=idoly::presentation::profile;
using Method=const void;
using VoidMethod=void (*)(void *,Method *);
using ObjectMethod=void *(*)(void *,Method *);
uintptr_t image_base=0;
template<class T>T read(void *object,size_t offset) {T value{};std::memcpy(&value,static_cast<char *>(object)+offset,sizeof value);return value;}
template<class T>void store(void *object,size_t offset,T value) {std::memcpy(static_cast<char *>(object)+offset,&value,sizeof value);}
#include "../shared_cache_hooks.hpp"

struct Class {const char *space,*name;};
Class item_class{"Octo.Data","Item"},bundle_class{"Octo.Loader","OctoAssetBundleLoader"},
    resource_class{"Octo.Loader","OctoResourceLoader"},settings_class{"Octo","OctoFullSettings"};
struct ManagedString {void *klass=nullptr,*monitor=nullptr;int32_t length=0;uint16_t text[2049]{};};
static_assert(offsetof(ManagedString,length)==0x10&&offsetof(ManagedString,text)==0x14);
ManagedString strings[16];size_t string_count=0;
ManagedString *text(const char *value) {
    assert(string_count<16);auto *result=&strings[string_count++];result->length=static_cast<int32_t>(std::strlen(value));
    assert(result->length<2049);for (int i=0;i<result->length;++i) result->text[i]=static_cast<unsigned char>(value[i]);return result;
}
alignas(8) unsigned char item[0x58]{};
void *handles[1024]{};uint32_t next_handle=1;unsigned retained=0,released=0,replayed=0;
pthread_t main_thread;
ManagedString *filename_string=nullptr,*bucket_string=nullptr;
std::string replayed_path;
bool expect_ready=true;
void *object_class(void *object) {return object?read<void *>(object,0):nullptr;}
const char *class_name(void *klass) {return static_cast<Class *>(klass)->name;}
const char *class_space(void *klass) {return static_cast<Class *>(klass)->space;}
uint32_t strong(void *object,bool pinned) {
    assert(pthread_equal(pthread_self(),main_thread)&&!pinned&&object&&next_handle<1024);
    handles[next_handle]=object;++retained;return next_handle++;
}
void *target(uint32_t handle) {assert(pthread_equal(pthread_self(),main_thread));return handles[handle];}
void release(uint32_t handle) {assert(pthread_equal(pthread_self(),main_thread)&&handles[handle]);handles[handle]=nullptr;++released;}
void *get_item(void *,void *,Method *) {return item;}
void *get_filename(void *,void *,Method *) {return filename_string;}
void *new_string(const char *value) {return text(value);}
uint8_t selected_mode=0;
void set_mode(void *,uint8_t mode,Method *) {selected_mode=mode;}
bool setup(void *,bool,Method *) {return true;}
int32_t original_cached(void *,void *,void *,void *,Method *) {return 0;}
void *original_path(void *,void *,void *,void *,Method *) {return nullptr;}
void update(void *,Method *) {}
void original_pre_download(void *loader,void *,void *callback,void *progress,bool auto_delete,Method *method) {
    assert(pthread_equal(pthread_self(),main_thread)&&loader&&callback&&!progress&&!auto_delete&&method==reinterpret_cast<Method *>(0x1234));
    if (!expect_ready) {++replayed;return;}
    assert(shared_is_cached_hook(nullptr,bucket_string,filename_string,item,nullptr)==3);
    void *path=shared_file_path_hook(nullptr,bucket_string,filename_string,item,nullptr);
    assert(path);auto *value=static_cast<ManagedString *>(path);replayed_path.clear();
    for (int i=0;i<value->length;++i) replayed_path.push_back(static_cast<char>(value->text[i]));
    ++replayed;
}
void configure_calls() {
    main_thread=pthread_self();shared_object_class=object_class;shared_class_name=class_name;shared_class_namespace=class_space;
    shared_strong_new=strong;shared_handle_get=target;shared_handle_free=release;shared_string_new=new_string;
    shared_bundle_item=get_item;shared_resource_item=get_item;shared_resource_filename=get_filename;
    shared_settings_set=set_mode;shared_setup_original=setup;shared_is_cached_original=original_cached;
    shared_file_path_original=original_path;shared_pre_download_original=original_pre_download;shared_downloader_update_original=update;
    shared_hooks_ready.store(true);
}
sc::Key key() {
    sc::Key result;result.kind=2;result.upload=102050;result.generation=1234567;result.size=13;
    std::memcpy(result.object,"AbC123",6);for (unsigned i=0;i<16;++i) result.md5[i]=static_cast<uint8_t>(i);
    std::strcpy(result.filename,"000102030405060708090a0b0c0d0e0f.mp4");return result;
}
void unit_tests() {
    auto value=key();assert(value.valid());uint8_t token[16]{},packet[sc::request_size+64]{};
    assert(sc::encode_request(packet,2,value,token,19,value.filename,std::strlen(value.filename)));
    assert(!std::memcmp(packet,"IDRSREQ1",8)&&packet[10]==2&&packet[11]==2&&sc::get(packet+28,8)==19);
    assert(sc::get(packet+36,4)==102050&&sc::get(packet+40,8)==1234567&&sc::get(packet+48,8)==13);
    assert(!sc::encode_request(packet,1,value,token,9007199254740992ull,value.filename,std::strlen(value.filename)));
    assert(!sc::filename_valid("000102030405060708090a0b0c0d0e0f.MP4",36,value));
    value.upload=0x80000000u;assert(!value.valid());value=key();
    static sc::Index index;sc::Receipt receipt;receipt.device=1;receipt.inode=2;receipt.size=value.size;receipt.mode=0100400;receipt.links=1;
    std::strcpy(receipt.path,"/private/session/views/view-one/RAbC123/000102030405060708090a0b0c0d0e0f.mp4");
    assert(index.insert(1,value,receipt));sc::Receipt result;assert(index.find(1,value,result));assert(!std::strcmp(receipt.path,result.path));
    auto other=value;std::strcpy(other.filename,"000102030405060708090a0b0c0d0e0f.mp3");assert(!index.find(1,other,result));
    assert(!index.find(2,value,result)&&index.find(2,value,result,true));
    // The first advertised path survives a full table and rejected admission.
    for (size_t i=1;i<sc::cache_limit;++i) {other=value;other.generation+=i;assert(index.insert(1,other,receipt));}
    other.generation+=sc::cache_limit;assert(!index.insert(1,other,receipt));assert(index.find(1,value,result));
    uint8_t response[sc::response_size+sc::max_path]{};std::memcpy(response,"IDRSRSP1",8);sc::put(response+8,1,2);response[11]=1;
    std::memcpy(response+12,token,16);sc::put(response+28,19,8);std::memcpy(response+36,value.md5,16);sc::put(response+52,value.size,8);
    sc::put(response+60,1,8);sc::put(response+68,2,8);sc::put(response+92,0100400,4);sc::put(response+96,1,4);
    auto response_path="/private/session/views/one/RAbC123/000102030405060708090a0b0c0d0e0f.mp4";
    auto length=std::strlen(response_path);sc::put(response+100,length,2);std::memcpy(response+104,response_path,length);
    assert(sc::decode_response(response,104+length,token,19,value,"/private/session",result));
    assert(!sc::decode_response(response,104+length,token,20,value,"/private/session",result));
    response[96]=2;assert(!sc::decode_response(response,104+length,token,19,value,"/private/session",result));response[96]=1;
    response[102]=1;assert(!sc::decode_response(response,104+length,token,19,value,"/private/session",result));
    assert(!sc::decode_response(response,104+length,token,19,value,"/private/other",result));
    assert(sizeof(sc::Index)<3*1024*1024);
    response[102]=0;
    for (size_t position:{size_t{0},size_t{8},size_t{10},size_t{11},size_t{12},size_t{28},size_t{36},size_t{52},size_t{96},size_t{100},size_t{102}}) {
        response[position]^=1;
        assert(!sc::decode_response(response,104+length,token,19,value,"/private/session",result));
        response[position]^=1;
    }
    char filename[]="/tmp/idoly-shared-stamp-XXXXXX";int fd=mkstemp(filename);assert(fd>=0);
    assert(::write(fd,"raw-payload",11)==11&&!fchmod(fd,0400));struct stat info{};assert(!fstat(fd,&info));close(fd);
    sc::Receipt stamp;stamp.device=info.st_dev;stamp.inode=info.st_ino;stamp.size=info.st_size;stamp.mode=info.st_mode;stamp.links=info.st_nlink;
    stamp.modified_ns=info.st_mtim.tv_sec*1000000000ll+info.st_mtim.tv_nsec;
    stamp.changed_ns=info.st_ctim.tv_sec*1000000000ll+info.st_ctim.tv_nsec;std::strcpy(stamp.path,filename);
    assert(shared_stamp_matches(stamp));
    std::string alias=std::string(filename)+"-hardlink";assert(!link(filename,alias.c_str()));assert(!shared_stamp_matches(stamp));
    assert(!unlink(alias.c_str()));assert(!chmod(filename,0600));assert(!shared_stamp_matches(stamp));assert(!unlink(filename));

    // A server epoch change releases captured arguments only when Unity drains
    // the completed fallback; the worker never touches a managed handle.
    configure_calls();expect_ready=false;
    char directory[]="/tmp/idoly-native-epoch-XXXXXX";assert(mkdtemp(directory));
    std::string requests=std::string(directory)+"/req",responses=std::string(directory)+"/rsp";
    assert(!mkdir(requests.c_str(),0700)&&!mkdir(responses.c_str(),0700));
    std::string active=std::string(directory)+"/active";
    fd=open(active.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);uint8_t marker[16]{};
    std::memcpy(marker,"IDRSACT1",8);sc::put(marker+8,41,8);assert(::write(fd,marker,16)==16);close(fd);
    assert(shared_configure(directory,41));
    store<void *>(item,0,&item_class);store<uint32_t>(item,0x50,value.upload);store<uint64_t>(item,0x48,value.generation);
    store<int32_t>(item,0x28,static_cast<int32_t>(value.size));std::memcpy(item+0x20,value.object,6);std::memcpy(item+0x30,value.md5,16);
    struct {Class *klass;} loader{&resource_class},settings{&settings_class};
    filename_string=text(value.filename);bucket_string=text("RAbC123");
    assert(shared_setup_hook(&settings,false,nullptr)&&selected_mode==2);
    shared_pre_download_hook(&loader,text("synthetic"),&settings,nullptr,false,reinterpret_cast<Method *>(0x1234));
    assert(retained==3&&released==0&&replayed==0);
    assert(shared_configure(directory,41));assert(released==0&&replayed==0);
    pthread_mutex_lock(&shared_mutex);assert(shared_pending[0].stage!=sc::Stage::complete);pthread_mutex_unlock(&shared_mutex);
    assert(shared_configure(directory,42));assert(released==0&&replayed==0);
    shared_downloader_update_hook(nullptr,nullptr);assert(released==3&&replayed==1&&shared_fallback==1);
    assert(!unlink(active.c_str()));
    shared_pre_download_hook(&loader,text("stopped_broker"),&settings,nullptr,false,reinterpret_cast<Method *>(0x1234));
    const uint64_t begun=shared_clock_ms();
    while (replayed<2&&shared_clock_ms()-begun<1000) {shared_downloader_update_hook(nullptr,nullptr);timespec tick{0,10000000};nanosleep(&tick,nullptr);}
    assert(replayed==2&&retained==6&&released==6);
    // Requests may already be atomically published; remove only this fixture's
    // files after draining, leaving no test directories behind.
    timespec pause{0,50000000};nanosleep(&pause,nullptr);
    for (auto path:{requests,responses}) {DIR *dir=opendir(path.c_str());assert(dir);while (auto *entry=readdir(dir)) if (entry->d_name[0]!='.') unlink((path+"/"+entry->d_name).c_str());closedir(dir);}
    assert(!rmdir(requests.c_str())&&!rmdir(responses.c_str())&&!rmdir(directory));
}
int main(int argc,char **argv) {
    if (argc==1) {unit_tests();return 0;}
    if (argc!=11||std::strcmp(argv[1],"--ipc")) return 2;
    configure_calls();const uint64_t epoch=std::strtoull(argv[3],nullptr,10);sc::Key value;
    value.kind=static_cast<uint8_t>(std::strtoul(argv[4],nullptr,10));value.upload=static_cast<uint32_t>(std::strtoul(argv[5],nullptr,10));
    value.generation=std::strtoull(argv[6],nullptr,10);value.size=std::strtoull(argv[7],nullptr,10);
    assert(std::strlen(argv[8])==6&&std::strlen(argv[9])==32);std::memcpy(value.object,argv[8],6);
    for (unsigned i=0;i<16;++i) {char pair[3]={argv[9][i*2],argv[9][i*2+1],0};value.md5[i]=static_cast<uint8_t>(std::strtoul(pair,nullptr,16));}
    assert(std::strlen(argv[10])<=sc::max_filename);std::strcpy(value.filename,argv[10]);
    store<void *>(item,0,&item_class);store<uint32_t>(item,0x50,value.upload);store<uint64_t>(item,0x48,value.generation);
    store<int32_t>(item,0x28,static_cast<int32_t>(value.size));std::memcpy(item+0x20,value.object,6);std::memcpy(item+0x30,value.md5,16);
    char bucket[8]{};bucket[0]=value.kind==1?'A':'R';std::memcpy(bucket+1,value.object,6);bucket_string=text(bucket);filename_string=text(value.filename);
    struct {Class *klass;} loader{value.kind==1?&bundle_class:&resource_class},settings{&settings_class};
    assert(shared_configure(argv[2],epoch));assert(shared_setup_hook(&settings,false,nullptr)&&selected_mode==2);
    shared_pre_download_hook(&loader,text("synthetic_name"),&settings,nullptr,false,reinterpret_cast<Method *>(0x1234));
    assert(replayed==0&&retained==3&&released==0);
    const uint64_t start=shared_clock_ms();
    while (!replayed&&shared_clock_ms()-start<15000) {shared_downloader_update_hook(nullptr,nullptr);timespec pause{0,10000000};nanosleep(&pause,nullptr);}
    if (replayed!=1||retained!=released||replayed_path.empty()) return 3;
    struct stat info{};assert(!stat(replayed_path.c_str(),&info));
    std::printf("{\"status\":\"ready\",\"path\":\"%s\",\"device\":%llu,\"inode\":%llu,\"replayed\":%u,\"handles_released\":%u}\n",
        replayed_path.c_str(),static_cast<unsigned long long>(info.st_dev),static_cast<unsigned long long>(info.st_ino),replayed,released);
    return 0;
}
