"""Portable fake-process contracts only; these do not establish an actual UI tap."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
UDID = "12345678-1234-1234-1234-123456789ABC"
PRIVATE = "PRIVATE_SIGNED_URL_TOKEN_MUST_NOT_ESCAPE"


def load_driver():
    path = ROOT / "ios-unified/probe/ui_test_driver.py"
    spec = importlib.util.spec_from_file_location("idoly_ui_test_driver_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Pipe:
    def __init__(self, owner, fd):
        self.owner, self.fd, self.closed = owner, fd, False
    def fileno(self):
        return self.fd
    def close(self):
        self.closed = True


class Process:
    def __init__(self, owner, args, kwargs):
        self.owner, self.args, self.kwargs = owner, args, kwargs
        self.pid = 1000 + len(owner.calls)
        self.stdout = Pipe(owner, self.pid)
        self.code = None
        owner.buffers[self.pid] = b""
    def poll(self):
        return self.code
    def wait(self, timeout):
        assert timeout <= 0.2
        if self.code is None:
            raise subprocess.TimeoutExpired("owned-xcodebuild", timeout)
        return self.code
    def emit(self, value):
        self.owner.buffers[self.pid] += value
    def complete(self, value=b"", code=0):
        self.emit(value)
        self.code = code


class Processes:
    def __init__(self):
        self.calls, self.buffers, self.killed = [], {}, []
    def __call__(self, args, **kwargs):
        process = Process(self, list(args), kwargs)
        self.calls.append(process)
        return process
    def read(self, fd, size):
        value = self.buffers[fd]
        if not value:
            raise BlockingIOError()
        result, self.buffers[fd] = value[:size], value[size:]
        return result
    def killpg(self, pid, sig):
        assert any(process.pid == pid for process in self.calls)
        self.killed.append((pid, sig))
        next(process for process in self.calls if process.pid == pid).code = -15


@pytest.fixture
def env(tmp_path, monkeypatch):
    module = load_driver()
    source = tmp_path / "source"
    source.mkdir()
    for relative in module.SOURCE_PATHS:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic committed source: " + relative)
    monkeypatch.setattr(module, "_SOURCE_ROOT", source)
    monkeypatch.setattr(module, "_DRIVER_PATH", source / "ui_test_driver.py")
    processes = Processes()
    monkeypatch.setattr(module.subprocess, "Popen", processes)
    monkeypatch.setattr(module.os, "set_blocking", lambda fd, blocking: None)
    monkeypatch.setattr(module.os, "read", processes.read)
    monkeypatch.setattr(module.os, "killpg", processes.killpg)
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    driver = module.ProbePromptCancelDriver(UDID, remaining=lambda cap=60: min(cap, 900))
    yield module, driver, processes, source, clock
    driver.close()


def built_products(env, *, mutate=None, extra=False):
    module, driver, processes, source, clock = env
    products = driver._derived / "Build/Products"
    host = products / "Debug-iphonesimulator/IdolyProbeCancelUITests-Runner.app"
    test = host / "PlugIns/IdolyProbeCancelUITests.xctest"
    app = products / "Debug-iphonesimulator/CancelDriverHost.app"
    test.mkdir(parents=True)
    app.mkdir(parents=True)
    for path, identifier in ((host, module.RUNNER_BUNDLE), (app, module.DUMMY_BUNDLE)):
        (path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier,
                                                        "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}))
    target = {"BlueprintName": module.SCHEME, "IsUITestBundle": True,
        "TestHostPath": "__TESTROOT__/Debug-iphonesimulator/IdolyProbeCancelUITests-Runner.app",
        "TestBundlePath": "__TESTHOST__/PlugIns/IdolyProbeCancelUITests.xctest",
        "UITargetAppPath": "__TESTROOT__/Debug-iphonesimulator/CancelDriverHost.app"}
    if mutate:
        mutate(target)
    data = {"__xctestrun_metadata__": {"FormatVersion": 2},
            "TestConfigurations": [{"TestTargets": [target]}]}
    path = products / "IdolyProbeCancelUITests_iphonesimulator18.5-arm64.xctestrun"
    path.write_bytes(plistlib.dumps(data))
    if extra:
        (products / "IdolyProbeCancelUITests_extra-iphonesimulator.xctestrun").write_bytes(plistlib.dumps(data))
    return path


def summary():
    value = lambda text: {"_value": text}
    return {"metrics": {"testsCount": value("1"), "testsFailedCount": value("0"), "testsSkippedCount": value("0")},
        "actions": {"_values": [{"schemeCommandName": value("Test"),
          "runDestination": {"targetDeviceRecord": {"identifier": value(UDID)}},
          "actionResult": {"status": value("succeeded"), "testsRef": {"id": value("0~actual-test-reference")}}}]}}


def results():
    leaf = {"_type": {"_name": "ActionTestMetadata"},
        "identifier": {"_value": "OfficialPromptCancelTests/testCancelExistingProbePrompt()"},
        "name": {"_value": "testCancelExistingProbePrompt()"}, "testStatus": {"_value": "Success"}}
    return {"summaries": {"_values": [{"testableSummaries": {"_values": [{
        "targetName": {"_value": "IdolyProbeCancelUITests"}, "tests": {"_values": [{
            "_type": {"_name": "ActionTestSummaryGroup"}, "subtests": {"_values": [leaf]}}]}}]}}]}}


def first_leaf(value):
    return value["summaries"]["_values"][0]["testableSummaries"]["_values"][0]["tests"]["_values"][0]["subtests"]["_values"][0]


def testing(env):
    module, driver, processes, source, clock = env
    assert driver.start()["phase"] == "building"
    path = built_products(env)
    processes.calls[0].complete(b"build complete\n")
    status = driver.poll()
    assert status == {"phase": "running", "ready": False, "error_code": None}
    assert len(processes.calls) == 2
    return path


def reading_summary(env):
    module, driver, processes, source, clock = env
    testing(env)
    processes.calls[1].emit(module.READY_MARKER + b"\n")
    assert driver.poll()["ready"] is True
    driver._result.mkdir()
    processes.calls[1].complete(b"** TEST SUCCEEDED **\n")
    assert driver.poll()["phase"] == "running"
    assert len(processes.calls) == 3


def reading_tests(env, root=None):
    module, driver, processes, source, clock = env
    reading_summary(env)
    processes.calls[2].complete(json.dumps(summary() if root is None else root).encode())
    status = driver.poll()
    assert status["phase"] == "running", status
    assert len(processes.calls) == 4


def assert_sanitized(value):
    rendered = str(value) + repr(value)
    assert PRIVATE not in rendered and "https://" not in rendered and "secret?" not in rendered


def test_exact_public_commands_handshake_and_validated_single_test_proof(env):
    module, driver, processes, source, clock = env
    reading_tests(env)
    processes.calls[3].complete(json.dumps(results()).encode())
    assert driver.poll()["phase"] == "passed"
    proof = driver.finish()
    assert proof["schema"] == 1 and proof["status"] == "PASS" and proof["execution"] == "public_xctest"
    assert proof["simulator_udid"] == UDID and proof["test_identifier"] == module.TEST_IDENTIFIER
    assert proof["tests"] == 1 and proof["failures"] == proof["skipped"] == 0
    assert proof["actual_cancel_tap"] is True and proof["ready_marker_observed"] is True
    assert set(proof["source_pins"]) == set(module.SOURCE_PATHS)
    for relative, sha in proof["source_pins"].items():
        assert sha == hashlib.sha256((source / relative).read_bytes()).hexdigest()
    assert proof["source_sha256"] == hashlib.sha256(json.dumps(proof["source_pins"], sort_keys=True,
                                                             separators=(",", ":")).encode()).hexdigest()
    for name in ("xctestrun_sha256", "xcresult_summary_sha256", "xcresult_tests_sha256"):
        assert len(proof[name]) == 64
    build, test, root, detail = [p.args for p in processes.calls]
    assert build == ["xcodebuild", "-project", str(source / "ui-tests/IdolyProbeCancelUITests.xcodeproj"),
        "-scheme", module.SCHEME, "-configuration", "Debug", "-destination", "id=" + UDID,
        "-derivedDataPath", str(driver._derived), "CODE_SIGNING_ALLOWED=NO", "build-for-testing"]
    assert "test-without-building" in test and "build-for-testing" not in test
    assert test.count("-only-testing:" + module.TEST_IDENTIFIER) == 1
    assert test[test.index("-destination") + 1] == "id=" + UDID
    assert test[test.index("-parallel-testing-enabled") + 1] == "NO"
    assert test[test.index("-maximum-concurrent-test-simulator-destinations") + 1] == "1"
    assert root == ["xcrun", "xcresulttool", "get", "--legacy", "--path", str(driver._result), "--format", "json"]
    assert detail == root + ["--id", "0~actual-test-reference"]
    assert all(p.kwargs["start_new_session"] is True and p.kwargs["stdin"] == subprocess.DEVNULL for p in processes.calls)
    assert all(p.kwargs["stderr"] == subprocess.STDOUT for p in processes.calls[:2])
    assert all(p.kwargs["stderr"] == subprocess.DEVNULL for p in processes.calls[2:])
    assert all(not any(word in p.args for word in ("simctl", "launch", "activate", "terminate", "install", "boot", "shutdown", "delete"))
               for p in processes.calls)
    work = driver._work
    driver.close()
    assert not work.exists() and not processes.killed


@pytest.mark.parametrize("bad", ["booted", "all", "", "../private", "https://secret?" + PRIVATE, None])
def test_no_arbitrary_simulator_selector_or_input_is_accepted(env, bad):
    module, driver, processes, source, clock = env
    with pytest.raises(module.DriverError) as caught:
        module.ProbePromptCancelDriver(bad, remaining=lambda cap=60: cap)
    assert caught.value.code == "ui_driver_udid_invalid"
    assert_sanitized(caught.value)
    assert not processes.calls


def test_spawn_does_not_mean_ready_and_only_exact_standalone_marker_counts(env):
    module, driver, processes, source, clock = env
    testing(env)
    processes.calls[1].emit(b"prefix " + module.READY_MARKER + b"\n")
    assert driver.poll()["ready"] is False
    processes.calls[1].emit(module.READY_MARKER[:10])
    assert driver.poll()["ready"] is False
    processes.calls[1].emit(module.READY_MARKER[10:] + b"\r\n")
    assert driver.poll()["ready"] is True


def test_success_log_alone_and_zero_exit_without_handshake_are_never_proof(env):
    module, driver, processes, source, clock = env
    testing(env)
    processes.calls[1].complete(b"** TEST SUCCEEDED **\n" + PRIVATE.encode())
    status = driver.poll()
    assert status["phase"] == "failed" and status["error_code"] == "ui_driver_ready_missing"
    with pytest.raises(module.DriverError) as caught:
        driver.finish()
    assert_sanitized(caught.value)
    assert len(processes.calls) == 2


@pytest.mark.parametrize("mutation,code", [
    (lambda x: x["metrics"]["testsCount"].update(_value="2"), "ui_driver_result_count_mismatch"),
    (lambda x: x["metrics"]["testsFailedCount"].update(_value="1"), "ui_driver_result_count_mismatch"),
    (lambda x: x["metrics"]["testsSkippedCount"].update(_value="1"), "ui_driver_result_count_mismatch"),
    (lambda x: x["metrics"]["testsCount"].update(_value=True), "ui_driver_result_invalid"),
    (lambda x: x["actions"]["_values"][0]["actionResult"]["status"].update(_value="failed"), "ui_driver_result_not_success"),
    (lambda x: x["actions"]["_values"][0]["runDestination"]["targetDeviceRecord"]["identifier"].update(_value="other-device"), "ui_driver_result_destination_mismatch"),
    (lambda x: x["actions"]["_values"][0]["actionResult"]["testsRef"]["id"].update(_value="https://secret?" + PRIVATE), "ui_driver_result_invalid"),
])
def test_result_root_requires_actual_destination_counts_success_and_local_reference(env, mutation, code):
    module, driver, processes, source, clock = env
    reading_summary(env)
    root = summary()
    mutation(root)
    processes.calls[2].complete(json.dumps(root).encode())
    status = driver.poll()
    assert status["phase"] == "failed" and status["error_code"] == code
    assert len(processes.calls) == 3
    assert_sanitized(status)


@pytest.mark.parametrize("mutation,code", [
    (lambda x: first_leaf(x)["testStatus"].update(_value="Failure"), "ui_driver_result_not_success"),
    (lambda x: first_leaf(x)["testStatus"].update(_value="Skipped"), "ui_driver_result_not_success"),
    (lambda x: first_leaf(x)["identifier"].update(_value="OtherClass/testCancelExistingProbePrompt()"), "ui_driver_result_method_mismatch"),
    (lambda x: first_leaf(x)["identifier"].update(_value="OfficialPromptCancelTests/otherMethod()"), "ui_driver_result_method_mismatch"),
    (lambda x: x["summaries"]["_values"][0]["testableSummaries"]["_values"][0]["targetName"].update(_value="OtherTarget"), "ui_driver_result_target_mismatch"),
    (lambda x: x["summaries"]["_values"][0]["testableSummaries"]["_values"][0]["tests"]["_values"][0]["subtests"]["_values"].append(copy.deepcopy(first_leaf(x))), "ui_driver_result_count_mismatch"),
])
def test_actual_test_tree_requires_exact_single_method_success(env, mutation, code):
    module, driver, processes, source, clock = env
    reading_tests(env)
    value = results()
    mutation(value)
    processes.calls[3].complete(json.dumps(value).encode())
    status = driver.poll()
    assert status["phase"] == "failed" and status["error_code"] == code
    assert_sanitized(status)


@pytest.mark.parametrize("mutation", [lambda x: x.update(UITargetAppPath="/private/arbitrary.app"),
    lambda x: x.update(UITargetAppPath="__TESTROOT__/../arbitrary.app"),
    lambda x: x.update(UITargetAppPath="https://secret?" + PRIVATE),
    lambda x: x.update(UITargetAppBundleIdentifier="game.qualiarts.idolypride.iosprobe"),
    lambda x: x.update(BlueprintName="OtherTarget")])
def test_generated_run_cannot_target_arbitrary_paths_urls_or_probe(env, mutation):
    module, driver, processes, source, clock = env
    driver.start()
    built_products(env, mutate=mutation)
    processes.calls[0].complete()
    status = driver.poll()
    assert status["phase"] == "failed" and status["error_code"] == "ui_driver_xctestrun_invalid"
    assert len(processes.calls) == 1
    assert_sanitized(status)


def test_multiple_generated_xctestruns_are_rejected_instead_of_picking_one(env):
    module, driver, processes, source, clock = env
    driver.start()
    built_products(env, extra=True)
    processes.calls[0].complete()
    assert driver.poll()["error_code"] == "ui_driver_xctestrun_invalid"
    assert len(processes.calls) == 1


def test_source_changes_between_build_and_test_are_rejected(env):
    module, driver, processes, source, clock = env
    driver.start()
    built_products(env)
    (source / "ui-tests/OfficialPromptCancelTests.swift").write_text("changed source")
    processes.calls[0].complete()
    assert driver.poll()["error_code"] == "ui_driver_source_changed"
    assert len(processes.calls) == 1


def test_log_cap_stops_only_owned_process_and_fixed_deadline_is_enforced(env, monkeypatch):
    module, driver, processes, source, clock = env
    monkeypatch.setattr(module, "_LOG_LIMIT", 32)
    driver.start()
    processes.calls[0].emit(b"x" * 33)
    assert driver.poll()["error_code"] == "ui_driver_log_limit"
    assert processes.killed and processes.killed[0][0] == processes.calls[0].pid
    assert (driver._work / "build.log").stat().st_size <= 32


def test_phase_deadline_returns_fixed_error_without_exposing_logs(env):
    module, driver, processes, source, clock = env
    driver.start()
    processes.calls[0].emit(PRIVATE.encode())
    clock[0] += 181
    status = driver.poll()
    assert status["error_code"] == "ui_driver_deadline"
    assert_sanitized(status)
    assert processes.killed


def test_result_tool_failure_and_malformed_json_never_leak_details(env):
    module, driver, processes, source, clock = env
    reading_summary(env)
    processes.calls[2].complete(PRIVATE.encode(), code=1)
    status = driver.poll()
    assert status["error_code"] == "ui_driver_result_failed"
    assert_sanitized(status)



def test_only_failed_build_can_expose_its_verified_bounded_pre_input_tail(env):
    module, driver, processes, source, clock = env
    assert driver.build_failure_log() is None
    driver.start()
    assert driver.build_failure_log() is None
    payload = b"compiler diagnostic\n" + b"x" * (70 * 1024)
    processes.calls[0].complete(payload, code=65)
    assert driver.poll()["error_code"] == "ui_driver_build_failed"
    assert driver._failure_phase == "building" and not driver._test_spawned
    tail = driver.build_failure_log()
    assert type(tail) is bytes and len(tail) == 64 * 1024
    assert tail == payload[-64 * 1024:]
    assert len(processes.calls) == 1
    driver.close()
    assert driver.build_failure_log() is None


def test_test_failure_cannot_expose_build_test_or_result_logs(env):
    module, driver, processes, source, clock = env
    testing(env)
    processes.calls[1].complete(PRIVATE.encode(), code=65)
    assert driver.poll()["error_code"] == "ui_driver_test_failed"
    assert driver._failure_phase == "testing" and driver._test_spawned
    assert driver.build_failure_log() is None


def test_pre_input_build_diagnostic_cannot_follow_replaced_symlink(env):
    module, driver, processes, source, clock = env
    driver.start()
    processes.calls[0].complete(b"build error", code=65)
    assert driver.poll()["error_code"] == "ui_driver_build_failed"
    log = driver._work / "build.log"
    log.unlink()
    foreign = source / "foreign-build.log"
    foreign.write_bytes(PRIVATE.encode())
    log.symlink_to(foreign)
    assert driver.build_failure_log() is None
