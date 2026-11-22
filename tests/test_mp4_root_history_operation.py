"""Shipping pure Root lifetime, actual operation image and late output joins.

Named native/metadata/worker services are typed models. The current-source
lifetime, exact original Call/Before association, direct Evaluate completion,
and postfactory Root/output join bodies are extracted from production markers.
There is no engine/device/MP4 success claim.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/mp4_root_history'
COUNTS={'source-image':33,'completed-output':34,'returned-evaluate':32}

@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    blocks={
        'source-image':marker(text,'MP4_ROOT_HISTORY_PENDING_SOURCE_LIFETIME_HOST')+marker(text,'MP4_ROOT_HISTORY_OPERATION_IMAGE_HOST'),
        'completed-output':marker(text,'MP4_CHILD_COMPLETED_OUTPUT_CONTEXT_HOST'),
        'returned-evaluate':marker(text,'MP4_ROOT_HISTORY_RETURNED_EVALUATE_HOST'),
    }
    folder=tmp_path_factory.mktemp('shipping-root-operation');result={}
    for kind,body in blocks.items():
        source,binary=folder/(kind+'.cpp'),folder/kind
        source.write_text((FIX/(kind+'-prefix.cpp.inc')).read_text()+body+(FIX/(kind+'-main.cpp.inc')).read_text())
        compiled=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=60)
        assert compiled.returncode==0,compiled.stderr
        result[kind]=binary
    return result

@pytest.mark.parametrize('kind,mode',[(k,m) for k,n in COUNTS.items() for m in range(n)])
def test_shipping_retained_root_operation_fact(binaries,kind,mode):
    outcome=subprocess.run([str(binaries[kind]),str(mode)],capture_output=True,text=True,timeout=5)
    assert outcome.returncode==0,outcome.stderr
