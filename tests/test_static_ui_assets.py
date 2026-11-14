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


def image_fixture(objects):
    """Give the small fixture an arbitrary original image-object inventory."""
    original, base, _, _, _ = fixture(script=(1, 7002))
    metadata = bytearray(original[48:base["table_offset"]])
    struct.pack_into("<i", metadata, base["count_offset"] - 48, len(objects))
    data = bytearray()
    for path, value, type_id in objects:
        metadata.extend(struct.pack("<qQIi", path, len(data), len(value), type_id))
        data.extend(value)
        data.extend(b"\0" * (-len(data) % 8))
    metadata.extend(original[base["table_offset"] + 24 * 3:48 + base["metadata_bytes"]])
    metadata_size = len(metadata)
    data_offset = (48 + metadata_size + 15) & ~15
    header = (struct.pack(">4I", 0, 0, 22, 0) + b"\0" * 4
              + struct.pack(">IQQQ", metadata_size, data_offset + len(data), data_offset, 0))
    metadata = header + metadata + b"\0" * (data_offset - 48 - metadata_size)
    raw = metadata + data
    profile = {**base, "bytes": len(raw), "metadata_bytes": metadata_size,
               "data_offset": data_offset, "metadata_sha256": sha(metadata),
               "object_count": len(objects), "sha256": sha(raw)}
    return raw, profile


def rewrite_images(raw, profile, **kwargs):
    destination = io.BytesIO()
    report = ui._rewrite(io.BytesIO(raw), destination, profile, [], [], "ios", "ko", **kwargs)
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


def test_composes_all_ios_sprites_direct_textures_and_large_private_textures():
    objects = [(path, f"original-sprite-{path}".encode(), 1) for path in range(1, 140)]
    objects += [(path, f"original-texture-{path}".encode(), 2) for path in range(140, 154)]
    objects += [(path, f"unselected-object-{path}".encode(), 1 + path % 2)
                for path in range(154, 181)]
    raw, profile = image_fixture(objects)
    replacements = {path: {"input_sha256": sha(value), "raw": b"localized-" + value}
                    for path, value, _ in objects if path < 154}
    appended = [{"path_id": 181 + index, "type_id": 2,
                 "raw": b"R" * (ui.MAX_OBJECT + 1) if index == 0
                        else f"private-RGBA-texture-{index}".encode()}
                for index in range(139)]
    result, report = rewrite_images(raw, profile, extra_replacements=replacements,
                                    append_objects=appended)
    after = output_objects(result, profile, len(objects) + 139)
    assert report["image_object_replacements"] == 139 + 14
    assert report["appended_texture_objects"] == 139
    assert report["output_object_count"] == len(objects) + 139
    assert report["output_asset_sha256"] == sha(result)
    assert report["output_asset_bytes"] == len(result)
    for path, original, type_id in objects:
        expected = replacements[path]["raw"] if path in replacements else original
        assert after[path][0] == expected
        assert after[path][2] == type_id
        assert after[path][1] % 8 == 0
    for item in appended:
        assert after[item["path_id"]][0] == item["raw"]
        assert after[item["path_id"]][2] == 2
        assert after[item["path_id"]][1] % 8 == 0
    assert b"EXTERNALS-AND-OTHER-METADATA" in result


def test_accepts_exact_image_object_count_bounds_together():
    objects = [(path, f"sprite-{path}".encode(), 1) for path in range(1, 257)]
    objects.append((257, b"unselected-original-texture", 2))
    raw, profile = image_fixture(objects)
    replacements = {path: {"input_sha256": sha(value), "raw": b"localized-" + value}
                    for path, value, _ in objects[:-1]}
    appended = [{"path_id": 258 + index, "type_id": 2, "raw": b"new-texture"}
                for index in range(256)]
    result, report = rewrite_images(raw, profile, extra_replacements=replacements,
                                    append_objects=appended)
    assert report["image_object_replacements"] == report["appended_texture_objects"] == 256
    after = output_objects(result, profile, 257 + 256)
    assert after[257][0] == objects[-1][1]
    assert len(after) == 257 + 256


@pytest.mark.parametrize("kind", ["replacement", "append"])
def test_rejects_image_object_count_257_before_writing(kind):
    raw, profile, _, _, _ = fixture()
    kwargs = ({"extra_replacements": {path: {"input_sha256": "0" * 64, "raw": b"image"}
                                      for path in range(1, 258)}} if kind == "replacement"
              else {"append_objects": [{"path_id": 4 + index, "type_id": 2, "raw": b"image"}
                                        for index in range(257)]})
    out = io.BytesIO()
    with pytest.raises(ValueError, match="bound"):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko", **kwargs)
    assert out.getvalue() == b""


@pytest.mark.parametrize("path", [2, 3])
def test_sprite_and_existing_texture_require_the_exact_original_sha(path):
    raw, profile, _, _, _ = fixture()
    out = io.BytesIO()
    with pytest.raises(ValueError, match="exact original"):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko",
                    extra_replacements={path: {"input_sha256": "0" * 64, "raw": b"image"}})
    assert out.getvalue() == b""


@pytest.mark.parametrize("kind", ["replace_text", "append_sprite"])
def test_image_changes_reject_unrelated_existing_or_appended_types(kind):
    raw, profile, _, label, _ = fixture()
    kwargs = ({"extra_replacements": {1: {"input_sha256": sha(label), "raw": b"image"}}}
              if kind == "replace_text" else
              {"append_objects": [{"path_id": 4, "type_id": 1, "raw": b"image"}]})
    out = io.BytesIO()
    with pytest.raises(ValueError):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko", **kwargs)
    assert out.getvalue() == b""


def test_sprite_replacement_retains_the_strict_one_MiB_bound():
    raw, profile, _, _, _ = fixture()
    original = output_objects(raw, profile)[2][0]
    out = io.BytesIO()
    with pytest.raises(ValueError, match="original"):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko",
                    extra_replacements={2: {"input_sha256": sha(original),
                                            "raw": b"S" * (ui.MAX_OBJECT + 1)}})
    assert out.getvalue() == b""


@pytest.mark.parametrize("kind", ["existing", "append"])
def test_texture_output_uses_the_shared_texture_size_bound(monkeypatch, kind):
    from idoly_local import static_ui_images
    # Exercise the exact configured boundary without allocating a 17MiB fixture.
    monkeypatch.setattr(static_ui_images, "MAX_TEXTURE_BYTES", 32)
    raw, profile, _, _, _ = fixture()
    original = output_objects(raw, profile)[3][0]
    def kwargs(value):
        return ({"extra_replacements": {3: {"input_sha256": sha(original), "raw": value}}}
                if kind == "existing" else
                {"append_objects": [{"path_id": 4, "type_id": 2, "raw": value}]})
    result, _ = rewrite_images(raw, profile, **kwargs(b"T" * 32))
    assert output_objects(result, profile, 3 if kind == "existing" else 4)[
        3 if kind == "existing" else 4][0] == b"T" * 32
    out = io.BytesIO()
    with pytest.raises(ValueError):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko", **kwargs(b"T" * 33))
    assert out.getvalue() == b""


def test_original_image_input_retains_the_strict_one_MiB_bound():
    original = b"S" * (ui.MAX_OBJECT + 1)
    raw, profile, _, _, _ = fixture(second=original)
    out = io.BytesIO()
    with pytest.raises(ValueError, match="target overlaps"):
        ui._rewrite(io.BytesIO(raw), out, profile, [], [], "ios", "ko",
                    extra_replacements={2: {"input_sha256": sha(original), "raw": b"image"}})
    assert out.getvalue() == b""


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
