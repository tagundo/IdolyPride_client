"""Focused ARM proof must retain one session and reject incomplete evidence."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import grpc
import pytest


SPEC = spec_from_file_location("focused_arm_live_qa", Path(__file__).with_name("qa_arm_live.py"))
arm = module_from_spec(SPEC)
SPEC.loader.exec_module(arm)
TOKEN = "original-local-arm-session"
IDS = ("9000000000000000301", "9000000000000000302")


class Rejected(grpc.RpcError):
    def __init__(self, code):
        self.status = code

    def code(self):
        return self.status


def client_schema():
    path = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Recovered client descriptor is unavailable")
    return arm.native.Schema.from_descriptor_set(path)


class Device:
    def __init__(self):
        self.process = self.running = self.mode = False
        self.pid = 100
        self.starts = 0
        self.events = []
        self.forget_mode = False

    def adb(self, *args, **kwargs):
        self.events.append((args, kwargs))
        if args[:3] == ("shell", "am", "start"):
            self.process = True
            self.pid += 1
        elif args[:3] == ("shell", "am", "force-stop"):
            self.process = self.running = False
            if self.forget_mode:
                self.mode = False
        elif args[:3] == ("shell", "pidof", "-s"):
            assert kwargs == {"check": False}
            return str(self.pid) if self.process else ""
        else:
            raise AssertionError(args)
        return ""

    def tap(self, label, stage):
        assert self.process
        self.events.append(((label, stage), {}))
        if label == arm.MODE_LABEL:
            assert not self.running
            self.mode = not self.mode
        elif label == "서버 시작":
            self.running = True
            self.starts += 1
        elif label == "서버 중지":
            self.running = False
        else:
            raise AssertionError(label)

    def capture(self, stage):
        self.events.append((("capture", stage), {}))
        node = ET.Element("node", {"class": "android.widget.CheckBox", "text": arm.MODE_LABEL,
                                  "checked": str(self.mode).lower()})
        root = ET.Element("hierarchy")
        root.append(node)
        return root


@pytest.fixture
def focused(tmp_path, monkeypatch):
    schema, qa = client_schema(), Device()
    user = schema.response_type("/api.User/Get")()
    user.user.name = "Original local manager"
    user.userPublic.publicUserId = "local-only-profile"
    user.balance.freeBalance = 10
    preserved = {"profiles": [("sandbox",)], "sessions": [(TOKEN,)], "profile_settings": [("saved",)]}
    clock = (b"original raw lesson clock", schema.fingerprint)
    attempts = [("one", "seed/time/response-1"), ("two", "seed/time/response-2")]
    receipt = {"snapshot_sha256": "safe fake digest"}
    calls, checks, bootstraps = [], [], []
    state = {"default_code": grpc.StatusCode.UNIMPLEMENTED, "default_enabled": False,
             "default_mutates": False, "preexisting": False, "protected_changed": False}

    def rpc(received_schema, port, path, token=None, request=None, request_id=None):
        assert received_schema is schema and port == 12345 and qa.running
        calls.append((qa.starts, path, token, request_id, qa.mode))
        if path == "/api.System/Check":
            assert token is None and request_id is None
            return SimpleNamespace(keepAliveTimeMilliseconds=1000)
        assert token == TOKEN
        if path == "/api.User/Get":
            return type(user).FromString(user.SerializeToString())
        if path == "/api.Quest/Start":
            assert request.questId == "qt-main-1-001-01" and request.deckNumber == request.playCount == 1
            if not qa.mode and not state["default_enabled"]:
                if state["default_mutates"]:
                    user.balance.freeBalance += 50
                raise Rejected(state["default_code"])
            return schema.response_type(path)(questId=request.questId)
        assert request_id is None
        if path == "/api.Home/Login":
            assert (request.settingInfo.soundBgm, request.settingInfo.soundEffect,
                    request.settingInfo.soundVoice, request.settingInfo.frameRate,
                    request.settingInfo.nightMode) == (37, 29, 61, 30, True)
        elif path == "/api.Home/Enter":
            return schema.response_type(path)(currentMainAreaId="area-main-001")
        elif path == "/api.Home/SetReview":
            user.user.isReviewed = True
        elif path == "/api.Tutorial/Init":
            assert request.name == "QAManager"
            user.user.name = request.name
        elif path == "/api.Tutorial/Progress":
            assert request.type == 1 and request.step == 150
        else:
            raise AssertionError(path)
        return schema.response_type(path)()

    def bootstrap(received_schema, port):
        assert received_schema is schema and port == 12345 and qa.running and not qa.mode and qa.starts == 1
        bootstraps.append(qa.starts)
        return SimpleNamespace(keepAliveTimeMilliseconds=1000), SimpleNamespace(gameAuthToken=TOKEN)

    def tutorial(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and qa.starts == 2 and qa.mode and master_dir == tmp_path
        assert label == "Android native"
        invoke("/api.Tutorial/Progress", schema.request_type("/api.Tutorial/Progress")(type=1, step=150))
        checks.append(("tutorial", qa.starts))
        return {"completed_step": 150, "platform": label}

    def native_live(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and qa.starts == 3 and qa.mode and master_dir == tmp_path
        assert label == "Android native"
        for identity in IDS:
            invoke("/api.Quest/Start", schema.request_type("/api.Quest/Start")(
                questId="qt-main-1-001-01", deckNumber=1, playCount=1), identity)
        invoke("/api.User/Get", schema.request_type("/api.User/Get")(), None)
        return dict(receipt)

    def retries(received_schema, invoke, master_dir, saved):
        assert received_schema is schema and qa.starts == 4 and qa.mode and saved == receipt
        assert master_dir == tmp_path
        for identity in IDS:
            invoke("/api.Quest/Start", schema.request_type("/api.Quest/Start")(
                questId="qt-main-1-001-01", deckNumber=1, playCount=1), identity)
        invoke("/api.User/Get", schema.request_type("/api.User/Get")(), None)

    def wait(received_schema, port, *, expected=True, timeout):
        assert received_schema is schema and port == 12345 and not expected and not qa.running and timeout == 30

    def capture_preserved(received_qa):
        assert received_qa is qa and not qa.process and qa.starts == 1
        checks.append(("baseline", qa.starts))
        return preserved

    def verify_preserved(received_qa, expected):
        assert received_qa is qa and not qa.process and expected == preserved
        if state["protected_changed"]:
            raise RuntimeError("identity/session/settings changed")
        checks.append(("preserved", qa.starts))

    def database(received_qa, received_schema, saved=None, *, expected_clock=None, expected_attempts=None):
        assert received_qa is qa and received_schema is schema and not qa.process
        checks.append(("database", qa.starts))
        if saved is None:
            assert qa.starts == 2
            return clock, (("existing",),) if state["preexisting"] else ()
        assert saved == receipt and expected_clock == clock
        current = tuple(attempts)
        if expected_attempts is not None and expected_attempts != current:
            raise RuntimeError("cached seed/time/response changed")
        return clock, current

    monkeypatch.setattr(arm.native, "rpc", rpc)
    monkeypatch.setattr(arm.native, "bootstrap", bootstrap)
    monkeypatch.setattr(arm.native, "wait_server", wait)
    monkeypatch.setattr(arm.native, "assert_starter_roster", lambda value: checks.append(("roster", qa.starts)))
    monkeypatch.setattr(arm.native, "assert_starter_home_positions", lambda value: checks.append(("home", qa.starts)))
    monkeypatch.setattr(arm.native, "assert_initial_inventory", lambda value, master: {
        "initial_card_count": 17, "initial_item_count": 2, "default_unit_slot_count": 5})
    monkeypatch.setattr(arm, "preserved_database", capture_preserved)
    monkeypatch.setattr(arm.native, "verify_upgrade_database", verify_preserved)
    monkeypatch.setattr(arm.native, "verify_main_live_database", database)
    monkeypatch.setattr(arm.tutorial_qa, "run_tutorial_continuation", tutorial)
    monkeypatch.setattr(arm.main_live_qa, "run_main_live_checks", native_live)
    monkeypatch.setattr(arm.main_live_qa, "assert_main_live_retries", retries)
    return schema, qa, tmp_path, state, calls, checks, bootstraps, attempts, receipt


def run_focused(focused):
    schema, qa, directory, *_rest = focused
    return arm.exercise(qa, schema, 12345, directory, 600)


def test_four_process_starts_reuse_one_original_session_and_compare_stopped_receipts(focused):
    _schema, qa, _directory, _state, calls, checks, bootstraps, _attempts, receipt = focused
    result = run_focused(focused)
    assert qa.starts == 4 and not qa.process and not qa.running
    assert bootstraps == [1]
    assert result["qa_scope"] == "first_main_live_native_integration"
    assert result["full_legacy_regression_tested"] is False and result["device_game_client_tested"] is False
    assert result["native_go_init_verified"] is result["mode_setting_persisted"] is result["final_stop"] is True
    assert result["main_live"] == receipt
    assert all(value is True for key, value in result.items() if key.startswith("main_live_") and key != "main_live")
    assert [(number, identity) for number, path, _token, identity, _mode in calls if path == "/api.Quest/Start"] == [
        (1, arm.DEFAULT_REQUEST_ID), (3, IDS[0]), (3, IDS[1]), (4, IDS[0]), (4, IDS[1])]
    assert all(token == TOKEN for _number, path, token, _identity, _mode in calls if path != "/api.System/Check")
    assert checks == [("roster", 1), ("home", 1), ("baseline", 1),
        ("tutorial", 2), ("preserved", 2), ("database", 2),
        ("preserved", 3), ("database", 3), ("preserved", 4), ("database", 4)]
    after_init = next(i for i, call in enumerate(calls) if call[1] == "/api.Tutorial/Progress")
    assert calls[after_init + 1][1] == "/api.Home/Enter"
    assert sum(event[0][0] == arm.MODE_LABEL for event in qa.events) == 1


def test_missing_bootstrap_session_stops_before_profile_mutations(focused, monkeypatch):
    monkeypatch.setattr(arm.native, "bootstrap", lambda *_args: (
        SimpleNamespace(keepAliveTimeMilliseconds=1000), SimpleNamespace(gameAuthToken="")))
    with pytest.raises(RuntimeError, match="valid local session"):
        run_focused(focused)
    assert [path for _start, path, _token, _identity, _mode in focused[4]] == ["/api.System/Check"]


def test_initial_enabled_checkbox_is_not_silently_reset_by_the_driver(focused):
    focused[1].mode = True
    with pytest.raises(RuntimeError, match="retain the expected"):
        run_focused(focused)
    assert focused[1].starts == 0 and not focused[4]


@pytest.mark.parametrize("field,expected", (("default_enabled", "enabled by default"),
    ("default_mutates", "changed the snapshot"), ("preexisting", "already has"),
    ("protected_changed", "identity/session/settings")))
def test_incomplete_mode_or_preservation_cannot_produce_a_success_report(focused, field, expected):
    focused[3][field] = True
    with pytest.raises(RuntimeError, match=expected):
        run_focused(focused)


def test_wrong_default_off_status_is_not_retried_as_a_mutation(focused):
    focused[3]["default_code"] = grpc.StatusCode.FAILED_PRECONDITION
    with pytest.raises(Rejected):
        run_focused(focused)
    assert sum(call[1] == "/api.Quest/Start" for call in focused[4]) == 1


def test_lost_checkbox_preference_stops_before_computed_requests(focused, monkeypatch):
    original = focused[1].adb

    def forget_after_tutorial(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[:3] == ("shell", "am", "force-stop") and focused[1].starts == 2:
            focused[1].mode = False
        return value

    monkeypatch.setattr(focused[1], "adb", forget_after_tutorial)
    with pytest.raises(RuntimeError, match="retain the expected"):
        run_focused(focused)
    assert [(call[0], call[3]) for call in focused[4] if call[1] == "/api.Quest/Start"] == [
        (1, arm.DEFAULT_REQUEST_ID)]


def test_cached_seed_time_or_response_change_is_rejected_after_restart(focused, monkeypatch):
    original = arm.main_live_qa.assert_main_live_retries

    def rerolled(*args, **kwargs):
        original(*args, **kwargs)
        focused[7][0] = ("one", "different seed/time/response")

    monkeypatch.setattr(arm.main_live_qa, "assert_main_live_retries", rerolled)
    with pytest.raises(RuntimeError, match="cached seed/time/response changed"):
        run_focused(focused)


def startup_device(monkeypatch, pids, *, ready=False):
    pending = iter(pids)
    observed = []

    class Process:
        def adb(self, *args, **kwargs):
            assert args == ("shell", "pidof", "-s", arm.native.PACKAGE) and kwargs == {"check": False}
            value = next(pending)
            observed.append(value)
            return value

    probes = []

    def rpc(*_args):
        probes.append(True)
        if not ready:
            raise Rejected(grpc.StatusCode.UNAVAILABLE)
        return SimpleNamespace(keepAliveTimeMilliseconds=1000)

    ticks = iter(range(100))
    monkeypatch.setattr(arm.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(arm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(arm.native, "rpc", rpc)
    return Process(), observed, probes


def test_native_signal_death_fails_after_three_missing_process_observations(monkeypatch):
    qa, observations, probes = startup_device(monkeypatch, ["", "", ""])
    with pytest.raises(RuntimeError, match="process exited"):
        arm.wait_started(qa, object(), 12345, initial_pid="123", timeout=600)
    assert observations == ["", "", ""] and not probes


def test_native_process_replacement_does_not_hide_a_startup_crash(monkeypatch):
    qa, observations, probes = startup_device(monkeypatch, ["456"], ready=True)
    with pytest.raises(RuntimeError, match="process changed"):
        arm.wait_started(qa, object(), 12345, initial_pid="123", timeout=600)
    assert observations == ["456"] and not probes


def test_startup_requires_an_observed_owned_process_before_accepting_a_port(monkeypatch):
    qa, observations, probes = startup_device(monkeypatch, ["", "123"], ready=True)
    arm.wait_started(qa, object(), 12345, initial_pid="", timeout=600)
    assert observations == ["", "123"] and probes == [True]


@pytest.mark.parametrize("serial,qemu", (("physical-phone", "1"), ("emulator-5554", "0")))
def test_rejected_targets_are_not_installed_captured_or_read_for_logs(tmp_path, monkeypatch, serial, qemu):
    calls = []

    class RefusedDevice:
        def __init__(self, _adb, _serial, artifacts):
            artifacts.mkdir(parents=True)

        def adb(self, *args, **kwargs):
            calls.append(args)
            assert args == ("shell", "getprop", "ro.kernel.qemu")
            return qemu

        def capture(self, _stage):
            raise AssertionError("Rejected target must not be captured")

        def close(self):
            raise AssertionError("Rejected target must not be read for logcat")

    monkeypatch.setattr(arm.native, "QA", RefusedDevice)
    out = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="disposable emulator"):
        arm.main(["--apk", str(tmp_path / "not-read.apk"), "--serial", serial, "--artifacts", str(out)])
    assert calls == ([] if serial == "physical-phone" else [("shell", "getprop", "ro.kernel.qemu")])
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] is False and result["qa_scope"] == arm.SCOPE


@pytest.mark.parametrize("case", ("existing-profile", "wrong-abi", "native-failure"))
def test_cli_keeps_evidence_only_after_a_fresh_owned_arm_target_is_verified(tmp_path, monkeypatch, case):
    events = []

    class Target:
        def __init__(self, _adb, _serial, artifacts):
            artifacts.mkdir(parents=True)

        def adb(self, *args, **kwargs):
            events.append(args)
            if args == ("shell", "getprop", "ro.kernel.qemu"):
                return "1"
            if args[:3] == ("install", "-r", "-g"):
                return "Success"
            if args[:4] == ("shell", "run-as", arm.native.PACKAGE, "ls"):
                return arm.native.PRIVATE_DATABASE if case == "existing-profile" else ""
            if args == ("shell", "dumpsys", "package", arm.native.PACKAGE):
                return "primaryCpuAbi=" + ("x86_64" if case == "wrong-abi" else "arm64-v8a")
            if args == ("logcat", "-c") or args == ("shell", "am", "force-stop", arm.native.PACKAGE):
                return ""
            raise AssertionError(args)

        def forward(self, port):
            assert port == 50051
            events.append(("forward",))
            return 12345

        def capture(self, stage):
            events.append(("capture", stage))

        def close(self):
            events.append(("close",))

    def failing_exercise(*_args):
        raise RuntimeError("native library process exited")

    monkeypatch.setattr(arm.native, "QA", Target)
    monkeypatch.setattr(arm.native.Schema, "from_descriptor_set", lambda _path: object())
    monkeypatch.setattr(arm, "exercise", failing_exercise)
    apk, out = tmp_path / "synthetic.apk", tmp_path / "artifacts"
    apk.write_bytes(b"own synthetic APK bytes are not executed by this unit test")
    expected = {"existing-profile": "freshly cleared", "wrong-abi": "production ARM64", "native-failure": "process exited"}[case]
    with pytest.raises(RuntimeError, match=expected):
        arm.main(["--apk", str(apk), "--artifacts", str(out)])
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] is False and result["error_type"] == "RuntimeError"
    if case == "native-failure":
        assert ("capture", "90-final") in events and ("close",) in events
        assert result["installed_primary_cpu_abi"] == "arm64-v8a"
    else:
        assert not any(event[0] in ("capture", "close", "forward", "logcat") for event in events)
        assert ("shell", "am", "force-stop", arm.native.PACKAGE) not in events
