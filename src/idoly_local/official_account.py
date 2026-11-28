"""Explicit Japanese transfer-password inspection and one-shot account collection.

No account is created, recreated, refreshed, or written to local storage here.
Transport errors, callback failures and response contents never enter error text.
"""
from dataclasses import dataclass, field
import base64
import json
import re
import threading
import time
import uuid

_SYSTEM = "/api.System/Check"
_MIGRATE = "/api.Migration/MigratePassword"
_EXECUTE = "/api.Migration/Execute"
_LOGIN = "/api.Auth/Login"
_MASTER = "/api.Master/Get"
_USER = "/api.User/Get"
_METHODS = (_SYSTEM, _MIGRATE, _EXECUTE, _LOGIN, _MASTER, _USER)
_PROJECT = "solis-firebase"
_NUMBER = "543065248020"
_BUNDLE = "game.qualiarts.idolypride"
_AUDIENCE = "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit"
_MAX_RPC = 17 * 1024 * 1024
_TTL = 600
STAGES = frozenset(("preparing", "checking", "verifying", "verified", "transferring",
    "firebase", "login", "master", "account", "collected"))
TRANSPORT_ERROR_CODES = frozenset((
    'cancel_invalid',
    'cancelled',
    'deadline_exceeded',
    'firebase_request_invalid',
    'headers_invalid',
    'http_body_invalid',
    'http_body_too_large',
    'http_failed',
    'http_redirect_rejected',
    'http_status_rejected',
    'rpc_application_rejected',
    'rpc_encoding_rejected',
    'rpc_failed',
    'rpc_frame_invalid',
    'rpc_headers_invalid',
    'rpc_http_rejected',
    'rpc_method_rejected',
    'rpc_request_invalid',
    'rpc_response_incomplete',
    'rpc_response_too_large',
    'rpc_status_rejected',
    'rpc_stream_failed',
    'seed_invalid',
    'timeout_invalid',
    'tls_alpn_invalid',
    'tls_failed',
    'tls_roots_invalid',
))
ERROR_CODES = frozenset((
    'account_identity_mismatch',
    'cancel_invalid',
    'cancelled',
    'client_busy',
    'client_closed',
    'credential_reflected',
    'firebase_response_invalid',
    'firebase_scope_mismatch',
    'firebase_token_invalid',
    'firebase_token_time_invalid',
    'linked_user_invalid',
    'master_version_invalid',
    'official_master_mismatch',
    'official_config_invalid',
    'official_config_scope_mismatch',
    'official_config_unavailable',
    'official_firebase_failed',
    'official_maintenance',
    'official_reauthentication_required',
    'official_review_unsupported',
    'official_rpc_failed',
    'official_schema_unsupported',
    'official_seed_failed',
    'official_seed_invalid',
    'official_transport_unavailable',
    'platform_invalid',
    'progress_callback_failed',
    'rpc_method_not_allowed',
    'rpc_response_invalid',
    'transfer_id_invalid',
    'transfer_password_invalid',
    'transfer_rejected',
    'verification_closed',
    'verification_consumed',
    'verification_expired',
    'verification_invalid',
)) | TRANSPORT_ERROR_CODES


class OfficialAccountError(RuntimeError):
    """A fixed, credential-free code suitable for diagnostics and the UI."""
    def __init__(self, code):
        self.code = code
        super().__init__("Official account stopped: " + code)


def _need(condition, code):
    if not condition:
        raise OfficialAccountError(code)


def _transport_failure(error, fallback):
    # An exact finite allowlist keeps useful local failure classes without ever
    # forwarding a remote message, numeric status, arbitrary code or URL.
    try:
        code = getattr(error, "code", None)
    except Exception:
        code = None
    return OfficialAccountError(code if type(code) is str and code in TRANSPORT_ERROR_CODES else fallback)


def _text(value, maximum=16384):
    return type(value) is str and 0 < len(value) <= maximum and all(32 <= ord(c) < 127 for c in value)


def _identity(value):
    return _text(value, 128) and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None


