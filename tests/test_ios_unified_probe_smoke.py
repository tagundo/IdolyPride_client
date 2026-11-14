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
    report = {"schema": 1, "original_called": 1, "main_thread": True,
            "application_argument_matches": True, "command_completion_main_thread": True,
            "crypto_completion_main_thread": True,
            "native_crypto": {"ok": True, "nist_encrypt": True, "nist_decrypt": True,
                              "invalid_iv_rejected": True, "worker_main_thread": False},
            "server_status": {"schema": 1, "hook_installed": True, "phase": 4,
                              "captured": 1, "forwarded": 1, "attempts": 1,
                              "python_initialized": True, "error": None,
                              "keyboard_guard_installed": True, "keyboard_ready": True,
                              "launch_requested": True, "launch_prepared": True, "launcher_visible": False,
                              "client_data": {"selected": True, "language": "ko", "bundle_identifier": "local.idoly.client-data"}},
            "launcher": {"premature_phase": 1, "premature_original_called": 0,
                "premature_launch_requested": False, "ready_phase": 2, "ready_original_called": 0,
                "ready_launch_requested": False, "ready_launch_prepared": False,
                "ready_observations": 5, "ready_wait_seconds": 1.003,
                "ready_launcher_visible": True, "ready_button_found": True,
                "ready_button_enabled": True, "ready_button_title": "게임 시작",
                "button_action_dispatched": True, "button_dispatch_count": 1,
                "duplicate_launch_called": True, "forwarded_after_button": True},
            "corner_gesture": {"game_window_key": True, "matching_count": 1,
                "recognizer_name": "idoly.server-menu-corner", "one_finger_count": 1, "three_finger_count": 0,
                "minimum_press_seconds": 2.0, "allowable_movement_points": 12.0, "delegate_present": True,
                "delays_touches_began": False, "delays_touches_ended": False, "cancels_touches_in_view": True},
            "ports": {"grpc": 50051, "assets": 8080,
                      "grpc_connect": True, "assets_connect": True},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "last_error": None, "runtime": {"running": True, "grpc_address": "127.0.0.1:50051",
                                                "asset_url": "http://127.0.0.1:8080"}}}}
    report["keyboard"] = {
        "before_capture":{"guard_installed":True,"ready":False,"phase":2,"returned_nil":True,
                          "returned_initialized_field":False,"original_calls":0,"field_creation_count":0},
        "before_launch":{"guard_installed":True,"ready":False,"phase":2,"returned_nil":True,
                         "returned_initialized_field":False,"original_calls":0,"field_creation_count":0},
        "during_init":{"guard_installed":True,"ready":False,"phase":4,"returned_nil":True,
                       "returned_initialized_field":False,"original_calls":0,"field_creation_count":0},
        "after_init":{"guard_installed":True,"ready":True,"phase":4,"returned_nil":False,
                      "returned_initialized_field":True,"original_calls":1,"field_creation_count":1},
    }
    report["early_status"] = {"id":2718,"ok":True,"state":"starting","running":False,
                              "phase":1,"captured":0,"completion_main_thread":True}
    report["launcher"].update(premature_captured=0,server_ready_before_capture=True,
        uncaptured_original_called=0,uncaptured_attempts=1,capture_after_ready_once=True)
    report["menu_lifetime"] = {"opened_via_owned_menu_target":True,"full_screen":True,
        "frame_width_matches":True,"frame_width":393.0,"window_width":393.0,"return_button_found":True,
        "server_control_found":True,"server_control_disabled_while_running":True,
        "return_action_dispatched":True,"dismissed":True,"menu_view_detached_after_close":True,"game_window_key_after_close":True,
        "dismiss_observation":{"presented_controller_remaining":False,"settings_controller_still_presented":False,
            "settings_view_attached":False,"settings_is_being_dismissed":False,"game_window_key":True,
            "application_state":0,"observations":4,"wait_seconds":0.303,"timed_out":False},
        "status_completion_main_thread":True,"grpc_connected_after_close":True,"assets_connected_after_close":True,
        "web":{"web_found":True,"evaluation_succeeded":True,"ready":True,"forms_present":True,
               "scale_2_present":True,"buffer_4096_present":True,"no_horizontal_overflow":True,
               "timed_out":False,"viewport_width":393,"content_width":393,"select_count":14},
        "host_status_after_close":{"id":2,"ok":True,"result":{"state":"ready","running":True,
               "last_error":None,"runtime":{"running":True,"grpc_address":"127.0.0.1:50051",
                                              "asset_url":"http://127.0.0.1:8080"}}}}
    return report


