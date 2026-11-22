"""Original-byte proof for the native icall's caller and direct capture output."""
from pathlib import Path
import importlib.util
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_original_publication_caller_and_capture_destination():
    originals=Path('/workspace/shared/idoly-sdk-cache-analysis')
    if not (originals/'android-native.so').is_file() or not (originals/'ios-native.bin').is_file():
        pytest.skip('Pinned original Android/iOS source images unavailable')
    sys.path.insert(0,str(ROOT/'tools'))
    spec=importlib.util.spec_from_file_location('capture_source_audit',ROOT/'tools/audit_mp4_capture_global.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    profiles=module.audit(originals)
    header=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    for start,end,expected in [
        ('// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE','// END_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE',module.profile_text(profiles)),
        ('// BEGIN_MP4_CAPTURE_PUBLICATION_PROFILE','// END_MP4_CAPTURE_PUBLICATION_PROFILE',module.publication_text(profiles)),
    ]:
        assert header[header.index(start):header.index(end)+len(end)]==expected
    for platform,profile in profiles.items():
        # This bounded route proof must not become a fabricated all-writer lease.
        assert profile['all_writer_closure'] is False
        owned=profile['owned_publication']
        assert owned['original_return']=={'android':'0x923d4e4','ios':'0x7bcb81c'}[platform]
        assert 'direct_output_proof'in owned
        assert any('consumer closure'in requirement for requirement in owned['runtime_requires'])
