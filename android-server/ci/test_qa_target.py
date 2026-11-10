"""Only observed disposable guests may reach native APK or private-state QA."""
from types import SimpleNamespace
import json
import sys

import pytest

import qa_target as target
import qa_emulator as native


# Minimized non-secret indicators from the official ARM64-only Cuttlefish guest.
CVD = {
    "ro.hardware": "cutf_cvm", "ro.boot.hardware": "cutf_cvm",
    "ro.product.device": "vsoc_arm64_only", "ro.product.cpu.abi": "arm64-v8a",
    "ro.product.cpu.abilist": "arm64-v8a", "ro.dalvik.vm.native.bridge": "0",
    "ro.build.type": "userdebug", "ro.kernel.qemu": "",
}


def getter(properties, calls):
    def adb(*args, **kwargs):
        calls.append(args)
        assert args[:2] == ("shell", "getprop") and not kwargs
        return properties.get(args[2], "") + "\n"
    return adb


def test_official_native_arm_guest_is_identified_without_changing_properties():
    calls = []
    observed = target.verify_disposable_target(getter(CVD, calls), "127.0.0.1:6520")
    assert observed == {"kind": "cuttlefish_arm64_only", **CVD}
    assert {args[2] for args in calls} == set(CVD)


@pytest.mark.parametrize("serial", (
    "physical-phone", "127.0.0.1:5555", "localhost:6520", "[::1]:6520",
    "192.168.0.5:6520", "127.0.0.1:6521", "127.0.0.1:06520",
    "127.0.0.1:6520 ", " emulator-5554", "emulator-", "emulator-phone",
    "emulator-5554;reboot", "emulator-5554\n", None, 6520,
))
def test_unknown_or_noncanonical_transports_do_not_even_query_a_device(serial):
    calls = []
    with pytest.raises(RuntimeError, match="disposable emulator"):
        target.verify_disposable_target(getter(CVD, calls), serial)
    assert calls == []


@pytest.mark.parametrize("name,value", (
    ("ro.hardware", "ranchu"), ("ro.boot.hardware", "goldfish"),
    ("ro.product.device", "vsoc_x86_64"), ("ro.product.cpu.abi", "x86_64"),
    ("ro.product.cpu.abilist", "arm64-v8a,armeabi-v7a"),
    ("ro.dalvik.vm.native.bridge", "libndk_translation.so"),
    ("ro.dalvik.vm.native.bridge", ""), ("ro.build.type", "user"),
    ("ro.kernel.qemu", "1"), ("ro.hardware", ""),
))
def test_mixed_missing_or_translated_cvd_identity_is_rejected(name, value):
    properties, calls = dict(CVD), []
    properties[name] = value
    with pytest.raises(RuntimeError, match="disposable emulator"):
        target.verify_disposable_target(getter(properties, calls), "127.0.0.1:6520")
    assert ("shell", "getprop", name) in calls


@pytest.mark.parametrize("serial", ("emulator-5554", "emulator-5580"))
def test_legacy_stock_emulator_keeps_its_existing_qemu_guard(serial):
    calls = []
    observed = target.verify_disposable_target(getter({"ro.kernel.qemu": "1"}, calls), serial)
    assert observed == {"kind": "android_emulator", "ro.kernel.qemu": "1"}
    assert calls == [("shell", "getprop", "ro.kernel.qemu")]


@pytest.mark.parametrize("qemu", ("", "0", "true"))
def test_emulator_serial_alone_does_not_admit_a_target(qemu):
    with pytest.raises(RuntimeError, match="disposable emulator"):
        target.verify_disposable_target(getter({"ro.kernel.qemu": qemu}, []), "emulator-5554")


@pytest.mark.parametrize("pid", ("", "1234"))
def test_private_snapshot_guard_rechecks_cvd_identity_and_stopped_process(pid):
    calls = []
    def adb(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("shell", "getprop"):
            return CVD[args[2]]
        assert args == ("shell", "pidof", "-s", native.PACKAGE)
        assert kwargs == {"check": False}
        return pid
    qa = SimpleNamespace(command=["adb", "-s", "127.0.0.1:6520"], adb=adb)
    if pid:
        with pytest.raises(RuntimeError, match="force-stopped"):
            native._guard_stopped_emulator(qa)
    else:
        native._guard_stopped_emulator(qa)
    assert calls[-1] == ("shell", "pidof", "-s", native.PACKAGE)
    assert all(args[:2] == ("shell", "getprop") for args in calls[:-1])


def test_rejected_cli_target_is_not_installed_captured_or_read_for_logs(tmp_path, monkeypatch):
    calls = []
    class Refused:
        def __init__(self, _adb, _serial, artifacts):
            self.artifacts = artifacts
            artifacts.mkdir()
        def adb(self, *args, **kwargs):
            calls.append(args)
            raise AssertionError("Unknown transport must be rejected before ADB")
        def capture(self, _stage):
            raise AssertionError("Rejected target must not be captured")
        def close(self):
            raise AssertionError("Rejected target must not be read for logcat")
    monkeypatch.setattr(native, "QA", Refused)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["qa_emulator.py", "--apk", str(tmp_path / "missing.apk"),
                                      "--serial", "physical-phone", "--artifacts", str(out)])
    with pytest.raises(RuntimeError, match="disposable emulator"):
        native.main()
    assert calls == []
    report = json.loads((out / "result.json").read_text())
    assert report["ok"] is False and "target_evidence" not in report