@pytest.mark.parametrize("phase,field,replacement", (
    ("before_capture", "ready", True), ("before_capture", "original_calls", 1),
    ("before_capture", "field_creation_count", 1),
    ("before_launch", "returned_nil", False), ("before_launch", "original_calls", 1),
    ("before_launch", "field_creation_count", 1),
    ("during_init", "ready", True), ("during_init", "returned_nil", False),
    ("during_init", "returned_initialized_field", True), ("during_init", "original_calls", 1),
    ("during_init", "field_creation_count", 1),
    ("after_init", "ready", False), ("after_init", "returned_nil", True),
    ("after_init", "returned_initialized_field", False), ("after_init", "original_calls", 0),
    ("after_init", "original_calls", 2), ("after_init", "field_creation_count", 0),
    ("after_init", "field_creation_count", 2),
    ("before_capture", "phase", True), ("before_launch", "original_calls", False),
    ("during_init", "field_creation_count", False), ("after_init", "original_calls", True),
    ("after_init", "field_creation_count", True), ("before_capture", "guard_installed", 1),
    ("during_init", "ready", 0), ("after_init", "ready", 1),
))
def test_keyboard_guard_only_calls_original_after_unity_initialization(phase, field, replacement):
    observed = native_report()
    observed["keyboard"][phase][field] = replacement
    with pytest.raises(probe.ProbeError, match="^keyboard_guard_" + phase + "_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("key,value", (("keyboard_guard_installed", False), ("keyboard_guard_installed", 1),
                                      ("keyboard_ready", False), ("keyboard_ready", 1)))
def test_final_native_status_requires_keyboard_guard_and_readiness(key, value):
    observed = native_report()
    observed["server_status"][key] = value
    with pytest.raises(probe.ProbeError, match="^keyboard_guard_after_init_failed$"):
        probe.validate_report(observed)


def test_keyboard_phase_evidence_is_required_and_validated_output_drops_unknown_data():
    observed = native_report()
    del observed["keyboard"]["during_init"]
    with pytest.raises(probe.ProbeError, match="^keyboard_guard_during_init_failed$"):
        probe.validate_report(observed)
    observed = native_report()
    observed["keyboard"]["private_phase"] = {"credentials":"must-not-export"}
    observed["keyboard"]["after_init"]["private_field"] = "must-not-export"
    result = probe.validate_report(observed)
    assert result["keyboard"]["during_init"]["ready"] is False
    assert result["keyboard"]["after_init"]["original_calls"] == 1
    assert result["server_status"]["keyboard_ready"] is True
    assert "must-not-export" not in json.dumps(result)


def test_keyboard_diagnostic_projection_keeps_only_strict_bounded_public_scalars():
    observed = probe.keyboard_observation({
        "before_capture":{"guard_installed":1,"ready":False,"phase":True,"returned_nil":"private",
                          "returned_initialized_field":False,"original_calls":17,"field_creation_count":-1,
                          "private_field":"never-copy"},
        "before_launch":["private"],
        "during_init":{"phase":4,"original_calls":16,"field_creation_count":16,"ready":True},
        "after_init":{"phase":5,"original_calls":True,"field_creation_count":{},"guard_installed":False},
        "private_phase":{"token":"never-copy"}})
    assert observed == {
        "before_capture":{"ready":False,"returned_initialized_field":False},
        "during_init":{"phase":4,"original_calls":16,"field_creation_count":16,"ready":True},
        "after_init":{"guard_installed":False}}
    assert "private" not in json.dumps(observed) and "never-copy" not in json.dumps(observed)


