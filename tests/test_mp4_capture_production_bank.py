"""Actual constructor births retain partial captures independently of request success."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def bank(tmp_path_factory):
    cc=shutil.which('c++')
    if not cc:pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('capture-production');source=folder/'test.cpp';binary=folder/'test'
    header=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    body=header[header.index('// BEGIN_MP4_CAPTURE_PRODUCTION_BANK'):header.index('// END_MP4_CAPTURE_PRODUCTION_BANK')]
    source.write_text(r'''
#include <cstdint>
#include <cassert>
#include <string>
#include <stdexcept>
#include <unordered_map>
'''+body+r'''
using namespace idoly_mp4_capture_production;
struct Tex{uintptr_t native=0;};struct Wrapper{Tex*texture=nullptr;};
int controller=0,context=0,name=0;bool live=true,admission=true,pending=true,thread_ok=true,adopted=true,throw_name=false,fail_root=false;
uint32_t next_root=0;std::unordered_map<uint32_t,void*>roots;Wrapper*current_wrapper=nullptr;
int field_reads=0,native_reads=0;uint32_t sink_wrapper=0,sink_texture=0;Resource received{};
uint32_t retain(void*p){if(fail_root)return 0;roots[++next_root]=p;return next_root;}
Api api(){Api a{};a.thread=[](){return thread_ok;};a.current=[](void*c,uint64_t e,uint64_t j){return admission&&live&&c==&context&&e==7&&j==9;};
 a.assignment_current=[](void*c,uint64_t e,uint64_t j){return live&&c==&context&&e==7&&j==9;};
 a.owned_request=[](void*,void*c,uint64_t r){return pending&&c==&controller&&r==13;};
 a.owned_origin=[](void*,void*c,uint64_t r){return c==&controller&&r==13;};
 a.descriptor=[](void*,const Descriptor&d){return d.fields[0]==1920&&d.fields[1]==1080;};
 a.capture_name=[](void*,void*n){if(throw_name)throw std::runtime_error("name");return n==&name;};
 a.current_capture=[](void*,void*c,void**w,void**t){assert(c==&controller);++field_reads;*w=current_wrapper;*t=current_wrapper?current_wrapper->texture:nullptr;return true;};
 a.wrapper_texture=[](void*w,void**t){*t=static_cast<Wrapper*>(w)->texture;return true;};
 a.texture_native=[](void*t,uintptr_t*n){++native_reads;*n=static_cast<Tex*>(t)->native;return true;};
 a.retain=retain;a.retained=[](uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;};a.release=[](uint32_t r){assert(roots.erase(r)==1);};return a;}
bool adopt(void*,const Resource&r){if(!adopted)return false;received=r;sink_wrapper=retain(r.wrapper);if(r.texture)sink_texture=retain(r.texture);return true;}
void sink_release(){if(sink_wrapper)assert(roots.erase(sink_wrapper)==1);if(sink_texture)assert(roots.erase(sink_texture)==1);sink_wrapper=sink_texture=0;}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];Bank b;Descriptor d{};d.fields[0]=1920;d.fields[1]=1080;
 auto a=api();if(mode=="missing_api")a.texture_native=nullptr;
 bool configured=b.bind(a,&context,&controller,7,9,0x1110,0x1234,0x5678);
 if(mode=="missing_api"){assert(!configured);return 0;}assert(configured&&b.valid());
 Wrapper w;Tex t;
 if(mode=="destructor_partial_ctor"){
  try{auto u=b.update(&controller,13,0x1110);auto c=b.wrapper(&w,&d,&name,0x1234);auto r=b.texture(&t,&d,0x5678);t.native=101;throw std::runtime_error("original constructor");}
  catch(const std::runtime_error&){}
  Resource resource{};assert(b.historical(0,&resource)&&resource.native_known&&resource.native==101&&!resource.wrapper_returned&&!resource.texture_returned);
  assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
 if(mode=="capacity"){
  Wrapper wrappers[8];Tex textures[8];
  for(int i=0;i<8;++i){assert(b.can_prepare());auto u=b.update(&controller,13,0x1110);{auto c=b.wrapper(&wrappers[i],&d,&name,0x1234);{auto r=b.texture(&textures[i],&d,0x5678);textures[i].native=101+i;assert(r.finish(true));}wrappers[i].texture=&textures[i];assert(c.finish(true));}current_wrapper=&wrappers[i];assert(u.finish(true));}
  assert(b.count()==8&&!b.can_prepare());for(uint32_t i=0;i<8;++i){assert(b.transfer(i,&context,adopt));sink_release();}assert(b.finish()&&roots.empty());return 0;}
 if(mode=="wrong_controller"){int other;auto u=b.update(&other,13,0x1110);assert(!u.owned());auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned());assert(!b.count());return 0;}
 if(mode=="wrong_request"){auto u=b.update(&controller,14,0x1110);assert(!u.owned());auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned());assert(!b.count());return 0;}
 if(mode=="wrong_update_origin"){auto u=b.update(&controller,13,0x1114);assert(!u.owned()&&!u.owned_origin()&&!u.must_abort());
  auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned()&&!c.owned_origin()&&!c.must_abort()&&!b.count());return 0;}
 if(mode=="no_update"){auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned()&&!b.count());return 0;}
 if(mode=="bad_descriptor"){d.fields[0]=10;auto u=b.update(&controller,13,0x1110);auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned()&&!b.count());return 0;}
 if(mode=="wrong_wrapper_origin"){auto u=b.update(&controller,13,0x1110);auto c=b.wrapper(&w,&d,&name,0x1238);assert(!c.owned()&&!b.count());return 0;}
 if(mode=="wrong_name"){auto u=b.update(&controller,13,0x1110);auto c=b.wrapper(&w,&d,&controller,0x1234);assert(!c.owned()&&!b.count());return 0;}
 if(mode=="name_exception"){throw_name=true;auto u=b.update(&controller,13,0x1110);auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned()&&!b.valid());return 0;}
 if(mode=="nested_unowned"){auto u=b.update(&controller,13,0x1110);auto nested=b.update(&controller,14,0x1110);auto c=b.wrapper(&w,&d,&name,0x1234);assert(!c.owned()&&!b.count());return 0;}
 {
  auto u=b.update(&controller,13,0x1110);assert(u.owned());
  if(mode=="withdraw_before_wrapper"){
   live=false;auto c=b.wrapper(&w,&d,&name,0x1234);int original_calls=0;
   if(!c.must_abort())++original_calls;
   assert(c.owned_origin()&&c.must_abort()&&!original_calls&&!b.count());
   c.finish(false);u.finish(false);assert(b.finish()&&roots.empty());return 0;}
  if(mode=="wrapper_root_failure")fail_root=true;
  {
   auto c=b.wrapper(&w,&d,&name,0x1234);
   if(mode=="wrapper_root_failure"){
    int original_calls=0;if(!c.must_abort())++original_calls;
    assert(!c.owned()&&c.owned_origin()&&c.must_abort()&&!original_calls&&!b.valid());
    Resource r;assert(!b.historical(0,&r)&&b.transferred(0));c.finish(false);u.finish(false);
    assert(b.finish()&&roots.empty());return 0;}
   assert(c.owned()&&b.count()==1&&roots.size()==1);
   if(mode=="active_transfer"){assert(!b.transfer(0,&context,adopt)&&!b.finish());}
   if(mode=="wrong_texture_origin"){auto r=b.texture(&t,&d,0x567c);assert(!r.owned());return 0;}
   if(mode=="texture_root_failure")fail_root=true;
   {
    auto r=b.texture(&t,&d,0x5678);
    if(mode=="texture_root_failure"){
     int original_calls=0;if(!r.must_abort())++original_calls;
     assert(!r.owned()&&r.owned_origin()&&r.must_abort()&&!original_calls&&!b.valid());
     Resource resource;assert(b.historical(0,&resource)&&!resource.texture&&roots.size()==1);
     r.finish(false);c.finish(false);u.finish(false);fail_root=false;
     assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
    assert(r.owned()&&roots.size()==2);
    if(mode=="withdraw_inside_texture"){
     t.native=101;live=false;assert(r.finish(true)&&r.must_abort());c.finish(false);u.finish(false);
     Resource resource{};assert(b.historical(0,&resource)&&resource.texture_returned&&resource.native==101
      &&!resource.wrapper_returned&&!resource.assigned&&!w.texture);
     assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
    if(mode=="partial_texture_ctor"){
     t.native=101;assert(r.finish(false));assert(c.finish(false));assert(u.finish(false));
     Resource resource{};assert(b.historical(0,&resource)&&resource.texture==&t&&resource.native==101&&!resource.texture_returned&&!resource.wrapper_returned&&!resource.assigned);
     assert(!b.produced(&w,&t)&&b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
    if(mode!="zero_native")t.native=101;
    bool done=r.finish(true);
    if(mode=="zero_native"){assert(!done&&!b.valid());return 0;}
    assert(done);
   }
   w.texture=&t;
   if(mode=="wrapper_body_failure"){assert(c.finish(false));assert(u.finish(false));Resource resource{};assert(b.historical(0,&resource)&&resource.texture_returned&&!resource.wrapper_returned);assert(!b.produced(&w,&t));assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();return 0;}
   assert(c.finish(true));
  }
  if(mode=="unassigned_partial"){assert(u.finish(false));assert(!b.produced(&w,&t));assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
  current_wrapper=&w;
  if(mode=="admission_lost_after_assignment")admission=false;
  if(mode=="assignment_native_changed"){t.native=202;assert(!b.observe_assignment(&controller,13,&w,&t));return 0;}
  if(mode=="source_loss_before_assignment"){live=false;const int reads=field_reads;assert(u.finish(false));assert(field_reads==reads&&!b.produced(&w,&t));assert(b.transfer(0,&context,adopt)&&b.finish());sink_release();assert(roots.empty());return 0;}
  if(mode=="publication_assignment"){assert(b.observe_assignment(&controller,13,&w,&t)&&b.produced(&w,&t));}
  assert(u.finish(mode!="update_body_failure"));
 }
 assert(b.produced(&w,&t));Resource resource{};assert(b.produced(&w,&t,&resource)&&resource.assigned);
 if(mode=="request_end_failure"){pending=false;assert(b.produced(&w,&t));}
 if(mode=="handoff"){live=false;pending=false;current_wrapper=nullptr;const int reads=field_reads;assert(b.produced(&w,&t)&&b.historical(0,&resource));assert(field_reads==reads);}
 if(mode=="root_identity_lost"){roots[resource.texture_root]=&w;assert(!b.produced(&w,&t)&&!b.transfer(0,&context,adopt));return 0;}
 if(mode=="transfer_wait"){adopted=false;assert(!b.transfer(0,&context,adopt)&&roots.size()==2&&!b.finish());adopted=true;}
 assert(b.transfer(0,&context,adopt)&&received.wrapper==&w&&received.texture==&t&&received.native==101);
 assert(roots.size()==2&&!b.produced(&w,&t)&&!b.transfer(0,&context,adopt));assert(b.finish());sink_release();assert(roots.empty());
 if(mode=="second_job"){live=pending=true;assert(b.bind(api(),&context,&controller,7,9,0x1110,0x1234,0x5678)&&!b.count());}
}
''')
    p=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined',
        '-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=45)
    assert p.returncode==0,p.stdout+p.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','missing_api','wrong_controller','wrong_request','no_update','bad_descriptor',
    'wrong_wrapper_origin','wrong_name','name_exception','nested_unowned','wrapper_root_failure','wrong_texture_origin',
    'texture_root_failure','partial_texture_ctor','zero_native','wrapper_body_failure','unassigned_partial',
    'assignment_native_changed','source_loss_before_assignment','publication_assignment','update_body_failure',
    'handoff','root_identity_lost','transfer_wait','second_job','active_transfer','destructor_partial_ctor','capacity','request_end_failure',
    'withdraw_before_wrapper','withdraw_inside_texture','admission_lost_after_assignment','wrong_update_origin'])
def test_original_capture_production(bank,mode):
    p=subprocess.run([str(bank),mode],capture_output=True,text=True,timeout=6)
    assert p.returncode==0,p.stdout+p.stderr
