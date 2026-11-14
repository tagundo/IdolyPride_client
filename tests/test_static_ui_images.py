from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from idoly_local import static_ui_images as images

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "client-presentation/images/ko"


class NoArchiveAccess:
    def __getattr__(self, name):
        raise AssertionError("An unrelated locale must not inspect client assets")


@pytest.mark.parametrize("language", ["ja", "en"])
def test_other_locales_keep_all_original_image_data_without_reading_assets(language):
    members, proof = images.android_members(NoArchiveAccess(), language=language)
    assert members == {} and proof["translated_sprites"] == 0
    replacement, appended, proof = images.ios_patches(NoArchiveAccess(), language=language)
    assert replacement == {} and appended == [] and proof["translated_sprites"] == 0


def test_translated_clients_cannot_silently_omit_their_png_inputs():
    for method in (images.android_members, images.ios_patches):
        with pytest.raises(ValueError, match="explicit pinned PNG inputs"):
            method(NoArchiveAccess(), language="ko")


@pytest.mark.parametrize("language", ["", "kr", "KO", None])
def test_unknown_languages_are_rejected_before_asset_access(language):
    with pytest.raises(ValueError, match="Unknown static image language"):
        images.android_members(NoArchiveAccess(), language=language)


def test_all_vendored_translations_match_their_source_and_profile_pins():
    profile = json.loads((ROOT / "client-presentation/images/korean-static-sprites-v1.json").read_text())
    assert profile["policy"] == images.POLICY
    assert profile["source"] == {"repository": images.SOURCE_REPOSITORY,
                                  "revision": images.SOURCE_REVISION,
                                  "data_terms": "NOASSERTION"}
    files = {entry["name"]: entry for entry in profile["inputs"]}
    assert set(files) == {entry["name"] + ".png" for entry in images.PROFILES}
    assert len(files) == 7
    for entry in images.PROFILES:
        raw = images._png(INPUTS, entry)
        assert files[entry["name"] + ".png"] == {
            "name": entry["name"] + ".png", "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def test_modified_and_symlinked_image_sources_are_rejected(tmp_path):
    entry = images.PROFILES[0]
    target = tmp_path / (entry["name"] + ".png")
    raw = bytearray(images._png(INPUTS, entry))
    raw[-1] ^= 1
    target.write_bytes(raw)
    with pytest.raises(ValueError, match="differs from the pinned"):
        images._png(tmp_path, entry)
    target.unlink()
    target.symlink_to(INPUTS / target.name)
    with pytest.raises(ValueError, match="regular translated PNG"):
        images._png(tmp_path, entry)


def test_vertical_padding_retains_pixels_without_scaling():
    pytest.importorskip("UnityPy")
    from PIL import Image
    entry = next(entry for entry in images.PROFILES if entry["name"].endswith("vertical"))
    raw = images._png(INPUTS, entry)
    canvas = images._canvas(raw, entry)
    assert canvas.size == (72, 152)
    with Image.open(INPUTS / (entry["name"] + ".png")) as original:
        assert canvas.crop((7, 7, 66, 145)).tobytes() == original.tobytes()
    assert canvas.getpixel((0, 0)) == canvas.getpixel((71, 151)) == (0, 0, 0, 0)


def test_virtual_reader_does_not_accept_unbounded_or_unrelated_objects():
    for raw, cls, platform in [(b"", 28, 9), (b"a" * (1024 * 1024 + 1), 28, 9),
                               (b"a", 114, 9), (b"a", 213, 99)]:
        with pytest.raises(ValueError, match="Unsupported virtual"):
            images._mini_asset(raw, cls, platform)
