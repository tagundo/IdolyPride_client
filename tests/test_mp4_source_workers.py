"""Actual Source worker/callback markers; original engine/query leaves modeled."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mp4_source_workers"
MODES = ['baseline', 'live_callback_wait', 'foreign_callback_sticky', 'callback_overflow', 'particle_wait', 'partial_roster', 'roster_throw', 'retain_partial', 'complete_failure', 'complete_throw', 'source_lost_mid_complete', 'callback_during_complete', 'source_lost_release', 'wrong_key_release', 'release_callback_wait', 'release_particle_wait', 'release_roster_wait', 'release_particle_callback', 'release_roster_callback', 'release_roster_post_callback', 'release_offthread', 'withdraw_offthread', 'withdraw_wrong_key', 'new_watch_old_withdraw', 'current_job_changed', 'current_native_identity', 'current_foot_scheduled', 'current_inventory', 'current_animation', 'current_particle', 'current_pipeline_busy', 'binding']


def marker(bridge, name):
    start = bridge.index("// BEGIN_" + name)
    end = bridge.index("// END_" + name, start)
    return bridge[start:end]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    callback = marker(bridge, "MP4_SOURCE_PRODUCER_CALLBACK_OBSERVERS")
    worker = marker(bridge, "MP4_CONCRETE_SOURCE_WORKERS")
    folder = tmp_path_factory.mktemp("source-workers")
    result = {}
    for kind, prefix, body, driver in (
        ("workers", "prefix.cpp.inc", callback + worker, "driver.cpp.inc"),
        ("callbacks", "callback-test-prefix.cpp.inc", callback, "callback-test-driver.cpp.inc"),
    ):
        source, binary = folder / (kind + ".cpp"), folder / kind
        source.write_text((FIXTURES / prefix).read_text() + body + (FIXTURES / driver).read_text())
        subprocess.run([
            "g++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie", "-pthread",
            str(source), "-o", str(binary),
        ], check=True)
        result[kind] = binary
    return result


@pytest.mark.parametrize("mode", MODES)
def test_actual_source_workers(binaries, mode):
    subprocess.run([str(binaries["workers"]), mode], check=True, timeout=30)


@pytest.mark.parametrize("case", range(14))
def test_actual_source_callback_observers(binaries, case):
    subprocess.run([str(binaries["callbacks"]), str(case)], check=True, timeout=30)


@pytest.fixture(scope="module")
def property_rw_binaries(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    callback = marker(bridge, "MP4_SOURCE_PRODUCER_CALLBACK_OBSERVERS")
    folder = tmp_path_factory.mktemp("source-property-rw")
    result = {}
    for kind, driver in (("rw", "property-rw-driver.cpp.inc"), ("wait", "property-rw-wait-driver.cpp.inc")):
        source, binary = folder / (kind+".cpp"), folder / kind
        source.write_text((FIXTURES/"property-rw-prefix.cpp.inc").read_text()+callback+(FIXTURES/driver).read_text())
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-pthread", str(source), "-o", str(binary)], check=True)
        result[kind] = binary
    return result


@pytest.mark.parametrize("case", ["current", "nested", "foreign_guard", "typed_throw"]+[family+str(i) for family in ["ordinary", "main_reentry", "existing_writer"] for i in range(3)])
def test_property_rw_writer_exclusion(property_rw_binaries, case):
    subprocess.run([str(property_rw_binaries["rw"]), case], check=True, timeout=30)


@pytest.mark.parametrize("family", range(3))
def test_foreign_writer_waits_before_original_during_property_access(property_rw_binaries, family):
    subprocess.run([str(property_rw_binaries["wait"]), str(family)], check=True, timeout=30)
