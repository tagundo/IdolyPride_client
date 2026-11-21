"""Own-install receipts accept only the exact recorded installed code cohort."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'


@pytest.fixture(scope='module')
def receipt_binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    source = (NATIVE / 'bridge.cpp').read_text().split('// BEGIN_MP4_MANAGED_HOOK_RECEIPTS\n', 1)[1].split('// END_MP4_MANAGED_HOOK_RECEIPTS', 1)[0]
    harness = r'''
#include "profile.hpp"
#include "mp4_game_bindings.hpp"
#include <atomic>
#include <cassert>
#include <cstring>
#include <string>
namespace pin=idoly::presentation::profile;namespace mp4game=idoly_mp4_game;
alignas(16) unsigned char image[256]{};uintptr_t image_base=reinterpret_cast<uintptr_t>(image);bool mapped=true;
bool mp4_mapped(uintptr_t at,size_t bytes,bool executable){return mapped&&executable&&at>=image_base&&at+bytes>=at&&at+bytes<=image_base+sizeof(image);}
// ACTUAL
int main(int argc,char** argv){
    assert(argc==2);const std::string mode=argv[1];
    pin::Entry entry{"verified original",32,{}};for(unsigned i=0;i<16;++i)entry.bytes[i]=i;
    mp4game::Binding binding{};binding.rva=32;memcpy(binding.prefix,entry.bytes,16);
    memset(image+32,0x88,16);void* trampoline=reinterpret_cast<void*>(0x1234);void* stub=reinterpret_cast<void*>(0x5678);
    if(mode=="missing_original"){void* empty=nullptr;assert(!mp4_record_managed_hook(&entry,stub,&empty));return 0;}
    if(mode=="missing_stub"){assert(!mp4_record_managed_hook(&entry,nullptr,&trampoline));return 0;}
    if(mode=="unmapped_record"){mapped=false;assert(!mp4_record_managed_hook(&entry,stub,&trampoline));return 0;}
    assert(mp4_record_managed_hook(&entry,stub,&trampoline));assert(!mp4_managed_hook_verified(binding));
    mp4_managed_hook_receipts_ready.store(true);
    assert(mp4_managed_hook_verified(binding));
    if(mode=="valid")return 0;
    if(mode=="foreign_code")image[32]^=1;
    else if(mode=="foreign_original_prefix")binding.prefix[0]^=1;
    else if(mode=="foreign_rva")binding.rva=48;
    else if(mode=="foreign_base")++image_base;
    else if(mode=="changed_trampoline")trampoline=reinterpret_cast<void*>(0x9999);
    else if(mode=="rollback")mp4_managed_hook_receipts_ready.store(false);
    else if(mode=="unmapped_check")mapped=false;
    else assert(false);
    assert(!mp4_managed_hook_verified(binding));
}
'''
    directory = tmp_path_factory.mktemp('mp4-managed-receipt')
    cpp, binary = directory / 'receipt.cpp', directory / 'receipt'
    cpp.write_text(harness.replace('// ACTUAL', source))
    result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(NATIVE), str(cpp), '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', ['missing_original', 'missing_stub', 'unmapped_record', 'valid', 'foreign_code',
    'foreign_original_prefix', 'foreign_rva', 'foreign_base', 'changed_trampoline', 'rollback', 'unmapped_check'])
def test_own_installed_code_and_trampoline_identity_are_required(receipt_binary, mode):
    result = subprocess.run([str(receipt_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
