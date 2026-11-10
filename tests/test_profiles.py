import hashlib
import sqlite3
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import pytest

from idoly_local.codec import encode
from idoly_local.profiles import import_profile, new_profile
from idoly_local.state import State


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="profiles-test.proto", package="api", syntax="proto3")
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
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("api.UserGetResponse"))
    return SimpleNamespace(response_type=lambda _: cls, fingerprint=hashlib.sha256(b"test-schema").hexdigest())


def test_new_account_is_minimal_and_survives_restart(tmp_path, schema):
    path = tmp_path / "state.db"
    state = State(path)
    payload = new_profile(state, schema, "new", "새 매니저")
    response = schema.response_type("/api.User/Get").FromString(payload)
    assert response.user.name == "새 매니저"
    assert response.user.managerLevel == 1
    assert not response.cards
    identity = state.profile("new")
    assert response.userPublic.serverUserId == identity["server_id"]
    assert response.userPublic.publicUserId == identity["public_id"]
    restarted = State(path)
    assert restarted.snapshot("new") == (payload, schema.fingerprint)
    assert restarted.ensure_profile("new") == identity
    token, logged_in = restarted.login("new")
    assert logged_in == identity
    assert restarted.authenticated(token, "new")
    with pytest.raises(ValueError, match="already"):
        new_profile(restarted, schema, "new", "replacement")
    assert restarted.snapshot("new") == (payload, schema.fingerprint)


def test_import_preserves_unknown_fields_identity_and_invalidates_its_sessions(tmp_path, schema):
    state = State(tmp_path / "state.db")
    old_token, _ = state.login("preserved")
    other_token, other_identity = state.login("other")
    response = schema.response_type("/api.User/Get")()
    response.user.name = "원래 매니저"
    response.user.managerLevel = 257
    response.cards.append("existing-card")
    response.userPublic.serverUserId = "original-server"
    response.userPublic.publicUserId = "000000123456"
    # Unknown field 1200 with an integer payload must survive schema evolution.
    payload = response.SerializeToString() + b"\x80\x4b\x7b"
    source = tmp_path / "user-get.pb"
    source.write_bytes(payload)
    assert import_profile(state, schema, "preserved", source) == payload
    assert state.snapshot("preserved") == (payload, schema.fingerprint)
    assert state.profile("preserved") == {"name": "preserved", "server_id": "original-server", "public_id": "000000123456"}
    assert not state.authenticated(old_token, "preserved")
    assert state.authenticated(other_token, "other")
    assert state.profile("other") == other_identity
    assert state.snapshot("other") is None
    token, identity = state.login("preserved")
    assert identity["server_id"] == "original-server"
    assert state.authenticated(token, "preserved")
    assert not state.authenticated(token, "other")


def test_wire_import_without_public_ids_generates_stable_local_identity(tmp_path, schema):
    state = State(tmp_path / "state.db")
    response = schema.response_type("/api.User/Get")()
    response.user.name = "Imported"
    source = tmp_path / "wire.bin"
    source.write_bytes(encode(response.SerializeToString(), ticks=621355968000000000))
    import_profile(state, schema, "imported", source, wire=True)
    identity = state.profile("imported")
    assert identity["server_id"]
    assert len(identity["public_id"]) == 12
    import_profile(state, schema, "imported", source, wire=True)
    assert state.profile("imported") == identity


@pytest.mark.parametrize("payload", [b"", b"\x0a\x05x", b"\x0a\x00", b"\x0a\x03\x0a\x01 "])
def test_invalid_import_leaves_existing_snapshot_and_session_untouched(tmp_path, schema, payload):
    state = State(tmp_path / "state.db")
    original = new_profile(state, schema, "existing", "Keep")
    token, identity = state.login("existing")
    source = tmp_path / "invalid.pb"
    source.write_bytes(payload)
    with pytest.raises(ValueError, match="Malformed|nonempty"):
        import_profile(state, schema, "existing", source)
    assert state.snapshot("existing") == (original, schema.fingerprint)
    assert state.profile("existing") == identity
    assert state.authenticated(token, "existing")


def test_explicit_import_replaces_snapshot_but_stores_no_request_credentials(tmp_path, schema):
    path = tmp_path / "state.db"
    state = State(path)
    new_profile(state, schema, "profile", "Old")
    token, _ = state.login("profile")
    response = schema.response_type("/api.User/Get")()
    response.user.name = "New"
    source = tmp_path / "response.pb"
    source.write_bytes(response.SerializeToString())
    import_profile(state, schema, "profile", source)
    assert state.snapshot("profile")[0] == source.read_bytes()
    assert not state.authenticated(token, "profile")
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"profiles", "sessions", "snapshots", "profile_settings", "starter_profiles",
                          "profile_lesson_progress", "main_live_attempts"}
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT response FROM snapshots WHERE profile='profile'").fetchone()[0] == source.read_bytes()
    assert not list(tmp_path.glob("*.json"))


def test_state_adds_snapshot_table_to_preexisting_database(tmp_path, schema):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE profiles(name TEXT PRIMARY KEY,server_id TEXT NOT NULL,public_id TEXT NOT NULL)")
        db.execute("CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,profile TEXT NOT NULL REFERENCES profiles(name),expires_at INTEGER NOT NULL)")
        db.execute("INSERT INTO profiles VALUES ('old','server','public')")
    state = State(path)
    assert state.profile("old")["server_id"] == "server"
    assert state.snapshot("old") is None
    state.save_snapshot("old", b"", schema.fingerprint)
    assert state.snapshot("old") == (b"", schema.fingerprint)
    with state.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO snapshots VALUES ('absent',?,?)", (b"", schema.fingerprint))


def test_manager_name_required_before_creating_identity(tmp_path, schema):
    state = State(tmp_path / "state.db")
    with pytest.raises(ValueError, match="nonempty"):
        new_profile(state, schema, "blank", " ")
    assert state.profile("blank") is None
