"""Mac compatibility exports and build-only translation input validation."""
from __future__ import annotations

from pathlib import Path

# Preserve the existing Mac import surface while native in-process hosts share
# the same public-data installation policy directly from the portable package.
from idoly_local.public_payload import (
    FIXED_FILES, PACK_PREFIX, install_bundled_translations, install_payload, member_path,
)


def translation_bundle_input(source=None, expected_sha256=None, expected_bytes=None):
    """Validate optional producer inputs identically for both Mac builders."""
    values = (source, expected_sha256, expected_bytes)
    if all(value is None for value in values):
        return None, {"included": False}
    if any(value is None for value in values):
        raise ValueError("Optional translations require explicit path, SHA and bytes together")
    from idoly_local.bundled_translations import validate_translation_bundle

    source = Path(source).expanduser().absolute()
    report = validate_translation_bundle(source, expected_sha256=expected_sha256,
                                          expected_bytes=expected_bytes, platform="ios")
    return source, {"included": True, **report}
