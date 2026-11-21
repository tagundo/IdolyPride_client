"""Finite source overlay preserves all old records and rejects data drift."""
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_love_payload", ROOT / "tools/prepare_love_server_data.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def fixture(tmp_path, monkeypatch, *, conflict=False, mutate_source=False):
    source_root = tmp_path / "source"
    for name in mod.SOURCE_FILES:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("public-source:" + name).encode())
    monkeypatch.setattr(mod, "ROOT", source_root)
    originals = {"data/master-json/" + name + ".json": b'[ {"id":"original", "unknown":{"value":"kept"}} ]\n'
                 for name in mod.RELATED_TABLES if name not in mod.NEW_TABLES}
    originals.update({
        "data/master-json/!version.txt": b"original-version\n",
        "data/protocol/pinned-descriptor.pb": b"public-original-protocol",
        "data/original-master/public-master.pack": b"public-original-encrypted-master",
        "data/translated-master/ko/Master.db": b"ko-translation-must-not-change\x00",
        "data/translated-master/en/Master.db": b"en-translation-must-not-change\x00",
        "data/home-talk/preserved.asset": b"unrelated-old-data-must-not-change",
    })
    manifest = {"schema": 1, "unknownManifestMetadata": {"kept": True},
                "tables": {name: 1 for name in mod.RELATED_TABLES if name not in mod.NEW_TABLES},
                "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                          for name, raw in sorted(originals.items())]}
    base = tmp_path / "base.zip"
    with ZipFile(base, "x", compression=ZIP_DEFLATED) as archive:
        for name, raw in sorted(originals.items()):
            info = ZipInfo(name, (2021, 2, 3, 4, 5, 6))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            info.extra = b"\x0a\x00\x00\x00"
            archive.writestr(info, raw)
        archive.writestr(mod.MANIFEST, mod.canonical(manifest))
    monkeypatch.setattr(mod, "BASE_BYTES", base.stat().st_size)
    monkeypatch.setattr(mod, "BASE_SHA256", mod.digest(base))
    events = {"event-" + str(i): {"episodes": {}} for i in range(6)}
    assets = ["asset-" + str(i) for i in range(68)] + ["love_2411_04_02"]
    for i in range(72):
        asset = assets[i % len(assets)]
        events["event-" + str(i // 12)]["episodes"]["episode-" + str(i)] = {
            "storyAssetId": asset, "advEvidence": {"available": asset != "love_2411_04_02"}}
    catalog = {"schema": 1, "schema_sha256": "a" * 64, "master_version": "b" * 64,
               "source_files": {}, "events": events, "ruleset_sha256": "c" * 64}
    seen = []
    def builder(data, output):
        seen.append(data)
        assert (data / "original-master/public-master.pack").read_bytes() == b"public-original-encrypted-master"
        assert not (data / "translated-master").exists()
        with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
            for name in mod.RELATED_TABLES:
                rows = [{"id": "original", "unknown": {"value": "kept"}}]
                if conflict and name == "Item":
                    rows[0]["unknown"]["value"] = "changed"
                archive.writestr("data/master-json/" + name + ".json", mod.canonical(rows))
            archive.writestr("data/master-json/LoveCatalog.json", mod.canonical(catalog))
            for name in sorted(mod.ADDITIONS):
                if not name.startswith("data/master-json/"):
                    archive.writestr(name, b"public-source-license-proof:" + name.encode())
            archive.writestr("data/unexpected-fresh-member.txt", b"never copied")
        if mutate_source:
            (source_root / mod.SOURCE_FILES[0]).write_bytes(b"changed during preparation")
    monkeypatch.setattr(mod, "run_builder", builder)
    return base, originals, seen


def test_overlay_is_reproducible_and_preserves_old_compressed_records(tmp_path, monkeypatch):
    base, originals, seen = fixture(tmp_path, monkeypatch)
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    report_path = tmp_path / "proof.json"
    first = mod.upgrade_server_data(base, one, report_path=report_path, prepare_overlay=tmp_path / "one-overlay.zip")
    second = mod.upgrade_server_data(base, two, prepare_overlay=tmp_path / "two-overlay.zip")
    assert first == second
    assert mod.digest(one) == mod.digest(two) == first["output"]["sha256"]
    assert report_path.read_bytes() == mod.canonical(first) + b"\n"
    assert len(seen) == 2
    with ZipFile(base) as old, ZipFile(one) as output:
        assert one.read_bytes()[:old.start_dir] == base.read_bytes()[:old.start_dir]
        assert set(output.namelist()) == set(old.namelist()) | mod.ADDITIONS
        assert len(output.namelist()) == len(set(output.namelist()))
        for name, raw in originals.items():
            assert output.read(name) == raw
            for attr in ("CRC", "compress_type", "compress_size", "header_offset", "date_time", "external_attr", "extra"):
                assert getattr(output.getinfo(name), attr) == getattr(old.getinfo(name), attr)
        manifest = json.loads(output.read(mod.MANIFEST))
        assert manifest["unknownManifestMetadata"] == {"kept": True}
        assert "LoveCatalog" not in manifest["tables"]
        assert set(manifest["tables"]) == set(mod.RELATED_TABLES)
        catalog = json.loads(output.read("data/master-json/LoveCatalog.json"))
        claimed = catalog.pop("ruleset_sha256")
        assert claimed == hashlib.sha256(mod.canonical(catalog)).hexdigest()
        for name, sha in catalog["source_files"].items():
            assert hashlib.sha256(output.read("data/master-json/" + name)).hexdigest() == sha
        for row in first["added_members"]:
            info = output.getinfo(row["path"])
            assert info.compress_type == 0 and info.date_time == mod.STAMP
            assert info.extra == info.comment == b""
        assert "data/unexpected-fresh-member.txt" not in output.namelist()
    assert first["love_catalog"]["events"] == 6
    assert first["love_catalog"]["episodes"] == 72
    assert first["love_catalog"]["unique_adv_assets"] == 69
    assert first["love_catalog"]["observed_adv_assets"] == 68
    assert first["love_catalog"]["missing_adv_assets"] == ["love_2411_04_02"]
    assert first["unchanged_old_entries"]["count"] == len(originals)
    assert first["determinism"]["old_compressed_records_preserved"] is True
    assert len(first["component_sources"]) == 7
    assert len(first["prepared_overlay"]["members"]) == 11
    assert {row["path"] for row in first["prepared_overlay"]["members"]} == mod.ADDITIONS
    assert first["prepared_overlay"]["sha256"] == mod.digest(tmp_path / "one-overlay.zip")


@pytest.mark.parametrize("problem", ("content", "size", "symlink", "existing-output"))
def test_wrong_base_and_existing_outputs_fail_before_builder(tmp_path, monkeypatch, problem):
    base, _, seen = fixture(tmp_path, monkeypatch)
    output = tmp_path / "output.zip"
    if problem == "content":
        monkeypatch.setattr(mod, "BASE_SHA256", "0" * 64)
    elif problem == "size":
        monkeypatch.setattr(mod, "BASE_BYTES", base.stat().st_size + 1)
    elif problem == "symlink":
        linked = tmp_path / "link.zip"
        linked.symlink_to(base)
        base = linked
    else:
        output.write_bytes(b"owned-existing-do-not-delete")
    with pytest.raises(mod.PreparationError):
        mod.upgrade_server_data(base, output, prepare_overlay=tmp_path / "overlay.zip")
    assert not seen
    if problem == "existing-output":
        assert output.read_bytes() == b"owned-existing-do-not-delete"
    else:
        assert not output.exists()


@pytest.mark.parametrize("problem", ("retained-data-differs", "source-mutated"))
def test_mutating_retained_tables_or_sources_aborts_without_partial_output(tmp_path, monkeypatch, problem):
    base, _, _ = fixture(tmp_path, monkeypatch, conflict=problem == "retained-data-differs",
                         mutate_source=problem == "source-mutated")
    output, report = tmp_path / "output.zip", tmp_path / "proof.json"
    with pytest.raises(mod.PreparationError, match="love_payload_(original_table_differs|source_changed)"):
        mod.upgrade_server_data(base, output, report_path=report, prepare_overlay=tmp_path / "overlay.zip")
    assert not output.exists() and not report.exists()
    assert not list(tmp_path.glob(".love-payload-*"))


@pytest.mark.parametrize("raw", (b'[{},]', b'[{}{}]', b'[,{}]', b'[{},,{}]', b'[1]', b'[]tail', b'[',
                                  b'[{"x":1,"x":2}]', b'[{"x":NaN}]'))
def test_table_parser_rejects_malformed_or_ambiguous_data(tmp_path, raw):
    path = tmp_path / "table.json"
    path.write_bytes(raw)
    with pytest.raises(mod.PreparationError):
        mod.semantic_rows(path)


def test_semantic_digest_retains_nested_unknown_fields_across_chunk_boundaries(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    rows = [{"id": "first", "unknown": {"unicode": "原文" * 40000, "nested": [1, True, None]}}, {"id": "second"}]
    first.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    second.write_bytes(mod.canonical(rows))
    assert mod.semantic_rows(first) == mod.semantic_rows(second)
    target = tmp_path / "canonical.json"
    mod.canonical_table(first, target)
    assert target.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("name", ("data/../escape", "/data/absolute", "data/./alias", "data/back\\slash"))
def test_public_extraction_rejects_path_aliases_before_writing(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    with ZipFile(path, "x") as archive:
        archive.writestr(name, b"public")
    with ZipFile(path) as archive, pytest.raises(mod.PreparationError, match="love_payload_member_rejected"):
        mod.inventory(archive)


def test_native_apply_reproduces_compile_without_decoder_or_public_extraction(tmp_path, monkeypatch):
    base, _, _ = fixture(tmp_path, monkeypatch)
    overlay = tmp_path / "public-overlay.zip"
    prepared = mod.upgrade_server_data(base, tmp_path / "prepared.zip", prepare_overlay=overlay)
    checked = []
    def verify(path):
        checked.append(path)
        assert mod.digest(path) == prepared["prepared_overlay"]["sha256"]
        return prepared["prepared_overlay"]
    monkeypatch.setattr(mod, "verify_prepared_overlay", verify)
    def forbidden(*args, **kwargs):
        raise AssertionError("native apply invoked original-master data preparation")
    monkeypatch.setattr(mod, "run_builder", forbidden)
    monkeypatch.setattr(mod, "extract_public", forbidden)
    applied = mod.upgrade_server_data(base, tmp_path / "applied.zip", overlay_zip=overlay)
    assert checked == [overlay]
    assert applied == prepared
    assert (tmp_path / "applied.zip").read_bytes() == (tmp_path / "prepared.zip").read_bytes()


def test_apply_requires_explicit_mode_and_static_overlay_verification(tmp_path, monkeypatch):
    base, _, seen = fixture(tmp_path, monkeypatch)
    with pytest.raises(mod.PreparationError, match="^love_payload_overlay_mode_required$"):
        mod.upgrade_server_data(base, tmp_path / "none.zip")
    with pytest.raises(mod.PreparationError, match="^love_payload_overlay_mode_required$"):
        mod.upgrade_server_data(base, tmp_path / "both.zip", overlay_zip=tmp_path / "untrusted.zip",
                                prepare_overlay=tmp_path / "new.zip")
    def unpinned(path):
        raise ValueError("untrusted public overlay")
    monkeypatch.setattr(mod, "verify_prepared_overlay", unpinned)
    with pytest.raises(ValueError, match="untrusted public overlay"):
        mod.upgrade_server_data(base, tmp_path / "unpinned.zip", overlay_zip=tmp_path / "untrusted.zip")
    assert not seen


def test_failure_does_not_delete_another_calls_output(tmp_path, monkeypatch):
    base, _, _ = fixture(tmp_path, monkeypatch)
    output = tmp_path / "racing.zip"
    original = mod.run_builder
    def other_owner(data, fresh):
        original(data, fresh)
        output.write_bytes(b"another concurrent owner")
    monkeypatch.setattr(mod, "run_builder", other_owner)
    with pytest.raises(FileExistsError):
        mod.upgrade_server_data(base, output, prepare_overlay=tmp_path / "owned-overlay.zip")
    assert output.read_bytes() == b"another concurrent owner"
    assert not (tmp_path / "owned-overlay.zip").exists()
