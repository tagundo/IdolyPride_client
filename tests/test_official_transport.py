"""Protocol tests use a real h2 peer, synthetic TLS sockets and no public network."""
import hashlib
import json
import ssl
import threading

import pytest
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, StreamEnded

from idoly_local import codec
from idoly_local import official_transport as module


class Peer:
    def __init__(self, plain=b"reply", *, status="0", app_code="0", bad_frame=False,
                 http_status="200", encoding="identity", duplicate=False):
        self.server = H2Connection(H2Configuration(client_side=False, header_encoding="ascii"))
        self.server.initiate_connection()
        self.server.increment_flow_control_window(1024 * 1024)
        self.plain = plain
        encoded = codec.encode(plain)
        self.message = b"\0" + (len(encoded) + int(bad_frame)).to_bytes(4, "big") + encoded
        self.status, self.app_code = status, app_code
        self.http_status, self.encoding, self.duplicate = http_status, encoding, duplicate
        self.offset = 0
        self.request = bytearray()
        self.headers = None
        self.ready = self.trailers = self.closed = False

    def settimeout(self, value):
        assert 0 < value <= 60

    def selected_alpn_protocol(self):
        return "h2"

    def sendall(self, raw):
        for event in self.server.receive_data(raw):
            if isinstance(event, RequestReceived):
                self.headers = dict(event.headers)
            elif isinstance(event, DataReceived):
                self.request.extend(event.data)
                self.server.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, StreamEnded):
                self.server.send_headers(1, [(":status", self.http_status),
                    ("content-type", "application/grpc+proto"), ("grpc-encoding", self.encoding),
                    ("x-error-code", self.app_code), *([("x-error-code", self.app_code)] if self.duplicate else [])])
                self.ready = True

    def recv(self, size):
        if self.ready:
            while self.offset < len(self.message):
                amount = min(len(self.message) - self.offset, self.server.local_flow_control_window(1),
                             self.server.max_outbound_frame_size)
                if not amount:
                    break
                self.server.send_data(1, self.message[self.offset:self.offset + amount])
                self.offset += amount
            if self.offset == len(self.message) and not self.trailers:
                self.server.send_headers(1, [("grpc-status", self.status)], end_stream=True)
                self.trailers = True
        return self.server.data_to_send(size)

    def close(self):
        self.closed = True


class TLS:
    def __init__(self, peer):
        self.peer = peer
        self.names = []

    def wrap_socket(self, raw, *, server_hostname):
        assert raw is self.peer
        self.names.append(server_hostname)
        return raw


def transport(monkeypatch, **options):
    client, peer = module.OfficialTransport(), Peer(**options)
    tls = TLS(peer)
    client._context = tls
    addresses = []
    def connect(address, *, timeout):
        addresses.append(address)
        assert 0 < timeout <= 30
        return peer
    monkeypatch.setattr(module.socket, "create_connection", connect)
    return client, peer, tls, addresses


def test_verified_pinned_tls_contexts():
    client = module.OfficialTransport()
    for context in (client._context, client._http_context):
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert context.cert_store_stats()["x509_ca"] >= 118
    assert hashlib.sha256(module.ROOTS_PEM.encode()).hexdigest() == "2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b"


def test_unary_real_h2_framing_crypto_flow_control_and_fixed_host(monkeypatch):
    plain = bytes(range(256)) * 1000
    client, peer, tls, addresses = transport(monkeypatch, plain=plain)
    assert client.rpc("/api.User/Get", b"request", {"x-auth-token": "synthetic"}) == plain
    assert addresses == [("api.game-idolypride.jp", 443)]
    assert tls.names == ["api.game-idolypride.jp"]
    assert peer.headers[":scheme"] == "https" and peer.headers[":path"] == "/api.User/Get"
    assert peer.request[0] == 0 and int.from_bytes(peer.request[1:5], "big") == len(peer.request) - 5
    assert codec.decode(bytes(peer.request[5:])) == b"request"
    assert peer.closed and peer.trailers and peer.offset == len(peer.message)


@pytest.mark.parametrize("options, code", [
    ({"status": "16"}, "rpc_status_rejected"),
    ({"app_code": "123"}, "rpc_application_rejected"),
    ({"app_code": "private-secret"}, "rpc_application_rejected"),
    ({"http_status": "302"}, "rpc_http_rejected"),
    ({"encoding": "gzip"}, "rpc_encoding_rejected"),
    ({"duplicate": True}, "rpc_headers_invalid"),
    ({"bad_frame": True}, "rpc_frame_invalid"),
])
def test_unary_rejects_protocol_or_application_errors_without_retry(monkeypatch, options, code):
    client, peer, _, addresses = transport(monkeypatch, **options)
    with pytest.raises(module.OfficialTransportError) as error:
        client.rpc("/api.User/Get", b"", {})
    assert error.value.code == code
    assert "private-secret" not in str(error.value)
    assert peer.closed and len(addresses) == 1


