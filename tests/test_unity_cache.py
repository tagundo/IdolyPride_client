from hashlib import sha1, sha256
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


def test_serialized_prefab_repair_versions_existing_extracted_resources():
    before = "5e55c12ddc6a08a8d96e8b3f616537ef5f833d99a3948c90de99bfd0521da292"
    after = "fbb0ced4360da452cc6b389d30847021903dea731cdc900cae932d99191b0350"
    old, _ = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS)
    fixed, proof = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
                                         serialized_asset_sha256=after)
    assert fixed != old
    assert fixed != cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
                                           serialized_asset_sha256=before)[0]
    # Independently derive the UUID bits from the namespace and exact asset hash.
    name = "|".join(("idoly-local-code-assets-v2", METADATA, SETTINGS, after))
    digest = bytearray(sha1(uuid.UUID(cache.ORIGINAL_GUID.decode()).bytes + name.encode()).digest()[:16])
    digest[6] = digest[6] & 15 | 80
    digest[8] = digest[8] & 63 | 128
    assert fixed == str(uuid.UUID(bytes=bytes(digest))).encode()
    assert proof['serialized_asset_sha256'] == after
    assert proof['device_files_read_or_deleted_by_builder'] is False


@pytest.mark.parametrize('value', ['', 'g' * 64, 'A' * 64, 1, b'a' * 64])
def test_invalid_serialized_resource_digest_rejected(value):
    with pytest.raises(ValueError, match='SHA-256'):
        cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
                                serialized_asset_sha256=value)


def test_localized_font_and_prefab_outputs_version_the_extracted_cache():
    serialized = "f" * 64
    prior, _ = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
                                      serialized_asset_sha256=serialized)
    korean, proof = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
        serialized_asset_sha256=serialized, presentation_assets_sha256="a" * 64)
    other, _ = cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
        serialized_asset_sha256=serialized, presentation_assets_sha256="b" * 64)
    assert len({prior, korean, other}) == 3
    assert proof["domain"] == "idoly-local-code-presentation-v3"
    assert proof["presentation_assets_sha256"] == "a" * 64
    assert proof["device_files_read_or_deleted_by_builder"] is False
    with pytest.raises(ValueError, match="serialized asset"):
        cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
                                 presentation_assets_sha256="a" * 64)


@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, 1, b"a" * 64])
def test_invalid_presentation_asset_digest_rejected(value):
    with pytest.raises(ValueError, match="presentation assets"):
        cache.derive_cache_guid(cache.ORIGINAL_GUID, METADATA, SETTINGS,
            serialized_asset_sha256="f" * 64, presentation_assets_sha256=value)


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
