"""Shipping Frame/production join; physical GPU and engine calls are modeled."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]


def _marker(text, name):
    first = text.index('// BEGIN_' + name)
    last = text.index('// END_' + name, first) + len('// END_' + name)
    return text[first:last]


def _run(tmp_path, fixture, expected, threaded=False):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    source, binary = tmp_path / 'test.cpp', tmp_path / 'test'
    source.write_text(fixture)
    command = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-Wno-misleading-indentation', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    if threaded:
        command += ['-pthread']
    built = subprocess.run(command + [str(source), '-o', str(binary)],
                           capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                 'UBSAN_OPTIONS': 'halt_on_error=1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def test_shipping_native_capture_publication_host(tmp_path):
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    fixture = (ROOT / 'tests/fixtures/mp4_capture_native_host.cpp.inc').read_text()
    fixture = fixture.replace('// NATIVE_PINS', _marker(bridge, 'MP4_CAPTURE_NATIVE_PINS'))
    fixture = fixture.replace('// NATIVE_HOST', _marker(bridge, 'MP4_CAPTURE_NATIVE_PUBLICATION_HOST'))
    _run(tmp_path, fixture, '29 native publication host cases', threaded=True)


def test_shipping_frame_capture_join(tmp_path):
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    owner = (ROOT / 'client-presentation/native/mp4_camera_owner.hpp').read_text()
    bank = _marker(owner, 'MP4_CAPTURE_PRODUCTION_BANK')
    assert 'bool scopes_unwound()const noexcept' in bank
    fixture = (ROOT / 'tests/fixtures/mp4_frame_capture_host.cpp.inc').read_text()
    fixture = fixture.replace('// REAL_PRODUCTION_BANK', bank)
    fixture = fixture.replace('// ACTUAL_JOIN', _marker(bridge, 'MP4_FRAME_CAPTURE_JOIN'))
    _run(tmp_path, fixture, '15 Frame/Capture join cases')
