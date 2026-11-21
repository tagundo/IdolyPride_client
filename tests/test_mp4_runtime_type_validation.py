"""Attest mutable IL2CPP descriptors without accepting arbitrary runtime pointers."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'


def function(source, name):
    start = source.index(name + '(')
    start = source.rfind('\n', 0, start) + 1
    body = source.index('{', start)
    depth, end = 1, body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def compile_run(tmp_path, source):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler required')
    path = tmp_path / 'type.cpp'
    path.write_text(source)
    binary = tmp_path / 'type'
    result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(NATIVE),
                             str(path), '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('platform', ['android', 'ios'])
def test_all_six_descriptors_require_exact_initialized_rows_for_every_verified_language(tmp_path, platform):
    record = json.loads((NATIVE / 'mp4_type_descriptor_profile.json').read_text())['platforms'][platform]
    substitutions = {
        'PLATFORM': platform,
        'EXPECTED_BASE_SLOT': record['metadata_base_global'],
        'EXPECTED_HEADER_SLOT': record['metadata_header_global'],
        'EXPECTED_DEFINITION_BYTES': str(record['type_definition_bytes']),
        'EXPECTED_OFFSETS': ','.join(str(row['type_definition_offset']) for row in record['language_variants']),
    }
    def rendered(source):
        for key, value in substitutions.items():
            source = source.replace(key, value)
        return source
    compile_run(tmp_path, rendered(r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <limits>
#include "mp4_type_descriptor.hpp"
#include "mp4_replay_profile.hpp"
using namespace idoly_mp4_game;
int main(){
 const auto& metadata=PLATFORM_type_metadata_profile;
 assert(metadata.metadata_base_slot==EXPECTED_BASE_SLOT&&metadata.metadata_header_slot==EXPECTED_HEADER_SLOT);
 assert(metadata.definition_bytes==EXPECTED_DEFINITION_BYTES);
 const uint32_t expected_offsets[]={EXPECTED_OFFSETS};
 for(unsigned index=0;index<4;++index)assert(metadata.definition_offsets[index]==expected_offsets[index]);
 const auto& runtime=PLATFORM_runtime_profile;const auto& replay=idoly_mp4_replay::PLATFORM_replay_profile;
 auto converted=[](const auto& value){Binding result{};result.rva=value.rva;std::memcpy(result.prefix,value.prefix,16);return result;};
 const Binding descriptors[]={runtime.single_type,runtime.audio_clip_type,runtime.texture2d_type,
   converted(replay.actor_descriptor_type),converted(replay.out_game_param_type),converted(replay.transition_param_type)};
 for(uint32_t offset:metadata.definition_offsets){
  assert(type_metadata_layout(metadata,0xfab11baf,31,offset,metadata.definition_bytes));
  assert(!type_metadata_layout(metadata,0xfab11baf,31,offset+1,metadata.definition_bytes));
  assert(!type_metadata_layout(metadata,0xfab11baf,31,offset,metadata.definition_bytes-88));
  assert(!type_metadata_layout(metadata,0,31,offset,metadata.definition_bytes));
  assert(!type_metadata_layout(metadata,0xfab11baf,30,offset,metadata.definition_bytes));
  const uintptr_t definitions=0x70000000+offset;
  for(const auto& descriptor:descriptors){
   uint8_t runtime_bytes[16];std::memcpy(runtime_bytes,descriptor.prefix,16);
   assert(type_descriptor_shape(descriptor,runtime_bytes));
   assert(!resolved_type_descriptor(descriptor,runtime_bytes,definitions,metadata.definition_bytes));
   uint64_t index=0;std::memcpy(&index,descriptor.prefix,8);
   const uintptr_t expected=definitions+index*88;std::memcpy(runtime_bytes,&expected,8);
   assert(std::memcmp(runtime_bytes,descriptor.prefix,16)!=0);
   assert(resolved_type_descriptor(descriptor,runtime_bytes,definitions,metadata.definition_bytes));
   uintptr_t foreign=expected+88;std::memcpy(runtime_bytes,&foreign,8);
   assert(!resolved_type_descriptor(descriptor,runtime_bytes,definitions,metadata.definition_bytes));
   std::memcpy(runtime_bytes,&expected,8);
   for(unsigned at=8;at<16;++at){runtime_bytes[at]^=1;
    assert(!type_descriptor_shape(descriptor,runtime_bytes));
    assert(!resolved_type_descriptor(descriptor,runtime_bytes,definitions,metadata.definition_bytes));runtime_bytes[at]^=1;}
   assert(!resolved_type_descriptor(descriptor,runtime_bytes,definitions,88));
   assert(!resolved_type_descriptor(descriptor,runtime_bytes,0,metadata.definition_bytes));
   assert(!resolved_type_descriptor(descriptor,runtime_bytes,std::numeric_limits<uintptr_t>::max()-16,metadata.definition_bytes));
  }
 }
}
'''))


@pytest.mark.parametrize('platform', ['android', 'ios'])
def test_actual_unity_thread_gate_checks_mapping_row_and_class_before_publishing_api(tmp_path, platform):
    bridge = (NATIVE / 'bridge.cpp').read_text()
    begin = bridge.index('struct Mp4MetadataRange {')
    end = bridge.index('\nvoid* mp4_original_current_controller()', begin)
    actual = bridge[begin:end]
    compile_run(tmp_path, (r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
#include "mp4_type_descriptor.hpp"
#include "mp4_replay_profile.hpp"
namespace mp4game=idoly_mp4_game;
uint8_t image[512]{};uintptr_t image_base=reinterpret_cast<uintptr_t>(image);
std::vector<uint8_t> metadata(32*1024*1024);
bool mp4_source_verified=true,unity_thread=true,descriptor_mapped=true,metadata_readable=true;
int class_calls=0,range_queries=0;uintptr_t expected_row=0;char mp4_binding_error[96]{};
mp4game::TypeMetadataProfile mp4_type_metadata_profile=mp4game::PLATFORM_type_metadata_profile;
template<class T>T read(void* object,size_t offset){T out{};std::memcpy(&out,static_cast<uint8_t*>(object)+offset,sizeof out);return out;}
template<class T>void write(void* object,size_t offset,T value){std::memcpy(static_cast<uint8_t*>(object)+offset,&value,sizeof value);}
bool game_call(){return unity_thread;}
bool mp4_mapped(uintptr_t address,size_t bytes,bool executable){return descriptor_mapped&&!executable&&address==image_base+256&&bytes==16;}
bool mp4_readable_memory(uintptr_t address,size_t bytes){++range_queries;
 const uintptr_t start=reinterpret_cast<uintptr_t>(metadata.data());
 return metadata_readable&&address>=start&&bytes<=metadata.size()&&address-start<=metadata.size()-bytes;}
struct Class {const char* space;const char* name;} klass{"System","Single"};
void* font_class_type(const void* descriptor){++class_calls;assert(read<uintptr_t>(const_cast<void*>(descriptor),0)==expected_row);return &klass;}
const char* class_name(void* value){assert(value==&klass);return klass.name;}
const char* class_namespace(void* value){assert(value==&klass);return klass.space;}
''' + actual + r'''
int main(){
 mp4_type_metadata_profile.metadata_base_slot=16;mp4_type_metadata_profile.metadata_header_slot=24;
 const auto& profile=mp4_type_metadata_profile;
 const auto& runtime=mp4game::PLATFORM_runtime_profile;const auto& replay=idoly_mp4_replay::PLATFORM_replay_profile;
 struct Case {mp4game::Binding binding;const char* space;const char* name;};
 auto converted=[](const auto& value){mp4game::Binding result{};result.rva=value.rva;std::memcpy(result.prefix,value.prefix,16);return result;};
 const Case cases[]={{runtime.single_type,"System","Single"},{runtime.audio_clip_type,"UnityEngine","AudioClip"},
  {runtime.texture2d_type,"UnityEngine","Texture2D"},{converted(replay.actor_descriptor_type),"Solis.Common","SolisActorDescriptor"},
  {converted(replay.out_game_param_type),"Solis.OutGame","OutGameLivePlayerParam"},{converted(replay.transition_param_type),"Solis.OutGame","LivePlayerTransitionParam"}};
 write(image,16,metadata.data());write(image,24,metadata.data());
 for(uint32_t offset:profile.definition_offsets){
  write(metadata.data(),0,uint32_t(0xfab11baf));write(metadata.data(),4,uint32_t(31));
  write(metadata.data(),0xa0,offset);write(metadata.data(),0xa4,profile.definition_bytes);
  for(const auto& item:cases){
   auto binding=item.binding;binding.rva=256;klass={item.space,item.name};
   std::memcpy(image+256,binding.prefix,16);uint64_t index=0;std::memcpy(&index,binding.prefix,8);
   expected_row=reinterpret_cast<uintptr_t>(metadata.data())+offset+index*88;write(image,256,expected_row);
   mp4_metadata_readable={};const int before=class_calls;
   assert(mp4_resolved_type_class(binding,item.space,item.name)==&klass&&class_calls==before+1);
   write(image,256,index);assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+1);
   assert(std::strstr(mp4_binding_error,"original_mv_type_row_"));
   write(image,256,expected_row+88);assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+1);
   write(image,256,expected_row);image[266]^=1;assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+1);image[266]^=1;
   descriptor_mapped=false;assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+1);descriptor_mapped=true;
   klass.space="Foreign";assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+2);
   assert(std::strstr(mp4_binding_error,"original_mv_type_identity_"));klass.space=item.space;
   mp4_metadata_readable={};metadata_readable=false;assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+2);metadata_readable=true;
   write(metadata.data(),0xa0,offset+4);assert(!mp4_resolved_type_class(binding,item.space,item.name)&&class_calls==before+2);write(metadata.data(),0xa0,offset);
  }
 }
 auto binding=runtime.single_type;binding.rva=256;mp4_metadata_readable={};
 const int before=class_calls;write(image,16,reinterpret_cast<void*>(0x1000));write(image,24,reinterpret_cast<void*>(0x1000));
 assert(!mp4_resolved_type_class(binding,"System","Single")&&class_calls==before);
 assert(std::strstr(mp4_binding_error,"original_mv_metadata_unreadable_"));
 write(image,16,nullptr);write(image,24,nullptr);assert(!mp4_resolved_type_class(binding,"System","Single")&&class_calls==before);
 unity_thread=false;assert(!mp4_resolved_type_class(binding,"System","Single")&&class_calls==before);
 unity_thread=true;mp4_source_verified=false;assert(!mp4_resolved_type_class(binding,"System","Single")&&class_calls==before);
}
''').replace('PLATFORM', platform))


def test_actual_platform_metadata_range_reader_rejects_unmapped_and_protected_pages(tmp_path):
    bridge = (NATIVE / 'bridge.cpp').read_text()
    declarations = bridge[bridge.index('#ifdef IDOLY_DARWIN_BRIDGE\nextern "C" {\nextern unsigned int mach_task_self_;'):
                          bridge.index('bool mp4_readable_memory(')]
    actual = function(bridge, 'mp4_readable_memory')
    compile_run(tmp_path, ('#define IDOLY_DARWIN_BRIDGE 1\n' if sys.platform == 'darwin' else '') + r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <sys/mman.h>
#include <unistd.h>
''' + declarations + actual + r'''
int main(){
 const size_t page=static_cast<size_t>(sysconf(_SC_PAGESIZE));
 auto* mapping=static_cast<uint8_t*>(mmap(nullptr,page*3,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0));
 assert(mapping!=MAP_FAILED);const uintptr_t base=reinterpret_cast<uintptr_t>(mapping);
 assert(mp4_readable_memory(base,page*3));assert(!mp4_readable_memory(0,1));
 assert(!mp4_readable_memory(base,0));assert(!mp4_readable_memory(1,16));
 assert(!mp4_readable_memory(std::numeric_limits<uintptr_t>::max()-2,16));
 assert(mprotect(mapping+page,page,PROT_NONE)==0);
 assert(mp4_readable_memory(base,page));assert(!mp4_readable_memory(base,page*2));
 assert(!mp4_readable_memory(base+page,page));assert(mp4_readable_memory(base+page*2,page));
 assert(mprotect(mapping+page,page,PROT_READ|PROT_WRITE)==0);assert(mp4_readable_memory(base,page*3));
 assert(munmap(mapping+page,page)==0);assert(!mp4_readable_memory(base,page*3));
 assert(munmap(mapping,page)==0);assert(munmap(mapping+page*2,page)==0);
}
''')


def test_profile_records_actual_raw_and_packaged_language_layouts():
    proof = json.loads((NATIVE / 'mp4_type_descriptor_profile.json').read_text())
    assert proof['descriptor_row_bytes'] == 88
    expected = {'android': [22225200, 22225224, 22225256, 22225264],
                'ios': [22256544, 22256568, 22256600, 22256608]}
    for platform, offsets in expected.items():
        record = proof['platforms'][platform]
        assert record['metadata_base_equals_header_store_proven'] is True
        assert record['observed_initializer_writes_only_descriptor_data8'] is True
        assert [row['type_definition_offset'] for row in record['language_variants']] == offsets
        assert [row['language'] for row in record['language_variants']] == ['original', 'ja', 'en', 'ko']
        assert all(row['type_definition_bytes'] == record['type_definition_count'] * 88 for row in record['language_variants'])
        assert all(len(row['metadata_sha256']) == 64 for row in record['language_variants'])
