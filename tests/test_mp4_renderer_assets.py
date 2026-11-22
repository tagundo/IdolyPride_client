"""Per-object shader preservation across translated, relocated Unity v22 Data."""
import copy
import importlib.util
import struct
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("renderer_assets", ROOT / "tools/audit_mp4_renderer_assets.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def serialized(shader=b"shader-program", text=b"Japanese", *, relative=0, shader_class=48, extra=None):
    types = [shader_class, 49]
    payloads = [(1, relative, shader, 0), (2, relative + len(shader), text, 1)]
    if extra:
        payloads.append((3, relative + len(shader) + len(text), extra, 0))
    metadata = bytearray(b"2022.3.57f1\0" + struct.pack("<iBi", 13, 0, len(types)))
    for cls in types:
        metadata += struct.pack("<iBh", cls, 0, -1) + bytes(16)
    metadata += struct.pack("<i", len(payloads))
    metadata += bytes((-len(metadata)) % 4)
    table = 48 + len(metadata)
    for path, offset, raw, kind in payloads:
        metadata += struct.pack("<qQIi", path, offset, len(raw), kind)
    metadata += bytes(8)
    offset = (48 + len(metadata) + 63) & ~63
    data = bytes(relative) + shader + text + (extra or b"")
    size = offset + len(data)
    header = struct.pack(">4I", 0, 0, 22, 0) + bytes(4) + struct.pack(">IQQQ", len(metadata), size, offset, 0)
    return header + metadata + bytes(offset - 48 - len(metadata)) + data, table


def zip_file(tmp_path, files):
    path = tmp_path / "input.apk"
    with ZipFile(path, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return path


@pytest.mark.parametrize("change", ("text", "long_text", "relocate", "compute"))
def test_only_program_bytes_define_identity(change):
    before, _ = serialized(shader_class=72 if change == "compute" else 48)
    after, _ = serialized(text=b"Korean translated text" if change == "long_text" else b"English", relative=16 if change == "relocate" else 0,
                          shader_class=72 if change == "compute" else 48)
    assert audit.serialized_programs(before) == audit.serialized_programs(after)
    assert before != after


@pytest.mark.parametrize("change", ("shader", "new_program", "class"))
def test_changed_program_is_rejected(change, monkeypatch):
    before, _ = serialized()
    monkeypatch.setattr(audit, "PROGRAMS", {"android": {"resources.assets": audit.serialized_programs(before)}})
    after, _ = serialized(shader=b"different" if change == "shader" else b"shader-program", extra=b"added" if change == "new_program" else None,
                          shader_class=72 if change == "class" else 48)
    with pytest.raises(ValueError, match="object_mismatch"):
        audit.verify_asset_bytes(after, "android", "resources.assets")


@pytest.mark.parametrize("change", ("header", "version", "platform", "type_tree", "type_count", "object_count", "path", "overlap", "extent", "kind", "length", "truncated"))
def test_malformed_serialized_data_is_rejected(change):
    source, table = serialized()
    raw = bytearray(source)
    if change == "header": raw[8:12] = struct.pack(">I", 21)
    elif change == "version": raw[48] ^= 1
    elif change == "platform": struct.pack_into("<i", raw, 61, 99)
    elif change == "type_tree": raw[65] = 1
    elif change == "type_count": struct.pack_into("<i", raw, 66, -1)
    elif change == "object_count": struct.pack_into("<i", raw, table - 4, 500001)
    elif change == "path": struct.pack_into("<q", raw, table + 24, 1)
    elif change == "overlap": struct.pack_into("<Q", raw, table + 24 + 8, 0)
    elif change == "extent": struct.pack_into("<Q", raw, table + 8, len(raw))
    elif change == "kind": struct.pack_into("<i", raw, table + 20, 3)
    elif change == "length": struct.pack_into("<I", raw, table + 16, audit.MAX_PROGRAM + 1)
    elif change == "truncated": raw.pop()
    with pytest.raises(ValueError, match="renderer_program"):
        audit.serialized_programs(bytes(raw))


@pytest.mark.parametrize("split", (False, True))
def test_archive_guard_compares_actual_objects(tmp_path, monkeypatch, split):
    before, _ = serialized()
    after, _ = serialized(text=b"Korean", relative=8)
    monkeypatch.setattr(audit, "PROGRAMS", {"android": {"resources.assets": audit.serialized_programs(before)}})
    prefix = "assets/bin/Data/resources.assets"
    files = {prefix + ".split0": after[:90], prefix + ".split1": after[90:]} if split else {prefix: after}
    report = audit.verify_archive(zip_file(tmp_path, files), "android")
    assert report["program_objects"] == 1
    assert report["shader_and_compute_object_bytes_preserved"]
    assert not report["whole_serialized_file_equality_required"]


@pytest.mark.parametrize("change", ("gap", "both", "weird", "missing", "unexpected"))
def test_archive_ambiguity_or_extra_program_is_rejected(tmp_path, monkeypatch, change):
    raw, _ = serialized()
    monkeypatch.setattr(audit, "PROGRAMS", {"android": {"resources.assets": audit.serialized_programs(raw)}})
    p = "assets/bin/Data/resources.assets"
    files = {p: raw}
    if change == "gap": files = {p + ".split1": raw}
    elif change == "both": files[p + ".split0"] = raw
    elif change == "weird": files = {p + ".splitwhat": raw}
    elif change == "missing": files = {"unrelated": b"x"}
    elif change == "unexpected": files["assets/bin/Data/extra.assets"] = raw
    with pytest.raises(ValueError, match="renderer_program"):
        audit.verify_archive(zip_file(tmp_path, files), "android")


@pytest.mark.parametrize("name", ("f7ada0af4f174f0694ca6a487b8f543d", "level0"))
def test_guid_and_scene_programs_require_an_original_object_manifest(tmp_path, monkeypatch, name):
    raw, _ = serialized()
    monkeypatch.setattr(audit, "PROGRAMS", {"android": {"resources.assets": audit.serialized_programs(raw)}})
    files = {"assets/bin/Data/resources.assets": raw, "assets/bin/Data/" + name: raw}
    with pytest.raises(ValueError, match="unexpected_program_file"):
        audit.verify_archive(zip_file(tmp_path, files), "android")


def test_source_manifest_covers_both_program_classes_and_platforms():
    assert set(audit.PROGRAMS) == {"android", "ios"}
    assert {c for files in audit.PROGRAMS.values() for objects in files.values() for c in (row["class_id"] for row in objects.values())} == {48, 72}
    assert sum(map(len, audit.PROGRAMS["android"].values())) == 153
    assert sum(map(len, audit.PROGRAMS["ios"].values())) == 152
    assert audit.source_manifest_digest("android") == "1ade73b64ddef041e430400ff9c2e3dde2ac1417efbb2f231be0a33fb25fb180"


def test_packager_guards_cover_inputs_final_output_and_language_resources():
    android = (ROOT / "tools/package_android_unified.py").read_text()
    ios = (ROOT / "ios-unified/package_unified.py").read_text()
    languages = (ROOT / "tools/build_ios_client_languages.py").read_text()
    assert 'for code, path in language_inputs.items()' in android
    assert 'renderer_assets.verify_archive(aligned, "android")' in android
    assert '"renderer_program_assets": renderer_program_assets' in android
    assert "renderer_program_assets(base_ipa,client_languages,manifest)" in ios
    assert "verify_archive(partial,'ios')" in ios
    assert "'selected_language_resources':overlays" in ios
    assert 'renderer_assets.verify_archive(stock_ipa, "ios")' in languages
    assert 'renderer_assets.verify_archive(base_ipa, "ios")' in languages
    assert 'renderer_assets.verify_asset_bytes(check.read(code + "/" + RESOURCES)' in languages


def test_actual_ios_packager_rejects_unverified_shader_programs(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "ios-unified"))
    import package_unified
    malformed = zip_file(tmp_path, {"Payload/IDOLY PRIDE.app/Data/resources.assets": b"not Unity"})
    with pytest.raises(ValueError, match="renderer_program"):
        package_unified.renderer_program_assets(malformed, None, {"inputs": {"stock_ipa": {}}})
