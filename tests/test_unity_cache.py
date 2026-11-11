from hashlib import sha256
import uuid

import pytest

from idoly_local import unity_cache as cache


METADATA = "ddaabf9d842fe89a4c9c07f09876c2e546aa1ba94b127694a849c8d2bb17c436"
SETTINGS = "21c7da3b2fb6e0775301667d6a809918144ce5939f0e99908a467ce29ac337d1"


def test_pinned_original_guid_derives_deterministic_canonical_code_cache_version():
    result, proof = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS)
    # Independently reproduced from SHA1(namespace bytes || UTF-8 name), then
    # applying the RFC UUID version/variant bits without calling uuid.uuid5.
    assert result == b"c07eb3a7-ce76-523d-8bfa-19c3a9eb6b36"
    assert len(cache.ORIGINAL_GUID) == len(result) == 36
    assert sha256(cache.ORIGINAL_GUID).hexdigest() == cache.ORIGINAL_SHA256
    assert result != cache.ORIGINAL_GUID
    assert result == cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS)[0]
    parsed = uuid.UUID(result.decode("ascii"))
    assert parsed.version == 5 and str(parsed).encode() == result
    assert proof["metadata_sha256"] == METADATA and proof["globalgamemanagers_sha256"] == SETTINGS
    assert proof["device_files_read_or_deleted_by_builder"] is False
    assert proof["account_settings_sdk_flags_or_clocks_changed"] is False


def test_old_engine_cache_marker_differs_and_either_build_input_versions_it():
    old_cached_unity_ver = cache.ORIGINAL_GUID
    new, _ = cache.derive_cache_guid(old_cached_unity_ver, METADATA, SETTINGS)
    assert old_cached_unity_ver != new
    assert cache.derive_cache_guid(old_cached_unity_ver, "0" * 64, SETTINGS)[0] != new
    assert cache.derive_cache_guid(old_cached_unity_ver, METADATA, "1" * 64)[0] != new
    # Unity's original equal/mismatch decision can now take its normal extraction path.
    assert (old_cached_unity_ver == cache.ORIGINAL_GUID) and not (old_cached_unity_ver == new)


@pytest.mark.parametrize("value", [b"", cache.ORIGINAL_GUID + b"\n", b"x" * 36,
    cache.ORIGINAL_GUID.upper(), b"00000000-0000-0000-0000-000000000000", "not bytes"])
def test_wrong_or_noncanonical_original_guid_rejected(value):
    with pytest.raises(ValueError):
        cache.derive_cache_guid(value, METADATA, SETTINGS)


@pytest.mark.parametrize("value", [None, "", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_non_sha256_build_input_rejected(value):
    with pytest.raises(ValueError, match="SHA-256"):
        cache.derive_cache_guid(cache.ORIGINAL_GUID, value, SETTINGS)
    with pytest.raises(ValueError, match="SHA-256"):
        cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, value)
