"""Repair two pinned, serialized story-loading radio fade references at build time.

The original 6.1.1 Android prefab has two RadioButtonView._fade references set
to null even though each radio already owns a CanvasGroup.  The loading
presenter also references these exact CanvasGroups.  This connects those
existing components; it does not change SetDisabled, exception handling, or
any runtime callback.  No asset parser or UnityPy dependency runs in production.
"""
from __future__ import annotations

import hashlib
import struct


MEMBER = "assets/bin/Data/7880e7e422d314c04a16c4690ae21a43"
FILE_BYTES = 49_540
INPUT_SHA256 = "5e55c12ddc6a08a8d96e8b3f616537ef5f833d99a3948c90de99bfd0521da292"
OUTPUT_SHA256 = "fbb0ced4360da452cc6b389d30847021903dea731cdc900cae932d99191b0350"
POLICY = "story-loading-orientation-fade-v1"

# Object identities, ownership, MonoScript PPtr, field order, and hierarchy
# were independently decoded from the complete SHA-pinned original prefab.
# view path, GameObject path, CanvasGroup path, view start, CanvasGroup start,
# unchanged label path.  The serialized object table stays byte-identical.
_RADIOS = (
    (297, 27, 221, 39_688, 28_952, 242),  # Horizontal
    (310, 29, 224, 41_952, 29_024, 230),  # Portrait
)
_FADE_OFFSET = 32
_EXPECTED_DIFF_OFFSETS = (39_724, 41_988)


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _check_identity(value: bytes, expected_sha256: str) -> None:
    _need(isinstance(value, bytes), "Story loading prefab must be immutable bytes")
    _need(len(value) == FILE_BYTES, "Story loading prefab size differs from the pinned original")
    _need(_sha(value) == expected_sha256, "Story loading prefab SHA-256 differs from the pinned input")


def _check_references(value: bytes, *, repaired: bool) -> None:
    for _, gameobject, canvas, view_start, canvas_start, label in _RADIOS:
        _need(struct.unpack_from("<iq", value, view_start) == (0, gameobject),
              "Story radio GameObject identity differs")
        _need(struct.unpack_from("<iq", value, view_start + 16) == (1, 4753),
              "Story radio MonoScript identity differs")
        _need(struct.unpack_from("<i", value, view_start + 28)[0] == 0,
              "Story radio serialized name layout differs")
        _need(struct.unpack_from("<iq", value, view_start + _FADE_OFFSET)
              == (0, canvas if repaired else 0), "Story radio fade reference differs")
        _need(struct.unpack_from("<iq", value, view_start + 44) == (0, label),
              "Story radio label reference differs")
        _need(struct.unpack_from("<iq", value, canvas_start) == (0, gameobject),
              "Story radio CanvasGroup belongs to a different GameObject")


def patch_story_loading_prefab(value: bytes) -> tuple[bytes, dict]:
    """Connect the two existing same-GameObject CanvasGroups in one exact asset.

    A different client, an already patched asset, or any changed source byte is
    rejected.  No file, account, cache, SDK flag, or game state is read or written.
    """
    _check_identity(value, INPUT_SHA256)
    _check_references(value, repaired=False)
    result = bytearray(value)
    repairs = []
    for view, gameobject, canvas, view_start, _, label in _RADIOS:
        at = view_start + _FADE_OFFSET
        struct.pack_into("<iq", result, at, 0, canvas)
        repairs.append({"view_path_id": view, "gameobject_path_id": gameobject,
            "fade_PPtr_offset": at, "before_fade_PPtr": [0, 0],
            "after_fade_PPtr": [0, canvas], "same_GameObject_CanvasGroup_path_id": canvas,
            "unchanged_label_PPtr": [0, label]})
    result = bytes(result)
    _check_identity(result, OUTPUT_SHA256)
    _check_references(result, repaired=True)
    differences = tuple(i for i, (before, after) in enumerate(zip(value, result)) if before != after)
    _need(differences == _EXPECTED_DIFF_OFFSETS, "Unexpected bytes changed in story loading prefab")
    return result, {"member": MEMBER, "policy": POLICY, "bytes": FILE_BYTES,
        "input_sha256": INPUT_SHA256, "output_sha256": OUTPUT_SHA256,
        "repaired_references": repairs, "changed_byte_offsets": list(differences),
        "changed_bytes": len(differences), "all_other_bytes_unchanged": True,
        "serialized_metadata_and_object_table_unchanged": True,
        "existing_components_only": True, "runtime_hooks_added": False,
        "runtime_exception_handling_changed": False, "runtime_translation_or_frame_work_added": False,
        "device_playback_verified": False}
