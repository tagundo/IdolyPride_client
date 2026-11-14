#!/usr/bin/env python3
"""Test real macOS NSURLSession loopback HTTP with bounded, owned fixtures.

Starts only ephemeral loopback HTTP servers and command-line Foundation clients.
No UIKit, Unity, app windows, Simulator or physical PlayCover is executed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import socket
import sys
import tempfile
import threading

import test_mac_menu as host

HERE = Path(__file__).resolve().parent
MAX_BODY = 16384


@contextmanager
def loopback(mode, *, redirect_port=None):
    observations = {"requests": [], "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *args):
            pass

        def do_GET(self):
            observations["requests"].append(self.path)
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{redirect_port}/redirect-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 404 if mode == "not_found" else 200
            raw = b'{"schema":1,"revision":0}' if mode in ("json", "not_found") else b"invalid-json"
            if mode == "array":
                raw = b"[]"
            if mode == "oversized":
                raw = b" " * (MAX_BODY + 1)
            if mode == "timeout":
                raw = b"{}"
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if mode != "oversized":
                self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if mode == "timeout":
                observations["release"].wait(5)
                return
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_port, observations
    finally:
        observations["release"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        host.require(not thread.is_alive(), "local_http_fixture_server_did_not_stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.absolute()
    host.require(not report_path.exists() and not report_path.is_symlink(), "fresh_local_http_report_required")
    report = {"schema": 1, "status": "FAIL", "actual_macos_foundation_execution": False,
              "actual_iOS_Unity_execution": False, "physical_PlayCover_execution": False,
              "windows_or_simulators_created": False, "runs": []}
    try:
        host.require(sys.platform == "darwin", "macos_and_Xcode_required_no_Foundation_execution")
        architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
        host.require(architecture in ("arm64", "x86_64"), "supported_host_architecture_required")
        sources = [HERE / "IdolyLocalHTTP.h", HERE / "IdolyLocalHTTP.m", HERE / "tests/local_http_test.m",
                   Path(__file__).resolve(), HERE / "test_mac_menu.py"]
        pins = {str(path.relative_to(HERE)): host.sha(path) for path in sources}
        sdk = host.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).decode().strip()
        compiler = host.run(["xcrun", "--sdk", "macosx", "--find", "clang"]).decode().strip()
        host.require(sdk.startswith("/") and compiler.startswith("/"), "absolute_Apple_tool_paths_required")
        with tempfile.TemporaryDirectory(prefix="idoly-local-http-compile-") as scratch:
            binary = Path(scratch) / "local_http_test"
            host.run([compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                      "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation",
                      HERE / "IdolyLocalHTTP.m", HERE / "tests/local_http_test.m", "-o", binary])
            image = host.inspect_host_binary(binary, architecture)

            def request(port, timeout=2):
                raw = host.run([binary, "--request", str(port), str(timeout)], timeout=15)
                host.require(0 < len(raw) <= 8192, "local_http_result_bound")
                result = json.loads(raw)
                host.require(type(result) is dict and result.get("status") == "PASS"
                             and result.get("actual_macos_foundation_execution") is True,
                             "local_http_fixture_execution_failed")
                readiness = result.get("readiness", {})
                host.require(readiness.get("worker_main_thread") is False
                             and type(readiness.get("received_bytes")) is int
                             and 0 <= readiness["received_bytes"] <= MAX_BODY
                             and readiness.get("url") == f"http://127.0.0.1:{port}/client/playback",
                             "local_http_worker_or_url_or_bound_failed")
                return result, readiness

            with loopback("json") as (port, observations):
                validation = json.loads(host.run([binary, "--validation", str(port)], timeout=15))
                host.require(validation.get("status") == "PASS" and validation.get("main_thread_rejected") is True
                             and validation.get("invalid_ports_rejected") is True
                             and validation.get("invalid_timeout_rejected") is True
                             and observations["requests"] == [], "local_http_invalid_input_made_request")
                report["validation"] = validation
            for mode, expected in (("json", "none"), ("not_found", "http_status"),
                                   ("invalid_json", "invalid_json"), ("array", "invalid_json"),
                                   ("oversized", "response_too_large"), ("timeout", "timeout")):
                with loopback(mode) as (port, observations):
                    result, readiness = request(port, 1 if mode == "timeout" else 2)
                    host.require(readiness.get("error_code") == expected and readiness.get("ok") is (mode == "json")
                                 and readiness.get("body_is_json") is (mode == "json")
                                 and observations["requests"] == ["/client/playback"], "local_http_response_case_failed")
                    host.require(readiness.get("http_status") == (404 if mode == "not_found" else 200),
                                 "local_http_status_not_preserved")
                    report["runs"].append({"fixture": mode, **result})
            with loopback("json") as (target_port, target):
                with loopback("redirect", redirect_port=target_port) as (port, observations):
                    result, readiness = request(port)
                    host.require(readiness.get("error_code") == "redirect" and readiness.get("http_status") == 302
                                 and readiness.get("ok") is False and target["requests"] == []
                                 and observations["requests"] == ["/client/playback"], "local_http_redirect_followed")
                    report["runs"].append({"fixture": "redirect_not_followed", **result})
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                closed_port = reservation.getsockname()[1]
            result, readiness = request(closed_port)
            host.require(readiness.get("error_code") == "connection" and readiness.get("http_status") == 0
                         and readiness.get("ok") is False, "local_http_connection_failure_not_classified")
            report["runs"].append({"fixture": "closed_loopback_port", **result})
            host.require(pins == {str(path.relative_to(HERE)): host.sha(path) for path in sources},
                         "local_http_sources_changed_during_test")
            report.update(status="PASS", actual_macos_foundation_execution=True, host_architecture=architecture,
                          sdk=sdk, source_sha256=pins, executable=image,
                          fixed_loopback_path_verified=True, redirects_not_followed=True,
                          invalid_inputs_made_no_requests=True, body_and_deadline_bounded=True)
    except Exception as error:
        report["error"] = str(error) if isinstance(error, ValueError) else type(error).__name__
    host.write_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "actual_macos_foundation_execution": report["actual_macos_foundation_execution"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
