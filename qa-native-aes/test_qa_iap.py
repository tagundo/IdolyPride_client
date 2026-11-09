from pathlib import Path
import hashlib
import struct
from zipfile import ZipFile

import pytest

import qa_iap
from qa_fast_aes import Image


@pytest.fixture(scope="module")
def native():
    root = Path(__file__).resolve().parents[1]
    candidates = (root / "data/ci-input/Game-local-r2.apk", root / "data/clients/Game-r2-pinned.apk")
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        pytest.skip("Pinned r2 QA input is needed for original ARM64 factory execution")
    with ZipFile(source) as archive:
        return archive.read("lib/arm64-v8a/libil2cpp.so")


def test_unknown_native_version_is_rejected():
    with pytest.raises(ValueError, match="audited 6.1.1"):
        qa_iap.patch_initializer(b"different native version")


def test_only_initializer_replaced_and_managed_factory_abi_executed(native):
    patched, report = qa_iap.patch_initializer(native)
    offset = Image(native).offset(qa_iap.INITIALIZE)
    assert len(patched) == len(native)
    assert patched[:offset] == native[:offset]
    assert patched[offset + 32:] == native[offset + 32:]
    branch = struct.unpack_from("<I", patched, offset + 12)[0]
    immediate = branch & 0x3FFFFFF
    if immediate & 0x2000000:
        immediate -= 0x4000000
    assert qa_iap.INITIALIZE + 12 + immediate * 4 == qa_iap.FACTORY
    result = qa_iap.verify_abi(native, patched)
    assert result["arm64_execution_checks"] == 2
    assert result["real_managed_factory_and_success_getter_executed"]
    assert result["hidden_x8_preserved_across_runtime_calls"]
    assert result["callee_saved_x19_through_x29_and_sp_preserved"]
    assert result["return_buffer_boundary_preserved"]
    assert report["purchase_receipt_grant_functions_modified"] is False
    assert report["store_initialized"] is False


@pytest.mark.parametrize("target,error", [(qa_iap.INITIALIZE, "prologue"), (qa_iap.FACTORY, "factory/getter")])
def test_prologue_and_factory_are_independently_guarded(native, monkeypatch, target, error):
    altered = bytearray(native)
    altered[Image(native).offset(target)] ^= 1
    altered = bytes(altered)
    # Even an explicitly accepted new hash cannot bypass instruction guards.
    monkeypatch.setattr(qa_iap, "ORIGINAL_SHA256", hashlib.sha256(altered).hexdigest())
    with pytest.raises(ValueError, match=error):
        qa_iap.patch_initializer(altered)


def test_abi_verifier_rejects_changes_outside_initializer(native):
    patched, _ = qa_iap.patch_initializer(native)
    altered = bytearray(patched)
    altered[Image(native).offset(qa_iap.FACTORY)] ^= 1
    with pytest.raises(ValueError, match="only the 32-byte"):
        qa_iap.verify_abi(native, bytes(altered))
