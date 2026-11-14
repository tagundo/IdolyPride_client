"""Curated CSV phrases require exact source values and preserve other data."""
from __future__ import annotations

import csv
import hashlib
import io
import json

import pytest

from idoly_local import ui_text_finishes as ui


def encoded(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["KEY", "Japanese"])
    writer.writerows(rows)
    return stream.getvalue().encode()


def decoded(raw):
    return list(csv.reader(io.StringIO(raw.decode(), newline=""), skipinitialspace=True))


def test_exact_key_and_upstream_value_are_both_required_and_custom_values_survive():
    raw = encoded([
        ["photo.materialNotEnough", "{0}[이/가] 부족합니다", "other-column"],
        ["card.detail.action.itemNotEnough", "사용자 지정: {0}"],
        ["unrelated.key", "{0}[이/가] 부족합니다"],
        ["unrelated.japanese", "日本語"],
    ])
    result, report = ui.apply_csv(raw)
    rows = decoded(result)
    assert rows[0] == ["KEY", "Japanese"]
    assert rows[1] == ["photo.materialNotEnough", "{0} 부족", "other-column"]
    assert rows[2:] == decoded(raw)[2:]
    assert report["changed_keys"] == ["photo.materialNotEnough"]
    assert report["changed_key_count"] == 1
    assert {"key": "card.detail.action.itemNotEnough", "reason": "custom_or_other_language_value"} in report["skipped_keys"]
    assert "missing_keys" not in report
    assert report["runtime_particle_resolver_added"] is False


@pytest.mark.parametrize("line", ["\n", "\\n"])
def test_stock_newline_escape_matches_without_changing_placeholders_or_extra_columns(line):
    raw = encoded([
        ["error.dialog.update.app.message", "새로운 버전이 있습니다." + line + "{0}[으/로] 업데이트 해 주세요.", "tail"],
        ["deck.copy.confirm.description", "[{0}]를 [{1}][으/로] " + line + "덮어쓰기하시겠습니까?"],
    ])
    result, report = ui.apply_csv(raw)
    assert decoded(result)[1] == ["error.dialog.update.app.message", "새로운 버전이 있습니다.\\n{0}에서 업데이트해 주세요.", "tail"]
    assert decoded(result)[2] == ["deck.copy.confirm.description", "[{0}] 내용으로 [{1}]에\\n덮어쓰기하시겠습니까?"]
    assert report["changed_key_count"] == 2


def test_all_reviewed_phrases_are_final_and_second_application_is_byte_identical():
    profile = json.loads(ui.PROFILE_PATH.read_bytes())
    raw = encoded([[row["key"], row["expected_ko"].replace("\n", "\\n")] for row in profile["entries"]])
    result, first = ui.apply_csv(raw)
    second, report = ui.apply_csv(result)
    assert len(profile["entries"]) == first["changed_key_count"] == 33
    assert second == result and report["changed_keys"] == []
    assert len(report["already_final_keys"]) == 33 and report["skipped_keys"] == []
    assert first["source_profile_sha256"] == hashlib.sha256(ui.PROFILE_PATH.read_bytes()).hexdigest()
    assert first["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first["output_sha256"] == report["input_sha256"] == report["output_sha256"]
    rows = dict((row[0], row[1]) for row in decoded(result)[1:])
    assert rows["marathon.boxGacha.resetSheetDescription.limitReset"] == "{0}: 초기화 가능 횟수 {1}회"
    assert rows["message.picture.sheet.title"] == "{0}의 이미지"
    assert not any(ui._PARTICLE.search(value) for value in rows.values())


def test_unknown_language_or_custom_whitespace_is_not_rewritten():
    raw = encoded([
        ["photo.materialNotEnough", "{0}が足りません"],
        ["card.detail.action.itemNotEnough", "{0}[이/가] 부족합니다 "],
    ])
    result, report = ui.apply_csv(raw)
    assert result == raw and report["changed_keys"] == []
    assert report["already_final_keys"] == []


@pytest.mark.parametrize("raw", [
    b"\xef\xbb\xbfKEY,Japanese\nkey,value\n",
    b"KEY,Korean\nkey,value\n",
    b"KEY,Japanese\nkey,one\nkey,two\n",
    b"KEY,Japanese\nkey\n",
    b"KEY,Japanese\nkey,\0\n",
    b"KEY,Japanese\nkey,\xff\n",
])
def test_malformed_csv_is_rejected(raw):
    with pytest.raises(ValueError):
        ui.apply_csv(raw)


def test_changed_profile_is_rejected_before_translation(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_bytes(ui.PROFILE_PATH.read_bytes() + b" ")
    monkeypatch.setattr(ui, "PROFILE_PATH", profile)
    with pytest.raises(ValueError, match="reviewed source"):
        ui.apply_csv(encoded([["photo.materialNotEnough", "{0}[이/가] 부족합니다"]]))
