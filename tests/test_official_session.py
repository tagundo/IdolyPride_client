"""Synthetic archives and fake transports only; never contact an account."""
import base64
import importlib.util
import json
from pathlib import Path
import plistlib
import ssl
from urllib.request import Request

import grpc
import pytest

from idoly_local import codec, official_session as module
from idoly_local.official_session import (APP_VERSION, GOOGLE_APP_ID, PROJECT_ID,
    OfficialHttp, OfficialSessionError, inspect_archives, login_existing_account)
from idoly_local.schema import Schema

NOW = 1794350000
UID = "SYNTHETIC_PRIVATE_UID"
REFRESH = "SYNTHETIC_PRIVATE_REFRESH_TOKEN"
KEY = "SYNTHETIC_PUBLIC_API_KEY"
GAME = "SYNTHETIC_PRIVATE_GAME_AUTH_TOKEN"
SEED = "SYNTHETIC_PRIVATE_SEED"
NONCE = "a5" * 32
ROOT = Path(__file__).resolve().parents[1]


def token(uid=UID, issued=NOW - 100, expires=NOW + 3500, **changes):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    claims = {"sub": uid, "aud": PROJECT_ID, "iss": "https://securetoken.google.com/" + PROJECT_ID,
              "iat": issued, "exp": expires, "auth_time": issued - 1}
    claims.update(changes)
    return encode({"alg": "RS256", "typ": "JWT"}) + "." + encode(claims) + "." + \
        base64.urlsafe_b64encode(b"inert-synthetic-signature-1234567890").decode().rstrip("=")


def archive(uid=UID, issued=NOW - 100, expires=NOW + 3500, **claims):
    objects = ["$null"]
    def add(value):
        objects.append(value)
        return plistlib.UID(len(objects) - 1)
    def cls(name):
        return add({"$classname": name, "$classes": [name, "NSObject"]})
    user_cls, service_cls, date_cls = cls("FIRUser"), cls("FIRSecureTokenService"), cls("NSDate")
    date = add({"$class": date_cls, "NS.time": float(expires - 978307200)})
    service = add({"$class": service_cls, "accessToken": add(token(uid, issued, expires, **claims)),
                   "refreshToken": add(REFRESH), "accessTokenExpirationDate": date, "APIKey": add(KEY)})
    root = add({"$class": user_cls, "userID": add(uid), "firebaseAppID": add(GOOGLE_APP_ID),
                "APIKey": add(KEY), "tokenService": service, "tenantID": plistlib.UID(0)})
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                          "$objects": objects, "$top": {"root": root}}, fmt=plistlib.FMT_BINARY)


def credentials(**kwargs):
    return inspect_archives([archive(**kwargs)]).select(now=NOW)


@pytest.fixture(scope="module")
def schema():
    return Schema.from_descriptor_set(ROOT / "data/protocol/idolypride-6.1.1.pb")


class Http:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {"id_token": token(issued=NOW, expires=NOW + 3600),
            "refresh_token": "SYNTHETIC_ROTATED_REFRESH", "user_id": UID,
            "project_id": "543065248020", "expires_in": "3600"}

    def refresh(self, candidate):
        self.calls.append(("refresh", candidate))
        return self.response

    def seed(self, device, advertising):
        self.calls.append(("seed", device, advertising))
        return SEED


class Call:
    def __init__(self, metadata=()): self.headers = metadata
    def code(self): return grpc.StatusCode.OK
    def initial_metadata(self): return self.headers
    def trailing_metadata(self): return ()


class Channel:
    def __init__(self, schema, *, reauthenticate=False, metadata=(), broken=False):
        self.schema, self.calls = schema, []
        self.reauthenticate, self.metadata, self.broken = reauthenticate, metadata, broken
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def unary_unary(self, method):
        assert method in module.LOGIN_METHODS
        channel = self
        class RPC:
            def with_call(self, raw, *, metadata, timeout):
                request = channel.schema.request_type(method).FromString(codec.decode(raw))
                channel.calls.append((method, request, dict(metadata), timeout))
                if channel.broken:
                    raise RuntimeError("REMOTE_PRIVATE_ERROR " + GAME + REFRESH)
                response = channel.schema.response_type(method)()
                if method == "/api.Auth/Login":
                    response.gameAuthToken = GAME
                    response.requiredFirebaseReauthenticate = channel.reauthenticate
                if method == "/api.Master/Get": response.masterTag.version = "synthetic-master-version"
                return codec.encode(response.SerializeToString()), Call(channel.metadata)
        return RPC()


