"""Real 6.1.1 protocol across official client, durable import and local game reads.

Only the external transport is synthetic. No credentials or official services
are used. A missing/replaced original descriptor fails instead of skipping.
"""
import base64
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from idoly_local import codec, official_account
from idoly_local.account_manager import AccountManager, selected_profile
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.official_account import OfficialAccountClient
from idoly_local.official_import import OfficialImportManager
from idoly_local.rpc import RpcCode
from idoly_local.schema import Schema
from idoly_local.state import State

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "data/protocol/idolypride-6.1.1.pb"
DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
CANONICAL_SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
NOW = 1800000000
MASTER = "synthetic-original-protocol-master"
PUBLIC = "original_protocol_public_1234"
SERVER = "original_protocol_server_5678"
PASSWORD = "SYNTHETIC_ORIGINAL_PROTOCOL_PASSWORD"
TICKET = "SYNTHETIC_ORIGINAL_PROTOCOL_ONE_TIME_TICKET"
SEED = "SYNTHETIC_ORIGINAL_PROTOCOL_SEED"
GAME = "SYNTHETIC_ORIGINAL_PROTOCOL_OFFICIAL_GAME_TOKEN"
UID = "SYNTHETIC_ORIGINAL_PROTOCOL_FIREBASE_UID"
REFRESH = "SYNTHETIC_ORIGINAL_PROTOCOL_REFRESH_TOKEN"
LOCAL_LOGIN_INPUT = "SYNTHETIC_LOCAL_LOGIN_IGNORED_FIREBASE_TOKEN"
USER = "/api.User/Get"
LOGIN = "/api.Auth/Login"

# The snapshot contains all these original collections, not a copied toy schema.
CATALOG = {"Card": "card-original", "Character": "character-original", "Item": "item-original",
           "Costume": "costume-original", "Hair": "hair-original", "Music": "music-original"}


def _varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


UNKNOWN_PAYLOAD = b"original-protocol-unknown-field-preserved"
UNKNOWN = _varint((30001 << 3) | 2) + _varint(len(UNKNOWN_PAYLOAD)) + UNKNOWN_PAYLOAD


def _jwt(claims):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"inert-original-protocol-signature-1234567890").decode().rstrip("=")
    return encode({"alg": "RS256", "typ": "JWT"}) + "." + encode(claims) + "." + signature


def _custom_token():
    issuer = "firebase-adminsdk-synthetic@solis-firebase.iam.gserviceaccount.com"
    return _jwt({"aud": "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit",
                 "iss": issuer, "sub": issuer, "uid": UID, "iat": NOW - 5, "exp": NOW + 3500})


def _id_token():
    return _jwt({"aud": "solis-firebase", "iss": "https://securetoken.google.com/solis-firebase",
                 "sub": UID, "user_id": UID, "iat": NOW - 1, "exp": NOW + 3599,
                 "firebase": {"sign_in_provider": "custom"}})


def _config(platform):
    return {"api_key": "AIzaSYNTHETIC_ORIGINAL_PROTOCOL_PUBLIC_KEY", "project_id": "solis-firebase",
            "project_number": "543065248020", "bundle_id": "game.qualiarts.idolypride",
            "google_app_id": "1:543065248020:" + platform + ":0123456789abcdef012345",
            "app_version": "6.1.1"}


def _snapshot(schema):
    value = schema.response_type(USER)()
    value.user.name = "원본 계정"
    value.user.managerLevel = 31
    value.user.managerExp = 123456
    value.userPublic.serverUserId = SERVER
    value.userPublic.publicUserId = PUBLIC
    value.cards.add(cardId=CATALOG["Card"], level=45, totalExp=12345, rarity=5, skillLevel1=3)
    value.characters.add(characterId=CATALOG["Character"], activityLevel=7, reliability=9,
        favoriteCostumeId=CATALOG["Costume"], favoriteHairId=CATALOG["Hair"])
    value.items.add(itemId=CATALOG["Item"], amount=987654321)
    value.costumes.add(costumeId=CATALOG["Costume"], checked=True, obtainedTime=NOW * 1000)
    value.hairs.add(hairId=CATALOG["Hair"], checked=True)
    value.musics.add(musicId=CATALOG["Music"])
    value.photos.add(photoId="photo-original-instance", assetId="photo-original-asset",
        characterIds=[CATALOG["Character"]], name="원본 사진", locked=True)
    return value.SerializeToString() + UNKNOWN


