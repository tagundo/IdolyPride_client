"""Offline translations of individually audited native display literals.

The caller first verifies its stock/base metadata and routing transformations,
then supplies the preceding producer's output SHA-256. This preserves the
verification chain even when an iOS build uses a custom local API endpoint.
Generic Localify dictionary matches never extend the fixed display allowlist.
"""
from __future__ import annotations

import hashlib
import re

from .client_patch import literal_rows
from .ui_translation_build import translate_metadata_literals

POLICY = "native-display-literals-v1"
MAX_METADATA_BYTES = 32 * 1024 * 1024
SOURCE_TEXT = "開催中のイベントはありません"
PROFILES = {
    "android": {
        "literal_index": 35651,
        "original_metadata_sha256": "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e",
        "display_method": "Solis.OutGame.MenuButtonUtility.<OnClickAsync>d__7.MoveNext",
        "method_rva": "0x5250d48", "display_call_rva": "0x5252cb0",
        "callee": "Solis.Common.ToastManager.Show", "callee_rva": "0x4654510",
    },
    "ios": {
        "literal_index": 34989,
        "original_metadata_sha256": "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda",
        "display_method": "Solis.OutGame.MenuButtonUtility.<OnClickAsync>d__7.MoveNext",
        "method_rva": "0x2bb28e0", "display_call_rva": "0x2bb2e44",
        "callee": "Solis.Common.ToastManager.Show", "callee_rva": "0x1dbe3fc",
    },
}
TRANSLATIONS = {
    "ko": "진행 중인 이벤트가 없습니다.",
    "en": "There are no ongoing events.",
}


def patch_bytes(metadata, platform, language, *, expected_sha256):
    """Translate only the profiled toast after validating its exact build input."""
    if (not isinstance(platform, str) or platform not in PROFILES
            or not isinstance(language, str) or language not in ("ja", "ko", "en")):
        raise ValueError("Unsupported native display-literal platform or language")
    if not isinstance(metadata, bytes) or not 256 <= len(metadata) <= MAX_METADATA_BYTES:
        raise ValueError("Display-literal metadata exceeds its format bound")
    if (not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or hashlib.sha256(metadata).hexdigest() != expected_sha256):
        raise ValueError("Display-literal input differs from the preceding verified producer")
    profile = PROFILES[platform]
    index = profile["literal_index"]
    _, rows = literal_rows(metadata)
    if index >= len(rows) or rows[index][3] != SOURCE_TEXT.encode("utf-8"):
        raise ValueError("Audited native display literal index or Japanese text differs")
    del rows
    replacements = {SOURCE_TEXT: SOURCE_TEXT if language == "ja" else TRANSLATIONS[language]}
    result, proof = translate_metadata_literals(metadata, replacements,
        allowed_indexes=[index], expected_sha256=expected_sha256)
    expected_changed = [] if language == "ja" else [index]
    if proof["changed_indexes"] != expected_changed:
        raise ValueError("Native display-literal translation changed an unexpected index")
    return result, {
        "schema": 1, "policy": POLICY, "platform": platform, "language": language,
        "audited_original_metadata_sha256": profile["original_metadata_sha256"],
        "audited_display_literal_indexes": [index], "source_text": SOURCE_TEXT,
        "translated_text": SOURCE_TEXT if language == "ja" else TRANSLATIONS[language],
        "display_method": profile["display_method"], "display_call_rva": profile["display_call_rva"],
        "callee": profile["callee"], "generic_dictionary_match_all": False,
        "all_other_literals_and_metadata_sections_unchanged": True,
        "input_bound_to_preceding_producer": True, "runtime_translation_work": False,
        **proof,
    }
