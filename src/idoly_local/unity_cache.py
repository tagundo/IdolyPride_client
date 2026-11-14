"""Version Unity's extracted IL2CPP resources using their actual build inputs.

Original Unity reads assets/bin/Data/unity_app_guid and compares its 36 bytes
with the derived il2cpp/unity.ver marker. A new build GUID takes Unity's normal
resource-extraction path; this module never reads or deletes device/cache/account
files and does not change boot.config or PlayerSettings' product GUID.
"""
from __future__ import annotations

import hashlib
import re
import uuid


MEMBER = "assets/bin/Data/unity_app_guid"
ORIGINAL_GUID = b"a711296b-d0fa-4aa6-a376-90142093f41a"
ORIGINAL_SHA256 = "0495a6f0504dda9edd55c550dcf58e582df6a1c80cc530328bdf5ce5998c832a"
DOMAIN = "idoly-local-code-v1"
ASSET_DOMAIN = "idoly-local-code-assets-v2"


def derive_cache_guid(original: bytes, metadata_sha256: str, settings_sha256: str, *,
                      serialized_asset_sha256: str | None = None) -> tuple[bytes, dict]:
    if not isinstance(original, bytes) or len(original) != 36:
        raise ValueError("Expected a 36-byte Unity build GUID")
    try:
        text = original.decode("ascii")
        namespace = uuid.UUID(text)
    except (UnicodeDecodeError, ValueError, AttributeError):
        raise ValueError("Unity build GUID must be a canonical ASCII UUID") from None
    if str(namespace) != text:
        raise ValueError("Unity build GUID must be a canonical ASCII UUID")
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256 or original != ORIGINAL_GUID:
        raise ValueError("Unity build GUID differs from the pinned original client")
    if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
           for value in (metadata_sha256, settings_sha256)):
        raise ValueError("Unity cache inputs require lowercase SHA-256 digests")
    if serialized_asset_sha256 is not None and (not isinstance(serialized_asset_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", serialized_asset_sha256) is None):
        raise ValueError("Unity serialized asset input requires a lowercase SHA-256 digest")
    domain = DOMAIN if serialized_asset_sha256 is None else ASSET_DOMAIN
    inputs = (domain, metadata_sha256, settings_sha256)
    if serialized_asset_sha256 is not None:
        inputs += (serialized_asset_sha256,)
    name = "|".join(inputs)
    result = str(uuid.uuid5(namespace, name)).encode("ascii")
    if len(result) != 36 or result == original:
        raise ValueError("Unity derived build GUID did not change")
    proof = {"member": MEMBER, "algorithm": "UUIDv5", "domain": domain,
        "namespace_guid": text, "guid": result.decode("ascii"),
        "metadata_sha256": metadata_sha256, "globalgamemanagers_sha256": settings_sha256,
        "input_sha256": ORIGINAL_SHA256, "output_sha256": hashlib.sha256(result).hexdigest(),
        "bytes": 36, "engine_managed_il2cpp_cache_version": True,
        "device_files_read_or_deleted_by_builder": False,
        "account_settings_sdk_flags_or_clocks_changed": False}
    if serialized_asset_sha256 is not None:
        proof["serialized_asset_sha256"] = serialized_asset_sha256
    return result, proof