class _Timer:
    """Do not leave background expiry threads after these short offline tests."""
    def __init__(self, interval, callback, args=()):
        self.interval, self.callback, self.args = interval, callback, args
        self.daemon = False
        self.cancelled = False
    def start(self):
        pass
    def cancel(self):
        self.cancelled = True


class _SyntheticTransport:
    """Implements only the external boundary, using actual request/reply classes."""
    def __init__(self, schema, raw):
        self.schema, self.raw = schema, raw
        self.calls, self.closed = [], False
    def seed(self, headers, *, cancel=None):
        self.calls.append("seed")
        assert set(headers) == {"X-Device", "X-Ad", "X-App", "X-AppVersion", "X-SeedVersion"}
        return SEED
    def rpc(self, path, plain, metadata, *, cancel=None, timeout=30):
        self.calls.append(path)
        assert timeout == 30
        request = self.schema.request_type(path).FromString(plain)
        response = self.schema.response_type(path)()
        if path == "/api.System/Check":
            if request.firebaseIDToken:
                assert request.firebaseIDToken == _id_token()
        elif path == "/api.Migration/MigratePassword":
            assert request.userId == PUBLIC and request.password == PASSWORD
            assert "x-auth-token" not in metadata
            response.success = True
            response.linkedUserId = PUBLIC
            response.linkedUser.name = "원본 미리보기"
            response.linkedUser.managerLevel = 31
            response.onetimeToken = TICKET
        elif path == "/api.Migration/Execute":
            assert request.onetimeToken == TICKET
            response.token = _custom_token()
        elif path == LOGIN:
            assert request.firebaseIDToken == _id_token()
            response.gameAuthToken = GAME
            response.userPublic.serverUserId = SERVER
            response.userPublic.publicUserId = PUBLIC
        elif path == "/api.Master/Get":
            assert metadata["x-auth-token"] == GAME
            response.masterTag.version = MASTER
            return response.SerializeToString() + UNKNOWN
        elif path == USER:
            assert metadata["x-auth-token"] == GAME and metadata["x-master-version"] == MASTER
            return self.raw
        else:
            pytest.fail("Unexpected official RPC: " + path)
        return response.SerializeToString()
    def firebase(self, operation, api_key, payload, headers, *, cancel=None):
        self.calls.append(operation)
        assert api_key == "AIzaSYNTHETIC_ORIGINAL_PROTOCOL_PUBLIC_KEY"
        if operation == "signin":
            assert payload == {"token": _custom_token(), "returnSecureToken": True}
            # Modern sign-in responses need not return localId.
            return {"idToken": _id_token(), "refreshToken": REFRESH, "expiresIn": "3600"}
        assert operation == "lookup" and payload == {"idToken": _id_token()}
        return {"users": [{"localId": UID}]}
    def close(self):
        self.closed = True


@pytest.fixture(scope="module")
def original_schema():
    assert DESCRIPTOR.is_file(), "Focused CI must prepare the actual pinned 6.1.1 descriptor"
    assert hashlib.sha256(DESCRIPTOR.read_bytes()).hexdigest() == DESCRIPTOR_SHA256
    schema = Schema.from_descriptor_set(DESCRIPTOR)
    assert schema.fingerprint == CANONICAL_SCHEMA_SHA256
    fields = schema.method(USER).output_type.fields_by_name
    assert {name: fields[name].number for name in ("items", "cards", "characters", "costumes", "musics", "hairs", "userPublic")} == {
        "items": 2, "cards": 3, "characters": 4, "costumes": 5, "musics": 32, "hairs": 37, "userPublic": 999}
    assert fields["cards"].message_type.fields_by_name["cardId"].number == 1
    assert fields["items"].message_type.fields_by_name["amount"].number == 3
    return schema


def _environment(tmp_path, schema, monkeypatch, platform):
    monkeypatch.setattr(official_account.time, "time", lambda: NOW)
    (tmp_path / "protocol").mkdir()
    (tmp_path / "protocol/idolypride-6.1.1.pb").write_bytes(DESCRIPTOR.read_bytes())
    (tmp_path / "original-master").mkdir()
    (tmp_path / "original-master/master-tag.json").write_text(json.dumps({"version": MASTER}))
    (tmp_path / "master-json").mkdir()
    (tmp_path / "master-json/!version.txt").write_text(MASTER)
    for table, identity in CATALOG.items():
        (tmp_path / ("master-json/" + table + ".json")).write_text(json.dumps([{"id": identity}]))
    raw = _snapshot(schema)
    accounts = AccountManager(tmp_path)
    clients, transports = [], []
    def factory(actual_schema, *, platform):
        assert actual_schema.fingerprint == CANONICAL_SCHEMA_SHA256
        transport = _SyntheticTransport(actual_schema, raw)
        client = OfficialAccountClient(actual_schema, platform=platform,
                                       transport=transport, config=_config(platform))
        clients.append(client)
        transports.append(transport)
        return client
    manager = OfficialImportManager(tmp_path, accounts=accounts, client_factory=factory,
                                    now=lambda: NOW, timer_factory=_Timer)
    return accounts, manager, clients, transports, raw


