"""Actual ProFlare scratch collector; modeled source leaves, no GPU claim."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"

@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge=(ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin=bridge.index("// BEGIN_MP4_RENDERER_PROFLARE_PRESENTATION_HOST")
    end=bridge.index("// END_MP4_RENDERER_PROFLARE_PRESENTATION_HOST",begin)
    source=(FIXTURES / "mp4_proflare_presentation_host_prefix.cpp.inc").read_text()+bridge[begin:end]
    source+=(FIXTURES / "mp4_proflare_presentation_host_driver.cpp.inc").read_text()
    directory=tmp_path_factory.mktemp("mp4-proflare-presentation-host")
    path=directory / "host.cpp";path.write_text(source);binary=directory / "host"
    result=subprocess.run([shutil.which("g++") or "clang++","-std=c++17","-Wall","-Wextra","-Werror","-Wno-misleading-indentation","-g","-O1","-fsanitize=address,undefined","-fno-pie","-no-pie","-I",str(ROOT / "client-presentation/native"),str(path),"-o",str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return binary

@pytest.mark.parametrize("case",["normal","repeat","dormant","owned_birth","no_contract","stale_contract","no_owner","missing_pass","lookup","foreign_pass","field_layout","null_material","null_block","invalid_overlay","no_owned_slot","invalid_slot"])
def test_actual_scratch_inventory(host,case):
    result=subprocess.run([str(host),case],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
