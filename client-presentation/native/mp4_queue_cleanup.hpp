// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Retirement of journal-associated temporary outputs. The caller must hold
// the queue's exclusive ownership and pass an inactive, validated output ID.
#include "mp4_queue.hpp"

namespace idoly_mp4_queue_cleanup {
enum class Result {ok,deferred,invalid_argument,final_deferred};
struct Report {uint32_t removed=0,missing=0,deferred=0;};
inline const char*error_code(Result result) {
    switch(result){case Result::ok:return "none";case Result::invalid_argument:return "queue_temporary_cleanup_invalid";
        case Result::final_deferred:return "queue_final_cleanup_deferred";
        default:return "queue_temporary_cleanup_deferred";}
}
namespace detail {
inline bool private_directory(int fd) {
    struct stat s{};return fd>=0&&::fstat(fd,&s)==0&&(s.st_mode&0170000)==0040000
        &&(s.st_mode&07777)==0700&&s.st_uid==geteuid();
}
inline bool temporary(int fd,struct stat& s) {
    return fd>=0&&::fstat(fd,&s)==0&&(s.st_mode&0170000)==0100000
        &&(s.st_mode&07777)==0600&&s.st_uid==geteuid()&&s.st_nlink==1&&s.st_size>=0;
}
inline bool unchanged(const struct stat&a,const struct stat&b) {
    if(a.st_dev!=b.st_dev||a.st_ino!=b.st_ino||a.st_uid!=b.st_uid||a.st_mode!=b.st_mode
        ||a.st_nlink!=b.st_nlink||a.st_size!=b.st_size)return false;
#ifdef IDOLY_DARWIN_BRIDGE
    return a.st_mtimespec.tv_sec==b.st_mtimespec.tv_sec&&a.st_mtimespec.tv_nsec==b.st_mtimespec.tv_nsec
        &&a.st_ctimespec.tv_sec==b.st_ctimespec.tv_sec&&a.st_ctimespec.tv_nsec==b.st_ctimespec.tv_nsec;
#else
    return a.st_mtim.tv_sec==b.st_mtim.tv_sec&&a.st_mtim.tv_nsec==b.st_mtim.tv_nsec
        &&a.st_ctim.tv_sec==b.st_ctim.tv_sec&&a.st_ctim.tv_nsec==b.st_ctim.tv_nsec;
#endif
}
inline void member(int exports,const char* name,Report& report) {
    namespace queue_detail=idoly_mp4_queue::detail;
    const int flags=queue_detail::rd|queue_detail::nofollow|queue_detail::nonblock;
    int first=::openat(exports,name,flags);
    if(first<0){if(queue_detail::error_number()==2)++report.missing;else ++report.deferred;return;}
    struct stat original{};
    if(!temporary(first,original)){::close(first);++report.deferred;return;}
    // Keep the first inode open while resolving the same directory member a
    // second time. Replacement between these lookups must never be unlinked.
    int second=::openat(exports,name,flags);struct stat current{};
    const bool owned=temporary(second,current)&&unchanged(original,current);
    if(second>=0)::close(second);
    if(!owned){::close(first);++report.deferred;return;}
    const int result=::unlinkat(exports,name,0);const int error=queue_detail::error_number();
    ::close(first);
    if(result==0)++report.removed;else if(error==2)++report.missing;else ++report.deferred;
}
} // namespace detail
inline Result clean(int exports,const char* output_id,Report* output=nullptr) {
    Report report{};
    if(!detail::private_directory(exports)||!idoly_mp4_queue::detail::hex(output_id,32)) {
        if(output){*output=report;}
        return Result::invalid_argument;
    }
    char name[48]{};
    ::memcpy(name,output_id,32);::memcpy(name+32,".pcm",5);detail::member(exports,name,report);
    ::memcpy(name+32,".partial.mp4",13);detail::member(exports,name,report);
    if(output)*output=report;
    return report.deferred?Result::deferred:Result::ok;
}

// Prepared only for an explicit removal of a completed journal record. The
// held descriptor preserves the first observed inode through journal fsync.
struct FinalFile {
    int held_fd=-1;
    struct stat identity{};
    char name[48]{};
    bool prepared=false,missing=false;
};
inline void discard_final(FinalFile& file) {
    if(file.held_fd>=0)::close(file.held_fd);
    file=FinalFile{};
}
inline Result prepare_final(int exports,const char* output_id,FinalFile& file) {
    discard_final(file);
    if(!detail::private_directory(exports)||!idoly_mp4_queue::detail::hex(output_id,32))
        return Result::invalid_argument;
    ::memcpy(file.name,output_id,32);::memcpy(file.name+32,".mp4",5);
    namespace queue_detail=idoly_mp4_queue::detail;
    const int fd=::openat(exports,file.name,queue_detail::rd|queue_detail::nofollow|queue_detail::nonblock);
    if(fd<0) {
        if(queue_detail::error_number()==2){file.prepared=true;file.missing=true;return Result::ok;}
        discard_final(file);return Result::final_deferred;
    }
    if(!detail::temporary(fd,file.identity)){::close(fd);discard_final(file);return Result::final_deferred;}
    file.held_fd=fd;file.prepared=true;return Result::ok;
}
inline Result remove_final(int exports,FinalFile& file) {
    struct Retirement {FinalFile& file;~Retirement(){discard_final(file);}} retirement{file};
    // A malformed/stale preparation can never turn into an arbitrary unlink.
    if(!file.prepared||!detail::private_directory(exports)
        ||idoly_mp4_queue::detail::length(file.name,sizeof(file.name))!=36
        ||::memcmp(file.name+32,".mp4",5))return Result::invalid_argument;
    char output_id[33]{};::memcpy(output_id,file.name,32);
    if(!idoly_mp4_queue::detail::hex(output_id,32))return Result::invalid_argument;
    namespace queue_detail=idoly_mp4_queue::detail;
    const int flags=queue_detail::rd|queue_detail::nofollow|queue_detail::nonblock;
    if(file.missing) {
        // A new file at a previously absent name has no captured identity.
        int appeared=::openat(exports,file.name,flags);
        if(appeared>=0){::close(appeared);return Result::final_deferred;}
        return queue_detail::error_number()==2?Result::ok:Result::final_deferred;
    }
    struct stat held{},current{};
    if(!detail::temporary(file.held_fd,held)||!detail::unchanged(file.identity,held))return Result::final_deferred;
    int second=::openat(exports,file.name,flags);
    if(second<0)return queue_detail::error_number()==2?Result::ok:Result::final_deferred;
    const bool owned=detail::temporary(second,current)&&detail::unchanged(file.identity,current);
    ::close(second);
    if(!owned)return Result::final_deferred;
    if(::unlinkat(exports,file.name,0)==0)return Result::ok;
    return queue_detail::error_number()==2?Result::ok:Result::final_deferred;
}
} // namespace idoly_mp4_queue_cleanup
