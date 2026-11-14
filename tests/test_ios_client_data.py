import hashlib
import json
import os
from pathlib import Path
import plistlib
import zipfile

import pytest

from idoly_local import ios_client_data as data


def spec(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def fixture(tmp_path, *, alter_manifest=None, extra=None, bad_overlay=False):
    app, state = tmp_path / "Game.app", tmp_path / "state"
    (app / "LocalServer").mkdir(parents=True); state.mkdir()
    files = {"Data/common-shader": b"shared original bytes", "Data/Raw/empty": b"",
             "Data/resources.assets": b"Korean embedded UI and images",
             "Data/Managed/Metadata/global-metadata.dat": b"Korean local metadata"}
    for name, raw in files.items():
        path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    manifest = {"schema": 1, "policy": data.POLICY, "bundle_id": data.BUNDLE_ID,
                "common": {name: spec(raw) for name, raw in files.items() if name not in data.OVERLAYS},
                "languages": {lang: {} for lang in data.LANGUAGES},
                "source": {"stock_ipa_sha256": "a" * 64, "base_ipa_sha256": "b" * 64,
                           "english_ui_sha256": "c" * 64}}
    overlays = {}
    for lang in data.LANGUAGES:
        for name in data.OVERLAYS:
            raw = files[name] if lang == "ko" else (lang + ":" + name).encode()
            row = {**spec(raw), "source": "base" if lang == "ko" else "archive"}
            if lang != "ko":
                member = lang + "/" + name; row["member"] = member; overlays[member] = raw
            manifest["languages"][lang][name] = row
    if alter_manifest:
        alter_manifest(manifest)
    package = app / "LocalServer/client-languages.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        for name, raw in overlays.items():
            z.writestr(name, b"bad data" if bad_overlay and name.startswith("en/") else raw)
        if extra:
            z.writestr(extra, b"unexpected")
    (app / "LocalServer/client-languages.json").write_text(json.dumps({"schema": 1, **spec(package.read_bytes())}))
    return app, state, files, manifest


@pytest.mark.parametrize("language", data.LANGUAGES)
def test_prepares_selected_prebuilt_language_and_reuses_verified_bundle(tmp_path, language):
    app, state, originals, manifest = fixture(tmp_path)
    result = data.prepare_client_data(app, state, language)
    bundle = Path(result["bundle_path"])
    assert result == {"schema": 1, "language": language, "bundle_id": data.BUNDLE_ID,
                      "bundle_path": str(state / "client-data" / (language + ".bundle")),
                      "reused": False, "files": 4}
    info = plistlib.loads((bundle / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "local.idoly.client-data"
    assert info["CFBundlePackageType"] == "BNDL" and "CFBundleExecutable" not in info
    assert info["IdolyClientLanguage"] == language
    for name, row in {**manifest["common"], **manifest["languages"][language]}.items():
        assert spec((bundle / name).read_bytes()) == {k: row[k] for k in ("bytes", "sha256")}
    for name, raw in originals.items():
        assert (app / name).read_bytes() == raw
        assert (app / name).stat().st_ino != (bundle / name).stat().st_ino
    assert data.prepare_client_data(app, state, language) == {**result, "reused": True}


def test_common_links_are_owned_and_cache_damage_does_not_modify_signed_app(tmp_path):
    app, state, originals, _ = fixture(tmp_path)
    ko = Path(data.prepare_client_data(app, state, "ko")["bundle_path"])
    en = Path(data.prepare_client_data(app, state, "en")["bundle_path"])
    relative = "Data/common-shader"
    assert (ko / relative).stat().st_ino == (en / relative).stat().st_ino
    assert (ko / relative).stat().st_ino != (app / relative).stat().st_ino
    (ko / relative).write_bytes(b"changed only owned cache")
    assert (app / relative).read_bytes() == originals[relative]
    repaired = data.prepare_client_data(app, state, "ko")
    assert repaired["reused"] is False
    assert (ko / relative).read_bytes() == originals[relative]
    assert list((state / "client-data").glob("*.retired-*"))


def test_link_unavailable_falls_back_to_owned_copy(tmp_path, monkeypatch):
    app, state, _, _ = fixture(tmp_path)
    def unavailable(*args, **kwargs):
        raise OSError("cross filesystem")
    monkeypatch.setattr(data.os, "link", unavailable)
    result = data.prepare_client_data(app, state, "en")
    assert Path(result["bundle_path"]).is_dir()


@pytest.mark.parametrize("extra", ("../../escape", "en/Data/unlisted", "Info.plist"))
def test_extra_or_escaping_archive_entries_are_rejected(tmp_path, extra):
    app, state, _, _ = fixture(tmp_path, extra=extra)
    with pytest.raises(ValueError, match="inventory"):
        data.prepare_client_data(app, state, "en")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("change", (
    lambda m: m["common"].update({"Data/../../escape": spec(b"x")}),
    lambda m: m["languages"]["en"].clear(),
    lambda m: m["languages"]["en"]["Data/resources.assets"].update(source="base"),
    lambda m: m["languages"]["en"]["Data/resources.assets"].update(member="ko/Data/resources.assets"),
    lambda m: m.update(schema=True),
    lambda m: m.update(bundle_id="unexpected.bundle"),
))
def test_invalid_language_manifest_is_rejected(tmp_path, change):
    app, state, _, _ = fixture(tmp_path, alter_manifest=change)
    with pytest.raises(ValueError):
        data.prepare_client_data(app, state, "en")


def test_overlay_hash_failure_cleans_only_its_stage(tmp_path):
    app, state, originals, _ = fixture(tmp_path, bad_overlay=True)
    with pytest.raises(ValueError):
        data.prepare_client_data(app, state, "en")
    assert not (state / "client-data/en.bundle").exists()
    assert not list((state / "client-data").glob(".prepare-*"))
    assert all((app / name).read_bytes() == raw for name, raw in originals.items())


def test_descriptor_and_source_symlinks_are_rejected(tmp_path):
    app, state, _, _ = fixture(tmp_path)
    (app / "Data/common-shader").unlink()
    outside = tmp_path / "private"; outside.write_bytes(b"do not read")
    (app / "Data/common-shader").symlink_to(outside)
    with pytest.raises(ValueError):
        data.prepare_client_data(app, state, "ja")
    assert outside.read_bytes() == b"do not read"


def test_unrecognized_existing_bundle_is_preserved(tmp_path):
    app, state, _, _ = fixture(tmp_path)
    target = state / "client-data/ja.bundle"; target.mkdir(parents=True)
    (target / "user-file").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="preserved"):
        data.prepare_client_data(app, state, "ja")
    assert (target / "user-file").read_bytes() == b"preserve"


def test_package_hash_mismatch_stops_before_destination_creation(tmp_path):
    app, state, _, _ = fixture(tmp_path)
    package = app / "LocalServer/client-languages.zip"
    package.write_bytes(package.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="package hash"):
        data.prepare_client_data(app, state, "ko")
    assert not (state / "client-data").exists()


def test_symbolic_destination_is_never_followed(tmp_path):
    app, state, _, _ = fixture(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir()
    (state / "client-data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        data.prepare_client_data(app, state, "ko")
    assert list(outside.iterdir()) == []
