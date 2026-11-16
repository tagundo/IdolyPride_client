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
    assert profile["policy"] == images.LEGACY_POLICY
    assert profile["source"] == {"repository": images.SOURCE_REPOSITORY,
                                  "revision": images.SOURCE_REVISION,
                                  "data_terms": "NOASSERTION"}
    files = {entry["name"]: entry for entry in profile["inputs"]}
    assert set(files) == {entry["name"] + ".png" for entry in images.LEGACY_PROFILES}
    assert len(files) == 7
    for entry in images.LEGACY_PROFILES:
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


def test_virtual_reader_does_not_accept_unbounded_or_unrelated_objects(monkeypatch):
    monkeypatch.setattr(images, "MAX_TEXTURE_BYTES", 32)
    for raw, cls, platform in [(b"", 28, 9), (b"a" * 33, 28, 9),
                               (b"a" * (images.MAX_SPRITE_BYTES + 1), 213, 9),
                               (b"a", 114, 9), (b"a", 213, 99)]:
        with pytest.raises(ValueError, match="Unsupported virtual"):
            images._mini_asset(raw, cls, platform)


def test_static_texture_discards_cpu_copy_and_preserves_exact_rgba_pixels():
    pytest.importorskip("UnityPy")
    from zipfile import ZipFile
    stock = ROOT / 'data/clients/Game-r2-pinned.apk'
    if not stock.is_file():
        pytest.skip('Pinned original font-schema fixture is not cached')
    entry = images.PROFILES[0]
    with ZipFile(stock) as archive:
        template = images._texture_template(archive, 'android')
    canvas = images._canvas(images._png(INPUTS, entry), entry)
    raw = images._texture(template, canvas, entry['name'], 13)
    _, reader = images._mini_asset(raw, 28, 13)
    texture = reader.read()
    assert not texture.m_IsReadable and not texture.m_StreamingMipmaps
    assert texture.m_MipCount == 1 and texture.m_CompleteImageSize == 152 * 72 * 4
    assert texture.image.tobytes() == canvas.tobytes()


def test_all_pinned_bundled_translations_cover_both_platforms_without_dropping_duplicate_names():
    assert len(images.PROFILES) == 138
    android = [row["android"] for row in images.PROFILES if row["android"] is not None]
    ios = [target for row in images.PROFILES for target in row["ios"]]
    assert len(android) == len({row["member"] for row in android}) == 134
    assert len(ios) == len({row["path_id"] for row in ios}) == 139
    ka = next(row for row in images.PROFILES if row["name"] == "Ka")
    assert {row["path_id"] for row in ka["ios"]} == {550, 675}
    assert {row["name"] for row in images.PROFILES if row["android"] is None} == {
        "Kai", "Nou", "Sai", "love_loading_logo"}


def test_new_wider_translation_uses_png_rect_without_resampling_or_clipping():
    pytest.importorskip("UnityPy")
    from PIL import Image
    directory = Path("/workspace/ipr-translation-data-ko/local-files/resource/img")
    if not directory.is_dir():
        pytest.skip("Pinned public image translation checkout is not cached")
    entry = next(row for row in images.PROFILES if row["name"] == "love_label_koi")
    assert entry["png_size"] == [63, 32]
    assert entry["android"]["source_layout"]["sprite_size"] == [32, 32]
    canvas = images._canvas(images._png(directory, entry), entry)
    with Image.open(directory / (entry["name"] + ".png")) as source:
        assert canvas.size == source.size == (63, 32)
        assert canvas.tobytes() == source.convert("RGBA").tobytes()


def test_pinned_rgb_image_expands_to_rgba_without_changing_its_rgb_samples(tmp_path):
    pytest.importorskip("UnityPy")
    from PIL import Image
    source = Image.new("RGB", (3, 2), (17, 91, 203))
    path = tmp_path / "rgb.png"
    source.save(path)
    raw = path.read_bytes()
    entry = {"name": "rgb", "png_bytes": len(raw), "png_sha256": hashlib.sha256(raw).hexdigest(),
             "png_color_type": 2, "png_size": [3, 2], "sprite_size": [3, 2], "padding_offset": [0, 0]}
    canvas = images._canvas(images._png(tmp_path, entry), entry)
    assert canvas.mode == "RGBA" and canvas.size == source.size
    assert canvas.tobytes() == source.convert("RGBA").tobytes()


@pytest.mark.parametrize("name,size,content,offset", [
    ("love_btn_present", (194,40), (72,40), (61,0)),
    ("love_btn_achievement", (280,40), (250,40), (15,0)),
    ("love_btn_playing", (240,48), (96,48), (72,0)),
    ("love_btn_mission", (80,40), (78,37), (1,1)),
    ("love_btn_status", (192,40), (185,37), (3,1)),
    ("love_btn_setting", (80,40), (75,40), (2,0)),
    ("love_button_start", (192,48), (184,48), (4,0)),
    ("love_btn_fin", (159,40), (147,40), (6,0)),
    ("love_btn_max", (72,28), (72,27), (0,0)),
])
def test_fixed_love_button_text_keeps_original_ui_geometry(name, size, content, offset):
    row = next(row for row in images.PROFILES if row["name"] == name)
    assert row["layout_policy"] == row["render_key_policy"] == images.TEXT_LAYOUT_POLICY
    assert tuple(row["sprite_size"]) == size
    assert tuple(row["content_size"]) == content
    assert tuple(row["padding_offset"]) == offset
    for target in ([row["android"]] if row["android"] else []) + row["ios"]:
        assert tuple(target["source_layout"]["sprite_size"]) == size


@pytest.mark.parametrize("name", ("love_btn_present", "love_btn_achievement", "love_btn_playing"))
def test_short_korean_words_are_padded_not_stretched_or_redrawn(name):
    pytest.importorskip("UnityPy")
    from io import BytesIO
    from PIL import Image
    row = next(row for row in images.PROFILES if row["name"] == name)
    # A nonuniform pixel canary exposes both anisotropic scaling and cropping.
    source = Image.new("RGBA", row["png_size"], (17, 51, 119, 255))
    source.putpixel((0, 0), (217, 61, 7, 123))
    stream = BytesIO(); source.save(stream, format="PNG")
    canvas = images._canvas(stream.getvalue(), row)
    x, y = row["padding_offset"]
    assert canvas.size == tuple(row["sprite_size"])
    assert canvas.crop((x, y, x + source.width, y + source.height)).tobytes() == source.tobytes()
    assert canvas.getpixel((0, 0)) == (0, 0, 0, 0)


def test_fixed_love_layout_does_not_accept_a_different_original_or_png_rectangle():
    from copy import deepcopy
    raw = json.loads((ROOT / "client-presentation/images/korean-static-sprites-v2.json").read_text())
    source = next(row for row in raw["inputs"] if row["name"] == "love_btn_present")
    for damage in ("png", "original"):
        changed = deepcopy(source)
        if damage == "png": changed["png_size"][0] += 1
        else: changed["ios"][0]["source_layout"]["sprite_size"][0] += 1
        with pytest.raises(ValueError, match="audited rectangle"):
            images._text_layout(changed)
    # Separate animated logo consumers require their own audited layout fix;
    # do not shrink two Korean letters into the former single-kanji slot.
    logo = next(row for row in images.PROFILES if row["name"] == "love_label_koi")
    assert logo["sprite_size"] == logo["png_size"] == [63, 32]
    assert logo["layout_policy"] == "localify-png-rect"
