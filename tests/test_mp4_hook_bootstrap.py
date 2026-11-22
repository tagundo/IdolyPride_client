"""Shipping exact backend install receipts against unchanged upstream ARM64 rewrites.

The original byte-generator is unchanged Shadowhook 2.0.1 MIT source. Platform
loader/record/code memory and actual hooking are explicit typed host fixtures;
these tests are not Android installation, GPU, device or completed export proof.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/mp4_hook_bootstrap'


@pytest.mark.parametrize('corrupt_ip', [False, True])
def test_shipping_bootstrap_exact_original_gateway_and_publication(tmp_path, corrupt_ip):
    cc, cxx = shutil.which('cc'), shutil.which('c++')
    if not cc or not cxx:
        pytest.skip('Host C and C++ compilers are required')
    original = (FIXTURE / 'sh_a64.c').read_bytes()
    assert hashlib.sha256(original).hexdigest() == '4a7185fe3efd2150a68400a0c221c2d7c711a21f53627eb3613a3e6ec89efb10'
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    core = bridge.split('// BEGIN_MP4_HOOK_BOOTSTRAP_CORE\n', 1)[1].split('// END_MP4_HOOK_BOOTSTRAP_CORE', 1)[0]
    (tmp_path / 'shipping-bootstrap.hpp').write_text('#pragma once\n' + core)
    for path in FIXTURE.iterdir():
        shutil.copyfile(path, tmp_path / path.name)
    flags = ['-Wall', '-Wextra', '-Werror', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    configured = ['-DSH_CONFIG_CORRUPT_IP_REGS=1'] if corrupt_ip else []
    obj, binary = tmp_path / 'original.o', tmp_path / 'bootstrap'
    result = subprocess.run([cc, '-std=c11', *flags, *configured, '-I', str(tmp_path), '-c', str(tmp_path / 'sh_a64.c'), '-o', str(obj)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([cxx, '-std=c++17', *flags, '-no-pie', '-I', str(tmp_path), str(tmp_path / 'driver.cpp'), str(obj), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'bootstrap cases 191 passed\n'