def install_channel(monkeypatch, schema, **kwargs):
    channel, connections = Channel(schema, **kwargs), []
    monkeypatch.setattr(module, "_tls_credentials", lambda path: "verified-tls-sentinel")
    def connect(target, credentials, *, options):
        connections.append((target, credentials, dict(options)))
        return channel
    monkeypatch.setattr(module.grpc, "secure_channel", connect)
    return channel, connections


def assert_redacted(value):
    for private in (UID, REFRESH, KEY, GAME, SEED, token()):
        assert private not in str(value) and private not in repr(value)


def test_inventory_latest_same_uid_and_128_accounts_require_selection():
    same = inspect_archives([archive(issued=NOW - i - 1) for i in range(128)])
    assert same.summary(now=NOW)["account_groups"] == 1
    assert same.select(now=NOW).issued_at == NOW - 1
    assert_redacted(same)
    mixed = inspect_archives([archive(uid="SYNTHETIC_UID_" + str(i)) for i in range(128)])
    summary = mixed.summary(now=NOW)
    assert summary["matched_rows"] == summary["account_groups"] == 128
    assert set(summary["groups"][0]) == {"group_number", "candidate_count", "current_candidate_count"}
    with pytest.raises(OfficialSessionError, match="account_selection_required_or_invalid"):
        mixed.select(now=NOW)
    assert mixed.select(now=NOW, group_number=100).firebase_uid == "SYNTHETIC_UID_99"
    assert "SYNTHETIC_UID_" not in json.dumps(summary)


def test_bad_project_and_uid_blobs_are_counted_but_cannot_be_selected():
    inventory = inspect_archives([archive(), archive(aud="wrong-project"), archive(sub="wrong-user")])
    assert inventory.summary(now=NOW)["rejected_archives"] == 2
    with pytest.raises(OfficialSessionError, match="archive_candidates_invalid"):
        inventory.select(now=NOW)


def test_group_binding_is_inspection_local_and_does_not_change_for_token_refresh():
    first = inspect_archives([archive()])
    summary = first.summary(now=NOW, binding_nonce=NONCE)
    group = summary["groups"][0]
    assert set(group) == {"group_number", "candidate_count", "current_candidate_count", "binding"}
    assert len(group["binding"]) == 64 and all(c in "0123456789abcdef" for c in group["binding"])
    assert_redacted(summary)
    fresh = inspect_archives([archive(issued=NOW - 1, expires=NOW + 3600)])
    assert fresh.select(now=NOW, group_number=1, binding_nonce=NONCE,
        expected_group_binding=group["binding"]).firebase_uid == UID
    assert fresh.summary(now=NOW, binding_nonce="f0" * 32)["groups"][0]["binding"] != group["binding"]
    assert "binding" not in first.summary(now=NOW)["groups"][0]


def test_group_reassignment_cannot_select_a_different_account_after_inspection():
    original = inspect_archives([archive(uid="SYNTHETIC_A"), archive(uid="SYNTHETIC_B")])
    binding = original.summary(now=NOW, binding_nonce=NONCE)["groups"][0]["binding"]
    reordered = inspect_archives([archive(uid="SYNTHETIC_B"), archive(uid="SYNTHETIC_A")])
    with pytest.raises(OfficialSessionError, match="account_inventory_changed"):
        reordered.select(now=NOW, group_number=1, binding_nonce=NONCE, expected_group_binding=binding)
    # An ordinal changing does not prevent explicit selection of the original UID.
    assert reordered.select(now=NOW, group_number=2, binding_nonce=NONCE,
        expected_group_binding=binding).firebase_uid == "SYNTHETIC_A"


@pytest.mark.parametrize("nonce,binding", [(None, "a" * 64), (NONCE, None),
    ("bad-nonce", "a" * 64), (NONCE, "PRIVATE_BAD_BINDING"), ("A" * 64, "a" * 64)])
