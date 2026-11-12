import json

import pytest

from idoly_local.language_settings import LanguageSettingsState, select_language_tag, validate_settings


def test_default_and_valid_settings_never_write_files(tmp_path):
    path = tmp_path / "client-language.json"
    state = LanguageSettingsState(path)
    assert state.settings() == {"schema": 1, "language": "ja"}
    assert not path.exists()
    for language in ("ko", "en", "ja"):
        path.write_text(json.dumps({"schema": 1, "language": language}))
        assert state.settings()["language"] == language
    assert not state.status()["invalid_settings_file"]


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"\xff", b" "*8193,
    b'{"schema":true,"language":"ko"}', b'{"schema":1,"language":"fr"}',
    b'{"schema":1,"language":"ko","language":"en"}',
    b'{"schema":1,"language":"ko","path":"state.db"}',
    '{"schema":1,"language":"ja"}'.encode("utf-16")])
def test_invalid_file_preserves_last_valid_selection(tmp_path, raw):
    path = tmp_path / "client-language.json"
    path.write_text('{"schema":1,"language":"ko"}')
    state = LanguageSettingsState(path)
    assert state.settings()["language"] == "ko"
    path.write_bytes(raw)
    assert state.status() == {"settings": {"schema": 1, "language": "ko"}, "invalid_settings_file": True}
    assert path.read_bytes() == raw


@pytest.mark.parametrize("kind", ["master-tag.json", "media-master-tag.json"])
def test_selector_preserves_japanese_and_selects_prebuilt_same_mode_only(tmp_path, kind):
    base = tmp_path / kind
    base.write_text('original')
    assert select_language_tag(base, "ja") == base
    with pytest.raises(ValueError, match="missing"):
        select_language_tag(base, "ko")
    translated = tmp_path / "languages/ko" / kind
    translated.parent.mkdir(parents=True)
    translated.write_text('translated')
    assert select_language_tag(base, "ko") == translated
    assert base.read_text() == 'original'
    translated.unlink()
    translated.symlink_to(base)
    with pytest.raises(ValueError, match="missing"):
        select_language_tag(base, "ko")


@pytest.mark.parametrize("locale", [None, True, "../en", "KO", "ja?file=state.db"])
def test_selector_never_uses_arbitrary_locale_paths(tmp_path, locale):
    with pytest.raises(ValueError):
        select_language_tag(tmp_path / "master-tag.json", locale)


def test_unknown_tag_and_settings_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        select_language_tag(tmp_path / "state.db", "ko")
    with pytest.raises(ValueError):
        validate_settings({"schema": 1, "language": ["en"]})