@pytest.mark.parametrize("source,filename,stage", (
    ("checkpoint","embedded-probe-checkpoint.json","keyboard_before_capture_checked"),
    ("status","embedded-probe-status.json","keyboard_before_launch_checked"),
    ("report","embedded-probe.json","keyboard_after_init_checked"),
))
def test_keyboard_failure_checkpoint_is_projected_from_fixed_public_files(tmp_path, source, filename, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    observed = native_report() if source == "report" else {
        "schema":1,"stage":stage,"keyboard_guard_installed":True,"keyboard_ready":False,
        "server_status":{"phase":2,"keyboard_guard_installed":True,"keyboard_ready":False},
        "keyboard":native_report()["keyboard"]}
    observed["keyboard"]["before_capture"]["field_creation_count"] = 1
    observed["keyboard"]["before_capture"]["arbitrary_payload"] = "never-copy"
    observed["keyboard"]["private_phase"] = {"token":"never-copy"}
    (documents / filename).write_text(json.dumps(observed))
    result = probe.failure_checkpoint(tmp_path)
    assert result["keyboard"]["before_capture"]["field_creation_count"] == 1
    if source == "checkpoint":
        assert result["stage"] == stage and result["keyboard_guard_installed"] is True
        assert result["keyboard_ready"] is False
    if source == "status":
        assert result["status_keyboard_guard_installed"] is True and result["status_keyboard_ready"] is False
    if source == "report":
        assert result["report_valid"] is False
    assert "never-copy" not in json.dumps(result)


def test_final_keyboard_failure_preserves_only_bounded_observation_in_audit(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    observed = native_report()
    observed["keyboard"]["during_init"]["field_creation_count"] = 1
    observed["keyboard"]["during_init"]["private_field"] = "never-copy"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch(__name__ + ".native_report", return_value=observed), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "keyboard_guard_during_init_failed"
    assert result["native_keyboard_observed"]["during_init"]["field_creation_count"] == 1
    assert result["native_checkpoint"]["keyboard"]["during_init"]["field_creation_count"] == 1
    assert "never-copy" not in json.dumps(result)
    rpc.assert_not_called()


def test_waiting_keyboard_failure_keeps_known_scalars_and_cleans_owned_simulator(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    def simctl(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            documents = controller.container / "Documents"
            (documents / "embedded-probe.json").unlink()
            observed = {"server_status":{"phase":2,"error":None},
                        "probe_error":"keyboard_created_before_initialize",
                        "keyboard":native_report()["keyboard"]}
            observed["keyboard"]["before_capture"]["field_creation_count"] = 1
            observed["keyboard"]["private_phase"] = {"token":"never-copy"}
            (documents / "embedded-probe-status.json").write_text(json.dumps(observed))
        return result
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", simctl), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "keyboard_created_before_initialize"
    assert result["native_keyboard_observed"]["before_capture"]["field_creation_count"] == 1
    assert result["cleanup"] == {"shutdown":True,"delete":True}
    assert "never-copy" not in json.dumps(result)
    rpc.assert_not_called()


def test_waiting_deadline_retains_only_previously_valid_keyboard_scalars(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    observed = {"server_status":{"phase":2,"error":None}, "keyboard":native_report()["keyboard"]}
    observed["keyboard"]["after_init"]["private_text"] = "never-copy"
    (documents / "embedded-probe-status.json").write_text(json.dumps(observed))
    remaining = mock.Mock(side_effect=[1, 1, probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time, "sleep"), pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path, remaining)
    assert str(caught.value) == "probe_deadline_exceeded"
    assert caught.value.native_keyboard["during_init"]["ready"] is False
    assert "never-copy" not in json.dumps(caught.value.native_keyboard)


@pytest.mark.parametrize("path,replacement,code", [
    (("early_status", "id"), 2719, "early_status_correlation_failed"),
    (("early_status", "captured"), 1, "early_status_correlation_failed"),
    (("launcher", "server_ready_before_capture"), False, "server_not_ready_before_capture"),
    (("launcher", "uncaptured_attempts"), 2, "server_not_ready_before_capture"),
    (("menu_lifetime", "dismissed"), False, "settings_menu_lifetime_failed"),
    (("menu_lifetime", "grpc_connected_after_close"), False, "settings_menu_lifetime_failed"),
    (("menu_lifetime", "host_status_after_close", "result", "running"), False, "server_stopped_after_menu_close"),
    (("menu_lifetime", "frame_width"), 250, "settings_menu_width_failed"),
    (("menu_lifetime", "dismiss_observation", "settings_view_attached"), True, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "dismiss_observation", "game_window_key"), False, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "dismiss_observation", "timed_out"), True, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "web", "scale_2_present"), False, "settings_web_readiness_or_layout_failed"),
    (("menu_lifetime", "web", "buffer_4096_present"), False, "settings_web_readiness_or_layout_failed"),
    (("menu_lifetime", "web", "content_width"), 500, "settings_web_metrics_failed"),
])
def test_autostart_before_capture_and_menu_survival_are_required(path, replacement, code):
    observed = native_report()
    target = observed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(probe.ProbeError, match=code):
        probe.validate_report(observed)


def test_new_flow_audit_discards_unrecognized_native_values():
    observed = native_report()
    observed["server_status"]["client_data"]["unrecognized_payload"] = "must-not-export"
    observed["menu_lifetime"]["unrecognized_payload"] = "must-not-export"
    result = probe.validate_report(observed)
    assert result["launcher"]["server_ready_before_capture"] is True
    assert result["early_status"]["id"] == 2718
    assert result["menu_lifetime"]["host_status_after_close"]["result"]["running"] is True
    assert "must-not-export" not in json.dumps(result)


@pytest.mark.parametrize("stage", ("settings_menu_requested", "settings_return_requested", "settings_return_observed",
                                  "settings_return_timeout", "settings_menu_dismissed"))
def test_owned_menu_checkpoints_are_projected_before_simulator_cleanup(tmp_path, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    value = {"schema":1,"stage":stage,"original_called":1,"phase":4,
             "menu_close":{"presented_controller_remaining":True,"game_window_key":False,
                           "wait_seconds":0.6,"observations":7,"unknown":"must-not-export"}}
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps(value))
    observed = probe.failure_checkpoint(tmp_path)
    assert observed["stage"] == stage
    assert "checkpoint_read_error" not in observed
    assert observed["menu_close"] == {"presented_controller_remaining":True,"game_window_key":False,
                                      "wait_seconds":0.6,"observations":7}


def test_menu_dismissal_diagnostics_drop_nonboolean_or_unbounded_values():
    assert probe.menu_close_observation({"game_window_key":1,"settings_view_attached":"private",
        "presented_controller_remaining":True,"application_state":5,"wait_seconds":float("nan"),
        "observations":100000,"unknown":"private"}) == {"presented_controller_remaining":True}


def test_menu_timeout_distinguishes_transition_and_key_window_without_weakening_failure(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    detail = {"presented_controller_remaining":False,"settings_controller_still_presented":False,
              "settings_view_attached":False,"settings_is_being_dismissed":False,"game_window_key":False,
              "application_state":0,"observations":61,"wait_seconds":6.05,"timed_out":True,
              "unknown":"must-not-export"}
    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            documents = controller.container / "Documents"
            (documents / "embedded-probe.json").unlink()
            (documents / "embedded-probe-status.json").write_text(json.dumps({"schema":1,"original_called":1,
                "server_status":{"phase":4,"error":None},"probe_error":"settings_menu_not_dismissed","menu_close":detail}))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"), mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe,"probe_rpcs") as rpc:
        observed = probe.run_probe(app,tmp_path / "dismissal-timeout.json")
    assert observed["status"] == "FAIL" and observed["error"] == "settings_menu_not_dismissed"
    assert observed["native_menu_close_observed"]["presented_controller_remaining"] is False
    assert observed["native_menu_close_observed"]["game_window_key"] is False
    assert observed["cleanup"] == {"shutdown":True,"delete":True}
    assert "must-not-export" not in json.dumps(observed)
    rpc.assert_not_called()


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
        self.timeouts = []
        self.failed_action = failed_action
        self.startup_failure = startup_failure

    def __call__(self, arguments, timeout):
        self.calls.append(tuple(arguments))
        self.timeouts.append(timeout)
        assert 0 < timeout <= (180 if arguments[0] in ("install", "launch") else 60)
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
    assert result["native_probe"]["launcher"]["ready_original_called"] == 0
    assert result["native_probe"]["launcher"]["button_dispatch_count"] == 1
    assert result["native_probe"]["server_status"]["launcher_visible"] is False
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]
    assert [call[0] for call in controller.calls] == ["list", "list", "create", "boot", "bootstatus", "install",
                                                    "get_app_container", "launch", "shutdown", "delete"]
    socket_call.assert_called_once()
    assert socket_call.call_args.args[0] == ("127.0.0.1", 8080)
    assert 60 < controller.timeouts[7] <= 180  # Cold UIKit/WK startup has its own bounded budget.
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


def test_launch_budget_remains_clamped_to_original_overall_deadline(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    clock = {"now": 0.0}

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "install":
            clock["now"] = 50.0
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock["now"]), \
            mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe.socket, "create_connection"), \
            mock.patch.object(probe, "probe_rpcs", return_value=[]):
        result = probe.run_probe(app, tmp_path / "audit.json", timeout=90)
    assert result["status"] == "PASS"
    assert controller.timeouts[5] == 90.0
    assert controller.timeouts[7] == 40.0


@pytest.mark.parametrize("action", ("install", "launch"))
@pytest.mark.parametrize("timed_out", (False, True))
def test_probe_install_launch_failure_keeps_fixed_code_and_bounded_cli_context(action, timed_out):
    arguments = [action, CREATED, "do-not-copy-command-arguments"]
    # Include invalid UTF-8 and escaping-heavy text to bound serialized JSON,
    # rather than assuming a character bound is also an audit-size bound.
    stdout = b"public-probe-output\n" + b"\xff\x00" * 10000
    stderr = b"public-probe-error\n" + "\u2000".encode() * 10000
    if timed_out:
        effect = probe.subprocess.TimeoutExpired("not copied", 180, output=stdout, stderr=stderr)
        command = mock.Mock(side_effect=effect)
    else:
        command = mock.Mock(return_value=probe.subprocess.CompletedProcess([], 1, stdout, stderr))
    with mock.patch.object(probe.subprocess, "run", command), pytest.raises(probe.ProbeError) as raised:
        probe._simctl(arguments, 180)
    assert str(raised.value) == ("simctl_timeout" if timed_out else "simctl_failed")
    detail = raised.value.tool_detail
    assert detail["action"] == action
    assert detail["stdout"].startswith("public-probe-output\n")
    assert detail["stderr"].startswith("public-probe-error\n")
    assert detail["stdout_truncated"] is True and detail["stderr_truncated"] is True
    encoded = json.dumps(detail, ensure_ascii=True).encode()
    assert len(encoded) <= probe.MAX_TOOL_DETAIL
    assert b"do-not-copy-command-arguments" not in encoded


@pytest.mark.parametrize("action", ("list", "create", "boot", "get_app_container", "shutdown", "delete"))
def test_other_simulator_commands_do_not_contribute_host_cli_context(action):
    result = probe.subprocess.CompletedProcess([], 1, b"do not retain", b"private unrelated host text")
    with mock.patch.object(probe.subprocess, "run", return_value=result), \
            pytest.raises(probe.ProbeError, match="^simctl_failed$") as raised:
        probe._simctl([action, CREATED], 30)
    assert not hasattr(raised.value, "tool_detail")


def test_launch_ack_timeout_accepts_only_full_native_and_rpc_success_without_relaunch(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")

    def command(arguments, timeout):
        if arguments[0] == "launch":
            controller(arguments, timeout)
            raise probe._simctl_error("simctl_timeout", arguments, b"probe-start-output", b"probe-start-error")
        return controller(arguments, timeout)

    rows = [{"path": path} for path in probe.RPC_PATHS]
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe.socket, "create_connection") as listener, \
            mock.patch.object(probe, "probe_rpcs", return_value=rows) as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "PASS"
    assert result["launch_ack_timeout"] is True
    assert result["launch_ack_diagnostic"] == {"action": "launch", "stdout": "probe-start-output",
        "stderr": "probe-start-error", "stdout_truncated": False, "stderr_truncated": False}
    assert result["launch_ack_checkpoint"]["report_valid"] is True
    assert result["native_probe"]["launcher"]["button_dispatch_count"] == 1
    assert result["rpcs"] == rows
    listener.assert_called_once()
    rpc.assert_called_once()
    assert [call[0] for call in controller.calls].count("launch") == 1
    assert result["cleanup"] == {"shutdown": True, "delete": True}
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]


