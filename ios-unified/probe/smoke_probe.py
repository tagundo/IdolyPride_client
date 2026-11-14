#!/usr/bin/env python3
"""Run the integrated server's fake Unity host in one disposable iOS Simulator.

Actual execution requires macOS/Xcode. Portable tests mock simulator control;
they do not establish simulator, device, game, or PlayCover compatibility.
Only a UUID returned by this invocation's `simctl create` may be changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

BUNDLE_ID = "game.qualiarts.idolypride.iosprobe"
DESCRIPTOR_MEMBER = "protocol/idolypride-6.1.1.pb"
MAX_JSON = 64 * 1024
MAX_DESCRIPTOR = 16 * 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT = 2 * 1024 * 1024
RPC_PATHS = ("/api.System/Check", "/api.Auth/Login", "/api.Home/Enter")
# A well-formed unknown protobuf varint makes empty requests exercise AES too.
PUBLIC_PROBE_FIELD = b"\xc0\xa3\x09\x01"  # field 19000, wire type 0, value 1


class ProbeError(ValueError):
    """A bounded, credential-free failure code suitable for the JSON audit."""


def require(value, code):
    if not value:
        raise ProbeError(code)


def read_bounded(path, maximum):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "invalid_bounded_file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns),
                "file_changed_while_opening")
        with os.fdopen(fd, "rb", closefd=False) as incoming:
            raw = incoming.read(maximum + 1)
        after = os.fstat(fd)
        require(len(raw) == before.st_size and after.st_size == before.st_size
                and after.st_mtime_ns == before.st_mtime_ns,
                "file_changed_while_reading")
        return raw
    finally:
        os.close(fd)


def parse_json(raw, maximum=MAX_JSON):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def nonfinite(_value):
        raise ProbeError("nonfinite_json")
    require(0 < len(raw) <= maximum, "json_size_bound")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProbeError("invalid_json") from None
    require(type(value) is dict, "json_object_required")
    return value


def write_audit(path, report):
    raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(raw) <= MAX_JSON, "audit_size_bound")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), "fresh_audit_path_required")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _simctl(arguments, timeout):
    try:
        result = subprocess.run(["/usr/bin/xcrun", "simctl", *arguments],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ProbeError("simctl_timeout") from None
    require(len(result.stdout) <= MAX_COMMAND_OUTPUT and len(result.stderr) <= MAX_COMMAND_OUTPUT,
            "simctl_output_bound")
    require(result.returncode == 0, "simctl_failed")
    return result.stdout


def discover(device_type, runtime, remaining):
    types = parse_json(_simctl(["list", "devicetypes", "--json"], remaining()), MAX_COMMAND_OUTPUT)
    runtimes = parse_json(_simctl(["list", "runtimes", "--json"], remaining()), MAX_COMMAND_OUTPUT)
    choices = [item for item in runtimes.get("runtimes", [])
               if type(item) is dict and item.get("isAvailable") is True
               and str(item.get("identifier", "")).startswith("com.apple.CoreSimulator.SimRuntime.iOS-")]
    if runtime is not None:
        choices = [item for item in choices if item.get("identifier") == runtime]
    require(bool(choices), "available_ios_runtime_required")
    def version(item):
        value = str(item.get("version", ""))
        require(bool(re.fullmatch(r"\d+(?:\.\d+){0,3}", value)), "invalid_runtime_version")
        return tuple(map(int, value.split(".")))
    chosen_runtime = max(choices, key=version)
    numbers = version(chosen_runtime)
    require(len(numbers) <= 3 and all(0 <= number <= 255 for number in numbers), "invalid_runtime_version")
    numbers = (*numbers, *(0 for _ in range(3 - len(numbers))))
    runtime_version = (numbers[0] << 16) | (numbers[1] << 8) | numbers[2]
    def compatible(item):
        minimum, maximum = item.get("minRuntimeVersion", 0), item.get("maxRuntimeVersion", 0xFFFFFFFF)
        return (type(minimum) is int and type(maximum) is int
                and minimum <= runtime_version <= maximum)
    choices = [item for item in types.get("devicetypes", []) if type(item) is dict
               and str(item.get("identifier", "")).startswith(("com.apple.CoreSimulator.SimDeviceType.iPhone-",
                                                               "com.apple.CoreSimulator.SimDeviceType.iPad-"))
               and compatible(item)]
    if device_type is not None:
        choices = [item for item in choices if item.get("identifier") == device_type]
    else:
        choices = [item for item in choices if ".iPhone-" in item["identifier"]]
    require(bool(choices), "ios_device_type_required")
    preferred = ("iPhone-16-Pro", "iPhone-15-Pro", "iPhone-14-Pro")
    rank = lambda item: next((i for i, suffix in enumerate(preferred)
                             if item["identifier"].endswith("." + suffix)), len(preferred))
    chosen_type = min(choices, key=rank)
    return chosen_type["identifier"], chosen_runtime["identifier"]


def boot_created_simulator(created, remaining):
    _simctl(["boot", created], remaining())
    # A cold first boot can take longer than one bounded simctl invocation.
    # Timing out that observer does not cancel the owned Simulator's boot.
    while True:
        try:
            _simctl(["bootstatus", created, "-b"], remaining())
            return
        except ProbeError as error:
            if str(error) != "simctl_timeout":
                raise
            remaining()  # The original overall deadline remains authoritative.


def load_schema(app):
    from idoly_local.schema import Schema
    payload = Path(app) / "LocalServer" / "ServerData.zip"
    require(payload.is_file() and not payload.is_symlink(), "public_server_payload_required")
    with ZipFile(payload) as archive:
        members = [item for item in archive.infolist() if item.filename == DESCRIPTOR_MEMBER]
        require(len(members) == 1 and 0 < members[0].file_size <= MAX_DESCRIPTOR,
                "bounded_public_descriptor_required")
        with archive.open(members[0]) as incoming:
            raw = incoming.read(MAX_DESCRIPTOR + 1)
        require(len(raw) == members[0].file_size, "descriptor_extent_differs")
    with tempfile.TemporaryDirectory(prefix="idoly-ios-probe-schema-") as directory:
        target = Path(directory) / "public.pb"
        target.write_bytes(raw)
        schema = Schema.from_descriptor_set(target)
    for path in RPC_PATHS:
        schema.method(path)
    return schema, hashlib.sha256(raw).hexdigest()


def validate_report(value):
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1,
            "probe_schema_differs")
    require(type(value.get("original_called")) is int and value["original_called"] == 1
            and value.get("main_thread") is True and value.get("application_argument_matches") is True
            and value.get("command_completion_main_thread") is True,
            "unity_original_gate_failed")
    status, ports, crypto = (value.get(key) for key in ("server_status", "ports", "commoncrypto"))
    require(all(type(item) is dict for item in (status, ports, crypto)), "probe_fields_missing")
    require(type(status.get("schema")) is int and status["schema"] == 1
            and type(status.get("phase")) is int and status["phase"] == 4
            and status.get("hook_installed") is True and status.get("python_initialized") is True
            and status.get("error") is None
            and all(type(status.get(key)) is int and status[key] == 1
                    for key in ("captured", "forwarded", "attempts")),
            "embedded_server_not_ready")
    require(type(ports.get("grpc")) is int and ports["grpc"] == 50051
            and type(ports.get("assets")) is int and ports["assets"] == 8080
            and ports.get("grpc_connect") is True and ports.get("assets_connect") is True,
            "embedded_listener_probe_failed")
    require(crypto.get("nist_aes128_cbc") is True and crypto.get("nist_aes256_cbc") is True,
            "commoncrypto_fixture_failed")
    native_crypto = value.get("native_crypto")
    require(value.get("crypto_completion_main_thread") is True and type(native_crypto) is dict
            and all(native_crypto.get(key) is True for key in
                    ("ok", "nist_encrypt", "nist_decrypt", "invalid_iv_rejected"))
            and native_crypto.get("worker_main_thread") is False,
            "python_commoncrypto_bridge_failed")
    host = value.get("host_status")
    require(type(host) is dict and host.get("ok") is True
            and type(host.get("id")) is int and host["id"] == 1, "native_status_command_failed")
    result = host.get("result")
    require(type(result) is dict and result.get("state") == "ready" and result.get("running") is True
            and result.get("last_error") is None, "python_host_not_ready")
    runtime = result.get("runtime")
    require(type(runtime) is dict and runtime.get("running") is True
            and runtime.get("grpc_address") == "127.0.0.1:50051"
            and runtime.get("asset_url") == "http://127.0.0.1:8080", "python_host_listeners_differ")
    # Copy only public, explicitly checked fields into the audit.
    return {"schema": 1, "original_called": 1, "main_thread": True,
            "application_argument_matches": True, "command_completion_main_thread": True,
            "crypto_completion_main_thread": True,
            "native_crypto": {"ok": True, "nist_encrypt": True, "nist_decrypt": True,
                              "invalid_iv_rejected": True, "worker_main_thread": False},
            "server_status": {key: status[key] for key in
                ("schema", "phase", "hook_installed", "python_initialized", "captured", "forwarded", "attempts")},
            "ports": {key: ports[key] for key in ("grpc", "assets", "grpc_connect", "assets_connect")},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "runtime": {key: runtime[key] for key in ("running", "grpc_address", "asset_url")}}}}


def wait_report(container, remaining):
    documents = Path(container) / "Documents"
    final, waiting = documents / "embedded-probe.json", documents / "embedded-probe-status.json"
    while True:
        remaining()
        try:
            return validate_report(parse_json(read_bounded(final, MAX_JSON)))
        except FileNotFoundError:
            pass
        try:
            status = parse_json(read_bounded(waiting, MAX_JSON)).get("server_status")
            require(type(status) is dict, "invalid_waiting_status")
            require(status.get("phase") != 3 and status.get("error") is None,
                    "native_startup_failed")
        except FileNotFoundError:
            pass
        time.sleep(min(0.25, remaining()))


def unary_h2(path, request, *, token=None, port=50051, timeout=15):
    """One real encrypted unary h2c RPC, restricted to IPv4 loopback."""
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import (ConnectionTerminated, DataReceived, ResponseReceived,
                           StreamEnded, StreamReset, TrailersReceived)
    from idoly_local import codec
    require(path in RPC_PATHS and type(port) is int and 0 < port <= 65535,
            "invalid_probe_rpc")
    require(type(request) is bytes and len(request) <= MAX_JSON, "rpc_request_bound")
    encrypted = codec.encode(request + PUBLIC_PROBE_FIELD)
    require(bool(encrypted), "rpc_request_not_encrypted")
    frame = b"\0" + struct.pack("!I", len(encrypted)) + encrypted
    peer = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    peer.initiate_connection()
    headers = [(":method", "POST"), (":scheme", "http"), (":authority", f"127.0.0.1:{port}"),
               (":path", path), ("content-type", "application/grpc"), ("te", "trailers"),
               ("grpc-timeout", f"{max(1, min(99999999, int(timeout * 1000)))}m")]
    if token is not None:
        require(type(token) is str and 0 < len(token) <= 4096 and token.isascii()
                and not any(ord(c) < 33 or ord(c) > 126 for c in token), "invalid_local_auth_token")
        headers.append(("x-auth-token", token))
    peer.send_headers(1, headers)
    peer.send_data(1, frame, end_stream=True)
    response, metadata, ended = bytearray(), {}, False
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
            connection.sendall(peer.data_to_send())
            while not ended:
                left = deadline - time.monotonic()
                require(left > 0, "rpc_deadline_exceeded")
                connection.settimeout(left)
                raw = connection.recv(64 * 1024)
                require(bool(raw), "rpc_closed_before_trailers")
                for event in peer.receive_data(raw):
                    if isinstance(event, (ResponseReceived, TrailersReceived)):
                        require(event.stream_id == 1, "unexpected_rpc_stream")
                        for key, value in event.headers:
                            require(key not in metadata and len(key) + len(value) <= 8192,
                                    "invalid_rpc_headers")
                            metadata[key] = value
                        require(sum(len(k) + len(v) for k, v in metadata.items()) <= 16 * 1024,
                                "rpc_headers_bound")
                    elif isinstance(event, DataReceived):
                        require(event.stream_id == 1 and len(response) + len(event.data) <= MAX_RESPONSE,
                                "rpc_response_bound")
                        response.extend(event.data)
                        peer.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        require(event.stream_id == 1, "unexpected_rpc_stream")
                        ended = True
                    elif isinstance(event, (ConnectionTerminated, StreamReset)):
                        raise ProbeError("rpc_stream_terminated")
                pending = peer.data_to_send()
                if pending:
                    connection.sendall(pending)
    except OSError:
        raise ProbeError("rpc_loopback_transport_failed") from None
    require(metadata.get(":status") == "200" and metadata.get("grpc-status") == "0"
            and metadata.get("content-type", "").startswith("application/grpc"), "rpc_status_failed")
    require(len(response) >= 5 and response[0] == 0
            and len(response) == 5 + struct.unpack_from("!I", response, 1)[0], "invalid_unary_rpc_frame")
    require(len(response) > 5, "rpc_response_not_encrypted")
    plain = codec.decode(bytes(response[5:]))
    return plain, {"path": path, "grpc_status": 0, "request_encrypted": True,
                   "response_encrypted": True, "response_bytes": len(plain),
                   "response_sha256": hashlib.sha256(plain).hexdigest()}


def probe_rpcs(schema, *, port=50051, timeout=15):
    rows = []
    token = None
    deadline = time.monotonic() + timeout
    for path in RPC_PATHS:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "rpc_deadline_exceeded")
        request = schema.request_type(path)().SerializeToString()
        plain, row = unary_h2(path, request, token=token, port=port, timeout=remaining)
        result = schema.response_type(path).FromString(plain)
        if path == RPC_PATHS[0]:
            require(result.keepAliveTimeMilliseconds == 60000, "system_check_fixture_differs")
        elif path == RPC_PATHS[1]:
            token = result.gameAuthToken
            require(bool(token) and bool(result.userPublic.serverUserId)
                    and bool(result.userPublic.publicUserId), "fresh_local_login_failed")
        else:
            require(bool(result.currentMainAreaId), "fresh_local_home_failed")
        rows.append(row)
    return rows


def run_probe(app, audit, *, device_type=None, runtime=None, timeout=240):
    audit = Path(audit)
    require(not audit.exists() and not audit.is_symlink(), "fresh_audit_path_required")
    report = {"schema": 1, "status": "FAIL", "execution": "ios_simulator",
              "gameplay_tested": False, "device_tested": False, "playcover_tested": False,
              "simulator_created": False, "cleanup": {"shutdown": False, "delete": False}}
    created = None
    start = time.monotonic()
    stage = "platform"
    def remaining():
        value = timeout - (time.monotonic() - start)
        require(value > 0, "probe_deadline_exceeded")
        return min(60, value)
    try:
        require(sys.platform == "darwin", "macos_required_no_simulator_execution")
        require(type(timeout) in (int, float) and 5 <= timeout <= 600, "invalid_probe_timeout")
        app = Path(app).resolve(strict=True)
        require(app.is_dir() and app.suffix == ".app", "simulator_app_required")
        info = plistlib.loads(read_bounded(app / "Info.plist", MAX_JSON))
        require(info.get("CFBundleIdentifier") == BUNDLE_ID
                and info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "fake_unity_probe_app_required")
        report["bundle_id"] = BUNDLE_ID
        stage = "public_schema"
        schema, report["descriptor_sha256"] = load_schema(app)
        stage = "simulator_discovery"
        chosen_type, chosen_runtime = discover(device_type, runtime, remaining)
        report.update(device_type=chosen_type, runtime=chosen_runtime)
        stage = "simulator_create"
        raw = _simctl(["create", "IdolyEmbeddedProbe-" + uuid.uuid4().hex, chosen_type, chosen_runtime], remaining())
        value = raw.decode("ascii").strip()
        require(bool(re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", value)),
                "invalid_created_simulator_uuid")
        created = str(uuid.UUID(value)).upper()
        report.update(simulator_created=True, simulator_uuid=created)
        stage = "simulator_boot"
        boot_created_simulator(created, remaining)
        stage = "app_install"
        _simctl(["install", created, str(app)], remaining())
        stage = "fresh_container"
        raw = _simctl(["get_app_container", created, BUNDLE_ID, "data"], remaining())
        container = Path(raw.decode("utf-8").strip())
        require(container.is_absolute() and container.is_dir() and not container.is_symlink(),
                "invalid_fresh_app_container")
        for relative in ("Library/Application Support/IdolyPrideLocal/state.db",
                         "Library/Application Support/IdolyPrideLocal/media-state.db",
                         "Documents/embedded-probe.json", "Documents/embedded-probe-status.json"):
            path = container / relative
            require(not path.exists() and not path.is_symlink(), "preexisting_probe_state_rejected")
        report["fresh_local_state_before_launch"] = True
        stage = "app_launch"
        _simctl(["launch", created, BUNDLE_ID], remaining())
        stage = "startup_gate_report"
        report["native_probe"] = wait_report(container, remaining)
        stage = "asset_listener"
        with socket.create_connection(("127.0.0.1", 8080), timeout=min(5, remaining())):
            pass
        report["host_asset_loopback_connected"] = True
        stage = "encrypted_rpc"
        report["rpcs"] = probe_rpcs(schema, timeout=min(15, remaining()))
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="FAIL", failed_stage=stage,
                      error=(str(error) if isinstance(error, ProbeError) else type(error).__name__))
    finally:
        if created is not None:
            for action in ("shutdown", "delete"):
                try:
                    _simctl([action, created], 30)
                    report["cleanup"][action] = True
                except BaseException as error:
                    report["cleanup"][action + "_error"] = type(error).__name__
            if not all(report["cleanup"][key] for key in ("shutdown", "delete")):
                report.update(status="FAIL", cleanup_complete=False)
        report["seconds"] = round(time.monotonic() - start, 3)
        write_audit(audit, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--device-type")
    parser.add_argument("--runtime")
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args(argv)
    try:
        result = run_probe(args.app, args.audit, device_type=args.device_type,
                           runtime=args.runtime, timeout=args.timeout)
    except (ProbeError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error) if isinstance(error, ProbeError)
                          else type(error).__name__}))
        return 1
    print(json.dumps({"status": result["status"], "audit": str(args.audit)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
