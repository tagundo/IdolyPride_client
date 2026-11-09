"""Real local HTTP diagnostics, transfer observations and safe runtime export."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from idoly_local.app_runtime import Runtime
from idoly_local.assets import create_asset_server
from idoly_local.diagnostics import ClientDiagnostics


def batch(*events):
    return json.dumps({"schema": 1, "source": "android-game", "events": list(events)}).encode()


EXCEPTION = {"kind": "exception", "type": "NullReferenceException",
             "frames": ["Solis.OutGame.HomeTopScreenPresenter.SetHomeEnterData"]}
STARTED = {"kind": "status", "code": "collector_started"}


class DiagnosticHTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "assets"
        (self.root / "master").mkdir(parents=True)
        self.content = bytes(range(256)) * 1024
        (self.root / "master" / "fixture.pack").write_bytes(self.content)
        self.logs = []
        self.diagnostics = ClientDiagnostics(self.logs.append)
        self.transfers = []
        self.completed = threading.Event()

        def observe(event):
            self.transfers.append(event)
            if event["phase"] in ("completed", "failed"):
                self.completed.set()

        self.server = self.serve(self.diagnostics, observe)

    def serve(self, diagnostics, observer):
        server = create_asset_server("127.0.0.1", 0, self.root,
                                     diagnostics=diagnostics, transfer_callback=observer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

        self.addCleanup(cleanup)
        return server

    def request(self, method, path, body=None, headers=None, *, server=None, auto_length=True):
        server = server or self.server
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.putrequest(method, path)
            values = dict(headers or {})
            if auto_length and body is not None and "Content-Length" not in values:
                values["Content-Length"] = str(len(body))
            for name, value in values.items():
                connection.putheader(name, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post(self, raw, **kwargs):
        return self.request("POST", "/diagnostics/client", raw,
                            {"Content-Type": "application/json"}, **kwargs)

    def test_real_post_and_json_status_share_only_validated_events(self):
        code, headers, raw = self.post(batch(STARTED, EXCEPTION))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["accepted"], 2)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        code, headers, raw = self.request("GET", "/diagnostics/status")
        self.assertEqual(code, 200)
        result = json.loads(raw)
        self.assertEqual(result["events"], [STARTED, EXCEPTION])
        self.assertEqual(result["latest_exception"], EXCEPTION)
        self.assertEqual(result["progress"]["stage"], "unity_exception")
        self.assertEqual(int(headers["Content-Length"]), len(raw))
        self.assertEqual(len(self.logs), 2)
        self.assertEqual(self.transfers, [])

    def test_http_rejections_are_atomic_and_never_log_raw_body_or_query(self):
        self.post(batch(STARTED))
        before = self.diagnostics.status()
        secret = "synthetic-private-token-not-a-real-account"
        invalid = batch(EXCEPTION, {"kind": "status", "code": "logcat_started", "token": secret})
        cases = [
            ("/diagnostics/other?token=" + secret, batch(EXCEPTION), {"Content-Type": "application/json"}, 404, True),
            ("/diagnostics/client?token=" + secret, batch(EXCEPTION), {"Content-Type": "application/json"}, 404, True),
            ("/diagnostics/client", batch(EXCEPTION), {"Content-Type": "text/plain"}, 415, True),
            ("/diagnostics/client", b"", {"Content-Type": "application/json", "Content-Length": "32769"}, 413, True),
            ("/diagnostics/client", b"", {"Content-Type": "application/json", "Transfer-Encoding": "chunked"}, 400, False),
            ("/diagnostics/client", None, {"Content-Type": "application/json"}, 411, False),
            ("/diagnostics/client", b"{" + secret.encode(), {"Content-Type": "application/json"}, 400, True),
            ("/diagnostics/client", invalid, {"Content-Type": "application/json"}, 400, True),
        ]
        with self.assertLogs("idoly_local.assets", level="INFO") as captured:
            for path, raw, headers, expected, auto_length in cases:
                with self.subTest(path=path, expected=expected):
                    code, _, response = self.request("POST", path, raw, headers, auto_length=auto_length)
                    self.assertEqual(code, expected)
                    self.assertNotIn(secret, response.decode())
                    self.assertEqual(self.diagnostics.status(), before)
        self.assertNotIn(secret, "\n".join(captured.output + self.logs))
        self.assertNotIn("SetHomeEnterData", "\n".join(self.logs))
        self.assertEqual(self.transfers, [])

    def test_nonloopback_peer_cannot_read_or_submit_diagnostics(self):
        with mock.patch("idoly_local.assets.ipaddress.ip_address",
                        return_value=SimpleNamespace(is_loopback=False)):
            code, _, response = self.post(batch(EXCEPTION))
            self.assertEqual((code, json.loads(response)), (403, {"error": "loopback_required"}))
            code, _, response = self.request("GET", "/diagnostics/status")
            self.assertEqual((code, json.loads(response)), (403, {"error": "loopback_required"}))
        self.assertEqual(self.diagnostics.status()["received_events"], 0)
        self.assertEqual(self.logs, [])

    def test_actual_get_head_and_range_report_only_bytes_transferred(self):
        code, headers, content = self.request("HEAD", "/master/fixture.pack")
        self.assertEqual((code, content), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), len(self.content))
        self.assertEqual(self.transfers, [])
        for range_value, expected in [(None, self.content), ("bytes=1024-2047", self.content[1024:2048])]:
            self.completed.clear()
            start = len(self.transfers)
            headers = {"Range": range_value} if range_value else {}
            code, response_headers, content = self.request("GET", "/master/fixture.pack", headers=headers)
            self.assertEqual(code, 206 if range_value else 200)
            self.assertEqual(content, expected)
            self.assertTrue(self.completed.wait(2))
            events = self.transfers[start:]
            self.assertEqual(events[0]["phase"], "started")
            self.assertEqual(events[0]["sent_bytes"], 0)
            self.assertEqual(events[-1]["phase"], "completed")
            self.assertEqual(events[-1]["sent_bytes"], len(content))
            self.assertTrue(all(event["total_bytes"] == len(content) for event in events))
            self.assertTrue(all(0 <= event["sent_bytes"] <= len(content) for event in events))
            self.assertEqual(int(response_headers["Content-Length"]), len(content))
        # A partial response's total is its 1 KiB response, never the 256 KiB
        # source file, an estimated download queue or the entire game archive.
        self.assertEqual(self.transfers[-1]["total_bytes"], 1024)
        count = len(self.transfers)
        self.assertEqual(self.request("GET", "/master/missing.pack")[0], 404)
        self.assertEqual(self.request("GET", "/master/fixture.pack", headers={"Range": "bytes=999999-"})[0], 416)
        self.assertEqual(len(self.transfers), count)

    def test_failing_observer_cannot_interrupt_file_response(self):
        called = threading.Event()

        def broken_observer(_event):
            called.set()
            raise RuntimeError("synthetic observer failure")

        server = self.serve(ClientDiagnostics(), broken_observer)
        code, _, content = self.request("GET", "/master/fixture.pack", server=server)
        self.assertEqual((code, content), (200, self.content))
        self.assertTrue(called.wait(2))

    def test_runtime_export_includes_diagnostics_and_real_transfer_without_account_database(self):
        # A private sibling database represents local account/session storage;
        # the diagnostic contract and public assets never read or export it.
        secret = "synthetic-private-session-not-a-real-account"
        with sqlite3.connect(self.directory / "state.db") as database:
            database.execute("CREATE TABLE account (session_token TEXT, firebase_id TEXT)")
            database.execute("INSERT INTO account VALUES (?, ?)", (secret, "synthetic-firebase-id"))
        runtime = Runtime("synthetic-local-profile")
        transferred = threading.Event()

        def observe(event):
            runtime._observe_transfer(event)
            if event["phase"] == "completed":
                transferred.set()

        server = self.serve(runtime._diagnostics, observe)
        self.assertEqual(self.post(batch(EXCEPTION), server=server)[0], 200)
        code, _, content = self.request("GET", "/master/fixture.pack",
                                        headers={"Range": "bytes=0-31"}, server=server)
        self.assertEqual((code, content), (206, self.content[:32]))
        self.assertTrue(transferred.wait(2))
        status = runtime.status()
        self.assertNotIn("events", status["client_diagnostics"])
        self.assertEqual(status["client_diagnostics"]["latest_exception"], EXCEPTION)
        self.assertEqual(status["asset_transfer"]["session_bytes_sent"], 32)
        self.assertEqual(status["asset_transfer"]["total_bytes"], 32)
        self.assertEqual(status["asset_transfer"]["completed_requests"], 1)
        self.assertEqual(status["asset_transfer"]["active_requests"], 0)
        snapshot = runtime.diagnostics_snapshot()
        self.assertEqual(snapshot["schema"], 1)
        self.assertEqual(snapshot["client_diagnostics"]["events"], [EXCEPTION])
        exported = json.dumps(snapshot)
        for private in [secret, "synthetic-firebase-id", "session_token", "firebase_id", "state.db"]:
            self.assertNotIn(private, exported)
        self.assertEqual(self.request("GET", "/../state.db", server=server)[0], 404)
        # Export mutation must not overwrite the receiver's saved exception.
        snapshot["client_diagnostics"]["events"][0]["frames"].clear()
        self.assertEqual(runtime.diagnostics_snapshot()["client_diagnostics"]["latest_exception"], EXCEPTION)


if __name__ == "__main__":
    unittest.main()
