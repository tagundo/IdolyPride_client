import importlib.util
from pathlib import Path
import plistlib
import sqlite3
from contextlib import closing
from zipfile import ZipFile

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools/export_playcover_auth.py"
SPEC = importlib.util.spec_from_file_location("playcover_export", SOURCE)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)
APP_ID = "1:123456:ios:aabbccdd"
BUNDLE = exporter.BUNDLES[0]
SECRET = "private-token-must-never-be-printed"


def archive_blob():
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                          "$top": {"root": plistlib.UID(1)},
                          "$objects": ["$null", {"accessToken": SECRET}]}, fmt=plistlib.FMT_BINARY)


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    home = tmp_path / "mac-home"
    settings, database = exporter._paths(BUNDLE, home)
    settings.parent.mkdir(parents=True)
    settings.write_bytes(plistlib.dumps({"playChain": True, "playChainDebugging": False}))
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE genp (agrp TEXT, acct TEXT, svce TEXT, v_Data BLOB)')
        connection.execute('INSERT INTO genp VALUES (?,?,?,?)', (
            "fixture-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, archive_blob(),
        ))
        connection.execute('INSERT INTO genp VALUES (?,?,?,?)', (
            "unrelated", "other-account", "firebase_auth_unrelated", SECRET.encode(),
        ))
        connection.commit()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home, settings, database


def test_default_diagnostic_reports_only_presence_flags_and_schema(mac_home, capsys):
    _, settings, database = mac_home
    before = settings.read_bytes(), database.read_bytes()
    assert exporter.main([]) == 0
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert "fixture-group" not in output.out
    assert APP_ID not in output.out
    assert '"schema": "recognized"' in output.out
    assert exporter.BUNDLES[1] in output.out
    assert before == (settings.read_bytes(), database.read_bytes())


def test_export_scopes_one_archive_and_writes_private_bytes_without_input_changes(mac_home, tmp_path, capsys):
    _, settings, database = mac_home
    output = tmp_path / "private/firebase-user.archive"
    before = settings.read_bytes(), database.read_bytes()
    assert exporter.main(["--bundle", BUNDLE, "--google-app-id", APP_ID, "--output", str(output)]) == 0
    assert output.read_bytes() == archive_blob()
    assert output.stat().st_mode & 0o777 == 0o600
    messages = capsys.readouterr()
    assert SECRET not in messages.out + messages.err
    assert before == (settings.read_bytes(), database.read_bytes())


def test_read_only_connection_cannot_modify_source(mac_home):
    _, _, database = mac_home
    with closing(exporter._connect(database)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM genp")


@pytest.mark.parametrize("flag", [False, None, 1, "true"])
def test_non_playchain_export_is_blocked_without_output(mac_home, tmp_path, capsys, flag):
    _, settings, _ = mac_home
    settings.write_bytes(plistlib.dumps({"playChain": flag} if flag is not None else {}))
    output = tmp_path / "private/firebase-user.archive"
    assert exporter.main(["--bundle", BUNDLE, "--output", str(output)]) == 1
    messages = capsys.readouterr()
    assert "in-process export is required" in messages.err
    assert SECRET not in messages.out + messages.err
    assert not output.exists()


def test_ambiguous_scoped_rows_fail_and_optional_google_app_id_resolves(mac_home, tmp_path):
    home, _, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO genp VALUES (?,?,?,?)", (
            "other-group", exporter.ACCOUNTS[0], "firebase_auth_1:999:ios:ffff", archive_blob(),
        ))
        connection.commit()
    output = tmp_path / "private/archive"
    with pytest.raises(exporter.ExportError, match="Multiple Firebase archives"):
        exporter.export_archive(BUNDLE, output, home)
    assert not output.exists()
    exporter.export_archive(BUNDLE, output, home, APP_ID)
    assert output.read_bytes() == archive_blob()


def test_ipa_derives_only_public_google_app_id(mac_home, tmp_path, capsys):
    ipa = tmp_path / "game.ipa"
    with ZipFile(ipa, "w") as archive:
        config = plistlib.dumps({"GOOGLE_APP_ID": APP_ID, "API_KEY": "public-config-unused"})
        archive.writestr("Payload/Game.app/GoogleService-Info.plist", config)
        archive.writestr("Payload/Game.app/Frameworks/UnityFramework.framework/GoogleService-Info.plist", config)
    output = tmp_path / "private/archive"
    assert exporter.main(["--bundle", BUNDLE, "--ipa", str(ipa), "--output", str(output)]) == 0
    messages = capsys.readouterr()
    assert SECRET not in messages.out + messages.err
    assert "public-config-unused" not in messages.out + messages.err


def test_schema_and_blob_validation_fail_without_dumping_values(mac_home, tmp_path, capsys):
    _, _, database = mac_home
    output = tmp_path / "private/archive"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE genp SET v_Data=?", (SECRET.encode(),))
        connection.commit()
    assert exporter.main(["--bundle", BUNDLE, "--output", str(output)]) == 1
    messages = capsys.readouterr()
    assert SECRET not in messages.out + messages.err
    assert not output.exists()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("ALTER TABLE genp RENAME COLUMN v_Data TO wrong")
        connection.commit()
    assert exporter.main(["--bundle", BUNDLE, "--output", str(output)]) == 1
    assert "Unrecognized PlayChain schema" in capsys.readouterr().err


def test_export_never_overwrites_existing_archive(mac_home, tmp_path):
    home, _, _ = mac_home
    output = tmp_path / "existing.archive"
    output.write_bytes(b"preserve me")
    with pytest.raises(exporter.ExportError, match="Output already exists"):
        exporter.export_archive(BUNDLE, output, home, APP_ID)
    assert output.read_bytes() == b"preserve me"


def test_export_requires_explicit_bundle_and_does_not_create_output(tmp_path):
    output = tmp_path / "archive"
    with pytest.raises(SystemExit) as failure:
        exporter.main(["--output", str(output)])
    assert failure.value.code == 2
    assert not output.exists()
