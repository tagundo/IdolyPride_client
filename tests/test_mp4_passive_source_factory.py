"""Actual shipping passive source construction, using explicit native services.

These source/main-thread/GC/native-publication services are modeled typed leaves.
The tests do not claim engine loading, GPU execution or a completed MP4 export.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker, namespace

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
FIX=ROOT/'tests/fixtures'

@pytest.fixture(scope='module')
def passive_binaries(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    source=(NATIVE/'bridge.cpp').read_text()
    folder=tmp_path_factory.mktemp('shipping-passive-source-factory')
    headers={
        'pending-journal.hpp':marker(source,'MP4_DIRECTOR_MAINTENANCE_CORE'),
        'birth-scope.hpp':namespace(source,'// Shared-only: real native allocation/registration','mp4_director_birth'),
        'source-origin.hpp':namespace(source,'// Concrete original entry contract.','mp4_director_birth'),
        'typed-host.hpp':namespace(source,'// Shared typed actual-entry adapters.','mp4_director_birth'),
        'passive-scope.hpp':marker(source,'MP4_PASSIVE_SOURCE_FACTORY_CORE'),
    }
    for name,body in headers.items():(folder/name).write_text('#pragma once\n'+body)
    models={
        'scope':(FIX/'mp4_passive_source_factory_model.cpp.inc').read_text(),
        'host':(FIX/'mp4_passive_source_factory_host_prefix.cpp.inc').read_text()+marker(source,'MP4_PASSIVE_SOURCE_FACTORY_HOST')+(FIX/'mp4_passive_source_factory_host_main.cpp.inc').read_text(),
    }
    binaries={}
    for name,body in models.items():
        path,binary=folder/(name+'.cpp'),folder/name
        path.write_text(body)
        result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(folder),'-I',str(NATIVE),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        binaries[name]=binary
    return binaries

@pytest.mark.parametrize('mode',range(35))
def test_shipping_passive_journal_never_grants_private_authority(passive_binaries,mode):
    result=subprocess.run([str(passive_binaries['scope']),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr

@pytest.mark.parametrize('mode',range(25))
def test_shipping_early_host_actual_services_and_later_source_seal(passive_binaries,mode):
    result=subprocess.run([str(passive_binaries['host']),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
