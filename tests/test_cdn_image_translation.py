"""Build-time image data preserves Octo masking and coherent SDK identities."""
import hashlib
import copy
import pytest

from idoly_local.cdn_image_translation import (
    _check_texture_fields, bundle_mask, crypt_header, patch_image_bundle,
)
from idoly_local.octo_manifest import Database
from idoly_local.resource_translation import ResourceTranslation
from idoly_local.resource_translation_build import build_resource_overlay


NAME = "img_story_top_main-new"
SOURCE = {"repository": "https://example.invalid/public-images", "revision": "a" * 40}


def test_original_header_mask_matches_known_public_toolkit_vector_and_leaves_tail_unchanged():
    # Independently recorded prefix from the original 6.1.1 public CDN bundle.
    encoded = bytes.fromhex("9d47a54fbf76ad73d230d53ffb11ab1d")
    assert crypt_header(encoded, NAME).startswith(b"UnityFS\0")
    original = bytes(range(256)) + b"unaltered bundle body"
    modified = crypt_header(original, NAME)
    assert modified[:256] != original[:256]
    assert modified[256:] == original[256:]
    assert crypt_header(modified, NAME) == original
    with pytest.raises(ValueError):
        bundle_mask("../private")


def test_unpinned_image_and_corrupted_original_are_rejected_before_unity_import():
    with pytest.raises(ValueError, match="manifest"):
        patch_image_bundle(b"not the manifest bytes", b"PNG", name=NAME,
            original_md5="0" * 32, png_sha256="0" * 64)
    original = b"original"
    with pytest.raises(ValueError, match="PNG"):
        patch_image_bundle(original, b"wrong image", name=NAME,
            original_md5=hashlib.md5(original).hexdigest(), png_sha256="0" * 64)


def test_larger_translation_keeps_sampler_gpu_format_and_stream_identity():
    before = {"m_Width": 512, "m_Height": 128, "m_CompleteImageSize": 30272,
        "m_StreamData": {"path": "archive:/image.resS", "offset": 0, "size": 30272},
        "m_IsReadable": False, "m_Name": "img_chr_plate_smr", "m_TextureFormat": 50,
        "m_MipCount": 1, "m_ColorSpace": 1,
        "m_TextureSettings": {"m_FilterMode": 1, "m_WrapU": 1, "m_WrapV": 1}}
    translated = copy.deepcopy(before)
    translated.update(m_Height=256, m_CompleteImageSize=59168)
    translated["m_StreamData"]["size"] = 59168
    _check_texture_fields(before, translated)
    for key, replacement in (("m_TextureFormat", 48), ("m_Name", "other"),
            ("m_MipCount", 2), ("m_ColorSpace", 0),
            ("m_TextureSettings", {"m_FilterMode": 0, "m_WrapU": 0, "m_WrapV": 0})):
        invalid = copy.deepcopy(translated); invalid[key] = replacement
        with pytest.raises(ValueError, match="unrelated"):
            _check_texture_fields(before, invalid)
    invalid = copy.deepcopy(translated); invalid["m_StreamData"]["offset"] = 128
    with pytest.raises(ValueError, match="stream identity"):
        _check_texture_fields(before, invalid)


def original_manifest():
    database = Database(revision=1087, urlFormat="original")
    database.assetBundleList.add(id=1, name=NAME, size=3, md5=hashlib.md5(b"old").hexdigest(),
        objectName="old_image", generation=1, uploadVersionId=202050, state=3,
        priority=7, tagid=[2], dependencie=[9])
    database.assetBundleList.add(id=2, name="stage_model", size=3, md5="a" * 32,
        objectName="unchanged", generation=1, uploadVersionId=202050, state=3)
    database.resourceList.add(id=1, name="adv_test.txt", size=3, md5="a" * 32,
        objectName="old_story", generation=1, uploadVersionId=202050, state=3)
    return database.SerializeToString()


def image_result():
    raw = b"prebuilt independently checked UnityFS image"
    return raw, {"original_sha256": hashlib.sha256(b"old").hexdigest(),
        "output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw),
        "png": {"sha256": "a" * 64, "bytes": 123, "width": 1024, "height": 256},
        "texture": {"name": NAME, "width": 1024, "height": 256, "format_before": 50,
            "format_after": 50, "encoding": "ASTC6x6-medium", "quality": 60, "threads": 1,
            "source_RGBA_sha256": "b" * 64, "decoded_RGBA_sha256": "c" * 64,
            "readback_pixel_exact": False}}


def test_merged_story_and_image_builder_does_not_reuse_original_sdk_hashes(tmp_path):
    original = original_manifest()
    report = build_resource_overlay(original, tmp_path, tmp_path / "output",
        language="ko", revision=1088, source=SOURCE,
        read_script=lambda _name: "한국어 대사".encode(),
        image_names=[NAME], image_source=SOURCE, read_image=lambda _name: image_result())
    assert report["schema"] == 2
    assert report["coverage"]["translated"] == 1
    assert report["image_coverage"] == {"candidates": 1, "translated": 1, "missing": 0, "unchanged_original": 0}
    layer = ResourceTranslation(tmp_path / "output", original, language="ko")
    after, before = Database.FromString(layer.manifest), Database.FromString(original)
    old, new = before.assetBundleList[0], after.assetBundleList[0]
    assert new.name == old.name and new.id == old.id
    assert new.tagid == old.tagid and new.dependencie == old.dependencie and new.priority == old.priority
    assert (new.objectName, new.generation, new.md5, new.size) != (old.objectName, old.generation, old.md5, old.size)
    assert new.md5 == hashlib.md5(image_result()[0]).hexdigest()
    assert after.assetBundleList[1] == before.assetBundleList[1]
    layer.close()


@pytest.mark.parametrize("mutation", [
    {"image_names": [NAME, NAME]}, {"image_names": ["img_absent"]},
    {"image_source": {"repository": "", "revision": "a" * 40}},
    {"read_image": None},
    {"read_image": lambda _name: (b"changed", image_result()[1])},
])
def test_image_builder_rejects_unbound_names_and_content(tmp_path, mutation):
    args = {"language": "ko", "revision": 1088, "source": SOURCE,
        "read_script": lambda _name: None, "image_names": [NAME], "image_source": SOURCE,
        "read_image": lambda _name: image_result()}
    args.update(mutation)
    with pytest.raises(ValueError):
        build_resource_overlay(original_manifest(), tmp_path, tmp_path / "output", **args)
