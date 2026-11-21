"""Execute the production photography hooks and bounded lazy-input normalizer."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''
#include <atomic>
#include <cstdio>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
using Method=const void;using VoidMethod=void(*)(void*,Method*);
struct Mp4UniTask {void*source;short token;uint8_t padding[6];};
struct Mp4CancellationToken {void*source;};
struct Object {alignas(16) uint8_t storage[512]{};};
Object data,chars,descriptors,source,source_items,result,actor,actor2,player,presenter,transition,capture;
void* ptr(Object&x){return x.storage;}
std::map<void*,std::string> types;
template<class T>T read(void*p,size_t o){T v{};if(p)std::memcpy(&v,static_cast<uint8_t*>(p)+o,sizeof v);return v;}
template<class T>void set(Object&x,size_t o,T v){std::memcpy(x.storage+o,&v,sizeof v);}
void typed(Object&x,const char*t){types[ptr(x)]=t;}
bool mp4_type_is(void*p,const char*t){return p&&types[p]==t;}
std::atomic<bool>ready{true};bool mp4_source_verified=true,mp4_replay_verified=true,unity=true,available=true;
bool game_call(bool=false){return unity;}bool mp4_prepare_runtime(){return available;}
uintptr_t image_base=0;
struct Binding{uintptr_t rva=0;};struct Profile{Binding photo_select_to_array,field_set_value;};
Profile mp4_profile,mp4_replay_profile;
std::map<uint32_t,void*> roots;uint32_t next_handle=1;bool retain_ok=true;
uint32_t mp4_retain(void*p){if(!retain_ok||!p)return 0;auto id=next_handle++;roots[id]=p;return id;}
void weak_free(uint32_t h){assert(roots.erase(h)==1);}
size_t mp4_array_length(void*p){return read<uintptr_t>(p,0x18);}
void*mp4_array_data(void*p){return static_cast<uint8_t*>(p)+0x20;}
void*object_class(void*p){return p;}
bool method_ok=true,field_ok=true;int to_arrays=0,field_sets=0,originals=0;std::string scenario;std::vector<int>order;
void*to_array(void*p,const void*);
struct Info {void*(*call)(void*,const void*);};Info info{to_array};
const void*font_method(void*p,const char*n,int32_t count){assert(p==ptr(descriptors)&&std::string(n)=="ToArray"&&count==0);return method_ok?&info:nullptr;}
void*font_field(void*p,const char*n){assert(p==ptr(data)&&std::string(n)=="<ActorDescriptors>k__BackingField");return field_ok?reinterpret_cast<void*>(71):nullptr;}
void field_set(void*p,void*f,void*v){
 assert(p==ptr(data)&&f==reinterpret_cast<void*>(71)&&roots.size()==3);++field_sets;order.push_back(2);
 auto array=*static_cast<void**>(v);std::memcpy(static_cast<uint8_t*>(p)+0x20,&array,sizeof array);
}
void*to_array(void*p,const void*m){
 assert(p==ptr(descriptors)&&m==&info&&roots.size()==2);++to_arrays;order.push_back(1);
 if(scenario=="throws")throw std::runtime_error("original selector");
 if(scenario=="source_changes")set(source,0x18,int32_t(1));
 if(scenario=="data_changes")set(data,0x28,ptr(source_items));
 return ptr(result);
}
struct Weak {void*value=nullptr;void*get(bool=false)const{return value;}void set(void*p){value=p;}void clear(){value=nullptr;}};
Weak mp4_photography_presenter;
struct Navigation {uint64_t generation=0;bool failed=false;char error[96]="none";};
Navigation mp4_photography_navigation;
namespace idoly_mp4_runtime {
void*normalized=nullptr;
void observe_presenter_ended(void*p){assert(p==ptr(presenter));order.push_back(6);}
void observe_photography_initializing(void*p,void*d,void*a){assert(p==ptr(player)&&d==ptr(data));normalized=a;order.push_back(3);}
}
@@PRODUCTION@@
Mp4UniTask original_root(void*p,void*t,void*c,Mp4CancellationToken token,Method*m){
 assert(p==ptr(presenter)&&t==ptr(transition)&&c==ptr(capture)&&token.source==reinterpret_cast<void*>(81)&&m==reinterpret_cast<void*>(82));
 ++originals;order.push_back(4);return {reinterpret_cast<void*>(83),-91,{1,2,3,4,5,6}};
}
Mp4UniTask original_player(void*p,void*d,Mp4CancellationToken token,Method*m){
 assert(p==ptr(player)&&d==ptr(data)&&token.source==reinterpret_cast<void*>(81)&&m==reinterpret_cast<void*>(82));
 assert(roots.empty());++originals;order.push_back(4);return {reinterpret_cast<void*>(83),-91,{1,2,3,4,5,6}};
}
void original_end(void*p,Method*){assert(p==ptr(presenter));++originals;order.push_back(5);}
int main(int argc,char**argv){
 assert(argc==2);scenario=argv[1];
 typed(data,"Solis.Common.Photography.PhotographyLiveData");typed(chars,"System.String[]");
 typed(descriptors,".SelectList`2");typed(source,"System.Collections.Generic.List`1");
 typed(result,"Solis.Common.SolisActorDescriptor[]");typed(actor,"Solis.Common.SolisActorDescriptor");typed(actor2,"Solis.Common.SolisActorDescriptor");
 typed(presenter,"Solis.Photography.PhotographyLivePresenter");
 set(data,0x20,ptr(descriptors));set(data,0x28,ptr(chars));set(chars,0x18,uintptr_t(2));
 set(descriptors,0x10,ptr(source));set(descriptors,0x18,reinterpret_cast<void*>(1));
 set(source,0x10,ptr(source_items));set(source,0x18,int32_t(2));set(source_items,0x18,uintptr_t(2));
 set(result,0x18,uintptr_t(2));set(result,0x20,ptr(actor));set(result,0x28,ptr(actor2));
 mp4_profile.photo_select_to_array.rva=reinterpret_cast<uintptr_t>(&to_array);
 mp4_replay_profile.field_set_value.rva=reinterpret_cast<uintptr_t>(&field_set);
 mp4_photography_initialize_original=original_root;mp4_photography_player_initialize_original=original_player;mp4_photography_end_original=original_end;
 if(scenario=="wrong_data")typed(data,"Other.Data");
 if(scenario=="wrong_chars")typed(chars,"Other.Array");
 if(scenario=="empty")set(chars,0x18,uintptr_t(0));
 if(scenario=="too_many")set(chars,0x18,uintptr_t(33));
 if(scenario=="mismatch")set(source,0x18,int32_t(1));
 if(scenario=="negative")set(source,0x18,int32_t(-1));
 if(scenario=="capacity")set(source_items,0x18,uintptr_t(1));
 if(scenario=="capacity_large")set(source_items,0x18,uintptr_t(1025));
 if(scenario=="selector_null")set(descriptors,0x18,static_cast<void*>(nullptr));
 if(scenario=="unknown_iterable")typed(descriptors,"System.Linq.WhereSelectListIterator`2");
 if(scenario=="method_missing")method_ok=false;
 if(scenario=="field_missing")field_ok=false;
 if(scenario=="wrong_method")mp4_profile.photo_select_to_array.rva+=4;
 if(scenario=="bad_result")typed(actor2,"Other.Descriptor");
 if(scenario=="bad_result_array")typed(result,"Other.Array");
 if(scenario=="result_count")set(result,0x18,uintptr_t(1));
 if(scenario=="unverified")mp4_source_verified=false;
 if(scenario=="replay_unverified")mp4_replay_verified=false;
 if(scenario=="wrong_thread")unity=false;
 if(scenario=="retain_failure")retain_ok=false;
 if(scenario=="array")set(data,0x20,ptr(result));
 if(scenario=="hook"||scenario=="hook_unavailable"){
  available=scenario=="hook";auto r=mp4_photography_initialize_hook(ptr(presenter),ptr(transition),ptr(capture),{reinterpret_cast<void*>(81)},reinterpret_cast<void*>(82));
  assert(r.source==reinterpret_cast<void*>(83)&&r.token==-91&&r.padding[5]==6);
  assert(mp4_photography_presenter.get()==(available?ptr(presenter):nullptr));order.clear();
  r=mp4_photography_player_initialize_hook(ptr(player),ptr(data),{reinterpret_cast<void*>(81)},reinterpret_cast<void*>(82));
  assert(r.source==reinterpret_cast<void*>(83)&&r.token==-91&&r.padding[5]==6&&originals==2);
  assert(order==(available?std::vector<int>{1,2,3,4}:std::vector<int>{4}));
  order.clear();mp4_photography_end_hook(ptr(presenter),nullptr);assert(!mp4_photography_presenter.get()&&originals==3&&order==std::vector<int>({6,5}));
 }else {
  auto*array=mp4_normalize_photography_descriptors(ptr(data));
  bool good=scenario=="valid"||scenario=="array";
  assert((array==ptr(result))==good&&roots.empty());
  if(good){assert(read<void*>(ptr(data),0x20)==ptr(result));assert(field_sets==(scenario=="valid"?1:0));}
  else assert(field_sets==0);
  if(scenario=="valid"){
   assert(to_arrays==1);assert(mp4_normalize_photography_descriptors(ptr(data))==ptr(result));assert(to_arrays==1&&field_sets==1&&roots.empty());
  }
 }
}
'''

@pytest.fixture(scope='module')
def photography_harness(tmp_path_factory):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++17 compiler unavailable')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    code=source.split('// BEGIN_MP4_PHOTOGRAPHY_HOOKS',1)[1].split('// END_MP4_PHOTOGRAPHY_HOOKS',1)[0]
    work=tmp_path_factory.mktemp('photo-hooks');cpp=work/'photo.cpp';binary=work/'photo'
    cpp.write_text(HARNESS.replace('@@PRODUCTION@@',code))
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('scenario',('valid','array','wrong_data','wrong_chars','empty','too_many','mismatch','negative','capacity','capacity_large','selector_null','unknown_iterable','method_missing','field_missing','wrong_method','bad_result','bad_result_array','result_count','unverified','replay_unverified','wrong_thread','retain_failure','source_changes','data_changes','throws','hook','hook_unavailable'))
def test_concrete_original_inputs_and_hook_abi(photography_harness,scenario):
    result=subprocess.run([str(photography_harness),scenario],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
