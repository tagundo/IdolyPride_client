"""Actual shipping Bounds authority host with bounded native-object fixtures.

Native call targets are typed setter/dirty fixtures; unchanged original AArch64
execution evidence lives in the source audit. This does not render a GPU frame.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"
HARNESS = r'''
#include "mp4_actor_state.hpp"
#include <atomic>
#include <cassert>
#include <cmath>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
namespace mp4actor=idoly_mp4_actor;
struct Region {uintptr_t at;size_t size;};
std::vector<Region> regions;
bool unity_thread=true,source=true,held=true,live=true,mapped_code=true;
bool mp4_actor_source_verified=true;
std::atomic<bool>mp4_native_clock_source_ready{true};
uintptr_t mp4_native_base=1;
bool game_call(){return unity_thread;}
bool mp4_actor_selected_source(void*){return source;}
bool mp4_actor_clock_held(void*){return held;}
bool mp4_native_mapped(uintptr_t at,size_t n,int){
 for(const auto&r:regions)if(at>=r.at&&at-r.at<=r.size&&n<=r.size-(at-r.at))return true;
 return false;
}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){
 uintptr_t at=reinterpret_cast<uintptr_t>(p);if(offset>~uintptr_t(0)-at||!mp4_native_mapped(at+offset,sizeof out,1))return false;
 std::memcpy(&out,reinterpret_cast<void*>(at+offset),sizeof out);return true;
}
template<class T>void put(void*p,size_t offset,const T&v){std::memcpy(static_cast<uint8_t*>(p)+offset,&v,sizeof v);}
template<class T>T get(void*p,size_t offset){T out{};assert(mp4_actor_field(p,offset,out));return out;}
alignas(16)uint8_t object_bytes[64]{},native_bytes[1024]{},replacement[1024]{},vtable_bytes[512]{},animator_bytes[64]{},animator_native[1024]{};
bool skin=true;const char*type="UnityEngine.SkinnedMeshRenderer";
bool mp4_alive(void*p){return live&&p==object_bytes;}
bool mp4_exact_type(void*p,const char*name){return p==object_bytes&&std::string(type)==name;}
struct Owner{void*animator=nullptr;};
struct Host{size_t count=1;Owner owners[1]{{animator_bytes}};}mp4_actor_host;
struct Mp4BoundsCode{uintptr_t rva;uint8_t prefix[16];};
struct Mp4BoundsPins{Mp4BoundsCode base_set,skin_set,automatic;};
Mp4BoundsPins android_mp4_bounds_pins{},ios_mp4_bounds_pins{};
int base_sets=0,skin_sets=0,resets=0;bool drop_base=false,drop_skin=false,drop_reset=false;
std::string change_after;std::vector<std::string>calls;
void mutate(const char*phase){if(change_after==phase){source=false;}}
void base_set(void*n,const mp4actor::Bounds*b){
 assert(n==native_bytes);++base_sets;calls.emplace_back("base");if(!drop_base){put(n,0xd8,*b);put(n,0x128,get<uint32_t>(n,0x128)|0x800000u);}mutate("base");
}
void skin_set(void*n,const mp4actor::Bounds*b){
 assert(n==native_bytes);++skin_sets;calls.emplace_back("skin");if(!drop_skin){put(n,0x278,*b);put<uint8_t>(n,0x298,0);}mutate("skin");
 // Exact original skin setter tailcalls the base setter. This typed fixture
 // retains that order; AArch64 tests execute the unchanged tailcall itself.
 base_set(n,b);
}
void automatic(void*n){assert(n==native_bytes);++resets;calls.emplace_back("automatic");if(!drop_reset)put(n,0x128,get<uint32_t>(n,0x128)&~0x800000u);mutate("automatic");}
#ifdef HOST_IOS
#define IDOLY_DARWIN_BRIDGE 1
#endif
// ACTUAL_HOST
void install_pin(Mp4BoundsCode&pin,uintptr_t fn){pin.rva=fn-mp4_native_base;std::memcpy(pin.prefix,reinterpret_cast<void*>(fn),16);regions.push_back({fn,16});}
void setup(bool skinned,bool explicit_local){
 skin=skinned;type=skin?"UnityEngine.SkinnedMeshRenderer":"UnityEngine.MeshRenderer";
 for(auto r:{Region{reinterpret_cast<uintptr_t>(object_bytes),sizeof object_bytes},Region{reinterpret_cast<uintptr_t>(native_bytes),sizeof native_bytes},Region{reinterpret_cast<uintptr_t>(replacement),sizeof replacement},Region{reinterpret_cast<uintptr_t>(vtable_bytes),sizeof vtable_bytes},Region{reinterpret_cast<uintptr_t>(animator_bytes),sizeof animator_bytes},Region{reinterpret_cast<uintptr_t>(animator_native),sizeof animator_native}})regions.push_back(r);
 install_pin(android_mp4_bounds_pins.base_set,reinterpret_cast<uintptr_t>(base_set));install_pin(android_mp4_bounds_pins.skin_set,reinterpret_cast<uintptr_t>(skin_set));install_pin(android_mp4_bounds_pins.automatic,reinterpret_cast<uintptr_t>(automatic));ios_mp4_bounds_pins=android_mp4_bounds_pins;
 put(object_bytes,16,reinterpret_cast<uintptr_t>(native_bytes));put(native_bytes,0,reinterpret_cast<uintptr_t>(vtable_bytes));put<int32_t>(native_bytes,8,17);put(vtable_bytes,0x130,reinterpret_cast<uintptr_t>(skin?skin_set:base_set));
 put(animator_bytes,16,reinterpret_cast<uintptr_t>(animator_native));put<uint32_t>(native_bytes,0x128,0x4567u|(explicit_local?0x800000u:0));
 put(native_bytes,0xd8,mp4actor::Bounds{{1,2,3},{4,5,6}});put(native_bytes,0x278,mp4actor::Bounds{{10,20,30},{40,50,60}});
}
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];setup(mode!="mesh_auto"&&mode!="mesh_explicit",mode=="mesh_explicit"||mode=="skin_explicit");
 mp4actor::RendererBoundsImage saved{};
 if(mode=="wrong_thread")unity_thread=false;
 if(mode=="unverified")mp4_actor_source_verified=false;
 if(mode=="clock_unverified")mp4_native_clock_source_ready=false;
 if(mode=="source_changed")source=false;
 if(mode=="unheld")held=false;
 if(mode=="no_owners")mp4_actor_host.count=0;
 if(mode=="animator_job_pending")put<uint64_t>(animator_native,0x238,1);
 if(mode=="animator_job_version")put<int32_t>(animator_native,0x240,1);
 if(mode=="baseline_dirty")put<uint8_t>(native_bytes,0x298,1);
 if(mode=="dirty_invalid")put<uint8_t>(native_bytes,0x298,2);
 if(mode=="offscreen_invalid")put<uint8_t>(native_bytes,0x294,2);
 if(mode=="nonfinite")put(native_bytes,0xd8,mp4actor::Bounds{{1,std::numeric_limits<float>::infinity(),3},{4,5,6}});
 if(mode=="negative_extents")put(native_bytes,0x278,mp4actor::Bounds{{1,2,3},{-1,5,6}});
 if(mode=="prefix_bad")android_mp4_bounds_pins.base_set.prefix[0]^=0xff,ios_mp4_bounds_pins=android_mp4_bounds_pins;
 if(mode=="wrong_setter")put<uintptr_t>(vtable_bytes,0x130,1);
 if(mode=="wrong_type")type="Custom.SkinnedMeshRenderer";
 if(mode=="dead")live=false;
 if(mode=="pointer_unmapped")put<uintptr_t>(object_bytes,16,~uintptr_t(0)-8);
 if(mode=="offscreen")put<uint8_t>(native_bytes,0x294,1);
 const bool capture=mp4_actor_bounds_capture(object_bytes,&saved);
 const bool rejection=mode=="wrong_thread"||mode=="unverified"||mode=="clock_unverified"||mode=="source_changed"||mode=="unheld"||mode=="no_owners"||mode=="animator_job_pending"||mode=="animator_job_version"||mode=="baseline_dirty"||mode=="dirty_invalid"||mode=="offscreen_invalid"||mode=="nonfinite"||mode=="negative_extents"||mode=="prefix_bad"||mode=="wrong_setter"||mode=="wrong_type"||mode=="dead"||mode=="pointer_unmapped";
 if(rejection){assert(!capture&&calls.empty());return 0;}
 assert(capture&&mp4_actor_bounds_verify(object_bytes,&saved));
 if(mode=="current_unheld"){held=false;assert(mp4_actor_bounds_current(object_bytes,&saved));assert(!mp4_actor_bounds_verify(object_bytes,&saved)&&!mp4_actor_bounds_restore(object_bytes,&saved)&&calls.empty());return 0;}
 if(mode=="identity_native")put(object_bytes,16,reinterpret_cast<uintptr_t>(replacement));
 if(mode=="identity_id")put<int32_t>(native_bytes,8,18);
 if(mode=="identity_vtable")put(native_bytes,0,reinterpret_cast<uintptr_t>(replacement));
 if(mode=="identity_offscreen")put<uint8_t>(native_bytes,0x294,1);
 if(mode.rfind("identity_",0)==0){assert(!mp4_actor_bounds_current(object_bytes,&saved)&&!mp4_actor_bounds_restore(object_bytes,&saved)&&calls.empty());return 0;}
 put(native_bytes,0xd8,mp4actor::Bounds{{7,8,9},{10,11,12}});put(native_bytes,0x278,mp4actor::Bounds{{70,80,90},{100,110,120}});put<uint32_t>(native_bytes,0x128,0x804567);put<uint8_t>(native_bytes,0x298,1);
 if(mode=="drop_base")drop_base=true;
 if(mode=="drop_skin")drop_skin=true;
 if(mode=="drop_reset")drop_reset=true;
 if(mode=="source_after_skin")change_after="skin";
 if(mode=="source_after_base")change_after="base";
 if(mode=="source_after_reset")change_after="automatic";
 const bool restored=mp4_actor_bounds_restore(object_bytes,&saved);
 if(mode=="drop_base"||mode=="drop_skin"||mode=="drop_reset"||mode.rfind("source_after_",0)==0){
  assert(!restored);if(mode=="source_after_skin"||mode=="source_after_base")assert(!resets);return 0;
 }
 assert(restored&&mp4_actor_bounds_verify(object_bytes,&saved));
 assert(base_sets==(skin?2:1)&&skin_sets==(skin?1:0)&&resets==(saved.explicit_local?0:1));
 assert(get<uint32_t>(native_bytes,0x128)==(0x4567u|(saved.explicit_local?0x800000u:0)));
 assert(calls.front()==(skin?"skin":"base")&&calls.back()==(saved.explicit_local?"base":"automatic"));
 if(skin)assert(!std::memcmp(&saved.skin,native_bytes+0x278,sizeof saved.skin)&&!get<uint8_t>(native_bytes,0x298));
 assert(!std::memcmp(&saved.base,native_bytes+0xd8,sizeof saved.base));
}
'''


@pytest.fixture(scope="module", params=["android", "ios"])
def bounds_binary(tmp_path_factory, request):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if not compiler:
        pytest.skip("A host C++ compiler is required")
    source_text = (NATIVE / "bridge.cpp").read_text()
    actual = source_text.split("// BEGIN_MP4_RENDERER_BOUNDS_AUTHORITY_HOST\n", 1)[1].split("// END_MP4_RENDERER_BOUNDS_AUTHORITY_HOST", 1)[0]
    folder = tmp_path_factory.mktemp("bounds-host-" + request.param)
    source, binary = folder / "bounds.cpp", folder / "bounds"
    source.write_text(HARNESS.replace("// ACTUAL_HOST", actual))
    command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(NATIVE), str(source), "-o", str(binary)]
    if request.param == "ios":
        command.append("-DHOST_IOS=1")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", "mesh_auto mesh_explicit skin_auto skin_explicit offscreen wrong_thread unverified clock_unverified source_changed unheld no_owners animator_job_pending animator_job_version baseline_dirty dirty_invalid offscreen_invalid nonfinite negative_extents prefix_bad wrong_setter wrong_type dead pointer_unmapped current_unheld identity_native identity_id identity_vtable identity_offscreen drop_base drop_skin drop_reset source_after_skin source_after_base source_after_reset".split())
def test_actual_shipping_bounds_host_preserves_native_authority(bounds_binary, mode):
    result = subprocess.run([str(bounds_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
