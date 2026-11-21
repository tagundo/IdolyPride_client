"""Execute the shipping native host's file gate with real filesystem objects."""
from pathlib import Path
import os
import platform
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "ios-unified/native/IdolyEmbeddedServer.m"
IDENTIFIER = "a" * 32


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        pytest.skip("Native C compiler required")
    folder = tmp_path_factory.mktemp("ios-mp4-host-file-gate")
    source, output = folder / "gate.c", folder / "gate"
    host = HOST.read_text()
    policy = host.split("// BEGIN_MP4_QUEUE_FILE_POLICY", 1)[1].split("// END_MP4_QUEUE_FILE_POLICY", 1)[0]
    source.write_text("""#define _GNU_SOURCE
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
""" + policy + """
int main(int argc,char **argv) {
    if (argc != 3) return 2;
    printf("%d %d %d\\n",IDMP4HexIdentifier(argv[2]),IDMP4PrivateDirectory(argv[1]),IDMP4FinishedFile(argv[1],argv[2]));
    return 0;
}
""")
    subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror",str(source),"-o",str(output)],
                   check=True,capture_output=True,text=True,timeout=30)

    def run(root, identifier=IDENTIFIER):
        result = subprocess.run([str(output),str(root),identifier],check=True,capture_output=True,text=True,timeout=2)
        return tuple(map(int,result.stdout.split()))
    return run


def test_owned_completed_output_can_be_saved_without_a_client_path(gate, tmp_path):
    tmp_path.chmod(0o700)
    output = tmp_path / (IDENTIFIER + ".mp4")
    output.write_bytes(b"owned-completed-MP4")
    before = output.read_bytes()
    assert gate(tmp_path) == (1,1,1)
    assert output.read_bytes() == before


@pytest.mark.parametrize("identifier", ["", "a"*31, "a"*33, "A"*32, "."*32, "../"+"a"*29, "a"*31+"/"])
def test_client_identity_cannot_select_a_path(gate, tmp_path, identifier):
    assert gate(tmp_path,identifier) == (0,1,0)


@pytest.mark.parametrize("kind", ["empty","directory","fifo","symlink","hardlink"])
def test_save_rejects_unfinished_or_unowned_file_shapes_without_deleting_them(gate, tmp_path, kind):
    output = tmp_path / (IDENTIFIER + ".mp4")
    foreign = tmp_path / "foreign"
    if kind == "empty":
        output.write_bytes(b"")
    elif kind == "directory":
        output.mkdir()
    elif kind == "fifo":
        os.mkfifo(output,0o600)
    else:
        foreign.write_bytes(b"keep-foreign-output")
        if kind == "symlink":
            output.symlink_to(foreign)
        else:
            os.link(foreign,output)
    assert gate(tmp_path) == (1,1,0)
    assert output.lstat()
    if foreign.exists():
        assert foreign.read_bytes() == b"keep-foreign-output"


def test_export_root_must_be_private_and_cannot_be_a_symlink(gate, tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / (IDENTIFIER + ".mp4")).write_bytes(b"owned")
    alias = tmp_path / "alias"
    alias.symlink_to(private,target_is_directory=True)
    assert gate(alias) == (1,0,0)
    private.chmod(0o755)
    assert gate(private) == (1,0,0)
    assert private.stat().st_mode & 0o777 == 0o755


def test_missing_output_never_becomes_a_new_empty_file(gate, tmp_path):
    assert gate(tmp_path) == (1,1,0)
    assert not list(tmp_path.iterdir())


