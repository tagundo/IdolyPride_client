"""Source-derived fixed Rig/Expression/LookAt/Quartz/IK payload contracts."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler: pytest.skip("C++ compiler unavailable")
    output=tmp_path_factory.mktemp("actor-fixed")/"fixed"
    built=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-O2","-I",str(ROOT/"client-presentation/native"),str(ROOT/"tests/mp4_actor_fixed_jobs_harness.cpp"),"-o",str(output)],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    return output
@pytest.mark.parametrize("platform",["android","ios"])
@pytest.mark.parametrize("index",range(5))
@pytest.mark.parametrize("scenario",["normal","no_fence","budget","owner_lost","graph_generation","job_generation","job_configuration","row_binding","mirror_changed","history"])
def test_source_fixed_job_schema(binary,platform,index,scenario):
    result=subprocess.run([str(binary),platform,str(index),scenario],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
