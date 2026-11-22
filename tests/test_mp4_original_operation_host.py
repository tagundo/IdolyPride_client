"""Verify the actual raw-original receipt, including unwind and nested scopes."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

def function(text,signature):
    a=text.index(signature);o=text.index('{',a);depth=1;b=o+1
    while depth:
        depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[a:b]

@pytest.fixture(scope='module')
def original_operation(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    a=text.index('struct Mp4RawOriginalOperation {');b=text.index('struct Mp4OriginalEvaluationScope',a)
    actual=text[a:b]+'\n'+function(text,'[[maybe_unused]] bool mp4_director_actual_operation(')
    prefix=r'''
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <string>
namespace mp4_director_maintenance{
enum class Kind:uint8_t{play=1,stop=2,rebuild=3,zero_evaluate=4,saved_evaluate=5,maintenance=6};
struct Call{Kind kind=Kind::play;uint64_t epoch=0,serial=0;uintptr_t source_asset=0,receiver=0,method=0;uint64_t original_receipt=0;};
}
bool thread=true,current=true;
bool game_call(){return thread;}
bool mp4_scene_source_current(){return current;}
struct SceneHost{bool active=true;void*root_asset=reinterpret_cast<void*>(11);uint32_t root_asset_handle=1;struct Source{uint64_t generation=7;}source;}mp4_scene_host;
struct Ledger{uint64_t epoch=7;void*asset=reinterpret_cast<void*>(11);}mp4_rebuild_ledger;
void* mp4_scene_root_asset_receipt(uint64_t epoch){return epoch==mp4_rebuild_ledger.epoch?mp4_rebuild_ledger.asset:nullptr;}
'''
    driver=r'''
int main(int argc,char**argv){
 assert(argc==2);std::string mode=argv[1];using C=mp4_director_maintenance::Call;using K=mp4_director_maintenance::Kind;
 C call{};call.serial=99;assert(!mp4_director_actual_operation(&call)&&!call.serial);
 if(mode=="null_output"){assert(!mp4_director_actual_operation(nullptr));return 0;}
 if(mode=="sequence_overflow")mp4_raw_original_sequence=~uint64_t(0);
 if(mode=="depth_limit")mp4_raw_original_operation.depth=8;
 if(mode=="asset_missing")mp4_rebuild_ledger.asset=nullptr;
 if(mode=="eval_overflow")mp4_raw_evaluate_sequence=~uint64_t(0);
 const bool eval=mode=="zero"||mode=="saved"||mode=="eval_overflow";
 const bool implicit_receipt=eval||mode=="maintenance";
 {
  Mp4OriginalOperationScope scope(7,mode=="maintenance"?6:mode=="unsupported_kind"?7:mode=="play"?1:mode=="stop"?2:eval?(mode=="saved"?5:4):3,reinterpret_cast<void*>(22),33,(implicit_receipt||mode=="missing_rebuild_receipt")?0:44);
  if(mode=="unsupported_kind"||mode=="sequence_overflow"||mode=="depth_limit"||mode=="asset_missing"||mode=="eval_overflow"||mode=="missing_rebuild_receipt"){
   assert(!scope.valid&&!mp4_director_actual_operation(&call));return 0;
  }
  assert(scope.valid&&!mp4_director_actual_operation(&call));scope.invoked();
  if(mode=="foreign_thread")thread=false;
  if(mode=="source_lost")current=false;
  if(mode=="inactive")mp4_scene_host.active=false;
  if(mode=="epoch_changed")++mp4_scene_host.source.generation;
  if(mode=="asset_changed")mp4_scene_host.root_asset=reinterpret_cast<void*>(12);
  if(!thread||!current||!mp4_scene_host.active||mode=="epoch_changed"||mode=="asset_changed"){
   assert(!mp4_director_actual_operation(&call)&&!call.serial);return 0;
  }
  assert(mp4_director_actual_operation(&call)&&call.epoch==7&&call.serial==1&&call.receiver==22&&call.method==33&&call.source_asset==11);
  assert(call.kind==(mode=="maintenance"?K::maintenance:mode=="play"?K::play:mode=="stop"?K::stop:eval?(mode=="saved"?K::saved_evaluate:K::zero_evaluate):K::rebuild));
  assert(call.original_receipt==(implicit_receipt?1:44));
  if(mode=="nested_throw"){
   try{Mp4OriginalOperationScope nested(7,5,reinterpret_cast<void*>(55),66,0);nested.invoked();
    assert(mp4_director_actual_operation(&call)&&call.serial==2&&call.receiver==55&&call.original_receipt==1);throw std::runtime_error("original");
   }catch(const std::runtime_error&){}
   assert(mp4_director_actual_operation(&call)&&call.serial==1&&call.receiver==22&&call.original_receipt==44);
  }
 }
 assert(!mp4_director_actual_operation(&call)&&!call.serial&&!mp4_raw_original_operation.depth);
}
'''
    folder=tmp_path_factory.mktemp('original-operation');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('mode',['normal','play','stop','maintenance','unsupported_kind','missing_rebuild_receipt','zero','saved','nested_throw','sequence_overflow','eval_overflow','depth_limit','asset_missing','foreign_thread','source_lost','inactive','epoch_changed','asset_changed','null_output'])
def test_actual_original_stack_receipt(original_operation,mode):
    result=subprocess.run([str(original_operation),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
