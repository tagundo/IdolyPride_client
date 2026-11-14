from __future__ import annotations

import hashlib
import io
import struct

import pytest

from idoly_local import static_ui_assets as ui


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(*, source="センター", second=b"untranslated-object", script=(1, 7023), text_offset=88):
    text = source.encode()
    label = bytearray(88)
    struct.pack_into("<iq", label, 16, *script)
    label.extend(struct.pack("<i", len(text)) + text)
    label.extend(b"\0" * (-len(label) % 4))
    label.extend(b"unchanged-label-style")
    label = bytes(label)
    meta = bytearray(b"2022.3.57f1\0" + struct.pack("<iBi", 9, 0, 3))
    meta.extend(struct.pack("<iBh", 114, 0, 1) + bytes.fromhex(ui.SCRIPT_ID) + bytes.fromhex(ui.TYPE_HASH))
    meta.extend(struct.pack("<iBh", 213, 0, -1) + b"S" * 16)
    meta.extend(struct.pack("<iBh", 28, 0, -1) + b"T" * 16)
    count_offset = 48 + len(meta)
    meta.extend(struct.pack("<i", 3))
    meta.extend(b"\0" * (-(48 + len(meta)) % 4))
    table = 48 + len(meta)
    label_pad = -len(label) % 8
    second_pad = -len(second) % 8
    data = label + b"\0" * label_pad + second + b"\0" * second_pad + b"original-texture"
    records = [(1, 0, len(label), 0), (2, len(label) + label_pad, len(second), 1),
               (3, len(label) + label_pad + len(second) + second_pad, len(b"original-texture"), 2)]
    for record in records:
        meta.extend(struct.pack("<qQIi", *record))
    meta.extend(b"EXTERNALS-AND-OTHER-METADATA")
    metadata_size = len(meta)
    data_offset = (48 + len(meta) + 15) & ~15
    header = struct.pack(">4I", 0, 0, 22, 0) + b"\0" * 4 + struct.pack(">IQQQ", metadata_size, data_offset + len(data), data_offset, 0)
    metadata = header + meta + b"\0" * (data_offset - 48 - len(meta))
    raw = metadata + data
    profile = {"bytes": len(raw), "metadata_bytes": metadata_size, "data_offset": data_offset,
               "metadata_sha256": sha(metadata), "object_count": 3, "table_offset": table,
               "count_offset": count_offset, "sha256": sha(raw)}
    target = [1, 0, len(label), 0, sha(label), 0]
    return raw, profile, target, label, records


def output_objects(raw, profile, count=3):
    start = struct.unpack_from(">Q", raw, 32)[0]
    result = {}
    for index in range(count):
        path, relative, size, kind = struct.unpack_from("<qQIi", raw, profile["table_offset"] + 24 * index)
        result[path] = (raw[start + relative:start + relative + size], relative, kind)
    return result


def rewrite(raw, profile, target, source="センター", translated="센터", **kwargs):
    destination = io.BytesIO()
    report = ui._rewrite(io.BytesIO(raw), destination, profile, [target], [[source, translated, None]],
                         "android", "ko", **kwargs)
    return destination.getvalue(), report


def test_resize_changes_only_m_text_and_rebases_following_objects():
    raw, profile, target, label, records = fixture()
    result, report = rewrite(raw, profile, target, translated="화면 중앙의 센터")
    before, after = output_objects(raw, profile), output_objects(result, profile)
    text = "화면 중앙의 센터".encode()
    assert after[1][0][:88] == label[:88]
    assert struct.unpack_from("<i", after[1][0], 88)[0] == len(text)
    assert after[1][0][92:92 + len(text)] == text
    assert after[1][0].endswith(b"unchanged-label-style")
    assert before[2][0] == after[2][0]
    assert before[3][0] == after[3][0]
    assert after[2][1] > before[2][1] and after[2][1] % 8 == 0
    assert report["output_asset_sha256"] == sha(result)
    assert report["output_asset_bytes"] == len(result)
    assert report["changed_static_texts"] == 1
    assert b"EXTERNALS-AND-OTHER-METADATA" in result


def test_shorter_text_keeps_following_payload_alignment():
    raw, profile, target, label, records = fixture()
    result, report = rewrite(raw, profile, target)
    after = output_objects(result, profile)
    assert after[1][0][92:98] == "센터".encode()
    assert after[2][1] == records[1][1]
    assert report["output_asset_bytes"] == len(raw)


@pytest.mark.parametrize("language", ["ja", "en"])
def test_missing_or_original_language_preserves_whole_asset(language):
    raw, profile, target, label, records = fixture()
    out = io.BytesIO()
    report = ui._rewrite(io.BytesIO(raw), out, profile, [target], [["センター", "센터", None]],
                         "android", language)
    assert out.getvalue() == raw
    assert report["changed_static_texts"] == 0