def _finish(manager, expected):
    thread = manager._thread
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive(), "Synthetic official worker did not finish"
    status = manager.status(public=False)
    assert status["state"] == expected, status
    assert not status["busy"]
    return status


def _inspect_fetch(manager, transports, platform):
    payload = {"user_id": PUBLIC, "password": PASSWORD, "platform": platform}
    manager.command("official_inspect", payload)
    payload.clear()
    verified = _finish(manager, "verified")
    assert transports[0].calls == ["seed", "/api.System/Check", "/api.Migration/MigratePassword"]
    assert verified["preview"]["public_id"] == PUBLIC
    assert verified["preview"]["server_id"] is None
    verification = manager._job.verification
    manager.command("official_fetch", {"job_id": verified["job_id"]})
    ready = _finish(manager, "ready")
    assert verification.closed and verification.consumed
    assert not verification._token and not verification._metadata
    return ready


def _assert_private_archive(path, raw):
    with ZipFile(path) as archive:
        assert set(archive.namelist()) == {"manifest.json", "account.json"}
        manifest = json.loads(archive.read("manifest.json"))
        payload = archive.read("account.json")
        bundle = json.loads(payload)
    assert manifest["schema_sha256"] == CANONICAL_SCHEMA_SHA256 and manifest["mode"] == "normal"
    assert set(bundle["tables"]) == {"profiles", "snapshots", "starter_profiles", "profile_settings",
        "profile_lesson_progress", "preference_receipts", "main_live_attempts"}
    assert "sessions" not in bundle["tables"]
    assert base64.b64decode(bundle["tables"]["snapshots"][0]["response"]["$bytes"], validate=True) == raw
    for secret in (PASSWORD, TICKET, SEED, GAME, UID, REFRESH, _custom_token(), _id_token(), LOCAL_LOGIN_INPUT):
        assert secret.encode() not in payload
        assert base64.b64encode(secret.encode()) not in payload
    return bundle


class _Abort(Exception):
    def __init__(self, code):
        self.code = code


class _Context:
    def __init__(self, token=None):
        self.token = token
    def invocation_metadata(self):
        return (("x-auth-token", self.token),) if self.token else ()
    def abort(self, code, details):
        raise _Abort(code)


