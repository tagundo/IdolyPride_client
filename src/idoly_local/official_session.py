"""Explicit, user-local login using an existing PlayCover Firebase identity.

No account creation, inheritance, daily initialization, gameplay, persistence or
automatic retry exists here. Token claims are checked for scope, not treated as
cryptographically verified; the official TLS services authenticate the token.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import uuid

import grpc

from . import codec
from .collect import OFFICIAL_TARGET, _application_codes, _tls_credentials
from .firebase_archive import (FirebaseArchiveCredentials, FirebaseArchiveError,
    _jwt, parse_firebase_archive, select_candidate, summarize_candidates)

BUNDLE = "game.qualiarts.idolypride"
GOOGLE_APP_ID = "1:543065248020:ios:babf05d967621a37ab3201"
PROJECT_ID = "solis-firebase"
APP_VERSION = "6.1.1"
_PROJECT_NUMBER = "543065248020"
_SEED_URL = "https://id.qseed.jp/getId"
_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
_SYSTEM = "/api.System/Check"
_LOGIN = "/api.Auth/Login"
_MASTER = "/api.Master/Get"
LOGIN_METHODS = frozenset((_SYSTEM, _LOGIN, _MASTER))
_MAX_HTTP = 128 * 1024
_MAX_RPC = 17 * 1024 * 1024


class OfficialSessionError(RuntimeError):
    """A fixed code only; never include HTTP/RPC details or credentials."""
    def __init__(self, code):
        self.code = code
        super().__init__("Official session stopped: " + code)


def _need(condition, code):
    if not condition:
        raise OfficialSessionError(code)


def _ascii(value, maximum=16384):
    return type(value) is str and 0 < len(value) <= maximum and all(32 <= ord(c) < 127 for c in value)


def _hex_binding(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _account_binding(candidate, nonce):
    """An inspection-local opaque selection, independent of token rotation.

    The worker keeps the random nonce and resulting binding in memory. Neither
    the UID nor a stable cross-inspection account fingerprint reaches its UI.
    """
    _need(_hex_binding(nonce), "account_binding_invalid")
    scope = json.dumps(["idolypride-playcover-account-binding-v1", candidate.app_id,
        candidate.project_id, candidate.api_key, candidate.firebase_uid],
        ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(bytes.fromhex(nonce) + scope).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class ArchiveInventory:
    candidates: tuple[FirebaseArchiveCredentials, ...] = field(repr=False)
    matched_rows: int
    rejected_archives: int

    def __repr__(self):
        return "<ArchiveInventory redacted>"

    def summary(self, *, now: int, binding_nonce: str | None = None):
        if binding_nonce is not None:
            _need(_hex_binding(binding_nonce), "account_binding_invalid")
        try:
            groups = summarize_candidates(list(self.candidates), now=now) if self.candidates else ()
        except FirebaseArchiveError:
            raise OfficialSessionError("archive_scopes_differ") from None
        first = list({candidate.firebase_uid: candidate for candidate in self.candidates}.values())
        return {"status": "inspected", "matched_rows": self.matched_rows,
            "valid_archives": len(self.candidates), "rejected_archives": self.rejected_archives,
            "account_groups": len(groups), "groups": [
                {"group_number": g.group_number, "candidate_count": g.candidate_count,
                 "current_candidate_count": g.current_candidate_count,
                 **({"binding": _account_binding(first[index], binding_nonce)}
                    if binding_nonce is not None else {})} for index, g in enumerate(groups)]}

    def select(self, *, now: int, group_number: int | None = None,
               binding_nonce: str | None = None, expected_group_binding: str | None = None):
        _need(not self.rejected_archives, "archive_candidates_invalid")
        bound = binding_nonce is not None or expected_group_binding is not None
        if bound:
            _need(_hex_binding(binding_nonce) and _hex_binding(expected_group_binding),
                  "account_binding_invalid")
        try:
            candidate = select_candidate(list(self.candidates), now=now, group_number=group_number,
                                         require_current=False)
        except FirebaseArchiveError:
            # The caller can inspect safe group numbers without exposing UIDs.
            raise OfficialSessionError("account_selection_required_or_invalid") from None
        if bound:
            _need(hmac.compare_digest(_account_binding(candidate, binding_nonce), expected_group_binding),
                  "account_inventory_changed")
        return candidate


def inspect_archives(archives) -> ArchiveInventory:
    """Parse opaque in-memory blobs; this function never opens a network/file."""
    _need(type(archives) in (list, tuple) and 0 < len(archives) <= 4096, "archive_rows_invalid")
    candidates, rejected = [], 0
    for raw in archives:
        try:
            candidates.append(parse_firebase_archive(raw, expected_app_id=GOOGLE_APP_ID,
                                                     expected_project_id=PROJECT_ID))
        except FirebaseArchiveError:
            rejected += 1
    return ArchiveInventory(tuple(candidates), len(archives), rejected)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise OfficialSessionError("http_redirect_rejected")


class OfficialHttp:
    """Only the two fixed HTTPS operations required by an existing login."""
    def __init__(self, *, roots_file: Path | None = None):
        try:
            context = ssl.create_default_context(cafile=str(roots_file) if roots_file else None)
            self._opener = build_opener(HTTPSHandler(context=context), _NoRedirect())
        except Exception:
            raise OfficialSessionError("tls_roots_invalid") from None

    def __repr__(self):
        return "<OfficialHttp fixed verified TLS endpoints>"

    def _request(self, request, *, limit):
        parsed = urlsplit(request.full_url)
        allowed = ((parsed.scheme == "https" and parsed.netloc == "id.qseed.jp"
                    and parsed.path == "/getId" and not parsed.query and request.get_method() == "GET")
                   or (parsed.scheme == "https" and parsed.netloc == "securetoken.googleapis.com"
                       and parsed.path == "/v1/token" and request.get_method() == "POST"
                       and parsed.query.startswith("key=") and "&" not in parsed.query))
        _need(allowed and not parsed.fragment, "http_target_not_allowed")
        try:
            with self._opener.open(request, timeout=30) as response:
                _need(response.status == 200, "http_request_rejected")
                # Even a custom opener must not silently follow redirects.
                _need(response.geturl() == request.full_url, "http_redirect_rejected")
                raw = response.read(limit + 1)
                _need(len(raw) <= limit, "http_response_too_large")
                return raw
        except OfficialSessionError:
            raise
        except HTTPError as error:
            code = "http_redirect_rejected" if 300 <= error.code < 400 else "http_request_rejected"
            error.close()
            raise OfficialSessionError(code) from None
        except Exception:
            raise OfficialSessionError("http_transport_failed") from None

    def refresh(self, credentials):
        request = Request(_TOKEN_URL + "?" + urlencode({"key": credentials.api_key}),
            data=urlencode({"grant_type": "refresh_token", "refresh_token": credentials.refresh_token}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "X-Ios-Bundle-Identifier": BUNDLE, "X-Firebase-GMPID": GOOGLE_APP_ID}, method="POST")
        raw = self._request(request, limit=_MAX_HTTP)
        try:
            result = json.loads(raw)
        except Exception:
            raise OfficialSessionError("firebase_response_invalid") from None
        _need(type(result) is dict, "firebase_response_invalid")
        return result

    def seed(self, device_id, advertising_id):
        request = Request(_SEED_URL, headers={"X-Device": device_id, "X-Ad": advertising_id,
            "X-App": BUNDLE, "X-AppVersion": APP_VERSION, "X-SeedVersion": "1.0.1"}, method="GET")
        try:
            value = self._request(request, limit=4096).decode("ascii")
        except UnicodeError:
            raise OfficialSessionError("seed_response_invalid") from None
        _need(_ascii(value, 4096) and value == value.strip(), "seed_response_invalid")
        return value


@dataclass(slots=True, repr=False)
class OfficialSession:
    metadata: dict[str, str] = field(repr=False)

    def __repr__(self):
        return "<OfficialSession credentials redacted; memory only>"

    def close(self):
        self.metadata.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _existing_token(credentials, *, now, http):
    _need(type(credentials) is FirebaseArchiveCredentials and credentials.app_id == GOOGLE_APP_ID
          and credentials.project_id == PROJECT_ID and _ascii(credentials.api_key)
          and _ascii(credentials.refresh_token), "firebase_scope_invalid")
    try:
        issued, expires = _jwt(credentials.id_token, credentials.firebase_uid, PROJECT_ID)
    except FirebaseArchiveError:
        raise OfficialSessionError("firebase_scope_invalid") from None
    _need(issued <= now + 300, "firebase_token_time_invalid")
    if expires > now:
        return credentials.id_token
    response = http.refresh(credentials)
    _need(type(response) is dict and response.get("user_id") == credentials.firebase_uid
          and response.get("project_id") == _PROJECT_NUMBER, "firebase_refresh_scope_mismatch")
    token = response.get("id_token")
    _need(_ascii(token) and _ascii(response.get("refresh_token")), "firebase_response_invalid")
    lifetime = response.get("expires_in")
    _need(type(lifetime) is str and lifetime.isascii() and lifetime.isdigit()
          and 0 < len(lifetime) <= 5 and 0 < int(lifetime) <= 86400, "firebase_response_invalid")
    try:
        issued, expires = _jwt(token, credentials.firebase_uid, PROJECT_ID)
    except FirebaseArchiveError:
        raise OfficialSessionError("firebase_refresh_scope_mismatch") from None
    _need(issued <= now + 300 and expires > now, "firebase_token_time_invalid")
    return token


def _call(schema, channel, method, metadata, **fields):
    _need(method in LOGIN_METHODS, "rpc_method_not_allowed")
    try:
        request = schema.request_type(method)(**fields).SerializeToString()
        raw, call = channel.unary_unary(method).with_call(codec.encode(request),
            metadata=list(metadata.items()), timeout=30)
        _need(call.code() == grpc.StatusCode.OK, "rpc_failed")
        _need(not _application_codes(call), "application_error")
        _need(type(raw) is bytes and len(raw) <= _MAX_RPC, "rpc_response_invalid")
        plain = codec.decode(raw)
        _need(len(plain) <= _MAX_RPC, "rpc_response_invalid")
        return schema.response_type(method).FromString(plain)
    except OfficialSessionError:
        raise
    except Exception:
        raise OfficialSessionError("rpc_failed") from None


def login_existing_account(schema, credentials, *, login_existing_account=False,
                           roots_file=None, now=None, http=None) -> OfficialSession:
    """One explicitly authorized existing-account login; credentials stay in RAM.

    A refresh is performed only for an expired token. Reauthentication requests
    stop immediately, with no retries, signup, inheritance or creation fallback.
    """
    _need(login_existing_account is True, "existing_login_opt_in_required")
    now = int(time.time()) if now is None else now
    _need(type(now) is int and 0 <= now <= 253402300799, "time_invalid")
    try:
        for method in LOGIN_METHODS:
            schema.method(method)
        http = OfficialHttp(roots_file=roots_file) if http is None else http
        token = _existing_token(credentials, now=now, http=http)
        device_id, advertising_id = uuid.uuid4().hex, str(uuid.uuid4())
        seed = http.seed(device_id, advertising_id)
        _need(_ascii(seed, 4096), "seed_response_invalid")
        metadata = {"x-app-version": APP_VERSION, "x-platform": "iOS",
                    "x-seed-id": seed, "x-ad-id": advertising_id}
        tls = _tls_credentials(roots_file)
        with grpc.secure_channel(OFFICIAL_TARGET, tls, options=(
                ("grpc.enable_retries", 0), ("grpc.max_receive_message_length", _MAX_RPC))) as channel:
            _call(schema, channel, _SYSTEM, {"x-app-version": APP_VERSION})
            _call(schema, channel, _SYSTEM, metadata, firebaseIDToken=token)
            login = _call(schema, channel, _LOGIN, metadata, firebaseIDToken=token)
            _need(not login.requiredFirebaseReauthenticate and _ascii(login.gameAuthToken),
                  "existing_account_login_rejected")
            metadata["x-auth-token"] = login.gameAuthToken
            master = _call(schema, channel, _MASTER, metadata)
            _need(master.HasField("masterTag") and _ascii(master.masterTag.version, 256),
                  "master_version_invalid")
            metadata["x-master-version"] = master.masterTag.version
        return OfficialSession(metadata)
    except OfficialSessionError:
        raise
    except Exception:
        raise OfficialSessionError("existing_login_failed") from None
