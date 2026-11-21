from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest

from idoly_local import static_ui_images, static_ui_textures as textures

ROOT = Path(__file__).resolve().parents[1]


class NoArchiveAccess:
    def __getattr__(self, name):
        raise AssertionError("Other locales must not inspect source assets")


@pytest.mark.parametrize("language", ["ja", "en"])
def test_unrelated_locales_do_not_open_assets(language):
    for method in (textures.android_members, textures.ios_patches):
        output, proof = method(NoArchiveAccess(), language=language)
        assert output == {} and proof["translated_textures"] == 0
        assert not proof["runtime_image_hooks"]


def test_direct_texture_translation_requires_explicit_inputs():
    for method in (textures.android_members, textures.ios_patches):
        with pytest.raises(ValueError, match="explicit pinned PNG inputs"):
            method(NoArchiveAccess(), language="ko")


def test_all_fourteen_original_texture_ids_and_gpu_formats_are_pinned():
    raw = (ROOT / "client-presentation/images/korean-static-textures-v1.json").read_bytes()
    profile = json.loads(raw)
    assert profile["policy"] == textures.POLICY and profile["source"] == textures.SOURCE
    assert len(profile["inputs"]) == len(textures.PROFILES) == 14
    assert len({row["android"]["member"] for row in textures.PROFILES}) == 14
    assert {row["ios"]["path_id"] for row in textures.PROFILES} == {
        124, 133, 156, 157, 180, 181, 187, 211, 217, 219, 229, 235, 254, 281}
    assert all(row[platform]["format"] == 50 and row[platform]["mips"] == 1
               for row in textures.PROFILES for platform in ("android", "ios"))
    large = next(row for row in textures.PROFILES if row["name"] == "profile_card_default")
    assert large["png_size"] == [2048, 1024]
    assert large["ios"]["stream_data"]["size"] == 935712 < 2048 * 1024 * 4


@pytest.mark.parametrize("platform", ("android", "ios"))
@pytest.mark.parametrize("corruption", ("length", "digest"))
def test_direct_texture_fingerprint_rejects_corrupted_input_before_decode(monkeypatch, platform, corruption):
    entry = textures.PROFILES[0]
    original = b"invalid source" if corruption == "length" else b"\0" * entry[platform]["bytes"]
    real_import = builtins.__import__

    def deny_optional_decode_imports(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"attrs", "PIL", "UnityPy"}:
            raise AssertionError("Corrupted pinned bytes must be rejected before optional imports")
        return real_import(name, *args, **kwargs)

    def deny_decode(*args, **kwargs):
        raise AssertionError("Corrupted pinned bytes must not reach the Unity decoder")

    monkeypatch.setattr(builtins, "__import__", deny_optional_decode_imports)
    monkeypatch.setattr(textures.images, "_mini_asset", deny_decode)
    with pytest.raises(ValueError, match="fingerprint differs"):
        textures._patch(original, entry, platform, {"image_dir": ROOT, "encoded": {}})


def test_exact_translated_png_pins_are_shared_by_both_platforms():
    directory = Path("/workspace/ipr-translation-data-ko/local-files/resource/img")
    if not directory.is_dir():
        pytest.skip("Pinned public translation checkout is not cached")
    for row in textures.PROFILES:
        raw = static_ui_images._png(directory, row)
        assert hashlib.sha256(raw).hexdigest() == row["png_sha256"]