def test_wrong_complete_asset_hash_writes_nothing():
    raw, profile, target, label, records = fixture()
    raw = raw[:-1] + bytes([raw[-1] ^ 1])
    out = io.BytesIO()
    with pytest.raises(ValueError, match="declared composed input"):
        ui._rewrite(io.BytesIO(raw), out, profile, [target], [["センター", "센터", None]], "android", "ko")
    assert out.getvalue() == b""


@pytest.mark.parametrize("change", ["substring", "wrong_script", "wrong_type", "wrong_object"])
def test_rejects_unrelated_strings_and_changed_object_identity(change):
    raw, profile, target, label, records = fixture(script=(1, 123) if change == "wrong_script" else (1, 7023))
    source = "セン" if change == "substring" else "センター"
    if change == "wrong_type":
        target[3] = 1
    elif change == "wrong_object":
        target[4] = "0" * 64
    with pytest.raises(ValueError):
        rewrite(raw, profile, target, source=source)


def test_adds_private_texture_without_changing_existing_texture_or_metadata_tail():
    raw, profile, target, label, records = fixture(second=b"original-sprite")
    out = io.BytesIO()
    report = ui._rewrite(io.BytesIO(raw), out, profile, [target], [["センター", "센터", None]],
                         "android", "ko", extra_replacements={2: {"input_sha256": sha(b"original-sprite"),
                         "raw": b"localized-sprite"}}, append_objects=[{"path_id": 4, "type_id": 2,
                         "raw": b"private-localized-texture"}])
    result = out.getvalue()
    before, after = output_objects(raw, profile), output_objects(result, profile, 4)
    assert after[2][0] == b"localized-sprite"
    assert after[3][0] == before[3][0]
    assert after[4][0] == b"private-localized-texture"
    assert struct.unpack_from("<i", result, profile["count_offset"])[0] == 4
    assert struct.unpack_from(">I", result, 20)[0] == profile["metadata_bytes"] + 24
    assert struct.unpack_from(">Q", result, 32)[0] == profile["data_offset"] + 32
    assert report["output_asset_bytes"] == len(result)
    assert report["output_asset_sha256"] == sha(result)
    assert b"EXTERNALS-AND-OTHER-METADATA" in result


def test_rejects_image_patch_into_a_text_object():
    raw, profile, target, label, records = fixture()
    with pytest.raises(ValueError, match="overlap"):
        rewrite(raw, profile, target, extra_replacements={1: {"input_sha256": sha(label), "raw": b"bad"}})


def test_ios_uses_its_own_pinned_solistext_script_reference():
    raw, profile, target, label, records = fixture(script=(1, 7002))
    out = io.BytesIO()
    report = ui._rewrite(io.BytesIO(raw), out, profile, [target], [["センター", "센터", None]],
                         "ios", "ko")
    assert report["changed_static_texts"] == 1
    assert output_objects(out.getvalue(), profile)[1][0][92:98] == "센터".encode()
    wrong, wrong_profile, wrong_target, _, _ = fixture(script=(1, 7023))
    with pytest.raises(ValueError, match="MonoScript"):
        ui._rewrite(io.BytesIO(wrong), io.BytesIO(), wrong_profile, [wrong_target],
                    [["センター", "센터", None]], "ios", "ko")


def test_japanese_combined_csv_keeps_original_encoded_script(monkeypatch):
    from idoly_local import ui_assets
    encoded = b"original encoded Japanese CSV script"
    raw, profile, target, label, records = fixture(script=(1, 7002), second=encoded)
    monkeypatch.setitem(ui_assets.ASSETS, "ios", {"target_path_id": 2, "target_object_sha256": sha(encoded)})
    monkeypatch.setattr(ui_assets, "validate_proof", lambda proof, csv, language: {"language": language})
    def unexpected(*args):
        raise AssertionError("Japanese CSV must retain original encoding")
    monkeypatch.setattr(ui_assets, "_replacement", unexpected)
    out = io.BytesIO()
    ui._rewrite(io.BytesIO(raw), out, profile, [target], [["センター", "센터", None]],
                "ios", "ja", csv_bytes=b"KEY,Japanese\n")
    assert out.getvalue() == raw


def test_profile_pins_exact_source_values_and_types_for_both_platforms():
    profile = ui._profile()
    assert len(profile["android"]) == 537
    assert sum(len(asset["targets"]) for asset in profile["android"]) == 1964
    assert len(profile["ios"][0]["targets"]) == 1964
    texts = {row[0]: row[1] for row in profile["texts"]}
    assert texts["読み込み中"] == "불러오는중"
    assert texts["センター"] == "센터"
    assert texts["ライブ撮影"] == "라이브 촬영"
    assert texts["衣装"] == "의상"
    assert texts["縦画面"] == "세로 뷰"
    assert texts["横画面"] == "가로 뷰"
    # These upstream values are Localify particle-resolver instructions, not
    # final display strings. Preserve the original until full context exists.
    assert texts["で"] is None
    assert texts["を"] is None
