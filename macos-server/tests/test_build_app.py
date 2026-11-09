from pathlib import Path
import json
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_app


def test_native_smoke_launches_bundle_executable_and_requires_visible_window(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {"gui_started": True, "window_visible": False, "server_started": True, "server_stopped": True}
    (evidence / "app-smoke.json").write_text(json.dumps(report))
    app = tmp_path / "이동한 앱/Local Server.app"
    calls = []

    class Process:
        def __init__(self, command, **options):
            calls.append((command, options))

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(build_app.subprocess, "Popen", Process)
    with pytest.raises(ValueError, match="visible-window"):
        build_app.smoke_native_app(app, evidence, tmp_path / "data")
    command, options = calls[0]
    assert command[0] == str(app / "Contents/MacOS/IdolyPrideLocalServer")
    assert options["start_new_session"] is True
    assert "--app-smoke" in command
    report["window_visible"] = True
    (evidence / "app-smoke.json").write_text(json.dumps(report))
    assert build_app.smoke_native_app(app, evidence, tmp_path / "data") == report


def test_native_smoke_timeout_terminates_only_its_owned_process_group_and_reports_phase(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "app-smoke.checkpoint.json").write_text(json.dumps({"phase": "model_initialized"}))
    terminated = []

    class Process:
        pid = 123456

        def __init__(self, *args, **kwargs):
            self.waits = 0

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("owned-native-app", timeout)
            return -15

    monkeypatch.setattr(build_app.subprocess, "Popen", Process)
    monkeypatch.setattr(build_app.os, "killpg", lambda pid, signal: terminated.append((pid, signal)))
    with pytest.raises(ValueError, match="model_initialized"):
        build_app.smoke_native_app(tmp_path / "Local.app", evidence, tmp_path / "data", timeout=0.1)
    assert terminated == [(123456, build_app.signal.SIGTERM)]
