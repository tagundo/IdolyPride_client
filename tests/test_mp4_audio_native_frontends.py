"""Actual shipping Audio frontend/retirement joins; native ARM and leaf calls modeled."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]


def _marker(text, name):
    begin = text.index('// BEGIN_' + name)
    end = text.index('// END_' + name, begin) + len('// END_' + name)
    return text[begin:end]


@pytest.mark.parametrize('family', ('frontend', 'retirement'))
def test_shipping_audio_native_frontend(tmp_path, family):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    fixture = (ROOT / 'tests/fixtures' / ('mp4_audio_native_' + family + '.cpp.inc')).read_text()
    markers = [('SOURCE_PINS', 'MP4_AUDIO_NATIVE_FRONTEND_PINS'), ('NATIVE_FRONTENDS', 'MP4_AUDIO_NATIVE_FRONTEND_HOST')] if family == 'frontend' else [('RETIREMENT_BIND', 'MP4_AUDIO_NATIVE_RETIREMENT_BIND_HOST')]
    for slot, marker in markers:
        fixture = fixture.replace('// ' + slot, _marker(bridge, marker))
    source, binary = tmp_path / 'test.cpp', tmp_path / 'test'
    source.write_text(fixture)
    built = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            str(source), '-o', str(binary)], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1', 'UBSAN_OPTIONS':'halt_on_error=1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert ('29 actual Audio frontend cases' if family == 'frontend' else '17 actual Audio retirement binding cases') in result.stdout