def test_launch_ack_timeout_without_report_still_expires_under_original_deadline(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    clock = {"now": 0.0}

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            (controller.container / "Documents/embedded-probe.json").unlink()
            clock["now"] = 90.0
            raise probe._simctl_error("simctl_timeout", arguments)
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock["now"]), \
            mock.patch.object(probe, "_simctl", command), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json", timeout=90)
    assert result["status"] == "FAIL"
    assert result["error"] == "probe_deadline_exceeded"
    assert result["failed_stage"] == "startup_gate_report"
    assert result["launch_ack_timeout"] is True
    assert result["native_checkpoint"]["report_available"] is False
    assert [call[0] for call in controller.calls].count("launch") == 1
    assert result["cleanup"] == {"shutdown": True, "delete": True}
    rpc.assert_not_called()


def test_launch_os_rejection_is_still_fatal_even_if_a_report_exists(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            raise probe._simctl_error("simctl_failed", arguments, stderr=b"public install rejection")
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL"
    assert result["error"] == "simctl_failed" and result["failed_stage"] == "app_launch"
    assert result["launch_ack_timeout"] is False
    assert result["native_checkpoint"]["report_valid"] is True
    assert result["simctl_failure"]["stderr"] == "public install rejection"
    rpc.assert_not_called()


def test_startup_failure_is_immediate_and_still_deletes_simulator(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", startup_failure=True)
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "native_startup_failed"
    assert result["native_startup_error"] == "native-startup-fixture"
    assert result["failed_stage"] == "startup_gate_report"
    assert result["native_checkpoint"]["status_phase"] == 3
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
    assert result["native_checkpoint"]["report_valid"] is True


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


def test_preexisting_checkpoint_is_rejected_before_launch_or_native_observation(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    checkpoint = controller.container / "Documents/embedded-probe-checkpoint.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text('{"schema":1,"stage":"report_written"}')
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "preexisting_probe_state_rejected"
    assert "launch" not in [call[0] for call in controller.calls]
    assert result["native_checkpoint"] == {"stage": "not_observed", "container_available": False}


def test_failure_checkpoint_projects_only_fixed_native_stages_and_scalar_gate_fields(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": "crypto_received", "phase": 4, "original_called": 1,
        "application_state": 0, "launch_requested": True, "launch_prepared": True,
        "launcher_visible": False, "private_text": "must not retain checkpoint payload"}))
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "original_called": 0, "server_status": {"phase": 2, "launch_requested": False,
        "error": "must not retain raw server error"}, "probe_error": "must not retain unknown text"}))
    raw_report = native_report()
    raw_report["unknown_private_text"] = "must not retain report payload"
    (documents / "embedded-probe.json").write_text(json.dumps(raw_report))
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "crypto_received" and result["phase"] == 4
    assert result["original_called"] == 1 and result["application_state"] == 0
    assert result["status_phase"] == 2 and result["status_original_called"] == 0
    assert result["report_phase"] == 4 and result["report_original_called"] == 1
    assert result["report_valid"] is True
    assert all(type(value) in (str, int, bool, float, type(None))
               for key, value in result.items() if key != "keyboard")
    assert result["keyboard"] == raw_report["keyboard"]
    assert "must not retain" not in json.dumps(result)


