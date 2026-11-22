"""Exercise shipping RootTimeline phase/structural visitor order, without Unity/GPU claims."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

def function(source, name):
    m = re.search(r'(?:\[\[maybe_unused\]\] )?bool\s+' + name + r'\(', source)
    assert m, name
    at = source.index('{', m.start())
    depth, end = 1, at + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[m.start():end] + '\n'

@pytest.fixture(scope='module')
def spine(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    text = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    actual = ''.join(function(text, name) for name in (
        'mp4_timeline_source_plan_phase', 'mp4_timeline_current', 'mp4_timeline_phase_witness_current', 'mp4_timeline_phase_current',
        'mp4_timeline_original_rebuild_complete', 'mp4_timeline_restoration_plan_closed',
        'mp4_timeline_visit_owned_contexts'))
    fixture = (ROOT / 'tests/fixtures/mp4_root_timeline_phase_host.cpp.inc').read_text()
    folder = tmp_path_factory.mktemp('root-phase')
    src, binary = folder / 'test.cpp', folder / 'test'
    src.write_text(fixture.replace('// SHIPPING_ROOT_TIMELINE_PHASE_HOST', actual))
    built = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                            str(src), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary

@pytest.mark.parametrize('mode', '''bootstrap_plan bootstrap_missing_receipt bootstrap_other_source capture_partial capture_unconfigured capture_wrong_phase capture_clock_running
capture_admission restore_partial restore_plan restore_final_visitor restore_unprepared restore_nonheld
admission admission_after_stage_cleanup admission_receipt_lost admission_other_source admission_unpublished active_stage_source_lost current_missing_callback current_foreign_graph
active_held_partial active_started_partial active_started_complete restore_plan_before_children
restore_final_children_pending restore_final_parent_pending restore_final_eval_pending restore_final_speed_pending
restore_final_full context_wrong_list_version context_source_lost'''.split())
def test_shipping_root_timeline_phase_host(spine, mode):
    run = subprocess.run([str(spine), mode], capture_output=True, text=True, timeout=10,
                         env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                              'UBSAN_OPTIONS': 'halt_on_error=1'})
    assert run.returncode == 0, run.stdout + run.stderr
