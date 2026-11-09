"""Portable validation of the synthetic-only ARM64 fixture's reporting contract."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "native/selftest"
SPEC = importlib.util.spec_from_file_location("native_selftest_driver", ROOT / "run_emulator.py")
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


def report():
    return {"schema": 1, "ok": True, "synthetic_only": True, "abi": "arm64-v8a",
            "shadowhook_version": "2.0.1", "init_result": 0, "init_errno": 0, "install_errno": 0,
            "bl_install_errno": 0, "add_unintercept_result": 0, "bl_unintercept_result": 0,
            **{name: True for name in DRIVER.CHECKS}}


def test_every_state_check_required():
    DRIVER.validate_report(report())
    for name in DRIVER.CHECKS:
        failed = report()
        failed[name] = False
        with pytest.raises(ValueError):
            DRIVER.validate_report(failed)


def test_unverified_or_non_arm64_reports_rejected():
    for changes in ({"ok": False}, {"abi": "x86_64"}, {"synthetic_only": False},
                    {"shadowhook_version": "unverified"}, {"gpr": 1}, {"init_result": 12},
                    {"init_errno": 35}, {"install_errno": -1}, {"init_result": False}):
        with pytest.raises(ValueError):
            DRIVER.validate_report({**report(), **changes})


def test_driver_rejects_physical_device_before_install(tmp_path, monkeypatch):
    class Result:
        returncode = 0
        stdout = "1\n"

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(DRIVER.subprocess, "run", execute)
    with pytest.raises(ValueError, match="disposable emulator"):
        DRIVER.run(tmp_path / "fixture.apk", adb="adb", serial="physical-123", artifacts=tmp_path / "logs")
    assert calls == []


def test_driver_rejects_non_arm64_emulator_before_install(tmp_path, monkeypatch):
    class Result:
        returncode = 0

        def __init__(self, output):
            self.stdout = output

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return Result("1\n" if command[-1] == "ro.kernel.qemu" else "x86_64,x86\n")

    monkeypatch.setattr(DRIVER.subprocess, "run", execute)
    with pytest.raises(ValueError, match="ARM64-capable"):
        DRIVER.run(tmp_path / "fixture.apk", adb="adb", serial="emulator-5554", artifacts=tmp_path / "logs")
    assert len(calls) == 2


def test_missing_json_preserves_scoped_failure_evidence_and_still_fails(tmp_path, monkeypatch):
    class Result:
        returncode = 0

        def __init__(self, output=""):
            self.stdout = output

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        tail = command[3:]
        if tail[-1] == "ro.kernel.qemu": return Result("1\n")
        if tail[-1] in ("ro.product.cpu.abi", "ro.product.cpu.abilist"): return Result("arm64-v8a\n")
        if tail[:6] == ["shell", "cmd", "package", "list", "packages", "-U"]:
            return Result("package:" + DRIVER.PACKAGE + ".other uid:99999\npackage:" + DRIVER.PACKAGE + " uid:10234\n")
        if tail[:2] == ["shell", "date"]: return Result("11-09T14:15:16.000\n")
        if tail[:3] == ["shell", "pidof", "-s"]: return Result("4321\n")
        if tail[:5] == ["shell", "dumpsys", "activity", "exit-info", DRIVER.PACKAGE]:
            return Result("synthetic package exit: SIGILL\n")
        if tail[:3] == ["logcat", "-b", "all"]: return Result("synthetic native bridge SIGILL\n")
        return Result()

    ticks = iter([0, 46])
    monkeypatch.setattr(DRIVER.subprocess, "run", execute)
    monkeypatch.setattr(DRIVER.time, "monotonic", lambda: next(ticks))
    artifacts = tmp_path / "logs"
    with pytest.raises(RuntimeError, match="Timed out"):
        DRIVER.run(tmp_path / "fixture.apk", adb="adb", serial="emulator-5554", artifacts=artifacts)
    failure_calls = [call for call in calls if call[3:6] == ["logcat", "-b", "all"]]
    assert len(failure_calls) == 1
    assert "--uid=10234" in failure_calls[0] and "11-09 14:15:16.000" in failure_calls[0]
    assert "--uid=99999" not in failure_calls[0]
    assert "*:V" in failure_calls[0]
    assert "SIGILL" in (artifacts / "failure-own-uid-logcat.txt").read_text()
    assert "SIGILL" in (artifacts / "failure-fixture-exit-info.txt").read_text()
    assert any(call[3:] == ["shell", "am", "force-stop", DRIVER.PACKAGE] for call in calls)


@pytest.mark.parametrize("proc_uid,expect_fallback", [("10234", True), ("99999", False), (None, True)])
def test_empty_uid_log_uses_pid_without_time_filter_and_checks_uid(tmp_path, monkeypatch, proc_uid, expect_fallback):
    class Result:
        returncode = 0

        def __init__(self, output=""):
            self.stdout = output

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        tail = command[3:]
        if tail[-1] == "ro.kernel.qemu": return Result("1\n")
        if tail[-1] in ("ro.product.cpu.abi", "ro.product.cpu.abilist"): return Result("arm64-v8a\n")
        if tail[:6] == ["shell", "cmd", "package", "list", "packages", "-U"]:
            return Result("package:" + DRIVER.PACKAGE + " uid:10234\n")
        if tail[:2] == ["shell", "date"]: return Result("11-09T14:15:16.000\n")
        if tail[:3] == ["shell", "pidof", "-s"]: return Result("4321\n")
        if tail == ["shell", "cat", "/proc/4321/status"]:
            return Result("" if proc_uid is None else "Uid:\t" + "\t".join([proc_uid] * 4) + "\n")
        if tail[:3] == ["logcat", "-b", "all"] and "--pid=4321" in tail:
            return Result("shadowhook_tag: init-errno: 12\n")
        return Result()

    ticks = iter([0, 46])
    monkeypatch.setattr(DRIVER.subprocess, "run", execute)
    monkeypatch.setattr(DRIVER.time, "monotonic", lambda: next(ticks))
    artifacts = tmp_path / "logs"
    with pytest.raises(RuntimeError, match="Timed out"):
        DRIVER.run(tmp_path / "fixture.apk", adb="adb", serial="emulator-5554", artifacts=artifacts)
    fallback = [call for call in calls if call[3:6] == ["logcat", "-b", "all"] and "--pid=4321" in call]
    assert bool(fallback) is expect_fallback
    if expect_fallback:
        assert len(fallback) == 1 and "--uid=10234" in fallback[0] and "-T" not in fallback[0]
        assert "init-errno: 12" in (artifacts / "failure-own-pid-logcat.txt").read_text()
    else:
        assert (artifacts / "failure-pid-reused.txt").is_file()
