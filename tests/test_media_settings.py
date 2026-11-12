import json

import pytest

from idoly_local.media_settings import (DEFAULTS, MAX_BYTES, MAX_REVISION, MediaSettingsState,
                                        decode_settings, save_settings, validate_settings)


def encoded(**changes):
    return json.dumps(DEFAULTS | changes).encode()


def test_defaults_strict_file_and_invalid_reopen_preserve_last_valid(tmp_path):
    path = tmp_path / "client-media.json"
    settings = MediaSettingsState(path)
    assert settings.settings() == DEFAULTS and not path.exists()
    path.write_bytes(encoded(revision=7, hide_video_mv=True, mv_sort="title", outfit_sort="old"))
    expected = settings.settings()
    assert expected["revision"] == 7 and expected["hide_video_mv"]
    expected["revision"] = 0
    assert settings.settings()["revision"] == 7
    path.write_bytes(b"broken")
    assert settings.settings()["revision"] == 7
    assert settings.status()["invalid_settings_file"]
    assert MediaSettingsState(path).settings() == DEFAULTS
    assert path.read_bytes() == b"broken"


@pytest.mark.parametrize("changes", [{"schema": True}, {"schema": 2}, {"schema": 1.0},
    {"revision": True}, {"revision": -1}, {"revision": 1.0}, {"revision": MAX_REVISION + 1},
    {"hide_video_mv": 1}, {"hide_video_mv": "false"}, {"mv_sort": "original"},
    {"mv_sort": []}, {"outfit_sort": "newest"}, {"extra": "private"}])
def test_settings_reject_wrong_types_unknown_keys_and_unadvertised_options(changes):
    with pytest.raises(ValueError):
        decode_settings(encoded(**changes))


def test_bounded_json_rejects_duplicate_escaped_keys_and_trailing_input():
    for raw in [b"{}", b"[]", b"null", b"", encoded() + b"{}", b" " * (MAX_BYTES + 1),
                b"{\"schema\":1," + encoded()[1:], b"{\"\\u0073chema\":1," + encoded()[1:],
                encoded().replace(b'"revision": 0', b'"revision": NaN'), b"\xff"]:
        with pytest.raises(ValueError):
            decode_settings(raw)
    assert decode_settings(encoded(revision=MAX_REVISION))["revision"] == MAX_REVISION
    assert validate_settings(DEFAULTS) == DEFAULTS


def test_atomic_edits_monotonic_revision_and_no_account_files_changed(tmp_path):
    path = tmp_path / "client-media.json"
    ordinary, media = tmp_path / "state.db", tmp_path / "media-state.db"
    ordinary.write_bytes(b"original account")
    media.write_bytes(b"preserved media account")
    first = save_settings(path, DEFAULTS | {"hide_video_mv": True}, now_ms=100)
    assert first["revision"] == 100 and DEFAULTS["revision"] == 0
    second = save_settings(path, first | {"mv_sort": "old"}, now_ms=100)
    third = save_settings(path, second | {"outfit_sort": "title"}, now_ms=1)
    assert second["revision"] == 101 and third["revision"] == 102
    assert MediaSettingsState(path).settings() == third
    assert ordinary.read_bytes() == b"original account" and media.read_bytes() == b"preserved media account"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["client-media.json", "media-state.db", "state.db"]


def test_failed_atomic_replace_and_revision_exhaustion_keep_previous_bytes(tmp_path, monkeypatch):
    path = tmp_path / "client-media.json"
    save_settings(path, DEFAULTS, now_ms=100)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_settings(path, DEFAULTS | {"revision": MAX_REVISION}, now_ms=101)
    assert path.read_bytes() == before

    def fail(*args):
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr("idoly_local.media_settings.os.replace", fail)
    with pytest.raises(OSError):
        save_settings(path, DEFAULTS, now_ms=101)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["client-media.json"]


def test_nonregular_settings_do_not_read_other_files(tmp_path):
    account = tmp_path / "state.db"
    account.write_bytes(b"must remain private")
    path = tmp_path / "client-media.json"
    path.symlink_to(account)
    settings = MediaSettingsState(path)
    assert settings.settings() == DEFAULTS and settings.status()["invalid_settings_file"]
    assert account.read_bytes() == b"must remain private"
