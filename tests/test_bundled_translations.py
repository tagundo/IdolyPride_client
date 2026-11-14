"""Prepared-language installation is atomic, bounded and separate from core data."""
import hashlib
import json
from pathlib import Path
import stat
from zipfile import ZipFile, ZipInfo

import pytest

from idoly_local import bundled_translations as bundle


def make_bundle(tmp_path, *, version="v1", platform="android", languages=("ko", "en"),
                change=None, extra=None, name="translations.zip"):
    files = {}
    for language in languages:
        for leaf in ("manifest.pb", "manifest.json", "objects.zip"):
            raw = f"{version}:{language}:{leaf}".encode()
            if leaf == "manifest.json":
                raw = json.dumps({"schema": 1, "language": language,
                    "source": {"repository": "https://example.test/translation", "revision": "a" * 40,
                               "terms": "NOASSERTION"},
                    "coverage": {"adv_resources": 3, "translated": 1, "missing": 1, "unchanged_original": 1}}).encode()
            files[f"{language}/{platform}/{leaf}"] = raw
    index = {"schema": 1, "version": version, "platform": platform, "files": {
        name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in files.items()}}
    if change:
        change(index, files)
    entries = {"translation-package.json": json.dumps(index).encode(),
               **{"translations/" + name: raw for name, raw in files.items()}}
    entries.update(extra or {})
    path = tmp_path / name
    with ZipFile(path, "w") as archive:
        for filename, raw in entries.items():
            archive.writestr(filename, raw)
    return path, {"expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "expected_bytes": path.stat().st_size, "platform": platform}


def install(source, root, pins):
    return bundle.install_translation_bundle(source, root, **pins)


def test_first_repeat_update_and_platform_coexistence_preserve_originals(tmp_path):
    root = tmp_path / "Downloads/IdolyPride"
    core = root / "octo-cache/ja.bin"
    core.parent.mkdir(parents=True)
    core.write_bytes(b"original Japanese cache")
    legacy = root / "translations/ko/android/owner.bin"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing manually prepared data")
    source, pins = make_bundle(tmp_path)
    verified = bundle.validate_translation_bundle(source, **pins)
    assert verified["files"] == 6 and verified["platform"] == "android"
    first = install(source, root, pins)
    selected = bundle.resolve_translation_root(root, platform="android")
    assert first["state"] == "installed" and first["files"] == 6
    assert selected.name == pins["expected_sha256"]
    payload = selected / "ko/android/objects.zip"
    inode = payload.stat().st_ino
    assert payload.read_bytes() == b"v1:ko:objects.zip"
    repeat = install(source, root, pins)
    assert repeat["state"] == "unchanged" and payload.stat().st_ino == inode
    ios, ios_pins = make_bundle(tmp_path, platform="ios", name="ios.zip")
    install(ios, root, ios_pins)
    assert bundle.resolve_translation_root(root, platform="android") == selected
    assert bundle.resolve_translation_root(root, platform="ios").name == ios_pins["expected_sha256"]
    assert core.read_bytes() == b"original Japanese cache" and legacy.read_bytes() == b"existing manually prepared data"
    assert not list(root.rglob(".install-*")) and not list(root.rglob(".current-*"))


def test_pointer_changes_only_after_complete_version_is_published(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    first, pins = make_bundle(tmp_path)
    install(first, root, pins)
    old = bundle.resolve_translation_root(root, platform="android")
    second, new_pins = make_bundle(tmp_path, version="v2", name="next.zip")
    original_replace = bundle.os.replace
    observations = []

    def publish(source, destination):
        if Path(destination).name == "current-android.json":
            assert bundle.resolve_translation_root(root, platform="android") == old
            new = root / "translations/.versions" / new_pins["expected_sha256"]
            assert (new / "version.json").is_file()
            assert (new / "en/android/objects.zip").read_bytes() == b"v2:en:objects.zip"
            observations.append(True)
        return original_replace(source, destination)

    monkeypatch.setattr(bundle.os, "replace", publish)
    install(second, root, new_pins)
    assert observations == [True]
    current = bundle.resolve_translation_root(root, platform="android")
    assert current != old and (old / "ko/android/objects.zip").read_bytes() == b"v1:ko:objects.zip"


def test_failed_new_package_keeps_previous_selection_and_cleans_staging(tmp_path):
    root = tmp_path / "cache"
    first, pins = make_bundle(tmp_path)
    install(first, root, pins)
    before = (root / "translations/current-android.json").read_bytes()

    def corrupt(_index, files):
        files["en/android/objects.zip"] = b"same declared index, corrupt contents"

    broken, broken_pins = make_bundle(tmp_path, version="broken", change=corrupt, name="broken.zip")
    with pytest.raises(ValueError):
        install(broken, root, broken_pins)
    assert (root / "translations/current-android.json").read_bytes() == before
    assert bundle.resolve_translation_root(root, platform="android").name == pins["expected_sha256"]
    assert not list(root.rglob(".install-*")) and not list(root.rglob(".current-*"))


def test_failed_atomic_selection_retains_previous_complete_version(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    first, pins = make_bundle(tmp_path)
    install(first, root, pins)
    before = (root / "translations/current-android.json").read_bytes()
    second, new_pins = make_bundle(tmp_path, version="v2", name="next.zip")
    def fail(_source, _destination):
        raise OSError("simulated pointer publication failure")
    monkeypatch.setattr(bundle.os, "replace", fail)
    with pytest.raises(OSError):
        install(second, root, new_pins)
    assert (root / "translations/current-android.json").read_bytes() == before
    assert bundle.resolve_translation_root(root, platform="android").name == pins["expected_sha256"]
    assert not list(root.rglob(".current-*"))


def test_log_observer_cannot_revert_successful_publication(tmp_path):
    source, pins = make_bundle(tmp_path)
    def fail(_message):
        raise OSError("simulated log sink failure")
    assert bundle.install_translation_bundle(source, tmp_path / "cache", log=fail, **pins)["state"] == "installed"
    assert bundle.resolve_translation_root(tmp_path / "cache", platform="android").name == pins["expected_sha256"]


def test_semantic_preparation_failure_never_replaces_previous_pointer(tmp_path):
    root = tmp_path / "cache"
    first, pins = make_bundle(tmp_path)
    install(first, root, pins)
    before = (root / "translations/current-android.json").read_bytes()
    second, new_pins = make_bundle(tmp_path, version="incompatible", name="incompatible.zip")
    observed = []
    def reject(directory):
        assert (directory / "ko/android/objects.zip").is_file()
        assert bundle.resolve_translation_root(root, platform="android").name == pins["expected_sha256"]
        observed.append(directory)
        raise ValueError("language resource base manifest differs")
    with pytest.raises(ValueError, match="base manifest"):
        bundle.install_translation_bundle(second, root, validate_prepared=reject, **new_pins)
    assert len(observed) == 1
    assert (root / "translations/current-android.json").read_bytes() == before
    assert not list(root.rglob(".current-*"))


@pytest.mark.parametrize("field,value", (("translated", True), ("missing", -1), ("adv_resources", 99)))
def test_producer_rejects_inconsistent_or_untyped_coverage(tmp_path, field, value):
    def change(index, files):
        name = "ko/android/manifest.json"
        report = json.loads(files[name])
        report["coverage"][field] = value
        files[name] = json.dumps(report).encode()
        index["files"][name] = {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}
    source, pins = make_bundle(tmp_path, change=change)
    with pytest.raises(ValueError, match="coverage/source"):
        bundle.validate_translation_bundle(source, **pins)


def with_image_report(index, files, mutation=None):
    name = "ko/android/manifest.json"
    report = json.loads(files[name])
    report.update(schema=2,
        image_source={"repository": "https://example.test/images", "revision": "b" * 40},
        image_coverage={"candidates": 3, "translated": 1, "missing": 1, "unchanged_original": 1},
        changed_images=[{"name": "img_story_top_main-new"}])
    if mutation is not None:
        mutation(report)
    files[name] = json.dumps(report).encode()
    index["files"][name] = {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}


def test_schema_two_image_counts_and_provenance_stay_separate_from_story_coverage(tmp_path):
    source, pins = make_bundle(tmp_path, change=with_image_report)
    verified = bundle.validate_translation_bundle(source, **pins)
    assert verified["coverage"]["ko"] == {
        "adv_resources": 3, "translated": 1, "missing": 1, "unchanged_original": 1}
    assert verified["image_coverage"] == {"ko": {
        "candidates": 3, "translated": 1, "missing": 1, "unchanged_original": 1}}
    assert verified["image_sources"]["ko"]["revision"] == "b" * 40
    assert verified["sources"]["ko"]["revision"] == "a" * 40
    assert "en" not in verified["image_coverage"]  # Schema-one language remains valid.


@pytest.mark.parametrize("mutation", [
    lambda report: report["image_coverage"].update(translated=True),
    lambda report: report["image_coverage"].update(missing=-1),
    lambda report: report["image_coverage"].update(candidates=99),
    lambda report: report["image_coverage"].update(unapproved=0),
    lambda report: report.update(image_coverage=None),
    lambda report: report.update(changed_images={}),
    lambda report: report.update(changed_images=[]),
    lambda report: report.update(image_source={"repository": "", "revision": "b" * 40}),
    lambda report: report["image_source"].update(revision="invalid"),
])
def test_schema_two_rejects_incoherent_image_report_with_valid_outer_hash(tmp_path, mutation):
    source, pins = make_bundle(tmp_path,
        change=lambda index, files: with_image_report(index, files, mutation))
    with pytest.raises(ValueError, match="image coverage/source"):
        bundle.validate_translation_bundle(source, **pins)


@pytest.mark.parametrize("bad", ("../state.db", "/ko/android/manifest.pb", "ko//android/manifest.pb",
    "ko/android/../state.db", "ja/android/manifest.pb", "ko/ios/manifest.pb", "ko/android/private.bin"))
def test_index_paths_are_checked_before_any_version_is_visible(tmp_path, bad):
    def replace(index, files):
        record = index["files"].pop("ko/android/manifest.pb")
        raw = files.pop("ko/android/manifest.pb")
        index["files"][bad], files[bad] = record, raw

    source, pins = make_bundle(tmp_path, change=replace)
    root = tmp_path / "cache"
    with pytest.raises(ValueError):
        install(source, root, pins)
    assert not (root / "translations/current-android.json").exists()
    assert not (tmp_path / "state.db").exists()


@pytest.mark.parametrize("kind", ("extra", "incomplete", "platform", "symlink"))
def test_unindexed_incomplete_wrong_platform_and_link_members_are_rejected(tmp_path, kind):
    if kind == "extra":
        source, pins = make_bundle(tmp_path, extra={"state.db": b"never install"})
    else:
        def change(index, files):
            if kind == "incomplete":
                del index["files"]["ko/android/objects.zip"]
                del files["ko/android/objects.zip"]
            elif kind == "platform":
                index["platform"] = "ios"
        source, pins = make_bundle(tmp_path, change=change)
        if kind == "symlink":
            info = ZipInfo("translations/ko/android/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with ZipFile(source, "a") as archive:
                archive.writestr(info, "../../state.db")
            pins["expected_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            pins["expected_bytes"] = source.stat().st_size
    with pytest.raises(ValueError):
        install(source, tmp_path / "cache", pins)


@pytest.mark.parametrize("field,value", (("expected_sha256", "0" * 64), ("expected_bytes", 1),
    ("expected_bytes", True), ("platform", "ja")))
def test_explicit_outer_identity_is_required(tmp_path, field, value):
    source, pins = make_bundle(tmp_path)
    pins[field] = value
    with pytest.raises(ValueError):
        install(source, tmp_path / "cache", pins)


def test_legacy_direct_layout_is_used_only_without_a_platform_pointer(tmp_path):
    root = tmp_path / "cache"
    assert bundle.resolve_translation_root(root, platform="android") == root / "translations"
    source, pins = make_bundle(tmp_path)
    install(source, root, pins)
    pointer = root / "translations/current-android.json"
    value = json.loads(pointer.read_text())
    value["archive_sha256"] = "../escape"
    pointer.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        bundle.resolve_translation_root(root, platform="android")
    # The other platform has no pointer and keeps its legacy namespace.
    assert bundle.resolve_translation_root(root, platform="ios") == root / "translations"


def test_symlink_namespace_and_metadata_never_follow_outside_paths(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "cache"
    root.mkdir()
    (root / "translations").symlink_to(outside, target_is_directory=True)
    source, pins = make_bundle(tmp_path)
    with pytest.raises(ValueError):
        install(source, root, pins)
    assert not list(outside.iterdir())
    (root / "translations").unlink()
    install(source, root, pins)
    pointer = root / "translations/current-android.json"
    pointer.unlink()
    pointer.symlink_to(outside / "missing")
    with pytest.raises(ValueError):
        bundle.resolve_translation_root(root, platform="android")


def test_optional_text_catalog_is_a_complete_provenance_pair(tmp_path):
    def add(index, files):
        for leaf in ("text.json", "text-manifest.json"):
            raw = b"offline provenance only"
            name = "ko/" + leaf
            files[name] = raw
            index["files"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    source, pins = make_bundle(tmp_path, change=add)
    root = tmp_path / "cache"
    install(source, root, pins)
    assert (bundle.resolve_translation_root(root, platform="android") / "ko/text.json").read_bytes() == b"offline provenance only"



def test_malformed_deflate_member_is_nonfatal_and_preserves_previous_selection(tmp_path):
    import struct
    from zipfile import ZIP_DEFLATED

    root = tmp_path / "cache"
    previous, previous_pins = make_bundle(tmp_path, name="previous.zip")
    install(previous, root, previous_pins)
    selected = root / "translations/current-android.json"
    before = selected.read_bytes()
    plain, _pins = make_bundle(tmp_path, version="malformed-deflate", name="plain.zip")
    malformed = tmp_path / "malformed.zip"
    with ZipFile(plain) as source, ZipFile(malformed, "w", compression=ZIP_DEFLATED) as target:
        for info in source.infolist():
            target.writestr(info.filename, source.read(info))
    with ZipFile(malformed) as archive:
        entry = archive.getinfo("translations/ko/android/objects.zip")
    body = bytearray(malformed.read_bytes())
    name_bytes, extra_bytes = struct.unpack_from("<HH", body, entry.header_offset + 26)
    start = entry.header_offset + 30 + name_bytes + extra_bytes
    # An invalid DEFLATE block raises zlib.error before any CRC/hash mismatch.
    # Re-pin the tiny synthetic outer ZIP so its parser reaches this boundary.
    body[start:start + entry.compress_size] = b"\xff" * entry.compress_size
    malformed.write_bytes(body)
    pins = {"expected_sha256": hashlib.sha256(body).hexdigest(),
            "expected_bytes": len(body), "platform": "android"}
    with pytest.raises(ValueError, match="invalid"):
        bundle.validate_translation_bundle(malformed, **pins)
    with pytest.raises(ValueError, match="invalid"):
        install(malformed, root, pins)
    assert selected.read_bytes() == before
    assert bundle.resolve_translation_root(root, platform="android").name == previous_pins["expected_sha256"]
    assert not list(root.rglob(".install-*")) and not list(root.rglob(".current-*"))
