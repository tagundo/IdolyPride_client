"""Immutable source factory/early VM service ABI and real ARM dispatch block."""
import importlib.util
import os
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit_mp4_passive_source_factory import audit,execute_dispatch

@pytest.fixture(scope='module')
def originals():
    path=Path(os.environ.get('IDOLY_ORIGINAL_CLIENTS','/workspace/shared/idoly-sdk-cache-analysis'))
    if not all((path/name).is_file() for name in ('android-metadata.dat','android-native.so','ios-metadata.dat','ios-native.bin','mp4-android-analysis/libunity.so')):
        pytest.skip('External immutable original clients are not present')
    return path

def test_whole_original_factory_virtual_pair_and_early_source_services(originals):
    if importlib.util.find_spec('capstone') is None:pytest.skip('Capstone is required for actual source disassembly')
    assert audit(originals)=={'methods':8,'dispatch_blocks':2,'layouts':2}

@pytest.mark.parametrize('platform,variant',[(platform,variant) for platform in ('android','ios') for variant in range(2)])
def test_actual_original_arm_factory_abi_and_true_caller_return(originals,platform,variant):
    if importlib.util.find_spec('unicorn') is None:pytest.skip('Unicorn is required for actual source ARM execution')
    result=execute_dispatch(originals,platform,variant)
    assert result['arguments']==5 and result['aggregate_bytes']==16
