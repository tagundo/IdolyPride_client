"""Actual Source/container closure for a genuine prepared or entered operation.

Native/public Source probes are explicit fixture models; this does not model DSP memory.
"""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'tests/fixtures'

@pytest.fixture(scope='module')
def active_audio(tmp_path_factory):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('host C++ compiler required')
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    def body(name):
        begin='// BEGIN_'+name+'\n';end='// END_'+name
        assert bridge.count(begin)==bridge.count(end)==1
        return bridge.split(begin,1)[1].split(end,1)[0]
    prefix=(F/'mp4_child_pending_origin_prefix.cpp.inc').read_text()
    needle='struct{bool granted_phase'
    assert prefix.count(needle)==1
    prefix=prefix.replace(needle,'bool audio_schedule_closed=true;\nstruct{bool closed(uint64_t e)const{return e==7&&audio_schedule_closed;}bool granted_phase')
    source='#include <cstdlib>\n'+prefix+'\n'+body('MP4_CHILD_PENDING_OPERATION_ORIGIN')+'\n'
    source+=(F/'mp4_audio_active_call_prefix.cpp.inc').read_text()+'\n'
    source+=body('MP4_AUDIO_ACTIVE_CALL_SOURCE_QUIET')+'\n'+(F/'mp4_audio_active_call_driver.cpp.inc').read_text()
    folder=tmp_path_factory.mktemp('actual-audio-call');cpp=folder/'host.cpp';binary=folder/'host'
    cpp.write_text(source)
    result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(cpp),'-o',str(binary)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize('case',range(1,55))
def test_actual_same_call_audio_source_closure(active_audio,case):
    result=subprocess.run([str(active_audio),str(case)],capture_output=True,text=True,timeout=15,
        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1'})
    assert result.returncode==0,result.stdout+result.stderr
