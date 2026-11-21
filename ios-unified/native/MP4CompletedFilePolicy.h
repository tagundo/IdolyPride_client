// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

static inline bool IDMP4LibraryIdentifier(const char *value) {
    if (!value || strlen(value) != 32) return false;
    for (size_t i=0;i<32;++i)
        if (!((value[i]>='0'&&value[i]<='9')||(value[i]>='a'&&value[i]<='f'))) return false;
    return true;
}
static inline bool IDMP4LibraryPrivateDirectoryFD(int fd) {
    struct stat info;
    return fd>=0 && fstat(fd,&info)==0 && S_ISDIR(info.st_mode)
        && info.st_uid==getuid() && (info.st_mode&07777)==0700;
}
static inline int IDMP4LibraryOpenDirectory(const char *path) {
    if (!path || path[0]!='/') { errno=EINVAL;return -1; }
    int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    struct stat opened,named;
    if (IDMP4LibraryPrivateDirectoryFD(fd) && fstat(fd,&opened)==0 && lstat(path,&named)==0
            && S_ISDIR(named.st_mode) && opened.st_dev==named.st_dev && opened.st_ino==named.st_ino) return fd;
    if (fd>=0) { close(fd);errno=EACCES; }
    return -1;
}
static inline bool IDMP4LibrarySameFile(const struct stat *a,const struct stat *b) {
    if (a->st_dev!=b->st_dev || a->st_ino!=b->st_ino || a->st_mode!=b->st_mode
            || a->st_uid!=b->st_uid || a->st_nlink!=b->st_nlink || a->st_size!=b->st_size) return false;
#if defined(__APPLE__)
    return a->st_mtimespec.tv_sec==b->st_mtimespec.tv_sec && a->st_mtimespec.tv_nsec==b->st_mtimespec.tv_nsec
        && a->st_ctimespec.tv_sec==b->st_ctimespec.tv_sec && a->st_ctimespec.tv_nsec==b->st_ctimespec.tv_nsec;
#else
    return a->st_mtim.tv_sec==b->st_mtim.tv_sec && a->st_mtim.tv_nsec==b->st_mtim.tv_nsec
        && a->st_ctim.tv_sec==b->st_ctim.tv_sec && a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
#endif
}
static inline bool IDMP4LibraryPrivateFile(const struct stat *info) {
    return S_ISREG(info->st_mode) && info->st_uid==getuid() && info->st_nlink==1
        && (info->st_mode&07777)==0600 && info->st_size>0 && (uint64_t)info->st_size<=UINT64_C(9007199254740991);
}
static inline int IDMP4LibraryOpenFinalAt(int directory,const char *identifier,struct stat *identity) {
    if (!IDMP4LibraryIdentifier(identifier) || !IDMP4LibraryPrivateDirectoryFD(directory)) return -1;
    char name[37];memcpy(name,identifier,32);memcpy(name+32,".mp4",5);
    int fd=openat(directory,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    struct stat opened,named;
    if (fd>=0 && fstat(fd,&opened)==0 && IDMP4LibraryPrivateFile(&opened)
            && fstatat(directory,name,&named,AT_SYMLINK_NOFOLLOW)==0 && IDMP4LibrarySameFile(&opened,&named)) {
        if (identity) *identity=opened;
        return fd;
    }
    if (fd>=0) close(fd);
    return -1;
}
