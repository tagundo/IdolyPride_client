"""Only the exact owned original CaptureRequest's global publication is omitted."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def guard(tmp_path_factory):
    cc=shutil.which('c++')
    if not cc:pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('capture-publication');source=folder/'test.cpp';binary=folder/'test'
    header=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    actual=header[header.index('// BEGIN_MP4_CAPTURE_PUBLICATION_GUARD'):header.index('// END_MP4_CAPTURE_PUBLICATION_GUARD')]
    source.write_text(r'''
#include <cstdint>
#include <cassert>
#include <atomic>
#include <string>
#include <stdexcept>
#include <thread>
'''+actual+r'''
using namespace idoly_mp4_capture_publication;
void*ptr(uintptr_t x){return reinterpret_cast<void*>(x);}
bool live=true,pending=true,private_capture=true,program=true,thread_ok=true,wrong_wrapper=false,drop_after_private=false;
bool throw_capture=false,throw_current=false;
bool issued=true;uint64_t issued_serial=13;
bool update_origin=true;
int current_calls=0;std::atomic<int> ordinary_calls{0};std::atomic<uintptr_t> shader_binding{1};
Api api(){Api a{};a.thread=[](){return thread_ok;};
 a.publication_origin=[](void*,void*controller,uint64_t request){return update_origin&&controller==ptr(12)&&request==issued_serial;};
 a.issued=[](void*c,void*camera,void*controller,uint64_t epoch,uint64_t job,uint64_t request){
  const bool match=issued&&c==ptr(10)&&camera==ptr(11)&&controller==ptr(12)&&epoch==7&&job==9&&request==issued_serial;
  if(match)issued=false;
  return match;};
 a.current=[](void*c,uint64_t e,uint64_t j){if(throw_current)throw std::runtime_error("current");++current_calls;return live&&c==ptr(10)&&e==7&&j==9;};
 a.owned_request=[](void*c,void*camera,void*controller,uint64_t request){return pending&&c==ptr(10)&&camera==ptr(11)&&controller==ptr(12)&&request==issued_serial;};
 a.current_capture=[](void*,void*controller,void**wrapper,void**texture){if(throw_capture)throw std::runtime_error("capture");assert(controller==ptr(12));*wrapper=wrong_wrapper?ptr(20):ptr(21);*texture=ptr(2);return true;};
 a.private_capture=[](void*,void*controller,void*wrapper,void*texture){assert(controller==ptr(12));bool result=private_capture&&wrapper==ptr(21)&&texture==ptr(2);if(drop_after_private)live=false;return result;};
 a.source_program=[](void*,uint64_t e,uint64_t j){return program&&e==7&&j==9;};return a;}
bool call(int32_t property=55,void*texture=ptr(2),uintptr_t caller=0x923d4e4){
 if(Request::suppress(property,texture,caller))return true;
 ++ordinary_calls;shader_binding.store(reinterpret_cast<uintptr_t>(texture));return false;
}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];Request r;Api a=api();
 if(mode=="no_request"){assert(!call()&&ordinary_calls==1&&shader_binding==2);return 0;}
 if(mode=="missing_api")a.private_capture=nullptr;
 if(mode=="program_unproved")program=false;
 if(mode=="unowned"){pending=false;issued=false;}
 if(mode=="revoked_before_enter")live=false;
 const bool entered=r.enter(a,ptr(10),ptr(11),ptr(12),7,9,13,55,0x923d4e4);
 if(mode=="missing_api"||mode=="unowned"){
  assert(!entered&&!call());auto receipt=r.finish();assert(!receipt.valid&&!receipt.suppressed&&ordinary_calls==1&&shader_binding==2);return 0;}
 if(mode=="program_unproved"||mode=="revoked_before_enter"){
  assert(!entered&&r.must_abort()&&Request::historical_origin(ptr(12))&&call());auto receipt=r.finish();
  assert(!receipt.valid&&receipt.suppressed==1&&!ordinary_calls&&shader_binding==1);return 0;}
 assert(entered);
 if(mode=="ordinary_update"){
  update_origin=false;assert(!call());auto q=r.finish();assert(q.valid&&q.issued&&!q.suppressed&&ordinary_calls==1&&shader_binding==2);return 0;}
 if(mode=="readonly_request"){auto q=r.finish();assert(q.valid&&!q.suppressed&&!q.wrapper&&!q.texture&&shader_binding==1&&ordinary_calls==0);return 0;}
 if(mode=="wrong_property"){assert(!call(56));auto q=r.finish();assert(q.valid&&!q.suppressed&&ordinary_calls==1&&shader_binding==2);return 0;}
 if(mode=="wrong_origin"){assert(!call(55,ptr(2),0x923d4e8));auto q=r.finish();assert(q.valid&&!q.suppressed&&ordinary_calls==1);return 0;}
 if(mode=="wrong_texture"){assert(call(55,ptr(3)));auto q=r.finish();assert(!q.valid&&q.suppressed==1&&!ordinary_calls&&shader_binding==1);return 0;}
 if(mode=="stale")live=false;
 if(mode=="request_changed")pending=false;
 if(mode=="wrong_wrapper")wrong_wrapper=true;
 if(mode=="unprotected_texture")private_capture=false;
 if(mode=="thread_changed")thread_ok=false;
 if(mode=="source_changed")program=false;
 if(mode=="midcheck_source_loss")drop_after_private=true;
 if(mode=="capture_exception")throw_capture=true;
 if(mode=="current_exception")throw_current=true;
 if(mode=="stale"||mode=="request_changed"||mode=="wrong_wrapper"||mode=="unprotected_texture"||mode=="thread_changed"||mode=="source_changed"||mode=="midcheck_source_loss"||mode=="capture_exception"||mode=="current_exception"){
  assert(call());auto q=r.finish();assert(!q.valid&&q.suppressed==1&&!ordinary_calls&&shader_binding==1);return 0;}
 if(mode=="other_thread"){std::thread t([]{assert(!call());});t.join();assert(ordinary_calls==1&&shader_binding==2);}
 if(mode=="nested_unowned"){
  Request child;assert(!child.enter(a,ptr(10),ptr(11),ptr(12),7,9,99,55,0x923d4e4));assert(!call());assert(!child.finish().valid);
  assert(ordinary_calls==1&&shader_binding==2);}
 if(mode=="nested_same_operation"){
  Request child;assert(!child.enter(a,ptr(10),ptr(11),ptr(12),7,9,13,55,0x923d4e4));
  assert(!Request::historical_origin(ptr(12))&&!child.must_abort()&&!call());
  assert(!child.finish().valid&&Request::historical_origin(ptr(12)));
 }
 assert(call());assert(ordinary_calls==(mode=="other_thread"||mode=="nested_unowned"||mode=="nested_same_operation"?1:0));
 if(mode=="external_after_owned"){assert(!call(56,ptr(3)));}
 if(mode=="duplicate"){assert(call());auto q=r.finish();assert(!q.valid&&q.suppressed==2&&!ordinary_calls&&shader_binding==1);return 0;}
 if(mode=="retired_after_suppress"){live=false;auto q=r.finish();assert(!q.valid&&q.suppressed==1&&!ordinary_calls&&shader_binding==1);return 0;}
 auto q=r.finish();assert(q.valid&&q.epoch==7&&q.job==9&&q.request==13&&q.controller==ptr(12)&&q.wrapper==ptr(21)&&q.texture==ptr(2)&&q.suppressed==1);
 if(mode=="direct_capture_pass"){
  // Protocol check: original CapturePass/adapter use current wrapper fields,
  // independently of the intentionally untouched paused-display shader global.
  void*pass_identifier=ptr(31);void*wrapper_texture=q.texture;
  assert(pass_identifier==ptr(31)&&wrapper_texture==ptr(2)&&shader_binding==1&&!ordinary_calls);}
 if(mode=="external_after_owned")assert(shader_binding==3&&ordinary_calls==1);
 else if(mode!="other_thread"&&mode!="nested_unowned"&&mode!="nested_same_operation")assert(shader_binding==1&&!ordinary_calls);
 assert(!r.finish().valid);
 if(mode=="reuse_request"){issued=true;issued_serial=14;assert(r.enter(a,ptr(10),ptr(11),ptr(12),7,9,14,55,0x923d4e4));assert(call());auto again=r.finish();assert(again.valid&&again.suppressed==1&&!ordinary_calls);}
 if(mode=="after_request"){assert(!call());assert(ordinary_calls==1&&shader_binding==2);}
}
''')
    p=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-pthread',
        '-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert p.returncode==0,p.stdout+p.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','no_request','missing_api','program_unproved','unowned','readonly_request',
    'wrong_property','wrong_origin','wrong_texture','stale','request_changed','wrong_wrapper','unprotected_texture',
    'thread_changed','source_changed','midcheck_source_loss','other_thread','nested_unowned','external_after_owned',
    'duplicate','retired_after_suppress','direct_capture_pass','after_request','capture_exception','current_exception','reuse_request',
    'revoked_before_enter','nested_same_operation','ordinary_update'])
def test_owned_native_publication(guard,mode):
    p=subprocess.run([str(guard),mode],capture_output=True,text=True,timeout=6)
    assert p.returncode==0,p.stdout+p.stderr
