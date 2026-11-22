"""Production journal with Android's hard-link denial and syscall fault injection."""
from pathlib import Path
import shutil
import subprocess
import sys
import json

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux/Android no-replace syscall boundary")

HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <sys/syscall.h>
#include <errno.h>
#include <stdarg.h>
#include <initializer_list>
#include <new>
#include <assert.h>
static const char* fault="none";
static int fault_number=EIO,allocations=0,fail_allocation=0,links=0,renames=0;
static int temp_fd=-1,temp_stats=0;
static bool installed=false,partial_written=false;
void* storage_malloc(size_t size){if(++allocations==fail_allocation){errno=ENOMEM;return nullptr;}return ::malloc(size);}
int storage_openat(int dir,const char* name,int flags,...){
    mode_t mode=0;if(flags&O_CREAT){va_list args;va_start(args,flags);mode=static_cast<mode_t>(va_arg(args,int));va_end(args);}
    if(!strcmp(fault,"open_temp")&&!strncmp(name,".queue-",7)){errno=ENOSPC;return -1;}
    if(!strcmp(fault,"validate_installed_open")&&installed&&!strcmp(name,"queue-v1.bin")){errno=EACCES;return -1;}
    int fd=::openat(dir,name,flags,mode);if(fd>=0&&!strncmp(name,".queue-",7)&&(flags&O_CREAT)){temp_fd=fd;temp_stats=0;}return fd;
}
int storage_fstat(int fd,struct stat* info){
    if(fd==temp_fd&&!installed){
        ++temp_stats;if(!strcmp(fault,"stat_temp")&&temp_stats==1){errno=EIO;return -1;}
        if(!strcmp(fault,"validate_temp_stat")&&temp_stats==2){errno=EIO;return -1;}
    }
    if(installed&&!strcmp(fault,"validate_installed_stat")){errno=EIO;return -1;}
    const int result=::fstat(fd,info);
    if(!result&&fd==temp_fd&&!installed&&temp_stats==2&&!strcmp(fault,"validate_temp"))info->st_mode=(info->st_mode&~0777)|0644;
    if(!result&&installed&&!strcmp(fault,"validate_installed_identity"))++info->st_ino;
    return result;
}
ssize_t storage_write(int fd,const void* bytes,size_t count){
    if(!strcmp(fault,"write_temp")){errno=ENOSPC;return -1;}
    if(!strcmp(fault,"write_zero"))return 0;
    if(!strcmp(fault,"write_partial")){if(partial_written){errno=ENOSPC;return -1;}partial_written=true;count=count>23?23:count;}
    return ::write(fd,bytes,count);
}
int storage_fsync(int fd){struct stat info{};assert(!::fstat(fd,&info));
    if(!strcmp(fault,"sync_temp")&&S_ISREG(info.st_mode)){errno=EIO;return -1;}
    if(!strcmp(fault,"sync_directory")&&S_ISDIR(info.st_mode)){errno=EINVAL;return -1;}
    return ::fsync(fd);
}
int storage_linkat(int,const char*,int,const char*,int){++links;errno=EPERM;return -1;}
int storage_renameat(int from,const char* oldname,int to,const char* newname){
    if(!strcmp(fault,"replace_journal")){errno=EIO;return -1;}
    return ::renameat(from,oldname,to,newname);
}
long storage_syscall(long number,...){
    assert(number==SYS_renameat2);va_list args;va_start(args,number);
    const int olddir=va_arg(args,int);const char* oldname=va_arg(args,const char*);
    const int newdir=va_arg(args,int);const char* newname=va_arg(args,const char*);
    const unsigned flags=va_arg(args,unsigned);va_end(args);
    ++renames;assert(olddir==newdir&&flags==1U&&!strcmp(newname,"queue-v1.bin")&&!strncmp(oldname,".queue-",7));
    if(!strcmp(fault,"install_new")){errno=fault_number;return -1;}
    if(!strncmp(fault,"race_",5)){
        int fd=::openat(newdir,"foreign",O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0&&::write(fd,"foreign",7)==7);::close(fd);
        if(!strcmp(fault,"race_regular")){fd=::openat(newdir,newname,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0&&::write(fd,"winner",6)==6);::close(fd);}
        else if(!strcmp(fault,"race_symlink"))assert(!::symlinkat("foreign",newdir,newname));
        else {assert(!strcmp(fault,"race_hardlink"));assert(!::linkat(newdir,"foreign",newdir,newname,0));}
    }
    const long result=::syscall(number,olddir,oldname,newdir,newname,flags);if(!result)installed=true;return result;
}
#define malloc storage_malloc
#define openat storage_openat
#define fstat storage_fstat
#define write storage_write
#define fsync storage_fsync
#define linkat storage_linkat
#define renameat storage_renameat
#define syscall storage_syscall
#include "client-presentation/native/mp4_queue.hpp"
#undef malloc
#undef openat
#undef fstat
#undef write
#undef fsync
#undef linkat
#undef renameat
#undef syscall
using namespace idoly_mp4_queue;
static unsigned nonce=0;
bool random_bytes(void*,uint8_t* bytes,size_t count){memset(bytes,0,count);bytes[0]=static_cast<uint8_t>(++nonce);return true;}
Descriptor selection(){Descriptor value{};strcpy(value.stage_asset,"stage");strcpy(value.timeline_asset,"timeline");value.actor_count=1;Actor& actor=value.actors[0];strcpy(actor.character_id,"character");actor.asset_count=1;strcpy(actor.assets[0],"body");return value;}
Options options(){Options value{};value.width=1920;value.height=1080;return value;}
int main(int argc,char** argv){
    assert(argc==3||argc==4);const char* mode=argv[1];Queue queue(random_bytes);char id[33]{};
    assert(queue.open(argv[2],"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")==Error::ok);
    allocations=0;fault=mode;
    if(!strcmp(mode,"allocate_store"))fail_allocation=1;
    if(!strcmp(mode,"allocate_wire"))fail_allocation=2;
    if(!strcmp(mode,"install_new")){assert(argc==4);fault_number=atoi(argv[3]);}
    if(!strcmp(mode,"replace_journal")){
        fault="none";assert(queue.enqueue(selection(),options(),id)==Error::ok);installed=false;fault=mode;
    }
    const size_t previous=queue.count();const Error result=queue.enqueue(selection(),options(),id);
    assert(links==0); // Every attempted hard link would fail like an Android app.
    if(!strcmp(mode,"none")){
        assert(result==Error::ok&&queue.count()==1&&renames==1);
        assert(!strcmp(queue.storage_stage(),"none")&&queue.storage_errno()==0);
        queue.close();installed=false;assert(queue.open(argv[2],"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")==Error::ok&&queue.count()==1);
    }else if(!strncmp(mode,"race_",5)){
        assert(result==Error::changed_storage&&queue.count()==0&&queue.storage_errno()==EEXIST);
        assert(!strcmp(queue.storage_stage(),"install_new"));
    }else if(!strcmp(mode,"sync_directory")||!strncmp(mode,"validate_installed",18)){
        assert(result==Error::durability_uncertain);assert(queue.enqueue(selection(),options(),id)==Error::not_open);
        const int observed_errno=queue.storage_errno();assert(observed_errno>=0&&observed_errno<=4095);
        printf("%s %d %zu\n",queue.storage_stage(),observed_errno,queue.count());
        fault="none";installed=false;queue.close();assert(queue.open(argv[2],"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")==Error::ok&&queue.count()==1);
        return 0;
    }else {
        assert(result==Error::io&&queue.count()==previous);
        assert(queue.storage_errno()>=0&&queue.storage_errno()<=4095);
    }
    printf("%s %d %zu\n",queue.storage_stage(),queue.storage_errno(),queue.count());
}
'''


@pytest.fixture(scope="module")
def storage_runner(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mp4-queue-storage-compile")
    source, executable = folder / "queue.cpp", folder / "queue"
    source.write_text(HARNESS)
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    compiled = subprocess.run([compiler, "-std=c++14", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(executable)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr

    def run(mode, root, *arguments):
        return subprocess.run([str(executable), mode, str(root), *map(str, arguments)], check=True, capture_output=True, text=True, timeout=4).stdout.strip()

    return run


@pytest.fixture
def private(tmp_path):
    folder = tmp_path / "queue"
    folder.mkdir(mode=0o700)
    return folder


def test_first_commit_never_uses_forbidden_hardlink_and_reopens(storage_runner, private):
    assert storage_runner("none", private) == "none 0 1"
    assert (private / "queue-v1.bin").stat().st_nlink == 1
    assert not list(private.glob(".queue-*.tmp"))


@pytest.mark.parametrize("mode", ["regular", "symlink", "hardlink"])
def test_no_replace_kernel_install_preserves_target_created_after_last_check(storage_runner, private, mode):
    assert storage_runner("race_" + mode, private) == "install_new 17 0"
    journal, foreign = private / "queue-v1.bin", private / "foreign"
    assert journal.read_bytes() == (b"winner" if mode == "regular" else b"foreign")
    assert foreign.read_bytes() == b"foreign"
    assert journal.is_symlink() is (mode == "symlink")
    if mode == "hardlink":
        assert journal.stat().st_ino == foreign.stat().st_ino
    assert not list(private.glob(".queue-*.tmp"))


@pytest.mark.parametrize("number", [1, 13, 28, 38, 95, 50000])
def test_failed_no_replace_syscall_has_no_link_or_overwriting_fallback(storage_runner, private, number):
    assert storage_runner("install_new", private, number) == f"install_new {number if number <= 4095 else 0} 0"
    assert not (private / "queue-v1.bin").exists()
    assert not list(private.glob(".queue-*.tmp"))


@pytest.mark.parametrize("mode,stage,number", [
    ("allocate_store", "allocate_store", 12), ("allocate_wire", "allocate_wire", 12),
    ("open_temp", "open_temp", 28), ("write_temp", "write_temp", 28),
    ("write_partial", "write_temp", 28), ("write_zero", "write_temp", 0),
    ("sync_temp", "sync_temp", 5), ("validate_temp_stat", "validate_temp", 5),
    ("validate_temp", "validate_temp", 0),
])
def test_pre_install_failure_records_exact_stage_without_publishing_job(storage_runner, private, mode, stage, number):
    assert storage_runner(mode, private) == f"{stage} {number} 0"
    assert not (private / "queue-v1.bin").exists()
    assert not list(private.glob(".queue-*.tmp"))


def test_stat_failure_keeps_unidentified_temp_instead_of_unlinking_unknown_inode(storage_runner, private):
    assert storage_runner("stat_temp", private) == "stat_temp 5 0"
    assert not (private / "queue-v1.bin").exists()
    assert len(list(private.glob(".queue-*.tmp"))) == 1


@pytest.mark.parametrize("mode,stage,number,count", [
    ("sync_directory", "sync_directory", 22, 1),
    ("validate_installed_open", "validate_installed", 13, 0),
    ("validate_installed_stat", "validate_installed", 5, 0),
    ("validate_installed_identity", "validate_installed", 0, 0),
])
def test_post_install_uncertainty_blocks_mutations_until_reopen(storage_runner, private, mode, stage, number, count):
    assert storage_runner(mode, private) == f"{stage} {number} {count}"
    assert (private / "queue-v1.bin").is_file()
    assert not list(private.glob(".queue-*.tmp"))


def test_failed_existing_journal_replace_keeps_old_committed_job(storage_runner, private):
    assert storage_runner("replace_journal", private) == "replace_journal 5 1"
    assert (private / "queue-v1.bin").is_file()
    assert not list(private.glob(".queue-*.tmp"))


def test_public_queue_error_and_diagnostics_expose_bounded_stage_without_paths(tmp_path):
    runtime = (ROOT / "client-presentation/native/mp4_queue_runtime.hpp").read_text()
    # This fixture exercises storage error publication. The independently
    # tested selected-MV cache is an input to its publisher, not a storage API.
    functions = (runtime[runtime.index("inline void queue_set_error("):runtime.index("inline bool queue_cached_add(")]
                 + runtime[runtime.index("inline void queue_publish("):runtime.index("inline bool queue_configure(")])
    source = HARNESS.split("int main(int argc,char** argv){", 1)[0] + r'''
