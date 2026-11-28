// SPDX-License-Identifier: AGPL-3.0-or-later
#import "IdolyMP4Library.h"
#include "MP4CompletedFilePolicy.h"
#include <errno.h>
#include <dirent.h>
#include <sys/file.h>
#include <stdio.h>

static const NSUInteger IDMP4LibraryRootLimit=256,IDMP4LibraryFileLimit=1024,IDMP4LibraryPage=32;
static BOOL IDMP4LibraryLeaf(id value) {
    if (![value isKindOfClass:NSString.class] || [value length]!=49 || ![value hasPrefix:@".idoly-mp4-audio-"]) return NO;
    return IDMP4LibraryIdentifier([[value substringFromIndex:17] UTF8String]);
}
static NSArray<NSString *> *IDMP4LibraryNames(int descriptor,BOOL *valid) {
    *valid=NO;
    int duplicate=dup(descriptor);DIR *directory=duplicate>=0?fdopendir(duplicate):NULL;
    if (!directory) { if(duplicate>=0)close(duplicate);return @[]; }
    NSMutableArray *names=[NSMutableArray new];struct dirent *entry;NSUInteger examined=0;errno=0;
    while ((entry=readdir(directory))) {
        if (!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")) continue;
        if (++examined>4096) { closedir(directory);return @[]; }
        NSString *name=[NSString stringWithUTF8String:entry->d_name];
        if (name) [names addObject:name];
        errno=0;
    }
    BOOL complete=errno==0;closedir(directory);*valid=complete;return names;
}
static BOOL IDMP4LibraryWriteAll(int fd,const void *bytes,size_t count) {
    const unsigned char *source=bytes;
    while (count) { ssize_t amount=write(fd,source,count);if(amount<0&&errno==EINTR)continue;
        if(amount<=0)return NO;source+=amount;count-=(size_t)amount; }
    return YES;
}
@interface IDMP4LibraryIndex : NSObject
@property(nonatomic) int directory,lock;
@property(nonatomic,strong) NSMutableArray<NSString *> *roots;
- (BOOL)save;
@end
@implementation IDMP4LibraryIndex
- (instancetype)init { if((self=[super init])){_directory=-1;_lock=-1;}return self; }
- (void)dealloc {if(_lock>=0){flock(_lock,LOCK_UN);close(_lock);}if(_directory>=0)close(_directory);}
- (BOOL)save {
    NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"schema":@1,@"roots":_roots} options:0 error:NULL];
    if(!data || data.length>65536 || _roots.count>IDMP4LibraryRootLimit)return NO;
    NSString *temporary=[@".roots-" stringByAppendingString:NSUUID.UUID.UUIDString];
    int fd=openat(_directory,temporary.UTF8String,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    BOOL good=fd>=0 && IDMP4LibraryWriteAll(fd,data.bytes,data.length) && fsync(fd)==0;
    if(fd>=0)close(fd);
    if(good)good=renameat(_directory,temporary.UTF8String,_directory,"roots-v1.json")==0 && fsync(_directory)==0;
    if(!good)unlinkat(_directory,temporary.UTF8String,0);
    return good;
}
@end
static IDMP4LibraryIndex *IDMP4LibraryLoad(NSString *root) {
    if(![root isKindOfClass:NSString.class] || !root.isAbsolutePath || ![root isEqual:root.stringByResolvingSymlinksInPath])return nil;
    int parent=IDMP4LibraryOpenDirectory(root.fileSystemRepresentation);if(parent<0)return nil;
    BOOL made=mkdirat(parent,".idoly-mp4-completed",0700)==0;
    if(!made && errno!=EEXIST){close(parent);return nil;}
    int directory=openat(parent,".idoly-mp4-completed",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(made && fsync(parent)!=0){if(directory>=0)close(directory);close(parent);return nil;}
    close(parent);if(!IDMP4LibraryPrivateDirectoryFD(directory)){if(directory>=0)close(directory);return nil;}
    IDMP4LibraryIndex *index=[IDMP4LibraryIndex new];index.directory=directory;
    index.lock=openat(directory,".lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
    struct stat info;
    if(index.lock<0 || fstat(index.lock,&info)!=0 || !S_ISREG(info.st_mode) || info.st_uid!=getuid()
            || info.st_nlink!=1 || (info.st_mode&07777)!=0600 || flock(index.lock,LOCK_EX|LOCK_NB)!=0)return nil;
    int fd=openat(directory,"roots-v1.json",O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if(fd<0){if(errno!=ENOENT)return nil;index.roots=[NSMutableArray new];return index;}
    struct stat before,after;BOOL good=fstat(fd,&before)==0 && IDMP4LibraryPrivateFile(&before) && before.st_size<=65536;
    NSMutableData *bytes=good?[NSMutableData dataWithLength:(NSUInteger)before.st_size]:nil;size_t at=0;
    while(good&&at<bytes.length){ssize_t n=read(fd,(unsigned char *)bytes.mutableBytes+at,bytes.length-at);
        if(n<0&&errno==EINTR)continue;if(n<=0){good=NO;break;}at+=(size_t)n;}
    good=good&&fstat(fd,&after)==0&&IDMP4LibrarySameFile(&before,&after);close(fd);if(!good)return nil;
    id object=[NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL];
    if(![object isKindOfClass:NSDictionary.class] || [object count]!=2 || ![object[@"schema"]isEqual:@1]
            || CFGetTypeID((__bridge CFTypeRef)object[@"schema"])==CFBooleanGetTypeID()
            || ![object[@"roots"]isKindOfClass:NSArray.class] || [object[@"roots"]count]>IDMP4LibraryRootLimit)return nil;
    NSMutableArray *roots=[NSMutableArray new];
    for(id leaf in object[@"roots"]){if(!IDMP4LibraryLeaf(leaf)||[roots containsObject:leaf])return nil;[roots addObject:leaf];}
    index.roots=roots;return index;
}
static NSNumber *IDMP4LibraryCreated(const struct stat *info) {
#if defined(__APPLE__)
    int64_t seconds=info->st_birthtimespec.tv_sec,nanoseconds=info->st_birthtimespec.tv_nsec;
    if(seconds<=0){seconds=info->st_mtimespec.tv_sec;nanoseconds=info->st_mtimespec.tv_nsec;}
#else
    int64_t seconds=info->st_mtim.tv_sec,nanoseconds=info->st_mtim.tv_nsec;
#endif
    uint64_t value=seconds>0?(uint64_t)seconds*1000+(uint64_t)MAX(0,nanoseconds)/1000000:0;
    return @(MIN(UINT64_C(9007199254740991),value));
}
static NSDictionary *IDMP4LibraryRecord(NSString *exports,NSString *identifier,NSString *jobID) {
    if(![exports isEqual:exports.stringByResolvingSymlinksInPath])return nil;
    int directory=IDMP4LibraryOpenDirectory(exports.fileSystemRepresentation);struct stat info;
    int file=directory>=0?IDMP4LibraryOpenFinalAt(directory,identifier.UTF8String,&info):-1;
    if(directory>=0)close(directory);if(file<0)return nil;close(file);
    NSMutableDictionary *row=[@{@"export_id":identifier,@"bytes":@((uint64_t)info.st_size),
        @"created_ms":IDMP4LibraryCreated(&info),@"_root":exports}mutableCopy];if(jobID)row[@"job_id"]=jobID;
    return row;
}
static NSArray *IDMP4LibraryFiles(NSString *exports,BOOL *valid) {
    *valid=NO;if(![exports isEqual:exports.stringByResolvingSymlinksInPath])return @[];
    int broker=IDMP4LibraryOpenDirectory(exports.stringByDeletingLastPathComponent.fileSystemRepresentation);
    if(broker<0){if(errno==ENOENT)*valid=YES;return @[];}close(broker);
    int directory=IDMP4LibraryOpenDirectory(exports.fileSystemRepresentation);
    if(directory<0){if(errno==ENOENT){*valid=YES;return @[];}return @[];}
    BOOL complete=NO;NSArray *names=IDMP4LibraryNames(directory,&complete);NSMutableArray *records=[NSMutableArray new];
    if(complete)for(NSString *name in names){
        if(name.length!=36||![name hasSuffix:@".mp4"])continue;
        NSDictionary *row=IDMP4LibraryRecord(exports,[name substringToIndex:32],nil);
        if(row){[records addObject:row];if(records.count>IDMP4LibraryFileLimit)break;}
    }
    close(directory);*valid=complete;return records;
}
static NSArray *IDMP4LibraryCollect(NSString *root,IDMP4LibraryIndex *index,NSArray *queueJobs,NSString *queueExports,
                                   NSString *protectedRoot,BOOL pruneEmpty,NSString **error) {
    NSMutableArray *records=[NSMutableArray new],*retained=[NSMutableArray new];BOOL changed=NO;
    if(queueJobs.count>8){*error=@"mp4_catalog_unavailable";return nil;}
    for(NSString *leaf in index.roots){BOOL valid=NO;NSString *exports=[[root stringByAppendingPathComponent:leaf]stringByAppendingPathComponent:@"exports"];
        NSArray *files=IDMP4LibraryFiles(exports,&valid);if(!valid){*error=@"mp4_catalog_unavailable";return nil;}
        if(files.count||!pruneEmpty||[exports isEqual:protectedRoot]){[retained addObject:leaf];[records addObjectsFromArray:files];}else changed=YES;
        if(records.count>IDMP4LibraryFileLimit){*error=@"mp4_catalog_capacity";return nil;}
    }
    // Migration is deliberately one level and only the historical broker
    // namespace. Unknown queue files, partial MP4s and arbitrary folders never
    // become saved outputs through this catalog.
    int parent=IDMP4LibraryOpenDirectory(root.fileSystemRepresentation);BOOL valid=NO;
    NSArray *names=parent>=0?IDMP4LibraryNames(parent,&valid):@[];if(parent>=0)close(parent);
    if(!valid){*error=@"mp4_catalog_unavailable";return nil;}
    for(NSString *leaf in names)if(IDMP4LibraryLeaf(leaf)&&![retained containsObject:leaf]){
        NSString *exports=[[root stringByAppendingPathComponent:leaf]stringByAppendingPathComponent:@"exports"];BOOL complete=NO;
        NSArray *files=IDMP4LibraryFiles(exports,&complete);if(!complete||!files.count)continue;
        if(retained.count>=IDMP4LibraryRootLimit){*error=@"mp4_catalog_capacity";return nil;}
        [retained addObject:leaf];[records addObjectsFromArray:files];changed=YES;
        if(records.count>IDMP4LibraryFileLimit){*error=@"mp4_catalog_capacity";return nil;}
    }
    if(records.count>IDMP4LibraryFileLimit){*error=@"mp4_catalog_capacity";return nil;}
    if(changed){index.roots=retained;if(![index save]){*error=@"mp4_catalog_unavailable";return nil;}}
    // The one-shot cap is separate from the existing at-most-eight queue jobs.
    // No scan of queue exports or adoption of unjournaled queue files occurs.
    for(id item in queueJobs){
        if(![item isKindOfClass:NSDictionary.class]||![item[@"state"]isEqual:@"completed"]||!queueExports)continue;
        NSString *identifier=item[@"output_id"],*job=item[@"job_id"];
        if(![identifier isKindOfClass:NSString.class]||!IDMP4LibraryIdentifier(identifier.UTF8String)
                ||![job isKindOfClass:NSString.class]||!IDMP4LibraryIdentifier(job.UTF8String))continue;
        NSDictionary *row=IDMP4LibraryRecord(queueExports,identifier,job);if(row)[records addObject:row];
    }
    NSMutableSet *seen=[NSMutableSet new];for(NSDictionary *row in records){
        if([seen containsObject:row[@"export_id"]]){*error=@"mp4_catalog_unavailable";return nil;}[seen addObject:row[@"export_id"]];}
    [records sortUsingComparator:^NSComparisonResult(NSDictionary *a,NSDictionary *b){
        NSComparisonResult compared=[b[@"created_ms"]compare:a[@"created_ms"]];return compared==NSOrderedSame?[a[@"export_id"]compare:b[@"export_id"]]:compared;}];
    return records;
}
BOOL IDMP4LibraryBookmark(NSString *root,NSString *exports,NSString **error) {
    *error=@"mp4_catalog_unavailable";NSString *broker=exports.stringByDeletingLastPathComponent,*leaf=broker.lastPathComponent;
    if(!IDMP4LibraryLeaf(leaf)||![exports.lastPathComponent isEqual:@"exports"]||![broker.stringByDeletingLastPathComponent isEqual:root]
            ||![exports isEqual:exports.stringByResolvingSymlinksInPath])return NO;
    int directory=IDMP4LibraryOpenDirectory(broker.fileSystemRepresentation),files=IDMP4LibraryOpenDirectory(exports.fileSystemRepresentation);
    BOOL good=directory>=0&&files>=0;if(directory>=0)close(directory);if(files>=0)close(files);if(!good)return NO;
    IDMP4LibraryIndex *index=IDMP4LibraryLoad(root);if(!index)return NO;
    NSArray *records=IDMP4LibraryCollect(root,index,@[],nil,exports,YES,error);if(!records)return NO;
    if(records.count>=IDMP4LibraryFileLimit){*error=@"mp4_catalog_capacity";return NO;}
    if([index.roots containsObject:leaf])return YES;
    if(index.roots.count>=IDMP4LibraryRootLimit){*error=@"mp4_catalog_capacity";return NO;}
    [index.roots addObject:leaf];return [index save];
}
NSDictionary *IDMP4LibraryStatus(NSString *root,NSArray *jobs,NSString *queueExports,NSUInteger offset,NSString **error) {
    *error=@"mp4_catalog_unavailable";IDMP4LibraryIndex *index=IDMP4LibraryLoad(root);if(!index)return nil;
    NSArray *records=IDMP4LibraryCollect(root,index,jobs,queueExports,nil,NO,error);if(!records)return nil;
    NSUInteger start=offset,amount=start<records.count?MIN(IDMP4LibraryPage,records.count-start):0;NSMutableArray *visible=[NSMutableArray new];
    for(NSDictionary *record in (amount?[records subarrayWithRange:NSMakeRange(start,amount)]:@[])){
        NSMutableDictionary *row=[record mutableCopy];[row removeObjectForKey:@"_root"];[visible addObject:row];}
    return @{@"schema":@1,@"available":@YES,@"records":visible,@"offset":@(start),@"total":@(records.count),@"has_more":@(start+amount<records.count)};
}
NSURL *IDMP4LibraryFile(NSString *root,NSArray *jobs,NSString *queueExports,NSString *exportID,NSString **error) {
    *error=@"mp4_export_not_ready";IDMP4LibraryIndex *index=IDMP4LibraryLoad(root);if(!index)return nil;
    NSArray *records=IDMP4LibraryCollect(root,index,jobs,queueExports,nil,NO,error);if(!records)return nil;
    for(NSDictionary *record in records){
        if(exportID?![record[@"export_id"]isEqual:exportID]:record[@"job_id"]!=nil)continue;
        NSString *directory=record[@"_root"];int folder=IDMP4LibraryOpenDirectory(directory.fileSystemRepresentation);
        int file=folder>=0?IDMP4LibraryOpenFinalAt(folder,[record[@"export_id"]UTF8String],NULL):-1;
        if(folder>=0)close(folder);if(file<0)return nil;close(file);
        return [NSURL fileURLWithPath:[directory stringByAppendingPathComponent:[record[@"export_id"]stringByAppendingString:@".mp4"]]];
    }
    return nil;
}