def _cancelled(cancel):
    if cancel is None:
        return False
    try:
        result = cancel.is_set() if hasattr(cancel, "is_set") else cancel()
        _need(type(result) is bool, "cancel_invalid")
        return result
    except OfficialAccountError:
        raise
    except Exception:
        raise OfficialAccountError("cancel_invalid") from None


def _object_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "firebase_token_invalid")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _need(type(value) is dict, "firebase_token_invalid")
        return value
    except OfficialAccountError:
        raise
    except Exception:
        raise OfficialAccountError("firebase_token_invalid") from None


def _jwt(token):
    _need(_text(token), "firebase_token_invalid")
    parts = token.split(".")
    _need(len(parts) == 3 and all(re.fullmatch(r"[A-Za-z0-9_-]+", p) for p in parts),
          "firebase_token_invalid")
    try:
        decoded = [base64.b64decode(p + "=" * (-len(p) % 4), altchars=b"-_", validate=True)
                   for p in parts]
    except Exception:
        raise OfficialAccountError("firebase_token_invalid") from None
    header, claims = _object_json(decoded[0]), _object_json(decoded[1])
    _need(header.get("alg") == "RS256" and header.get("typ", "JWT") == "JWT"
          and len(decoded[2]) >= 32, "firebase_token_invalid")
    return claims


def _times(claims, now):
    issued, expires = claims.get("iat"), claims.get("exp")
    _need(type(issued) is int and type(expires) is int
          and 0 <= issued < expires <= 253402300799 and expires - issued <= 3600
          and issued <= now + 300 and expires > now, "firebase_token_time_invalid")
    if "auth_time" in claims:
        auth = claims["auth_time"]
        _need(type(auth) is int and 0 <= auth <= issued, "firebase_token_time_invalid")


def _custom_uid(token, now):
    claims = _jwt(token)
    issuer = claims.get("iss")
    _need(_text(issuer, 256) and issuer == claims.get("sub")
          and re.fullmatch(r"[A-Za-z0-9._-]+@" + re.escape(_PROJECT)
                           + r"\.iam\.gserviceaccount\.com", issuer) is not None
          and claims.get("aud") == _AUDIENCE and _text(claims.get("uid"), 128),
          "firebase_scope_mismatch")
    _need("tenant_id" not in claims and "tenantId" not in claims, "firebase_scope_mismatch")
    custom_claims = claims.get("claims", {})
    _need(type(custom_claims) is dict and not any(k in custom_claims
          for k in ("tenant_id", "tenantId", "firebase")), "firebase_scope_mismatch")
    _times(claims, now)
    return claims["uid"]


def _id_token(token, uid, now):
    claims = _jwt(token)
    _need(claims.get("sub") == uid and claims.get("user_id", uid) == uid
          and claims.get("aud") == _PROJECT
          and claims.get("iss") == "https://securetoken.google.com/" + _PROJECT,
          "firebase_scope_mismatch")
    firebase = claims.get("firebase")
    _need(type(firebase) is dict and firebase.get("sign_in_provider") == "custom"
          and firebase.get("tenant") in (None, "")
          and claims.get("tenant_id") in (None, ""), "firebase_scope_mismatch")
    _times(claims, now)


def _config(platform, value):
    if value is None:
        try:
            from .official_account_config import load_public_config
            value = load_public_config(platform)
        except Exception:
            raise OfficialAccountError("official_config_unavailable") from None
    _need(type(value) is dict, "official_config_invalid")
    config = dict(value)
    _need(config.get("project_id") == _PROJECT and config.get("project_number") == _NUMBER
          and config.get("bundle_id") == _BUNDLE and config.get("app_version") == "6.1.1",
          "official_config_scope_mismatch")
    _need(_text(config.get("api_key"), 128)
          and re.fullmatch(r"AIza[A-Za-z0-9_-]{20,80}", config["api_key"]) is not None,
          "official_config_invalid")
    app_id = config.get("google_app_id")
    _need(_text(app_id, 128) and re.fullmatch(r"1:" + _NUMBER + ":" + platform
          + r":[a-f0-9]{16,64}", app_id) is not None, "official_config_scope_mismatch")
    if "certificate_sha1" in config:
        _need(platform == "android" and type(config["certificate_sha1"]) is str
              and re.fullmatch(r"[A-Fa-f0-9]{40}", config["certificate_sha1"]) is not None,
              "official_config_invalid")
    return config


