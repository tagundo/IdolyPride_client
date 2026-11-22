"""Actual readonly saved/current/final Root checkpoints, extracted from Bridge.

Typed original property/native publication/Source-lifetime services are models.
The aggregate-current service deliberately traps: these final queries cannot
enter modules, parent confirmation, NativeBirth or persistent construction.
No device, GPU or encoded-file success is asserted.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/mp4_root_history'

@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    common=''.join(marker(source,name) for name in (
        'MP4_ROOT_HISTORY_SAVED_CONTEXT_HOST',
        'MP4_ROOT_HISTORY_SAVED_EVALUATE_HOST',
        'MP4_ROOT_HISTORY_ALL_SAVED_ROOTS_HOST'))
    prefix=(FIX/'all-saved-prefix.cpp.inc').read_text()
    bodies={
        'all-saved':prefix+common+(FIX/'all-saved-main.cpp.inc').read_text(),
        'final':prefix+(FIX/'final-model.cpp.inc').read_text()+common+
            marker(source,'MP4_ROOT_HISTORY_FINAL_SOURCE_ROOTS_HOST')+
            (FIX/'final-main.cpp.inc').read_text(),
    }
    folder=tmp_path_factory.mktemp('shipping-final-source-roots');result={}
    for name,body in bodies.items():
        path,binary=folder/(name+'.cpp'),folder/name
        path.write_text(body)
        built=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror',
            '-Wno-misleading-indentation','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer','-fno-pie','-no-pie',str(path),'-o',str(binary)],
            capture_output=True,text=True,timeout=60)
        assert built.returncode==0,built.stderr
        result[name]=binary
    return result

@pytest.mark.parametrize('kind,mode',[(k,m) for k,n in [('all-saved',45),('final',20)] for m in range(n)])
def test_shipping_strictly_readonly_final_source_roots(binaries,kind,mode):
    ran=subprocess.run([str(binaries[kind]),str(mode)],capture_output=True,text=True,timeout=5)
    assert ran.returncode==0,ran.stderr
