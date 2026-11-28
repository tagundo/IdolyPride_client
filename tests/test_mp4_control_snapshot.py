"""Actual retained Control image accessor, with no query-minted capability."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
FIX=ROOT/'tests/fixtures/mp4_root_history'

@pytest.fixture(scope='module')
def control_snapshot_binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    text=(NATIVE/'bridge.cpp').read_text()
    name='idoly_mp4_control_assets'
    body='namespace '+name+' {'+text.split('namespace '+name+' {',1)[1].split('} // namespace '+name,1)[0]+'} // namespace '+name
    folder=tmp_path_factory.mktemp('shipping-control-snapshot')
    (folder/'control-asset-scope.hpp.inc').write_text(body)
    path,binary=folder/'model.cpp',folder/'model'
    path.write_text((FIX/'control-snapshot.cpp.inc').read_text())
    result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie','-I',str(folder),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return binary

@pytest.mark.parametrize('mode',range(22))
def test_shipping_control_snapshot_exact_owner_retained_images_and_drift(control_snapshot_binary,mode):
    result=subprocess.run([str(control_snapshot_binary),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