@pytest.mark.parametrize("platform", ["ios", "android"])
def test_original_protocol_real_client_import_reopen_export_and_local_relogin(tmp_path, original_schema, monkeypatch, platform):
    schema = original_schema
    accounts, manager, clients, transports, raw = _environment(tmp_path, schema, monkeypatch, platform)
    state = accounts._state("normal")
    other_identity = state.ensure_profile("other")
    other = schema.response_type(USER)()
    other.user.name = "기존 로컬"
    other.userPublic.serverUserId = other_identity["server_id"]
    other.userPublic.publicUserId = other_identity["public_id"]
    state.save_snapshot("other", other.SerializeToString(), schema.fingerprint, starter_version=0)
    other_before = state.account_snapshot("other")
    other_token, _ = state.login("other")
    try:
        ready = _inspect_fetch(manager, transports, platform)
        assert ready["counts"] == {"cards": 1, "items": 1, "photos": 1}
        assert ready["preview"]["manager_name"] == "원본 계정"
        assert clients[0]._closed and transports[0].closed
        staged = list((accounts.base / "imports").glob("*.zip"))
        assert len(staged) == 1
        _assert_private_archive(staged[0], raw)
        assert state.profile("imported") is None
        assert state.account_snapshot("other") == other_before
        applied = manager.command("official_apply", {"job_id": ready["job_id"], "profile": "imported",
                                 "replace": False, "expected_revision": None})
        assert applied["job"]["state"] == "completed"
        assert applied["account"]["mode"] == "normal" and applied["account"]["profile"] == "imported"
        assert selected_profile(tmp_path, False) == selected_profile(tmp_path, True) == "sandbox"
        assert not (tmp_path / "media-state.db").exists()
        assert not list((accounts.base / "imports").glob("*.zip"))
        assert not list((accounts.base / "imports").glob("*.json"))
        # Reopen the actual database/schema rather than reading a staged mock.
        reopened_accounts = AccountManager(tmp_path)
        reopened_schema = reopened_accounts._schema()
        reopened = State(tmp_path / "state.db")
        assert reopened.snapshot("imported") == (raw, reopened_schema.fingerprint)
        assert reopened.starter_version("imported") == 0
        assert reopened.profile("imported")["server_id"] == SERVER
        assert reopened.profile("imported")["public_id"] == PUBLIC
        assert reopened.account_snapshot("other") == other_before
        assert reopened.authenticated(other_token, "other")
        assert not reopened.authenticated(GAME, "imported")
        with reopened.connect() as database:
            assert database.execute("SELECT COUNT(*) FROM sessions WHERE profile='imported'").fetchone()[0] == 0
        # A real capture store deliberately contains stale account data.
        stale = reopened_schema.response_type(USER)()
        stale.user.name = "낡은 캡처"
        stale_source = tmp_path / "stale-user.pb"
        stale_source.write_bytes(stale.SerializeToString())
        fixtures = tmp_path / "fixtures"
        import_response(stale_source, fixtures, reopened_schema, USER)
        captured = FixtureStore(fixtures, reopened_schema)
        assert captured.get(USER, b"") != raw
        # Exercise the full real Application constructor, Auth.Login and User.Get.
        app = Application(reopened_schema, reopened, captured, profile="imported")
        with pytest.raises(_Abort) as unauthenticated:
            app.handle(USER, b"", _Context())
        assert unauthenticated.value.code == RpcCode.UNAUTHENTICATED
        request = reopened_schema.request_type(LOGIN)(firebaseIDToken=LOCAL_LOGIN_INPUT).SerializeToString()
        replies = [reopened_schema.response_type(LOGIN).FromString(app.handle(LOGIN, codec.encode(request), _Context()))
                   for _ in range(2)]
        local_tokens = [reply.gameAuthToken for reply in replies]
        assert local_tokens[0] != local_tokens[1]
        for reply in replies:
            assert reply.gameAuthToken.startswith("local-") and reply.gameAuthToken != GAME
            assert reply.userPublic.serverUserId == SERVER and reply.userPublic.publicUserId == PUBLIC
            assert app.handle(USER, b"", _Context(reply.gameAuthToken)) == raw
        decoded = reopened_schema.response_type(USER).FromString(raw)
        assert decoded.cards[0].cardId == CATALOG["Card"] and decoded.cards[0].level == 45
        assert decoded.items[0].itemId == CATALOG["Item"] and decoded.items[0].amount == 987654321
        assert decoded.characters[0].favoriteHairId == CATALOG["Hair"]
        assert decoded.costumes[0].costumeId == CATALOG["Costume"]
        assert decoded.hairs[0].hairId == CATALOG["Hair"] and decoded.musics[0].musicId == CATALOG["Music"]
        assert decoded.photos[0].assetId == "photo-original-asset" and raw.endswith(UNKNOWN)
        bundle, revision = reopened.account_snapshot("imported")
        exported = reopened_accounts.command("accounts_export", {"mode": "normal", "profile": "imported",
                                                                 "expected_revision": revision})
        _assert_private_archive(Path(exported["path"]), raw)
        with reopened.connect() as database:
            hashes = {row[0] for row in database.execute("SELECT token_hash FROM sessions")}
        assert hashlib.sha256(GAME.encode()).hexdigest() not in hashes
        assert {hashlib.sha256(value.encode()).hexdigest() for value in (other_token, *local_tokens)} <= hashes
        assert all(not bundle["tables"][key] for key in ("profile_settings", "profile_lesson_progress",
                                                        "preference_receipts", "main_live_attempts"))
        # Neither local login nor export re-enters official authentication.
        assert transports[0].calls == ["seed", "/api.System/Check", "/api.Migration/MigratePassword",
            "/api.Migration/Execute", "signin", "lookup", "/api.System/Check", LOGIN, "/api.Master/Get", USER]
        for path in tmp_path.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_bytes()
            for secret in (PASSWORD, TICKET, SEED, GAME, UID, REFRESH, _custom_token(), _id_token(), LOCAL_LOGIN_INPUT):
                assert secret.encode() not in content
    finally:
        manager.close()
        if manager._thread is not None:
            manager._thread.join(timeout=5)
