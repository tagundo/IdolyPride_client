"""Exercise the production PCM I/O bounds with real files and syscall faults."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stddef.h>
#include <cassert>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <cerrno>
std::string mode;unsigned calls=0;
long fake_pread(int fd,void* data,size_t count,int64_t offset){
    ++calls;if(mode=="oversized")return static_cast<long>(count)+1;
    if(mode=="zero")return 0;if(mode=="error"){errno=EIO;return -1;}
    return ::pread(fd,data,mode=="partial"&&count>3?3:count,offset);
}
long fake_pwrite(int fd,const void* data,size_t count,int64_t offset){
    ++calls;if(mode=="oversized")return static_cast<long>(count)+1;
    if(mode=="zero")return 0;if(mode=="error"){errno=EIO;return -1;}
    return ::pwrite(fd,data,mode=="partial"&&count>3?3:count,offset);
}
#define pread fake_pread
#define pwrite fake_pwrite
// PRODUCTION
#undef pread
#undef pwrite
int main(int argc,char**argv){
    assert(argc==3);mode=argv[1];const bool writing=std::string(argv[2])=="write";
    char path[]="/tmp/idoly-pcm-transfer-XXXXXX";int fd=mkstemp(path);assert(fd>=0);assert(unlink(path)==0);
    std::vector<uint8_t> original(65546,0x6b),buffer(65536,0x31);
    assert(::pwrite(fd,original.data(),original.size(),0)==static_cast<long>(original.size()));
    size_t count=buffer.size();int64_t offset=5;int selected_fd=fd;void* data=buffer.data();
    bool expected=mode=="complete"||mode=="partial"||mode=="empty";
    if(mode=="negative")offset=-1;
    if(mode=="overflow")offset=INT64_MAX-2;
    if(mode=="too_large")++count;
    if(mode=="null")data=nullptr;
    if(mode=="bad_fd")selected_fd=-1;
    if(mode=="empty"){count=0;data=nullptr;}
    const bool ok=transfer_at(selected_fd,data,count,offset,writing);assert(ok==expected);
    const bool preflight=mode=="negative"||mode=="overflow"||mode=="too_large"||mode=="null"||mode=="bad_fd"||mode=="empty";
    if(preflight)assert(calls==0);
    if(mode=="oversized"||mode=="zero"||mode=="error")assert(calls==1);
    std::vector<uint8_t> observed(original.size());assert(::pread(fd,observed.data(),observed.size(),0)==static_cast<long>(observed.size()));
    if(ok&&count&&writing){
        assert(!std::memcmp(observed.data(),original.data(),5));
        assert(!std::memcmp(observed.data()+5,buffer.data(),count));
        assert(!std::memcmp(observed.data()+5+count,original.data()+5+count,original.size()-5-count));
    }else assert(observed==original);
    if(ok&&count&&!writing)for(uint8_t value:buffer)assert(value==0x6b);
    assert(close(fd)==0);
}
'''


@pytest.fixture(scope="module")
def transfer_binary(tmp_path_factory):
    compiler=shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:pytest.skip("C++ compiler required")
    body=(ROOT/"client-presentation/native/mp4_runtime.hpp").read_text().split("inline bool transfer_at(",1)[1].split("\nstruct Configuration",1)[0]
    build=tmp_path_factory.mktemp("mp4-transfer");source=build/"transfer.cpp";binary=build/"transfer"
    source.write_text(HARNESS.replace("// PRODUCTION","inline bool transfer_at("+body))
    result=subprocess.run([compiler,"-std=c++17","-O1","-Wall","-Wextra","-Werror",
        "-Wno-misleading-indentation","-D_FORTIFY_SOURCE=3",str(source),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize("mode",["complete","partial","empty","negative","overflow","too_large","null","bad_fd","oversized","zero","error"])
@pytest.mark.parametrize("direction",["read","write"])
def test_pcm_transfer_bounds_and_short_io(transfer_binary,mode,direction):
    result=subprocess.run([str(transfer_binary),mode,direction],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