@pytest.mark.parametrize("stage", ("private arbitrary message", ["status_received"], None))
def test_failure_checkpoint_rejects_unknown_or_nonscalar_stages(tmp_path, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": stage, "phase": 4, "private": "discard"}))
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "not_observed"
    assert result["checkpoint_read_error"] == "invalid_checkpoint_stage"
    assert "phase" not in result
    assert "private" not in json.dumps(result)


def test_failure_checkpoint_drops_bad_scalar_types_and_keeps_read_errors_public(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": "status_received", "phase": True, "original_called": 9999,
        "application_state": 3, "launch_requested": 1, "launch_prepared": "private text"}))
    (documents / "embedded-probe-status.json").write_text("invalid private JSON text")
    outside = tmp_path / "unrelated-private-report.json"
    outside.write_text('{"private":"never follow"}')
    (documents / "embedded-probe.json").symlink_to(outside)
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "status_received"
    assert not {"phase", "original_called", "application_state", "launch_requested", "launch_prepared"} & result.keys()
    assert result["status_read_error"] == "invalid_json"
    assert result["report_read_error"] == "invalid_bounded_file"
    assert "private" not in json.dumps(result)


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


@pytest.mark.parametrize("field,value", (("launch_requested", False), ("launch_prepared", False),
                                          ("launcher_visible", True), ("launch_requested", 1),
                                          ("launch_prepared", 1), ("launcher_visible", 0)))