@pytest.mark.parametrize("path, metadata, code", [
    ("/api.Auth/Create", {}, "rpc_method_rejected"),
    ("https://example.invalid/api.User/Get", {}, "rpc_method_rejected"),
    ("/api.User/Get", {"authorization": "secret"}, "headers_invalid"),
    ("/api.User/Get", {"x-auth-token": "secret\nleak"}, "headers_invalid"),
])
def test_invalid_request_never_connects(monkeypatch, path, metadata, code):
    client, _, _, addresses = transport(monkeypatch)
    with pytest.raises(module.OfficialTransportError) as error:
        client.rpc(path, b"", metadata)
    assert error.value.code == code and not addresses
    assert "secret" not in str(error.value)


def test_cancelled_before_connect(monkeypatch):
    client, _, _, addresses = transport(monkeypatch)
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(module.OfficialTransportError, match="cancelled"):
        client.rpc("/api.User/Get", b"", {}, cancel=cancelled)
    assert not addresses


class Response:
    def __init__(self, body, status=200, length=None):
        self.body, self.status, self.length = body, status, length
    def getheader(self, key):
        return self.length if key == "Content-Length" else None
    def read(self, size):
        result, self.body = self.body[:size], self.body[size:]
        return result


def http_transport(monkeypatch, body, *, status=200, length=None):
    client, calls = module.OfficialTransport(), []
    class Connection:
        @property
        def sock(self):
            return self
        def settimeout(self, timeout):
            assert 0 < timeout <= 30
        def connect(self):
            pass
        def __init__(self, host, port, *, timeout, context):
            assert port == 443 and context is client._http_context
            self.record = {"host": host, "closed": False}
            calls.append(self.record)
        def request(self, method, path, *, body, headers):
            self.record.update(method=method, path=path, body=body, headers=headers)
        def getresponse(self):
            return Response(body, status, length)
        def close(self):
            self.record["closed"] = True
    monkeypatch.setattr(module.http.client, "HTTPSConnection", Connection)
    return client, calls


def test_firebase_fixed_endpoint_payload_and_scope_headers(monkeypatch):
    client, calls = http_transport(monkeypatch, b'{"idToken":"synthetic"}')
    key = "AIza" + "a" * 30
    assert client.firebase("signin", key, {"token": "private-token", "returnSecureToken": True},
                           {"X-Ios-Bundle-Identifier": "game.qualiarts.idolypride"}) == {"idToken": "synthetic"}
    assert len(calls) == 1 and calls[0]["host"] == "identitytoolkit.googleapis.com"
    assert calls[0]["path"] == "/v1/accounts:signInWithCustomToken?key=" + key
    assert json.loads(calls[0]["body"])["token"] == "private-token"
    assert calls[0]["closed"]
    assert "private-token" not in repr(client)


@pytest.mark.parametrize("status,length,body,code", [
    (302, None, b"", "http_redirect_rejected"),
    (400, None, b'{"error":"private-secret"}', "http_status_rejected"),
    (200, "131073", b"", "http_body_too_large"),
    (200, "5", b"{}", "http_body_invalid"),
    (200, None, b'{"a":1,"a":2}', "http_body_invalid"),
    (200, None, b'{"a":NaN}', "http_body_invalid"),
])
def test_http_rejection_is_bounded_sanitized_and_never_retried(monkeypatch, status, length, body, code):
    client, calls = http_transport(monkeypatch, body, status=status, length=length)
    with pytest.raises(module.OfficialTransportError) as error:
        client.firebase("lookup", "AIza" + "a" * 30, {"idToken": "private-token"}, {})
    assert error.value.code == code
    assert "private-secret" not in str(error.value) and "private-token" not in str(error.value)
    assert len(calls) == 1 and calls[0]["closed"]


def test_seed_only_fixed_complete_headers(monkeypatch):
    client, calls = http_transport(monkeypatch, b"synthetic-seed")
    headers = {key: "synthetic" for key in module._SEED_HEADERS}
    assert client.seed(headers) == "synthetic-seed"
    assert calls[0]["host"] == "id.qseed.jp" and calls[0]["path"] == "/getId"
    assert calls[0]["method"] == "GET" and calls[0]["body"] is None
    with pytest.raises(module.OfficialTransportError, match="headers_invalid"):
        client.seed({"X-App": "incomplete"})
    assert len(calls) == 1
