"""Sound autosave policy and real typed wrapper call contracts; no device claim."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest
NATIVE=Path(__file__).resolve().parents[1]


def test_sound_persistence_policy(tmp_path):
    compiler=shutil.which('c++')
    if not compiler:
        pytest.skip('Host C++ compiler unavailable')
    binary=tmp_path/'sound-persistence'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(NATIVE/'tests/sound_persistence_test.cpp'),'-o',str(binary)],check=True,capture_output=True,timeout=20)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)


def test_real_sound_hooks_preserve_self_value_method_order_and_exceptions(tmp_path):
    compiler=shutil.which('c++')
    if not compiler:
        pytest.skip('Host C++ compiler unavailable')
    bridge=(NATIVE/'bridge.cpp').read_text()
    fragment=bridge.split('// BEGIN_SOUND_AUTOSAVE_HOOKS\n',1)[1].split('// END_SOUND_AUTOSAVE_HOOKS',1)[0]
    fixture=tmp_path/'hooks.cpp'
    fixture.write_text(r'''
#include <atomic>
#include <cassert>
#include <cstring>
#include <stdexcept>
#include "sound_persistence.hpp"
using Method=const void;
using VoidMethod=void (*)(void*,Method*);
std::atomic<bool> ready{true};bool main_thread=true;
bool game_call(bool establish){assert(!establish);return main_thread;}
''' + fragment + r'''
struct Obj {unsigned char data[256]{};} presenter,model,settings;
void *refs[32]{};int64_t now=1000;int clocks=0,saves=0,volume_calls=0,toggle_calls=0,binds=0;bool fail_save=false,fail_setter=false,in_bind=false;
Method *sentinel=(Method*)0x1234;
template<class T>void put(Obj&o,size_t at,T v){std::memcpy(o.data+at,&v,sizeof v);}
uint32_t make_ref(void*p,bool b){assert(!b);for(unsigned i=1;i<32;++i)if(!refs[i]){refs[i]=p;return i;}return 0;}
void*get_ref(uint32_t h){return refs[h];}void free_ref(uint32_t h){refs[h]=nullptr;}
bool match(void*p,const char*,const char*n){return(p==&presenter&&(!std::strcmp(n,"GameSettingTopScreenPresenter")||!std::strcmp(n,"Behaviour")))||(p==&model&&!std::strcmp(n,"GameSettingTopScreenModel"))||(p==&settings&&!std::strcmp(n,"GameSetting"));}
bool valid_presenter(void*p,Method*){assert(p==&presenter);return true;}
int64_t clock_ms(){++clocks;return now;}
void original_save(void*p,Method*m){assert(p==&settings&&(m==nullptr||m==sentinel));++saves;if(fail_save)throw std::runtime_error("save");}
void volume(void*p,float v,Method*m){assert(p==&model&&m==sentinel);++volume_calls;assert(saves==0);if(fail_setter)throw std::runtime_error("setter");put(settings,0x18,v);}
void toggle(void*p,bool v,Method*m){assert(p==&model&&m==sentinel);++toggle_calls;assert(saves==0);put(settings,0x1c,uint8_t(v));}
void bind(void*p,Method*m){assert(p==&presenter&&m==sentinel);++binds;if(in_bind)sound_bgm_volume_hook(&model,.3f,sentinel);}
int main(){
 put(presenter,0xe0,(void*)&model);put(model,0x18,(void*)&settings);put(settings,0x18,.5f);put(settings,0x1c,uint8_t(1));
 sound::Calls api{make_ref,get_ref,free_ref,match,valid_presenter,valid_presenter,clock_ms,sound_save_auto};sound_tracker.configure(api);
 sound_bind_original=bind;sound_save_original=original_save;sound_bgm_volume_original=volume;sound_bgm_soundable_original=toggle;
 in_bind=true;sound_bind_hook(&presenter,sentinel);in_bind=false;assert(binds==1&&volume_calls==1&&!sound_tracker.pending()&&clocks==0);
 sound_bgm_volume_hook(&model,.2f,sentinel);assert(volume_calls==2&&sound_tracker.pending()&&clocks==1&&saves==0);now+=400;sound_tracker.tick(true);assert(saves==1&&!sound_tracker.pending());saves=0;
 sound_bgm_soundable_hook(&model,false,sentinel);assert(toggle_calls==1&&sound_tracker.pending());sound_save_hook(&settings,sentinel);assert(saves==1&&!sound_tracker.pending());saves=0;
 main_thread=false;sound_bgm_volume_hook(&model,.4f,sentinel);assert(volume_calls==3&&!sound_tracker.pending());main_thread=true;
 ready=false;sound_bgm_volume_hook(&model,.45f,sentinel);assert(volume_calls==4&&!sound_tracker.pending());ready=true;
 fail_setter=true;try{sound_bgm_volume_hook(&model,.6f,sentinel);assert(false);}catch(const std::runtime_error&){}fail_setter=false;assert(!sound_tracker.pending()&&volume_calls==5);
 sound_bgm_volume_hook(&model,.7f,sentinel);fail_save=true;try{sound_save_hook(&settings,sentinel);assert(false);}catch(const std::runtime_error&){}assert(sound_tracker.pending());saves=0;now+=400;sound_tracker.tick(true);assert(saves==1&&sound_tracker.pending());fail_save=false;now+=2000;sound_tracker.tick(true);assert(!sound_tracker.pending());
}
''')
    binary=tmp_path/'hooks'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(NATIVE),str(fixture),'-o',str(binary)],check=True,capture_output=True,timeout=20)
    subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)


def test_sound_profiles_and_tick_are_independent_of_graphics_configuration():
    bridge=(NATIVE/'bridge.cpp').read_text()
    body=bridge.split('void quality_update_hook(',1)[1].split('\n}\n',1)[0]
    assert body.count('sound_tracker.tick(true);')==2
    # Both tick calls follow a preserved original and include the !has path.
    no_config=body.split('if (!has) {',1)[1].split('return;',1)[0]
    assert no_config.index('quality_update_original')<no_config.index('sound_tracker.tick(true)')
    for platform in ('native','ios'):
        profile=json.loads((NATIVE.parent/platform/'profile.json').read_text())
        assert profile['sound_autosave']['quiet_ms']==400
        assert profile['sound_autosave']['device_persistence_verified'] is False
        for name in ('sound_bgm_volume','sound_bgm_soundable','sound_se_volume','sound_se_soundable','sound_voice_volume','sound_voice_soundable','sound_bind','sound_save'):
            assert name in profile['aliases']
            assert len(bytes.fromhex(profile['aliases'][name]['prefix16']))==16
    helper=(NATIVE/'sound_persistence.hpp').read_text()
    tick=helper.split('void tick(bool enabled) {',1)[1].split('\n    }',1)[0]
    assert tick.index('if (!dirty_) return;')<tick.index('api_.now_ms()')
    assert 'observed_save' in helper and 'binding_depth_' in helper
