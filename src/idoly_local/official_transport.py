"""Small fixed-endpoint verified TLS transport for explicit JP account import.

No grpcio, proxy settings, redirects, token refresh, endpoint overrides or retries.
Only the six audited RPCs and the three required HTTPS operations are reachable.
Responses and exception text are never forwarded into diagnostics.
"""
import http.client
import json
import re
import socket
import ssl
import time
from urllib.parse import urlencode

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import (ConnectionTerminated, DataReceived, ResponseReceived,
                       StreamEnded, StreamReset, TrailersReceived, WindowUpdated)
from . import codec
from .official_roots import ROOTS_PEM

RPC_HOST = "api.game-idolypride.jp"
RPC_METHODS = frozenset(("/api.System/Check", "/api.Migration/MigratePassword",
    "/api.Migration/Execute", "/api.Auth/Login", "/api.Master/Get", "/api.User/Get"))
_METADATA = frozenset(("x-app-version", "x-platform", "x-seed-id", "x-ad-id",
                       "x-auth-token", "x-master-version"))
_SEED_HEADERS = frozenset(("X-Device", "X-Ad", "X-App", "X-AppVersion", "X-SeedVersion"))
_FIREBASE_HEADERS = frozenset(("X-Firebase-GMPID", "X-Ios-Bundle-Identifier",
                               "X-Android-Package", "X-Android-Cert"))
_MAX_RPC = 17 * 1024 * 1024
_MAX_PLAIN = 16 * 1024 * 1024
_MAX_HTTP = 128 * 1024


class OfficialTransportError(RuntimeError):
    """Fixed local code only. Never include a remote message or endpoint query."""
    def __init__(self, code):
        self.code = code
        super().__init__("Official transport stopped: " + code)


def _need(ok, code):
    if not ok:
        raise OfficialTransportError(code)


def _close(value):
    if value is not None:
        try:
            value.close()
        except Exception:
            pass


def _headers(value, allowed):
    _need(type(value) is dict and set(value) <= allowed, "headers_invalid")
    total = 0
    for key, content in value.items():
        _need(type(key) is str and type(content) is str and 0 < len(content) <= 16384
              and all(32 <= ord(c) < 127 for c in content), "headers_invalid")
        total += len(key) + len(content)
    _need(total <= 24576, "headers_invalid")
    return list(value.items())


def _check(cancel, deadline):
    try:
        stopped = cancel.is_set() if hasattr(cancel, "is_set") else cancel() if cancel else False
        _need(type(stopped) is bool, "cancel_invalid")
    except OfficialTransportError:
        raise
    except Exception:
        raise OfficialTransportError("cancel_invalid") from None
    _need(not stopped, "cancelled")
    remaining = deadline - time.monotonic()
    _need(remaining > 0, "deadline_exceeded")
    return remaining


def _deadline(timeout):
    _need(type(timeout) in (int, float) and 0 < timeout <= 60, "timeout_invalid")
    return time.monotonic() + timeout


