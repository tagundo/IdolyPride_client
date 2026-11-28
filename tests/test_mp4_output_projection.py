"""Execute the real MP4 RT/projection code with a synthetic original camera.

This checks full 3D frustum coverage and exact RT pixels. It does not claim
device/GPU validation; platform rendering is still verified on the user's build.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _function(source, name):
    start = source.index(name + "(")
    start = source.rfind("\n", 0, start) + 1
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PRELUDE = r'''
#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include <atomic>
#include <array>
#include <cassert>
#include <cstring>
#include <string>
#include <vector>
using namespace idoly::presentation;
using Method=const void;
struct Obj {
    unsigned char bytes[128]{};bool live=true,is_camera=false;
    int32_t width=1920,height=1080;Obj* camera=nullptr;Obj* controller=nullptr;
    bool manual_aspect=false,physical=false,ortho=false,custom_projection=false;
    float aspect=16.f/9.f,raw_fov=60,focal=50,sensor_x=36,sensor_y=24,shift_x=0,shift_y=0;
    bool horizontal_gate=false;Rect rect{};
} a,b,ca,cb;
struct Weak {void* value=nullptr;void* get(bool=false)const{return value&&static_cast<Obj*>(value)->live?value:nullptr;}
    void set(void* next){value=next;}void clear(){value=nullptr;}};
namespace idoly_mp4_runtime {struct Game {bool active=true,owned=true;
    bool manual()const{return active;}bool owned_scene_current()const{return active&&owned;}
    bool owned_primary_scene_current()const{return active&&owned;}} game;
    inline void diagnostic_event(const char*,const char*,uint64_t=0,uint64_t=0,bool=false){}}
std::atomic<bool> ready{true};bool unity=true,internal_camera=false,resize_ok=true;
unsigned aspect_writes=0,aspect_resets=0,lens_writes=0;bool owner_switch_on_resize=false;std::vector<std::array<int32_t,2>> calls;
bool game_call(bool=false){return unity;}
bool mp4_type_is(void* p,const char*){return p&&static_cast<Obj*>(p)->live&&!static_cast<Obj*>(p)->is_camera;}
bool mp4_alive(void* p){return p&&static_cast<Obj*>(p)->live;}
bool alive_callback(void* p,Method*){return mp4_alive(p);}
bool(*object_alive)(void*,Method*)=alive_callback;unsigned remembered_controllers=0;
void remember_controller(void*){++remembered_controllers;}
bool mp4_actual_source_geometry(void* p,int32_t* w,int32_t* h){auto* v=static_cast<Obj*>(p);if(!v||!v->live)return false;*w=v->width;*h=v->height;return true;}
void* get_camera(void* p,Method*){return static_cast<Obj*>(p)->camera;}
float get_aspect(void* p,Method*){auto* v=static_cast<Obj*>(p);return v->manual_aspect?v->aspect:static_cast<float>(v->controller->width)/v->controller->height;}
float get_fov(void* p,Method*){auto* v=static_cast<Obj*>(p);return v->physical?static_cast<float>(2*std::atan(v->sensor_y/(2*v->focal))*180/3.141592653589793):v->raw_fov;}
void set_fov(void* p,float value,Method*){auto* v=static_cast<Obj*>(p);++lens_writes;v->raw_fov=value;if(v->physical)v->focal=static_cast<float>(v->sensor_y/(2*std::tan(value*3.141592653589793/360)));}
float get_focal(void* p,Method*){return static_cast<Obj*>(p)->focal;}
void set_focal(void* p,float value,Method*){++lens_writes;static_cast<Obj*>(p)->focal=value;}
bool get_physical(void* p,Method*){return static_cast<Obj*>(p)->physical;}
bool get_ortho(void* p,Method*){return static_cast<Obj*>(p)->ortho;}
void get_rect(void* p,Rect* value,Method*){*value=static_cast<Obj*>(p)->rect;}
ProjectionMatrix projected(Obj* camera,float aspect){
    float vertical=std::tan(get_fov(camera,nullptr)*3.141592653589793/360);
    if(camera->physical&&camera->horizontal_gate)vertical=camera->sensor_x/(2*camera->focal*aspect);
    ProjectionMatrix m{};m.values[0]=1/(vertical*aspect);m.values[5]=1/vertical;
    m.values[8]=camera->shift_x;m.values[9]=camera->shift_y;m.values[11]=camera->custom_projection?0:-1;
    return m;
}
void get_projection(void* p,ProjectionMatrix* value,Method*){auto* v=static_cast<Obj*>(p);*value=projected(v,get_aspect(p,nullptr));}
void set_aspect(void* p,float value,Method*){auto* v=static_cast<Obj*>(p);v->manual_aspect=true;v->aspect=value;++aspect_writes;}
void reset_aspect(void* p,Method*){static_cast<Obj*>(p)->manual_aspect=false;++aspect_resets;}
void resize_target(void* p,int width,int height,bool alpha,Method*){auto* v=static_cast<Obj*>(p);assert(!alpha&&!v->bytes[0x30]);
    calls.push_back({width,height});v->width=resize_ok?width:0;v->height=resize_ok?height:0;
    if(owner_switch_on_resize){idoly_mp4_runtime::game.owned=false;v->width=640;v->height=360;v->bytes[0x30]=0;v->camera->raw_fov=33;}
}
void* (*rt_camera)(void*,Method*)=get_camera;
void (*rt_original)(void*,int,int,bool,Method*)=resize_target;
float (*fov_get_original)(void*,Method*)=get_fov,(*focal_get_original)(void*,Method*)=get_focal,(*aspect_get_original)(void*,Method*)=get_aspect;
void (*fov_set_original)(void*,float,Method*)=set_fov,(*focal_set_original)(void*,float,Method*)=set_focal;
void (*camera_aspect_set_original)(void*,float,Method*)=set_aspect;
void (*camera_aspect_reset)(void*,Method*)=reset_aspect;
void (*camera_rect_get)(void*,Rect*,Method*)=get_rect;
void (*projection_get)(void*,ProjectionMatrix*,Method*)=get_projection;
bool (*physical_get)(void*,Method*)=get_physical,(*orthographic)(void*,Method*)=get_ortho;
bool full_rect(Rect r){return std::fabs(r.x)<.001f&&std::fabs(r.y)<.001f&&std::fabs(r.width-1)<.001f&&std::fabs(r.height-1)<.001f;}
struct Photo {Weak controller,camera;bool expanded=false,base_known=false;CameraState original{};Frustum original_frustum{};float original_focal=50;} photo;
bool remember_original_lens(void*){assert(false);return false;}bool set_expanded_camera(void*){assert(false);return false;}void reject_current_projection(){assert(false);}
'''

DRIVER = r'''
Frustum frustum(Obj* camera,float aspect){Frustum f{};assert(perspective_frustum(projected(camera,aspect),&f));return f;}
void verify(Frustum required,int width,int height){
    assert(a.width==width&&a.height==height&&a.bytes[0x30]==1&&full_rect(ca.rect));
    assert(mp4_verify_output_projection(&a)&&!ca.manual_aspect);
    assert(frustum_contains(frustum(&ca,get_aspect(&ca,nullptr)),required));
}
int main(int argc,char** argv){
    assert(argc==2);std::string mode=argv[1];
    a.camera=&ca;b.camera=&cb;ca.controller=&a;cb.controller=&b;ca.is_camera=cb.is_camera=true;a.bytes[0x30]=b.bytes[0x30]=1;
    if(mode=="physical_vertical"||mode=="physical_horizontal"||mode=="physical_shift")ca.physical=true;
    if(mode=="physical_horizontal")ca.horizontal_gate=true;
    if(mode=="physical_shift"){ca.shift_x=.17f;ca.shift_y=-.13f;}
    if(mode=="manual_fail"||mode=="manual_equal")ca.manual_aspect=true;
    if(mode=="ortho")ca.ortho=true;
    if(mode=="custom_projection")ca.custom_projection=true;
    if(mode=="partial_rect")ca.rect.width=.9f;
    int width=1000,height=1500;
    if(mode=="landscape"||mode=="manual_equal"){width=3840;height=2160;}
    if(mode=="ultrawide"){width=4000;height=1000;}
    if(mode=="owner"){
        unity=false;assert(!mp4_set_output_geometry(&a,width,height)&&calls.empty());unity=true;
        idoly_mp4_runtime::game.active=false;assert(!mp4_set_output_geometry(&a,width,height)&&calls.empty());
        idoly_mp4_runtime::game.active=true;
        assert(!mp4_set_output_geometry(&a,1921,1080)&&!mp4_set_output_geometry(&a,0,1080)&&calls.empty());
        assert(mp4_set_output_geometry(&a,width,height)&&mp4_output_projection(&a,true));
        assert(!mp4_set_output_geometry(&b,width,height));assert(mp4_set_output_geometry(&a,0,0));return 0;
    }
    if(mode=="ortho"||mode=="custom_projection"||mode=="partial_rect"){
        assert(!mp4_set_output_geometry(&a,width,height)&&calls.empty());
        assert(mp4_set_output_geometry(&a,0,0)&&calls.empty());return 0;
    }
    if(mode=="photo_expanded"){
        photo.expanded=photo.base_known=true;photo.controller.set(&a);photo.camera.set(&ca);
        photo.original={16.f/9.f,60,{}};photo.original_frustum=frustum(&ca,16.f/9.f);photo.original_focal=50;
        a.width=1600;a.height=1200;ca.raw_fov=expanded_camera(photo.original,{1600,1200},true).vertical_fov;
    }
    const int previous_width=a.width,previous_height=a.height;
    const float previous_fov=get_fov(&ca,nullptr),previous_focal=ca.focal;
    const bool previous_manual=ca.manual_aspect;
    Frustum required=mode=="photo_expanded"?photo.original_frustum:frustum(&ca,get_aspect(&ca,nullptr));
    if(mode=="reentrant_apply"){
        owner_switch_on_resize=true;assert(!mp4_set_output_geometry(&a,width,height));
        assert(a.width==640&&a.height==360&&ca.raw_fov==33&&a.bytes[0x30]==0&&lens_writes==0);
        assert(!mp4_geometry_active&&!mp4_geometry_controller.get()&&!mp4_geometry_camera.get());return 0;
    }
    assert(mp4_set_output_geometry(&a,width,height));
    if(mode=="manual_fail"){
        assert(!mp4_output_projection(&a,true)&&aspect_writes==0&&aspect_resets==0&&ca.manual_aspect);
        assert(mp4_set_output_geometry(&a,0,0)&&ca.manual_aspect&&get_aspect(&ca,nullptr)==16.f/9.f);
        assert(aspect_writes==0&&aspect_resets==0);return 0;
    }
    assert(mp4_output_projection(&a,true));
    if(mode=="manual_equal"){
        assert(ca.manual_aspect&&aspect_writes==0&&aspect_resets==0&&mp4_verify_output_projection(&a));
    }else verify(required,width,height);
    if(mode=="dynamic_lens"||mode=="physical_shift"){
        for(unsigned frame=0;frame<240;++frame){
            if(mode=="physical_shift"){
                ca.sensor_y=20.f+(frame%13);ca.shift_x=.01f*(frame%17);ca.shift_y=-.01f*(frame%11);
                focal_set_hook(&ca,35.f+(frame%27),nullptr);
            }else fov_set_hook(&ca,35.f+(frame%31),nullptr);
            assert(!mp4_projection.required_known);
            const float baseline_fov=get_fov(&ca,nullptr),baseline_focal=ca.focal;
            required=frustum(&ca,mp4_projection.reference_aspect);
            assert(mp4_output_projection(&a,true));const float first_fov=get_fov(&ca,nullptr);
            verify(required,width,height);
            assert(std::fabs(fov_get_hook(&ca,nullptr)-baseline_fov)<.0001f);
            assert(std::fabs(focal_get_hook(&ca,nullptr)-baseline_focal)<.0001f);
            for(unsigned repeat=0;repeat<4;++repeat){assert(mp4_output_projection(&a,true));assert(std::fabs(get_fov(&ca,nullptr)-first_fov)<.0001f);}
        }
    }
    if(mode=="projection_lost"){
        ca.rect.width=.8f;assert(!mp4_output_projection(&a,false));ca.rect.width=1;
    }
    if(mode=="scene_reused"||mode=="destroyed"){
        auto count=calls.size();idoly_mp4_runtime::game.owned=false;
        a.width=640;a.height=360;ca.raw_fov=33;
        if(mode=="destroyed")a.live=ca.live=false;
        assert(mp4_set_output_geometry(nullptr,0,0)&&calls.size()==count&&ca.raw_fov==33&&a.width==640);
        assert(!mp4_geometry_active&&!mp4_geometry_controller.get()&&!mp4_geometry_camera.get());
        idoly_mp4_runtime::game.owned=true;assert(mp4_set_output_geometry(&b,1280,720)&&mp4_output_projection(&b,true));
        assert(mp4_set_output_geometry(&b,0,0)&&b.width==1920&&b.height==1080);return 0;
    }
    if(mode=="reentrant_rt_hook"){
        const auto remembered=remembered_controllers,previous_lens_writes=lens_writes;
        owner_switch_on_resize=true;rt_hook(&a,-1,-1,false,nullptr);
        assert(a.width==640&&a.height==360&&ca.raw_fov==33&&a.bytes[0x30]==0&&lens_writes==previous_lens_writes);
        assert(remembered_controllers==remembered+1&&!mp4_output_geometry_owned(&a));
        assert(mp4_set_output_geometry(nullptr,0,0));return 0;
    }
    if(mode=="reentrant_restore"){
        const auto previous_lens_writes=lens_writes;owner_switch_on_resize=true;
        assert(mp4_set_output_geometry(&a,0,0));
        assert(a.width==640&&a.height==360&&ca.raw_fov==33&&a.bytes[0x30]==0&&lens_writes==previous_lens_writes);
        assert(!mp4_geometry_active&&!mp4_geometry_controller.get()&&!mp4_geometry_camera.get());return 0;
    }
    if(mode=="restore_failure")resize_ok=false;
    const bool restored=mp4_set_output_geometry(&a,0,0);
    assert(restored==(mode!="restore_failure"));
    assert(!mp4_geometry_active&&!mp4_geometry_controller.get()&&!mp4_geometry_camera.get());
    assert(ca.manual_aspect==previous_manual);
    if(restored){
        assert(a.width==previous_width&&a.height==previous_height&&std::fabs(ca.focal-previous_focal)<.0001f);
        if(mode=="physical_shift"){
            // Sensor/shift belong to Cinemachine's timeline, not this override.
            // Its normal previous-time evaluation restores them after the RT
            // and original focal length have been restored by this callback.
            const float expected=static_cast<float>(2*std::atan(ca.sensor_y/(2*previous_focal))*180/3.141592653589793);
            assert(std::fabs(get_fov(&ca,nullptr)-expected)<.0001f);ca.sensor_y=24;ca.shift_x=.17f;ca.shift_y=-.13f;
        }
        assert(std::fabs(get_fov(&ca,nullptr)-previous_fov)<.0001f);
    }
    assert(mp4_set_output_geometry(&a,0,0));
}
'''


@pytest.fixture(scope="module")
def projection_executable(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    globals_ = source[source.index("Weak mp4_geometry_controller;"):source.index("idoly_mp4_replay_factories::Factory mp4_replay_factory;")]
    projection = source.split("// BEGIN_MP4_OUTPUT_PROJECTION\n", 1)[1].split("// END_MP4_OUTPUT_PROJECTION", 1)[0]
    hooks = "\n".join(_function(source, name) for name in ("fov_get_hook", "fov_set_hook", "focal_get_hook", "focal_set_hook"))
    directory = tmp_path_factory.mktemp("mp4-output-projection")
    path, binary = directory / "projection.cpp", directory / "projection"
    rt_start = source.index("void rt_hook(void *self,")
    owned_rt_hook = source[rt_start:source.index("    // A selected MV can create",rt_start)] + "}\n"
    path.write_text(PRELUDE + globals_ + projection + hooks + owned_rt_hook + DRIVER)
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I",
        str(ROOT / "client-presentation/native"), str(path), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("mode", ["landscape", "portrait", "ultrawide", "dynamic_lens", "physical_vertical",
    "physical_horizontal", "physical_shift", "manual_fail", "manual_equal", "ortho", "custom_projection",
    "partial_rect", "owner", "photo_expanded", "projection_lost", "restore_failure", "scene_reused", "destroyed", "reentrant_apply", "reentrant_restore", "reentrant_rt_hook"])
def test_original_rt_and_full_projection_without_padding(projection_executable, mode):
    result = subprocess.run([str(projection_executable), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
