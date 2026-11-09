"""Pure-Python HTTP/2 unary gRPC transport for the shared game application.

Uses prior-knowledge h2c on loopback and the game's encrypted message envelope.
No grpcio extension is imported, so the same engine runs inside Chaquopy.
"""
from __future__ import annotations

import base64
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
import gzip
from io import BytesIO
import logging
import queue
import re
import select
import socket
import socketserver
import struct
import threading
import time
import zlib
from urllib.parse import quote

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import ConnectionTerminated, DataReceived, RequestReceived, StreamEnded, StreamReset
from h2.exceptions import H2Error, StreamClosedError
from h2.settings import SettingCodes

from . import codec
from .rpc import RpcCode, RpcFailure


LOG = logging.getLogger(__name__)
MAX_MESSAGE = 16 * 1024 * 1024
MAX_BUFFERED = 32 * 1024 * 1024
MAX_STREAMS = 32
MAX_HEADERS = 16 * 1024
_TIMEOUT = re.compile(r"([0-9]{1,8})([HMSmun])\Z")
_TIMEOUT_UNITS = {"H": 3600, "M": 60, "S": 1, "m": 1e-3, "u": 1e-6, "n": 1e-9}


class Context:
    """Small transport-neutral context used by Application.handle."""

    def __init__(self, metadata=(), deadline: float | None = None):
        self._metadata = tuple(metadata)
        self._deadline = deadline
        self.cancelled = threading.Event()
        self.initial_metadata = ()
        self.trailing_metadata = ()

    def invocation_metadata(self):
        return self._metadata

    def abort(self, code, details):
        code = RpcCode(code)
        raise RpcFailure(code if code != RpcCode.OK else RpcCode.UNKNOWN, str(details))

    def is_active(self):
        remaining = self.time_remaining()
        return not self.cancelled.is_set() and (remaining is None or remaining > 0)

    def time_remaining(self):
        return max(0.0, self._deadline - time.monotonic()) if self._deadline is not None else None

    def send_initial_metadata(self, metadata):
        self.initial_metadata = tuple(metadata)

    def set_trailing_metadata(self, metadata):
        self.trailing_metadata = tuple(metadata)


@dataclass
class _Stream:
    path: str
    headers: dict
    context: Context
    body: bytearray = field(default_factory=bytearray)
    failure: RpcFailure | None = None
    future: object = None


@dataclass
class _Reply:
    data: bytes
    context: Context
    offset: int = 0


def _context(headers):
    metadata = []
    for key, value in headers:
        if key.startswith(":") or key in ("content-type", "te", "grpc-timeout", "grpc-encoding", "grpc-accept-encoding"):
            continue
        if key.endswith("-bin"):
            try:
                for item in value.split(","):
                    item = item.strip()
                    metadata.append((key, base64.b64decode(item + "=" * (-len(item) % 4), validate=True)))
            except (ValueError, TypeError):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed binary request metadata") from None
        else:
            metadata.append((key, value))
    deadline = None
    timeout = dict(headers).get("grpc-timeout")
    if timeout is not None:
        match = _TIMEOUT.fullmatch(timeout)
        if not match:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed gRPC timeout")
        deadline = time.monotonic() + int(match[1]) * _TIMEOUT_UNITS[match[2]]
    return Context(metadata, deadline)


def _unframe(body: bytes, encoding: str) -> bytes:
    if len(body) < 5:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Missing gRPC unary message frame")
    compressed, length = body[0], struct.unpack_from("!I", body, 1)[0]
    if length > MAX_MESSAGE:
        raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC request exceeds message limit")
    if len(body) != 5 + length:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unary RPC requires exactly one complete message")
    payload = body[5:]
    if compressed == 0:
        return payload
    if compressed != 1:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Invalid gRPC compression flag")
    if encoding != "gzip":
        raise RpcFailure(RpcCode.UNIMPLEMENTED, "Unsupported gRPC message compression")
    try:
        with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
            payload = stream.read(MAX_MESSAGE + 1)
    except (OSError, EOFError, zlib.error):
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed gzip gRPC message") from None
    if len(payload) > MAX_MESSAGE:
        raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "Inflated gRPC request exceeds message limit")
    return payload


def _metadata_headers(metadata):
    result = []
    for key, value in metadata:
        if key.startswith(":") or key in ("grpc-status", "grpc-message", "content-type"):
            continue
        if key.endswith("-bin"):
            value = base64.b64encode(value).decode("ascii")
        result.append((key, str(value)))
    return result


