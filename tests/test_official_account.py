"""Original 6.1.1 descriptor with synthetic replies; no official network calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from idoly_local import official_account as module
from idoly_local.official_account import (CollectedAccount, ERROR_CODES, OfficialAccountClient,
    OfficialAccountError, STAGES)
from idoly_local.schema import Schema

ROOT = Path(__file__).resolve().parents[1]
NOW = 1794800000
PUBLIC = "SYNTHETIC_PUBLIC_1234"
SERVER = "SYNTHETIC_SERVER_1234"
PASSWORD = "SYNTHETIC_PRIVATE_PASSWORD"
TICKET = "SYNTHETIC_PRIVATE_TICKET"
UID = "SYNTHETIC_PRIVATE_FIREBASE_UID"
GAME = "SYNTHETIC_PRIVATE_GAME_TOKEN"
SEED = "SYNTHETIC_PRIVATE_SEED"
REFRESH = "SYNTHETIC_PRIVATE_REFRESH"
KEY = "AIzaSYNTHETIC_PUBLIC_CONFIGURATION_KEY"


def config(platform="ios"):
    return {"api_key": KEY, "project_id": "solis-firebase", "project_number": "543065248020",
        "google_app_id": "1:543065248020:" + platform + ":0123456789abcdef012345",
        "bundle_id": "game.qualiarts.idolypride", "app_version": "6.1.1"}


def jwt(claims, header=None):
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"inert-synthetic-signature-1234567890").decode().rstrip("=")
    return enc({"alg": "RS256", "typ": "JWT"} if header is None else header) + "." + enc(claims) + "." + signature


def custom(**changes):
    issuer = "firebase-adminsdk-synthetic@solis-firebase.iam.gserviceaccount.com"
    claims = {"aud": module._AUDIENCE, "iss": issuer, "sub": issuer, "uid": UID,
              "iat": NOW - 5, "exp": NOW + 3500}
    claims.update(changes)
    return jwt(claims)


def identity(**changes):
    claims = {"aud": "solis-firebase", "iss": "https://securetoken.google.com/solis-firebase",
        "sub": UID, "user_id": UID, "iat": NOW - 1, "exp": NOW + 3599,
        "auth_time": NOW - 2, "firebase": {"sign_in_provider": "custom"}}
    claims.update(changes)
    return jwt(claims)


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


UNKNOWN = varint(20001 << 3) + varint(99)


@pytest.fixture(scope="module")
def schema():
    return Schema.from_descriptor_set(ROOT / "data/protocol/idolypride-6.1.1.pb")


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(module.time, "time", lambda: NOW)


class Transport:
    def __init__(self, schema):
        self.schema = schema
        self.calls = []
        self.mutations = {}
        self.extra_raw = {}
        self.fail_at = None
        self.on_call = None
        self.closed = False
        self.seed_value = SEED
        self.signin = {"idToken": identity(), "refreshToken": REFRESH, "expiresIn": "3600"}
        self.lookup = {"users": [{"localId": UID}]}
        self.user_raw = self.master_raw = None

    def seed(self, headers, *, cancel=None):
        self.calls.append(("seed", dict(headers)))
        if self.fail_at == "seed":
            raise RuntimeError(PASSWORD + TICKET + GAME)
        return self.seed_value

    def rpc(self, method, request, metadata, *, cancel=None, timeout=30):
        request = self.schema.request_type(method).FromString(request)
        self.calls.append((method, request, dict(metadata), timeout))
        if self.on_call:
            self.on_call(method)
        if self.fail_at == method:
            raise RuntimeError(PASSWORD + TICKET + GAME)
        response = self.schema.response_type(method)()
        if method == module._MIGRATE:
            assert request.userId == PUBLIC and request.password == PASSWORD
            response.success = True
            response.linkedUserId = PUBLIC
            response.linkedUser.name = "검증한 매니저"
            response.linkedUser.managerLevel = 3
            response.onetimeToken = TICKET
        elif method == module._EXECUTE:
            assert request.onetimeToken == TICKET
            response.token = custom()
        elif method == module._LOGIN:
            assert request.firebaseIDToken == self.signin["idToken"]
            response.gameAuthToken = GAME
            response.userPublic.serverUserId = SERVER
            response.userPublic.publicUserId = PUBLIC
        elif method == module._MASTER:
            assert metadata["x-auth-token"] == GAME
            response.masterTag.version = "synthetic-official-master"
        elif method == module._USER:
            assert metadata["x-auth-token"] == GAME
            assert metadata["x-master-version"] == "synthetic-official-master"
            response.user.name = "수집한 매니저"
            response.user.managerLevel = 4
            response.userPublic.serverUserId = SERVER
            response.userPublic.publicUserId = PUBLIC
            response.cards.add(cardId="synthetic-card")
        mutate = self.mutations.get(method)
        if mutate:
            mutate(response, request)
        raw = response.SerializeToString() + self.extra_raw.get(method, b"")
        if method in (module._USER, module._MASTER):
            raw += UNKNOWN
        if method == module._USER:
            self.user_raw = raw
        elif method == module._MASTER:
            self.master_raw = raw
        return raw

    def firebase(self, operation, api_key, payload, headers, *, cancel=None):
        self.calls.append((operation, api_key, dict(payload), dict(headers)))
        if self.fail_at == operation:
            raise RuntimeError(PASSWORD + TICKET + GAME)
        if operation == "signin":
            assert payload == {"token": custom(), "returnSecureToken": True}
            return copy.deepcopy(self.signin)
        assert operation == "lookup" and payload == {"idToken": self.signin["idToken"]}
        return copy.deepcopy(self.lookup)

    def close(self):
        self.closed = True


def client(schema, platform="ios"):
    transport = Transport(schema)
    return OfficialAccountClient(schema, platform=platform, transport=transport, config=config(platform)), transport


def assert_redacted(value):
    rendered = str(value) + repr(value)
    for secret in (PUBLIC, SERVER, PASSWORD, TICKET, UID, GAME, SEED, REFRESH, KEY, custom(), identity()):
        assert secret not in rendered


def test_inspection_is_separate_and_collection_preserves_exact_unknown_fields(schema):
    account, transport = client(schema)
    stages = []
    verification = account.inspect(PUBLIC, PASSWORD, progress=stages.append)
    assert [c[0] for c in transport.calls] == ["seed", module._SYSTEM, module._MIGRATE]
    assert verification.public_id == PUBLIC and verification.server_id is None
    assert verification.manager_name == "검증한 매니저" and verification.manager_level == 3
    assert verification.created_at == NOW and verification.expires_at == NOW + 600
    assert not verification.consumed and not verification.closed
    assert_redacted(verification)
    assert_redacted(account)
    result = account.fetch(verification, progress=stages.append)
    assert type(result) is CollectedAccount
    assert result.user_get == transport.user_raw and result.master_get == transport.master_raw
    assert result.user_get.endswith(UNKNOWN) and result.master_get.endswith(UNKNOWN)
    assert result.server_id == SERVER and result.public_id == PUBLIC and result.platform == "ios"
    assert result.master_version == "synthetic-official-master"
    assert verification.consumed and verification.closed and not verification._token and not verification._metadata
    assert_redacted(result)
    assert stages == ["preparing", "checking", "verifying", "verified", "transferring", "firebase",
                      "login", "master", "account", "collected"]
    assert set(stages) == STAGES
    assert [c[0] for c in transport.calls] == ["seed", module._SYSTEM, module._MIGRATE, module._EXECUTE,
        "signin", "lookup", module._SYSTEM, module._LOGIN, module._MASTER, module._USER]
    for call in transport.calls:
        if call[0] in module._METHODS:
            assert call[3] == 30
            assert not any(x in call[2] for x in ("password", "firebaseIDToken", "onetimeToken"))
    result.close()
    assert result.user_get == result.master_get == b""
    account.close()
    assert transport.closed


@pytest.mark.parametrize("platform", ["ios", "android"])
def test_platform_scope_and_public_firebase_headers(schema, platform):
    options = config(platform)
    if platform == "android":
        options["certificate_sha1"] = "a1" * 20
    transport = Transport(schema)
    account = OfficialAccountClient(schema, platform=platform, transport=transport, config=options)
    options["api_key"] = "external-modification"
    account.fetch(account.inspect(PUBLIC, PASSWORD))
    rpc = next(c for c in transport.calls if c[0] == module._MIGRATE)
    assert rpc[2]["x-platform"] == ("iOS" if platform == "ios" else "Android")
    signin = next(c for c in transport.calls if c[0] == "signin")
    assert signin[1] == KEY
    assert signin[3]["X-Firebase-GMPID"] == config(platform)["google_app_id"]
    if platform == "ios":
        assert signin[3]["X-Ios-Bundle-Identifier"] == "game.qualiarts.idolypride"
        assert "X-Android-Package" not in signin[3]
    else:
        assert signin[3]["X-Android-Package"] == "game.qualiarts.idolypride"
        assert signin[3]["X-Android-Cert"] == ("A1" * 20)


@pytest.mark.parametrize("user,password,code", [("", PASSWORD, "transfer_id_invalid"),
    ("x" * 65, PASSWORD, "transfer_id_invalid"), ("bad id", PASSWORD, "transfer_id_invalid"),
    ("한국어", PASSWORD, "transfer_id_invalid"), (PUBLIC, "", "transfer_password_invalid"),
    (PUBLIC, "x" * 129, "transfer_password_invalid"), (PUBLIC, " leading", "transfer_password_invalid"),
    (PUBLIC, "trailing ", "transfer_password_invalid"), (PUBLIC, "a\nb", "transfer_password_invalid"),
    (PUBLIC, None, "transfer_password_invalid")])
def test_invalid_input_never_reaches_network(schema, user, password, code):
    account, transport = client(schema)
    with pytest.raises(OfficialAccountError, match=code):
        account.inspect(user, password)
    assert not transport.calls


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("project_number", "1"),
    ("google_app_id", "1:543065248020:android:0123456789abcdef"), ("bundle_id", "other"),
    ("app_version", "0.0.0"), ("api_key", ""), ("api_key", "bad\nkey"),
    ("certificate_sha1", "a" * 40)])
def test_invalid_or_cross_project_configuration_fails_closed(schema, field, value):
    options = config()
    options[field] = value
    transport = Transport(schema)
    with pytest.raises(OfficialAccountError):
        OfficialAccountClient(schema, transport=transport, config=options)
    assert not transport.calls


def test_missing_default_public_configuration_never_constructs_transport(schema, monkeypatch):
    def unavailable(platform):
        raise RuntimeError(PASSWORD)
    monkeypatch.setitem(sys.modules, "idoly_local.official_account_config", SimpleNamespace(load_public_config=unavailable))
    with pytest.raises(OfficialAccountError, match="official_config_unavailable") as caught:
        OfficialAccountClient(schema)
    assert_redacted(caught.value)


@pytest.mark.parametrize("mutate", [lambda r, q: setattr(r, "success", False),
    lambda r, q: setattr(r, "linkedUserId", "another-user"),
    lambda r, q: setattr(r, "onetimeToken", ""), lambda r, q: r.ClearField("linkedUser"),
    lambda r, q: setattr(r.linkedUser, "name", ""),
    lambda r, q: setattr(r.linkedUser, "managerLevel", 0)])
def test_invalid_inspection_cannot_produce_a_ticket(schema, mutate):
    account, transport = client(schema)
    transport.mutations[module._MIGRATE] = mutate
    with pytest.raises(OfficialAccountError) as caught:
        account.inspect(PUBLIC, PASSWORD)
    assert_redacted(caught.value)
    assert module._EXECUTE not in [c[0] for c in transport.calls]


@pytest.mark.parametrize("field", ["inMaintenance", "isBeforeRelease", "inReview", "alternativeApiHost"])
def test_maintenance_and_review_redirect_stop_before_password_submission(schema, field):
    account, transport = client(schema)
    def mutate(response, request):
        target = response.maintenanceInfo if field in ("inMaintenance", "isBeforeRelease") else response.reviewInfo
        setattr(target, field, "https://untrusted.invalid" if field == "alternativeApiHost" else True)
    transport.mutations[module._SYSTEM] = mutate
    with pytest.raises(OfficialAccountError):
        account.inspect(PUBLIC, PASSWORD)
    assert module._MIGRATE not in [c[0] for c in transport.calls]


@pytest.mark.parametrize("method", [module._EXECUTE, "signin", "lookup", module._LOGIN, module._MASTER, module._USER])
def test_failed_fetch_is_consumed_once_and_remote_error_is_redacted(schema, method):
    account, transport = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    transport.fail_at = method
    with pytest.raises(OfficialAccountError) as caught:
        account.fetch(verification)
    assert caught.value.code in ERROR_CODES
    assert_redacted(caught.value)
    count = len(transport.calls)
    with pytest.raises(OfficialAccountError, match="verification_closed"):
        account.fetch(verification)
    assert len(transport.calls) == count
    assert sum(c[0] == module._EXECUTE for c in transport.calls) == 1
    assert verification.closed and verification.consumed and not verification._metadata


@pytest.mark.parametrize("claims", [{"aud": "other"}, {"uid": ""}, {"iss": "bad@other.iam.gserviceaccount.com"},
    {"sub": "other"}, {"tenant_id": "tenant"}, {"claims": {"firebase": {}}},
    {"iat": NOW + 301, "exp": NOW + 3600}, {"exp": NOW}, {"iat": True},
    {"iat": NOW - 4000, "exp": NOW + 10}])
def test_custom_token_scope_and_time_errors_prevent_firebase_exchange(schema, claims):
    account, transport = client(schema)
    transport.mutations[module._EXECUTE] = lambda r, q: setattr(r, "token", custom(**claims))
    with pytest.raises(OfficialAccountError):
        account.fetch(account.inspect(PUBLIC, PASSWORD))
    assert "signin" not in [c[0] for c in transport.calls]


@pytest.mark.parametrize("claims", [{"aud": "other"}, {"iss": "https://evil.invalid"}, {"sub": "other"},
    {"user_id": "other"}, {"firebase": {"sign_in_provider": "password"}},
    {"firebase": {"sign_in_provider": "custom", "tenant": "other"}}, {"iat": True},
    {"exp": NOW}, {"auth_time": NOW + 100}])
def test_id_token_scope_and_time_errors_prevent_lookup_and_game_login(schema, claims):
    account, transport = client(schema)
    transport.signin["idToken"] = identity(**claims)
    with pytest.raises(OfficialAccountError):
        account.fetch(account.inspect(PUBLIC, PASSWORD))
    assert "lookup" not in [c[0] for c in transport.calls]
    assert module._LOGIN not in [c[0] for c in transport.calls]


@pytest.mark.parametrize("reply", [{"users": []}, {"users": [{"localId": "other"}]},
    {"users": [{"localId": UID}, {"localId": UID}]},
    {"users": [{"localId": UID, "tenantId": "other"}]},
    {"users": [{"localId": UID, "disabled": True}]}])
def test_firebase_lookup_is_authoritative_and_cannot_switch_identity(schema, reply):
    account, transport = client(schema)
    transport.lookup = reply
    with pytest.raises(OfficialAccountError, match="firebase_scope_mismatch"):
        account.fetch(account.inspect(PUBLIC, PASSWORD))
    assert module._LOGIN not in [c[0] for c in transport.calls]


@pytest.mark.parametrize("method,mutation", [(module._LOGIN, lambda r, q: setattr(r, "requiredFirebaseReauthenticate", True)),
    (module._LOGIN, lambda r, q: setattr(r, "gameAuthToken", "")),
    (module._LOGIN, lambda r, q: r.ClearField("userPublic")),
    (module._LOGIN, lambda r, q: setattr(r.userPublic, "publicUserId", "other")),
    (module._LOGIN, lambda r, q: setattr(r.userPublic, "serverUserId", "")),
    (module._MASTER, lambda r, q: r.ClearField("masterTag")),
    (module._USER, lambda r, q: setattr(r.userPublic, "serverUserId", "other")),
    (module._USER, lambda r, q: setattr(r.userPublic, "publicUserId", "other")),
    (module._USER, lambda r, q: r.ClearField("user"))])
def test_game_reply_identity_and_reauthentication_never_produce_a_snapshot(schema, method, mutation):
    account, transport = client(schema)
    transport.mutations[method] = mutation
    with pytest.raises(OfficialAccountError) as caught:
        account.fetch(account.inspect(PUBLIC, PASSWORD))
    assert_redacted(caught.value)
    if method == module._LOGIN:
        assert module._MASTER not in [c[0] for c in transport.calls]
    assert not any(c[0] in ("/api.Auth/Create", "/api.Auth/Recreate", "/api.Home/Login") for c in transport.calls)


def test_verification_cannot_be_used_by_another_client(schema):
    account, first = client(schema)
    other, second = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    with pytest.raises(OfficialAccountError, match="verification_invalid"):
        other.fetch(verification)
    assert not second.calls
    assert account.fetch(verification).public_id == PUBLIC


def test_expired_ticket_fails_before_execute(schema, monkeypatch):
    account, transport = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    monkeypatch.setattr(module.time, "monotonic", lambda: verification._deadline)
    with pytest.raises(OfficialAccountError, match="verification_expired"):
        account.fetch(verification)
    assert module._EXECUTE not in [c[0] for c in transport.calls]
    assert verification.closed and not verification._token and not verification._metadata


@pytest.mark.parametrize("action", ["forget", "close", "ticket_close"])
def test_forgetting_or_closing_drops_ticket_credentials(schema, action):
    account, transport = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    getattr(verification if action == "ticket_close" else account, "close" if action == "ticket_close" else action)()
    assert verification.closed and not verification._token and not verification._metadata
    with pytest.raises(OfficialAccountError):
        account.fetch(verification)
    assert module._EXECUTE not in [c[0] for c in transport.calls]


def test_cancel_during_execute_consumes_ticket_and_drops_result(schema):
    account, transport = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    cancel = threading.Event()
    transport.on_call = lambda method: cancel.set() if method == module._EXECUTE else None
    with pytest.raises(OfficialAccountError, match="cancelled"):
        account.fetch(verification, cancel=cancel)
    assert verification.closed and verification.consumed
    assert "signin" not in [c[0] for c in transport.calls]


def test_cancel_before_inspect_prevents_all_network_calls(schema):
    account, transport = client(schema)
    with pytest.raises(OfficialAccountError, match="cancelled"):
        account.inspect(PUBLIC, PASSWORD, cancel=lambda: True)
    assert not transport.calls


def test_progress_callback_error_never_reveals_credentials(schema):
    account, transport = client(schema)
    def bad(stage):
        raise RuntimeError(PASSWORD + TICKET)
    with pytest.raises(OfficialAccountError, match="progress_callback_failed") as caught:
        account.inspect(PUBLIC, PASSWORD, progress=bad)
    assert_redacted(caught.value)
    assert not transport.calls


def test_two_concurrent_fetch_calls_cannot_execute_twice(schema):
    account, transport = client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    entered, release = threading.Event(), threading.Event()
    def block(method):
        if method == module._EXECUTE:
            entered.set()
            assert release.wait(5)
    transport.on_call = block
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(account.fetch, verification)
        assert entered.wait(5)
        try:
            with pytest.raises(OfficialAccountError, match="client_busy"):
                account.fetch(verification)
        finally:
            release.set()
        assert future.result(timeout=5).public_id == PUBLIC
    assert sum(c[0] == module._EXECUTE for c in transport.calls) == 1


def test_real_descriptor_user_has_no_id_and_original_field_contracts_are_explicit(schema):
    linked = schema.method(module._MIGRATE).output_type.fields_by_name["linkedUser"].message_type
    assert "id" not in linked.fields_by_name
    assert linked.fields_by_name["managerLevel"].number == 100
    assert schema.method(module._USER).output_type.fields_by_name["userPublic"].number == 999
    class BrokenSchema:
        def method(self, path):
            return schema.method(module._EXECUTE if path == module._MIGRATE else path)
    with pytest.raises(OfficialAccountError, match="official_schema_unsupported"):
        OfficialAccountClient(BrokenSchema(), transport=Transport(schema), config=config())


def test_transport_cancelled_code_is_preserved_without_revealing_message(schema):
    account, transport = client(schema)
    class Cancelled(RuntimeError):
        code = "cancelled"
    def fail(headers, *, cancel=None):
        raise Cancelled(PASSWORD + TICKET)
    transport.seed = fail
    with pytest.raises(OfficialAccountError, match="cancelled") as caught:
        account.inspect(PUBLIC, PASSWORD)
    assert_redacted(caught.value)


def test_changed_signin_local_id_is_rejected_but_missing_id_is_supported(schema):
    account, transport = client(schema)
    assert "localId" not in transport.signin
    transport.signin["localId"] = "different-uid"
    with pytest.raises(OfficialAccountError, match="firebase_scope_mismatch"):
        account.fetch(account.inspect(PUBLIC, PASSWORD))
    assert "lookup" not in [c[0] for c in transport.calls]


def test_ticket_preview_is_immutable_and_client_reinspection_forgets_previous(schema):
    from dataclasses import FrozenInstanceError
    account, transport = client(schema)
    first = account.inspect(PUBLIC, PASSWORD)
    with pytest.raises(FrozenInstanceError):
        first.public_id = "different-id"
    second = account.inspect(PUBLIC, PASSWORD)
    assert first.closed and not first._token and not first._metadata
    assert second is not first and not second.closed
    assert account.fetch(second).public_id == PUBLIC


def test_inspection_closes_new_ticket_if_client_closes_before_publication(schema, monkeypatch):
    account, transport = client(schema)
    original = module.Verification
    created = []
    def construct(*args, **kwargs):
        verification = original(*args, **kwargs)
        created.append(verification)
        account.close()
        return verification
    monkeypatch.setattr(module, "Verification", construct)
    with pytest.raises(OfficialAccountError, match="client_closed"):
        account.inspect(PUBLIC, PASSWORD)
    assert len(created) == 1 and created[0].closed
    assert not created[0]._token and not created[0]._metadata
    assert account._verification is None


@pytest.mark.parametrize("method", [module._USER, module._MASTER])
@pytest.mark.parametrize("secret", [TICKET, custom(), identity(), REFRESH, GAME, SEED])
def test_long_authentication_token_reflected_in_unknown_reply_is_not_returned(schema, method, secret):
    account, transport = client(schema)
    payload = secret.encode("ascii")
    transport.extra_raw[method] = varint((20002 << 3) | 2) + varint(len(payload)) + payload
    verification = account.inspect(PUBLIC, PASSWORD)
    with pytest.raises(OfficialAccountError, match="credential_reflected") as caught:
        account.fetch(verification)
    assert_redacted(caught.value)
    assert verification.closed and not verification._token and not verification._metadata


@pytest.mark.parametrize("code", sorted(module.TRANSPORT_ERROR_CODES))
@pytest.mark.parametrize("boundary", ["seed", "rpc", "firebase"])
def test_finite_transport_failure_classes_are_preserved_without_remote_details(schema, code, boundary):
    account, transport = client(schema)
    class Fault(RuntimeError):
        pass
    def fail(*args, **kwargs):
        error = Fault(PASSWORD + TICKET + GAME)
        error.code = code
        raise error
    verification = None
    if boundary != "seed":
        verification = account.inspect(PUBLIC, PASSWORD)
    if boundary == "rpc":
        transport.rpc = fail
    elif boundary == "firebase":
        transport.firebase = fail
    else:
        transport.seed = fail
    with pytest.raises(OfficialAccountError) as caught:
        if verification is None:
            account.inspect(PUBLIC, PASSWORD)
        else:
            account.fetch(verification)
    assert caught.value.code == code and code in ERROR_CODES
    assert_redacted(caught.value)
    if verification is not None:
        assert verification.closed


@pytest.mark.parametrize("boundary,fallback", [("seed", "official_seed_failed"),
    ("rpc", "official_rpc_failed"), ("firebase", "official_firebase_failed")])
@pytest.mark.parametrize("bad_code", [PASSWORD, "arbitrary_server_detail", 500, None])
def test_arbitrary_transport_codes_are_collapsed_to_fixed_fallback(schema, boundary, fallback, bad_code):
    account, transport = client(schema)
    class Fault(RuntimeError):
        pass
    def fail(*args, **kwargs):
        error = Fault(PASSWORD + TICKET + GAME)
        error.code = bad_code
        raise error
    verification = None if boundary == "seed" else account.inspect(PUBLIC, PASSWORD)
    setattr(transport, boundary, fail)
    with pytest.raises(OfficialAccountError) as caught:
        if verification is None:
            account.inspect(PUBLIC, PASSWORD)
        else:
            account.fetch(verification)
    assert caught.value.code == fallback
    assert_redacted(caught.value)


def test_faulty_transport_code_property_cannot_escape_fixed_error_boundary(schema):
    account, transport = client(schema)
    class Fault(RuntimeError):
        @property
        def code(self):
            raise RuntimeError(PASSWORD)
    def fail(*args, **kwargs):
        raise Fault(TICKET)
    transport.seed = fail
    with pytest.raises(OfficialAccountError, match="official_seed_failed") as caught:
        account.inspect(PUBLIC, PASSWORD)
    assert_redacted(caught.value)


class AnonymousMasterTransport(Transport):
    """Only the public preflight boundary differs from normal synthetic auth."""
    def __init__(self, schema):
        super().__init__(schema)
        self.public_version = "synthetic-official-master"
        self.public_fault = None
        self.public_action = None
        self.public_raw = None

    def rpc(self, method, request, metadata, *, cancel=None, timeout=30):
        if method == module._MASTER and "x-auth-token" not in metadata:
            assert request == b"" and metadata == {"x-app-version":"6.1.1"} and timeout == 30
            self.calls.append((method, request, dict(metadata), timeout))
            if self.public_fault is not None: raise self.public_fault
            if self.public_action is not None: self.public_action()
            if self.public_raw is not None: return self.public_raw
            response = self.schema.response_type(method)()
            if self.public_version is not None: response.masterTag.version = self.public_version
            return response.SerializeToString()
        return super().rpc(method, request, metadata, cancel=cancel, timeout=timeout)


def anonymous_client(schema, platform="ios"):
    transport = AnonymousMasterTransport(schema)
    return OfficialAccountClient(schema, platform=platform, transport=transport, config=config(platform)), transport


@pytest.mark.parametrize("platform", ["ios", "android"])
def test_anonymous_master_preflight_sends_no_seed_credentials_or_auth_and_keeps_inspection_separate(schema, platform):
    account, transport = anonymous_client(schema, platform)
    assert account.preflight_master_version("synthetic-official-master") == "synthetic-official-master"
    assert [row[0] for row in transport.calls] == [module._MASTER]
    assert account._verification is None and not account._busy
    verification = account.inspect(PUBLIC, PASSWORD)
    assert not verification.consumed
    account.preflight_master_version("synthetic-official-master")
    assert not verification.consumed and not verification.closed
    result = account.fetch(verification)
    assert result.master_version == "synthetic-official-master"
    assert [row[0] for row in transport.calls] == [module._MASTER, "seed", module._SYSTEM, module._MIGRATE,
        module._MASTER, module._EXECUTE, "signin", "lookup", module._SYSTEM, module._LOGIN, module._MASTER, module._USER]
    assert_redacted(account)


@pytest.mark.parametrize("kind,code", [("mismatch","official_master_mismatch"),
    ("unavailable","official_rpc_failed"), ("timeout","deadline_exceeded"),
    ("missing","master_version_invalid"), ("malformed","official_rpc_failed")])
def test_public_preflight_failure_never_starts_transfer_authentication_or_account_read(schema, kind, code):
    from idoly_local.official_transport import OfficialTransportError
    account, transport = anonymous_client(schema)
    if kind == "mismatch": transport.public_version = "different-public-version"
    elif kind == "unavailable": transport.public_fault = RuntimeError(PASSWORD + TICKET)
    elif kind == "timeout": transport.public_fault = OfficialTransportError("deadline_exceeded")
    elif kind == "missing": transport.public_version = None
    else: transport.public_raw = b"\xff"
    with pytest.raises(OfficialAccountError) as stopped:
        account.preflight_master_version("synthetic-official-master")
    assert stopped.value.code == code and PASSWORD not in str(stopped.value) and TICKET not in str(stopped.value)
    assert [row[0] for row in transport.calls] == [module._MASTER]
    assert account._verification is None and not account._busy


@pytest.mark.parametrize("during", [False, True])
def test_preflight_cancellation_before_or_during_public_request_never_consumes_verified_ticket(schema, during):
    account, transport = anonymous_client(schema)
    verification = account.inspect(PUBLIC, PASSWORD)
    before = len(transport.calls)
    cancel = threading.Event()
    if during: transport.public_action = cancel.set
    else: cancel.set()
    with pytest.raises(OfficialAccountError, match="cancelled"):
        account.preflight_master_version("synthetic-official-master", cancel=cancel)
    assert len(transport.calls) == before + int(during)
    assert not verification.consumed and not verification.closed and verification._token == TICKET
    assert module._EXECUTE not in [row[0] for row in transport.calls]


def test_preflight_busy_guard_prevents_concurrent_inspection_without_sending_credentials(schema):
    account, transport = anonymous_client(schema)
    started, release = threading.Event(), threading.Event()
    def waiting():
        started.set()
        assert release.wait(3)
    transport.public_action = waiting
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(account.preflight_master_version, "synthetic-official-master")
        try:
            assert started.wait(3)
            with pytest.raises(OfficialAccountError, match="client_busy"):
                account.inspect(PUBLIC, PASSWORD)
            assert [row[0] for row in transport.calls] == [module._MASTER]
        finally:
            release.set()
        assert worker.result(timeout=3) == "synthetic-official-master"
