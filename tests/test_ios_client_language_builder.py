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
    def korean_resources(stock_zip, base_zip, destination, image_dir):
        assert stock_zip.read(builder.APP + builder.RESOURCES) == source[builder.RESOURCES]
        assert base_zip.read(builder.APP + builder.RESOURCES) == korean[builder.RESOURCES]
        raw = b"Fresh Korean UI with original button aspect"
        destination.write(raw)
        return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, {
            "original_stock_rebuilt": True, "all_other_objects_byte_identical": True}
    monkeypatch.setattr(builder, "_korean_resources", korean_resources)
    return stock, base, korean, calls


def test_prebuilt_archive_roundtrips_into_each_complete_runtime_bundle(tmp_path, monkeypatch, builder):
    stock, base, korean, calls = source_inputs(tmp_path, monkeypatch, builder)
    output = tmp_path / "output/client-languages.zip"
    report = builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json", image_dir=tmp_path / "images")
    assert calls == ["en"]
    assert report["runtime_string_translation"] is False and report["signed_app_modified_at_runtime"] is False
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {"manifest.json", "ko/" + builder.RESOURCES,
            *[lang + "/" + name for lang in ("ja", "en") for name in builder.OVERLAYS]}
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["common"].keys() == {"Data/shared"}
    assert manifest["languages"]["ko"][builder.RESOURCES]["source"] == "archive"
    assert manifest["languages"]["ko"][builder.METADATA]["source"] == "base"
    assert report["language_members"] == 3 and report["korean_resources_refreshed"] is True
    assert report["proofs"]["korean_resources"]["all_other_objects_byte_identical"] is True
    app, data = tmp_path / "App.app", tmp_path / "state"
    (app / "LocalServer").mkdir(parents=True); data.mkdir()
    (app / "LocalServer/client-languages.zip").write_bytes(output.read_bytes())
    (app / "LocalServer/client-languages.json").write_bytes(output.with_suffix(".json").read_bytes())
    for name, raw in korean.items():
        path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    bundles = {lang: Path(ios_client_data.prepare_client_data(app, data, lang)["bundle_path"]) for lang in ios_client_data.LANGUAGES}
    assert (bundles["ko"] / builder.RESOURCES).read_bytes() == b"Fresh Korean UI with original button aspect"
    assert (app / builder.RESOURCES).read_bytes() == korean[builder.RESOURCES]
    assert (bundles["ja"] / builder.RESOURCES).read_bytes() == b"Japanese UI"
    assert (bundles["en"] / builder.RESOURCES).read_bytes() == b"English prebuilt UI"
    assert all((bundles[lang] / builder.METADATA).read_bytes() == (lang + " local metadata").encode() for lang in ("ja", "en"))


