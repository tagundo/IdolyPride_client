"""Actual original prefab preservation and fail-closed build-helper checks."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from zipfile import ZipFile

import pytest

from idoly_local import story_loading_prefab as prefab


@pytest.fixture(scope="module")
def original() -> bytes:
    apk = Path("/workspace/shared/artifacts/client-6.1.1/game.qualiarts.idolypride.apk")
    if not apk.is_file():
        pytest.skip("Pinned original Android APK is required for real prefab checks")
    with ZipFile(apk) as archive:
        return archive.read(prefab.MEMBER)


def test_actual_prefab_connects_same_gameobject_canvasgroups_and_preserves_every_other_byte(original):
    before_sha = hashlib.sha256(original).hexdigest()
    changed, proof = prefab.patch_story_loading_prefab(original)
    assert len(changed) == 49_540
    assert before_sha == prefab.INPUT_SHA256
    assert hashlib.sha256(original).hexdigest() == before_sha
    assert hashlib.sha256(changed).hexdigest() == prefab.OUTPUT_SHA256
    assert [(i, a, b) for i, (a, b) in enumerate(zip(original, changed)) if a != b] == [
        (39_724, 0, 221), (41_988, 0, 224)]
    for view_start, canvas_start, gameobject, canvas, label in [
            (39_688, 28_952, 27, 221, 242), (41_952, 29_024, 29, 224, 230)]:
        assert struct.unpack_from("<iq", changed, view_start) == (0, gameobject)
        assert struct.unpack_from("<iq", changed, canvas_start) == (0, gameobject)
        assert struct.unpack_from("<iq", original, view_start + 32) == (0, 0)
        assert struct.unpack_from("<iq", changed, view_start + 32) == (0, canvas)
        assert struct.unpack_from("<iq", changed, view_start + 44) == (0, label)
    assert proof["changed_bytes"] == 2
    assert proof["all_other_bytes_unchanged"]
    assert proof["existing_components_only"]
    assert not proof["runtime_hooks_added"]
    assert not proof["runtime_exception_handling_changed"]
    assert not proof["device_playback_verified"]


@pytest.mark.parametrize("value", [None, "", bytearray(49_540), memoryview(b""), 49_540])
def test_rejects_non_bytes(value):
    with pytest.raises(ValueError, match="immutable bytes"):
        prefab.patch_story_loading_prefab(value)


@pytest.mark.parametrize("value", [b"", bytes(49_539), bytes(49_541)])
def test_rejects_wrong_length(value):
    with pytest.raises(ValueError, match="size differs"):
        prefab.patch_story_loading_prefab(value)


@pytest.mark.parametrize("offset", [0, 28_956, 39_720, 39_724, 41_988, 49_539])
def test_rejects_any_changed_source_including_metadata_ownership_and_references(original, offset):
    changed = bytearray(original)
    changed[offset] ^= 1
    with pytest.raises(ValueError, match="SHA-256 differs"):
        prefab.patch_story_loading_prefab(bytes(changed))


def test_rejects_double_application(original):
    patched, _ = prefab.patch_story_loading_prefab(original)
    with pytest.raises(ValueError, match="SHA-256 differs"):
        prefab.patch_story_loading_prefab(patched)
