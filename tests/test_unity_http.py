from hashlib import sha256
from pathlib import Path
import struct
from zipfile import ZipFile

import pytest

from idoly_local import unity_http as policy


@pytest.fixture(scope="module")
def original():
    root = Path(__file__).resolve().parents[1]
    candidates = [root / "data/clients/Game-r2-pinned.apk",
                  Path("/dev/shm/idoly-title-observer-v2/IdolyPride-normal-local-UI-QA-v2.apk")]
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        pytest.skip("Pinned user-supplied client fixture is not cached")
    with ZipFile(source) as archive:
        return archive.read(policy.MEMBER)


def test_pinned_original_fixture_changes_only_one_transport_policy_byte(original):
    assert sha256(original).hexdigest() == policy.ORIGINAL_SHA256
    assert policy.validate_shape(original) == policy.NOT_ALLOWED
    after, proof = policy.patch_player_http(original)
    assert len(after) == len(original)
    assert policy.validate_shape(after) == policy.ALWAYS_ALLOWED
    assert after[:policy.FIELD_OFFSET] == original[:policy.FIELD_OFFSET]
    assert after[policy.FIELD_OFFSET + 1:] == original[policy.FIELD_OFFSET + 1:]
    assert original[policy.FIELD_OFFSET:policy.FIELD_OFFSET + 4] == b"\0\0\0\0"
    assert after[policy.FIELD_OFFSET:policy.FIELD_OFFSET + 4] == b"\x02\0\0\0"
    assert sha256(after).hexdigest() == policy.PATCHED_SHA256
    assert proof["sdk_initialization_success_flags_or_tls_validation_changed"] is False
    assert proof["android_cleartext_hosts_unchanged"] == ["127.0.0.1"]


@pytest.mark.parametrize("data", [b"", b"\0" * 48, b"arbitrary input"])
def test_wrong_length_rejected_without_parsing_or_allocating_file_size(data):
    with pytest.raises(ValueError, match="size differs"):
        policy.patch_player_http(data)


def test_wrong_fingerprint_rejected_before_fixed_offset_write(original):
    changed = bytearray(original)
    changed[-1] ^= 1
    with pytest.raises(ValueError, match="fingerprint differs"):
        policy.patch_player_http(bytes(changed))


def test_wrong_serialized_file_header_rejected(original):
    changed = bytearray(original)
    struct.pack_into(">I", changed, 8, 21)
    with pytest.raises(ValueError, match="SerializedFile"):
        policy.patch_player_http(bytes(changed))


def test_already_enabled_or_unrecognized_policy_rejected(original):
    changed = bytearray(original)
    struct.pack_into("<i", changed, policy.FIELD_OFFSET, 2)
    with pytest.raises(ValueError, match="original Unity HTTP policy"):
        policy.patch_player_http(bytes(changed))
    struct.pack_into("<i", changed, policy.FIELD_OFFSET, 99)
    with pytest.raises(ValueError, match="original Unity HTTP policy"):
        policy.patch_player_http(bytes(changed))