def test_real_foundation_host_validates_queue_commands_and_private_configuration(tmp_path):
    """Run the real Objective-C command/sanitizer code on Apple's Foundation.

    Native Unity callbacks and the serial worker are deterministic fakes. The
    shipping request, JSON, private-directory, lifecycle and save code runs
    unchanged. This does not prove actual UIKit or Unity rendering behavior.
    """
    if platform.system() != "Darwin" or not shutil.which("xcrun"):
        pytest.skip("Actual Apple Foundation SDK required")
    host = HOST.read_text()
    section = host[host.index("static NSDictionary *mp4SessionStatus(void)"):host.index("void IdolyEmbeddedServerCryptoSelfTest(")]
    source, output = tmp_path / "queue-host.m", tmp_path / "queue-host"
    source.write_text(r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <dlfcn.h>
#include <stdio.h>
#import "MP4LifecyclePolicy.h"
static NSString *rootDirectory,*mp4ExportDirectory,*mp4PersistentExportDirectory,*mp4ConfiguredDirectory,*mp4ConfiguredQueueDirectory;
static NSDictionary *mp4TitleCatalog;
static const NSUInteger IDJSONLimit=65536;
static uint64_t mp4ConfiguredEpoch;
static atomic_bool pythonReady;
static IDMP4LifecyclePolicy mp4Lifecycle=ID_MP4_LIFECYCLE_POLICY_INITIALIZER;
static NSDictionary *descriptor,*nativeQueue;
static unsigned configurations,queueConfigurations,enqueues,starts,operations,runs,pauses,resumes,nativeResumes;
static int operationCode,operationPosition,lastSuspend;
static NSString *operationJob;
static NSString *nativeSessionPhase=@"rendering";
static bool nativeSceneReady=true;
static size_t fakeStatus(char *p,size_t cap){int n=snprintf(p,cap,"{\"phase\":\"%s\",\"frames\":5,\"total_frames\":100,\"ready\":false,\"unity_ticks\":9,\"capture_acks\":5}",nativeSessionPhase.UTF8String);return n>0&&(size_t)n<cap?(size_t)n:0;}
static int fakeReady(void){return nativeSceneReady?1:0;}
static NSString *JSON(id value){return [[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:value options:0 error:NULL] encoding:NSUTF8StringEncoding];}
static size_t fakeQueueStatus(char*p,size_t cap){NSData*d=[JSON(nativeQueue)dataUsingEncoding:NSUTF8StringEncoding];if(d.length>=cap)return 0;memcpy(p,d.bytes,d.length);p[d.length]=0;return d.length;}
static int fakeConfigure(const char*b,uint64_t e,const char*c,const char*o,int p){assert(b&&e&&c&&o&&p==2);++configurations;return 0;}
static int fakeConfigureQueue(const char*q,const char*o){assert(q&&o);++queueConfigurations;return 0;}
static int fakeEnqueue(uint32_t f,uint32_t d,uint32_t c,uint32_t v,uint32_t a){assert(f==60&&d==1&&c==2&&v==16000000&&a==192000);++enqueues;return 0;}
static int fakeStart(uint32_t f,uint32_t d,uint32_t c,uint32_t v,uint32_t a){assert(f==60&&d==1&&c==2&&v==16000000&&a==192000);++starts;return nativeSceneReady?0:-1;}
static int fakeRun(void){++runs;return 0;}
static int fakePause(void){++pauses;return 0;}
static int fakeResume(void){++resumes;return 0;}
static int fakeCommand(int op,const char*id,int p){assert(p>=0&&p<8);++operations;operationCode=op;operationPosition=p;operationJob=[NSString stringWithUTF8String:id];return 0;}
static void fakeSuspend(int reason){lastSuspend=reason;}
static void fakeSessionResume(void){++nativeResumes;lastSuspend=0;}
static void fakeCancel(void){}
static void* fakeDlsym(void*scope,const char*name){(void)scope;
 if(!strcmp(name,"IDMP4SessionStatus"))return(void*)fakeStatus;
 if(!strcmp(name,"IDMP4SessionReady"))return(void*)fakeReady;
 if(!strcmp(name,"IDMP4SessionConfigure"))return(void*)fakeConfigure;
 if(!strcmp(name,"IDMP4QueueConfigure"))return(void*)fakeConfigureQueue;
 if(!strcmp(name,"IDMP4QueueStatus"))return(void*)fakeQueueStatus;
 if(!strcmp(name,"IDMP4QueueEnqueue"))return(void*)fakeEnqueue;
 if(!strcmp(name,"IDMP4SessionStart"))return(void*)fakeStart;
 if(!strcmp(name,"IDMP4QueueRun"))return(void*)fakeRun;
 if(!strcmp(name,"IDMP4QueuePause"))return(void*)fakePause;
 if(!strcmp(name,"IDMP4QueueResume"))return(void*)fakeResume;
 if(!strcmp(name,"IDMP4QueueCommand"))return(void*)fakeCommand;
 if(!strcmp(name,"IDMP4SessionSuspend"))return(void*)fakeSuspend;
 if(!strcmp(name,"IDMP4SessionResume"))return(void*)fakeSessionResume;
 if(!strcmp(name,"IDMP4SessionCancel"))return(void*)fakeCancel;
 return NULL;
}
#define dlsym fakeDlsym
#define dispatch_async(queue,block) (block)()
@interface TestWorker:NSObject
- (void)enqueue:(void(^)(void))block;
@end
@implementation TestWorker
- (void)enqueue:(void(^)(void))block{block();}
@end
static TestWorker *worker;
static NSString *IDNativeDataDirectory(void){return rootDirectory;}
static NSString *callHost(const char*name,NSString*argument,NSString**error){assert(!strcmp(name,"mp4_configuration"));assert(argument==nil);*error=nil;return JSON(descriptor);}
''' + section + r'''
static NSDictionary *request(NSDictionary *value){__block NSDictionary *reply=nil;IdolyEmbeddedServerMP4Command(JSON(value),^(NSString*r){reply=[NSJSONSerialization JSONObjectWithData:[r dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];});assert(reply);return reply;}
static void mkdirs(NSString*p){BOOL good=[NSFileManager.defaultManager createDirectoryAtPath:p withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:NULL];assert(good);assert(chmod(p.fileSystemRepresentation,0700)==0);}
int main(int argc,char**argv){@autoreleasepool{
 assert(argc==2);rootDirectory=[[NSString stringWithUTF8String:argv[1]]stringByResolvingSymlinksInPath];worker=[TestWorker new];atomic_store(&pythonReady,true);
 NSString *session=[rootDirectory stringByAppendingPathComponent:@".idoly-mp4-audio-test"];
 NSString *exports=[session stringByAppendingPathComponent:@"exports"],*library=[rootDirectory stringByAppendingPathComponent:@".idoly-mp4-library"];
 NSString *queue=[library stringByAppendingPathComponent:@"queue"],*persistent=[library stringByAppendingPathComponent:@"exports"];
 mkdirs(session);mkdirs(exports);mkdirs(library);mkdirs(queue);mkdirs(persistent);
 descriptor=@{@"schema":@1,@"available":@YES,@"directory":session,@"export_directory":exports,@"capability":@"cccccccccccccccccccccccccccccccc",@"epoch":@7,@"queue_directory":queue,@"persistent_export_directory":persistent,
 @"title_catalog":@{@"ko":@{@"tln_live_tri-004":@"한국어 노래"},@"ja":@{@"tln_live_tri-004":@"日本語の歌"},@"en":@{@"tln_live_tri-004":@"English song"},@"fr":@{@"tln_live_tri-004":@"Ignored language"}}};
 nativeQueue=@{@"schema":@1,@"available":@YES,@"can_run":@YES,@"command_pending":@NO,@"running":@NO,@"paused":@NO,@"phase":@"idle",@"error_code":@"none",@"capacity":@8,@"last_added_job_id":@"",@"current_job_id":@"",@"jobs":@[],@"directory":@"/private/secret-must-not-leak"};
 // No progress timer runs in this harness: Hide/new-job transitions must use
 // the current native phase, not the previous visible overlay's cached phase.
 assert(!IdolyEmbeddedServerMP4IsFinishing());nativeSessionPhase=@"finishing";assert(IdolyEmbeddedServerMP4IsFinishing());
 nativeSessionPhase=@"completed";assert(!IdolyEmbeddedServerMP4IsFinishing());nativeSessionPhase=@"preparing_audio";assert(!IdolyEmbeddedServerMP4IsFinishing());
 nativeSessionPhase=@"finishing";assert(IdolyEmbeddedServerMP4IsFinishing());nativeSessionPhase=@"rendering";
 NSDictionary*r=request(@{@"id":@1,@"action":@"mp4_enqueue",@"fps":@60,@"video_codec":@2,@"video_bitrate":@16000000});
 assert([r[@"ok"]isEqual:@YES]&&enqueues==1&&configurations==1&&queueConfigurations==1);assert([JSON(r)rangeOfString:@"secret-must-not-leak"].location==NSNotFound);
 assert([request(@{@"id":@2,@"action":@"mp4_queue_status"})[@"ok"]isEqual:@YES]);assert(configurations==1&&queueConfigurations==1);
 // The native host forwards a ready paused source MV. It must not override a
 // genuinely false snapshot or permanently cache that failure in the menu.
 nativeSessionPhase=@"idle";nativeSceneReady=false;
 assert([request(@{@"id":@2,@"action":@"mp4_status"})[@"result"][@"ready"]isEqual:@NO]);
 r=request(@{@"id":@2,@"action":@"mp4_start",@"fps":@60,@"video_codec":@2,@"video_bitrate":@16000000});assert([r[@"ok"]isEqual:@NO]&&[r[@"error"][@"code"]isEqual:@"mp4_scene_not_ready"]&&starts==1);
 nativeSceneReady=true;
 assert([request(@{@"id":@2,@"action":@"mp4_status"})[@"result"][@"ready"]isEqual:@YES]);
 r=request(@{@"id":@2,@"action":@"mp4_start",@"fps":@60,@"video_codec":@2,@"video_bitrate":@16000000});assert([r[@"ok"]isEqual:@YES]&&starts==2);
 nativeSessionPhase=@"rendering";
 NSArray *invalid=@[@{@"id":@YES,@"action":@"mp4_queue_run"},@{@"id":@3,@"action":@"mp4_queue_move",@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",@"position":@YES},@{@"id":@3,@"action":@"mp4_enqueue",@"fps":@YES,@"video_codec":@2,@"video_bitrate":@16000000},@{@"id":@3,@"action":@"mp4_queue_status",@"path":@"/private"},@{@"id":@3,@"action":@"mp4_queue_cancel",@"job_id":@"../aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},@{@"id":@3,@"action":@"mp4_queue_run_unknown"}];
 for(NSDictionary*i in invalid)assert([request(i)[@"ok"]isEqual:@NO]);assert(operations==0&&runs==0&&enqueues==1);
 NSString *embedded=[@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"stringByAppendingFormat:@"%Cevil",(unichar)0];assert([request(@{@"id":@4,@"action":@"mp4_queue_cancel",@"job_id":embedded})[@"ok"]isEqual:@NO]);
 r=request(@{@"id":@5,@"action":@"mp4_queue_move",@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",@"position":@0});assert([r[@"ok"]isEqual:@YES]&&operations==1&&operationCode==4&&[operationJob isEqual:@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]);
 for(id consent in @[@NO,@1,@"true",NSNull.null])assert([request(@{@"id":@5,@"action":@"mp4_queue_remove",@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",@"delete_output":consent})[@"ok"]isEqual:@NO]);
 assert(operations==1);r=request(@{@"id":@5,@"action":@"mp4_queue_remove",@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"});assert([r[@"ok"]isEqual:@YES]&&operations==2&&operationCode==2&&operationPosition==0);
 r=request(@{@"id":@5,@"action":@"mp4_queue_remove",@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",@"delete_output":@YES});assert([r[@"ok"]isEqual:@YES]&&operations==3&&operationCode==2&&operationPosition==1);
 IdolyEmbeddedServerMP4SetLifecycleActive(NO);unsigned before=nativeResumes;
 assert([request(@{@"id":@6,@"action":@"mp4_queue_run"})[@"ok"]isEqual:@YES]);assert(lastSuspend==1&&nativeResumes==before);
 assert([request(@{@"id":@7,@"action":@"mp4_queue_pause"})[@"ok"]isEqual:@YES]);assert(lastSuspend==3);IdolyEmbeddedServerMP4SetLifecycleActive(YES);assert(nativeResumes==before&&lastSuspend==3);
 assert([request(@{@"id":@8,@"action":@"mp4_queue_resume"})[@"ok"]isEqual:@YES]);assert(nativeResumes==before+1&&runs==1&&pauses==1&&resumes==1);
 NSMutableDictionary *row=[@{@"job_id":@"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",@"output_id":@"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",@"timeline":@"tln_live_tri-004",@"actor_count":@5,@"width":@1920,@"height":@1080,@"fps_num":@60,@"video_codec":@2,@"state":@"completed",@"error_code":@""}mutableCopy];
 NSMutableDictionary *saved=[nativeQueue mutableCopy];saved[@"jobs"]=@[row];nativeQueue=saved;
 NSDictionary *localized=request(@{@"id":@8,@"action":@"mp4_queue_status"})[@"result"][@"jobs"][0][@"title_localizations"];
 assert(localized.count==3&&[localized[@"ko"]isEqual:@"한국어 노래"]&&[localized[@"ja"]isEqual:@"日本語の歌"]&&[localized[@"en"]isEqual:@"English song"]&&localized[@"fr"]==nil);
 row[@"timeline"]=@"tln_live_unknown";assert(request(@{@"id":@8,@"action":@"mp4_queue_status"})[@"result"][@"jobs"][0][@"title_localizations"]==nil);row[@"timeline"]=@"tln_live_tri-004";
 NSDictionary *badTitles=mp4SanitizeTitleCatalog(@{@"en":@{@"good":@"Readable title",@"bad_newline":@"Line\nbreak",@"bad_space":@"  ",@"bad_long":[@"a"stringByPaddingToLength:193 withString:@"a" startingAtIndex:0],@"../bad_key":@"Rejected key"}});
 assert([badTitles[@"en"]count]==1&&[badTitles[@"en"][@"good"]isEqual:@"Readable title"]);
 NSMutableDictionary *tooMany=[NSMutableDictionary new];for(unsigned i=0;i<2049;++i)tooMany[[NSString stringWithFormat:@"tln_live_%u",i]]=@"Title";assert(mp4SanitizeTitleCatalog(@{@"en":tooMany}).count==0);
 NSString *file=[persistent stringByAppendingPathComponent:@"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.mp4"];assert([@"finished"writeToFile:file atomically:NO encoding:NSUTF8StringEncoding error:NULL]);
 __block NSURL *chosen=nil;IdolyEmbeddedServerMP4ExportJob(row[@"job_id"],^(NSURL*u,NSString*error){assert(error==nil);chosen=u;});assert([chosen.path isEqual:file]);
 row[@"state"]=@"pending";chosen=nil;IdolyEmbeddedServerMP4ExportJob(row[@"job_id"],^(NSURL*u,NSString*error){assert(error);chosen=u;});assert(chosen==nil);row[@"state"]=@"completed";
 saved[@"jobs"]=@[row,row];assert([request(@{@"id":@9,@"action":@"mp4_queue_status"})[@"result"][@"available"]isEqual:@NO]);saved[@"jobs"]=@[row];saved[@"schema"]=@YES;assert([request(@{@"id":@10,@"action":@"mp4_queue_status"})[@"result"][@"available"]isEqual:@NO]);saved[@"schema"]=@1;
 NSMutableDictionary *rotated=[descriptor mutableCopy];rotated[@"epoch"]=@8;descriptor=rotated;assert([request(@{@"id":@11,@"action":@"mp4_queue_status"})[@"ok"]isEqual:@YES]);assert(configurations==2&&queueConfigurations==2);
 NSString *original=[queue stringByAppendingString:@"-original"];assert(rename(queue.fileSystemRepresentation,original.fileSystemRepresentation)==0);assert(symlink(original.fileSystemRepresentation,queue.fileSystemRepresentation)==0);
 assert([request(@{@"id":@12,@"action":@"mp4_queue_status"})[@"ok"]isEqual:@NO]);assert(configurations==2&&queueConfigurations==2);
 puts("PASS Foundation queue host requests and private outputs");
}return 0;}
''')
    compiler = subprocess.check_output(["xcrun","--sdk","macosx","--find","clang"],
                                       stderr=subprocess.STDOUT,text=True).strip()
    sdk = subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],
                                  stderr=subprocess.STDOUT,text=True).strip()
    compiled = subprocess.run([compiler,"-isysroot",sdk,"-mmacosx-version-min=12.0",
                               "-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",
                               "-I",str(ROOT / "ios-unified/native"),str(source),"-framework","Foundation","-o",str(output)],
                              check=False,capture_output=True,text=True,timeout=60)
    assert compiled.returncode == 0, "Foundation queue host compilation failed:\n" + compiled.stdout + compiled.stderr
    result = subprocess.run([str(output),str(tmp_path)],check=False,capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, "Foundation queue host execution failed:\n" + result.stdout + result.stderr
    assert result.stdout.strip() == "PASS Foundation queue host requests and private outputs"
