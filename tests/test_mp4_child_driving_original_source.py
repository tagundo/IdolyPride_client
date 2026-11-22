"""Finite shipping selectors/ABI/source bytes are locked to immutable originals."""
import importlib.util
import os
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('audit_mp4_child_driving', ROOT / 'tools/audit_mp4_child_driving.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_shipping_finite_director_control_source_calls_and_tail_edges():
    source = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    for platform in ('android', 'ios'):
        methods, edges = audit.pins(source, platform)
        assert len(methods) == 7
        assert [(parent, nested, tail) for parent, nested, _, _, _, tail in edges] == [(0, 5, True), (3, 4, False), (3, 6, False)]
        assert edges[0][3] == 0


def test_actual_whole_original_selector_layout_and_code_provenance():
    originals = Path(os.environ.get('IDOLY_ORIGINAL_CLIENTS', '/workspace/shared/idoly-sdk-cache-analysis'))
    if not all((originals / name).is_file() for name in ('android-metadata.dat', 'android-native.so', 'ios-metadata.dat', 'ios-native.bin', 'mp4-android-analysis/libunity.so')):
        pytest.skip('External immutable original clients are not present')
    assert audit.audit(originals) == {'methods': 14, 'direct_bl': 4, 'tail_b': 2, 'layouts': 2}
