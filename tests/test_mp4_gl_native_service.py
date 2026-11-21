"""Exercise shipping OS-only memory/official-EGL symbol verification.

The ELF fixture is data with AArch64 headers, never executable or a GPU driver.
The kernel /proc/self/mem copy is real; Unity/GC services are absent.
"""
from pathlib import Path
import shutil
import struct
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

def elf(mode):
    raw=bytearray(2048);ident=b'\x7fELF\x02\x01\x01'+b'\0'*9
    raw[:64]=struct.pack('<16sHHIQQQIHHHHHH',ident,3,183,1,0,64,512,0,64,56,1,64,3,0)
    raw[64:120]=struct.pack('<IIQQQQQQ',1,5,256,256,256,32,32,16)
    raw[256:288]=bytes(range(32))
    raw[576:640]=struct.pack('<IIQQQQIIQQ',0,11,0,0,768,72 if mode=='duplicate' else 48,2,0,8,24)
    raw[640:704]=struct.pack('<IIQQQQIIQQ',0,3,0,0,896,32,0,0,1,0)
    size=4 if mode in ('tiny','tiny_getter') else 32
    raw[792:816]=struct.pack('<IBBHQQ',1,0x12,0,1,256,size)
    raw[896:912]=b'\0eglMakeCurrent\0'
    if mode=='duplicate':raw[816:840]=raw[792:816]
    if mode=='wrong_machine':struct.pack_into('<H',raw,18,62)
    if mode=='bad_strings':struct.pack_into('<Q',raw,640+24,2**64-8)
    if mode=='bad_symbol_extent':struct.pack_into('<Q',raw,576+24,2**64-8)
    return raw

@pytest.fixture(scope='module')
def native_service(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text.split('// BEGIN_MP4_GL_NATIVE_SERVICE',1)[1].split('// END_MP4_GL_NATIVE_SERVICE',1)[0]
    prefix=r'''
#define _GNU_SOURCE 1
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <unistd.h>
#include <fcntl.h>
#include <elf.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <string>
namespace std {using ::memcmp;using ::strcmp;}
struct Dl_info{const char*dli_fname;void*dli_fbase;const char*dli_sname;void*dli_saddr;};
const char*module_path=nullptr;void*code=nullptr;bool wrong_base=false;
int dladdr(const void*address,Dl_info*out){assert(address==code);*out={module_path,reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(code)-256+(wrong_base?4:0)),nullptr,code};return 1;}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==3);std::string mode=argv[1];module_path=argv[2];
 mp4_gl_memory_fd=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);assert(mp4_gl_memory_fd>=0);
 unsigned char bytes[32]{};for(unsigned i=0;i<32;++i)bytes[i]=static_cast<unsigned char>(i);code=bytes;
 if(mode=="reader"){
  uint8_t output[32]{};assert(mp4_gl_native_read(nullptr,reinterpret_cast<uintptr_t>(bytes),output,32)&&!std::memcmp(bytes,output,32));
  assert(!mp4_gl_native_read(nullptr,0,output,1));assert(!mp4_gl_native_read(nullptr,reinterpret_cast<uintptr_t>(bytes),output,4097));
  assert(!mp4_gl_native_read(nullptr,~uintptr_t(0)-1,output,8));
  void*page=mmap(nullptr,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(page!=MAP_FAILED);assert(!munmap(page,4096));
  assert(!mp4_gl_native_read(nullptr,reinterpret_cast<uintptr_t>(page),output,1));close(mp4_gl_memory_fd);mp4_gl_memory_fd=-1;
  assert(!mp4_gl_native_read(nullptr,reinterpret_cast<uintptr_t>(bytes),output,1));return 0;
 }
 if(mode=="runtime_changed")bytes[0]=99;
 if(mode=="wrong_base")wrong_base=true;
 uint8_t prefix[16]{},size=0;const char*wanted=mode=="wrong_name"?"eglDestroyContext":"eglMakeCurrent";
 const bool ok=mp4_gl_platform_symbol(code,wanted,mode=="tiny_getter"?4:16,prefix,size);
 assert(ok==(mode=="valid"||mode=="tiny_getter"));if(ok){assert(size==(mode=="tiny_getter"?4:16));for(unsigned i=0;i<size;++i)assert(prefix[i]==i);}
 close(mp4_gl_memory_fd);
}
'''
    folder=tmp_path_factory.mktemp('gl-service');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['reader','valid','tiny','tiny_getter','wrong_machine','wrong_name','runtime_changed','wrong_base','duplicate','bad_strings','bad_symbol_extent','wrong_module'])
def test_shipping_os_reader_and_platform_symbol(native_service,tmp_path,mode):
    path=tmp_path/('libWrong.so' if mode=='wrong_module' else 'libEGL.so');path.write_bytes(elf(mode))
    result=subprocess.run([str(native_service),mode,str(path)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