def test_explicit_handoff_requires_preparation_and_hidden_launcher(field, value):
    report = native_report()
    report["server_status"][field] = value
    with pytest.raises(probe.ProbeError, match="launcher_handoff_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("premature_phase", 2), ("premature_phase", True),
        ("premature_original_called", 1), ("premature_original_called", False),
        ("premature_launch_requested", True), ("premature_launch_requested", 0)))
def test_launch_before_ready_must_be_ignored(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="premature_launch_not_ignored"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("ready_phase", 4), ("ready_original_called", 1),
        ("ready_launch_requested", True), ("ready_launch_prepared", True),
        ("ready_observations", 1), ("ready_observations", True),
        ("ready_wait_seconds", 0.99), ("ready_wait_seconds", True),
        ("ready_wait_seconds", float("nan")), ("ready_wait_seconds", float("inf"))))
def test_ready_must_remain_idle_for_observation_before_explicit_click(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="unity_started_before_launch_button"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("ready_launcher_visible", False),
        ("ready_button_found", False), ("ready_button_enabled", False),
        ("ready_button_found", 1), ("ready_button_title", "Start")))
def test_ready_requires_real_visible_enabled_launch_button(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="ready_launch_control_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("button_action_dispatched", False),
        ("button_action_dispatched", 1), ("button_dispatch_count", 0),
        ("button_dispatch_count", 2), ("button_dispatch_count", True),
        ("duplicate_launch_called", False), ("forwarded_after_button", False)))
