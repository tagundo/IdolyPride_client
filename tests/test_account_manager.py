"""Full SQLite account portability, native-only commands and rollback contracts."""
import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import pytest

from idoly_local import account_manager as accounts
from idoly_local.account_manager import AccountManager, AccountError, selected_profile, selection_status
from idoly_local.state import State

UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="accounts-test.proto", package="api", syntax="proto3")
    user = file.message_type.add(name="User")
    user.field.add(name="name", number=1, label=1, type=9)
    user.field.add(name="managerLevel", number=100, label=1, type=5)
    public = file.message_type.add(name="UserPublic")
    public.field.add(name="serverUserId", number=1, label=1, type=9)
    public.field.add(name="publicUserId", number=2, label=1, type=9)
    response = file.message_type.add(name="UserGetResponse")
    response.field.add(name="user", number=1, label=1, type=11, type_name=".api.User")
    response.field.add(name="cards", number=3, label=3, type=9)
    response.field.add(name="userPublic", number=999, label=1, type=11, type_name=".api.UserPublic")
    settings = file.message_type.add(name="SettingInfo")
    settings.field.add(name="value", number=1, label=1, type=5)
    progress = file.message_type.add(name="LessonProgress")
    progress.field.add(name="value", number=1, label=1, type=5)
    login = file.message_type.add(name="HomeLoginRequest")
    login.field.add(name="settingInfo", number=1, label=1, type=11, type_name=".api.SettingInfo")
    lesson = file.message_type.add(name="LessonResponse")
    lesson.field.add(name="progress", number=1, label=1, type=11, type_name=".api.LessonProgress")
    receipt = file.message_type.add(name="Receipt")
    receipt.field.add(name="value", number=1, label=1, type=5)
    pool = descriptor_pool.DescriptorPool(); pool.Add(file)
    classes = {name: message_factory.GetMessageClass(pool.FindMessageTypeByName("api."+name))
               for name in ("UserGetResponse", "HomeLoginRequest", "LessonResponse", "Receipt")}
    def response_type(path):
        return classes["UserGetResponse" if path == "/api.User/Get" else
                       "LessonResponse" if path == "/api.Activity/ReceiveLessonReward" else "Receipt"]
    return SimpleNamespace(response_type=response_type, request_type=lambda _: classes["HomeLoginRequest"],
                           fingerprint=hashlib.sha256(b"account-schema").hexdigest())


