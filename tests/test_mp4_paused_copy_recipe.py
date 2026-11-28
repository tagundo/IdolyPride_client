"""Actual paused-image copy host must bind raw entry, GPU ticket and retirement."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def copy_recipe(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text[text.index('// BEGIN_MP4_PAUSED_COPY_RECIPE_HOST'):text.index('// END_MP4_PAUSED_COPY_RECIPE_HOST')]
    prefix=r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
namespace mp4frame {
enum class Result:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct Descriptor{int32_t width=256,height=144,format=8;};struct Texture{void*object=nullptr;uintptr_t native=0;Descriptor descriptor{};};
}
enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
bool thread=true,live=true,supported=true,wait_begin=false,done=false,dispatched=false,throw_copy=false,no_fence=false,return_complete_ok=false;
int copies=0,begins=0,completes=0,retires=0,fail_root_at=0;uint64_t next_ticket=0,active_ticket=0;
uint32_t next_root=0;std::unordered_map<uint32_t,void*>roots;
bool game_call(){return thread;}bool mp4_scene_source_current(){return live;}
struct{bool verified=true;struct{uint64_t generation=7;}source;}mp4_camera_host;
struct{bool active=true;struct{uint64_t generation=7;}source;}mp4_scene_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
void*ptr(uintptr_t n){return reinterpret_cast<void*>(n);}
uint32_t mp4_retain(void*p){++next_root;if(fail_root_at==int(next_root))return 0;roots[next_root]=p;return next_root;}
void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t r){assert(roots.erase(r)==1);}
bool mp4_paused_texture_copy_supported(const mp4frame::Texture&a,const mp4frame::Texture&b){return supported&&a.object&&b.object&&a.object!=b.object&&a.native!=b.native&&!std::memcmp(&a.descriptor,&b.descriptor,sizeof(a.descriptor));}
void mp4_paused_texture_copy_original(void*a,void*b){assert(a!=b);++copies;if(throw_copy)throw 17;}
Mp4SceneResult mp4_gpu_auxiliary_begin(uint64_t,uint64_t,uint64_t,uint64_t*);
Mp4SceneResult mp4_gpu_auxiliary_complete(uint64_t,bool);
bool mp4_gpu_auxiliary_dispatched(uint64_t);
Mp4SceneResult mp4_gpu_auxiliary_poll(uint64_t);
bool mp4_gpu_auxiliary_retire(uint64_t);
'''
    driver=r'''
Mp4SceneResult mp4_gpu_auxiliary_begin(uint64_t s,uint64_t j,uint64_t r,uint64_t*t){++begins;assert(mp4_paused_copy_recipe_closed(s,j,r));*t=0;if(wait_begin)return Mp4SceneResult::waiting;assert(!active_ticket);*t=active_ticket=++next_ticket;done=dispatched=false;return Mp4SceneResult::ok;}
Mp4SceneResult mp4_gpu_auxiliary_complete(uint64_t t,bool returned){assert(t==active_ticket);++completes;if(!returned)return Mp4SceneResult::stale;dispatched=!no_fence;return return_complete_ok?Mp4SceneResult::ok:Mp4SceneResult::waiting;}
bool mp4_gpu_auxiliary_dispatched(uint64_t t){return t==active_ticket&&dispatched;}
Mp4SceneResult mp4_gpu_auxiliary_poll(uint64_t t){assert(t==active_ticket);return done?Mp4SceneResult::ok:Mp4SceneResult::waiting;}
bool mp4_gpu_auxiliary_retire(uint64_t t){if(t!=active_ticket||!done||!dispatched)return false;++retires;active_ticket=0;return true;}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];auto&h=mp4_paused_copy_bank;h.source=7;h.job=9;
 mp4frame::Texture a{ptr(1),101,{}},b{ptr(2),102,{}};uint64_t ticket=999;
 if(mode=="off_thread")thread=false;
 if(mode=="source_lost_before")live=false;
 if(mode=="job_changed")idoly_mp4_runtime::job.generation=10;
 if(mode=="unsupported")supported=false;
 if(mode=="nonce_overflow")mp4_paused_copy_nonce=0x0000ffffffffffffULL;
 auto*r=&h;
 if(mode=="foreign_context")r=nullptr;
 if(mode=="off_thread"||mode=="source_lost_before"||mode=="job_changed"||mode=="unsupported"||mode=="nonce_overflow"||mode=="foreign_context"){
  assert(mp4_paused_copy_begin(r,a,b,&ticket)!=mp4frame::Result::ok&&!ticket&&!copies&&!begins&&!h.count);return 0;}
 if(mode=="partial_root")fail_root_at=2;
 if(mode=="partial_root"){assert(mp4_paused_copy_begin(r,a,b,&ticket)==mp4frame::Result::failed&&!ticket&&roots.size()==1&&!begins);assert(mp4_paused_copy_abandon_prepared(7,9)&&roots.empty());assert(mp4_paused_copy_finish(7,9,true));return 0;}
 if(mode=="begin_wait"||mode=="wait_then_handoff"||mode=="wait_different_operands")wait_begin=true;
 auto start=mp4_paused_copy_begin(r,a,b,&ticket);
 if(wait_begin){assert(start==mp4frame::Result::waiting&&!ticket&&!copies&&h.count==1&&roots.size()==2);
  if(mode=="wait_then_handoff"){live=false;assert(mp4_paused_copy_abandon_prepared(7,9)&&roots.empty());assert(mp4_paused_copy_recipe_closed(7,9,h.records[0].recipe));assert(mp4_paused_copy_finish(7,9,true));return 0;}
  if(mode=="wait_different_operands"){mp4frame::Texture other{ptr(3),103,{}};assert(mp4_paused_copy_begin(r,b,other,&ticket)==mp4frame::Result::invalid&&!copies&&h.count==1);assert(mp4_paused_copy_abandon_prepared(7,9));return 0;}
  wait_begin=false;start=mp4_paused_copy_begin(r,a,b,&ticket);assert(h.count==1);
 }
 assert(start==mp4frame::Result::ok&&ticket==1&&roots.size()==2&&h.records[0].recipe==mp4_paused_copy_tag+1);
 assert(!mp4_paused_copy_recipe_closed(8,9,h.records[0].recipe)&&!mp4_paused_copy_recipe_closed(7,10,h.records[0].recipe)&&!mp4_paused_copy_recipe_closed(7,9,123));
 if(mode=="repeat_begin"){uint64_t second=999;assert(mp4_paused_copy_begin(r,a,b,&second)==mp4frame::Result::invalid&&!second&&begins==1);}
 if(mode=="wrong_operand"){try{mp4_paused_copy_original(r,b.object,a.object);assert(false);}catch(const Mp4PausedCopyRejected&){}assert(!copies&&!h.records[0].invoked);return 0;}
 if(mode=="source_lost_before_copy"){live=false;try{mp4_paused_copy_original(r,a.object,b.object);assert(false);}catch(const Mp4PausedCopyRejected&){}assert(!copies);return 0;}
 if(mode=="uninvoked_complete"){assert(mp4_paused_copy_complete(r,ticket,true)==mp4frame::Result::stale&&!dispatched&&!copies);return 0;}
 if(mode=="copy_throws")throw_copy=true;
 try{mp4_paused_copy_original(r,a.object,b.object);}catch(int code){assert(mode=="copy_throws"&&code==17);assert(mp4_paused_copy_complete(r,ticket,false)==mp4frame::Result::stale&&!dispatched);assert(!mp4_paused_copy_finish(7,9,true)&&roots.size()==2);return 0;}
 assert(copies==1&&h.records[0].invoked&&h.records[0].returned);
 if(mode=="no_fence")no_fence=true;
 if(mode=="complete_ready")return_complete_ok=true;
 if(mode=="no_fence"){assert(mp4_paused_copy_complete(r,ticket,true)==mp4frame::Result::failed&&!h.records[0].fenced);assert(!mp4_paused_copy_finish(7,9,true)&&roots.size()==2);return 0;}
 assert(mp4_paused_copy_complete(r,ticket,true)==mp4frame::Result::ok&&h.records[0].fenced);
 assert(mp4_paused_copy_complete(r,ticket,true)==mp4frame::Result::invalid&&completes==1);
 if(mode=="handoff_after_dispatch")live=false;
 assert(mp4_paused_copy_poll(r,ticket)==mp4frame::Result::waiting&&!mp4_paused_copy_retire(r,ticket)&&roots.size()==2);
 done=true;assert(mp4_paused_copy_poll(r,ticket)==mp4frame::Result::ok&&mp4_paused_copy_retire(r,ticket)&&roots.empty());
 assert(mp4_paused_copy_recipe_closed(7,9,h.records[0].recipe));
 assert(!mp4_paused_copy_finish(7,9,false)&&h.count==1);
 if(mode=="second_copy"){uint64_t second=0;assert(mp4_paused_copy_begin(r,b,a,&second)==mp4frame::Result::ok&&second==2&&h.count==2);
  mp4_paused_copy_original(r,b.object,a.object);assert(mp4_paused_copy_complete(r,second,true)==mp4frame::Result::ok);done=true;assert(mp4_paused_copy_retire(r,second)&&copies==2&&roots.empty());
  uint64_t third=0;assert(mp4_paused_copy_begin(r,a,b,&third)==mp4frame::Result::unsupported&&!third);}
 assert(mp4_paused_copy_finish(7,9,true)&&!h.count&&!h.source&&!h.job);
}
'''
    folder=tmp_path_factory.mktemp('paused-copy');src=folder/'test.cpp';binary=folder/'test';src.write_text(prefix+actual+driver)
    p=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(src),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stdout+p.stderr
    return binary
@pytest.mark.parametrize('mode',['normal','off_thread','source_lost_before','job_changed','unsupported','nonce_overflow','foreign_context','partial_root','begin_wait','wait_then_handoff','wait_different_operands','repeat_begin','wrong_operand','source_lost_before_copy','uninvoked_complete','copy_throws','no_fence','complete_ready','handoff_after_dispatch','second_copy'])
def test_actual_paused_copy_recipe_host(copy_recipe,mode):
    p=subprocess.run([str(copy_recipe),mode],capture_output=True,text=True,timeout=5)
    assert p.returncode==0,p.stdout+p.stderr