def test_partial_or_malformed_selection_binding_is_rejected(nonce, binding):
    with pytest.raises(OfficialSessionError, match="account_binding_invalid"):
        inspect_archives([archive()]).select(now=NOW, binding_nonce=nonce, expected_group_binding=binding)


def test_login_opt_in_blocks_every_transport(schema, monkeypatch):
    monkeypatch.setattr(module, "OfficialHttp", lambda **kw: pytest.fail("network initialized"))
    with pytest.raises(OfficialSessionError, match="existing_login_opt_in_required"):
        login_existing_account(schema, credentials(), now=NOW)


@pytest.mark.parametrize("method", ("/api.Auth/Create", "/api.Auth/Inherit", "/api.Home/Login",
    "/api.Dream/GenerateArea", "/api.Dream/StartQuest", "/api.Pvp/Start"))
def test_login_transport_cannot_invoke_prohibited_methods(schema, method):
    class NeverChannel:
        def unary_unary(self, method): pytest.fail("prohibited RPC reached transport")
    with pytest.raises(OfficialSessionError, match="rpc_method_not_allowed"):
        module._call(schema, NeverChannel(), method, {})


def test_current_token_login_fixed_allowlist_no_refresh_and_memory_only(schema, monkeypatch, tmp_path):
    channel, connections = install_channel(monkeypatch, schema)
    http = Http()
    session = login_existing_account(schema, credentials(), login_existing_account=True, now=NOW, http=http)
    assert [call[0] for call in channel.calls] == ["/api.System/Check", "/api.System/Check",
                                                "/api.Auth/Login", "/api.Master/Get"]
    assert [call[0] for call in http.calls] == ["seed"]
    assert connections == [("api.game-idolypride.jp:443", "verified-tls-sentinel",
        {"grpc.enable_retries": 0, "grpc.max_receive_message_length": module._MAX_RPC})]
    assert not channel.calls[0][1].firebaseIDToken
    assert channel.calls[1][1].firebaseIDToken == channel.calls[2][1].firebaseIDToken == token()
    assert channel.calls[0][2] == {"x-app-version": APP_VERSION}
    assert session.metadata["x-auth-token"] == GAME
    assert session.metadata["x-master-version"] == "synthetic-master-version"
    assert session.metadata["x-platform"] == "iOS"
    assert not {"content-type", "grpc-timeout", "x-app-request-id"} & session.metadata.keys()
    assert_redacted(session)
    assert list(tmp_path.iterdir()) == []
    session.close()
    assert session.metadata == {}


def test_each_login_uses_fresh_collector_device_ids(schema, monkeypatch):
    install_channel(monkeypatch, schema)
    http = Http()
    for _ in range(2):
        login_existing_account(schema, credentials(), login_existing_account=True, now=NOW, http=http).close()
    assert http.calls[0][1:] != http.calls[1][1:]
    assert all("38c81fc2-9955" not in str(call) and "5b60c8be15e69fd6" not in str(call) for call in http.calls)


def test_expired_token_refreshes_once_and_uses_same_uid(schema, monkeypatch):
    channel, _ = install_channel(monkeypatch, schema)
    http = Http()
    login_existing_account(schema, credentials(issued=NOW - 3600, expires=NOW),
        login_existing_account=True, now=NOW, http=http).close()
    assert [call[0] for call in http.calls] == ["refresh", "seed"]
    assert channel.calls[2][1].firebaseIDToken == http.response["id_token"]


@pytest.mark.parametrize("change", ({"user_id": "OTHER_PRIVATE_USER"}, {"project_id": "other-project"},
    {"id_token": token(sub="OTHER_PRIVATE_USER")}, {"id_token": token(aud="other-project")},
    {"id_token": token(expires=NOW)}, {"expires_in": "PRIVATE_REMOTE_TEXT"}))
def test_refreshed_scope_or_expiration_mismatch_stops_before_qseed_or_rpc(schema, monkeypatch, change):
    channel, _ = install_channel(monkeypatch, schema)
    http = Http()
    http.response.update(change)
    with pytest.raises(OfficialSessionError) as error:
        login_existing_account(schema, credentials(issued=NOW - 3600, expires=NOW),
            login_existing_account=True, now=NOW, http=http)
    assert [call[0] for call in http.calls] == ["refresh"] and not channel.calls
    assert_redacted(error.value)
    assert "OTHER_PRIVATE_USER" not in str(error.value) and "PRIVATE_REMOTE_TEXT" not in str(error.value)