def populated(state, schema, profile, label="Manager"):
    identity = state.ensure_profile(profile)
    response = schema.response_type("/api.User/Get")()
    response.user.name = label; response.user.managerLevel = 9
    response.userPublic.serverUserId = identity["server_id"]
    response.userPublic.publicUserId = identity["public_id"]
    response.cards.extend(("owned-a", "owned-b"))
    payload = response.SerializeToString() + UNKNOWN
    state.save_snapshot(profile, payload, schema.fingerprint, starter_version=7)
    with state.connect() as db:
        db.execute("INSERT INTO profile_settings VALUES (?,?,?)", (profile, b"\x08\x01"+UNKNOWN, schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES (?,?,?)", (profile, b"\x08\x01"+UNKNOWN, schema.fingerprint))
        db.execute("INSERT INTO preference_receipts VALUES (?,?,?,?,?,?)", (
            profile, "/api.Photograph/ToggleLock", "5", "a"*64, schema.fingerprint, b"\x08\x01"+UNKNOWN))
        db.execute("INSERT INTO main_live_attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (
            profile, "9", "b"*64, "/api.Quest/Start", schema.fingerprint, "master", "rules-v1",
            str((1<<64)-1), 1794810000000, b"\x08\x01"+UNKNOWN))
    return payload


@pytest.fixture
def manager(tmp_path, schema, monkeypatch):
    value = AccountManager(tmp_path, schema=schema)
    def seed(self, state, protocol, profile, mode, name):
        populated(state, protocol, profile, name)
    monkeypatch.setattr(AccountManager, "_seed", seed)
    return value


def create(manager, name="sandbox", mode="normal"):
    manager_name = name if len(name.encode("utf-16-le"))//2 <= 10 else "QA"
    return manager.command("accounts_create", {"mode": mode, "profile": name, "manager_name": manager_name})


def row(manager, name="sandbox", mode="normal"):
    return next(row for row in manager.status()["accounts"] if row["profile"] == name and row["mode"] == mode)


def exported(manager, name="sandbox", mode="normal"):
    return manager.command("accounts_export", {"mode": mode, "profile": name, "expected_revision": row(manager, name, mode)["revision"]})


def preview(manager, export):
    return manager.command("accounts_preview", {"path": export["path"]})


def importing(manager, token, name, *, mode="normal", replace=False, revision=None):
    return manager.command("accounts_import", {"token": token, "mode": mode, "profile": name,
                           "replace": replace, "expected_revision": revision})


def rewrite_zip(source, target, mutate):
    with ZipFile(source) as z:
        members = {name: z.read(name) for name in z.namelist()}
    mutate(members)
    with ZipFile(target, "w", compression=ZIP_STORED) as z:
        for name, raw in members.items(): z.writestr(name, raw)
    return target


def test_status_is_bounded_and_does_not_create_default_accounts(manager):
    result = manager.command("accounts_status", {})
    assert result["ok"] is True and result["status"]["accounts"] == []
    assert result["status"]["selected"] == {"normal": "sandbox", "media": "sandbox"}
    assert not (manager.root/"state.db").exists()
    assert not (manager.root/"media-state.db").exists()
    assert selected_profile(manager.root, False) == "sandbox"


def test_create_normal_media_and_select_are_isolated_and_queued(manager):
    create(manager); original = manager._state("normal").account_snapshot("sandbox")
    create(manager, "새 계정"); create(manager, "감상", "media")
    account = row(manager, "새 계정")
    before = manager.status()["selection_revision"]
    result = manager.command("accounts_select", {"mode": "normal", "profile": "새 계정",
        "expected_revision": account["revision"], "selection_revision": before})
    assert result["restart_required"] is True
    assert selected_profile(manager.root, False) == "새 계정"
    assert selected_profile(manager.root, True) == "sandbox"
    assert manager._state("normal").account_snapshot("sandbox") == original
    assert manager._state("normal").profile("감상") is None
    with pytest.raises(AccountError, match="selection_conflict"):
        manager.command("accounts_select", {"mode": "normal", "profile": "sandbox",
            "expected_revision": row(manager)["revision"], "selection_revision": before})


def test_default_seed_dispatch_uses_real_normal_and_explicit_media_entrypoints(tmp_path, schema, monkeypatch):
    calls = []
    def seed(state, protocol, profile, master, *, manager_name):
        calls.append(("normal", profile, master, manager_name)); populated(state, protocol, profile, manager_name)
    def media(state, protocol, profile, master): calls.append(("media", profile, master))
    monkeypatch.setitem(sys.modules, "idoly_local.gameplay", SimpleNamespace(seed_starter_profile=seed))
    monkeypatch.setitem(sys.modules, "idoly_local.media_runtime", SimpleNamespace(prepare_media_profile=media))
    value = AccountManager(tmp_path, schema=schema)
    create(value, "ordinary"); create(value, "gallery", "media")
    assert [entry[0] for entry in calls] == ["normal", "normal", "media"]
    assert calls[0][2] == tmp_path/"master-json"
    assert value._state("normal").snapshot("gallery") is None
    assert value._state("media").snapshot("ordinary") is None


def test_clone_is_complete_branch_with_exact_unknown_bytes_and_no_sessions(manager):
    create(manager)
    state = manager._state("normal")
    token, _ = state.login("sandbox")
    bundle, revision = state.account_snapshot("sandbox")
    result = manager.command("accounts_clone", {"mode": "normal", "source_profile": "sandbox",
        "profile": "branch", "expected_revision": revision})
    cloned, cloned_revision = state.account_snapshot("branch")
    for table, rows in bundle["tables"].items():
        key = "name" if table == "profiles" else "profile"
        assert cloned["tables"][table] == [{**entry, key: "branch"} for entry in rows]
    assert cloned["tables"]["snapshots"][0]["response"].endswith(UNKNOWN)
    assert result["account"]["revision"] == cloned_revision
    assert state.authenticated(token, "sandbox") and not state.authenticated(token, "branch")
    assert state.profile("branch")["server_id"] == state.profile("sandbox")["server_id"]


def test_portable_roundtrip_preserves_every_owned_table_and_unknown_fields(manager, tmp_path, schema):
    create(manager); source = manager._state("normal")
    source_token, _ = source.login("sandbox")
    before, _ = source.account_snapshot("sandbox")
    export = exported(manager)
    assert Path(export["path"]).name == export["filename"]
    assert export["filename"].startswith("IdolyPride-Account-") and export["filename"].endswith(".zip")
    assert Path(export["path"]).stat().st_size == export["bytes"]
    assert hashlib.sha256(Path(export["path"]).read_bytes()).hexdigest() == export["sha256"]
    with ZipFile(export["path"]) as z:
        assert set(z.namelist()) == {"manifest.json", "account.json"}
        raw = z.read("account.json")
        assert b'"sessions"' not in raw and source_token.encode() not in raw
    destination = AccountManager(tmp_path/"destination", schema=schema)
    staged = preview(destination, export)
    assert staged["archive"]["counts"] == {table: len(rows) for table, rows in before["tables"].items()}
    # Changing the external original after preview never changes its private copy.
    Path(export["path"]).write_bytes(b"external original changed")
    result = importing(destination, staged["token"], "restored")
    saved, _ = destination._state("normal").account_snapshot("restored")
    for table, entries in before["tables"].items():
        key = "name" if table == "profiles" else "profile"
        assert saved["tables"][table] == [{**entry, key: "restored"} for entry in entries]
    assert result["restore_point"] is None
    assert source.authenticated(source_token, "sandbox")
    assert not (destination.base/"imports"/(staged["token"]+".zip")).exists()
    assert not (destination.base/"imports"/(staged["token"]+".json")).exists()


def test_replace_and_restore_capture_all_target_rows_and_keep_other_accounts_sessions(manager):
    create(manager); create(manager, "target"); create(manager, "other"); create(manager, "media", "media")
    state = manager._state("normal"); media = manager._state("media")
    old, old_revision = state.account_snapshot("target")
    other = state.account_snapshot("other"); media_before = media.account_snapshot("media")
    old_token, _ = state.login("target"); other_token, _ = state.login("other")
    staged = preview(manager, exported(manager))
    result = importing(manager, staged["token"], "target", replace=True, revision=old_revision)
    assert result["restore_point"]["revision"] == old_revision
    assert not state.authenticated(old_token, "target") and state.authenticated(other_token, "other")
    replacement, revision = state.account_snapshot("target")
    assert replacement != old
    current_token, _ = state.login("target")
    restored = manager.command("accounts_restore", {"mode": "normal", "profile": "target",
        "id": result["restore_point"]["id"], "expected_revision": revision})
    assert state.account_snapshot("target") == (old, old_revision)
    assert not state.authenticated(current_token, "target") and state.authenticated(other_token, "other")
    assert state.account_snapshot("other") == other and media.account_snapshot("media") == media_before
    assert restored["restore_point"]["revision"] == revision


@pytest.mark.parametrize("action", ["clone", "select", "replace", "restore"])
def test_stale_revision_never_mutates_target_or_sessions(action, manager):
    create(manager); create(manager, "target")
    state = manager._state("normal"); before = state.account_snapshot("target")
    token, _ = state.login("target")
    staged = preview(manager, exported(manager))
    if action == "clone":
        invoke = lambda: manager.command("accounts_clone", {"mode": "normal", "source_profile": "target",
            "profile": "branch", "expected_revision": "0"*64})
    elif action == "select":
        invoke = lambda: manager.command("accounts_select", {"mode": "normal", "profile": "target", "expected_revision": "0"*64})
    elif action == "replace":
        invoke = lambda: importing(manager, staged["token"], "target", replace=True, revision="0"*64)
    else:
        replaced = importing(manager, staged["token"], "target", replace=True, revision=before[1])
        before = state.account_snapshot("target"); token, _ = state.login("target")
        invoke = lambda: manager.command("accounts_restore", {"mode": "normal", "profile": "target",
            "id": replaced["restore_point"]["id"], "expected_revision": "0"*64})
    points = manager.status()["restore_points"]
    with pytest.raises(ValueError, match="revision_conflict"):
        invoke()
    assert state.account_snapshot("target") == before and state.authenticated(token, "target")
    assert manager.status()["restore_points"] == points


def test_backup_failure_rolls_back_before_account_or_sessions_change(manager, monkeypatch):
    create(manager); create(manager, "target")
    state = manager._state("normal"); before = state.account_snapshot("target")
    token, _ = state.login("target")
    staged = preview(manager, exported(manager))
    original = accounts._sync_directory
    def fail_backup(path):
        if Path(path).name == "restore-points": raise OSError("test fsync failure")
        original(path)
    monkeypatch.setattr(accounts, "_sync_directory", fail_backup)
    with pytest.raises(OSError): importing(manager, staged["token"], "target", replace=True, revision=before[1])
    assert state.account_snapshot("target") == before and state.authenticated(token, "target")
    assert manager.status()["restore_points"] == []


def test_sql_failure_rolls_back_every_target_table_and_keeps_durable_restore_point(manager):
    create(manager); create(manager, "target")
    state = manager._state("normal"); before = state.account_snapshot("target")
    token, _ = state.login("target")
    staged = preview(manager, exported(manager))
    with state.connect() as db:
        db.execute("CREATE TRIGGER reject_account BEFORE INSERT ON profile_settings WHEN NEW.profile='target' "
                   "BEGIN SELECT RAISE(ABORT,'test reject'); END")
    with pytest.raises(sqlite3.IntegrityError):
        importing(manager, staged["token"], "target", replace=True, revision=before[1])
    assert state.account_snapshot("target") == before and state.authenticated(token, "target")
    assert manager.status()["restore_points"][0]["revision"] == before[1]


def test_restore_requires_index_bound_profile_and_revision(manager):
    create(manager); create(manager, "target")
    before = manager._state("normal").account_snapshot("target")
    result = importing(manager, preview(manager, exported(manager))["token"], "target", replace=True, revision=before[1])
    point = manager.base/"restore-points"/(result["restore_point"]["id"]+".zip")
    shutil.copyfile(exported(manager)["path"], point)
    current = manager._state("normal").account_snapshot("target")
    with pytest.raises(AccountError, match="restore_point_changed"):
        manager.command("accounts_restore", {"mode": "normal", "profile": "target",
            "id": result["restore_point"]["id"], "expected_revision": current[1]})
    assert manager._state("normal").account_snapshot("target") == current


def test_preview_token_is_bound_to_original_private_copy_hash(manager):
    create(manager); create(manager, "different")
    staged = preview(manager, exported(manager))
    private = manager.base/"imports"/(staged["token"]+".zip")
    shutil.copyfile(exported(manager, "different")["path"], private)
    with pytest.raises(AccountError, match="preview_changed"):
        importing(manager, staged["token"], "new")
    assert manager._state("normal").profile("new") is None


@pytest.mark.parametrize("case", ["kind", "extra", "traversal", "duplicate", "symlink", "wrong_schema", "hash", "sessions"])
def test_unsafe_or_wrong_kind_archives_cannot_change_accounts(case, manager, tmp_path):
    create(manager); export = exported(manager); bad = tmp_path/(case+".zip")
    with ZipFile(export["path"]) as z: members = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(members["manifest.json"])
    if case == "kind": manifest["kind"] = "idoly-resource-library"
    elif case == "wrong_schema": manifest["schema_sha256"] = "f"*64
    elif case == "hash": manifest["account_sha256"] = "0"*64
    elif case == "extra": members["extra"] = b"extra"
    elif case == "traversal": members["../account.json"] = members.pop("account.json")
    elif case == "sessions":
        bundle = accounts._unpack(members["account.json"])
        bundle["tables"]["sessions"] = []
        members["account.json"] = json.dumps(bundle, default=lambda value: {"$bytes": base64.b64encode(value).decode()}).encode()
        manifest["account_bytes"] = len(members["account.json"])
        manifest["account_sha256"] = hashlib.sha256(members["account.json"]).hexdigest()
    members["manifest.json"] = accounts._json(manifest)
    with ZipFile(bad, "w") as z:
        for name, raw in members.items():
            if case == "symlink" and name == "account.json":
                entry = ZipInfo(name); entry.external_attr = (stat.S_IFLNK | 0o777)<<16
                z.writestr(entry, raw)
            else: z.writestr(name, raw)
        if case == "duplicate": z.writestr("account.json", members["account.json"])
    before = manager._state("normal").account_snapshot("sandbox")
    with pytest.raises(ValueError): preview(manager, {"path": str(bad)})
    assert manager._state("normal").account_snapshot("sandbox") == before


def test_archive_rejects_hardlinks_symlinks_and_declared_extent(manager, tmp_path, monkeypatch):
    create(manager); export = exported(manager)
    link = tmp_path/"linked.zip"; link.symlink_to(export["path"])
    with pytest.raises(AccountError): preview(manager, {"path": str(link)})
    link.unlink(); os.link(export["path"], link)
    with pytest.raises(AccountError): preview(manager, {"path": str(link)})
    link.unlink()
    monkeypatch.setattr(accounts, "MAX_ACCOUNT_JSON", 64)
    with pytest.raises(AccountError, match="member_invalid"):
        preview(manager, export)


def test_wrong_proto_and_explicit_identity_mismatch_are_rejected_before_export(manager, schema):
    create(manager)
    state = manager._state("normal"); original, _ = state.account_snapshot("sandbox")
    with state.connect() as db:
        db.execute("UPDATE profile_settings SET schema_sha256=?", ("f"*64,))
    with pytest.raises(AccountError, match="protocol_schema_differs"): exported(manager)
    with state.connect() as db:
        db.execute("UPDATE profile_settings SET schema_sha256=?", (schema.fingerprint,))
        db.execute("UPDATE profiles SET server_id='different' WHERE name='sandbox'")
    with pytest.raises(AccountError, match="identity_mismatch"): exported(manager)
    assert state.snapshot("sandbox")[0] == original["tables"]["snapshots"][0]["response"]


def test_import_mode_never_crosses_normal_and_media_databases(manager):
    create(manager); create(manager, "gallery", "media")
    normal = manager._state("normal").account_snapshot("sandbox")
    media = manager._state("media").account_snapshot("gallery")
    staged = preview(manager, exported(manager))
    with pytest.raises(AccountError, match="mode_differs"):
        importing(manager, staged["token"], "new-gallery", mode="media")
    assert manager._state("normal").account_snapshot("sandbox") == normal
    assert manager._state("media").account_snapshot("gallery") == media


def test_pagination_exposes_every_profile_and_fits_native_envelope(manager):
    normal, media = manager._state("normal"), manager._state("media")
    for n in range(31): normal.ensure_profile("n-"+str(n).zfill(2))
    for n in range(17): media.ensure_profile("m-"+str(n).zfill(2))
    first = manager.status(); second = manager.status(offset=first["next_offset"])
    assert first["accounts_total"] == second["accounts_total"] == 48
    assert len(first["accounts"]) == len(second["accounts"]) == 24
    assert second["next_offset"] is None
    assert len({(row["mode"], row["profile"]) for row in first["accounts"]+second["accounts"]}) == 48
    assert len(json.dumps(first, ensure_ascii=False).encode()) < 48*1024


def test_selection_status_is_metadata_only_and_corruption_blocks_start(manager, monkeypatch):
    create(manager)
    original = State.connect
    monkeypatch.setattr(State, "connect", lambda _: (_ for _ in ()).throw(AssertionError("status read account SQL")))
    assert selection_status(manager.root)["invalid_registry"] is False
    monkeypatch.setattr(State, "connect", original)
    (manager.base/"registry.json").write_text('{"schema":1,"selected":{"normal":"missing","media":null}}')
    with pytest.raises(AccountError, match="selected_account_missing"): selected_profile(manager.root, False)
    (manager.base/"registry.json").write_text('{broken')
    assert selection_status(manager.root)["invalid_registry"] is True
    with pytest.raises(AccountError): selected_profile(manager.root, False)


def test_profiles_are_sql_parameters_and_utf8_bounded(manager):
    key = "quote'; DROP TABLE profiles;--"
    create(manager, key)
    assert manager._state("normal").profile(key) is not None
    create(manager, "한"*21)
    with pytest.raises(AccountError, match="profile_invalid"): create(manager, "한"*22)
    with pytest.raises(AccountError): create(manager, "../outside")
    with pytest.raises(AccountError): manager.command("accounts_export", {"mode": "normal", "profile": key, "sql": "DROP TABLE profiles"})



@pytest.mark.parametrize("table", ["profile_settings", "profile_lesson_progress", "preference_receipts", "main_live_attempts"])
def test_malformed_auxiliary_protobuf_never_exports_as_valid_account(table, manager):
    create(manager)
    state = manager._state("normal")
    with state.connect() as db:
        db.execute("UPDATE " + table + " SET response=? WHERE profile='sandbox'", (b"\x80",))
    with pytest.raises(AccountError, match="protobuf_invalid"):
        exported(manager)



def test_unknown_database_tables_cannot_be_silently_omitted_from_backup(manager):
    create(manager)
    state = manager._state("normal")
    with state.connect() as db:
        db.execute("CREATE TABLE future_account_data(profile TEXT, payload BLOB)")
    with pytest.raises(ValueError, match="database_schema_differs"):
        state.account_snapshot("sandbox")



@pytest.mark.parametrize("kind,expected", [("permission", "account_permission_denied"),
    ("space", "account_insufficient_space"), ("busy", "account_storage_busy"),
    ("constraint", "account_state_rejected"), ("io", "account_storage_io")])
def test_native_errors_have_specific_safe_codes_without_paths_or_raw_sql(kind, expected, tmp_path, monkeypatch):
    import errno
    if kind == "permission": error = PermissionError(errno.EACCES, "secret account path")
    elif kind == "space": error = OSError(errno.ENOSPC, "secret disk path")
    elif kind == "busy":
        error = sqlite3.OperationalError("secret raw SQL")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    elif kind == "constraint": error = sqlite3.IntegrityError("secret trigger SQL")
    else: error = OSError(errno.EIO, "secret IO path")
    def fail(_action, _payload): raise error
    monkeypatch.setattr(accounts, "AccountManager", lambda _root: SimpleNamespace(command=fail))
    with pytest.raises(AccountError) as result:
        accounts.account_command(tmp_path, "accounts_status", {})
    assert str(result.value) == expected and "secret" not in str(result.value)



def test_actual_member_crc_is_checked_before_account_import(manager, tmp_path):
    create(manager); export = exported(manager); bad = tmp_path/"bad-crc.zip"
    rewrite_zip(export["path"], bad, lambda _members: None)
    with ZipFile(bad) as archive:
        entry = archive.getinfo("account.json")
        offset = entry.header_offset + 30 + len(entry.filename.encode()) + len(entry.extra)
    raw = bytearray(bad.read_bytes()); raw[offset+5] ^= 1; bad.write_bytes(raw)
    with pytest.raises(AccountError, match="archive_invalid"):
        preview(manager, {"path": str(bad)})


def test_restore_point_file_and_index_directories_are_synced_before_commit(manager, monkeypatch):
    create(manager); create(manager, "target")
    staged = preview(manager, exported(manager)); calls = []
    original = accounts._sync_directory
    def observe(path):
        calls.append(Path(path).name); original(path)
    monkeypatch.setattr(accounts, "_sync_directory", observe)
    revision = row(manager, "target")["revision"]
    importing(manager, staged["token"], "target", replace=True, revision=revision)
    assert "restore-points" in calls
    index_sync = calls.index("restore-points")
    assert calls[index_sync+1] == "account-management"



@pytest.mark.parametrize("name", ["", "   ", "a"*11, "😀"*6, "bad\nname", "bad\tname"])
def test_new_manager_names_match_original_utf16_input_limit(name, manager):
    with pytest.raises(AccountError, match="manager_name_invalid"):
        manager.command("accounts_create", {"mode": "normal", "profile": "new", "manager_name": name})
    assert manager._state("normal", existing=True) is None


def test_utf16_name_boundary_is_preserved_without_normalization(manager):
    name = "😀"*5
    manager.command("accounts_create", {"mode": "normal", "profile": "new", "manager_name": name})
    assert row(manager, "new")["manager_name"] == name



def test_abandoned_temporary_copies_are_bounded_without_rotating_restore_points(manager):
    create(manager)
    last = None
    for _ in range(10): last = exported(manager)
    assert len(list((manager.base/"exports").glob("*.zip"))) == 8
    assert Path(last["path"]).is_file()
    for _ in range(10): staged = preview(manager, last)
    assert len(list((manager.base/"imports").glob("*.zip"))) == 8
    assert (manager.base/"imports"/(staged["token"]+".zip")).is_file()
    assert manager.status()["restore_points"] == []
