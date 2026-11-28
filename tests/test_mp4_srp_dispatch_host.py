"""Actual typed SRP dispatcher/state helpers; modeled Unity and Runtime leaves."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def block(source, name):
    begin=source.index(f"// BEGIN_{name}")
    end=source.index(f"// END_{name}",begin)
    return source[begin:end]


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge=(ROOT / "client-presentation/native/bridge.cpp").read_text()
    source=(FIXTURES / "mp4_srp_dispatch_host_prefix.cpp.inc").read_text()
    for marker in ["MP4_RENDERER_SRP_HOST","MP4_RENDERER_SRP_STATE_HOST","MP4_SRP_DISPATCH_PINS","MP4_SRP_DISPATCH_HOST","MP4_SRP_MUTATION_HOOKS"]:
        source+=block(bridge,marker)
    source+=(FIXTURES / "mp4_srp_dispatch_host_driver.cpp.inc").read_text()
    directory=tmp_path_factory.mktemp("mp4-srp-dispatch-host")
    path=directory / "host.cpp";path.write_text(source);binary=directory / "host"
    result=subprocess.run([shutil.which("g++") or "clang++","-std=c++17","-Wall","-Wextra","-Werror","-Wno-misleading-indentation","-g","-O1","-fsanitize=address,undefined","-fno-pie","-no-pie","-pthread","-I",str(ROOT / "client-presentation/native"),str(path),"-o",str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize("case",[
    "normal","next_tick","stale_draw","prewarm","frame_frontend","add_frontend","invoke_frontend","mono_add","wrong_caller","wrong_mono","wrong_extension","mono_aabb",
    "root_add","unknown_add","add_exception","unowned_invoke","held_retry","offthread","withdraw","unheld_capture","no_selected",
    "duplicate_selected","frame_exception","nested_frame","handoff","callback_clear","unready_held","unready_requested","loop_released","capture_active_foreign","snapshot_foreign","snapshot_main_reentry","active_foreign","foreign_throw",
])
def test_actual_srp_dispatcher(host,case):
    result=subprocess.run([str(host),case],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
