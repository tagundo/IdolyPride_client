from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'client-presentation/native/bridge.cpp'


def function(source, name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    body = source.index('{', start)
    depth, end = 1, body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def compile_run(tmp_path, source):
    compiler = shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    path = tmp_path / 'fixture.cpp'
    path.write_text(source)
    binary = tmp_path / 'fixture'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_original_render_target_pixels_are_scoped_to_manual_owner_and_restored(tmp_path):
    source = BRIDGE.read_text()
    selected = '\n'.join(function(source, name) for name in ('mp4_output_geometry_owned', 'mp4_set_output_geometry'))
    compile_run(tmp_path, r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <vector>
#include <array>
struct Obj { unsigned char bytes[128]{};int32_t width=101,height=57;bool live=true; } a,b;
struct Weak {void* value=nullptr;void* get(bool=false)const{return value&&static_cast<Obj*>(value)->live?value:nullptr;}
    void set(void* next){value=next;}void clear(){value=nullptr;}} mp4_geometry_controller;
int32_t mp4_geometry_width=0,mp4_geometry_height=0,mp4_geometry_previous_width=0,mp4_geometry_previous_height=0;
bool mp4_geometry_active=false,unity=true,resize_ok=true;std::vector<std::array<int32_t,2>> calls;
namespace idoly_mp4_runtime {struct Game {bool active=true;bool manual()const{return active;}} game;}
bool game_call(){return unity;}bool mp4_type_is(void* p,const char*){return p==&a||p==&b;}
bool mp4_alive(void* p){return p&&static_cast<Obj*>(p)->live;}
bool mp4_actual_source_geometry(void* p,int32_t* w,int32_t* h){auto* value=static_cast<Obj*>(p);*w=value->width;*h=value->height;return value->live;}
template<class T>struct ScopedMemory {void* p;size_t offset;T original;bool apply;
 ScopedMemory(void* value,size_t at,bool enabled):p(value),offset(at),apply(enabled){std::memcpy(&original,static_cast<unsigned char*>(p)+offset,sizeof(T));}
 void set(T value){if(apply)std::memcpy(static_cast<unsigned char*>(p)+offset,&value,sizeof(T));}
 ~ScopedMemory(){if(apply)std::memcpy(static_cast<unsigned char*>(p)+offset,&original,sizeof(T));}};
void rt_original(void* p,int width,int height,bool alpha,void*){assert(!alpha);assert(!static_cast<Obj*>(p)->bytes[0x30]);
 calls.push_back({width,height});auto* value=static_cast<Obj*>(p);value->width=resize_ok?width:0;value->height=resize_ok?height:0;}
''' + selected + r'''
int main(){
 a.bytes[0x30]=1;b.bytes[0x30]=1;
 unity=false;assert(!mp4_set_output_geometry(&a,1920,1080)&&calls.empty());unity=true;
 idoly_mp4_runtime::game.active=false;assert(!mp4_set_output_geometry(&a,1920,1080)&&calls.empty());
 idoly_mp4_runtime::game.active=true;
 assert(!mp4_set_output_geometry(&a,1921,1080)&&!mp4_set_output_geometry(&a,0,1080)&&calls.empty());
 assert(mp4_set_output_geometry(&a,1920,1080));
 assert(a.width==1920&&a.height==1080&&a.bytes[0x30]==1&&mp4_output_geometry_owned(&a));
 assert(!mp4_output_geometry_owned(&b)&&!mp4_set_output_geometry(&b,3840,2160)&&calls.size()==1);
 assert(mp4_set_output_geometry(&a,3840,2160)&&mp4_geometry_previous_width==101&&mp4_geometry_previous_height==57);
 assert(mp4_set_output_geometry(&a,0,0)&&a.width==101&&a.height==57&&a.bytes[0x30]==1);
 assert(!mp4_geometry_active&&!mp4_output_geometry_owned(&a)&&!mp4_set_output_geometry(&a,0,0));
 resize_ok=false;assert(!mp4_set_output_geometry(&a,1920,1080)&&mp4_geometry_active);
 resize_ok=true;assert(mp4_set_output_geometry(&a,0,0)&&a.width==101&&a.height==57);
 assert(mp4_set_output_geometry(&a,1280,720));a.live=false;
 assert(!mp4_output_geometry_owned(&a));assert(mp4_set_output_geometry(&b,1920,1080));
 assert(mp4_geometry_previous_width==101&&mp4_geometry_previous_height==57);
 assert(mp4_set_output_geometry(&b,0,0)&&b.width==101&&b.height==57);
}
''')
