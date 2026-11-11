"""Read existing Firebase iOS user archives without native unarchiving or I/O.

The field names are pinned to firebase-ios-sdk 11.14.0, commit
45d327fcbe7793747295346c2209ad419bdead74: User.swift (FIRUser) and
SecureTokenService.swift (FIRSecureTokenService). These archives and JWT claims
are untrusted local input. No JWT signature is verified here, and loading an
archive does not establish that its credentials are accepted by Firebase.

Secret-bearing return objects are memory-only and deliberately have no useful
repr. Callers must never serialize them, include them in logs, or send them to
any endpoint other than the explicitly selected official account operation.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import plistlib
import re


_MAX_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS = 4096
_MAX_NODES = 32768
_MAX_DEPTH = 64
_MAX_CONTAINER = 4096
_MAX_TOKEN = 16384
_MAX_UNIX = 253402300799
_COCOA_EPOCH = 978307200
_PROJECT = re.compile(r"[a-z][a-z0-9-]{3,62}\Z")
_APP = re.compile(r"[0-9]+:[0-9]+:ios:[a-fA-F0-9]+\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")


class FirebaseArchiveError(ValueError):
    """Only fixed, credential-free errors leave this reader."""


def _need(value, code):
    if not value:
        raise FirebaseArchiveError(code)


@dataclass(frozen=True, slots=True, repr=False)
class FirebaseArchiveCredentials:
    firebase_uid: str = field(repr=False)
    app_id: str = field(repr=False)
    project_id: str = field(repr=False)
    api_key: str = field(repr=False)
    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    issued_at: int = field(repr=False)
    expires_at: int = field(repr=False)
    stored_expiration: float | None = field(repr=False)
    signature_verified: bool = field(default=False, init=False, repr=False)

    def __repr__(self):
        return "<FirebaseArchiveCredentials redacted; signature unverified>"

    @property
    def google_app_id(self) -> str:
        return self.app_id

    @property
    def access_token(self) -> str:
        return self.id_token

    @property
    def expires_at_ms(self) -> int:
        return self.expires_at * 1000

    def is_current(self, now: int) -> bool:
        _time(now)
        return self.issued_at <= now + 300 and self.expires_at > now


@dataclass(frozen=True, slots=True)
class FirebaseArchiveGroup:
    """Opaque selection information; never an account identifier or token."""
    group_number: int
    candidate_count: int
    current_candidate_count: int
    latest_issued_at: int


def _time(value):
    _need(type(value) is int and 0 <= value <= _MAX_UNIX, "invalid_time")


def _text(value, code, *, maximum=1024):
    _need(type(value) is str and 0 < len(value) <= maximum
          and not any(ord(char) < 33 or ord(char) == 127 for char in value), code)
    return value


class _Archive:
    def __init__(self, raw):
        _need(type(raw) is bytes and 40 <= len(raw) <= _MAX_BYTES, "archive_size_or_type")
        # NSKeyedArchiver emits binary plists. Bound the binary table before
        # plistlib allocates its object vector; XML/native deserialization is
        # intentionally outside this reader's supported input.
        _need(raw.startswith(b"bplist00"), "unsupported_archive_format")
        trailer = raw[-32:]
        offset_size, reference_size = trailer[6], trailer[7]
        count = int.from_bytes(trailer[8:16], "big")
        top = int.from_bytes(trailer[16:24], "big")
        offsets = int.from_bytes(trailer[24:32], "big")
        _need(offset_size in (1, 2, 4, 8) and reference_size in (1, 2, 4, 8)
              and 0 < count <= _MAX_OBJECTS and top < count
              and 8 <= offsets <= len(raw) - 32
              and offsets + count * offset_size == len(raw) - 32,
              "invalid_archive_table")
        try:
            document = plistlib.loads(raw)
        except Exception:
            raise FirebaseArchiveError("invalid_archive_plist") from None
        _need(type(document) is dict and document.get("$archiver") == "NSKeyedArchiver"
              and document.get("$version") == 100000, "unsupported_archive_schema")
        self.objects = document.get("$objects")
        _need(type(self.objects) is list and 1 < len(self.objects) <= _MAX_OBJECTS
              and self.objects[0] == "$null", "invalid_archive_objects")
        self._validate_graph(document)
        roots = document.get("$top")
        _need(type(roots) is dict and set(roots) == {"root"}, "ambiguous_archive_root")
        self.root = self.object(roots["root"], "FIRUser")

    def _validate_graph(self, document):
        # Inspect every container without expanding references into copies.
        # This bounds both disconnected garbage and the selected object graph.
        stack, nodes = [(document, 0)], 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            _need(nodes <= _MAX_NODES and depth <= _MAX_DEPTH, "archive_graph_limit")
            if type(value) is plistlib.UID:
                _need(0 <= value.data < len(self.objects), "invalid_archive_reference")
            elif type(value) is dict:
                _need(len(value) <= _MAX_CONTAINER and all(type(k) is str for k in value),
                      "invalid_archive_container")
                stack.extend((v, depth + 1) for v in value.values())
            elif type(value) is list:
                _need(len(value) <= _MAX_CONTAINER, "invalid_archive_container")
                stack.extend((v, depth + 1) for v in value)
            elif type(value) in (str, bytes):
                _need(len(value) <= _MAX_BYTES, "archive_value_limit")
            elif type(value) not in (int, float, bool):
                _need(False, "unsupported_archive_value")
        # Reject reference cycles even in fields that this reader never uses.
        colors = [0] * len(self.objects)
        def refs(value):
            pending = [value]
            while pending:
                item = pending.pop()
                if type(item) is plistlib.UID:
                    yield item.data
                elif type(item) is dict:
                    pending.extend(item.values())
                elif type(item) is list:
                    pending.extend(item)
        for start in range(len(self.objects)):
            if colors[start]:
                continue
            traversal = [(start, iter(refs(self.objects[start])))]
            colors[start] = 1
            while traversal:
                _need(len(traversal) <= _MAX_DEPTH, "archive_graph_limit")
                index, children = traversal[-1]
                child = next(children, None)
                if child is None:
                    colors[index] = 2
                    traversal.pop()
                elif colors[child] == 1:
                    _need(False, "cyclic_archive_reference")
                elif colors[child] == 0:
                    colors[child] = 1
                    traversal.append((child, iter(refs(self.objects[child]))))

    def value(self, value):
        if type(value) is plistlib.UID:
            if value.data == 0:
                return None
            return self.objects[value.data]
        return value

    def object(self, reference, class_name):
        value = self.value(reference)
        _need(type(value) is dict and "$class" in value, "invalid_archive_object")
        info = self.value(value["$class"])
        _need(type(info) is dict and info.get("$classname") == class_name
              and type(info.get("$classes")) is list
              and info["$classes"] == [class_name, "NSObject"], "unexpected_archive_class")
        return value

    def text(self, obj, key, *, maximum=1024):
        return _text(self.value(obj.get(key)), "missing_or_invalid_archive_field", maximum=maximum)

    def date(self, reference):
        if self.value(reference) is None:
            return None
        date = self.object(reference, "NSDate")
        value = date.get("NS.time")
        # Check bounds before converting arbitrary plist integers to float.
        # Chained comparisons also reject NaN/infinity without an overflow.
        _need(type(value) in (int, float)
              and -_COCOA_EPOCH <= value <= _MAX_UNIX - _COCOA_EPOCH,
              "invalid_archive_date")
        unix = value + _COCOA_EPOCH
        return float(unix)


def _json_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "invalid_token_claims")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception:
        raise FirebaseArchiveError("invalid_token_claims") from None
    _need(type(value) is dict, "invalid_token_claims")
    return value


def _jwt(token, uid, project_id):
    _text(token, "invalid_id_token", maximum=_MAX_TOKEN)
    parts = token.split(".")
    _need(len(parts) == 3 and all(_BASE64URL.fullmatch(p) for p in parts), "invalid_id_token")
    try:
        decoded = [base64.b64decode(p + "=" * (-len(p) % 4), altchars=b"-_", validate=True) for p in parts]
    except Exception:
        raise FirebaseArchiveError("invalid_id_token") from None
    header, claims = _json_object(decoded[0]), _json_object(decoded[1])
    _need(header.get("alg") == "RS256" and header.get("typ", "JWT") == "JWT"
          and len(decoded[2]) >= 32, "unsupported_id_token")
    _need(claims.get("aud") == project_id
          and claims.get("iss") == "https://securetoken.google.com/" + project_id
          and claims.get("sub") == uid, "token_scope_mismatch")
    firebase = claims.get("firebase", {})
    _need(type(firebase) is dict, "invalid_token_claims")
    _need(firebase.get("tenant") in (None, ""), "unsupported_tenant")
    issued, expires = claims.get("iat"), claims.get("exp")
    _time(issued)
    _time(expires)
    _need(issued < expires and expires - issued <= 86400, "invalid_token_times")
    if "auth_time" in claims:
        _time(claims["auth_time"])
        _need(claims["auth_time"] <= issued, "invalid_token_times")
    return issued, expires


def parse_firebase_archive(raw: bytes, *, expected_app_id: str, expected_project_id: str,
                           expected_api_key: str | None = None) -> FirebaseArchiveCredentials:
    """Decode one SDK user record; this performs no file, native or network I/O."""
    _need(type(expected_app_id) is str and _APP.fullmatch(expected_app_id), "invalid_expected_app")
    _need(type(expected_project_id) is str and _PROJECT.fullmatch(expected_project_id),
          "invalid_expected_project")
    if expected_api_key is not None:
        _text(expected_api_key, "invalid_expected_api_key")
    archive = _Archive(raw)
    user = archive.root
    uid = archive.text(user, "userID", maximum=128)
    app_id = archive.text(user, "firebaseAppID")
    _need(app_id == expected_app_id, "archive_app_mismatch")
    # No tenant fallback: a caller must not authenticate a different tenant.
    _need(archive.value(user.get("tenantID")) in (None, ""), "unsupported_tenant")
    api_key = archive.text(user, "APIKey")
    _need(expected_api_key is None or api_key == expected_api_key, "archive_api_key_mismatch")
    service = archive.object(user.get("tokenService"), "FIRSecureTokenService")
    service_api_key = archive.value(service.get("APIKey"))
    _need(service_api_key in (None, api_key), "archive_api_key_mismatch")
    id_token = archive.text(service, "accessToken", maximum=_MAX_TOKEN)
    refresh_token = archive.text(service, "refreshToken", maximum=_MAX_TOKEN)
    issued, expires = _jwt(id_token, uid, expected_project_id)
    return FirebaseArchiveCredentials(uid, app_id, expected_project_id, api_key, id_token,
        refresh_token, issued, expires, archive.date(service.get("accessTokenExpirationDate")))


def _groups(candidates):
    _need(type(candidates) in (tuple, list) and 0 < len(candidates) <= 4096,
          "invalid_candidates")
    grouped = {}
    scope = None
    for candidate in candidates:
        _need(type(candidate) is FirebaseArchiveCredentials, "invalid_candidates")
        current_scope = (candidate.app_id, candidate.project_id, candidate.api_key)
        scope = current_scope if scope is None else scope
        _need(scope == current_scope, "mixed_candidate_scopes")
        grouped.setdefault(candidate.firebase_uid, []).append(candidate)
    return tuple(grouped.values())


def summarize_candidates(candidates, *, now: int) -> tuple[FirebaseArchiveGroup, ...]:
    """Return only numbered account groups, counts and issuance timestamps."""
    _time(now)
    return tuple(FirebaseArchiveGroup(index, len(group),
        sum(candidate.is_current(now) for candidate in group),
        max(candidate.issued_at for candidate in group))
        for index, group in enumerate(_groups(candidates), 1))


def select_candidate(candidates, *, now: int, group_number: int | None = None,
                     require_current: bool = True) -> FirebaseArchiveCredentials:
    """Select within one account only; never infer an active account across UIDs.

    require_current=False explicitly permits an expired *offline* refresh
    candidate. It does not refresh, log in, or establish server validity.
    """
    _time(now)
    _need(type(require_current) is bool, "invalid_candidate_selection")
    groups = _groups(candidates)
    if group_number is None:
        _need(len(groups) == 1, "multiple_accounts_require_selection")
        group_number = 1
    _need(type(group_number) is int and 1 <= group_number <= len(groups), "invalid_group_number")
    eligible = [candidate for candidate in groups[group_number - 1]
                if candidate.issued_at <= now + 300 and (not require_current or candidate.is_current(now))]
    _need(eligible, "no_current_candidate" if require_current else "no_eligible_candidate")
    newest = max(candidate.issued_at for candidate in eligible)
    tied = [candidate for candidate in eligible if candidate.issued_at == newest]
    _need(len({(c.id_token, c.refresh_token) for c in tied}) == 1, "ambiguous_same_time_candidates")
    return tied[0]
