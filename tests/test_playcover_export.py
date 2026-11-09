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


def test_backup_all_128_scoped_archives_is_private_complete_and_read_only(mac_home, tmp_path, capsys, monkeypatch):
    _, settings, database = mac_home
    originals = [archive_blob()] + [archive_blob(f"private-record-{i}") for i in range(1, 128)]
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany("INSERT INTO genp VALUES (?,?,?,?)", [
            ("fixture-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, blob)
            for blob in originals[1:]
        ])
        connection.commit()
    before = settings.read_bytes(), database.read_bytes()
    destination = tmp_path / "private/firebase-archives"
    original_rename = Path.rename
    published = []

    def checked_rename(staging, target):
        if staging.name.startswith(".firebase-archives-"):
            assert not destination.exists()
            assert len(list(staging.glob("*.archive"))) == 128
            assert (staging / "manifest.json").is_file()
            published.append(True)
        return original_rename(staging, target)

    monkeypatch.setattr(Path, "rename", checked_rename)
    assert exporter.main(["--bundle", BUNDLE, "--google-app-id", APP_ID,
                          "--output-dir", str(destination)]) == 0
    messages = capsys.readouterr()
    assert json.loads(messages.out) == {"matched_rows": 128, "distinct_archive_count": 128, "saved_archives": 128}
    assert messages.err == ""
    for value in [SECRET, APP_ID, BUNDLE, "fixture-group", "private-record-", str(destination)]:
        assert value not in messages.out
    assert published == [True]
    assert destination.stat().st_mode & 0o777 == 0o700
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest == {"matched_rows": 128, "distinct_archive_count": 128,
                        "files": [f"{i:03d}.archive" for i in range(1, 129)]}
    assert {file.read_bytes() for file in destination.glob("*.archive")} == set(originals)
    assert all(file.stat().st_mode & 0o777 == 0o600 for file in destination.iterdir())
    assert not list(destination.parent.glob(".firebase-archives-*"))
    assert before == (settings.read_bytes(), database.read_bytes())


def test_backup_all_deduplicates_identical_bytes_without_choosing_account(mac_home, tmp_path):
    home, _, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany("INSERT INTO genp VALUES (?,?,?,?)", [
            ("another-private-group", exporter.ACCOUNTS[1], "firebase_auth_" + APP_ID, archive_blob()),
            ("another-private-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, archive_blob("another-user")),
        ])
        connection.commit()
    destination = tmp_path / "private/all"
    assert exporter.export_archives(BUNDLE, destination, home, APP_ID) == {
        "matched_rows": 3, "distinct_archive_count": 2, "saved_archives": 2}
    assert len(list(destination.glob("*.archive"))) == 2


def test_backup_all_validates_every_blob_before_publishing_any_file(mac_home, tmp_path, capsys):
    _, settings, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO genp VALUES (?,?,?,?)", (
            "fixture-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, b"invalid-private-archive",
        ))
        connection.commit()
    before = settings.read_bytes(), database.read_bytes()
    destination = tmp_path / "private/all"
    assert exporter.main(["--bundle", BUNDLE, "--google-app-id", APP_ID,
                          "--output-dir", str(destination)]) == 1
    messages = capsys.readouterr()
    assert "NSKeyedArchiver" in messages.err
    assert "invalid-private-archive" not in messages.out + messages.err
    assert not destination.exists()
    assert not destination.parent.exists()
    assert before == (settings.read_bytes(), database.read_bytes())


def test_backup_all_write_failure_removes_staging_and_publishes_nothing(mac_home, tmp_path, monkeypatch):
    home, _, database = mac_home
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO genp VALUES (?,?,?,?)", (
            "fixture-group", exporter.ACCOUNTS[0], "firebase_auth_" + APP_ID, archive_blob("another-user"),
        ))
        connection.commit()
    write_private = exporter._write_private
    writes = []

    def failing_write(path, data):
        writes.append(path.name)
        if len(writes) == 2:
            raise OSError("private-details-must-not-be-printed")
        write_private(path, data)

    monkeypatch.setattr(exporter, "_write_private", failing_write)
    destination = tmp_path / "private/all"
    with pytest.raises(exporter.ExportError, match="Cannot save") as error:
        exporter.export_archives(BUNDLE, destination, home, APP_ID)
    assert "private-details" not in str(error.value)
    assert not destination.exists()
    assert not list(destination.parent.glob(".firebase-archives-*"))


@pytest.mark.parametrize("existing_kind", ["empty-directory", "directory", "file", "dangling-symlink"])
def test_backup_all_requires_new_directory_and_never_overwrites(mac_home, tmp_path, existing_kind):
    home, _, _ = mac_home
    destination = tmp_path / "existing"
    if existing_kind in ("empty-directory", "directory"):
        destination.mkdir()
        if existing_kind == "directory":
            (destination / "preserve.txt").write_bytes(b"keep this existing backup")
    elif existing_kind == "file":
        destination.write_bytes(b"keep this existing file")
    else:
        destination.symlink_to(tmp_path / "not-present")
    with pytest.raises(exporter.ExportError, match="already exists"):
        exporter.export_archives(BUNDLE, destination, home, APP_ID)
    if existing_kind == "directory":
        assert (destination / "preserve.txt").read_bytes() == b"keep this existing backup"
    elif existing_kind == "file":
        assert destination.read_bytes() == b"keep this existing file"
    elif existing_kind == "dangling-symlink":
        assert destination.is_symlink()


def test_backup_all_requires_explicit_bundle_and_cannot_mix_export_actions(tmp_path):
    destination = tmp_path / "backup"
    with pytest.raises(SystemExit) as missing:
        exporter.main(["--output-dir", str(destination)])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as mixed:
        exporter.main(["--bundle", BUNDLE, "--output", str(tmp_path / "archive"),
                       "--output-dir", str(destination)])
    assert mixed.value.code == 2
    assert not destination.exists()
