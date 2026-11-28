"""Run shipping auxiliary-ticket composition without inventing RenderContext.

The explicit Ledger fixture controls GPU completion; physical driver behavior
is covered separately. These cases do not claim device execution.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module',params=['android','ios'])
def auxiliary(tmp_path_factory,request):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=bridge.split('// BEGIN_MP4_GPU_AUXILIARY_HOST',1)[1].split('// END_MP4_GPU_AUXILIARY_HOST',1)[0]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <string>
enum class Mp4SceneResult{ok,waiting,stale,unsupported,invalid};
bool thread_ok=true,recipe_ok=true,source_ok=true,configure_ok=true,gl_wait=false,dispatch_ok=true,proof_throws=false,dispatch_throws=false;
int configs=0,source_checks=0,dispatches=0,failed=0,retires=0,copy_calls=0;
bool game_call(){return thread_ok;}
namespace mp4_gpu_fence{
enum class Result{ready,waiting,quarantined};
Result completed=Result::waiting;
class Ledger{
 bool configured_=false,active_=false,unsafe_=false;uint64_t epoch_=0,sequence_=0,retired_=0;
public:
 void configure(uint64_t e){configured_=true;epoch_=e;}
 Result poll(uint64_t e,uint64_t=0){return !configured_||unsafe_||e!=epoch_?Result::quarantined:active_?Result::waiting:completed;}
 bool begin_auxiliary(uint64_t e,uint64_t s){if(!configured_||unsafe_||active_||e!=epoch_||s!=sequence_+1)return false;active_=true;sequence_=s;return true;}
 bool pending_auxiliary(uint64_t e,uint64_t s){return active_&&e==epoch_&&s==sequence_;}
 Result auxiliary_returned(uint64_t e,uint64_t s){assert(pending_auxiliary(e,s));++dispatches;if(dispatch_throws)throw std::runtime_error("fence");return Result::waiting;}
 bool last_dispatch_returned(){return dispatch_ok;}
 void auxiliary_failed(uint64_t e,uint64_t s){assert(pending_auxiliary(e,s));++failed;unsafe_=true;}
 bool end_auxiliary(uint64_t e,uint64_t s){assert(pending_auxiliary(e,s));active_=false;return !unsafe_;}
 bool retire_sequence(uint64_t e,uint64_t s){if(e!=epoch_||s!=retired_+1||poll(e,s)!=Result::ready)return false;++retires;retired_=s;return true;}
 void seal(uint64_t e){assert(e==epoch_);}
 bool release(uint64_t e){if(poll(e)!=Result::ready)return false;*this={};return true;}
};
struct Pins{};struct PinnedHost{};
}
struct Mp4GpuFenceHost{
 mp4_gpu_fence::PinnedHost pinned{};mp4_gpu_fence::Ledger ledger{};
 uint64_t source=0,epoch=0,sequence=0,retired=0,active_token=0,last_token=0,auxiliary_recipe=0;
 bool draw=false,configured=false,sealed=false;void*command_class=nullptr;
}mp4_gpu_fence_host;
mp4_gpu_fence::Pins mp4_gpu_pins;
bool closed(uint64_t s,uint64_t j,uint64_t r){return recipe_ok&&s==7&&j==9&&r;}
bool(*mp4_gpu_auxiliary_recipe_closed)(uint64_t,uint64_t,uint64_t)=closed;
bool mp4_gpu_host_sources(void*,const mp4_gpu_fence::Pins&){++source_checks;if(proof_throws)throw std::runtime_error("source");return source_ok;}
bool mp4_gpu_host_configure_for(Mp4GpuFenceHost&h,uint64_t s,uint64_t e,uint64_t r){++configs;if(!configure_ok)return false;h.source=s;h.epoch=e;h.auxiliary_recipe=r;h.configured=true;h.ledger.configure(e);return true;}
Mp4SceneResult mp4_gpu_gl_preflight_for(Mp4GpuFenceHost&,uint64_t,uint64_t){return gl_wait?Mp4SceneResult::waiting:Mp4SceneResult::ok;}
'''
    driver=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];using R=Mp4SceneResult;using F=mp4_gpu_fence::Result;
 uint64_t ticket=99;
 if(mode=="null_ticket"){assert(mp4_gpu_auxiliary_begin(7,9,11,nullptr)==R::invalid);return 0;}
 if(mode=="foreign_thread")thread_ok=false;
 if(mode=="missing_recipe")mp4_gpu_auxiliary_recipe_closed=nullptr;
 if(mode=="unknown_recipe")recipe_ok=false;
 if(mode=="configure_failure")configure_ok=false;
 if(mode=="gl_wait")gl_wait=true;
 if(mode=="render_inflight"||mode=="render_pending"||mode=="render_foreign"){
  auto&v=mp4_gpu_fence_host;mp4_gpu_host_configure_for(v,7,mode=="render_foreign"?10:9,0);
  v.sequence=1;v.draw=mode=="render_inflight";
 }
 R first=mp4_gpu_auxiliary_begin(7,9,11,&ticket);
 if(mode=="foreign_thread"||mode=="missing_recipe"||mode=="unknown_recipe"||mode=="render_foreign"){
  assert(first==R::stale&&!ticket&&!copy_calls);return 0;
 }
 if(mode=="configure_failure"){assert(first==R::unsupported&&!ticket&&!copy_calls);return 0;}
 if(mode=="render_inflight"||mode=="render_pending"){
  assert(first==R::waiting&&!ticket&&!copy_calls&&!mp4_gpu_auxiliary_host.configured);return 0;
 }
#ifndef IDOLY_DARWIN_BRIDGE
 if(mode=="gl_wait"){assert(first==R::waiting&&!ticket&&!copy_calls&&!configs);return 0;}
#endif
 assert(first==R::ok&&ticket&&mp4_gpu_auxiliary_host.draw&&!dispatches);
 const uint64_t initial=ticket;
 if(mode=="duplicate_begin"){uint64_t duplicate=55;assert(mp4_gpu_auxiliary_begin(7,9,11,&duplicate)==R::stale&&!duplicate&&mp4_gpu_auxiliary_host.active_token==initial);return 0;}
 if(mode=="wrong_complete"){assert(mp4_gpu_auxiliary_complete(ticket+1,true)==R::stale&&!dispatches&&mp4_gpu_auxiliary_host.draw);return 0;}
 ++copy_calls;
 if(mode=="proof_lost")source_ok=false;
 if(mode=="proof_exception")proof_throws=true;
 if(mode=="dispatch_exception")dispatch_throws=true;
 if(mode=="dispatch_unreturned")dispatch_ok=false;
 const bool returned=mode!="copy_exception";
 const R submitted=mp4_gpu_auxiliary_complete(ticket,returned);
 assert(!mp4_gpu_auxiliary_host.draw&&mp4_gpu_auxiliary_host.last_token==ticket);
 if(mode=="copy_exception"||mode=="proof_lost"||mode=="proof_exception"||mode=="dispatch_exception"){
  assert(submitted==R::stale&&failed==1&&mp4_gpu_auxiliary_poll(ticket)==R::stale&&!mp4_gpu_auxiliary_dispatched(ticket));
  assert(!mp4_gpu_auxiliary_retire(ticket)&&!mp4_gpu_auxiliary_finish(9));return 0;
 }
 if(mode=="dispatch_unreturned")assert(submitted==R::stale);else assert(submitted==R::waiting);
 assert(dispatches==1&&failed==0&&copy_calls==1);
 assert(mp4_gpu_auxiliary_dispatched(ticket)==(mode!="dispatch_unreturned"));
 assert(mp4_gpu_auxiliary_poll(ticket)==R::waiting&&!mp4_gpu_auxiliary_retire(ticket));
 const int proof_reads=source_checks;source_ok=false;
 mp4_gpu_fence::completed=F::ready;
 assert(mp4_gpu_auxiliary_poll(ticket)==R::ok&&mp4_gpu_auxiliary_retire(ticket)&&retires==1);
 assert(mp4_gpu_auxiliary_retire(ticket)&&retires==1&&source_checks==proof_reads);
 if(mode=="sequential"){
  source_ok=true;uint64_t second=0;assert(mp4_gpu_auxiliary_begin(7,9,12,&second)==R::ok&&second>ticket);
  assert(mp4_gpu_auxiliary_poll(ticket)==R::stale&&mp4_gpu_auxiliary_complete(ticket,true)==R::stale);
  assert(mp4_gpu_auxiliary_complete(second,true)==R::waiting&&mp4_gpu_auxiliary_poll(second)==R::ok&&mp4_gpu_auxiliary_retire(second));
 }
 assert(!mp4_gpu_auxiliary_finish(10)&&mp4_gpu_auxiliary_finish(9));
 assert(!mp4_gpu_auxiliary_host.configured&&mp4_gpu_auxiliary_poll(initial)==R::stale&&!mp4_gpu_auxiliary_dispatched(initial));
 if(mode=="reuse"){
  source_ok=true;uint64_t next=0;assert(mp4_gpu_auxiliary_begin(7,9,13,&next)==R::ok&&next>initial);
  assert(mp4_gpu_auxiliary_complete(initial,true)==R::stale&&mp4_gpu_auxiliary_host.draw);
 }
}
'''
    folder=tmp_path_factory.mktemp('gpu-aux-'+request.param);source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    cmd=[compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie']
    if request.param=='ios':cmd+=['-DIDOLY_DARWIN_BRIDGE']
    result=subprocess.run(cmd+[str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','null_ticket','foreign_thread','missing_recipe','unknown_recipe','configure_failure','gl_wait','render_inflight','render_pending','render_foreign','duplicate_begin','wrong_complete','copy_exception','proof_lost','proof_exception','dispatch_exception','dispatch_unreturned','sequential','reuse'])
def test_actual_auxiliary_owner_tickets_fence_and_retirement(auxiliary,mode):
    result=subprocess.run([str(auxiliary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
