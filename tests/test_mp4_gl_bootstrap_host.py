"""Execute the actual GL bootstrap owner under explicit native/GC fixtures.

This verifies ownership, generation and retry duties; no actual GPU completion
is simulated or asserted by these tests.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="module")
def bootstrap(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("Host C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    actual = bridge.split("// BEGIN_MP4_GL_BOOTSTRAP_HOST", 1)[1].split("// END_MP4_GL_BOOTSTRAP_HOST", 1)[0]
    prefix = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
using std::size_t;
enum class Mp4SceneResult {ok,waiting,stale,unsupported};
namespace mp4_gl_completion {struct Witness{uintptr_t manager=0,device=0,gl_context=0;uint64_t generation=0;uint32_t minimum_serial=0;};}
namespace mp4_gpu_fence {
struct Fence{void* pointer=nullptr;int32_t version=0,type=0;};
struct Device{void*manager=nullptr,*device=nullptr;uintptr_t vtable=0;bool gl_completion=false;};
struct Pins{};
struct Api{
 void*context=nullptr;
 bool(*sources)(void*,const Pins&)=nullptr;
 void*(*new_command)(void*)=nullptr;
 uint32_t(*retain)(void*,void*)=nullptr;
 void*(*target)(void*,uint32_t)=nullptr;
 void(*ctor)(void*,void*)=nullptr;
 Fence(*create)(void*,void*)=nullptr;
 void(*execute)(void*,void*)=nullptr;
};
struct PinnedHost{Api services;};
Api pinned_api(PinnedHost&h){return h.services;}
}
uintptr_t mp4_native_base=0x1000,device_address=0x2000;
struct GlPins{uintptr_t device_cell=8,device_vtable=16,caps_cell=24;};
GlPins mp4_gl_source_pins(){return {};}
std::atomic<bool>mp4_gl_observer_published{true};
std::atomic<uint64_t>mp4_gl_platform_generation{1};
bool thread_ok=true,reads=true,hooks=true,gl=true,capable=true,sync_real=true,witness_ready=false,configure_ok=true,sources_ok=true,root_ok=true,target_ok=true,null_fence=false;
int new_calls=0,root_calls=0,ctor_calls=0,create_calls=0,execute_calls=0,throw_at=0;bool generation_in_ctor=false;
bool game_call(){return thread_ok;}
bool mp4_gl_hook_receipts(void*){return hooks;}
bool mp4_gpu_host_read(void*,uintptr_t p,void*out,size_t n){
 if(!reads)return false;
 uintptr_t v=0;
 if(p==mp4_native_base+8)v=device_address;
 else if(p==device_address)v=gl?mp4_native_base+16:0x9000;
 else return false;
 assert(n==sizeof v);std::memcpy(out,&v,n);return true;
}
bool mp4_gl_native_read(void*,uintptr_t p,void*out,size_t n){
 if(!reads)return false;
 if(p==mp4_native_base+24){uintptr_t c=0x3000;assert(n==sizeof c);std::memcpy(out,&c,n);return true;}
 if(p==0x3000+0x496||p==0x3000+0x585){assert(n==1);*static_cast<uint8_t*>(out)=p==0x3000+0x496?capable:sync_real;return true;}
 return false;
}
bool mp4_gpu_capture_gl_witness(void*,const mp4_gpu_fence::Device&d,mp4_gl_completion::Witness&w){assert(d.device==reinterpret_cast<void*>(device_address)&&d.gl_completion);if(!witness_ready)return false;w={1,device_address,2,3,4};return true;}
struct Host{bool configured=false,draw=false,sealed=false;uint64_t source=0,epoch=0,auxiliary_recipe=0;mp4_gpu_fence::PinnedHost pinned;}mp4_gpu_fence_host;
using Mp4GpuFenceHost=Host;
mp4_gpu_fence::Pins mp4_gpu_pins;
bool mp4_gpu_host_configure(uint64_t source,uint64_t epoch){
 if(!configure_ok)return false;
 auto&h=mp4_gpu_fence_host;h.configured=true;h.source=source;h.epoch=epoch;
 auto&a=h.pinned.services;
 a.sources=[](void*,const mp4_gpu_fence::Pins&){return sources_ok;};
 a.new_command=[](void*)->void*{++new_calls;return reinterpret_cast<void*>(uintptr_t(0x4000+new_calls*16));};
 a.retain=[](void*,void*)->uint32_t{++root_calls;return root_ok?uint32_t(root_calls):0;};
 a.target=[](void*,uint32_t root)->void*{return target_ok?reinterpret_cast<void*>(uintptr_t(0x4000+root*16)):nullptr;};
 a.ctor=[](void*,void*){++ctor_calls;if(generation_in_ctor)++mp4_gl_platform_generation;if(throw_at==1)throw std::runtime_error("ctor");};
 a.create=[](void*,void*){++create_calls;if(throw_at==2)throw std::runtime_error("create");return mp4_gpu_fence::Fence{null_fence?nullptr:reinterpret_cast<void*>(7),1,1};};
 a.execute=[](void*,void*){++execute_calls;if(throw_at==3)throw std::runtime_error("execute");};
 return true;
}
bool mp4_gpu_host_configure_for(Mp4GpuFenceHost&h,uint64_t source,uint64_t epoch,uint64_t){assert(&h==&mp4_gpu_fence_host);return mp4_gpu_host_configure(source,epoch);}
'''
    driver = r'''
int main(int argc,char**argv){
 assert(argc==2);const std::string mode=argv[1];
 if(mode=="nongl")gl=false;
 if(mode=="uninstalled")mp4_gl_observer_published=false;
 if(mode=="bad_hooks")hooks=false;
 if(mode=="no_capability")capable=false;
 if(mode=="cpu_sync")sync_real=false;
 if(mode=="observed")witness_ready=true;
 if(mode=="configure_failure")configure_ok=false;
 if(mode=="source_failure")sources_ok=false;
 if(mode=="read_failure")reads=false;
 if(mode=="root_failure")root_ok=false;
 if(mode=="root_mismatch")target_ok=false;
 if(mode=="ctor_throw")throw_at=1;
 if(mode=="create_throw")throw_at=2;
 if(mode=="execute_throw")throw_at=3;
 if(mode=="generation_in_ctor")generation_in_ctor=true;
 if(mode=="null_fence")null_fence=true;
 if(mode=="exhausted_generation")mp4_gl_platform_generation=0;
 if(mode=="invalid_epoch"){assert(mp4_gpu_gl_preflight(7,0)==Mp4SceneResult::stale&&!new_calls);return 0;}
 if(mode=="foreign_thread"){thread_ok=false;assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::stale&&!new_calls);return 0;}
 auto r=mp4_gpu_gl_preflight(7,9);
 if(mode=="nongl"||mode=="observed"){assert(r==Mp4SceneResult::ok&&!new_calls);return 0;}
 if(mode=="uninstalled"||mode=="bad_hooks"||mode=="no_capability"||mode=="cpu_sync"||mode=="configure_failure"||mode=="source_failure"||mode=="read_failure"||mode=="exhausted_generation"){
  assert(r==Mp4SceneResult::unsupported&&!new_calls);return 0;
 }
 if(mode=="root_failure"||mode=="root_mismatch"){
  assert(r==Mp4SceneResult::unsupported&&new_calls==1&&!ctor_calls&&!create_calls&&!execute_calls&&mp4_gl_bootstrap_entries[0].quarantined);return 0;
 }
 if(throw_at||mode=="generation_in_ctor"||mode=="null_fence"){
  assert(r==Mp4SceneResult::stale&&mp4_gl_bootstrap_entries[0].quarantined&&root_calls==1&&ctor_calls==1);
  assert(create_calls==((throw_at==1||generation_in_ctor)?0:1));assert(execute_calls==(throw_at==3?1:0));return 0;
 }
 assert(r==Mp4SceneResult::waiting&&new_calls==1&&root_calls==1&&ctor_calls==1&&create_calls==1&&execute_calls==1);
 assert(mp4_gl_bootstrap_entries[0].root&&mp4_gl_bootstrap_entries[0].executed);
 assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::waiting&&new_calls==1);
 if(mode=="reuse_observation"){witness_ready=true;assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::ok&&new_calls==1&&root_calls==1);return 0;}
 if(mode=="new_generation"||mode=="capacity"){
  ++mp4_gl_platform_generation;assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::waiting&&new_calls==2);
  if(mode=="capacity"){
   for(int n=2;n<8;++n){++mp4_gl_platform_generation;assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::waiting);}
   ++mp4_gl_platform_generation;assert(mp4_gpu_gl_preflight(7,9)==Mp4SceneResult::unsupported&&new_calls==8);
  }
  assert(mp4_gl_bootstrap_entries[0].root==1&&mp4_gl_bootstrap_entries[1].root==2);
 }
}
'''
    folder = tmp_path_factory.mktemp("gl-bootstrap")
    source = folder / "test.cpp"
    source.write_text(prefix + actual + driver)
    binary = folder / "test"
    result = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(source), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary

@pytest.mark.parametrize("mode", ["normal", "nongl", "uninstalled", "bad_hooks", "no_capability", "cpu_sync", "observed", "configure_failure", "source_failure", "read_failure", "root_failure", "root_mismatch", "ctor_throw", "create_throw", "execute_throw", "generation_in_ctor", "null_fence", "reuse_observation", "new_generation", "capacity", "exhausted_generation", "invalid_epoch", "foreign_thread"])
def test_actual_bootstrap_retains_ownership_without_private_draw_ack(bootstrap, mode):
    result = subprocess.run([str(bootstrap), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