@pytest.mark.parametrize("failure", ("reauthenticate", "application", "transport"))
def test_login_failure_has_no_refresh_retry_or_account_creation(schema, monkeypatch, failure):
    channel, _ = install_channel(monkeypatch, schema,
        reauthenticate=failure == "reauthenticate", broken=failure == "transport",
        metadata=(("x-error-code", GAME),) if failure == "application" else ())
    http = Http()
    with pytest.raises(OfficialSessionError) as error:
        login_existing_account(schema, credentials(), login_existing_account=True, now=NOW, http=http)
    assert [call[0] for call in http.calls] == ["seed"]
    assert len([call for call in channel.calls if call[0] == "/api.Auth/Login"]) <= 1
    assert all(call[0] in module.LOGIN_METHODS for call in channel.calls)
    assert_redacted(error.value)


def test_http_tls_verification_fixed_hosts_body_and_redirect_rejection():
    http = OfficialHttp()
    handlers = http._opener.handlers
    https = next(handler for handler in handlers if hasattr(handler, "_context"))
    assert https._context.check_hostname and https._context.verify_mode == ssl.CERT_REQUIRED
    redirects = next(handler for handler in handlers if isinstance(handler, module._NoRedirect))
    with pytest.raises(OfficialSessionError, match="http_redirect_rejected"):
        redirects.redirect_request(Request("https://id.qseed.jp/getId"), None, 302, GAME, {},
                                   "https://example.invalid/" + REFRESH)
    with pytest.raises(OfficialSessionError, match="http_target_not_allowed"):
        http._request(Request("https://example.invalid/" + REFRESH), limit=10)


class Response:
    def __init__(self, url, raw, status=200): self.url, self.raw, self.status = url, raw, status
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def geturl(self): return self.url
    def read(self, limit): return self.raw[:limit]


def test_http_refresh_only_sends_credentials_to_google_and_seed_has_no_token():
    http, requests = OfficialHttp(), []
    class Opener:
        def open(self, request, *, timeout):
            requests.append(request)
            raw = json.dumps(Http().response).encode() if request.get_method() == "POST" else SEED.encode()
            return Response(request.full_url, raw)
    http._opener = Opener()
    assert http.refresh(credentials())["user_id"] == UID
    assert http.seed("FRESH_DEVICE", "FRESH_AD") == SEED
    assert requests[0].full_url == "https://securetoken.googleapis.com/v1/token?key=" + KEY
    assert requests[0].data == ("grant_type=refresh_token&refresh_token=" + REFRESH).encode()
    assert requests[1].full_url == "https://id.qseed.jp/getId" and requests[1].data is None
    assert REFRESH not in str(requests[1].headers) and token() not in str(requests[1].headers)


@pytest.mark.parametrize("kind", ("redirect", "oversize", "transport", "status", "json"))
def test_http_remote_errors_are_redacted_and_never_retried(kind):
    http, calls = OfficialHttp(), []
    class Opener:
        def open(self, request, *, timeout):
            calls.append(request)
            if kind == "transport": raise RuntimeError(REFRESH + GAME)
            return Response("https://example.invalid/" + REFRESH if kind == "redirect" else request.full_url,
                b"x" * (module._MAX_HTTP + 1) if kind == "oversize" else GAME.encode(),
                status=401 if kind == "status" else 200)
    http._opener = Opener()
    with pytest.raises(OfficialSessionError) as error: http.refresh(credentials())
    assert len(calls) == 1
    assert_redacted(error.value)


