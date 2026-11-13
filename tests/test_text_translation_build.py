import hashlib
import json
from zipfile import ZipFile

import pytest

from idoly_local.text_translation_build import compile_adv, compile_catalog

SOURCE = {"repository": "https://example.invalid/translations", "revision": "a" * 40}


def test_preparation_keeps_ui_ids_separate_from_generic_japanese_and_timed_phone_data(tmp_path):
    source = tmp_path / "source"; source.mkdir(); generic = source / "genericTrans"; generic.mkdir()
    (source / "localization.json").write_text(json.dumps({"yes": "네", "untranslated": ""}))
    (generic / "generic.json").write_text(json.dumps({"direct": "직접", "group": {"設定": "설정", "ambiguous": "one"}, "other": {"ambiguous": "two"}}))
    (generic / "generic.split.json").write_text(json.dumps({"[__split__]位": "[__split__]위"}))
    (source / "phoneSubtitles.json").write_text(json.dumps({"clip-id": [
        {"line": 2, "time": 1.5, "text": "두 번째\\n줄"}, {"line": 1, "time": 0, "text": "첫 번째"}]}))
    output = tmp_path / "output"
    report = compile_catalog(source, output, language="ko", source=SOURCE)
    data = json.loads((output / "text.json").read_text())
    assert data["ui"] == {"yes": "네"} and data["generic"] == {"direct": "직접", "設定": "설정"}
    assert data["split"] == {"[__split__]位": "[__split__]위"}
    assert data["phone"]["clip-id"] == [{"milliseconds": 0, "text": "첫 번째"}, {"milliseconds": 1500, "text": "두 번째\n줄"}]
    assert report["coverage"]["conflicting_generic_strings"] == 1
    assert report["pack"]["sha256"] == hashlib.sha256((output / "text.json").read_bytes()).hexdigest()


def test_absent_translations_and_japanese_never_claim_translated_coverage(tmp_path):
    for locale in ("ja", "ko", "en"):
        report = compile_catalog(tmp_path, tmp_path / locale, language=locale, source=SOURCE)
        assert not any(report["coverage"].values()) and report["fallback"] == "original_japanese"


@pytest.mark.parametrize("line", [{}, None, {"time": True, "line": 1}, {"time": -1, "line": 1}, {"time": float("nan"), "line": 1}])
def test_invalid_subtitle_timing_fails_preparation(tmp_path, line):
    (tmp_path / "phoneSubtitles.json").write_text(json.dumps({"clip": [line]}))
    with pytest.raises(ValueError, match="subtitle"):
        compile_catalog(tmp_path, tmp_path / "output", language="ko", source=SOURCE)


def test_indexed_adv_archive_is_deterministic_and_keeps_complete_utf8_scripts(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    script = "[title title=번역]\n원래 명령은 그대로\n"
    (source / "adv_bond_ai_01_01.txt").write_text(script)
    for directory in ("one", "two"):
        report = compile_adv(source, tmp_path / directory, source=SOURCE)
        assert report["files"]["adv_bond_ai_01_01.txt"]["sha256"] == hashlib.sha256(script.encode()).hexdigest()
    assert (tmp_path / "one/adv.zip").read_bytes() == (tmp_path / "two/adv.zip").read_bytes()
    with ZipFile(tmp_path / "one/adv.zip") as archive:
        assert archive.read("adv_bond_ai_01_01.txt").decode() == script
