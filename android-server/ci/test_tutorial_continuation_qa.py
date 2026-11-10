"""Protect the installed-server continuation's restart and session boundary."""
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import json
from pathlib import Path

import pytest

from idoly_local.schema import Schema
from idoly_local import tutorial_qa


SCRIPT = Path(__file__).with_name("qa_emulator.py")
SPEC = spec_from_file_location("android_continuation_qa", SCRIPT)
qa = module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class Device:
    def __init__(self):
        self.process = self.running = False
        self.starts = 0
        self.events = []

    def adb(self, *args):
        self.events.append(args)
        if args[:3] == ("shell", "am", "start"):
            self.process = True
        elif args[:3] == ("shell", "am", "force-stop"):
            self.process = self.running = False
        else:
            raise AssertionError("Unexpected continuation adb action")

    def tap(self, text, stage):
        assert self.process
        self.events.append((text, stage))
        self.running = text == "서버 시작"
        if self.running:
            self.starts += 1

    def capture(self, stage):
        self.events.append((stage,))


@pytest.fixture
def continuation(tmp_path, monkeypatch):
    descriptor = Path(__file__).resolve().parents[2] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Recovered client descriptor is unavailable")
    schema = Schema.from_descriptor_set(descriptor)
    device = Device()
    final = schema.response_type("/api.User/Get")()
    final.user.tutorialClearedTime = 1790000000123
    final.tutorials.add(tutorialType=1, step=150)
    final.MergeFromString(qa.QA_UNKNOWN_PB)
    receipt = {"completed_step": 150,
               "snapshot_sha256": hashlib.sha256(final.SerializeToString(deterministic=True)).hexdigest()}
    calls, preserved_checks = [], []

    def rpc(received_schema, port, path, token=None, request=None):
        assert received_schema is schema and port == 12345 and token == "local-private-fixture"
        assert device.running
        calls.append(path)
        return final

    def run(received_schema, invoke, master_dir, *, label):
        assert received_schema is schema and master_dir == tmp_path and label == "Android native"
        assert device.starts == 1
        invoke("/api.Tutorial/Progress", schema.request_type("/api.Tutorial/Progress")(type=1, step=150))
        return dict(receipt)

    def wait(received_schema, port, *, expected=True, timeout):
        assert received_schema is schema and port == 12345 and device.running == expected

    def preserved(received_device, original):
        assert received_device is device and original == {"fixture": "unchanged"}
        assert not device.process and not device.running
        preserved_checks.append(device.starts)

    monkeypatch.setattr(qa, "rpc", rpc)
    monkeypatch.setattr(qa, "wait_server", wait)
    monkeypatch.setattr(qa, "verify_upgrade_database", preserved)
    monkeypatch.setattr(tutorial_qa, "run_tutorial_continuation", run)
    return schema, device, final, receipt, calls, preserved_checks, tmp_path


def exercise(fixture):
    schema, device, _final, _receipt, _calls, _preserved_checks, master = fixture
    return qa.exercise_tutorial_continuation(device, schema, 12345, "local-private-fixture",
                                              master, 600, {"fixture": "unchanged"})


def test_continuation_reuses_original_session_and_checks_final_snapshot_after_process_restart(continuation):
    _schema, device, _final, receipt, calls, preserved_checks, _master = continuation
    result = exercise(continuation)
    assert result["tutorial_continuation"] == receipt
    assert all(value is True for key, value in result.items() if key != "tutorial_continuation")
    assert calls == ["/api.Tutorial/Progress", "/api.User/Get"]
    assert preserved_checks == [1, 2]
    assert device.starts == 2 and not device.process
    assert "local-private-fixture" not in json.dumps(result)


def test_persistence_mismatch_cannot_produce_success_receipt(continuation):
    _schema, device, final, _receipt, _calls, checks, _master = continuation
    # The expected receipt was captured before this simulated lost progression.
    final.tutorials[0].step = 140
    with pytest.raises(RuntimeError, match="restart changed"):
        exercise(continuation)
    assert device.starts == 2 and checks == [1]


def test_changed_identity_rows_abort_before_claiming_restart_preservation(continuation, monkeypatch):
    _schema, device, _final, _receipt, _calls, _checks, _master = continuation

    def changed(*_):
        raise RuntimeError("identity changed")

    monkeypatch.setattr(qa, "verify_upgrade_database", changed)
    with pytest.raises(RuntimeError, match="identity changed"):
        exercise(continuation)
    assert device.starts == 1 and not device.process
