"""Execute the actual native rebuild function across temporary surface loss."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("darwin", [False, True])
def test_original_rebuild_preserves_target_during_android_zero_size_and_retries(tmp_path,darwin):
    compiler=shutil.which("c++")
    if compiler is None:
        pytest.skip("Host C++ compiler unavailable")
    bridge=(ROOT/"client-presentation/native/bridge.cpp").read_text()
    start=bridge.index("void rebuild(void *controller) {")
    function=bridge[start:bridge.index("\n}\n",start)+3]
    source=tmp_path/"resize.cpp"
    source.write_text(r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include "presentation_scope.hpp"
using namespace idoly::presentation;
using Method=const void;
struct Dimensions {int width=0,height=0;};
struct Config {bool custom_graphics=true;int64_t revision=77;};
struct ResolutionAttempt {bool computed=false;Dimensions expected{};Config config{};int width=0,height=0;};
Config pending;
Config configuration(){return pending;}
int window_width=800,window_height=600;
int width(Method*){return window_width;}
int height(Method*){return window_height;}
int (*screen_width)(Method*)=width;
int (*screen_height)(Method*)=height;
thread_local void *resolution_scope=nullptr;
thread_local ResolutionAttempt *resolution_attempt=nullptr;
int destroy_calls=0,create_calls=0,acknowledge_calls=0;
int64_t acknowledged_revision=-1;
void *owned_export_controller=nullptr;
bool mp4_output_geometry_owned(void *controller){return controller&&controller==owned_export_controller;}
void destroy(void *controller,Method*){
 assert(resolution_scope==controller&&resolution_attempt);
 bool dynamic=true;std::memcpy(&dynamic,(char*)controller+0x30,sizeof dynamic);
 assert(dynamic==!pending.custom_graphics);++destroy_calls;
}
void create(void *controller,int w,int h,bool alpha,Method*){
 assert(resolution_scope==controller&&resolution_attempt&&w==-1&&h==-1&&!alpha);++create_calls;
 *resolution_attempt={true,{window_width,window_height},pending,window_width,window_height};
}
void (*rt_destroy)(void*,Method*)=destroy;
void (*rt_original)(void*,int,int,bool,Method*)=create;
void acknowledge_resolution(void *controller,const ResolutionAttempt &attempt){
 assert(resolution_scope==controller&&resolution_attempt==&attempt&&attempt.computed);
 ++acknowledge_calls;acknowledged_revision=attempt.config.revision;
}
''' + function + r'''
int main(){
 alignas(8) char controller[0x40]{};bool enabled=true;std::memcpy(controller+0x30,&enabled,sizeof enabled);
 ResolutionAttempt outer;void *previous=(void*)0x1234;resolution_scope=previous;resolution_attempt=&outer;
 // An active MP4 owns its exact target size. Ordinary graphics refresh must
 // not destroy or recreate that target, even with a valid drawable window.
 owned_export_controller=controller;rebuild(controller);
 assert(!destroy_calls&&!create_calls&&!acknowledge_calls&&acknowledged_revision==-1);
 bool unchanged=false;std::memcpy(&unchanged,controller+0x30,sizeof unchanged);assert(unchanged);
 assert(resolution_scope==previous&&resolution_attempt==&outer&&!outer.computed&&pending.revision==77);
 owned_export_controller=nullptr;
#ifndef IDOLY_DARWIN_BRIDGE
 for(auto dimensions:{Dimensions{0,600},Dimensions{800,0},Dimensions{0,0},Dimensions{-1,600},Dimensions{800,-1}}){
  window_width=dimensions.width;window_height=dimensions.height;
  // An invalid pointer makes any controller read/write before the guard fail.
  rebuild((void*)0x1);
  assert(!destroy_calls&&!create_calls&&!acknowledge_calls&&acknowledged_revision==-1);
  assert(resolution_scope==previous&&resolution_attempt==&outer&&!outer.computed&&pending.revision==77);
 }
 screen_width=nullptr;rebuild((void*)0x1);screen_width=width;
 screen_height=nullptr;rebuild((void*)0x1);screen_height=height;
 assert(!destroy_calls&&!create_calls&&!acknowledge_calls);
#endif
 window_width=800;window_height=600;rebuild(controller);
 assert(destroy_calls==1&&create_calls==1&&acknowledge_calls==1&&acknowledged_revision==77);
 bool restored=false;std::memcpy(&restored,controller+0x30,sizeof restored);assert(restored);
 assert(resolution_scope==previous&&resolution_attempt==&outer&&!outer.computed);
 pending.revision=78;
#ifndef IDOLY_DARWIN_BRIDGE
 window_width=0;window_height=0;rebuild((void*)0x1);
 assert(destroy_calls==1&&acknowledged_revision==77&&pending.revision==78);
#endif
 // The next valid size applies the same pending revision, once, normally.
 window_width=1200;window_height=800;rebuild(controller);
 assert(destroy_calls==2&&create_calls==2&&acknowledge_calls==2&&acknowledged_revision==78);
 assert(resolution_scope==previous&&resolution_attempt==&outer&&!outer.computed&&pending.revision==78);
 pending.custom_graphics=false;rebuild(controller);
 assert(destroy_calls==3&&create_calls==3&&acknowledge_calls==3);
#ifdef IDOLY_DARWIN_BRIDGE
 // The pre-existing Darwin implementation does not depend on these calls.
 screen_width=nullptr;screen_height=nullptr;rebuild(controller);assert(destroy_calls==4&&create_calls==4);
#endif
}
''')
    binary=tmp_path/"resize"
    flags=["-DIDOLY_DARWIN_BRIDGE=1"] if darwin else []
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",*flags,
        "-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(binary)],
        check=True,capture_output=True,timeout=20)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)


@pytest.mark.parametrize("darwin", [False,True])
def test_multiwindow_orientation_bypass_retains_configured_value_and_revision(tmp_path,darwin):
    compiler=shutil.which("c++")
    if compiler is None:
        pytest.skip("Host C++ compiler unavailable")
    bridge=(ROOT/"client-presentation/native/bridge.cpp").read_text()
    def function(name):
        start=bridge.index(name)
        return bridge[start:bridge.index("\n}\n",start)+3]
    wait=function("bool playback_wait_for_orientation() {")
    status=function("void playback_status_json(char *output,size_t size) {")
    setter=function('extern "C" JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedWindowing_setMultiWindow(')
    source=tmp_path/"orientation.cpp"
    source.write_text(r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <pthread.h>
#include <initializer_list>
#include "playback_config.hpp"
using namespace idoly::presentation;
using JNIEnv=void;using jclass=void*;using jboolean=unsigned char;
#define JNIEXPORT
#define JNICALL
pthread_mutex_t playback_mutex=PTHREAD_MUTEX_INITIALIZER;
PlaybackSettings playback_settings;
std::atomic<bool> ready{true};
std::atomic<bool> android_multi_window{false};
''' + wait + status + ("" if darwin else setter) + r'''
int main(){
 assert(playback_settings.accept(1,17,true));assert(playback_wait_for_orientation());
 char report[512];playback_status_json(report,sizeof report);
 assert(std::strstr(report,"\"revision\":17")&&std::strstr(report,"\"wait_for_orientation\":true"));
#ifndef IDOLY_DARWIN_BRIDGE
 Java_game_qualiarts_idolypride_localserver_UnifiedWindowing_setMultiWindow(nullptr,nullptr,1);
 assert(!playback_wait_for_orientation());
 playback_status_json(report,sizeof report);
 assert(std::strstr(report,"\"revision\":17")&&std::strstr(report,"\"wait_for_orientation\":true"));
 assert(playback_settings.wait()&&playback_settings.revision()==17);
 Java_game_qualiarts_idolypride_localserver_UnifiedWindowing_setMultiWindow(nullptr,nullptr,0);
 assert(playback_wait_for_orientation()&&playback_settings.revision()==17);
#else
 android_multi_window.store(true);assert(playback_wait_for_orientation());
#endif
 assert(playback_settings.accept(1,18,false));assert(!playback_wait_for_orientation());
#ifndef IDOLY_DARWIN_BRIDGE
 for(jboolean mode:{jboolean{1},jboolean{0},jboolean{1},jboolean{0}}){
  Java_game_qualiarts_idolypride_localserver_UnifiedWindowing_setMultiWindow(nullptr,nullptr,mode);
  assert(!playback_wait_for_orientation()&&!playback_settings.wait()&&playback_settings.revision()==18);
 }
#endif
 playback_status_json(report,sizeof report);
 assert(std::strstr(report,"\"revision\":18")&&std::strstr(report,"\"wait_for_orientation\":false"));
}
''')
    binary=tmp_path/"orientation"
    flags=["-DIDOLY_DARWIN_BRIDGE=1"] if darwin else []
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-pthread",*flags,
        "-I",str(ROOT/"client-presentation/native"),str(source),"-o",str(binary)],
        check=True,capture_output=True,timeout=20)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)
