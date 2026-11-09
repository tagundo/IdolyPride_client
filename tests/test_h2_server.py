"""Exercise pure-Python HTTP/2 through real grpcio and low-window HTTP/2 peers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gzip
import socket
import struct
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import grpc
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, ResponseReceived, StreamEnded, TrailersReceived
from h2.settings import SettingCodes

from idoly_local import codec
from idoly_local.h2_server import MAX_MESSAGE, create_server
from idoly_local.rpc import RpcCode


class EchoApplication:
    def __init__(self):
        self.calls = []
        self.slow_started = threading.Event()
        self.slow_release = threading.Event()

    def handle(self, path, raw, context):
        self.calls.append((path, tuple(context.invocation_metadata())))
        if path == "/api.Test/Denied":
            context.abort(RpcCode.UNAUTHENTICATED, "로그인이 필요합니다")
        if path == "/api.Test/Broken":
            raise ValueError("private input must not reach response or logs")
        if path == "/api.Test/Slow":
            self.slow_started.set()
            self.slow_release.wait(5)
        if path == "/api.Master/Get":
            return b"m" * 55000
        if path == "/api.Test/Huge":
            return b"x" * (MAX_MESSAGE + 1)
        return codec.decode(raw)


class H2TransportTests(unittest.TestCase):
    def setUp(self):
        self.application = EchoApplication()
        self.logs = []
        self.server = create_server(self.application, port=0, log_callback=self.logs.append).start()
        self.addCleanup(self.server.stop)
        self.channel = grpc.insecure_channel(f"127.0.0.1:{self.server.port}")
        self.addCleanup(self.channel.close)
        grpc.channel_ready_future(self.channel).result(timeout=3)

    def rpc(self, path="/api.Test/Echo"):
        return self.channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)

    def raw_h2(self, frame, *, path="/api.Test/Echo", window=65535, extra_headers=()):
        peer = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
        peer.initiate_connection()
        peer.update_settings({SettingCodes.INITIAL_WINDOW_SIZE: window})
        headers = [(":method", "POST"), (":scheme", "http"), (":authority", "localhost"),
                   (":path", path), ("content-type", "application/grpc"), ("te", "trailers"), *extra_headers]
        peer.send_headers(1, headers)
        peer.send_data(1, frame, end_stream=True)
        received, response_headers, chunks = bytearray(), {}, 0
        with socket.create_connection(self.server.address, timeout=3) as connection:
            connection.settimeout(5)
            connection.sendall(peer.data_to_send())
            ended = False
            while not ended:
                data = connection.recv(65536)
                self.assertTrue(data, "HTTP/2 connection closed before gRPC trailers")
                for event in peer.receive_data(data):
                    if isinstance(event, (ResponseReceived, TrailersReceived)):
                        response_headers.update(event.headers)
                    elif isinstance(event, DataReceived):
                        received.extend(event.data)
                        chunks += 1
                        peer.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        ended = True
                outgoing = peer.data_to_send()
                if outgoing:
                    connection.sendall(outgoing)
        return bytes(received), response_headers, chunks

    def test_real_grpc_unary_empty_binary_metadata_and_large_message(self):
        self.assertEqual(self.rpc()(b"", timeout=3), b"")
        self.assertEqual(self.rpc()(b"hello", metadata=(("x-auth-token", "local-token"), ("evidence-bin", b"\x00\xff")), timeout=3), b"hello")
        self.assertIn(("x-auth-token", "local-token"), self.application.calls[-1][1])
        self.assertIn(("evidence-bin", b"\x00\xff"), self.application.calls[-1][1])
        payload = bytes(range(256)) * 8192
        self.assertEqual(self.rpc()(payload, timeout=10), payload)

    def test_parallel_streams_complete_while_another_handler_waits(self):
        with ThreadPoolExecutor(max_workers=12) as executor:
            pending = executor.submit(self.rpc("/api.Test/Slow"), b"slow", timeout=5)
            self.assertTrue(self.application.slow_started.wait(2))
            try:
                results = list(executor.map(lambda number: self.rpc()(str(number).encode(), timeout=3), range(20)))
                self.assertEqual(results, [str(number).encode() for number in range(20)])
                self.assertFalse(pending.done())
            finally:
                self.application.slow_release.set()
            self.assertEqual(pending.result(timeout=3), b"slow")

    def test_master_response_respects_small_stream_window_and_trailers(self):
        body, headers, chunks = self.raw_h2(b"\0\0\0\0\0", path="/api.Master/Get", window=1024)
        self.assertEqual(headers["grpc-status"], "0")
        self.assertGreater(chunks, 40)
        self.assertEqual(body[0], 0)
        self.assertEqual(len(body), struct.unpack_from("!I", body, 1)[0] + 5)
        self.assertEqual(codec.decode(body[5:]), b"m" * 55000)

    def test_application_abort_and_unexpected_error_use_grpc_status(self):
        with self.assertRaises(grpc.RpcError) as denied:
            self.rpc("/api.Test/Denied")(b"", timeout=3)
        self.assertEqual(denied.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        self.assertEqual(denied.exception.details(), "로그인이 필요합니다")
        with self.assertRaises(grpc.RpcError) as broken:
            self.rpc("/api.Test/Broken")(b"", timeout=3)
        self.assertEqual(broken.exception.code(), grpc.StatusCode.INTERNAL)
        self.assertNotIn("private input", broken.exception.details())
        self.assertFalse(any("private input" in item for item in self.logs))

    def test_unknown_or_streaming_method_is_unimplemented(self):
        self.application.schema = SimpleNamespace(methods={"/api.Health/Watch": SimpleNamespace(client_streaming=False, server_streaming=True)})
        for path in ("/api.Unknown/Call", "/api.Health/Watch"):
            with self.subTest(path=path), self.assertRaises(grpc.RpcError) as caught:
                self.rpc(path)(b"", timeout=3)
            self.assertEqual(caught.exception.code(), grpc.StatusCode.UNIMPLEMENTED)
        self.assertFalse(self.application.calls)

    def test_malformed_frames_and_limits_do_not_call_application(self):
        cases = [(b"", RpcCode.INVALID_ARGUMENT), (b"\x02\0\0\0\0", RpcCode.INVALID_ARGUMENT),
                 (b"\0\0\0\0\x03a", RpcCode.INVALID_ARGUMENT),
                 (b"\0\0\0\0\0\0\0\0\0\0", RpcCode.INVALID_ARGUMENT),
                 (b"\0" + struct.pack("!I", MAX_MESSAGE + 1), RpcCode.RESOURCE_EXHAUSTED)]
        for frame, code in cases:
            with self.subTest(frame=frame):
                _, headers, _ = self.raw_h2(frame)
                self.assertEqual(headers["grpc-status"], str(int(code)))
        self.assertFalse(self.application.calls)

    def test_gzip_grpc_request_is_decoded_before_game_envelope(self):
        encoded = codec.encode(b"compressed payload")
        compressed = gzip.compress(encoded)
        frame = b"\1" + struct.pack("!I", len(compressed)) + compressed
        response, headers, _ = self.raw_h2(frame, extra_headers=(("grpc-encoding", "gzip"),))
        self.assertEqual(headers["grpc-status"], "0")
        self.assertEqual(codec.decode(response[5:]), b"compressed payload")

    def test_corrupt_gzip_maps_to_invalid_argument(self):
        damaged = bytearray(gzip.compress(b"message"))
        damaged[10] = 0xFF
        frame = b"\1" + struct.pack("!I", len(damaged)) + damaged
        _, headers, _ = self.raw_h2(frame, extra_headers=(("grpc-encoding", "gzip"),))
        self.assertEqual(headers["grpc-status"], str(int(RpcCode.INVALID_ARGUMENT)))
        self.assertFalse(self.application.calls)

    def test_response_limit_maps_to_resource_exhausted(self):
        with self.assertRaises(grpc.RpcError) as caught:
            self.rpc("/api.Test/Huge")(b"", timeout=3)
        self.assertEqual(caught.exception.code(), grpc.StatusCode.RESOURCE_EXHAUSTED)

    def test_failed_listener_shutdown_retains_ownership_for_retry(self):
        with mock.patch.object(self.server._listener, "shutdown", side_effect=RuntimeError("temporary shutdown failure")):
            with self.assertRaises(RuntimeError):
                self.server.stop()
        self.assertTrue(self.server.running)
        self.server.stop()
        self.assertFalse(self.server.running)
        replacement = create_server(EchoApplication(), port=self.server.port)
        replacement.stop()

    def test_stop_closes_live_connections_and_port_can_restart(self):
        port = self.server.port
        self.assertEqual(self.rpc()(b"before", timeout=3), b"before")
        self.server.stop()
        self.server.stop()
        replacement = create_server(EchoApplication(), port=port).start()
        self.addCleanup(replacement.stop)
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            rpc = channel.unary_unary("/api.Test/Echo", request_serializer=codec.encode, response_deserializer=codec.decode)
            self.assertEqual(rpc(b"after", timeout=3), b"after")


if __name__ == "__main__":
    unittest.main()
