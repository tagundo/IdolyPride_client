"""Real SRP dispatcher context receipts; original Runtime/Unity leaves modeled."""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1];F=ROOT/'tests/fixtures'
def block(s,name):
 a=s.index('// BEGIN_'+name);b=s.index('// END_'+name,a);return s[a:b]
@pytest.fixture(scope='module',params=['android','ios'])
def host(request,tmp_path_factory):
 bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
 source='#include <cstdint>\n#include <cstddef>\n#include <cstdlib>\n#include <cstring>\n#include <algorithm>\n#include <cmath>\n'+(F/'mp4_srp_dispatch_host_prefix.cpp.inc').read_text()
 for name in ['MP4_RENDERER_SRP_HOST','MP4_RENDERER_SRP_STATE_HOST','MP4_SRP_DISPATCH_PINS','MP4_SRP_DISPATCH_HOST','MP4_SRP_MUTATION_HOOKS']:source+=block(bridge,name)
 source+=(F/'mp4_srp_physical_driver.cpp.inc').read_text()
 path=tmp_path_factory.mktemp('srp-physical-'+request.param)/'host.cpp';path.write_text(source);binary=path.with_suffix('')
 flags=['-DIDOLY_DARWIN_BRIDGE=1']if request.param=='ios'else[]
 r=subprocess.run([shutil.which('g++')or'clang++','-std=c++17','-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie','-pthread','-I',str(ROOT/'client-presentation/native'),*flags,str(path),'-o',str(binary)],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
 return binary
@pytest.mark.parametrize('case',['physical_wait_context','physical_bad_plan','physical_no_selected','physical_no_intent','physical_exhausted'])
def test_actual_srp_physical_context(host,case):
 r=subprocess.run([str(host),case],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
