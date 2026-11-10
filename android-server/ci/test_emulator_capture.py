"""Cold-start UI observations must settle before any normal touch is sent."""
import pytest

from test_tutorial_continuation_qa import qa


VALID = '<hierarchy rotation="0"><node text="서버 시작" enabled="true" bounds="[0,0][20,20]" /></hierarchy>'


def observer(tmp_path, monkeypatch, dumps):
    device = qa.QA("adb", "emulator-5554", tmp_path)
    calls = []
    pending = iter(dumps)

    def adb(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ("exec-out", "uiautomator"):
            assert kwargs == {"check": False}
            return next(pending)
        if args == ("exec-out", "screencap", "-p"):
            assert kwargs == {"binary": True}
            return b"test-screenshot"
        if args[:3] == ("shell", "input", "tap"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(device, "adb", adb)
    monkeypatch.setattr(qa.time, "sleep", lambda _seconds: None)
    return device, calls


def test_cold_activity_idle_failure_retains_evidence_then_uses_fresh_hierarchy(tmp_path, monkeypatch):
    device, calls = observer(tmp_path, monkeypatch, ["ERROR: could not get idle state", VALID])
    device.tap("서버 시작", "cold")
    assert (tmp_path / "cold-0-hierarchy-attempt-0.txt").read_text() == "ERROR: could not get idle state"
    assert (tmp_path / "cold-0-hierarchy-attempt-0.png").read_bytes() == b"test-screenshot"
    assert (tmp_path / "cold-0.xml").read_text() == VALID
    assert [args for args, _kwargs in calls if args[:3] == ("shell", "input", "tap")] == [
        ("shell", "input", "tap", "10", "10")]
    assert calls[-2][0] == ("exec-out", "screencap", "-p")


def test_malformed_observation_is_retried_without_saving_it_as_valid_xml(tmp_path, monkeypatch):
    broken = '<hierarchy><node></hierarchy>'
    device, _calls = observer(tmp_path, monkeypatch, [broken, VALID])
    assert device.capture("parse").tag == "hierarchy"
    assert (tmp_path / "parse-hierarchy-attempt-0.txt").read_text() == broken
    assert (tmp_path / "parse.xml").read_text() == VALID


def test_repeated_observation_failures_stop_without_any_input(tmp_path, monkeypatch):
    device, calls = observer(tmp_path, monkeypatch, ["not idle"] * 5)
    with pytest.raises(RuntimeError, match="after five observations"):
        device.tap("서버 시작", "failed")
    assert not any(args[:2] == ("shell", "input") for args, _kwargs in calls)
    assert not (tmp_path / "failed-0.xml").exists()
    assert len(list(tmp_path.glob("failed-0-hierarchy-attempt-*.txt"))) == 5
    assert (tmp_path / "failed-0.png").is_file()