class _Connection:
    def __init__(self, server, client):
        self.server, self.client = server, client
        self.h2 = H2Connection(H2Configuration(client_side=False, header_encoding="utf-8"))
        self.streams: dict[int, _Stream] = {}
        self.replies: dict[int, _Reply] = {}
        self.completed = queue.SimpleQueue()
        self.inflight_bytes = 0
        self.wake_read, self.wake_write = socket.socketpair()
        self.wake_read.setblocking(False)
        self.wake_write.setblocking(False)

    def _invoke(self, path, payload, context):
        if not context.is_active():
            raise RpcFailure(RpcCode.DEADLINE_EXCEEDED, "RPC deadline exceeded")
        plain = self.server.application.handle(path, payload, context)
        if not isinstance(plain, bytes):
            raise RpcFailure(RpcCode.INTERNAL, "Local RPC handler returned invalid response bytes")
        if len(plain) > MAX_MESSAGE:
            raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC response exceeds message limit")
        encoded = codec.encode(plain)
        if len(encoded) > MAX_MESSAGE:
            raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "Encrypted gRPC response exceeds message limit")
        if not context.is_active():
            raise RpcFailure(RpcCode.DEADLINE_EXCEEDED, "RPC deadline exceeded")
        return encoded

    def _finish(self, sid, future, size):
        self.completed.put((sid, future, size))
        try:
            self.wake_write.send(b"x")
        except OSError:
            pass

    def _failure(self, sid, failure):
        if sid not in self.streams:
            return
        try:
            self.h2.send_headers(sid, [(":status", "200"), ("content-type", "application/grpc"),
                ("grpc-status", str(int(failure.code))),
                ("grpc-message", quote(failure.details[:2048], safe=""))], end_stream=True)
        except (StreamClosedError, H2Error):
            pass
        self.server._log(f"RPC {self.streams[sid].path[:180]} -> {failure.code.name}")
        self.streams.pop(sid, None)
        self.replies.pop(sid, None)

    def _receive_headers(self, event):
        headers = dict(event.headers)
        path = headers.get(":path", "")
        context = Context()
        failure = None
        try:
            if sum(len(key) + len(value) for key, value in event.headers) > MAX_HEADERS:
                raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC request headers exceed limit")
            context = _context(event.headers)
            if headers.get(":method") != "POST":
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "gRPC requires POST")
            content = headers.get("content-type", "").split(";", 1)[0]
            if content != "application/grpc" and not content.startswith("application/grpc+"):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Expected application/grpc content type")
            methods = getattr(getattr(self.server.application, "schema", None), "methods", None)
            if methods is not None:
                method = methods.get(path)
                if method is None or method.client_streaming or method.server_streaming:
                    raise RpcFailure(RpcCode.UNIMPLEMENTED, "Unknown or unsupported unary RPC")
        except RpcFailure as error:
            failure = error
        self.streams[event.stream_id] = _Stream(path, headers, context, failure=failure)

    def _receive_data(self, event):
        self.h2.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
        stream = self.streams.get(event.stream_id)
        if stream is None or stream.failure is not None:
            return
        buffered = sum(len(item.body) for item in self.streams.values())
        if len(stream.body) + len(event.data) > MAX_MESSAGE + 5 or buffered + len(event.data) > MAX_BUFFERED:
            stream.failure = RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC receive buffer limit exceeded")
            stream.body.clear()
            return
        stream.body.extend(event.data)
        if len(stream.body) >= 5 and struct.unpack_from("!I", stream.body, 1)[0] > MAX_MESSAGE:
            stream.failure = RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC request exceeds message limit")
            stream.body.clear()

    def _end_stream(self, sid):
        stream = self.streams.get(sid)
        if stream is None:
            return
        if stream.failure is not None:
            self._failure(sid, stream.failure)
            return
        try:
            payload = _unframe(bytes(stream.body), stream.headers.get("grpc-encoding", "identity"))
            stream.body.clear()
            if self.inflight_bytes + len(payload) > MAX_BUFFERED:
                raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "Too many outstanding request bytes")
        except RpcFailure as error:
            self._failure(sid, error)
            return
        try:
            future = self.server._executor.submit(self._invoke, stream.path, payload, stream.context)
        except RuntimeError:
            self._failure(sid, RpcFailure(RpcCode.UNAVAILABLE, "Local server is stopping"))
            return
        stream.future = future
        self.inflight_bytes += len(payload)
        future.add_done_callback(lambda done, sid=sid, size=len(payload): self._finish(sid, done, size))

    def _complete_replies(self):
        while True:
            try:
                sid, future, size = self.completed.get_nowait()
            except queue.Empty:
                break
            self.inflight_bytes -= size
            stream = self.streams.get(sid)
            if stream is None:
                continue
            try:
                encoded = future.result()
                if sum(len(reply.data) - reply.offset for reply in self.replies.values()) + len(encoded) + 5 > MAX_BUFFERED:
                    raise RpcFailure(RpcCode.RESOURCE_EXHAUSTED, "gRPC send buffer limit exceeded")
            except RpcFailure as error:
                self._failure(sid, error)
                continue
            except CancelledError:
                self._failure(sid, RpcFailure(RpcCode.CANCELLED, "RPC cancelled"))
                continue
            except Exception as error:
                self.server._log(f"RPC handler failed ({type(error).__name__})")
                self._failure(sid, RpcFailure(RpcCode.INTERNAL, "Local RPC handler failed"))
                continue
            try:
                self.h2.send_headers(sid, [(":status", "200"), ("content-type", "application/grpc"),
                    ("grpc-encoding", "identity"), ("grpc-accept-encoding", "identity,gzip"),
                    *_metadata_headers(stream.context.initial_metadata)])
                self.replies[sid] = _Reply(b"\0" + struct.pack("!I", len(encoded)) + encoded, stream.context)
            except (StreamClosedError, H2Error):
                self.streams.pop(sid, None)

    def _flush_replies(self):
        # Send one frame per stream per pass so parallel RPCs share the window.
        progress = True
        while progress:
            progress = False
            for sid, reply in list(self.replies.items()):
                try:
                    window = min(self.h2.local_flow_control_window(sid), self.h2.max_outbound_frame_size)
                    if window <= 0:
                        continue
                    count = min(window, len(reply.data) - reply.offset)
                    self.h2.send_data(sid, reply.data[reply.offset:reply.offset + count])
                    reply.offset += count
                    progress = True
                    if reply.offset == len(reply.data):
                        self.h2.send_headers(sid, [("grpc-status", "0"),
                            *_metadata_headers(reply.context.trailing_metadata)], end_stream=True)
                        stream = self.streams.pop(sid, None)
                        self.replies.pop(sid, None)
                        if stream is not None:
                            self.server._log(f"RPC {stream.path[:180]} -> OK")
                except (StreamClosedError, H2Error):
                    self.streams.pop(sid, None)
                    self.replies.pop(sid, None)

    def run(self):
        self.client.settimeout(5)
        self.client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self.h2.initiate_connection()
            self.h2.update_settings({SettingCodes.MAX_CONCURRENT_STREAMS: MAX_STREAMS,
                                     SettingCodes.MAX_HEADER_LIST_SIZE: MAX_HEADERS})
            self.client.sendall(self.h2.data_to_send())
            while not self.server._stopped.is_set():
                self._complete_replies()
                self._flush_replies()
                outgoing = self.h2.data_to_send()
                if outgoing:
                    self.client.sendall(outgoing)
                ready, _, _ = select.select([self.client, self.wake_read], [], [], 1)
                if self.wake_read in ready:
                    try:
                        while self.wake_read.recv(4096):
                            pass
                    except BlockingIOError:
                        pass
                if self.client not in ready:
                    continue
                data = self.client.recv(65536)
                if not data:
                    break
                for event in self.h2.receive_data(data):
                    if isinstance(event, RequestReceived):
                        self._receive_headers(event)
                    elif isinstance(event, DataReceived):
                        self._receive_data(event)
                    elif isinstance(event, StreamEnded):
                        self._end_stream(event.stream_id)
                    elif isinstance(event, StreamReset):
                        stream = self.streams.pop(event.stream_id, None)
                        self.replies.pop(event.stream_id, None)
                        if stream is not None:
                            stream.context.cancelled.set()
                            if stream.future is not None:
                                stream.future.cancel()
                    elif isinstance(event, ConnectionTerminated):
                        return
        except (OSError, H2Error, ValueError):
            # Invalid HTTP/2 traffic closes this connection; no request bytes or
            # metadata are logged. Other connections continue normally.
            pass
        finally:
            for stream in self.streams.values():
                stream.context.cancelled.set()
                if stream.future is not None:
                    stream.future.cancel()
            self.wake_read.close()
            self.wake_write.close()


