"""Streaming serialized-file surgery preserves every non-UI object and reference."""
import hashlib
import io
import json
import struct
from zipfile import ZIP_STORED, ZipFile

import pytest

from idoly_local import ui_assets as ui


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def csv_bytes(value="original"):
    return ("KEY,Japanese\n" + "".join(f'key-{index},"{value}"\n' for index in range(4199))).encode()


def fixture(monkeypatch, old_length=64):
    original_csv = csv_bytes()
    monkeypatch.setattr(ui, "ORIGINAL_CSV_SHA256", sha(original_csv))
    keys = [f"key-{index}" for index in range(4199)]
    monkeypatch.setattr(ui, "ORIGINAL_KEYS_SHA256", sha(b"\0".join(key.encode() for key in sorted(keys))))
    old_script = (bytes(range(256)) * ((old_length + 255) // 256))[:old_length]
    monkeypatch.setattr(ui, "ORIGINAL_SCRIPT_BYTES", len(old_script))
    monkeypatch.setattr(ui, "ORIGINAL_SCRIPT_SHA256", sha(old_script))
    name = b"af07872d088f944f"
    target = struct.pack("<I", len(name)) + name + struct.pack("<I", len(old_script)) + old_script
    assert len(target) % 8 == 0
    before = b"BEFORE\0\xff"
    between = b"ORIG-PAD"
    after = b"AFTER\xff\xfeREFERENCES"
    start = len(before)
    after_offset = start + len(target) + len(between)
    data = before + target + between + after + b"TRAILER"
    metadata = bytearray(320)
    struct.pack_into(">4I", metadata, 0, 0, 0, 22, 0)
    struct.pack_into(">IQQQ", metadata, 20, 256, len(metadata) + len(data), len(metadata), 0)
    struct.pack_into("<i", metadata, 92, 4)
    records = [(11, 0, len(before), 0), (1, start, len(target), 0),
               (77, after_offset, len(after), 0), (99, len(data), 0, 0)]
    for index, record in enumerate(records):
        struct.pack_into("<qQIi", metadata, 96 + index * 24, *record)
    unknown = b"UNKNOWN-TYPES-EXTERNALS-SCRIPTS!"
    metadata[240:240 + len(unknown)] = unknown
    raw = bytes(metadata) + data
    profile = dict(source_bytes=len(raw), source_sha256=sha(raw), metadata_sha256=sha(metadata),
                   metadata_bytes=256, data_offset=320, table_offset=96, object_count=4, object_count_offset=92,
                   type_count=1, target_index=1, target_path_id=1, target_relative_offset=start,
                   target_bytes=len(target), target_type_id=0, target_name=name.decode(),
                   target_object_sha256=sha(target))
    monkeypatch.setitem(ui.ASSETS, "android", profile)
    monkeypatch.setitem(ui.ASSETS, "ios", profile)
    return raw, profile, original_csv, records


class BoundedSource(io.BytesIO):
    def __init__(self, raw):
        super().__init__(raw)
        self.read_sizes = []

    def read(self, size=-1):
        assert 0 <= size <= ui.COPY_BYTES, "The full serialized file must never be read in one call"
        self.read_sizes.append(size)
        return super().read(size)


class ForwardDestination:
    def __init__(self):
        self.raw = bytearray()

    def write(self, raw):
        self.raw.extend(raw)
        return len(raw)


@pytest.mark.parametrize("old_length", [64, 131072])
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_growing_and_shrinking_target_preserves_other_objects_metadata_and_alignment(monkeypatch, old_length, platform):
    raw, profile, original_csv, records = fixture(monkeypatch, old_length)
    source, output = BoundedSource(raw), ForwardDestination()
    translated = csv_bytes("translated")
    proof = dict(language="ko", input_sha256=sha(original_csv), output_sha256=sha(translated),
                 bytes=len(translated), source_ui_keys=4199)
    report = ui.patch_asset_stream(source, output, translated, platform, language="ko", translation_proof=proof)
    patched = bytes(output.raw)
    delta = report["physical_size_delta"]
    assert delta % 8 == 0 and (delta > 0) == (old_length == 64)
    assert len(patched) == len(raw) + delta == report["output_asset_bytes"]
    assert sha(patched) == report["output_asset_sha256"]
    assert struct.unpack_from(">Q", patched, 24)[0] == len(patched)
    allowed = set(range(24, 32))
    for index, (path, offset, length, type_id) in enumerate(records):
        at = 96 + index * 24
        changed = struct.unpack_from("<qQIi", patched, at)
        assert changed[0] == path and changed[3] == type_id
        if path == 1:
            assert changed[1] == offset
            target = patched[320 + changed[1]:320 + changed[1] + changed[2]]
            assert target[:20] == raw[320 + offset:320 + offset + 20]
            script_length = struct.unpack_from("<I", target, 20)[0]
            assert target[24:24 + script_length] == translated
            assert set(target[24 + script_length:]) <= {0}
            allowed.update(range(at + 16, at + 20))
        else:
            assert changed[1] == offset + (delta if index >= 2 else 0)
            assert changed[2] == length
            assert patched[320 + changed[1]:320 + changed[1] + length] == raw[320 + offset:320 + offset + length]
            if index >= 2:
                allowed.update(range(at + 8, at + 16))
    assert all(patched[index] == raw[index] for index in range(320) if index not in allowed)
    assert b"ORIG-PAD" in patched and patched.endswith(b"TRAILER")
    assert report["other_object_count"] == 3 and report["shifted_object_offsets"] == 2
    assert report["runtime_translation_hooks_added"] is report["font_assets_modified"] is False
    assert max(source.read_sizes) <= ui.COPY_BYTES


def test_full_original_fingerprint_is_verified_before_any_output(monkeypatch):
    raw, profile, original_csv, _ = fixture(monkeypatch)
    changed = bytearray(raw);changed[-1] ^= 1
    output = ForwardDestination()
    with pytest.raises(ValueError, match="full fingerprint"):
        ui.patch_asset_stream(BoundedSource(changed), output, original_csv, "android")
    assert output.raw == b""
    changed = bytearray(raw);changed[240] ^= 1
    with pytest.raises(ValueError, match="metadata differs"):
        ui.patch_asset_stream(BoundedSource(changed), output, original_csv, "android")
    assert output.raw == b""


def test_changed_source_between_passes_cannot_return_a_success_proof(monkeypatch):
    raw, _, original_csv, _ = fixture(monkeypatch)

    class MutatingSource(BoundedSource):
        passes = 0

        def seek(self, *args):
            result = super().seek(*args)
            self.passes += 1
            if self.passes == 2:
                at = self.tell();self.getbuffer()[-1] ^= 1;super().seek(at)
            return result

    with pytest.raises(ValueError, match="changed during"):
        ui.patch_asset_stream(MutatingSource(raw), ForwardDestination(), original_csv, "android")


def test_csv_guard_preserves_exact_keys_header_and_native_parser_newlines(monkeypatch):
    _, _, original_csv, _ = fixture(monkeypatch)
    assert ui.validate_csv(original_csv)["ui_keys"] == 4199
    for changed in [b"\xef\xbb\xbf" + original_csv,
                    original_csv.replace(b"KEY,Japanese", b'"KEY","Japanese"', 1),
                    original_csv.replace(b"Japanese", b"Korean", 1),
                    original_csv.replace(b'"original"', b'"literal\nnewline"', 1),
                    original_csv.replace(b"key-0,", b"wrong-key,", 1),
                    original_csv.replace(b"key-1,", b"key-0,", 1)]:
        with pytest.raises(ValueError):
            ui.validate_csv(changed)
    assert ui.validate_csv(original_csv.replace(b'"original"', b'"escaped\\nnewline, ""quote"""', 1))


def test_fixed_language_proof_binds_original_output_language_and_coverage(monkeypatch):
    _, _, original_csv, _ = fixture(monkeypatch)
    translated = csv_bytes("translated")
    proof = dict(language="ko", input_sha256=sha(original_csv), output_sha256=sha(translated),
                 bytes=len(translated), source_ui_keys=4199, matching_keys=4199, changed_keys_count=4199)
    assert ui.validate_proof(proof, translated, "ko") == proof
    for changed in [None, {**proof, "language": "en"}, {**proof, "output_sha256": "0" * 64},
                    {**proof, "bytes": True}, {**proof, "source_ui_keys": 1},
                    {**proof, "matching_keys": 4200}]:
        with pytest.raises(ValueError):
            ui.validate_proof(changed, translated, "ko")
    with pytest.raises(ValueError, match="Japanese UI"):
        ui.validate_proof(None, translated, "ja")


def test_android_member_and_ios_forward_zip_writer_use_only_declared_member(monkeypatch):
    raw, _, original_csv, _ = fixture(monkeypatch)
    source = io.BytesIO()
    with ZipFile(source, "w", compression=ZIP_STORED) as archive:
        archive.writestr(ui.ANDROID_MEMBER, raw)
        archive.writestr("Payload/Game.app/Data/resources.assets", raw)
        archive.writestr("unrelated", b"untouched")
    with ZipFile(io.BytesIO(source.getvalue())) as archive:
        replacements, report = ui.android_members(archive, original_csv)
        assert list(replacements) == [ui.ANDROID_MEMBER]
        output = io.BytesIO()
        with ZipFile(output, "w") as destination, destination.open("Payload/Game.app/Data/resources.assets", "w") as member:
            ios_report = ui.patch_ios_member(archive, "Payload/Game.app/Data/resources.assets", member, original_csv)
    with ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert sha(archive.read("Payload/Game.app/Data/resources.assets")) == ios_report["output_asset_sha256"]
    assert sha(replacements[ui.ANDROID_MEMBER]) == report["output_asset_sha256"]


def test_read_ui_inputs_are_bounded_regular_files_and_proofs_reject_duplicate_fields(monkeypatch, tmp_path):
    _, _, original_csv, _ = fixture(monkeypatch)
    path = tmp_path / "original.csv";path.write_bytes(original_csv)
    assert ui.read_ui_csv(path) == original_csv
    link = tmp_path / "linked.csv";link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"):
        ui.read_ui_csv(link)
    proof = tmp_path / "proof.json";proof.write_text('{"language":"ko","language":"en"}')
    with pytest.raises(ValueError, match="Duplicate"):
        ui.read_ui_proof(proof, original_csv, "ko")


def test_japanese_ui_is_byte_identical_to_the_original_encrypted_asset(monkeypatch):
    raw, _, original_csv, _ = fixture(monkeypatch)
    output = ForwardDestination()
    report = ui.patch_asset_stream(BoundedSource(raw), output, original_csv, "android")
    assert bytes(output.raw) == raw
    assert report["ui_asset_byte_identical"] and report["physical_size_delta"] == 0
    assert report["shifted_object_offsets"] == 0
    assert report["input_asset_sha256"] == report["output_asset_sha256"]
    assert report["input_object_sha256"] == report["output_object_sha256"]
    assert report["input_script_sha256"] == report["output_script_sha256"]


def test_package_locale_inputs_do_not_silently_fall_back(monkeypatch, tmp_path):
    _, _, original_csv, _ = fixture(monkeypatch)
    assert ui.load_package_inputs() == (None, None)
    for language, csv_file, proof_file in (("ko", None, None), ("en", None, None), ("ja", None, tmp_path/"proof.json")):
        with pytest.raises(ValueError, match="requires CSV"):
            ui.load_package_inputs(language, csv_file, proof_file)
    path = tmp_path/"ja.csv";path.write_bytes(original_csv)
    value, proof = ui.load_package_inputs("ja", path)
    assert value == original_csv and proof["language"] == "ja"


def test_korean_package_inputs_bind_curated_output_and_retain_the_prepared_proof(monkeypatch, tmp_path):
    original = csv_bytes().replace(b'key-0,', b'photo.materialNotEnough,', 1)
    translated = original.replace(b'photo.materialNotEnough,"original"',
        'photo.materialNotEnough,"{0}[이/가] 부족합니다"'.encode(), 1)
    keys = ['photo.materialNotEnough', *[f'key-{i}' for i in range(1, 4199)]]
    monkeypatch.setattr(ui, 'ORIGINAL_CSV_SHA256', sha(original))
    monkeypatch.setattr(ui, 'ORIGINAL_KEYS_SHA256', sha(b'\0'.join(k.encode() for k in sorted(keys))))
    prepared = {'language': 'ko', 'input_sha256': sha(original), 'output_sha256': sha(translated),
                'bytes': len(translated), 'source_ui_keys': 4199, 'changed_keys_count': 1}
    path, evidence = tmp_path / 'ko.csv', tmp_path / 'proof.json'
    path.write_bytes(translated); evidence.write_text(json.dumps(prepared))
    value, proof = ui.load_package_inputs('ko', path, evidence)
    assert '{0} 부족'.encode() in value and '[이/가]'.encode() not in value
    assert proof['prepared_input_proof'] == prepared
    assert proof['curated_korean_ui']['changed_keys'] == ['photo.materialNotEnough']
    assert proof['output_sha256'] == sha(value) != prepared['output_sha256']
    assert proof['bytes'] == len(value) and ui.validate_csv(value)['ui_keys'] == 4199
    assert ui.validate_proof(proof, value, 'ko') == proof
    evidence.write_text(json.dumps({**prepared, 'output_sha256': '0' * 64}))
    with pytest.raises(ValueError, match='does not bind'):
        ui.load_package_inputs('ko', path, evidence)
