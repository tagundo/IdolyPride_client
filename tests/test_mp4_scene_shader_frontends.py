"""Exact early four-observer publication; backend/relay leaf is independently tested."""
from pathlib import Path
import re
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <string>
alignas(4096)unsigned char image[4096]{};uintptr_t image_base=reinterpret_cast<uintptr_t>(image);
void mp4_scene_shader_loaded_hook(){}void mp4_scene_shader_unloaded_hook(){}void mp4_scene_shader_bundle_unload_hook(){}void mp4_scene_shader_load_hook(){}
void original0(){}void original1(){}void original2(){}void original3(){}
using Original=void(*)();Original mp4_scene_shader_loaded_original=original0,mp4_scene_shader_unloaded_original=original1,mp4_scene_shader_bundle_unload_original=original2,mp4_scene_shader_load_original=original3;
Original*original_slots[]={&mp4_scene_shader_loaded_original,&mp4_scene_shader_unloaded_original,&mp4_scene_shader_bundle_unload_original,&mp4_scene_shader_load_original};
uintptr_t hook_values[]={reinterpret_cast<uintptr_t>(mp4_scene_shader_loaded_hook),reinterpret_cast<uintptr_t>(mp4_scene_shader_unloaded_hook),reinterpret_cast<uintptr_t>(mp4_scene_shader_bundle_unload_hook),reinterpret_cast<uintptr_t>(mp4_scene_shader_load_hook)};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace pin{struct Entry{uintptr_t rva=0;uint8_t bytes[16]{};};Entry mp4_scene_shader_loaded,mp4_scene_shader_unloaded,mp4_scene_shader_bundle_unload,mp4_scene_shader_load;}
pin::Entry*entries[]={&pin::mp4_scene_shader_loaded,&pin::mp4_scene_shader_unloaded,&pin::mp4_scene_shader_bundle_unload,&pin::mp4_scene_shader_load};
namespace mp4_bootstrap{struct Pin{uintptr_t rva=0;uint8_t original[24]{};};Pin android_scene_managed_pins[4],ios_scene_managed_pins[4];struct Install{};}
bool other_code=true;bool mp4_renderer_srp_code(const mp4game::Binding&b){return other_code&&b.rva==0xf00;}
#ifdef IDOLY_DARWIN_BRIDGE
bool relay_current[4]={true,true,true,true};
bool mp4_mapped(uintptr_t at,size_t n,bool){return at>=reinterpret_cast<uintptr_t>(image)&&at+n<=reinterpret_cast<uintptr_t>(image)+sizeof image;}
bool mp4_capture_static_frontend(const pin::Entry&e,uintptr_t hook,uintptr_t original,bool require_ready){
 assert(!require_ready);for(size_t i=0;i<4;++i)if(&e==entries[i])return relay_current[i]&&hook==hook_values[i]&&original&&original==reinterpret_cast<uintptr_t>(*original_slots[i]);return false;
}
#else
constexpr size_t mp4_managed_hook_capacity=160;
struct Receipt{uintptr_t base=0,rva=0;void*trampoline=nullptr;void**original_location=nullptr;void*stub=nullptr;}mp4_managed_hook_receipts[mp4_managed_hook_capacity];
std::atomic<size_t>mp4_managed_hook_count{4};bool backend_current[4]={true,true,true,true};
struct Backend{bool receipt(size_t index,uintptr_t target,uintptr_t replacement,uintptr_t gateway,uintptr_t stub,mp4_bootstrap::Install*){
 if(index<9||index>=13)return false;size_t i=index-9;return backend_current[i]&&target==image_base+128+i*32&&replacement==hook_values[i]&&gateway&&gateway==reinterpret_cast<uintptr_t>(*original_slots[i])&&stub==19+i;
}}mp4_managed_source_backend;
#endif
uintptr_t mp4_native_base=64;std::atomic<bool>mp4_native_clock_source_ready{true};
bool mp4_scene_shader_origin_receipt(int){return true;}bool(*mp4_scene_shader_role_receipt)(int)=nullptr;
// SHIPPING_FRONTEND
// SHIPPING_INSTALL
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 for(size_t i=0;i<4;++i){entries[i]->rva=128+i*32;for(size_t j=0;j<16;++j)entries[i]->bytes[j]=static_cast<uint8_t>(i*16+j);
  for(auto*p:{&mp4_bootstrap::android_scene_managed_pins[i],&mp4_bootstrap::ios_scene_managed_pins[i]}){p->rva=entries[i]->rva;for(size_t j=0;j<24;++j)p->original[j]=static_cast<uint8_t>(i*16+j);}
  memcpy(image+entries[i]->rva,mp4_bootstrap::ios_scene_managed_pins[i].original,24);
#ifndef IDOLY_DARWIN_BRIDGE
  mp4_managed_hook_receipts[i]={image_base,entries[i]->rva,reinterpret_cast<void*>(*original_slots[i]),reinterpret_cast<void**>(original_slots[i]),reinterpret_cast<void*>(19+i)};
#endif
 }
 if(mode=="no_image")image_base=0;
 if(mode.rfind("null_original",0)==0)*original_slots[mode.back()-'0']=nullptr;
 if(mode.rfind("prefix",0)==0)entries[mode.back()-'0']->bytes[0]^=1;
