"""Actual Actor producer helper, modeled Unity leaves; no native/GPU run."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
CASES = "source_admission active_source restore_plan restored source_changed pins inventory presentation temporal_plan binding foreign_player owned_actor_child foreign_child director_asset_changed director_graph_changed director_roster_changed wrong_director duplicate_actor_component wrong_actor_component virtual_reset_changed virtual_setup_changed unknown_reset wrong_swing base_reset unknown_setup unknown_weight metadata dirty_param_rows param_queue param_motion unknown_outer_callback unknown_callback unknown_outer_play duplicate_track_player owned_actor_swing_job owned_fixed_job wrong_fixed_job_owner unknown_actor_job unknown_actor_clip unknown_actor_script unregistered_actor_child pure_actor_mixer foreign_actor_root different_actor_mixer different_actor_graph different_master_graph missing_actor_input missing_authored_clip duplicate_runtime runtime_wrong_parent runtime_wrong_asset motion_swapped motion_reference exposed_default foot_changed wrong_native_clip_asset wrong_layer_kind wrong_layer_graph wrong_clip_graph stale_handle scheduled foreign_runtime ignored_userdata unrecognized foreign_actor_script".split()
@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    begin = bridge.index("// BEGIN_MP4_TIMELINE_ACTOR_PRODUCER_HOST")
    end = bridge.index("// END_MP4_TIMELINE_ACTOR_PRODUCER_HOST", begin)
    source = (FIXTURES / "mp4_timeline_actor_prefix.cpp.inc").read_text() + bridge[begin:end]
    source += (FIXTURES / "mp4_timeline_actor_driver.cpp.inc").read_text()
    directory = tmp_path_factory.mktemp("mp4-timeline-actor")
    path = directory / "host.cpp"
    path.write_text(source)
    binary = directory / "host"
    result = subprocess.run([shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-g", "-O1", "-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-I", str(ROOT / "client-presentation/native"), str(path), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary
@pytest.mark.parametrize("case", CASES)
def test_actual_actor_producer_source_and_receivers(host, case):
    result = subprocess.run([str(host), case], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