class _TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


class H2Server:
    def __init__(self, application, host="127.0.0.1", port=50051, log_callback=None):
        self.application, self.log_callback = application, log_callback
        self._stopped = threading.Event()
        self._lock = threading.RLock()
        self._clients = set()
        self._thread = None
        self._closed = False
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with owner._lock:
                    if owner._stopped.is_set():
                        return
                    owner._clients.add(self.request)
                try:
                    _Connection(owner, self.request).run()
                finally:
                    with owner._lock:
                        owner._clients.discard(self.request)

        listener_type = _TCPServer
        if ":" in host:
            listener_type = type("_IPv6Server", (_TCPServer,), {"address_family": socket.AF_INET6})
        self._listener = listener_type((host, port), Handler)
        self.address = self._listener.server_address[:2]
        self.port = self.address[1]
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="idoly-rpc")

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._closed

    def _log(self, message):
        LOG.info("%s", message)
        if self.log_callback is not None:
            try:
                self.log_callback(message[:400])
            except Exception:
                LOG.warning("RPC log callback failed")

    def start(self):
        with self._lock:
            if self._stopped.is_set():
                raise ValueError("This server has stopped; create a new server to restart")
            if self._thread is None:
                self._thread = threading.Thread(target=self._listener.serve_forever,
                    kwargs={"poll_interval": 0.05}, name="idoly-h2", daemon=True)
                self._thread.start()
        self._log(f"gRPC listening on {self.address[0]}:{self.port}")
        return self

    def stop(self):
        with self._lock:
            if self._closed:
                return
            self._stopped.set()
            clients = list(self._clients)
            thread = self._thread
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if thread is not None and thread.is_alive():
            self._listener.shutdown()
        self._listener.server_close()
        if thread is not None:
            thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError("gRPC listener did not stop; retry Stop")
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._closed = True
        self._log("gRPC stopped")


def create_server(application, host="127.0.0.1", port=50051, *, log_callback=None):
    """Return a bound server; call start() and stop() to own its lifecycle."""
    return H2Server(application, host, port, log_callback)
