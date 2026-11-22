"""Entire shipping source-roster body; public queries/PM/target leaves modeled."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
MODES = ['all_retain_failures','all_query_throws','baseline','cross_director','null_target','null_graph','uncovered_target','bad_role','foreign_target_provider','bad_target_native','unknown_track','duplicate_track','track_cycle','graph_invalid','root_missing','throw_collect','retain_failure','graph_only_partial_retry','changed_graph','changed_graph_version','changed_root','output_count','output_order','output_version','output_target','nonanimation_replaced','output_type','new_director','director_order','director_version','director_list_identity','director_asset','null_graph_becomes_live','root_lost','graph_root_lost','native_identity','binding_changed','foreign_generation','selected_source','prefix_changed','origin_changed','borrowed_failure_clears','release_offthread','throw_current','retry_after_partial']


@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    begin = bridge.index('// BEGIN_MP4_TIMELINE_ANIMATION_SOURCE_WORKER_ROSTER')
    end = bridge.index('// END_MP4_TIMELINE_ANIMATION_SOURCE_WORKER_ROSTER', begin)
    body = bridge[begin:end]
    folder = tmp_path_factory.mktemp('source-roster')
    prefix = (ROOT / 'tests/fixtures/mp4_animation_source_roster/prefix.cpp.inc').read_text()
    driver = (ROOT / 'tests/fixtures/mp4_animation_source_roster/driver.cpp.inc').read_text()
    result = {}
    for platform in ('android', 'ios'):
        source, binary = folder / f'{platform}.cpp', folder / platform
        source.write_text(prefix + body + driver)
        flags = ['-DIDOLY_DARWIN_BRIDGE=1'] if platform == 'ios' else []
        subprocess.run(['g++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', *flags, str(source), '-o', str(binary)], check=True)
        result[platform] = binary
    return result


@pytest.mark.parametrize('platform,mode', [(p, m) for p in ('android', 'ios') for m in MODES])
def test_actual_source_roster(binaries, platform, mode):
    subprocess.run([str(binaries[platform]), mode], check=True, timeout=30)