def _json_object(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            _need(key not in out, "http_body_invalid")
            out[key] = value
        return out
    try:
        out = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _need(type(out) is dict, "http_body_invalid")
        return out
    except OfficialTransportError:
        raise
    except Exception:
        raise OfficialTransportError("http_body_invalid") from None


class OfficialTransport:
    def __init__(self):
        try:
            self._context = ssl.create_default_context(cadata=ROOTS_PEM)
            self._context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._context.set_alpn_protocols(["h2"])
            self._http_context = ssl.create_default_context(cadata=ROOTS_PEM)
            self._http_context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._http_context.set_alpn_protocols(["http/1.1"])
            _need(self._context.check_hostname
                  and self._context.verify_mode == ssl.CERT_REQUIRED, "tls_roots_invalid")
        except OfficialTransportError:
            raise
        except Exception:
            raise OfficialTransportError("tls_roots_invalid") from None

    def __repr__(self):
        return "<OfficialTransport fixed verified TLS endpoints>"

    def _http(self, host, path, method, headers, body, *, limit, cancel):
        deadline = _deadline(30)
        conn = None
        try:
            _check(cancel, deadline)
            # HTTPSConnection connects directly: environment proxy configuration
            # and redirect handlers cannot change these fixed destinations.
            conn = http.client.HTTPSConnection(host, 443, timeout=_check(cancel, deadline),
                                               context=self._http_context)
            conn.connect()
            conn.sock.settimeout(_check(cancel, deadline))
            conn.request(method, path, body=body, headers=dict(headers))
            conn.sock.settimeout(_check(cancel, deadline))
            response = conn.getresponse()
            _need(not 300 <= response.status <= 399, "http_redirect_rejected")
            _need(response.status == 200, "http_status_rejected")
            length = response.getheader("Content-Length")
            if length is not None:
                _need(re.fullmatch(r"[0-9]{1,12}", length) is not None
                      and int(length) <= limit, "http_body_too_large")
            result = bytearray()
            while True:
                remaining = _check(cancel, deadline)
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                block = response.read(min(65536, limit + 1 - len(result)))
                if not block:
                    break
                result.extend(block)
                _need(len(result) <= limit, "http_body_too_large")
            _check(cancel, deadline)
            _need(length is None or len(result) == int(length), "http_body_invalid")
            return bytes(result)
        except OfficialTransportError:
            raise
        except ssl.SSLError:
            raise OfficialTransportError("tls_failed") from None
        except (TimeoutError, socket.timeout):
            raise OfficialTransportError("deadline_exceeded") from None
        except Exception:
            raise OfficialTransportError("http_failed") from None
        finally:
            _close(conn)

    def seed(self, headers, *, cancel=None):
        pairs = _headers(headers, _SEED_HEADERS)
        _need(set(headers) == _SEED_HEADERS, "headers_invalid")
        raw = self._http("id.qseed.jp", "/getId", "GET", pairs, None,
                         limit=4096, cancel=cancel)
        try:
            text = raw.decode("ascii")
            _need(0 < len(text) <= 4096 and text == text.strip()
                  and all(32 <= ord(c) < 127 for c in text), "seed_invalid")
            return text
        except UnicodeError:
            raise OfficialTransportError("seed_invalid") from None

    def firebase(self, operation, api_key, payload, headers, *, cancel=None):
        paths = {"signin": "/v1/accounts:signInWithCustomToken", "lookup": "/v1/accounts:lookup"}
        _need(operation in paths and type(api_key) is str
              and re.fullmatch(r"AIza[A-Za-z0-9_-]{20,80}", api_key) is not None,
              "firebase_request_invalid")
        pairs = _headers(headers, _FIREBASE_HEADERS)
        _need(type(payload) is dict, "firebase_request_invalid")
        _need(set(payload) == ({"token", "returnSecureToken"} if operation == "signin" else {"idToken"}),
              "firebase_request_invalid")
        token = payload.get("token" if operation == "signin" else "idToken")
        _need(type(token) is str and 0 < len(token) <= 16384
              and all(32 <= ord(c) < 127 for c in token), "firebase_request_invalid")
        _need(operation != "signin" or payload["returnSecureToken"] is True,
              "firebase_request_invalid")
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        pairs.append(("Content-Type", "application/json"))
        raw = self._http("identitytoolkit.googleapis.com", paths[operation] + "?" + urlencode({"key": api_key}),
                         "POST", pairs, body, limit=_MAX_HTTP, cancel=cancel)
        return _json_object(raw)

    def rpc(self, path, request_plain, metadata, *, cancel=None, timeout=30):
        _need(type(path) is str and path in RPC_METHODS, "rpc_method_rejected")
        _need(type(request_plain) is bytes and len(request_plain) <= 16384, "rpc_request_invalid")
        headers = _headers(metadata, _METADATA)
        deadline = _deadline(timeout)
        stream = None
        try:
            _check(cancel, deadline)
            payload = codec.encode(request_plain)
            framed = b"\0" + len(payload).to_bytes(4, "big") + payload
            _need(len(framed) <= 32768, "rpc_request_invalid")
            raw = socket.create_connection((RPC_HOST, 443), timeout=_check(cancel, deadline))
            try:
                raw.settimeout(_check(cancel, deadline))
                stream = self._context.wrap_socket(raw, server_hostname=RPC_HOST)
            except BaseException:
                _close(raw)
                raise
            _need(stream.selected_alpn_protocol() == "h2", "tls_alpn_invalid")
            client = H2Connection(H2Configuration(client_side=True, header_encoding="ascii"))
            client.initiate_connection()
            client.send_headers(1, [(":method", "POST"), (":scheme", "https"),
                (":authority", RPC_HOST), (":path", path), ("content-type", "application/grpc+proto"),
                ("te", "trailers"), ("grpc-timeout", str(int(timeout * 1000)) + "m"), *headers])
            offset = 0
            ended = False
            initial = False
            grpc_status = None
            result = bytearray()
            while not ended:
                stream.settimeout(_check(cancel, deadline))
                if offset < len(framed):
                    size = min(len(framed) - offset, client.local_flow_control_window(1), client.max_outbound_frame_size)
                    if size:
                        next_offset = offset + size
                        client.send_data(1, framed[offset:next_offset], end_stream=next_offset == len(framed))
                        offset = next_offset
                pending = client.data_to_send()
                if pending:
                    stream.sendall(pending)
                # Refill the remaining initial request window before waiting
                # for a server WINDOW_UPDATE or response.
                if offset < len(framed) and client.local_flow_control_window(1) > 0:
                    continue
                stream.settimeout(min(1.0, _check(cancel, deadline)))
                try:
                    data = stream.recv(65536)
                except socket.timeout:
                    continue
                _need(bool(data), "rpc_response_incomplete")
                for event in client.receive_data(data):
                    if isinstance(event, ConnectionTerminated):
                        if ended and event.error_code == 0 and event.last_stream_id >= 1:
                            continue
                        raise OfficialTransportError("rpc_stream_failed")
                    if isinstance(event, StreamReset):
                        raise OfficialTransportError("rpc_stream_failed")
                    if isinstance(event, WindowUpdated) and event.stream_id == 0:
                        continue
                    if getattr(event, "stream_id", 1) != 1:
                        raise OfficialTransportError("rpc_stream_failed")
                    if isinstance(event, (ResponseReceived, TrailersReceived)):
                        values = {}
                        for key, value in event.headers:
                            _need(key not in values, "rpc_headers_invalid")
                            values[key] = value
                        if isinstance(event, ResponseReceived):
                            _need(not initial and values.get(":status") == "200"
                                  and values.get("content-type", "").split(";", 1)[0]
                                  in ("application/grpc", "application/grpc+proto"), "rpc_http_rejected")
                            initial = True
                        app_code = values.get("x-error-code", "0")
                        _need(re.fullmatch(r"[0-9]{1,10}", app_code) is not None
                              and int(app_code) == 0, "rpc_application_rejected")
                        _need(values.get("grpc-encoding", "identity") == "identity", "rpc_encoding_rejected")
                        if "grpc-status" in values:
                            _need(grpc_status is None, "rpc_headers_invalid")
                            grpc_status = values["grpc-status"]
                    elif isinstance(event, DataReceived):
                        _need(initial, "rpc_headers_invalid")
                        result.extend(event.data)
                        _need(len(result) <= _MAX_RPC + 5, "rpc_response_too_large")
                        client.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        ended = True
                pending = client.data_to_send()
                if pending:
                    stream.settimeout(_check(cancel, deadline))
                    stream.sendall(pending)
            _check(cancel, deadline)
            _need(initial and grpc_status == "0", "rpc_status_rejected")
            _need(len(result) >= 5 and result[0] == 0
                  and int.from_bytes(result[1:5], "big") == len(result) - 5,
                  "rpc_frame_invalid")
            plain = codec.decode(bytes(result[5:]))
            _need(len(plain) <= _MAX_PLAIN, "rpc_response_too_large")
            return plain
        except OfficialTransportError:
            raise
        except ssl.SSLError:
            raise OfficialTransportError("tls_failed") from None
        except (TimeoutError, socket.timeout):
            raise OfficialTransportError("deadline_exceeded") from None
        except Exception:
            raise OfficialTransportError("rpc_failed") from None
        finally:
            _close(stream)