@dataclass(frozen=True, slots=True, repr=False)
class Verification:
    """One inspection's RAM-only ticket. Never serialize this object."""
    public_id: str
    manager_name: str
    manager_level: int
    platform: str
    created_at: int
    expires_at: int
    _owner: object = field(repr=False)
    _token: str = field(repr=False)
    _metadata: dict = field(repr=False)
    _deadline: float = field(repr=False)
    _consumed: bool = field(default=False, repr=False)
    _closed: bool = field(default=False, repr=False)
    _lock: object = field(default_factory=threading.Lock, repr=False)

    def __repr__(self):
        return "<Verification redacted; memory only>"

    @property
    def server_id(self):
        # Migration.linkedUser is transaction.User, which has no identity field.
        return None

    @property
    def consumed(self):
        with self._lock:
            return self._consumed

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def close(self):
        with self._lock:
            object.__setattr__(self, "_closed", True)
            object.__setattr__(self, "_token", "")
            self._metadata.clear()


@dataclass(slots=True, repr=False)
class CollectedAccount:
    """Exact account/master replies only; no authentication response or metadata."""
    user_get: bytes = field(repr=False)
    master_get: bytes = field(repr=False)
    master_version: str
    server_id: str
    public_id: str
    platform: str

    def __repr__(self):
        return "<CollectedAccount private snapshot; credentials excluded>"

    def close(self):
        self.user_get = self.master_get = b""


