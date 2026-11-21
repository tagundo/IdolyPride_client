"""Attest original typed master/constructor bindings for fresh Photography jobs."""
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import audit_mp4_photography_replay as audit
NATIVE=ROOT/'client-presentation/native'

def test_both_profiles_reproduce_header_and_keep_fresh_original_route():
    a=json.loads((NATIVE/'mp4_photography_replay_android_profile.json').read_text())
    i=json.loads((NATIVE/'mp4_photography_replay_ios_profile.json').read_text())
    assert (NATIVE/'mp4_photography_replay_profile.hpp').read_text()==audit.render_header(a,i)
    for profile in (a,i):
        m=profile['methods'];types=profile['runtime_types']
        assert len(m)==26 and len(types)==7
        assert m['stage_master']['native_abi']=='void*(const MethodInfo*)'
        assert m['stage_rows']['native_abi']=='void*(void*,int32_t,const MethodInfo*)'
        assert m['find_costume']['parameters']==[{'name':'key','type':'System.String','metadata_type_index':m['find_costume']['parameters'][0]['metadata_type_index']}]
        assert m['find_hair']['native_abi']=='void*(void*,void*,const MethodInfo*)'
        assert m['actor_ctor']['native_abi']=='void(void*,void*,void*,const MethodInfo*)'
        assert m['transition_ctor']['native_abi']=='void(void*,void*,void*,void*,bool,const MethodInfo*)'
        assert m['screen_transition_ctor']['native_abi']=='void(void*,void*,void*,void*,bool,bool,const MethodInfo*)'
        assert m['pre_download']['native_abi']=='BoolUniTask16(void*,CancellationToken8,bool,const MethodInfo*)'
        assert 'overloaded name/count is insufficient' in m['pre_download']['runtime_resolution']
        assert m['class_methods']['native_abi']=='const MethodInfo*(void*,void**)'
        assert m['pre_download']['return']=='Cysharp.Threading.Tasks.UniTask`1<System.Boolean>'
        assert profile['bool_task_layout']=={'bytes':16,'source':0,'result':8,'token':10}
        assert m['method_return_type']['native_abi']=='const Il2CppType*(const MethodInfo*)'
        for n in ('bool_task_status','bool_task_awaiter','bool_task_result'):assert m[n]['runtime_closed_method_info_required']
        assert m['scene_load']['native_abi']=='void(void*,int32_t,int32_t,const MethodInfo*)'
        assert m['scene_set_data']['native_abi']=='void(void*,void*,const MethodInfo*)'
        assert m['field_static_get']['native_abi']=='void(const FieldInfo*,void*)'
        assert m['runtime_class_init']['native_abi']=='void(Il2CppClass*)'
        assert any(x['parent']=='UnityEngine.Object' for x in profile['scene_manager_ancestry'])
        assert m['list_ctor']['runtime_closed_method_info_required'] and m['list_add']['runtime_closed_method_info_required']
        assert profile['fields']['actor_list']['offset']==0x40 and profile['fields']['display_actors']['offset']==0x48
        assert profile['fields']['stage_id']['offset']==profile['fields']['music_id']['offset']==0x18
        assert profile['enums']=={'stage_sort':0,'music_sort':0,'load_mode':0}
        assert profile['scope']=={'normal_master_only':True,'special_wrappers_supported':False,'game_executed':False,'runtime_verified':False}
        for row in [*m.values(),*types.values()]:assert int(row['rva'],16)>0 and len(bytes.fromhex(row['prefix']))==16


def test_header_rejects_missing_platform_binding():
    a=json.loads((NATIVE/'mp4_photography_replay_android_profile.json').read_text())
    i=json.loads((NATIVE/'mp4_photography_replay_ios_profile.json').read_text());del i['methods']['find_hair']
    with pytest.raises(ValueError,match='photo_replay_aliases_differ'):audit.render_header(a,i)


def test_overloaded_original_method_resolution_is_bounded_and_preserves_closed_context(tmp_path):
    import shutil,subprocess
    from test_mp4_controller_lookup import _function
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    body=_function((NATIVE/'bridge.cpp').read_text(),'const void* mp4_unique_class_method(')
    source=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
struct Info{uintptr_t pointer;unsigned context;};
std::vector<Info> methods;unsigned calls=0;
const void* enumerate(void* klass,void** cursor){assert(klass==reinterpret_cast<void*>(9));++calls;auto i=reinterpret_cast<uintptr_t>(*cursor);if(i>=methods.size())return nullptr;*cursor=reinterpret_cast<void*>(i+1);return &methods[i];}
struct Binding{uintptr_t rva;};struct Profile{Binding class_methods;};
uintptr_t image_base=0;Profile mp4_photography_profile{{reinterpret_cast<uintptr_t>(&enumerate)}};
template<class T>T read(void* p,size_t offset){T value{};std::memcpy(&value,static_cast<unsigned char*>(p)+offset,sizeof value);return value;}
'''+body+r'''
int main(){
 auto*klass=reinterpret_cast<void*>(9);
 assert(!mp4_unique_class_method(nullptr,123)&&!mp4_unique_class_method(klass,0)&&calls==0);
 methods={{7,1},{123,2},{8,3}};
 auto*expected=&methods[1];assert(mp4_unique_class_method(klass,123)==expected&&expected->context==2&&calls==4);
 calls=0;assert(!mp4_unique_class_method(klass,124)&&calls==4);
 methods.push_back({123,5});assert(!mp4_unique_class_method(klass,123));
 methods.assign(513,{7,1});methods[0].pointer=123;calls=0;assert(!mp4_unique_class_method(klass,123)&&calls==512);
 methods.assign(511,{7,1});methods[510]={123,999};calls=0;
 auto*last=static_cast<const Info*>(mp4_unique_class_method(klass,123));assert(last==&methods[510]&&last->context==999&&calls==512);
}
'''
    cpp=tmp_path/'method.cpp';binary=tmp_path/'method';cpp.write_text(source)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    subprocess.run([str(binary)],check=True)