@pytest.fixture
def worker():
    spec = importlib.util.spec_from_file_location("synthetic_preserve_playcover_events",
                                                ROOT / "tools/preserve_playcover_events.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def test_cli_default_inspection_is_offline_only_counts(worker, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(worker, "_export_rows", lambda *args: [("PRIVATE_GROUP", "PRIVATE_ACCOUNT", archive())])
    monkeypatch.setattr(worker, "login_existing_account", lambda *a, **kw: pytest.fail("login called"))
    monkeypatch.setattr(worker.Schema, "from_descriptor_set", lambda *a: pytest.fail("schema loaded"))
    assert worker.main(["--output", str(tmp_path / "must-not-exist")]) == 0
    out = capsys.readouterr()
    value = json.loads(out.out)
    assert value["status"] == "inspected" and value["matched_rows"] == 1
    assert not (tmp_path / "must-not-exist").exists() and out.err == ""
    assert_redacted(out.out)
    assert "PRIVATE_GROUP" not in out.out and "PRIVATE_ACCOUNT" not in out.out


def test_cli_menu_opt_in_does_not_imply_login(worker, monkeypatch, capsys):
    monkeypatch.setattr(worker, "_export_rows", lambda *a: pytest.fail("records read before opt-in"))
    assert worker.main(["--visit-current-menus"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed", "code": "menu_visit_requires_existing_login"}


def test_cli_reassigned_numbered_group_stops_before_login(worker, monkeypatch, capsys, tmp_path):
    rows = [("same-group", "same-account", archive(uid="SYNTHETIC_A")),
            ("same-group", "same-account", archive(uid="SYNTHETIC_B"))]
    monkeypatch.setattr(worker, "_export_rows", lambda *args: rows)
    monkeypatch.setattr(worker.time, "time", lambda: NOW)
    monkeypatch.setattr(worker, "login_existing_account", lambda *a, **kw: pytest.fail("stale group logged in"))
    assert worker.main(["--inspect", "--inventory-nonce", NONCE]) == 0
    inspection = json.loads(capsys.readouterr().out)
    binding = inspection["groups"][0]["binding"]
    assert "SYNTHETIC_A" not in json.dumps(inspection) and "SYNTHETIC_B" not in json.dumps(inspection)
    rows.reverse()
    output = tmp_path / "must-not-exist"
    assert worker.main(["--login-existing-account", "--account-group", "1", "--output", str(output),
                        "--inventory-nonce", NONCE, "--expected-group-binding", binding]) == 1
    result = capsys.readouterr()
    assert json.loads(result.out) == {"status": "failed", "code": "account_inventory_changed"}
    assert not output.exists() and result.err == ""


@pytest.mark.parametrize("args", [["--expected-group-binding", "a" * 64],
    ["--login-existing-account", "--inventory-nonce", NONCE]])
def test_cli_incomplete_binding_never_reads_archives(worker, monkeypatch, capsys, args):
    monkeypatch.setattr(worker, "_export_rows", lambda *a: pytest.fail("archives read for incomplete binding"))
    assert worker.main(args) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "account_binding_invalid"}


def test_cli_passes_metadata_only_in_memory_and_clears_after_capture(worker, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(worker, "_export_rows", lambda *a: [("ignored", "ignored", archive())])
    monkeypatch.setattr(worker.time, "time", lambda: NOW)
    session = module.OfficialSession({"x-auth-token": GAME, "x-app-version": APP_VERSION,
                                      "x-master-version": "synthetic-master"})
    monkeypatch.setattr(worker, "login_existing_account", lambda *a, **kw: session)
    observed = []
    def capture(schema, metadata, output, **kwargs):
        assert metadata is session.metadata and metadata["x-auth-token"] == GAME
        observed.append(kwargs)
        return {"complete": True, "captured_responses": 5, "captured_bytes": 100,
                "credentials_exported": False}
    monkeypatch.setattr(worker, "collect_in_memory", capture)
    assert worker.main(["--login-existing-account", "--visit-current-menus", "--account-group", "1",
                        "--output", str(tmp_path / "private-events")]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["status"] == "preserved" and observed[0]["visit_menus"] is True
    assert session.metadata == {} and out.err == "" and list(tmp_path.iterdir()) == []
    assert_redacted(out.out)


def test_cli_does_not_print_local_exception_details(worker, monkeypatch, capsys):
    def fail(*a): raise RuntimeError("PRIVATE_PATH/" + UID + REFRESH)
    monkeypatch.setattr(worker, "_export_rows", fail)
    assert worker.main([]) == 1
    out = capsys.readouterr()
    assert json.loads(out.out) == {"status": "failed", "code": "local_preservation_failed"}
    assert out.err == ""
    assert_redacted(out.out)
