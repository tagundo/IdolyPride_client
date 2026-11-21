"""Run the shipping ambient-render scope with explicit modeled global APIs.

No rendering/GPU assertion is made; the tests cover observer exception cleanup,
private Submit publication, and preserving ordinary calls during source handoff.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def unowned(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text.split('// BEGIN_MP4_UNOWNED_RENDER_HOST',1)[1].split('// END_MP4_UNOWNED_RENDER_HOST',1)[0]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <string>
using Method=const void;
struct Mp4RenderContext{void* pointer;};
struct Mp4RenderSubmission{Mp4RenderContext context{};uint64_t source_generation=7,job_generation=9,tick=4,draw_token=8;bool prewarm=false;};
using Mp4RenderCamera=void(*)(Mp4RenderContext,void*,Method*);
struct Host{bool invalidated=false;const char*error="none";}mp4_camera_host;
unsigned mp4_owned_render_depth=1;Mp4RenderSubmission mp4_owned_render_submission;
bool mp4_owned_render_ticket_active=true;
int globals=10,random_value=20,shader=30,calls=0,suspends=0,resumes=0;
bool nested=false,throw_original=false,handoff=false,failed_begin=false,failed_end=false,throw_begin=false,throw_end=false,reticket=false;
namespace idoly_mp4_actor{struct RandomSuspension{bool active=false;int saved=0;};}
struct Mp4ShaderSuspension{bool active=false;int saved=0;};
struct Rng{
 bool suspend_rng_for_unowned(idoly_mp4_actor::RandomSuspension&t){t.active=true;t.saved=random_value;random_value=2;return true;}
 bool resume_rng_after_unowned(idoly_mp4_actor::RandomSuspension&t){t.active=false;if(handoff)return false;random_value=t.saved;return true;}
}mp4_actor_mono_gate;
bool mp4_shader_suspend_for_unowned(Mp4ShaderSuspension&t){t.active=true;t.saved=shader;shader=3;return true;}
bool mp4_shader_resume_after_unowned(Mp4ShaderSuspension&t){t.active=false;if(handoff)return false;shader=t.saved;return true;}
bool suspend(uint64_t*t){++suspends;*t=8;globals=1;if(throw_begin)throw std::runtime_error("observer");return !failed_begin;}
bool resume(uint64_t t){assert(t==8);++resumes;if(handoff)return false;globals=10;if(throw_end)throw std::runtime_error("observer");return !failed_end;}
bool(*mp4_camera_suspend_extra_render)(uint64_t*)=suspend;
bool(*mp4_camera_resume_extra_render)(uint64_t)=resume;
void mp4_unowned_render_call(Mp4RenderCamera,Mp4RenderContext,void*,Method*);
void original(Mp4RenderContext context,void*camera,Method*method){
 assert(context.pointer==reinterpret_cast<void*>(1)&&camera==reinterpret_cast<void*>(2)&&method==reinterpret_cast<Method*>(3));
 ++calls;assert(!mp4_owned_render_ticket_active);assert(globals==1&&shader==(throw_begin?30:3));
 if(nested){nested=false;mp4_unowned_render_call(original,context,camera,method);}
 if(handoff){mp4_camera_host.invalidated=true;globals=77;random_value=88;shader=99;}
 if(reticket)++mp4_owned_render_submission.job_generation;
 if(throw_original)throw std::runtime_error("original");
}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 nested=mode=="nested";throw_original=mode=="original_throw"||mode=="original_and_cleanup_throw";
 handoff=mode=="handoff";failed_begin=mode=="begin_failed";failed_end=mode=="end_failed";
 throw_begin=mode=="begin_throw";throw_end=mode=="end_throw"||mode=="original_and_cleanup_throw";reticket=mode=="new_ticket";
 if(mode=="ticket_unpublished")mp4_owned_render_ticket_active=false;
 bool threw=false;try{mp4_unowned_render_call(original,{reinterpret_cast<void*>(1)},reinterpret_cast<void*>(2),reinterpret_cast<Method*>(3));}
 catch(const std::runtime_error&e){threw=true;assert(std::string(e.what())=="original");}
 assert(threw==throw_original);assert(calls==(mode=="nested"?2:1));assert(suspends==1&&resumes==1);assert(mp4_unowned_render_depth==0);
 const bool failed=handoff||failed_begin||failed_end||throw_begin||throw_end;
 assert(mp4_camera_host.invalidated==failed);
 assert(mp4_owned_render_ticket_active==(!failed&&!reticket&&mode!="ticket_unpublished"));
 if(handoff){assert(globals==77&&random_value==88&&shader==99);}
 else assert(globals==10&&random_value==20&&shader==30);
}
'''
    folder=tmp_path_factory.mktemp('unowned-render');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','nested','original_throw','handoff','begin_failed','end_failed','begin_throw','end_throw','original_and_cleanup_throw','new_ticket','ticket_unpublished'])
def test_shipping_ordinary_draw_uses_ambient_state_and_preserves_original(unowned,mode):
    result=subprocess.run([str(unowned),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
