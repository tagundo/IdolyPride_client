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
        assert owned['update_return']=={'android':'0x923d50c','ios':'0x7bcb850'}[platform]
        assert owned['wrapper_return']=={'android':'0x923d380','ios':'0x7bcb6b4'}[platform]
        assert owned['texture_return']=={'android':'0x9236580','ios':'0x7bc33d4'}[platform]
        assert owned['aot']['wrapper_ctor']['rva']=={'android':'0x92364fc','ios':'0x7bc3348'}[platform]
        assert owned['aot']['texture_ctor']['rva']=={'android':'0x8f69e7c','ios':'0x7830f20'}[platform]
        producer=owned['capture_queue_producer']
        assert producer['rva']=={'android':'0x8e01414','ios':'0x76802ec'}[platform]
        assert 'NEW VLCapturePass'in producer['proof']
        assert 'active renderer queue/issued-pass lifetime'in producer['retirement_requires']
        assert 'direct_output_proof'in owned
        assert any('consumer closure'in requirement for requirement in owned['runtime_requires'])