def test_unpinned_source_is_rejected_before_building(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    stock.write_bytes(stock.read_bytes() + b"changed")
    output = tmp_path / "out/client-languages.zip"
    with pytest.raises(ValueError, match="pinned"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json", image_dir=tmp_path / "images")
    assert not output.exists()


def test_writer_output_identity_mismatch_never_publishes_a_package(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    def wrong(incoming, destination, **kwargs):
        destination.write(b"actual bytes")
        return {"output_asset_bytes": 12, "output_asset_sha256": "0" * 64}
    monkeypatch.setattr(static_ui_assets, "patch_ios_stream", wrong)
    output = tmp_path / "out/client-languages.zip"
    with pytest.raises(ValueError, match="output member"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json", image_dir=tmp_path / "images")
    assert not output.exists() and not output.with_suffix(".zip.part").exists()


def test_existing_outputs_are_preserved(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    output = tmp_path / "client-languages.zip"; output.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="fresh"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json", image_dir=tmp_path / "images")
    assert output.read_bytes() == b"preserve"


def test_fresh_korean_resources_cannot_silently_use_the_old_base(tmp_path, monkeypatch, builder):
    stock, base, _, _ = source_inputs(tmp_path, monkeypatch, builder)
    output = tmp_path / "out/client-languages.zip"
    with pytest.raises(ValueError, match="explicit pinned image inputs"):
        builder.build_client_languages(stock, base, output, english_csv=tmp_path / "en.csv", english_proof=tmp_path / "en.json")
    assert not output.exists()


def serialized_resource(rows, *, trailer=b"\0" * 13):
    import struct
    classes = sorted({kind for _, kind, _ in rows})
    metadata = bytearray(b"2022.3.57f1\0" + struct.pack("<iBi", 9, 0, len(classes)))
    for kind in classes:
        metadata.extend(struct.pack("<iBh", kind, 0, -1))
        if kind == 114: metadata.extend(b"s" * 16)
        metadata.extend(bytes([kind % 256]) * 16)
    metadata.extend(struct.pack("<i", len(rows)))
    metadata.extend(b"\0" * (-(48 + len(metadata)) % 4))
    body = bytearray()
    for path, kind, raw in sorted(rows):
        metadata.extend(struct.pack("<qQIi", path, len(body), len(raw), classes.index(kind)))
        body.extend(raw); body.extend(b"\0" * (-len(body) % 8))
    metadata.extend(trailer)
    offset = (48 + len(metadata) + 15) & ~15
    header = struct.pack(">4I", 0, 0, 22, 0) + b"\0" * 4
    header += struct.pack(">IQQQ", len(metadata), offset + len(body), offset, 0)
    return header + metadata + b"\0" * (offset - 48 - len(metadata)) + body


def korean_graph_fixture():
    from idoly_local.static_ui_images import FIXED_LOVE_TEXT, TEXT_LAYOUT_POLICY
    before, after, sprites = [], [], []
    for number, (name, (size, _)) in enumerate(FIXED_LOVE_TEXT.items(), 1):
        for path, kind in ((number, 213), (100 + number, 28)):
            before.append((path, kind, b"old-" + name.encode()))
            after.append((path, kind, b"fresh-aspect-" + name.encode()))
        sprites.append({"name": name, "sprite_path_id": number, "private_texture_path_id": 100 + number,
            "layout_policy": TEXT_LAYOUT_POLICY, "readback_pixel_exact": True,
            "layout_size": list(size), "original_layout_size": list(size)})
    import base64
    from idoly_local.static_ui_images import _logo_rect, _logo_summary
    fixtures=json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/love-logo-rect-transforms.json").read_text())
    transforms=[]
    for row in fixtures["objects"]:
        if row["platform"]!="ios": continue
        raw=base64.b64decode(row["raw_base64"]); updated,proof=_logo_rect(raw,row["name"],"ios")
        before.append((row["path_id"],224,raw));after.append((row["path_id"],224,updated));transforms.append(proof)
    before.append((1000, 114, b"original font, story and other UI bytes"))
    after.append(before[-1])
    return before, after, {"sprites": sprites,"logo_layout":_logo_summary("ios",transforms,[])}


def test_korean_refresh_compares_every_undeclared_resource_object(builder):
    from io import BytesIO
    before, after, proof = korean_graph_fixture()
    result = builder._compare_korean_resources(BytesIO(serialized_resource(before)), BytesIO(serialized_resource(after)), proof)
    assert result["all_other_objects_byte_identical"] is True
    assert result["unchanged_object_count"] == 1
    assert len(result["declared_object_differences"]) == 23
    assert all(row["changed"] for row in result["declared_object_differences"])


@pytest.mark.parametrize("damage", ("font-or-story", "external-reference", "missing-object", "wrong-class", "missing-proof", "wrong-geometry"))
def test_korean_refresh_cannot_drop_existing_font_story_or_resource_graph(builder, damage):
    from io import BytesIO
    before, after, proof = korean_graph_fixture(); trailer = b"\0" * 13
    if damage == "font-or-story": after[-1] = (1000, 114, b"regressed original font or story")
    elif damage == "external-reference": trailer = b"changed-refs!"
    elif damage == "missing-object": after.pop()
    elif damage == "wrong-class": after[0] = (after[0][0], 114, after[0][2])
    elif damage == "missing-proof": proof["sprites"].pop()
    elif damage == "wrong-geometry": proof["sprites"][0]["layout_size"] = [1, 1]
    with pytest.raises(ValueError):
        builder._compare_korean_resources(BytesIO(serialized_resource(before)), BytesIO(serialized_resource(after, trailer=trailer)), proof)


@pytest.mark.parametrize("damage",("unknown-transform","nonuniform-scale","changed-position","wrong-original-hash","missing-logo","updated-corrupt-transform"))
def test_korean_refresh_rejects_an_unproven_or_nonuniform_whole_logo(builder,damage):
    from io import BytesIO
    before,after,proof=korean_graph_fixture();logo=proof["logo_layout"]
    if damage=="unknown-transform":logo["transforms"][0]["path_id"]=999
    elif damage=="nonuniform-scale":logo["uniform_scale"]=0.5
    elif damage=="changed-position":logo["transforms"][0]["position"]=[0,0]
    elif damage=="wrong-original-hash":logo["transforms"][0]["input_sha256"]="0"*64
    elif damage=="missing-logo":proof.pop("logo_layout")
    elif damage=="updated-corrupt-transform":
        row=logo["transforms"][0];index=next(i for i,item in enumerate(after) if item[0]==row["path_id"])
        path,kind,raw=after[index];corrupt=bytes([raw[0]^1])+raw[1:];after[index]=(path,kind,corrupt)
        row["output_sha256"]=hashlib.sha256(corrupt).hexdigest()
    with pytest.raises(ValueError):
        builder._compare_korean_resources(BytesIO(serialized_resource(before)),BytesIO(serialized_resource(after)),proof)


@pytest.mark.parametrize("same_size", (False, True))
def test_korean_refresh_rejection_identifies_only_the_public_changed_object(builder, same_size):
    from io import BytesIO
    before, after, proof = korean_graph_fixture()
    path, kind, original = before[-1]
    changed = b"x" * len(original) if same_size else b"different resource bytes"
    after[-1] = (path, kind, changed)
    with pytest.raises(ValueError) as failure:
        builder._compare_korean_resources(
            BytesIO(serialized_resource(before)), BytesIO(serialized_resource(after)), proof)
    assert str(failure.value) == (
        "An undeclared Korean UI, font, story or other resource object changed: "
        f"path_id={path}, class_id={kind}, old_bytes={len(original)}, new_bytes={len(changed)}, "
        f"old_sha256={hashlib.sha256(original).hexdigest()}, "
        f"new_sha256={hashlib.sha256(changed).hexdigest()}")
    assert original.decode() not in str(failure.value)
    assert changed.decode() not in str(failure.value)