#ifdef IDOLY_DARWIN_BRIDGE
 if(mode.rfind("relay",0)==0)relay_current[mode.back()-'0']=false;
 if(mode.rfind("tail",0)==0)image[entries[mode.back()-'0']->rva+20]^=1;
#else
 if(mode=="count_overflow")mp4_managed_hook_count.store(mp4_managed_hook_capacity+1);
 if(mode=="unpublished")mp4_managed_hook_count.store(3);
 if(mode.rfind("backend",0)==0)backend_current[mode.back()-'0']=false;
 if(mode.rfind("stub",0)==0)mp4_managed_hook_receipts[mode.back()-'0'].stub=nullptr;
#endif
 if(mode=="install_native_missing")mp4_native_base=0;
 if(mode=="install_native_unverified")mp4_native_clock_source_ready.store(false);
 if(mode=="unknown_code"){mp4game::Binding b{};b.rva=0xf00;assert(mp4_scene_shader_frontend_code(b));other_code=false;assert(!mp4_scene_shader_frontend_code(b));return 0;}
 if(mode=="known_code"){mp4game::Binding b{};b.rva=entries[0]->rva;memcpy(b.prefix,entries[0]->bytes,16);assert(mp4_scene_shader_frontend_code(b));++b.prefix[0];assert(!mp4_scene_shader_frontend_code(b));return 0;}
 const bool valid=mode=="valid_early"||mode=="install_native_missing"||mode=="install_native_unverified";
 assert(mp4_scene_shader_frontends_current()==valid);
 const bool installed=mode=="valid_early";assert(mp4_scene_shader_origin_install()==installed);
 assert((mp4_scene_shader_role_receipt==mp4_scene_shader_origin_receipt)==installed);return 0;
}
'''
def function(text,name):
    match=re.search(r'(?:\[\[maybe_unused\]\]\s*)?bool\s+'+name+r'\([^;]*?\)\{',text);assert match
    a=text.index('{',match.start());b=a+1;depth=1
    while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[match.start():b]
@pytest.fixture(scope='module',params=['android','ios'])
def host(request,tmp_path_factory):
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    block=text.split('// BEGIN_MP4_SCENE_SHADER_FRONTEND_HOST',1)[1].split('// END_MP4_SCENE_SHADER_FRONTEND_HOST',1)[0]
    source=PREFIX.replace('// SHIPPING_FRONTEND',block).replace('// SHIPPING_INSTALL',function(text,'mp4_scene_shader_origin_install'))
    folder=tmp_path_factory.mktemp('scene-frontends-'+request.param);cpp=folder/'test.cpp';binary=folder/'test';cpp.write_text(source)
    cmd=[shutil.which('c++')or'clang++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-pie','-no-pie',str(cpp),'-o',str(binary)]
    if request.param=='ios':cmd.insert(1,'-DIDOLY_DARWIN_BRIDGE=1')
    result=subprocess.run(cmd,capture_output=True,text=True);assert result.returncode==0,result.stderr
    return request.param,binary
def test_no_partial_early_scene_observer_capability(host):
    platform,binary=host
    cases=['valid_early','no_image','known_code','unknown_code','install_native_missing','install_native_unverified']
    cases += [base+str(i)for base in ['null_original','prefix']for i in range(4)]
    cases += [base+str(i)for base in (['relay','tail']if platform=='ios'else['backend','stub'])for i in range(4)]
    if platform=='android':cases+=['count_overflow','unpublished']
    for case in cases:
        result=subprocess.run([str(binary),case],capture_output=True,text=True)
        assert result.returncode==0,case+'\n'+result.stderr
