"""Actual shipping early readonly bank never grants Lineage/Driver authority.

Source binding/current native getters, RuntimeClip active-list and complete Root
source recipes are typed service models here, covered independently by the
original/source and active-list suites. This fixture exercises the actual early
snapshot, lifetime and final full-capture comparison bodies, without engine or
MP4 success claims.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
FIX=ROOT/'tests/fixtures/mp4_root_history'

@pytest.fixture(scope='module')
def readonly_binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    text=(NATIVE/'bridge.cpp').read_text()
    body=marker(text,'MP4_CHILD_READONLY_SOURCE_HOST')
    # The exact source binding leaf is an explicit service model; all caller
    # getter results are checked through the real snapshot/current/final body.
    start=body.index('bool mp4_child_readonly_bindings(){')
    end=body.index('bool mp4_child_readonly_state_current(',start)
    body=body[:start]+body[end:]
    folder=tmp_path_factory.mktemp('shipping-child-readonly')
    path,binary=folder/'readonly.cpp',folder/'readonly'
    path.write_text((FIX/'readonly-prefix.cpp.inc').read_text()+body+(FIX/'readonly-main.cpp.inc').read_text())
    result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return binary

@pytest.mark.parametrize('mode',range(38))
def test_shipping_early_state_roles_need_actual_full_child_handoff(readonly_binary,mode):
    result=subprocess.run([str(readonly_binary),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
