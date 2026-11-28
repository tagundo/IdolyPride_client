"""Owned UACD getter publication preserves ordinary renderer semantics."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_renderer_publication_reentrant_source_and_gpu_cleanup(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    binary = tmp_path / 'renderer-publication'
    subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT),
                    str(ROOT / 'tests/mp4_renderer_publication_harness.cpp'),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
