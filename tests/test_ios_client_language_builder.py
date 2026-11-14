import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

from idoly_local import ios_client_data, static_ui_assets, ui_assets


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[1] / "tools/build_ios_client_languages.py"
    spec = importlib.util.spec_from_file_location("test_ios_language_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_inputs(tmp_path, monkeypatch, builder):
    stock, base = tmp_path / "stock.ipa", tmp_path / "ko.ipa"
    source = {"Data/shared": b"same shader bytes", "Data/resources.assets": b"Japanese UI",
              "Data/Managed/Metadata/global-metadata.dat": b"Japanese metadata"}
    korean = {**source, "Data/resources.assets": b"Korean UI and translated images",
              "Data/Managed/Metadata/global-metadata.dat": b"Korean metadata"}
    for archive, files in ((stock, source), (base, korean)):
        with ZipFile(archive, "w") as z:
            for name, raw in files.items():
                z.writestr(builder.APP + name, raw)
    monkeypatch.setattr(builder, "STOCK_SHA256", hashlib.sha256(stock.read_bytes()).hexdigest())
    monkeypatch.setattr(builder, "BASE_SHA256", hashlib.sha256(base.read_bytes()).hexdigest())
    monkeypatch.setattr(builder, "STOCK_BYTES", stock.stat().st_size)
    monkeypatch.setattr(builder, "BASE_BYTES", base.stat().st_size)
    csv = b"KEY,Japanese\nyes,Yes\n"
    monkeypatch.setattr(ui_assets, "load_package_inputs", lambda language, *args: (csv, {"language": language}))
    monkeypatch.setitem(ui_assets.ASSETS, "ios", {"source_sha256": hashlib.sha256(source[builder.RESOURCES]).hexdigest(),
                                                "source_bytes": len(source[builder.RESOURCES])})
    calls = []
    def resources(incoming, destination, *, language, ui_csv, ui_proof):
        assert language == "en" and ui_csv == csv and ui_proof == {"language": "en"}
        assert incoming.read() == source[builder.RESOURCES]
        raw = b"English prebuilt UI"
        destination.write(raw); calls.append(language)
        return {"output_asset_bytes": len(raw), "output_asset_sha256": hashlib.sha256(raw).hexdigest(),
                "all_other_object_payloads_unchanged": True, "changes": ["not copied into receipt"]}
    monkeypatch.setattr(static_ui_assets, "patch_ios_stream", resources)
    def metadata(raw, language):
        assert raw == source[builder.METADATA]
        return (language + " local metadata").encode(), {"language": language}
    monkeypatch.setattr(builder, "_metadata_variant", metadata)
    return stock, base, korean, calls


def test_prebuilt_archive_roundtrips_into_each_complete_runtime_bundle(tmp_path, monkeypatch, builder):
    stock, base, korean, calls = source_inputs(tmp_path, monkeypatch, builder)
    output = tmp_path / "output/client-languages.zip"
    report = builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json")
    assert calls == ["en"]
    assert report["runtime_string_translation"] is False and report["signed_app_modified_at_runtime"] is False
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", *[lang + "/" + name for lang in ("ja", "en") for name in builder.OVERLAYS]}
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["common"].keys() == {"Data/shared"}
    assert all(row["source"] == "base" and "member" not in row for row in manifest["languages"]["ko"].values())
    app, data = tmp_path / "App.app", tmp_path / "state"
    (app / "LocalServer").mkdir(parents=True); data.mkdir()
    (app / "LocalServer/client-languages.zip").write_bytes(output.read_bytes())
    (app / "LocalServer/client-languages.json").write_bytes(output.with_suffix(".json").read_bytes())
    for name, raw in korean.items():
        path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    bundles = {lang: Path(ios_client_data.prepare_client_data(app, data, lang)["bundle_path"]) for lang in ios_client_data.LANGUAGES}
    assert (bundles["ko"] / builder.RESOURCES).read_bytes() == korean[builder.RESOURCES]
    assert (bundles["ja"] / builder.RESOURCES).read_bytes() == b"Japanese UI"
    assert (bundles["en"] / builder.RESOURCES).read_bytes() == b"English prebuilt UI"
    assert all((bundles[lang] / builder.METADATA).read_bytes() == (lang + " local metadata").encode() for lang in ("ja", "en"))


def test_unpinned_source_is_rejected_before_building(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    stock.write_bytes(stock.read_bytes() + b"changed")
    output = tmp_path / "out/client-languages.zip"
    with pytest.raises(ValueError, match="pinned"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json")
    assert not output.exists()


def test_writer_output_identity_mismatch_never_publishes_a_package(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    def wrong(incoming, destination, **kwargs):
        destination.write(b"actual bytes")
        return {"output_asset_bytes": 12, "output_asset_sha256": "0" * 64}
    monkeypatch.setattr(static_ui_assets, "patch_ios_stream", wrong)
    output = tmp_path / "out/client-languages.zip"
    with pytest.raises(ValueError, match="output member"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json")
    assert not output.exists() and not output.with_suffix(".zip.part").exists()


def test_existing_outputs_are_preserved(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    output = tmp_path / "client-languages.zip"; output.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json")
    assert output.read_bytes() == b"preserve"
