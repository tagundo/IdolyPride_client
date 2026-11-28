"""Production typed Talk job tail/row restoration; synthetic CPU fixtures."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
CASES=["normal","zero","unfenced_capture","missing_api","invalid_scalar","capacity_bound","fence_wait","owner_lost","owner_handoff","list_changed","length_changed","capacity_changed","handle_changed","bind_type_changed","voice_changed","curve_changed","prefix_changed"]
@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler: pytest.skip("C++ compiler unavailable")
    output=tmp_path_factory.mktemp("actor-talk")/"talk"
    built=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-O2","-I",str(ROOT/"client-presentation/native"),str(ROOT/"tests/mp4_actor_talk_harness.cpp"),"-o",str(output)],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    return output
@pytest.mark.parametrize("case",CASES)
def test_exact_talk_job_restoration(binary,case):
    ran=subprocess.run([str(binary),case],capture_output=True,text=True,timeout=5)
    assert ran.returncode==0,ran.stdout+ran.stderr
