"""Exercise exact shipping Mono callback routing before offline ownership."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def function(text,signature):
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


@pytest.fixture(scope='module')
def routes(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=function(bridge,'bool mp4_actor_present_callback_route(')
    prefix=r'''
#include "mp4_actor_state.hpp"
#include <cassert>
#include <cstring>
#include <string>
namespace mp4actor=idoly_mp4_actor;
uintptr_t image_base=0x100000;
struct Profile{mp4actor::ActorBinding actor_update{1,{}},actor_late{2,{}},derived_late_ref{3,{}},derived_late_shared{4,{}},eye_late{5,{}},face_late{6,{}},foot_apply{7,{}};}mp4_actor_profile;
uintptr_t method_pointer=0;bool found=true,mapped=true;std::string wanted;
void* object_class(void* object){return object;}
const void* method(void*,const char* name,int){wanted=name;return found?&method_pointer:nullptr;}
const void* (*font_method)(void*,const char*,int)=method;
template<class T> bool mp4_actor_field(void* p,size_t at,T& value){if(!mapped)return false;std::memcpy(&value,static_cast<char*>(p)+at,sizeof value);return true;}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];void* object=reinterpret_cast<void*>(1);
    auto phase=mp4actor::MonoPhase::actor_late;uintptr_t rva=2;const char* name="LateUpdate";
    if(mode=="update"){phase=mp4actor::MonoPhase::actor_update;rva=1;name="Update";}
    if(mode=="derived_ref")rva=3;if(mode=="derived_shared")rva=4;
    if(mode=="eye"){phase=mp4actor::MonoPhase::eye_late;rva=5;}
    if(mode=="face"){phase=mp4actor::MonoPhase::face_late;rva=6;}
    if(mode=="foot"){phase=mp4actor::MonoPhase::foot_apply;rva=7;name="ApplyJob";}
    bool expected=true;
    if(mode=="foreign_override"){rva=8;expected=false;}
    if(mode=="missing_method"){found=false;expected=false;}
    if(mode=="unmapped_method"){mapped=false;expected=false;}
    if(mode=="null_receiver"){object=nullptr;expected=false;}
    if(mode=="missing_capi"){font_method=nullptr;expected=false;}
    method_pointer=image_base+rva;
    assert(mp4_actor_present_callback_route(object,phase)==expected);
    if(object&&font_method)assert(wanted==name);
}
'''
    folder=tmp_path_factory.mktemp('actor-presentation-routes');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize('mode',['base','update','derived_ref','derived_shared','eye','face','foot','foreign_override','missing_method','unmapped_method','null_receiver','missing_capi'])
def test_shipping_callback_route_requires_verified_actual_entry(routes,mode):
    result=subprocess.run([str(routes),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
