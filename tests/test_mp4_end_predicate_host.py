"""Exact shipping completion guards, with ordinary predicate calls observable."""
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
def guards(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual='\n'.join(function(bridge,'bool '+alias+'_hook(')for alias in ('mp4_photography_is_end','mp4_player_is_end'))
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <string>
using Method=const void;using Mp4EndPredicate=bool(*)(void*,Method*);
Mp4EndPredicate mp4_photography_is_end_original=nullptr,mp4_player_is_end_original=nullptr;
bool on_thread=true,active=true,replaced=false,cleanup_only=false;uint64_t source_generation=7,owned_generation=7;
void* player=reinterpret_cast<void*>(1);void* presenter=reinterpret_cast<void*>(2);Method* info=reinterpret_cast<Method*>(3);
int original_calls=0,owner_calls=0;bool playing=true;float remaining=.08f;
bool game_call(){return on_thread;}
namespace idoly_mp4_runtime {struct Game{bool owns_automatic_source_raw(void* object)const{
    ++owner_calls;return object&&active&&!replaced&&!cleanup_only&&source_generation==owned_generation&&(object==player||object==presenter);
}}game;}
void* expected=nullptr;
bool original_photo(void* object,Method* method){assert(object==expected&&method==info);++original_calls;return !playing||remaining<.1f;}
bool original_player(void* object,Method* method){assert(object==expected&&method==info);++original_calls;return !playing||remaining<.4f;}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==3);std::string mode=argv[1],kind=argv[2];
    mp4_photography_is_end_original=original_photo;mp4_player_is_end_original=original_player;
    expected=kind=="photo"?presenter:player;
    bool suppressed=true;
    if(mode=="foreign_receiver"){expected=reinterpret_cast<void*>(4);suppressed=false;}
    if(mode=="generation_changed"){++source_generation;suppressed=false;}
    if(mode=="same_pointer_reinitialized"){replaced=true;suppressed=false;}
    if(mode=="retired"){active=false;suppressed=false;}
    if(mode=="cleanup_waiting"){cleanup_only=true;suppressed=false;}
    if(mode=="foreign_thread"){on_thread=false;suppressed=false;}
    if(mode=="not_playing")playing=false;
    if(mode=="mid_margin")remaining=.2f;
    const bool result=kind=="photo"?mp4_photography_is_end_hook(expected,info):mp4_player_is_end_hook(expected,info);
    assert(original_calls==(suppressed?0:1));
    assert(result==(suppressed?false:(!playing||remaining<(kind=="photo"?.1f:.4f))));
    assert(owner_calls==(on_thread?1:0));
}
'''
    folder=tmp_path_factory.mktemp('end-predicates');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize('kind',['photo','player'])
@pytest.mark.parametrize('mode',['owned','restoring','mid_margin','not_playing','foreign_receiver','generation_changed','same_pointer_reinitialized','retired','cleanup_waiting','foreign_thread'])
def test_owned_completion_waits_but_ordinary_receivers_preserve_original(guards,kind,mode):
    result=subprocess.run([str(guards),mode,kind],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
