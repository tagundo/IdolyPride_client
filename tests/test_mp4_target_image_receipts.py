"""Shipping TargetImage captured image + actual invocation receipts; engine leaves modeled."""
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


def test_shipping_target_image_capture_receipts(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ host compiler required')
    header = (ROOT / 'client-presentation/native/mp4_camera_owner.hpp').read_text()
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    fixture = (ROOT / 'tests/fixtures/mp4_target_image_receipts.cpp.inc').read_text()
    fixture = fixture.replace('// TARGET_SCOPE', _marker(header, 'MP4_TARGET_IMAGE_SCOPE'))
    fixture = fixture.replace('// CAPTURE_HOST', _marker(bridge, 'MP4_TARGET_IMAGE_CAPTURE_RECEIPT_HOST'))
    source, binary = tmp_path / 'test.cpp', tmp_path / 'test'
    source.write_text(fixture)
    built = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', str(source), '-o', str(binary)],
                           capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1', 'UBSAN_OPTIONS':'halt_on_error=1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert '20 exact TargetImage capture/image receipt cases' in result.stdout
