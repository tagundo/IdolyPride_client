"""Shipping source catalogue roots survive only their real captured lifetime."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/mp4_root_history'
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    a=text.index('namespace mp4birth=mp4_director_birth;')
    body=text[a:text.index('// Bind these directly to OriginApi',a)]
    folder=tmp_path_factory.mktemp('shipping-source-catalogue');source=folder/'catalogue.cpp';result=folder/'catalogue'
    source.write_text((FIX/'catalogue-prefix.cpp.inc').read_text()+body+(FIX/'catalogue-main.cpp.inc').read_text())
    compiled=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(source),'-o',str(result)],capture_output=True,text=True,timeout=60)
    assert compiled.returncode==0,compiled.stderr
    return result
@pytest.mark.parametrize('mode',range(15))
def test_capture_clear_and_different_mv_source(binary,mode):
    completed=subprocess.run([str(binary),str(mode)],capture_output=True,text=True,timeout=5)
    assert completed.returncode==0,completed.stderr
