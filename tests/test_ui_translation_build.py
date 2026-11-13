import hashlib
import struct

import pytest

from idoly_local.client_patch import literal_rows
from idoly_local.ui_translation_build import translate_localization_csv, translate_metadata_literals


def fixture():
    strings = ["設定".encode(), "comparison-operand".encode(), "設定".encode()]
    pool = b"".join(strings)
    start = 256 + len(strings) * 8
    padding = b"\0" * (-(start + len(pool)) % 8)
    tail = b"OTHER TABLES ARE IMMUTABLE"
    header = [0] * 64
    header[:8] = [0xFAB11BAF, 31, 256, len(strings) * 8, start, len(pool), start + len(pool) + len(padding), len(tail)]
    rows, offset = [], 0
    for value in strings:
        rows.append(struct.pack("<II", len(value), offset)); offset += len(value)
    return struct.pack("<64I", *header) + b"".join(rows) + pool + padding + tail


def test_csv_preserves_bom_comments_line_endings_values_commas_and_missing_japanese():
    raw = "\ufeff//comment\r\nyes,はい\r\nmissing,日本語\ncompound,with,commas".encode()
    result, report = translate_localization_csv(raw, {"yes": "네", "compound": "쉼표,가능", "unused": "무시"})
    assert result.decode() == '\ufeff//comment\r\n"yes","네"\r\nmissing,日本語\n"compound","쉼표,가능","commas"'
    assert report["changed_keys"] == ["yes", "compound"] and report["missing_keys"] == 1


def test_metadata_replaces_only_audited_display_literal_and_preserves_all_other_sections():
    raw = fixture(); old_header, old_rows = literal_rows(raw)
    result, report = translate_metadata_literals(raw, {"設定": "설정", "comparison-operand": "DO NOT CHANGE"},
        allowed_indexes=[0], expected_sha256=hashlib.sha256(raw).hexdigest())
    new_header, rows = literal_rows(result)
    assert rows[0][3] == "설정".encode()
    assert [row[3] for row in rows[1:]] == [row[3] for row in old_rows[1:]]
    assert result[new_header[6]:] == raw[old_header[6]:]
    assert new_header[6] % 8 == old_header[6] % 8
    assert report["changed_indexes"] == [0] and report["inserted_bytes"] % 8 == 0
    assert raw == fixture()


def test_unknown_translations_preserve_exact_original_bytes():
    raw = fixture()
    result, report = translate_metadata_literals(raw, {}, allowed_indexes=[0], expected_sha256=hashlib.sha256(raw).hexdigest())
    assert result == raw and report["missing_indexes"] == [0]


@pytest.mark.parametrize("indexes", [[900], [-1], [True], [0, 0], None])
def test_unreviewed_or_invalid_literal_selection_is_rejected(indexes):
    raw = fixture()
    with pytest.raises(ValueError):
        translate_metadata_literals(raw, {"設定": "설정"}, allowed_indexes=indexes, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_csv_rejects_nul():
    with pytest.raises(ValueError):
        translate_localization_csv(b"yes,yes\n", {"yes": "bad\0value"})


def test_csv_quotes_whitespace_and_preserves_multiline_fallback_and_header():
    raw = b'KEY,Japanese\n// comment\nunknown,"line1\nline2,comma"\nknown,source\n'
    translated, report = translate_localization_csv(raw, {"known": '  leading\tand "quote"\nsecond line'})
    assert translated.startswith(b'KEY,Japanese\n// comment\nunknown,"line1\nline2,comma"\n')
    assert b'"known","  leading\tand ""quote""\\nsecond line"\n' in translated
    assert report["changed_keys"] == ["known"] and report["missing_keys"] == 1
