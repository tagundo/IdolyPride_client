"""The capture shader binding must restore its actual prior value, including null."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def capture_global(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    text=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    actual=text[text.index('// BEGIN_MP4_CAPTURE_GLOBAL_LEASE'):text.index('// END_MP4_CAPTURE_GLOBAL_LEASE')]
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
namespace idoly_mp4_camera_state {enum class Result:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};}
'''
    driver=r'''
using namespace idoly_mp4_capture_global;
void*ptr(uintptr_t n){return reinterpret_cast<void*>(n);}
bool live=true,thread=true,held=true,quiet=true,lifetime=true,receipt=true,root_good=true,throw_set=false,drop_source=false,wrong_set=false,race_get=false;
Value global{};uint64_t sequence=1;int setters=0;uint32_t next_root=0;std::unordered_map<uint32_t,void*>roots;
Api api(){Api a{};a.thread=[](){return thread;};a.current=[](void*,uint64_t e,uint64_t j){return live&&e==7&&j==9;};a.held=[](void*){return held;};a.quiet=[](void*){return quiet;};
 a.serial=[](void*,int32_t p){assert(p==55);return sequence;};
 a.get=[](void*,int32_t p,Value*out){assert(p==55);*out=global;if(race_get)++sequence;return true;};
 a.baseline_lifetime=[](void*,const Value&){return lifetime;};
 a.capture_write=[](void*,uint64_t before,uint64_t after,const Value&v){return receipt&&after==before+1&&v.object==ptr(2);};
 a.set_original=[](void*,int32_t p,const Value&v,uint64_t before,uint64_t*after){assert(p==55);if(drop_source){live=false;return false;}if(sequence!=before)return false;++setters;global=v;if(wrong_set)global={ptr(3),303};*after=++sequence;if(throw_set)throw std::runtime_error("setter");return true;};
 a.retain=[](void*p){if(!root_good)return uint32_t(0);roots[++next_root]=p;return next_root;};a.retained=[](uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;};a.release_root=[](uint32_t h){assert(roots.erase(h)==1);};return a;
}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];Lease s;auto a=api();
 if(mode!="null_baseline")global={ptr(1),101};
 if(mode=="missing_api")a.capture_write=nullptr;
 if(mode=="unsafe_lifetime")lifetime=false;
 if(mode=="capture_race")race_get=true;
 if(mode=="zero_serial")sequence=0;
 if(mode=="root_failure")root_good=false;
 auto c=s.capture(a,ptr(10),7,9,55);
 if(mode=="missing_api"||mode=="unsafe_lifetime"||mode=="capture_race"||mode=="zero_serial"||mode=="root_failure"){
  assert(c!=Result::ok&&!setters);assert(s.release()==Result::ok&&roots.empty());return 0;}
 assert(c==Result::ok&&s.active());
 if(mode=="unchanged"){assert(s.observe_capture(sequence,sequence,global)==Result::ok);assert(s.restore()==Result::ok&&s.restored()&&!setters);assert(s.release()==Result::ok&&roots.empty());return 0;}
 if(mode=="release_owed"){assert(s.release()==Result::invalid);s.abandon();assert(s.release()==Result::ok&&roots.empty()&&!setters);return 0;}
 uint64_t before=sequence;global={ptr(2),202};++sequence;
 if(mode=="external_identical")receipt=false;
 if(mode=="two_writes")++sequence;
 if(mode=="external_identical"||mode=="two_writes"){
  assert(s.observe_capture(before,sequence,global)==Result::stale);assert(s.restore()==Result::stale&&!setters&&global.object==ptr(2));assert(s.release()==Result::ok&&roots.empty());return 0;}
 if(mode=="capture_during_tick")held=false;
 assert(s.observe_capture(before,sequence,global)==Result::ok);
 held=true;
 if(mode=="external_after_capture")++sequence;
 if(mode=="external_after_capture"){assert(s.restore()==Result::stale&&!setters&&global.object==ptr(2));assert(s.release()==Result::ok&&roots.empty());return 0;}
 if(mode=="gpu_wait"){quiet=false;assert(s.restore()==Result::waiting&&!setters);quiet=true;}
 if(mode=="held_wait"){held=false;assert(s.restore()==Result::waiting&&!setters);held=true;}
 if(mode=="source_retired")lifetime=false;
 if(mode=="source_retired"){assert(s.restore()==Result::stale&&!setters);s.abandon();assert(s.release()==Result::ok&&roots.empty());return 0;}
 if(mode=="source_lost"){live=false;assert(s.restore()==Result::stale&&!setters);s.abandon();assert(s.release()==Result::ok&&roots.empty());return 0;}
 if(mode=="setter_exception")throw_set=true;
 if(mode=="setter_source_handoff")drop_source=true;
 if(mode=="setter_wrong_value")wrong_set=true;
 if(mode=="setter_exception"||mode=="setter_source_handoff"||mode=="setter_wrong_value"){
  assert(s.restore()==Result::failed&&!s.restored());assert(s.restore()==Result::stale);assert(setters==(mode=="setter_source_handoff"?0:1));assert(s.release()==Result::ok&&roots.empty());return 0;}
 assert(s.restore()==Result::ok&&s.restored()&&setters==1);
 assert(global.object==(mode=="null_baseline"?nullptr:ptr(1)));
 live=false;assert(s.restore()==Result::ok);assert(s.release()==Result::ok&&roots.empty());
 if(mode=="second_job"){live=true;assert(s.capture(a,ptr(10),7,9,55)==Result::ok&&!s.restored());assert(s.restore()==Result::ok&&!roots.empty());assert(s.release()==Result::ok&&roots.empty());}
}
'''
    folder=tmp_path_factory.mktemp('capture-global');src=folder/'test.cpp';binary=folder/'test';src.write_text(prefix+actual+driver)
    p=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(src),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stdout+p.stderr
    return binary
@pytest.mark.parametrize('mode',['normal','null_baseline','missing_api','unsafe_lifetime','capture_race','zero_serial','root_failure','unchanged','release_owed','external_identical','two_writes','external_after_capture','gpu_wait','held_wait','source_retired','source_lost','setter_exception','setter_source_handoff','setter_wrong_value','second_job','capture_during_tick'])
def test_actual_capture_property_lease(capture_global,mode):
    p=subprocess.run([str(capture_global),mode],capture_output=True,text=True,timeout=5)
    assert p.returncode==0,p.stdout+p.stderr