def test_forwarding_requires_exactly_one_real_ui_action_and_duplicate_launch_guard(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="explicit_launch_action_failed"):
        probe.validate_report(report)


def test_launcher_evidence_is_required_and_only_checked_fields_are_audited():
    report = native_report()
    del report["launcher"]
    with pytest.raises(probe.ProbeError, match="launcher_evidence_missing"):
        probe.validate_report(report)
    report = native_report()
    report["launcher"]["unexpected_private_text"] = "must not enter audit"
    checked = probe.validate_report(report)
    assert "unexpected_private_text" not in checked["launcher"]
    assert checked["launcher"]["ready_wait_seconds"] >= 1.0


@pytest.mark.parametrize("field,value", (("game_window_key", False), ("one_finger_count", 0),
        ("one_finger_count", 2), ("one_finger_count", True), ("three_finger_count", 1),
        ("three_finger_count", False), ("minimum_press_seconds", 0.6), ("minimum_press_seconds", True),
        ("matching_count", 0), ("matching_count", 2), ("matching_count", True),
        ("recognizer_name", "unrelated-system-hold"), ("recognizer_name", None),
        ("allowable_movement_points", 100), ("delegate_present", False), ("delegate_present", 1),
        ("delays_touches_began", True), ("delays_touches_ended", True), ("cancels_touches_in_view", False)))
def test_actual_game_window_has_one_configured_corner_hold_and_no_three_finger_hold(field, value):
    report = native_report()
    report["corner_gesture"][field] = value
    with pytest.raises(probe.ProbeError, match="corner_gesture_configuration_failed"):
        probe.validate_report(report)


def test_corner_gesture_evidence_is_required_and_drops_unchecked_details():
    report = native_report()
    del report["corner_gesture"]
    with pytest.raises(probe.ProbeError, match="corner_gesture_configuration_failed"):
        probe.validate_report(report)
    report = native_report()
    report["corner_gesture"]["unchecked"] = "not copied"
    assert "unchecked" not in probe.validate_report(report)["corner_gesture"]


def test_corner_failure_audit_preserves_numeric_boolean_mismatch_without_private_fields(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    broken = native_report()
    # C comparison expressions box as int, unlike an explicit Objective-C
    # BOOL. Keep this actual mismatch visible while still rejecting it.
    broken["corner_gesture"]["delegate_present"] = 1
    broken["corner_gesture"]["private_text"] = "must not retain"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch(__name__ + ".native_report", return_value=broken), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "corner_gesture_configuration_failed"
    assert type(result["native_corner_observed"]["delegate_present"]) is int
    assert result["native_corner_observed"]["delegate_present"] == 1
    assert result["native_checkpoint"]["corner_delegate_present"] == 1
    assert result["native_corner_observed"]["matching_count"] == 1
    assert "must not retain" not in json.dumps(result)
    rpc.assert_not_called()


def test_corner_diagnostics_keep_only_bounded_scalars_and_redact_unexpected_names():
    observed = probe.corner_observation({"recognizer_name": "private arbitrary gesture name",
        "matching_count": 2, "one_finger_count": 100000, "three_finger_count": [1],
        "minimum_press_seconds": float("nan"), "allowable_movement_points": 12.0,
        "game_window_key": "private", "delegate_present": 1, "unknown": "private"})
    assert observed == {"recognizer_name": "unexpected_name", "matching_count": 2,
        "allowable_movement_points": 12.0, "delegate_present": 1}


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


@pytest.mark.parametrize("number", (0, 1))
def test_native_crypto_numeric_flags_do_not_count_as_json_booleans(number):
    report = native_report()
    report["native_crypto"]["ok"] = number
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


def test_atomic_status_replacement_between_lstat_and_open_retries_then_accepts_final_report(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 1, "error": None}}))
    replacement = documents / "atomic-checkpoint.json"
    replacement.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    original_open = probe.os.open
    replacements = []

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting and not replacements:
            replacements.append(True)
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    def after_retry(delay):
        assert 0 < delay <= 0.25
        (documents / "embedded-probe.json").write_text(json.dumps(native_report()))

    with mock.patch.object(probe.os, "open", opening), \
            mock.patch.object(probe.time, "sleep", side_effect=after_retry) as sleep:
        result = probe.wait_report(tmp_path, lambda: 5)
    assert result["original_called"] == 1
    assert replacements == [True]
    sleep.assert_called_once()


