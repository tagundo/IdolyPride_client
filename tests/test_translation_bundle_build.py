import hashlib
import json
from zipfile import ZipFile

import pytest

from idoly_local.translation_bundle_build import build_translation_bundle


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
