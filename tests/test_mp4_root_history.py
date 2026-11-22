"""Actual shipping immutable Root history/cohort/construction state bodies.

The fixtures model the named metadata, native getters and independent module
fences at their typed boundaries. Dictionary bytes, Root semantic collection,
path traversal, capture invocation, retained-image/GC lifetime, old-graph
retirement and completed saved-Evaluate/constructor joins use shipping code.
These are CPU/service tests, not device/GPU/MP4 output evidence.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'
FIX = ROOT / 'tests/fixtures/mp4_root_history'
COUNTS = {'image': 33, 'cache': 38, 'read': 30, 'path': 14, 'marker': 25,
          'cohort': 23, 'retired': 20, 'construction': 31, 'saved-evaluate': 60}


def between(text, start, end):
    at = text.index(start)
    return text[at:text.index(end, at)]


@pytest.fixture(scope='module')
def history_binaries(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    text = (NATIVE / 'bridge.cpp').read_text()
    folder = tmp_path_factory.mktemp('shipping-root-history')
    (folder / 'history.hpp').write_text('#pragma once\n' + marker(text, 'MP4_ROOT_HISTORY_CORE'))
    def f(name):
        return (FIX / name).read_text()
    read = marker(text, 'MP4_ROOT_HISTORY_READ_HOST')
    path = between(read, 'bool mp4_root_history_path(', 'bool mp4_root_history_flags(')
    # Cache/path/static-field readers are independent typed services in the
    # semantic-reader fixture; their real bodies have separate cases.
    start, end = read.index('bool mp4_root_history_path('), read.index('bool mp4_root_history_cache(')
    read = read[:start] + read[end:]
    context = between(text, 'struct Mp4TimelineContext {', '\n};') + '\n};\n'
    lineage = marker(text, 'MP4_ROOT_HISTORY_LINEAGE_POOL_HOST')
    retired = between(lineage, 'Mp4RootHistoryLineagePool::Record*mp4_root_history_record(', 'mp4child::Result mp4_root_history_store(')
    start, end = retired.index('Mp4TimelineContext*mp4_root_history_context('), retired.index('bool mp4_root_history_retired(')
    retired = retired[:start] + retired[end:]
    bodies = {
        'image': f('history-fixture.cpp'),
        'cache': f('cache-prefix.cpp.inc') + marker(text, 'MP4_ROOT_HISTORY_CACHE_HOST') + f('cache-main.cpp.inc'),
        'read': f('read-prefix.cpp.inc') + read + f('read-main.cpp.inc'),
        'path': f('path-prefix.cpp.inc') + path + f('path-main.cpp.inc'),
        'marker': f('marker-prefix.cpp.inc') + marker(text, 'MP4_ROOT_CAPTURE_MARKER_HOST') + f('marker-main.cpp.inc'),
        'cohort': f('cohort-prefix.cpp.inc').replace('// ACTUAL_CONTEXT', context) + marker(text, 'MP4_ROOT_HISTORY_PROVISIONAL_HOST') + marker(text, 'MP4_ROOT_HISTORY_INITIAL_COHORT_HOST') + f('cohort-main.cpp.inc'),
        'retired': f('retired-prefix.cpp.inc') + retired + f('retired-main.cpp.inc'),
        'construction': f('construction-prefix.cpp.inc') + marker(text, 'MP4_ROOT_HISTORY_CONSTRUCTION_QUERY_HOST') + f('construction-main.cpp.inc'),
        'saved-evaluate': f('saved-evaluate-prefix.cpp.inc') + marker(text, 'MP4_ROOT_HISTORY_SAVED_EVALUATE_HOST') + f('saved-evaluate-main.cpp.inc'),
    }
    binaries = {}
    for name, body in bodies.items():
        source, binary = folder / (name + '.cpp'), folder / name
        source.write_text(body)
        result = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-I' + str(folder), str(source), '-o', str(binary)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        binaries[name] = binary
    return binaries


@pytest.mark.parametrize('kind,mode', [(kind, mode) for kind, count in COUNTS.items() for mode in range(count)])
def test_shipping_actual_root_history_and_cohort_boundaries(history_binaries, kind, mode):
    result = subprocess.run([str(history_binaries[kind]), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