class OfficialAccountClient:
    def __init__(self, schema, *, platform="ios", transport=None, config=None):
        _need(platform in ("ios", "android") and type(platform) is str, "platform_invalid")
        self._config = _config(platform, config)
        self.schema, self.platform = schema, platform
        self._owner, self._lock = object(), threading.Lock()
        self._verification, self._busy, self._closed = None, False, False
        self._validate_schema()
        if transport is None:
            try:
                from .official_transport import OfficialTransport
                transport = OfficialTransport()
            except Exception as error:
                raise _transport_failure(error, "official_transport_unavailable") from None
        self._transport = transport

    def __repr__(self):
        return "<OfficialAccountClient Japanese transfer; credentials redacted>"

    def _validate_schema(self):
        # Fields used below must retain their original number/type. Unknown reply
        # fields are retained in raw bytes, and never justify another operation.
        contracts = {
            _SYSTEM: ({"firebaseIDToken": (1, 9)}, {"maintenanceInfo": (1, 11), "reviewInfo": (2, 11)}),
            _MIGRATE: ({"userId": (1, 9), "password": (2, 9)}, {"success": (1, 8),
                "linkedUserId": (2, 9), "linkedUser": (3, 11), "onetimeToken": (4, 9)}),
            _EXECUTE: ({"onetimeToken": (1, 9)}, {"token": (1, 9)}),
            _LOGIN: ({"firebaseIDToken": (1, 9)}, {"gameAuthToken": (1, 9),
                "userPublic": (2, 11), "requiredFirebaseReauthenticate": (3, 8)}),
            _MASTER: ({}, {"masterTag": (1, 11)}),
            _USER: ({}, {"user": (1, 11), "userPublic": (999, 11)}),
        }
        try:
            for method, (request, response) in contracts.items():
                descriptor = self.schema.method(method)
                for actual, expected, exact in ((descriptor.input_type, request, True),
                                                (descriptor.output_type, response, False)):
                    fields = actual.fields_by_name
                    _need(not exact or set(fields) == set(expected), "official_schema_unsupported")
                    for name, (number, kind) in expected.items():
                        field = fields[name]
                        _need(field.number == number and field.type == kind
                              and not field.is_repeated, "official_schema_unsupported")
            nested = ((_MIGRATE, "linkedUser", {"name": (1, 9), "managerLevel": (100, 5)}),
                (_USER, "user", {"name": (1, 9), "managerLevel": (100, 5)}),
                (_LOGIN, "userPublic", {"serverUserId": (1, 9), "publicUserId": (2, 9)}),
                (_USER, "userPublic", {"serverUserId": (1, 9), "publicUserId": (2, 9)}),
                (_MASTER, "masterTag", {"version": (1, 9)}),
                (_SYSTEM, "maintenanceInfo", {"inMaintenance": (1, 8), "isBeforeRelease": (6, 8)}),
                (_SYSTEM, "reviewInfo", {"inReview": (1, 8), "alternativeApiHost": (2, 9)}))
            for method, field_name, expected in nested:
                fields = self.schema.method(method).output_type.fields_by_name[field_name].message_type.fields_by_name
                for name, (number, kind) in expected.items():
                    field = fields[name]
                    _need(field.number == number and field.type == kind and not field.is_repeated,
                          "official_schema_unsupported")
        except OfficialAccountError:
            raise
        except Exception:
            raise OfficialAccountError("official_schema_unsupported") from None

    def _check(self, cancel, verification=None):
        _need(not self._closed, "client_closed")
        _need(not _cancelled(cancel), "cancelled")
        if verification is not None:
            _need(not verification.closed, "verification_closed")

    def _progress(self, stage, cancel, progress, verification=None):
        self._check(cancel, verification)
        if progress is not None:
            try:
                progress(stage)
            except Exception:
                raise OfficialAccountError("progress_callback_failed") from None
        self._check(cancel, verification)

    def _call(self, method, metadata, cancel, verification=None, **fields):
        _need(method in _METHODS, "rpc_method_not_allowed")
        self._check(cancel, verification)
        try:
            request = self.schema.request_type(method)(**fields).SerializeToString()
            raw = self._transport.rpc(method, request, dict(metadata), cancel=cancel, timeout=30)
            self._check(cancel, verification)
            _need(type(raw) is bytes and len(raw) <= _MAX_RPC, "rpc_response_invalid")
            return self.schema.response_type(method).FromString(raw), raw
        except OfficialAccountError:
            raise
        except Exception as error:
            self._check(cancel, verification)
            raise _transport_failure(error, "official_rpc_failed") from None

    def _system_check(self, metadata, cancel, verification=None, token=None):
        fields = {} if token is None else {"firebaseIDToken": token}
        response, _ = self._call(_SYSTEM, metadata, cancel, verification, **fields)
        _need(not response.maintenanceInfo.inMaintenance and not response.maintenanceInfo.isBeforeRelease,
              "official_maintenance")
        _need(not response.reviewInfo.inReview and not response.reviewInfo.alternativeApiHost,
              "official_review_unsupported")

    def preflight_master_version(self, expected_version, *, cancel=None, progress=None):
        """Check the public master before any seed, transfer or ticket use.

        Only the existing empty Master.Get and public app-version header are
        sent. The coordinator fixes the expected local version and rechecks its
        original files before calling inspect/fetch. Post-login checks remain.
        """
        _need(_text(expected_version, 256) and expected_version == expected_version.strip(),
              "master_version_invalid")
        with self._lock:
            self._check(cancel)
            _need(not self._busy, "client_busy")
            self._busy = True
        try:
            self._progress("checking", cancel, progress)
            master, _ = self._call(_MASTER, {"x-app-version": self._config["app_version"]}, cancel)
            _need(master.HasField("masterTag") and _text(master.masterTag.version, 256),
                  "master_version_invalid")
            _need(master.masterTag.version == expected_version, "official_master_mismatch")
            return expected_version
        finally:
            with self._lock:
                self._busy = False

    def inspect(self, user_id, password, *, cancel=None, progress=None):
        _need(_identity(user_id) and len(user_id) <= 64, "transfer_id_invalid")
        # Exact current password character/length policy is not established by
        # the original descriptor. Bound it without copying an old guide's rule.
        _need(_text(password, 128) and password == password.strip(), "transfer_password_invalid")
        with self._lock:
            _need(not self._closed, "client_closed")
            _need(not self._busy, "client_busy")
            self._busy = True
            if self._verification is not None:
                self._verification.close()
            self._verification = None
        metadata = {}
        try:
            self._progress("preparing", cancel, progress)
            device, advertising = uuid.uuid4().hex, str(uuid.uuid4())
            seed_headers = {"X-Device": device, "X-Ad": advertising, "X-App": _BUNDLE,
                "X-AppVersion": self._config["app_version"], "X-SeedVersion": "1.0.1"}
            try:
                seed = self._transport.seed(seed_headers, cancel=cancel)
            except Exception as error:
                self._check(cancel)
                raise _transport_failure(error, "official_seed_failed") from None
            self._check(cancel)
            _need(_text(seed, 4096) and seed == seed.strip(), "official_seed_invalid")
            metadata.update({"x-app-version": self._config["app_version"],
                "x-platform": "iOS" if self.platform == "ios" else "Android",
                "x-seed-id": seed, "x-ad-id": advertising})
            self._progress("checking", cancel, progress)
            self._system_check({"x-app-version": self._config["app_version"]}, cancel)
            self._progress("verifying", cancel, progress)
            response, _ = self._call(_MIGRATE, metadata, cancel, userId=user_id, password=password)
            password = None
            _need(response.success and response.linkedUserId == user_id
                  and _text(response.onetimeToken) and response.HasField("linkedUser"),
                  "transfer_rejected")
            name, level = response.linkedUser.name, response.linkedUser.managerLevel
            _need(type(name) is str and name.strip() and len(name.encode("utf-8")) <= 128
                  and 1 <= level <= 2147483647, "linked_user_invalid")
            self._progress("verified", cancel, progress)
            now = int(time.time())
            result = Verification(user_id, name, level, self.platform, now, now + _TTL,
                self._owner, response.onetimeToken, dict(metadata), time.monotonic() + _TTL)
            try:
                with self._lock:
                    self._check(cancel)
                    self._verification = result
                return result
            except BaseException:
                result.close()
                raise
        finally:
            password = None
            metadata.clear()
            with self._lock:
                self._busy = False

    def _firebase(self, operation, body, cancel, verification):
        self._check(cancel, verification)
        headers = {"X-Firebase-GMPID": self._config["google_app_id"]}
        if self.platform == "ios":
            headers["X-Ios-Bundle-Identifier"] = _BUNDLE
        else:
            headers["X-Android-Package"] = _BUNDLE
            if "certificate_sha1" in self._config:
                headers["X-Android-Cert"] = self._config["certificate_sha1"].upper()
        try:
            response = self._transport.firebase(operation, self._config["api_key"], body,
                                                 headers, cancel=cancel)
            self._check(cancel, verification)
            _need(type(response) is dict, "firebase_response_invalid")
            return response
        except OfficialAccountError:
            raise
        except Exception as error:
            self._check(cancel, verification)
            raise _transport_failure(error, "official_firebase_failed") from None

    def fetch(self, verification, *, cancel=None, progress=None):
        self._check(cancel)
        with self._lock:
            _need(not self._busy, "client_busy")
            _need(type(verification) is Verification and verification is self._verification
                  and verification._owner is self._owner, "verification_invalid")
            with verification._lock:
                _need(not verification._closed, "verification_closed")
                _need(not verification._consumed, "verification_consumed")
                if time.monotonic() >= verification._deadline:
                    object.__setattr__(verification, "_closed", True)
                    object.__setattr__(verification, "_token", "")
                    verification._metadata.clear()
                    raise OfficialAccountError("verification_expired")
                # Consume before any Execute attempt, including a lost response.
                object.__setattr__(verification, "_consumed", True)
                ticket, metadata = verification._token, dict(verification._metadata)
                object.__setattr__(verification, "_token", "")
            self._busy = True
        credentials = {value for value in (ticket, metadata.get("x-seed-id"))
                       if _text(value) and len(value) >= 16}
        try:
            self._progress("transferring", cancel, progress, verification)
            execute, _ = self._call(_EXECUTE, metadata, cancel, verification, onetimeToken=ticket)
            ticket = None
            uid = _custom_uid(execute.token, int(time.time()))
            credentials.add(execute.token)
            self._progress("firebase", cancel, progress, verification)
            signin = self._firebase("signin", {"token": execute.token, "returnSecureToken": True},
                                    cancel, verification)
            execute.Clear()
            identity = signin.get("idToken")
            for value in (identity, signin.get("refreshToken")):
                if _text(value) and len(value) >= 16:
                    credentials.add(value)
            _need(signin.get("localId", uid) == uid and _text(identity), "firebase_scope_mismatch")
            lifetime = signin.get("expiresIn")
            _need(type(lifetime) is str and lifetime.isascii() and lifetime.isdigit()
                  and 0 < len(lifetime) <= 5 and 0 < int(lifetime) <= 3600,
                  "firebase_response_invalid")
            _id_token(identity, uid, int(time.time()))
            signin.clear()  # Do not retain the refresh token returned by Firebase.
            lookup = self._firebase("lookup", {"idToken": identity}, cancel, verification)
            users = lookup.get("users")
            _need(type(users) is list and len(users) == 1 and type(users[0]) is dict
                  and users[0].get("localId") == uid
                  and users[0].get("tenantId") in (None, "")
                  and users[0].get("disabled", False) is False, "firebase_scope_mismatch")
            lookup.clear()
            self._progress("login", cancel, progress, verification)
            self._system_check(metadata, cancel, verification, identity)
            login, _ = self._call(_LOGIN, metadata, cancel, verification, firebaseIDToken=identity)
            identity = None
            _need(not login.requiredFirebaseReauthenticate and _text(login.gameAuthToken),
                  "official_reauthentication_required")
            _need(login.HasField("userPublic"), "account_identity_mismatch")
            server_id, public_id = login.userPublic.serverUserId, login.userPublic.publicUserId
            _need(_identity(server_id) and _identity(public_id)
                  and verification.public_id in (server_id, public_id), "account_identity_mismatch")
            metadata["x-auth-token"] = login.gameAuthToken
            if len(login.gameAuthToken) >= 16:
                credentials.add(login.gameAuthToken)
            login.Clear()
            self._progress("master", cancel, progress, verification)
            master, master_raw = self._call(_MASTER, metadata, cancel, verification)
            _need(master.HasField("masterTag") and _text(master.masterTag.version, 256),
                  "master_version_invalid")
            version = master.masterTag.version
            metadata["x-master-version"] = version
            self._progress("account", cancel, progress, verification)
            user, user_raw = self._call(_USER, metadata, cancel, verification)
            _need(user.HasField("userPublic") and user.userPublic.serverUserId == server_id
                  and user.userPublic.publicUserId == public_id and user.HasField("user")
                  and user.user.name.strip() and len(user.user.name.encode("utf-8")) <= 128,
                  "account_identity_mismatch")
            # Preserve original account bytes, but reject literal reflection of
            # the long credentials this fetch actually obtained. This is not a
            # universal classifier for arbitrary private server fields/passwords.
            _need(not any(value.encode("ascii") in raw for value in credentials
                          for raw in (user_raw, master_raw)), "credential_reflected")
            self._progress("collected", cancel, progress, verification)
            return CollectedAccount(user_raw, master_raw, version, server_id, public_id, self.platform)
        finally:
            ticket = identity = None
            credentials.clear()
            metadata.clear()
            verification.close()
            with self._lock:
                self._busy = False

    def forget(self):
        with self._lock:
            if self._verification is not None:
                self._verification.close()
            self._verification = None

    def close(self):
        with self._lock:
            self._closed = True
            if self._verification is not None:
                self._verification.close()
            self._verification = None
        close = getattr(self._transport, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
