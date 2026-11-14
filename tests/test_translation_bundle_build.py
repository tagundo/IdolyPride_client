import hashlib
import json
from zipfile import ZipFile

import pytest

from idoly_local.translation_bundle_build import build_translation_bundle, build_translation_bundle_overlay


def prepare(root):
    for language in ("ko", "en"):
        directory = root / language / "android"; directory.mkdir(parents=True)
        for name in ("manifest.pb", "manifest.json", "objects.zip"):
            if name == "manifest.json":
                (directory / name).write_text(json.dumps({"schema": 1, "language": language,
                    "coverage": {"adv_resources": 1, "translated": 1, "missing": 0, "unchanged_original": 0},
                    "source": {"repository": "https://example.invalid/translations", "revision": "a" * 40,
                               "data_terms": "NOASSERTION"}}))
            else:
                (directory / name).write_bytes((language + name).encode())


def test_platform_bundle_has_exact_pinned_members_and_is_reproducible(tmp_path):
    prepared = tmp_path / "input"; prepare(prepared)
    one = build_translation_bundle(prepared, tmp_path / "one.zip", platform="android", version="test")
    two = build_translation_bundle(prepared, tmp_path / "two.zip", platform="android", version="test")
    assert one == two and (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    assert one["sha256"] == hashlib.sha256((tmp_path / "one.zip").read_bytes()).hexdigest()
    with ZipFile(tmp_path / "one.zip") as archive:
        assert len(archive.namelist()) == 7
        assert not any("/ios/" in name for name in archive.namelist())
        for name, identity in one["index"]["files"].items():
            raw = archive.read("translations/" + name)
            assert len(raw) == identity["bytes"] and hashlib.sha256(raw).hexdigest() == identity["sha256"]


def test_failed_package_retires_only_its_incomplete_output(tmp_path):
    prepared = tmp_path / "input"; prepare(prepared)
    with pytest.raises(ValueError, match="bound"):
        build_translation_bundle(prepared, tmp_path / "too-big.zip", platform="android", version="test", max_bytes=100)
    assert not (tmp_path / "too-big.zip").exists() and not (tmp_path / "too-big.zip.part").exists()
    assert (prepared / "ko/android/objects.zip").is_file()


def test_prepared_image_manifest_is_packaged_without_loading_or_reencoding_pixels(tmp_path):
    prepared = tmp_path / "input"; prepare(prepared)
    path = prepared / "ko/android/manifest.json"
    report = json.loads(path.read_bytes())
    report.update(schema=2,
        image_source={"repository": "https://example.invalid/images", "revision": "b" * 40},
        image_coverage={"candidates": 2, "translated": 1, "missing": 1, "unchanged_original": 0},
        changed_images=[{"name": "img_story_top_main-new"}])
    path.write_text(json.dumps(report))
    binary = prepared / "ko/android/objects.zip"
    expected = binary.read_bytes()
    result = build_translation_bundle(prepared, tmp_path / "images.zip", platform="android", version="images")
    assert result["image_coverage"]["ko"]["translated"] == 1
    assert result["image_sources"]["ko"]["revision"] == "b" * 40
    assert result["coverage"]["ko"]["adv_resources"] == 1
    with ZipFile(tmp_path / "images.zip") as archive:
        assert archive.read("translations/ko/android/objects.zip") == expected


def prepare_image_overlay(root):
    root.mkdir()
    report = {"schema": 2, "language": "ko",
        "source": {"repository": "https://example.invalid/adv", "revision": "a" * 40},
        "coverage": {"adv_resources": 1, "translated": 1, "missing": 0, "unchanged_original": 0},
        "image_source": {"repository": "https://example.invalid/images", "revision": "b" * 40},
        "image_coverage": {"candidates": 1, "translated": 1, "missing": 0, "unchanged_original": 0},
        "changed_images": [{"name": "img_story_top_main-new"}]}
    for leaf, raw in (("manifest.json", json.dumps(report).encode()),
                      ("manifest.pb", b"new coherent KO manifest"),
                      ("objects.zip", b"new precomputed KO ADV and image objects")):
        (root / leaf).write_bytes(raw)


def test_overlay_streams_old_english_and_text_bytes_without_extraction(tmp_path, monkeypatch):
    prepared = tmp_path / "input"; prepare(prepared)
    text = tmp_path / "text"
    for language in ("ko", "en"):
        directory = text / language; directory.mkdir(parents=True)
        for leaf in ("text.json", "text-manifest.json"):
            (directory / leaf).write_bytes((language + ":existing:" + leaf).encode())
    source = tmp_path / "source.zip"
    original = build_translation_bundle(prepared, source, platform="android", version="old", text_root=text)
    before = source.read_bytes()
    overlay = tmp_path / "overlay"; prepare_image_overlay(overlay)
    monkeypatch.setattr(ZipFile, "read", lambda *_args, **_kwargs: pytest.fail("Whole ZIP member read forbidden"))
    one = build_translation_bundle_overlay(source, overlay, tmp_path / "new.zip", platform="android", version="new",
        expected_source_sha256=original["sha256"], expected_source_bytes=original["bytes"])
    two = build_translation_bundle_overlay(source, overlay, tmp_path / "repeat.zip", platform="android", version="new",
        expected_source_sha256=original["sha256"], expected_source_bytes=original["bytes"])
    assert one == two and (tmp_path / "new.zip").read_bytes() == (tmp_path / "repeat.zip").read_bytes()
    assert source.read_bytes() == before
    assert len(one["replaced_files"]) == 3 and len(one["preserved_files"]) == 7
    assert one["image_coverage"]["ko"]["translated"] == 1
    assert one["source_bundle"]["sha256"] == original["sha256"]
    with ZipFile(source) as old, ZipFile(tmp_path / "new.zip") as new:
        for name, identity in one["preserved_files"].items():
            with old.open("translations/" + name) as a, new.open("translations/" + name) as b:
                raw = b.read(64 * 1024)
                assert raw == a.read(64 * 1024)
                assert hashlib.sha256(raw).hexdigest() == identity["sha256"]


@pytest.mark.parametrize("kind", ("source_hash", "source_size", "output_bound", "overlay_symlink"))
def test_overlay_failure_preserves_old_archive_and_retires_only_its_partial(tmp_path, kind):
    prepared = tmp_path / "input"; prepare(prepared)
    source = tmp_path / "source.zip"
    original = build_translation_bundle(prepared, source, platform="android", version="old")
    before = source.read_bytes()
    overlay = tmp_path / "overlay"; prepare_image_overlay(overlay)
    args = {"expected_source_sha256": original["sha256"], "expected_source_bytes": original["bytes"]}
    if kind == "source_hash": args["expected_source_sha256"] = "0" * 64
    elif kind == "source_size": args["expected_source_bytes"] += 1
    elif kind == "output_bound": args["max_bytes"] = 16
    else:
        target = overlay / "objects.zip"; raw = target.read_bytes(); target.unlink()
        outside = tmp_path / "outside.zip"; outside.write_bytes(raw); target.symlink_to(outside)
    with pytest.raises(ValueError):
        build_translation_bundle_overlay(source, overlay, tmp_path / "bad.zip", platform="android", version="new", **args)
    assert not (tmp_path / "bad.zip").exists() and not (tmp_path / "bad.zip.part").exists()
    assert source.read_bytes() == before
