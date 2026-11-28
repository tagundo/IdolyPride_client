"""Execute the actual typed URP outer boundary and getter forwarding code.

The fixture models scheduling/lease results explicitly; it does not render GPU
pixels or claim a device verification.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def function(text, signature):
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


@pytest.fixture(scope='module')
def render_host(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=function(bridge,'void mp4_camera_withdraw_render_ticket() noexcept {')+'\n'+function(bridge,'void mp4_context_submit_hook(')+'\n'+function(bridge,'void mp4_unowned_render_call(')+'\n'+function(bridge,'void mp4_owned_render_call(')
    getter=function(bridge,'void* mp4_selected_renderer_hook(')
    prefix=r'''
#include <cassert>
#include <atomic>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>
using Method=const void;
struct Mp4RenderContext{void* pointer;};
struct Mp4RenderSubmission{Mp4RenderContext context{};uint64_t source_generation=0,job_generation=0,tick=0,draw_token=0;bool prewarm=false;};
using VoidMethod=void(*)(void*,Method*);
using Mp4RenderCamera=void(*)(Mp4RenderContext,void*,Method*);
enum class Mp4SceneResult{ok,waiting,stale};
void* selected=reinterpret_cast<void*>(1);void* foreign=reinterpret_cast<void*>(2);Method* expected_method=reinterpret_cast<Method*>(3);
bool on_thread=true,source=true,route=true,ready=true,preview=false,root_grant=true,wait_extra=false,fail_extra=false,fail_motion=false,fail_rng=false,nest=false,throw_original=false,gpu_wait=false,gpu_late_wait=false,no_submit=false,submit_throw=false,record_fail=false,nest_foreign=false,foreign_reenter=false;
int original_calls=0,claims=0,rearms=0,completed=0,pre_completed=0,motion_begin=0,motion_end=0,extra_begin=0,extra_end=0,extra_restore=0,consumed=0,resolve_calls=0,submit_calls=0,gpu_recorded=0,gpu_failed=0,gpu_begin=0,gpu_end=0;
bool last_success=false;std::vector<int> order;
bool interception=true;
bool mp4_camera_interception_published()noexcept{return interception;}
bool game_call(){return on_thread;}
std::atomic<bool>mp4_stage_lease_active{false},mp4_stage_foreign_dirty{false};
struct Scope{bool enabled=true,permit=true;bool active(){return enabled;}bool render_tick(uint64_t& tick){tick=4;return true;}bool consume_render_grant(){++consumed;order.push_back(2);if(!permit)return false;permit=false;return true;}};
struct Host{Scope scope;struct Source{void* camera=selected;uint64_t generation=7;}source;bool invalidated=false;const char*error="none";}mp4_camera_host;
bool mp4_camera_source_current(void*){return source;}
bool mp4_camera_render_route_admit(){return route;}
namespace idoly_mp4_runtime{
uint64_t claim_native_prewarm_render(){++claims;if(!preview)return 0;return 9;}
uint64_t native_simulation_render_generation(uint64_t tick){assert(tick==4);return root_grant?9:0;}
void complete_native_prewarm_render(uint64_t gen,bool success){assert(gen==9);++pre_completed;last_success=success;}
void release_native_prewarm_render_claim(uint64_t gen){assert(gen==9);++rearms;}
void complete_native_simulation_render(uint64_t gen,uint64_t tick,bool success){assert(gen==9&&tick==4);++completed;last_success=success;root_grant=false;}
}
uint64_t mp4_camera_motion_begin_draw(){++motion_begin;return fail_motion?0:8;}
bool mp4_camera_motion_end_draw(uint64_t token){assert(token==8);++motion_end;return true;}
bool mp4_camera_motion_before_source_change(){return true;}
Mp4SceneResult begin_extra(uint64_t* token){++extra_begin;order.push_back(1);*token=0;if(wait_extra)return Mp4SceneResult::waiting;if(fail_extra)return Mp4SceneResult::stale;*token=7;return Mp4SceneResult::ok;}
bool end_extra(uint64_t token){assert(token==7);++extra_end;return true;}
void restore_extra(){++extra_restore;}
bool history_ready(){return ready;}
Mp4SceneResult(*mp4_camera_begin_extra_draw)(uint64_t*)=begin_extra;
bool(*mp4_camera_end_extra_draw)(uint64_t)=end_extra;
void(*mp4_camera_restore_extra_render_globals)()=restore_extra;
bool(*mp4_camera_render_history_ready)()=history_ready;
namespace idoly_mp4_actor{struct RandomSuspension{bool active=false;};}
struct Mp4ShaderSuspension{bool active=false;};
bool mp4_shader_suspend_for_unowned(Mp4ShaderSuspension&){return true;}
bool mp4_shader_resume_after_unowned(Mp4ShaderSuspension&){return true;}
bool suspend_extra(uint64_t* token){*token=0;return true;}
bool resume_extra(uint64_t){return true;}
bool(*mp4_camera_suspend_extra_render)(uint64_t*)=suspend_extra;
bool(*mp4_camera_resume_extra_render)(uint64_t)=resume_extra;
unsigned mp4_unowned_render_depth=0;
struct Rng{bool suspend_rng_for_unowned(idoly_mp4_actor::RandomSuspension&){return true;}bool resume_rng_after_unowned(idoly_mp4_actor::RandomSuspension&){return true;}template<class F>bool isolate_preview(F action){if(fail_rng)return false;action();return true;}template<class F>bool isolate_render(uintptr_t key,F action){assert(key==reinterpret_cast<uintptr_t>(selected));if(fail_rng)return false;action();return true;}}mp4_actor_mono_gate;
unsigned mp4_owned_render_depth=0;void* mp4_owned_render_camera=nullptr;
Mp4RenderSubmission mp4_owned_render_submission{};unsigned mp4_owned_render_submits=0;
bool mp4_owned_render_submission_failed=false,mp4_owned_render_ticket_active=false;
Mp4SceneResult gpu_preflight(uint64_t source,uint64_t generation){assert(source==7&&generation==9);return gpu_wait?Mp4SceneResult::waiting:Mp4SceneResult::ok;}
Mp4SceneResult begin_gpu(const Mp4RenderSubmission& s){assert(s.context.pointer==foreign&&s.source_generation==7&&s.job_generation==9&&s.draw_token==7);++gpu_begin;return gpu_late_wait?Mp4SceneResult::waiting:Mp4SceneResult::ok;}
bool record_gpu(const Mp4RenderSubmission& s){assert(s.context.pointer==foreign&&s.draw_token==7);++gpu_recorded;return !record_fail;}
void failed_gpu(const Mp4RenderSubmission& s){assert(s.context.pointer==foreign);++gpu_failed;}
bool end_gpu(const Mp4RenderSubmission& s){assert(s.context.pointer==foreign);++gpu_end;return true;}
Mp4SceneResult(*mp4_camera_gpu_preflight)(uint64_t,uint64_t)=gpu_preflight;
Mp4SceneResult(*mp4_camera_begin_gpu_draw)(const Mp4RenderSubmission&)=begin_gpu;
bool(*mp4_camera_record_submit)(const Mp4RenderSubmission&)=record_gpu;
void(*mp4_camera_submit_failed)(const Mp4RenderSubmission&)=failed_gpu;
bool(*mp4_camera_end_gpu_draw)(const Mp4RenderSubmission&)=end_gpu;
bool mp4_actor_field(void* p,size_t offset,Mp4RenderContext& out){assert(offset==0);out=*static_cast<Mp4RenderContext*>(p);return true;}
void raw_submit(void* p,Method* method){assert(p&&method==expected_method);++submit_calls;if(submit_throw)throw std::runtime_error("Submit");}
VoidMethod mp4_context_submit_original=raw_submit;
void mp4_context_submit_hook(void*,Method*);

void mp4_owned_render_call(Mp4RenderCamera,Mp4RenderContext,void*,Method*);
void original(Mp4RenderContext context,void* camera,Method* method){assert(context.pointer==foreign&&method==expected_method);++original_calls;if(nest_foreign){nest_foreign=false;mp4_owned_render_call(original,context,foreign,method);}if(foreign_reenter&&camera==foreign){foreign_reenter=false;mp4_owned_render_call(original,context,selected,method);}if(nest){nest=false;mp4_owned_render_call(original,context,camera,method);}if(throw_original)throw std::runtime_error("original");if(!no_submit)mp4_context_submit_hook(&context,method);}
namespace mp4cam{enum class RendererResolve{forward,owned,error};struct RendererResolution{RendererResolve kind;void*renderer;bool original_called;};}
mp4cam::RendererResolution resolution{mp4cam::RendererResolve::forward,nullptr,false};
struct Publication{mp4cam::RendererResolution resolve(void* object){assert(object==selected);++resolve_calls;return resolution;}}mp4_renderer_publication;
void* getter_original(void* object,Method* method){assert(object==selected&&method==expected_method);++original_calls;return foreign;}
void*(*mp4_selected_renderer_original)(void*,Method*)=getter_original;
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
    if(mode.rfind("getter_",0)==0){
        void* expected=foreign;
        if(mode=="getter_foreign_thread")on_thread=false;
        if(mode=="getter_owned"){resolution={mp4cam::RendererResolve::owned,selected,false};expected=selected;}
        if(mode=="getter_error_called"){resolution={mp4cam::RendererResolve::error,selected,true};expected=selected;}
        if(mode=="getter_error_null"){resolution={mp4cam::RendererResolve::error,nullptr,true};expected=nullptr;}
        if(mode=="getter_error_forward")resolution={mp4cam::RendererResolve::error,nullptr,false};
        assert(mp4_selected_renderer_hook(selected,expected_method)==expected);
        assert(original_calls==((mode=="getter_owned"||mode=="getter_error_called"||mode=="getter_error_null")?0:1));
        assert(resolve_calls==(on_thread?1:0));
        assert(mp4_camera_host.invalidated==(mode.rfind("getter_error",0)==0));return 0;
    }
    if(mode=="withdrawn")interception=false;
    if(mode=="withdrawn_nested"){interception=false;mp4_owned_render_depth=1;mp4_owned_render_ticket_active=true;mp4_camera_withdraw_render_ticket();}
    if(mode=="foreign_thread")on_thread=false;
    if(mode=="unowned")mp4_camera_host.scope.enabled=false;
    if(mode=="ordinary_submit"){Mp4RenderContext c{foreign};mp4_context_submit_hook(&c,expected_method);assert(submit_calls==1&&!gpu_recorded&&!gpu_failed);return 0;}
    if(mode=="held")root_grant=false;
    if(mode=="gpu_wait")gpu_wait=true;
    if(mode=="gpu_late_wait")gpu_late_wait=true;
    if(mode=="no_submit")no_submit=true;
    if(mode=="submit_throw")submit_throw=true;
    if(mode=="record_fail")record_fail=true;
    if(mode=="prewarm"||mode=="prewarm_wait")preview=true;
    if(mode=="wait"||mode=="prewarm_wait")wait_extra=true;
    if(mode=="extra_error")fail_extra=true;
    if(mode=="motion_error")fail_motion=true;
    if(mode=="rng_error")fail_rng=true;
    if(mode=="nested")nest=true;
    if(mode=="nested_unowned"||mode=="nested_unowned_selected_reentry")nest_foreign=true;
    if(mode=="nested_unowned_selected_reentry")foreign_reenter=true;
    if(mode=="throw_original")throw_original=true;
    bool threw=false;try{mp4_owned_render_call(original,{foreign},selected,expected_method);}catch(const std::runtime_error&){threw=true;}
    if(mode=="withdrawn_nested"){assert(original_calls==1&&submit_calls==1&&!gpu_recorded&&!completed&&mp4_owned_render_depth==1&&!mp4_owned_render_ticket_active);return 0;}
    assert(threw==(mode=="throw_original"||mode=="submit_throw"));assert(!mp4_owned_render_depth&&!mp4_owned_render_camera);
    if(mode=="foreign_thread"||mode=="unowned"){assert(original_calls==1&&!extra_begin&&!completed&&!pre_completed);return 0;}
    if(mode=="withdrawn"){assert(original_calls==1&&!extra_begin&&!consumed&&!completed&&!gpu_begin);return 0;}
    if(mode=="held"){assert(!original_calls&&!extra_begin&&!consumed&&!completed);return 0;}
    if(gpu_wait||gpu_late_wait){
        assert(!original_calls&&!consumed&&!motion_begin&&!completed&&!pre_completed);
        assert(extra_begin==(gpu_late_wait?1:0)&&extra_end==(gpu_late_wait?1:0));
        gpu_wait=gpu_late_wait=false;mp4_owned_render_call(original,{foreign},selected,expected_method);
        assert(original_calls==1&&gpu_recorded==1&&last_success);return 0;
    }
    if(mode=="no_submit"||mode=="submit_throw"||mode=="record_fail"){
        assert(original_calls==1&&!last_success&&completed==1&&gpu_end==1);
        assert(gpu_failed==((submit_throw||record_fail)?1:0));assert(gpu_recorded==(record_fail?1:0));return 0;
    }
    if(wait_extra){assert(!original_calls&&!consumed&&!motion_begin&&!completed&&!pre_completed&&!extra_restore);assert(rearms==(preview?1:0));wait_extra=false;
        mp4_owned_render_call(original,{foreign},selected,expected_method);assert(original_calls==1&&last_success);return 0;}
    if(mode=="extra_error"){assert(!original_calls&&!consumed&&!motion_begin&&!last_success&&completed==1);return 0;}
    assert(extra_begin==1&&extra_end==1&&motion_begin==1);
    if(preview)assert(!consumed&&pre_completed==1&&!completed);else{assert(consumed==1&&completed==1&&!pre_completed);assert(order==std::vector<int>({1,2}));}
    if(mode=="motion_error"||mode=="rng_error"){assert(!original_calls&&!last_success);return 0;}
    if(mode=="nested_unowned_selected_reentry"){assert(mp4_camera_host.invalidated&&!last_success&&!gpu_recorded&&original_calls==2);return 0;}
    if(mode=="nested_unowned"){assert(gpu_recorded==1&&submit_calls==2&&last_success&&original_calls==2);return 0;}
    assert(original_calls==(mode=="nested"?2:1));assert(motion_end==1&&last_success!=throw_original);
    const int before=original_calls;mp4_owned_render_call(original,{foreign},selected,expected_method);
    if(!preview)assert(original_calls==before);
}
'''
    folder=tmp_path_factory.mktemp('render-host');source_file=folder/'test.cpp';binary=folder/'test'
    source_file.write_text(prefix+actual+'\n'+getter+driver)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',str(source_file),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize('mode',['normal','withdrawn_nested','withdrawn','nested','nested_unowned','nested_unowned_selected_reentry','held','ordinary_submit','gpu_wait','gpu_late_wait','no_submit','submit_throw','record_fail','wait','prewarm','prewarm_wait','extra_error','motion_error','rng_error','throw_original','foreign_thread','unowned','getter_forward','getter_foreign_thread','getter_owned','getter_error_called','getter_error_null','getter_error_forward'])
def test_actual_outer_draw_and_renderer_getter_preserve_tickets_and_forwarding(render_host,mode):
    result=subprocess.run([str(render_host),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
