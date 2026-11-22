"""Exercise shipping paused-frame preservation and real-copy retirement ordering."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def paused_frame(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    actual=text[text.index('// BEGIN_MP4_PAUSED_FRAME_SCOPE'):text.index('// END_MP4_PAUSED_FRAME_SCOPE')]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>
#include <stdexcept>
#include <string>
namespace idoly_mp4_camera_state {enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};}
'''
    driver=r'''
using namespace idoly_mp4_paused_frame;
void* ptr(uintptr_t n){return reinterpret_cast<void*>(n);}
bool begin_bad_ticket=false,complete_wait=false,external_alias=false,preservation_ready=true;int preserved=0;
bool live=true,held=true,thread=true,done=false,foreign=false,throw_copy=false,allocate_fail=false,begin_wait=false,root_fail=false,texture_changed=false;
int copies=0,begins=0,completes=0,retired=0,slot_writes=0,destroyed_rt=0,destroyed_capture=0,roots=0,release_roots=0;
uint32_t tokens[32]{};uintptr_t token_values[32]{};
Texture source{},backup{},final_target{};Image image{};
Api api(){Api a{};
 a.thread=[](){return thread;};a.current=[](void*,uint64_t e,uint64_t j){return live&&e==7&&j==9;};a.held=[](void*){return held;};
 a.image=[](void*,Image*out){*out=image;return true;};
 a.texture=[](void*,void*p,Texture*out){if(p!=backup.object)return false;*out=backup;if(texture_changed)++out->descriptor.format;return true;};
 a.allocate=[](void*,const Descriptor&d,Texture*out){backup={ptr(6),106,d};*out=backup;return allocate_fail?Result::failed:Result::ok;};
 a.copy_supported=[](void*,const Texture&,const Texture&){return !foreign;};
 a.copy_begin=[](void*,const Texture&,const Texture&,uint64_t*t){++begins;if(begin_wait){if(begin_bad_ticket)*t=11;return Result::waiting;}*t=11;done=false;return Result::ok;};
 a.copy_original=[](void*,void*s,void*d){assert(s!=d);++copies;if(throw_copy)throw std::runtime_error("copy");};
 a.copy_complete=[](void*,uint64_t t,bool ok){assert(t==11);++completes;return ok?(complete_wait?Result::waiting:Result::ok):Result::failed;};
 a.copy_poll=[](void*,uint64_t t){assert(t==11);return done?Result::ok:Result::waiting;};
 a.copy_retire=[](void*,uint64_t t){assert(t==11&&done);++retired;return true;};
 a.capture_slot=[](void*,void*old,void*replacement){assert(live&&held);if(image.captured_wrapper!=old)return false;image.captured_wrapper=replacement;++slot_writes;return true;};
 a.export_capture_owned=[](void*,void*p){return !foreign&&p==ptr(7);};
 a.capture_unreferenced=[](void*,void*){return !external_alias;};
 a.preserve_detached_capture=[](void*,void*p){assert(p==ptr(5));if(!preservation_ready)return false;++preserved;return true;};
 a.destroy_capture=[](void*,void*p){assert(p==ptr(7)&&!foreign);++destroyed_capture;return true;};
 a.destroy_texture=[](void*,Texture&t){assert(t.object==ptr(6));++destroyed_rt;t={};return true;};
 a.retain=[](void*p){if(root_fail)return uint32_t(0);const auto n=++roots;assert(n<32);tokens[n]=n;token_values[n]=reinterpret_cast<uintptr_t>(p);return uint32_t(n);};
 a.retained=[](uint32_t t){return tokens[t]?ptr(token_values[t]):nullptr;};
 a.release_root=[](uint32_t t){assert(tokens[t]);tokens[t]=0;++release_roots;};return a;
}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];
 Descriptor d{};d.width=256;d.height=144;d.samples=d.depth=d.mips=1;d.format=8;d.dimension=2;
 source={ptr(4),104,d};final_target={ptr(8),108,d};image={ptr(1),ptr(2),ptr(3),ptr(5),source,true};
 Scope s;auto a=api();
 if(mode=="missing_api"){a.copy_complete=nullptr;assert(s.capture(a,ptr(10),7,9)==Result::unsupported);return 0;}
 if(mode=="msaa")image.target.descriptor.samples=4;
 if(mode=="memoryless")image.target.descriptor.memoryless=1;
 if(mode=="pending_capture")image.capture_idle=false;
 if(mode=="msaa"||mode=="memoryless"||mode=="pending_capture"){assert(s.capture(a,ptr(10),7,9)==Result::unsupported&&!copies&&!slot_writes);return 0;}
 if(mode=="root_failure")root_fail=true;
 const auto captured=s.capture(a,ptr(10),7,9);
 if(mode=="root_failure"){assert(captured==Result::failed);s.abandon();assert(s.release()==Result::ok);return 0;}
 assert(captured==Result::ok);
 if(mode=="before_prepare_cancel"){assert(s.restore()==Result::ok&&s.restored()&&s.release()==Result::ok&&!copies);return 0;}
 if(mode=="allocation_failure")allocate_fail=true;
 if(mode=="shape_changed")texture_changed=true;
 if(mode=="copy_throws")throw_copy=true;
 if(mode=="start_wait"||mode=="bad_begin_ticket")begin_wait=true;
 if(mode=="bad_begin_ticket")begin_bad_ticket=true;
 if(mode=="complete_wait")complete_wait=true;
 auto first=s.prepare();
 if(mode=="bad_begin_ticket"||mode=="complete_wait"){assert(first==Result::failed||first==Result::waiting);assert(s.prepare()==Result::failed);s.abandon();done=true;assert(s.release()==Result::waiting&&!destroyed_rt);return 0;}
 if(mode=="allocation_failure"||mode=="shape_changed"){assert(first==Result::failed&&!copies);s.abandon();assert(s.release()==Result::ok&&destroyed_rt==1);return 0;}
 if(mode=="copy_throws"){assert(first==Result::failed&&copies==1&&completes==1);s.abandon();assert(s.release()==Result::waiting);done=true;assert(s.release()==Result::waiting&&!destroyed_rt);return 0;}
 if(mode=="start_wait"){assert(first==Result::waiting&&!copies&&!slot_writes);begin_wait=false;first=s.prepare();}
 assert(first==Result::waiting&&copies==1&&!slot_writes&&!s.ready());
 assert(s.prepare()==Result::waiting&&copies==1&&!slot_writes);
 if(mode=="source_lost_copying"){live=false;s.abandon();assert(s.release()==Result::waiting&&!destroyed_rt);done=true;assert(s.release()==Result::ok&&destroyed_rt==1&&!slot_writes);return 0;}
 done=true;assert(s.prepare()==Result::ok&&s.ready()&&slot_writes==1&&!image.captured_wrapper&&retired==1);
 assert(s.prepare()==Result::ok&&copies==1&&slot_writes==1);
 if(mode=="preserve_detached_wait"){live=false;s.abandon();preservation_ready=false;assert(s.release()==Result::waiting&&!destroyed_rt&&!preserved);preservation_ready=true;assert(s.release()==Result::ok&&preserved==1&&destroyed_rt==1);return 0;}
 if(mode=="source_lost_ready"){live=false;s.abandon();assert(s.release()==Result::ok&&slot_writes==1&&destroyed_rt==1);return 0;}
 if(mode=="restore_owed"){assert(s.release()==Result::invalid&&!destroyed_rt);s.abandon();assert(s.release()==Result::ok);return 0;}
 image.target_wrapper=ptr(9);image.target=final_target;image.captured_wrapper=ptr(7);
 if(mode=="foreign_capture")foreign=true;
 if(mode=="foreign_capture"){assert(s.restore()==Result::stale&&slot_writes==1&&copies==1);s.abandon();assert(s.release()==Result::ok&&!destroyed_capture);return 0;}
 if(mode=="restore_shape")++image.target.descriptor.width;
 if(mode=="restore_shape"){assert(s.restore()==Result::stale&&slot_writes==1);s.abandon();assert(s.release()==Result::ok);return 0;}
 if(mode=="restore_start_wait")begin_wait=true;
 assert(s.restore()==Result::waiting&&slot_writes==2&&image.captured_wrapper==ptr(5));
 if(mode=="restore_start_wait"){assert(copies==1);begin_wait=false;assert(s.restore()==Result::waiting&&copies==2&&slot_writes==2);}
 assert(copies==2&&!s.restored());assert(s.restore()==Result::waiting&&copies==2);
 assert(s.release()==Result::waiting&&!destroyed_capture&&!destroyed_rt);
 done=true;
 if(mode=="changed_after_restore_copy")image.target.native=999;
 if(mode=="changed_wrapper_after_copy")image.target_wrapper=ptr(90);
 if(mode=="changed_after_restore_copy"||mode=="changed_wrapper_after_copy"){assert(s.restore()==Result::stale&&!s.restored());s.abandon();assert(s.release()==Result::ok);return 0;}
 assert(s.restore()==Result::ok&&s.restored()&&retired==2);
 // Successful logical restoration is historical once ordinary callbacks resume.
 live=false;held=false;assert(s.restore()==Result::ok);
 if(mode=="external_identical_alias"){external_alias=true;assert(s.release()==Result::waiting&&!destroyed_capture&&!destroyed_rt);external_alias=false;}
 assert(s.release()==Result::ok);
 assert(destroyed_capture==1&&destroyed_rt==1&&release_roots==roots);
 assert(s.release()==Result::ok&&destroyed_capture==1&&destroyed_rt==1);
 if(mode=="second_job"){live=held=true;image={ptr(1),ptr(2),ptr(3),ptr(5),source,true};assert(s.capture(a,ptr(10),7,9)==Result::ok&&!s.ready()&&!s.restored());assert(s.prepare()==Result::waiting&&copies==3);done=true;assert(s.prepare()==Result::ok&&s.ready());s.abandon();assert(s.release()==Result::ok&&destroyed_rt==2);}
}
'''
    folder=tmp_path_factory.mktemp('paused-frame');source_file=folder/'test.cpp';binary=folder/'test'
    source_file.write_text(prefix+actual+driver)
    proc=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source_file),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stdout+proc.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','missing_api','msaa','memoryless','pending_capture','root_failure','before_prepare_cancel','allocation_failure','shape_changed','copy_throws','start_wait','source_lost_copying','source_lost_ready','restore_owed','foreign_capture','restore_shape','restore_start_wait','changed_after_restore_copy','changed_wrapper_after_copy','bad_begin_ticket','complete_wait','second_job','external_identical_alias','preserve_detached_wait'])
def test_shipping_paused_frame_copy_protocol(paused_frame,mode):
    result=subprocess.run([str(paused_frame),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
