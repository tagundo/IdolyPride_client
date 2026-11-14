"""Portable controller/protocol tests, explicitly not simulator execution proof."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
from unittest import mock
from zipfile import ZipFile

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import codec
from idoly_local.h2_server import create_server
from idoly_local.rpc import RpcCode


SOURCE = Path(__file__).resolve().parents[1] / "ios-unified/probe/smoke_probe.py"
spec = importlib.util.spec_from_file_location("ios_unified_smoke_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

CREATED = "00000000-0000-4000-8000-000000000123"
DEVICE = "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-18-5"


def native_report():
    return {"schema": 1, "original_called": 1, "main_thread": True,
            "application_argument_matches": True, "command_completion_main_thread": True,
            "crypto_completion_main_thread": True,
            "native_crypto": {"ok": True, "nist_encrypt": True, "nist_decrypt": True,
                              "invalid_iv_rejected": True, "worker_main_thread": False},
            "server_status": {"schema": 1, "hook_installed": True, "phase": 4,
                              "captured": 1, "forwarded": 1, "attempts": 1,
                              "python_initialized": True, "error": None},
            "ports": {"grpc": 50051, "assets": 8080,
                      "grpc_connect": True, "assets_connect": True},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "last_error": None, "runtime": {"running": True, "grpc_address": "127.0.0.1:50051",
                                                "asset_url": "http://127.0.0.1:8080"}}}}


def public_descriptor():
    file = descriptor_pb2.FileDescriptorProto(name="ios-probe-test.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    check = file.message_type.add(name="SystemCheckResponse")
    check.field.add(name="keepAliveTimeMilliseconds", number=3, type=5)
    public = file.message_type.add(name="UserPublic")
    public.field.add(name="serverUserId", number=1, type=9)
    public.field.add(name="publicUserId", number=2, type=9)
    login = file.message_type.add(name="LoginResponse")
    login.field.add(name="gameAuthToken", number=1, type=9)
    login.field.add(name="userPublic", number=2, type=11, type_name=".api.UserPublic")
    home = file.message_type.add(name="HomeResponse")
    home.field.add(name="currentMainAreaId", number=1, type=9)
    for service, method, output in (("System", "Check", "SystemCheckResponse"),
                                    ("Auth", "Login", "LoginResponse"),
                                    ("Home", "Enter", "HomeResponse")):
        file.service.add(name=service).method.add(name=method, input_type=".api.Empty", output_type=".api." + output)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    return descriptors.SerializeToString()


@pytest.fixture
def app(tmp_path):
    app = tmp_path / "EmbeddedProbe.app"
    (app / "LocalServer").mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": probe.BUNDLE_ID,
                                                   "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}))
    with ZipFile(app / "LocalServer/ServerData.zip", "w") as archive:
        # Match the distributed ServerData archive, independently of the
        # probe's lookup constant (installed core paths omit the data/ root).
        archive.writestr("data/protocol/idolypride-6.1.1.pb", public_descriptor())
    return app


class FakeSimctl:
    """No subprocess or simulator access: only command ownership is modeled."""
    def __init__(self, container, *, failed_action=None, startup_failure=False):
        self.container = container
        self.container.mkdir()
        self.calls = []
        self.failed_action = failed_action
        self.startup_failure = startup_failure

    def __call__(self, arguments, timeout):
        self.calls.append(tuple(arguments))
        assert 0 < timeout <= 60
        action = arguments[0]
        if action == self.failed_action:
            raise probe.ProbeError("simctl_failed")
        if action == "list":
            assert arguments[1] in ("devicetypes", "runtimes")
            if arguments[1] == "devicetypes":
                return json.dumps({"devicetypes": [{"identifier": DEVICE}]}).encode()
            return json.dumps({"runtimes": [{"identifier": RUNTIME, "version": "18.5", "isAvailable": True}]}).encode()
        if action == "create":
            assert arguments[1].startswith("IdolyEmbeddedProbe-")
            return (CREATED + "\n").encode()
        assert arguments[1] == CREATED, "An existing simulator must never be targeted"
        if action == "get_app_container":
            assert arguments[2:] == [probe.BUNDLE_ID, "data"]
            return (str(self.container) + "\n").encode()
        if action == "launch":
            documents = self.container / "Documents"
            documents.mkdir(exist_ok=True)
            if self.startup_failure:
                value = {"server_status": {"phase": 3, "error": "native-startup-fixture"}}
                (documents / "embedded-probe-status.json").write_text(json.dumps(value))
            else:
                (documents / "embedded-probe.json").write_text(json.dumps(native_report()))
        return b""


def test_linux_refuses_before_any_simulator_action_and_audits(app, tmp_path):
    audit = tmp_path / "nonmac.json"
    with mock.patch.object(probe.sys, "platform", "linux"), mock.patch.object(probe, "_simctl") as simctl:
        result = probe.run_probe(app, audit)
    simctl.assert_not_called()
    assert result["status"] == "FAIL"
    assert result["error"] == "macos_required_no_simulator_execution"
    assert json.loads(audit.read_text()) == result
    assert result["gameplay_tested"] is False


def test_existing_audit_is_preserved_without_touching_simulators(app, tmp_path):
    audit = tmp_path / "existing.json"
    audit.write_bytes(b"retain-existing-audit")
    with mock.patch.object(probe, "_simctl") as simctl, \
            pytest.raises(probe.ProbeError, match="fresh_audit_path_required"):
        probe.run_probe(app, audit)
    simctl.assert_not_called()
    assert audit.read_bytes() == b"retain-existing-audit"


def test_discovery_uses_available_runtime_and_compatible_device_types_only():
    older = "com.apple.CoreSimulator.SimDeviceType.iPhone-15-Pro"
    def command(arguments, _timeout):
        if arguments[1] == "devicetypes":
            return json.dumps({"devicetypes": [
                {"identifier": DEVICE, "minRuntimeVersion": 18 << 16},
                {"identifier": older, "minRuntimeVersion": 17 << 16}]}).encode()
        assert arguments == ["list", "runtimes", "--json"]
        return json.dumps({"runtimes": [
            {"identifier": RUNTIME, "version": "18.5", "isAvailable": False},
            {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-17-5", "version": "17.5", "isAvailable": True}]}).encode()
    with mock.patch.object(probe, "_simctl", command):
        selected = probe.discover(None, None, lambda: 5)
    assert selected == (older, "com.apple.CoreSimulator.SimRuntime.iOS-17-5")


def test_modern_xcode_type_catalog_over_report_bound_still_discovers_device():
    catalog = json.dumps({"devicetypes": [{"identifier": DEVICE, "model_metadata": "x" * 70000}]}).encode()
    assert probe.MAX_JSON < len(catalog) < probe.MAX_COMMAND_OUTPUT
    runtimes = json.dumps({"runtimes": [{"identifier": RUNTIME, "version": "18.5", "isAvailable": True}]}).encode()
    with mock.patch.object(probe, "_simctl", side_effect=[catalog, runtimes]):
        assert probe.discover(None, None, lambda: 5) == (DEVICE, RUNTIME)
    # Native reports retain the smaller, independent bound.
    with pytest.raises(probe.ProbeError, match="json_size_bound"):
        probe.parse_json(catalog)


def test_fresh_simulator_is_only_mutation_target_and_cleanup_runs(app, tmp_path):
    controller = FakeSimctl(tmp_path / "fresh-container")
    audit = tmp_path / "simulated-controller-test.json"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch.object(probe.socket, "create_connection") as socket_call, \
            mock.patch.object(probe, "probe_rpcs", return_value=[{"path": path} for path in probe.RPC_PATHS]):
        result = probe.run_probe(app, audit)
    assert result["status"] == "PASS"
    assert result["fresh_local_state_before_launch"] is True
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]
    assert [call[0] for call in controller.calls] == ["list", "list", "create", "boot", "bootstatus", "install",
                                                    "get_app_container", "launch", "shutdown", "delete"]
    socket_call.assert_called_once()
    assert socket_call.call_args.args[0] == ("127.0.0.1", 8080)
    assert audit.stat().st_size < probe.MAX_JSON
    assert audit.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failed_action", ("boot", "install", "launch"))
def test_stage_failures_clean_up_only_created_uuid(app, tmp_path, failed_action):
    controller = FakeSimctl(tmp_path / "container", failed_action=failed_action)
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL"
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]
    assert result["cleanup"] == {"shutdown": True, "delete": True}


def test_startup_failure_is_immediate_and_still_deletes_simulator(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", startup_failure=True)
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "native_startup_failed"
    assert result["native_startup_error"] == "native-startup-fixture"
    assert result["failed_stage"] == "startup_gate_report"
    assert result["cleanup"]["delete"] is True
    rpc.assert_not_called()


def test_shutdown_failure_does_not_skip_delete_or_claim_success(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", failed_action="shutdown")
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch.object(probe.socket, "create_connection"), \
            mock.patch.object(probe, "probe_rpcs", return_value=[]):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL" and result["cleanup_complete"] is False
    assert controller.calls[-1] == ("delete", CREATED)
    assert result["cleanup"]["delete"] is True


def test_existing_database_in_new_container_is_rejected_before_launch(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    state = controller.container / "Library/Application Support/IdolyPrideLocal/media-state.db"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"test-only-preexisting-state")
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "preexisting_probe_state_rejected"
    assert "launch" not in [call[0] for call in controller.calls]
    assert state.read_bytes() == b"test-only-preexisting-state"


@pytest.mark.parametrize("field,value", (("original_called", True), ("original_called", 2),
                                          ("main_thread", False), ("application_argument_matches", False),
                                          ("command_completion_main_thread", False)))
def test_gate_counters_and_main_thread_are_strict(field, value):
    report = native_report()
    report[field] = value
    with pytest.raises(probe.ProbeError, match="unity_original_gate_failed"):
        probe.validate_report(report)


def test_port_crypto_and_native_readiness_are_not_inferred():
    for category, key, bad in (("ports", "grpc", 50052), ("ports", "assets_connect", False),
                               ("commoncrypto", "nist_aes128_cbc", False),
                               ("server_status", "phase", 2), ("server_status", "captured", True)):
        report = native_report()
        report[category][key] = bad
        with pytest.raises(probe.ProbeError):
            probe.validate_report(report)
    report = native_report()
    report["unexpected_private_text"] = "not copied to audit"
    assert "unexpected_private_text" not in probe.validate_report(report)


def test_control_bridge_must_report_real_python_host_readiness_and_fixed_listeners():
    for field, value in (("state", "starting"), ("running", False), ("last_error", "test failure")):
        report = native_report()
        report["host_status"]["result"][field] = value
        with pytest.raises(probe.ProbeError, match="python_host_not_ready"):
            probe.validate_report(report)
    report = native_report()
    report["host_status"]["result"]["runtime"]["grpc_address"] = "127.0.0.1:50052"
    with pytest.raises(probe.ProbeError, match="python_host_listeners_differ"):
        probe.validate_report(report)
    report = native_report()
    report["host_status"]["ok"] = False
    with pytest.raises(probe.ProbeError, match="native_status_command_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field", ("ok", "nist_encrypt", "nist_decrypt", "invalid_iv_rejected", "worker_main_thread"))
def test_actual_python_commoncrypto_bridge_flags_are_all_required(field):
    report = native_report()
    report["native_crypto"][field] = field == "worker_main_thread"
    with pytest.raises(probe.ProbeError, match="python_commoncrypto_bridge_failed"):
        probe.validate_report(report)
    report = native_report()
    report["crypto_completion_main_thread"] = False
    with pytest.raises(probe.ProbeError, match="python_commoncrypto_bridge_failed"):
        probe.validate_report(report)


def test_duplicate_json_and_symlink_report_fail_closed(tmp_path):
    with pytest.raises(probe.ProbeError, match="duplicate_json_key"):
        probe.parse_json(b'{"schema":1,"schema":1}')
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(probe.ProbeError, match="invalid_bounded_file"):
        probe.read_bounded(link, probe.MAX_JSON)


def test_polling_has_a_deadline_without_native_report(tmp_path):
    calls = []
    def remaining():
        calls.append(1)
        if len(calls) == 4:
            raise probe.ProbeError("probe_deadline_exceeded")
        return 1
    with mock.patch.object(probe.time, "sleep"), pytest.raises(probe.ProbeError, match="probe_deadline_exceeded"):
        probe.wait_report(tmp_path, remaining)


class FixtureApplication:
    def __init__(self, schema, *, empty_token=False):
        self.schema, self.empty_token = schema, empty_token
        self.calls = []

    def handle(self, path, encrypted, context):
        assert encrypted and encrypted != probe.PUBLIC_PROBE_FIELD
        plain = codec.decode(encrypted)
        assert plain == probe.PUBLIC_PROBE_FIELD
        self.schema.request_type(path).FromString(plain)
        self.calls.append(path)
        result = self.schema.response_type(path)()
        if path == probe.RPC_PATHS[0]:
            result.keepAliveTimeMilliseconds = 60000
        elif path == probe.RPC_PATHS[1]:
            result.gameAuthToken = "" if self.empty_token else "portable-test-local-token"
            result.userPublic.serverUserId = "fresh-server-id"
            result.userPublic.publicUserId = "fresh-public-id"
        else:
            if dict(context.invocation_metadata()).get("x-auth-token") != "portable-test-local-token":
                context.abort(RpcCode.UNAUTHENTICATED, "fixture token required")
            result.currentMainAreaId = "fixture-main-area"
        return result.SerializeToString()


def test_real_portable_h2_and_aes_rpc_flow_uses_login_token_without_auditing_it(app):
    schema, fingerprint = probe.load_schema(app)
    assert len(fingerprint) == 64
    application = FixtureApplication(schema)
    server = create_server(application, port=0).start()
    try:
        rows = probe.probe_rpcs(schema, port=server.port, timeout=3)
    finally:
        server.stop()
    assert application.calls == list(probe.RPC_PATHS)
    assert all(row["request_encrypted"] and row["response_encrypted"] and row["grpc_status"] == 0 for row in rows)
    assert "portable-test-local-token" not in json.dumps(rows)


def test_login_without_fresh_identity_token_never_reaches_home(app):
    schema, _ = probe.load_schema(app)
    application = FixtureApplication(schema, empty_token=True)
    server = create_server(application, port=0).start()
    try:
        with pytest.raises(probe.ProbeError, match="fresh_local_login_failed"):
            probe.probe_rpcs(schema, port=server.port, timeout=3)
    finally:
        server.stop()
    assert application.calls == list(probe.RPC_PATHS[:2])


def test_cold_boot_retries_bounded_observer_for_only_the_created_uuid(monkeypatch):
    calls = []

    def simctl(arguments, timeout):
        calls.append((arguments, timeout))
        if arguments[0] == "bootstatus" and len(calls) == 2:
            raise probe.ProbeError("simctl_timeout")
        return b"booted"

    monkeypatch.setattr(probe, "_simctl", simctl)
    probe.boot_created_simulator(CREATED, lambda: 60)
    assert [row[0] for row in calls] == [
        ["boot", CREATED], ["bootstatus", CREATED, "-b"], ["bootstatus", CREATED, "-b"]]
    assert all(timeout == 60 for _, timeout in calls)


def test_cold_boot_keeps_overall_deadline_and_does_not_hide_other_failures(monkeypatch):
    def timed_out(arguments, timeout):
        if arguments[0] == "bootstatus":
            raise probe.ProbeError("simctl_timeout")
        return b""

    remaining = mock.Mock(side_effect=[60, 60, probe.ProbeError("probe_deadline_exceeded")])
    monkeypatch.setattr(probe, "_simctl", timed_out)
    with pytest.raises(probe.ProbeError, match="probe_deadline_exceeded"):
        probe.boot_created_simulator(CREATED, remaining)
    monkeypatch.setattr(probe, "_simctl", mock.Mock(side_effect=probe.ProbeError("simctl_failed")))
    with pytest.raises(probe.ProbeError, match="simctl_failed"):
        probe.boot_created_simulator(CREATED, lambda: 60)
