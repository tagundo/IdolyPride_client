"""Read-only runtime observations over the optional, bounded loopback route."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from idoly_local.assets import create_asset_server


class RuntimeDiagnosticsHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "master").mkdir()
        (self.root / "master" / "public.pack").write_bytes(b"public-pack")
        # A public file must never accidentally enable the reserved route or
        # supply its GET, HEAD, encoded-path or query-selector variants.
        (self.root / "diagnostics").mkdir()
        (self.root / "diagnostics" / "runtime").write_bytes(b"not-runtime-status")

    def serve(self, callback=None):
        server = create_asset_server("127.0.0.1", 0, self.root,
                                     runtime_status_callback=callback)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

        self.addCleanup(cleanup)
        return server

    def request(self, server, path="/diagnostics/runtime", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_enabled_get_returns_safe_rpc_snapshot_with_valid_json_and_no_cache(self):
        snapshot = {"schema": 1, "runtime": {"running": True, "logs": [
            "RPC /api.System/Check -> OK", "RPC /api.Deck/Save -> UNIMPLEMENTED"]},
            "client_diagnostics": {"received_events": 0}}
        callback = mock.Mock(return_value=snapshot)
        status, headers, body = self.request(self.serve(callback))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), snapshot)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        callback.assert_called_once_with()

    def test_disabled_route_is_404_and_existing_public_file_serving_is_unchanged(self):
        server = self.serve()
        for path in ("/diagnostics/runtime", "/diagnostics/%72untime", "/diagnostics/runtime?profile=x"):
            with self.subTest(path=path):
                self.assertEqual(self.request(server, path)[0], 404)
        status, _, body = self.request(server, "/master/public.pack")
        self.assertEqual((status, body), (200, b"public-pack"))

    def test_query_encoded_path_and_non_get_never_call_the_callback(self):
        callback = mock.Mock(return_value={"schema": 1})
        server = self.serve(callback)
        for path, method in (("/diagnostics/runtime?profile=x", "GET"),
                             ("/diagnostics/runtime?", "GET"),
                             ("/diagnostics/%72untime", "GET"),
                             ("/diagnostics/runtime", "HEAD"),
                             ("/diagnostics/%72untime", "HEAD"),
                             ("/diagnostics/runtime", "POST")):
            with self.subTest(path=path, method=method):
                status, headers, body = self.request(server, path, method)
                self.assertEqual(status, 404)
                self.assertEqual(headers["Cache-Control"], "no-store")
                if method == "HEAD":
                    self.assertEqual(body, b"")
                else:
                    self.assertEqual(json.loads(body), {"error": "not_found"})
        callback.assert_not_called()

    def test_nonloopback_peer_is_rejected_before_callback_even_with_forwarded_header(self):
        callback = mock.Mock(return_value={"schema": 1})
        server = self.serve(callback)
        with mock.patch("idoly_local.assets.ipaddress.ip_address",
                        return_value=SimpleNamespace(is_loopback=False)):
            status, headers, body = self.request(server, headers={"X-Forwarded-For": "127.0.0.1"})
        self.assertEqual((status, json.loads(body)), (403, {"error": "loopback_required"}))
        self.assertEqual(headers["Cache-Control"], "no-store")
        callback.assert_not_called()

    def test_callback_and_encoding_failures_return_fixed_unavailable_without_details(self):
        secret = "synthetic-private-callback-detail"
        callback = mock.Mock(side_effect=[RuntimeError(secret), [secret], {"bad": object()}, {"bad": float("nan")}])
        server = self.serve(callback)
        with self.assertLogs("idoly_local.assets", level="INFO") as logs:
            for _ in range(4):
                status, headers, body = self.request(server)
                self.assertEqual((status, json.loads(body)),
                                 (503, {"error": "runtime_diagnostics_unavailable"}))
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertNotIn(secret, body.decode())
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_utf8_body_limit_is_checked_before_sending_a_success_response(self):
        limit = 1024 * 1024
        callback = mock.Mock(side_effect=[{"x": "x" * (limit - 8)},
                                         {"x": "x" * (limit - 7)},
                                         {"x": "한" * (limit // 3 + 1)}])
        server = self.serve(callback)
        status, headers, body = self.request(server)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), limit)
        self.assertEqual(int(headers["Content-Length"]), limit)
        for _ in range(2):
            status, headers, body = self.request(server)
            self.assertEqual((status, json.loads(body)),
                             (503, {"error": "runtime_diagnostics_unavailable"}))
            self.assertLess(len(body), limit)
            self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_noncallable_observer_is_rejected_before_binding(self):
        with self.assertRaisesRegex(ValueError, "Runtime status callback must be callable"):
            create_asset_server("127.0.0.1", 0, self.root, runtime_status_callback={})


if __name__ == "__main__":
    unittest.main()
