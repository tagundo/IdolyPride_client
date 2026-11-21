"""Check temporary retirement against filesystem substitutions and special files."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <cassert>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cerrno>
#include <string>
std::string replaced_name;
int replacement_opens=0;
bool replace_on_second=false;
int cleanup_openat(int directory,const char* name,int flags,...) {
    assert((flags&O_NOFOLLOW)&&(flags&O_NONBLOCK)&&!(flags&O_CREAT));
    if(replace_on_second&&replaced_name==name&&++replacement_opens==2) {
        assert(::renameat(directory,name,directory,"saved-original")==0);
        int replacement=::openat(directory,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
        assert(replacement>=0&&::write(replacement,"FOREIGN",7)==7);::close(replacement);
    }
    return ::openat(directory,name,flags);
}
#define openat cleanup_openat
#include "mp4_queue_cleanup.hpp"
#undef openat
namespace cleanup=idoly_mp4_queue_cleanup;
const char* id="0123456789abcdef0123456789abcdef";
std::string member(const char* suffix){return std::string(id)+suffix;}
void create_file(int directory,const std::string& name,int mode=0600) {
    int fd=::openat(directory,name.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,mode);
    assert(fd>=0&&::write(fd,"TEST",4)==4);::close(fd);assert(::fchmodat(directory,name.c_str(),mode,0)==0);
}
bool exists(int directory,const std::string& name) {struct stat s{};return ::fstatat(directory,name.c_str(),&s,AT_SYMLINK_NOFOLLOW)==0;}
int main(int argc,char** argv) {
    assert(argc==3);const std::string scenario=argv[2];
    int directory=::open(argv[1],O_RDONLY|O_DIRECTORY|O_NOFOLLOW);assert(directory>=0);
    cleanup::Report report{};
    if(scenario=="owned") {
        create_file(directory,member(".pcm"));create_file(directory,member(".partial.mp4"));create_file(directory,member(".mp4"));create_file(directory,"foreign.pcm");
        assert(cleanup::clean(directory,id,&report)==cleanup::Result::ok&&report.removed==2&&report.deferred==0);
        assert(!exists(directory,member(".pcm"))&&!exists(directory,member(".partial.mp4")));
        assert(exists(directory,member(".mp4"))&&exists(directory,"foreign.pcm"));
        assert(cleanup::clean(directory,id,&report)==cleanup::Result::ok&&report.missing==2&&report.removed==0);
    }else if(scenario=="special") {
        create_file(directory,"foreign-target");assert(::symlinkat("foreign-target",directory,member(".pcm").c_str())==0);
        assert(::mkfifoat(directory,member(".partial.mp4").c_str(),0600)==0);
        assert(cleanup::clean(directory,id,&report)==cleanup::Result::deferred&&report.deferred==2&&report.removed==0);
        assert(exists(directory,member(".pcm"))&&exists(directory,member(".partial.mp4"))&&exists(directory,"foreign-target"));
        assert(!std::strcmp(cleanup::error_code(cleanup::Result::deferred),"queue_temporary_cleanup_deferred"));
    }else if(scenario=="hardlink") {
        create_file(directory,member(".pcm"));assert(::linkat(directory,member(".pcm").c_str(),directory,"foreign-hardlink",0)==0);
        create_file(directory,member(".partial.mp4"),0644);
        assert(cleanup::clean(directory,id,&report)==cleanup::Result::deferred&&report.deferred==2&&report.removed==0);
        assert(exists(directory,member(".pcm"))&&exists(directory,"foreign-hardlink")&&exists(directory,member(".partial.mp4")));
    }else if(scenario=="replacement") {
        create_file(directory,member(".pcm"));create_file(directory,member(".partial.mp4"));create_file(directory,member(".mp4"));
        replaced_name=member(".pcm");replace_on_second=true;
        assert(cleanup::clean(directory,id,&report)==cleanup::Result::deferred&&report.removed==1&&report.deferred==1);
        assert(exists(directory,"saved-original")&&exists(directory,member(".pcm"))&&exists(directory,member(".mp4")));
        int fd=::openat(directory,member(".pcm").c_str(),O_RDONLY|O_NOFOLLOW);char bytes[8]{};assert(fd>=0&&::read(fd,bytes,7)==7&&!std::strcmp(bytes,"FOREIGN"));::close(fd);
    }else if(scenario=="final_owned") {
        create_file(directory,member(".mp4"));create_file(directory,member(".pcm"));
        cleanup::FinalFile final{};assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok&&final.held_fd>=0);
        int held=final.held_fd;cleanup::discard_final(final);assert(final.held_fd<0&&::fcntl(held,F_GETFD)<0&&errno==EBADF);
        // Journal failure discards the held identity and preserves the video.
        assert(exists(directory,member(".mp4")));
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok);held=final.held_fd;
        assert(cleanup::remove_final(directory,final)==cleanup::Result::ok&&final.held_fd<0&&::fcntl(held,F_GETFD)<0);
        assert(!exists(directory,member(".mp4"))&&exists(directory,member(".pcm")));
    }else if(scenario=="final_replacement") {
        create_file(directory,member(".mp4"));cleanup::FinalFile final{};
        replaced_name=member(".mp4");replace_on_second=true;
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok);int held=final.held_fd;
        assert(cleanup::remove_final(directory,final)==cleanup::Result::final_deferred&&final.held_fd<0&&::fcntl(held,F_GETFD)<0);
        assert(exists(directory,"saved-original")&&exists(directory,member(".mp4")));
        assert(!std::strcmp(cleanup::error_code(cleanup::Result::final_deferred),"queue_final_cleanup_deferred"));
    }else if(scenario=="final_special") {
        create_file(directory,"foreign-final");cleanup::FinalFile final{};
        assert(::symlinkat("foreign-final",directory,member(".mp4").c_str())==0);
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::final_deferred&&final.held_fd<0);
        assert(::unlinkat(directory,member(".mp4").c_str(),0)==0&&::mkfifoat(directory,member(".mp4").c_str(),0600)==0);
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::final_deferred&&final.held_fd<0);
        assert(exists(directory,member(".mp4"))&&exists(directory,"foreign-final"));
    }else if(scenario=="final_missing") {
        cleanup::FinalFile final{};assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok&&final.missing);
        assert(cleanup::remove_final(directory,final)==cleanup::Result::ok&&!final.prepared);
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok&&final.missing);
        create_file(directory,member(".mp4"));assert(cleanup::remove_final(directory,final)==cleanup::Result::final_deferred);
        assert(exists(directory,member(".mp4")));
    }else if(scenario=="final_modified") {
        create_file(directory,member(".mp4"));cleanup::FinalFile final{};
        assert(cleanup::prepare_final(directory,id,final)==cleanup::Result::ok);int held=final.held_fd;
        int writer=::openat(directory,member(".mp4").c_str(),O_WRONLY|O_APPEND|O_NOFOLLOW);assert(writer>=0&&::write(writer,"CHANGED",7)==7);::close(writer);
        assert(cleanup::remove_final(directory,final)==cleanup::Result::final_deferred&&final.held_fd<0&&::fcntl(held,F_GETFD)<0);
        assert(exists(directory,member(".mp4")));
    }else if(scenario=="invalid") {
        create_file(directory,member(".pcm"));
        for(const char* invalid:{"../0123456789abcdef0123456789abcde","0123456789ABCDEF0123456789ABCDEF","0123456789abcdef0123456789abcde", "0123456789abcdef0123456789abcdef0",static_cast<const char*>(nullptr)})
            assert(cleanup::clean(directory,invalid,&report)==cleanup::Result::invalid_argument&&report.removed==0);
        assert(cleanup::clean(-1,id,&report)==cleanup::Result::invalid_argument);
        assert(::fchmod(directory,0755)==0&&cleanup::clean(directory,id,&report)==cleanup::Result::invalid_argument);
        assert(exists(directory,member(".pcm")));
    }else assert(false);
    ::close(directory);
}
'''


@pytest.fixture(scope="module")
def cleanup_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    root = tmp_path_factory.mktemp("mp4-queue-cleanup")
    source, binary = root / "cleanup.cpp", root / "cleanup"
    source.write_text(SOURCE)
    warnings = ["-Wno-misleading-indentation"]
    if "g++" in Path(compiler).name:
        warnings.append("-Wno-class-memaccess")
    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *warnings,
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["owned", "special", "hardlink", "replacement", "invalid", "final_owned", "final_replacement", "final_special", "final_missing", "final_modified"])
def test_bounded_journal_output_cleanup(cleanup_binary, tmp_path, scenario):
    tmp_path.chmod(0o700)
    result = subprocess.run([str(cleanup_binary), str(tmp_path), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
