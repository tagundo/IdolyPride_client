"""Actual early source-factory receipt adapter; no Scene/VM ownership inferred.

Android backend publication is a modeled service (the real finite trace verifier
has an independent shipping suite); Darwin relay instructions are reobserved.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <string>
namespace mp4_director_birth{using FactoryFn=void(*)();}
void original_body(){};void other_body(){};void mp4_child_factory_hook(){}
mp4_director_birth::FactoryFn mp4_child_factory_original=original_body;
alignas(4096) unsigned char memory[4096]{};
uintptr_t image_base=reinterpret_cast<uintptr_t>(memory);
std::atomic<bool>ready{false};
namespace mp4_bootstrap{
struct Pin{uintptr_t rva=128;uint8_t original[24]{};};
Pin android_bootstrap_pins[8]{},ios_bootstrap_pins[8]{};
struct Install{};
}
namespace pin{struct Entry{uintptr_t rva=128;unsigned char bytes[16]{};uintptr_t gateway=256,slot=512,relay_in=0,relay_out=0;};Entry mp4_source_timeline_factory;}
bool mp4_mapped(uintptr_t at,size_t n,bool){return at>=reinterpret_cast<uintptr_t>(memory)&&at+n<=reinterpret_cast<uintptr_t>(memory)+sizeof memory;}
template<class T>T read(void*p,size_t off){T value{};memcpy(&value,static_cast<unsigned char*>(p)+off,sizeof value);return value;}
#ifndef IDOLY_DARWIN_BRIDGE
constexpr size_t mp4_managed_hook_capacity=128;
struct Receipt{uintptr_t base=0,rva=0;void*stub=nullptr,*trampoline=nullptr;void**original_location=nullptr;}mp4_managed_hook_receipts[128]{};
std::atomic<size_t>mp4_managed_hook_count{0};
bool backend_current=true;
struct Backend{bool receipt(size_t i,uintptr_t target,uintptr_t replacement,uintptr_t gateway,uintptr_t stub,mp4_bootstrap::Install*){
 return backend_current&&i==8&&target==image_base+128&&replacement==reinterpret_cast<uintptr_t>(mp4_child_factory_hook)&&gateway==reinterpret_cast<uintptr_t>(original_body)&&stub==13;
}}mp4_managed_source_backend;
#endif
// STATIC_FRONTEND
// SOURCE_FRONTEND
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 auto&p=pin::mp4_source_timeline_factory;
 const unsigned char original[24]={0xff,0x83,0x01,0xd1,0xfe,0x6f,0x01,0xa9,0xfa,0x67,0x02,0xa9,0xf8,0x5f,0x03,0xa9,0xf6,0x57,0x04,0xa9,0xf4,0x4f,0x05,0xa9};
 memcpy(p.bytes,original,16);memcpy(memory+128,original,24);
 memcpy(mp4_bootstrap::android_bootstrap_pins[7].original,original,24);memcpy(mp4_bootstrap::ios_bootstrap_pins[7].original,original,24);
#ifdef IDOLY_DARWIN_BRIDGE
 mp4_child_factory_original=reinterpret_cast<mp4_director_birth::FactoryFn>(image_base+276);
 const uint32_t incoming=0x14000020,relay[]={0x90000010,0x91080210,0xc8dffe10,0xb4000050,0xd61f0200,0xd10183ff,0x17ffffdb};
 memcpy(memory+128,&incoming,4);memcpy(memory+256,relay,sizeof relay);
 uintptr_t target=reinterpret_cast<uintptr_t>(mp4_child_factory_hook);memcpy(memory+512,&target,sizeof target);
#else
 mp4_managed_hook_receipts[0]={image_base,128,reinterpret_cast<void*>(13),reinterpret_cast<void*>(original_body),reinterpret_cast<void**>(&mp4_child_factory_original)};mp4_managed_hook_count.store(1);
#endif
 auto saved=mp4_child_factory_original;
 if(mode=="null_original")saved=nullptr;
 if(mode=="wrong_original")saved=other_body;
 if(mode=="no_image")image_base=0;
 if(mode=="source_prefix")++p.bytes[4];
 if(mode=="wrong_rva")p.rva+=4;
#ifdef IDOLY_DARWIN_BRIDGE
 if(mode=="source_tail")++memory[148];
 if(mode=="patch")++memory[128];
 if(mode=="gateway")++memory[260];
 if(mode=="slot")memory[512]^=1;
 if(mode=="original_tail")++memory[260+16];
 if(mode=="relay")p.relay_in=4;
 if(mode=="no_gateway")p.gateway=0;
 if(mode=="no_slot")p.slot=0;
 if(mode=="late_capture_still_closed"){assert(!mp4_capture_static_frontend(p,reinterpret_cast<uintptr_t>(mp4_child_factory_hook),reinterpret_cast<uintptr_t>(saved)));assert(mp4_source_factory_gateway_current(saved));return 0;}
#else
 if(mode=="unpublished")mp4_managed_hook_count.store(0);
 if(mode=="backend_stale")backend_current=false;
 if(mode=="wrong_stub")mp4_managed_hook_receipts[0].stub=reinterpret_cast<void*>(14);
 if(mode=="wrong_slot")mp4_managed_hook_receipts[0].original_location=nullptr;
 if(mode=="wrong_base")++mp4_managed_hook_receipts[0].base;
 if(mode=="wrong_gateway")mp4_managed_hook_receipts[0].trampoline=reinterpret_cast<void*>(other_body);
 if(mode=="count_overflow")mp4_managed_hook_count.store(129);
#endif
 assert(mp4_source_factory_gateway_current(saved)==(mode=="valid_early"));return 0;
}
'''
@pytest.fixture(scope='module',params=['android','ios'])
def frontend(request,tmp_path_factory):
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=source.split('// BEGIN_MP4_SOURCE_FACTORY_FRONTEND_HOST',1)[1].split('// END_MP4_SOURCE_FACTORY_FRONTEND_HOST',1)[0]
    static=''
    if request.param=='ios':
        section=source.split('// BEGIN_MP4_CAPTURE_FRONTEND_SOURCE_HOST',1)[1].split('// END_MP4_CAPTURE_FRONTEND_SOURCE_HOST',1)[0]
        static=section.split('#ifdef IDOLY_DARWIN_BRIDGE',1)[1].split('#else',1)[0]
    content=PREFIX.replace('// SOURCE_FRONTEND',actual).replace('// STATIC_FRONTEND',static)
    folder=tmp_path_factory.mktemp('source-factory-'+request.param);cpp=folder/'test.cpp';binary=folder/'test';cpp.write_text(content)
    cmd=[shutil.which('g++') or 'clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(cpp),'-o',str(binary)]
    if request.param=='ios':cmd.insert(1,'-DIDOLY_DARWIN_BRIDGE=1')
    result=subprocess.run(cmd,capture_output=True,text=True);assert result.returncode==0,result.stderr
    return request.param,binary

def test_exact_early_factory_gateway_only(frontend):
    platform,binary=frontend
    modes=['valid_early','null_original','wrong_original','no_image','source_prefix','wrong_rva']
    modes+=['source_tail','patch','gateway','slot','original_tail','relay','no_gateway','no_slot','late_capture_still_closed'] if platform=='ios' else ['unpublished','backend_stale','wrong_stub','wrong_slot','wrong_base','wrong_gateway','count_overflow']
    for mode in modes:
        result=subprocess.run([str(binary),mode],capture_output=True,text=True)
        assert result.returncode==0,mode+'\n'+result.stderr