#include <pthread.h>
namespace queue_model=idoly_mp4_queue;
static Queue* observed_store=nullptr;
Queue& queue_store(){return *observed_store;}
static pthread_mutex_t control_mutex=PTHREAD_MUTEX_INITIALIZER;
enum class QueueCommandKind{none};
struct Request{QueueCommandKind kind=QueueCommandKind::none;}queue_request;
static bool queue_pause_pending=false,queue_available=true,queue_running=false,queue_paused=false;
static bool queue_replay_available=false,queue_can_run=false,queue_active_published=false,queue_scene_owned=false;
static char queue_error[65]="none",queue_last_added[33]{},queue_phase[32]="idle",queue_active_id[33]{};
static char queue_published[16384]{};
bool queue_cached_add(char* error,size_t capacity){snprintf(error,capacity,"%s","selected_mv_snapshot_missing");return false;}
''' + functions + r'''
int main(int argc,char** argv){
 assert(argc==3);Queue queue(random_bytes);observed_store=&queue;
 assert(queue.open(argv[2],"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")==Error::ok);
 fault=argv[1];fault_number=13;char id[33]{};const Error result=queue.enqueue(selection(),options(),id);
 assert(result==Error::io||result==Error::durability_uncertain);queue_set_storage_error(result);queue_publish();puts(queue_published);
}
'''
    cpp, executable = tmp_path / "publication.cpp", tmp_path / "publication"
    cpp.write_text(source)
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    compiled = subprocess.run([compiler, "-std=c++14", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread", "-I", str(ROOT), str(cpp), "-o", str(executable)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    for fault, error, stage, number in [
        ("install_new", "queue_install_new_failed", "install_new", 13),
        ("write_temp", "queue_write_temp_failed", "write_temp", 28),
        ("sync_directory", "queue_durability_uncertain", "sync_directory", 22),
    ]:
        directory = tmp_path / fault
        directory.mkdir(mode=0o700)
        result = subprocess.run([str(executable), fault, str(directory)], check=True, capture_output=True, text=True, timeout=4)
        value = json.loads(result.stdout)
        assert value["error_code"] == error
        assert value["storage_stage"] == stage and value["storage_errno"] == number
        assert value["can_add"] is False and value["add_error"] == "selected_mv_snapshot_missing"
        assert str(directory) not in result.stdout
        assert "queue-v1.bin" not in result.stdout
