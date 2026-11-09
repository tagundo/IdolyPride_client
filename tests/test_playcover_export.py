import importlib.util
from pathlib import Path
import hashlib
import json
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


def archive_blob(token=SECRET):
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                          "$top": {"root": plistlib.UID(1)},
                          "$objects": ["$null", {"accessToken": token}]}, fmt=plistlib.FMT_BINARY)


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
            "other-group", exporter.ACCOUNTS[0], "firebase_auth_1:999:ios:ffff", archive_blob("different-private-token"),
        ))
        connection.commit()
    output = tmp_path / "private/archive"
    with pytest.raises(exporter.ExportError, match="Multiple distinct Firebase archives"):
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


def test_identical_archive_bytes_across_rows_groups_and_account_kinds_export_once(mac_home, tmp_path):
    home, settings, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany("INSERT INTO genp VALUES (?,?,?,?)", [
            ("second-private-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, archive_blob()),
            ("third-private-group", exporter.ACCOUNTS[1], "firebase_auth_" + APP_ID, archive_blob()),
        ])
        connection.commit()
    before = settings.read_bytes(), database.read_bytes()
    output = tmp_path / "private/user.archive"
    exporter.export_archive(BUNDLE, output, home, APP_ID)
    assert output.read_bytes() == archive_blob()
    assert output.stat().st_mode & 0o777 == 0o600
    assert before == (settings.read_bytes(), database.read_bytes())


def test_distinct_default_and_shared_archives_remain_ambiguous_when_scoped(mac_home, tmp_path):
    home, _, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO genp VALUES (?,?,?,?)", (
            "fixture-group", exporter.ACCOUNTS[1], "firebase_auth_" + APP_ID, archive_blob("different-token"),
        ))
        connection.commit()
    output = tmp_path / "private/user.archive"
    with pytest.raises(exporter.ExportError, match="--diagnose"):
        exporter.export_archive(BUNDLE, output, home, APP_ID)
    assert not output.exists()
    diagnostic = exporter.diagnose_archives(BUNDLE, home, APP_ID)
    assert diagnostic == {
        "matched_rows": 2, "distinct_archive_count": 2,
        "counts_by_account_kind": {"default": 1, "shared": 1},
        "groups": [{"group_number": 1, "matched_rows": 2, "distinct_archive_count": 2,
                    "counts_by_account_kind": {"default": 1, "shared": 1}}],
    }


def test_diagnose_prints_only_counts_and_numbered_groups_without_source_changes(mac_home, capsys):
    _, settings, database = mac_home
    private_group = "private-team-and-user-group"
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany("INSERT INTO genp VALUES (?,?,?,?)", [
            (private_group, exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, archive_blob()),
            (private_group, exporter.ACCOUNTS[1], "firebase_auth_" + APP_ID, archive_blob("private-other-user")),
            ("unrelated-other-service", exporter.ACCOUNTS[0], "firebase_auth_1:999:ios:ffff", archive_blob("not-scoped")),
        ])
        connection.commit()
    before = settings.read_bytes(), database.read_bytes()
    assert exporter.main(["--bundle", BUNDLE, "--google-app-id", APP_ID, "--diagnose"]) == 0
    captured = capsys.readouterr()
    output = captured.out + captured.err
    for private_value in [SECRET, private_group, "fixture-group", "private-other-user", APP_ID,
                          exporter.ACCOUNTS[0], exporter.ACCOUNTS[1], archive_blob().hex(),
                          hashlib.sha256(archive_blob()).hexdigest()]:
        assert private_value not in output
    diagnostic = json.loads(captured.out)
    assert diagnostic["matched_rows"] == 3
    assert diagnostic["distinct_archive_count"] == 2
    assert diagnostic["counts_by_account_kind"] == {"default": 2, "shared": 1}
    assert diagnostic["groups"] == [
        {"group_number": 1, "matched_rows": 1, "distinct_archive_count": 1,
         "counts_by_account_kind": {"default": 1, "shared": 0}},
        {"group_number": 2, "matched_rows": 2, "distinct_archive_count": 2,
         "counts_by_account_kind": {"default": 1, "shared": 1}},
    ]
    assert before == (settings.read_bytes(), database.read_bytes())


def test_diagnose_requires_bundle_and_cannot_export_in_same_command(tmp_path):
    with pytest.raises(SystemExit) as missing_bundle:
        exporter.main(["--diagnose"])
    assert missing_bundle.value.code == 2
    with pytest.raises(SystemExit) as mixed_actions:
        exporter.main(["--bundle", BUNDLE, "--diagnose", "--output", str(tmp_path / "archive")])
    assert mixed_actions.value.code == 2