def test_final_report_replacement_between_lstat_and_open_still_fails(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    final = documents / "embedded-probe.json"
    final.write_text(json.dumps(native_report()))
    replacement = documents / "replacement-final.json"
    replacement.write_text(json.dumps(native_report()))
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == final:
            replacement.replace(final)
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_opening$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


def test_status_in_place_mutation_between_lstat_and_open_is_not_retried(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            waiting.write_text(raw + " ")  # Same inode, changed size/mtime.
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_opening$") as raised:
        probe.wait_report(tmp_path, lambda: 5)
    assert not hasattr(raised.value, "regular_replacement")
    sleep.assert_not_called()


def test_status_open_inode_mutation_during_read_is_not_retried(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_fstat = probe.os.fstat
    observations = []

    def inspect(fd):
        observations.append(fd)
        if len(observations) == 2:
            waiting.write_text(raw + " ")
        return original_fstat(fd)

    with mock.patch.object(probe.os, "fstat", inspect), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_reading$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


@pytest.mark.parametrize("unsafe", ("oversize", "symlink", "empty"))
def test_status_replacement_must_still_be_regular_nonempty_bounded_and_nofollow(tmp_path, unsafe):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    replacement = documents / "replacement.json"
    if unsafe == "symlink":
        target = documents / "not-a-checkpoint.json"
        target.write_text("{}")
        replacement.symlink_to(target)
    else:
        replacement.write_bytes(b"x" * (probe.MAX_JSON + 1) if unsafe == "oversize" else b"")
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    expected = OSError if unsafe == "symlink" else probe.ProbeError
    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(expected):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


def test_replaced_status_invalid_json_is_fatal_on_next_bounded_read(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    replacement = documents / "replacement.json"
    replacement.write_text("invalid JSON")
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting and replacement.exists():
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^invalid_json$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_called_once()


def test_repeated_atomic_checkpoint_replacement_keeps_original_deadline(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            replacement = documents / "next-checkpoint.json"
            replacement.write_text(raw)
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    remaining = mock.Mock(side_effect=[5, 5, 5, probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^probe_deadline_exceeded$"):
        probe.wait_report(tmp_path, remaining)
    assert remaining.call_count == 4
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("failure", sorted(probe.LAUNCHER_FAILURE_CODES))
def test_missing_button_or_explicit_action_fails_immediately_instead_of_waiting(tmp_path, failure):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "server_status": {"phase": 2, "error": None}, "probe_error": failure}))
    with mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^" + failure + "$"):
        probe.wait_report(tmp_path, lambda: 1)
    sleep.assert_not_called()


@pytest.mark.parametrize("failure", ("arbitrary private text", 1, False, ["ready_launch_button_missing"]))
def test_waiting_launcher_failure_diagnostic_is_a_fixed_public_code(tmp_path, failure):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "server_status": {"phase": 2, "error": None}, "probe_error": failure}))
    with pytest.raises(probe.ProbeError, match="^invalid_launcher_failure_code$"):
        probe.wait_report(tmp_path, lambda: 1)


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


def test_game_data_failure_ends_wait_without_waiting_for_server_timeout(tmp_path):
    documents = tmp_path / "Documents"; documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "schema": 1, "server_status": {"phase": 2, "error": None, "game_error": "public fixture error"}}))
    with pytest.raises(probe.ProbeError, match="native_game_preparation_failed") as caught:
        probe.wait_report(tmp_path, lambda: 1)
    assert caught.value.native_detail == "public fixture error"
