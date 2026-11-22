"""Immutable-source check for the shipping finite bootstrap source24 arrays."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
MODULE = ROOT / 'tools/audit_mp4_bootstrap_hooks.py'
spec = importlib.util.spec_from_file_location('audit_mp4_bootstrap_hooks', MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_shipping_source_arrays_are_finite_and_separate_images():
    text = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    for platform in ('android', 'ios'):
        primary = audit.source_pins(text, platform + '_bootstrap_pins')
        assert [row[0] for row in primary] == [*audit.NATIVE_ROLES, 'factory']
        assert [row[1] for row in primary] == ['engine'] * 7 + ['game']
        extras = audit.source_pins(text, platform + '_managed_extra_pins')
        assert all(row[0] == 'factory' and row[1] == 'game' for row in extras)


def test_rederive_all_shipping_source24_from_whole_verified_originals():
    originals = Path(os.environ.get('IDOLY_ORIGINAL_CLIENTS', '/workspace/shared/idoly-sdk-cache-analysis'))
    if not all((originals / name).is_file() for name in ('android-metadata.dat', 'android-native.so', 'ios-metadata.dat', 'ios-native.bin', 'mp4-android-analysis/libunity.so')):
        pytest.skip('External immutable original client inputs are not present')
    assert audit.audit(originals) == {'native_factory': 16, 'shader_capture': 16}
