from pathlib import Path
import json
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


def test_home_hierarchy_reference_requires_both_master_rows(tmp_path):
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "HierarchyDetailGrade.json").write_text(json.dumps([
        {"id": "hie-007-003", "hierarchyGradeId": "hie-007"}]))
    (master / "HierarchyGrade.json").write_text(json.dumps([{"id": "hie-007"}]))
    home = SimpleNamespace(hierarchyNotiInfo=SimpleNamespace(currentDetailGradeId="hie-007-003"))
    assert engine._home_hierarchy_reference(home, tmp_path) is True
    home.hierarchyNotiInfo.currentDetailGradeId = ""
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "missing"
    assert engine._home_hierarchy_reference(home, tmp_path) is False
    home.hierarchyNotiInfo.currentDetailGradeId = "hie-007-003"
    (master / "HierarchyGrade.json").write_text("[]")
    assert engine._home_hierarchy_reference(home, tmp_path) is False


class Runtime:
    def __init__(self):
        self.running = True
        self.stops = 0

    def status(self):
        return {"running": self.running, "profile": "sandbox", "grpc_address": "127.0.0.1:50051",
                "asset_url": "http://127.0.0.1:8080", "logs": ["not repeated in status"]}

    def stop(self):
        self.running = False
        self.stops += 1


def wait_until(check):
    deadline = time.monotonic() + 3
    while not check() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert check()


def test_native_control_start_stop_does_not_duplicate_runtime_or_logs(tmp_path, monkeypatch):
    events, runtimes = [], []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        runtime = Runtime()
        runtimes.append(runtime)
        kwargs["log_callback"]("server ready")
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda event, **data: events.append((event, data)))
    controller.start()
    wait_until(lambda: controller.runtime is not None)
    controller.start()
    assert len(runtimes) == 1
    assert controller.status()["running"] is True
    assert "logs" not in controller.status()
    controller.stop()
    assert runtimes[0].stops == 1
    assert controller.status()["running"] is False
    controller.close()
    assert runtimes[0].stops == 1
    assert any(event == "log" and data["message"] == "server ready" for event, data in events)


def test_quit_during_startup_cancels_owned_runtime_without_late_start(tmp_path, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    runtime = Runtime()
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)

    def start(*args, **kwargs):
        entered.set()
        assert finish.wait(timeout=3)
        return runtime

    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(start=start))
    import idoly_local
    monkeypatch.setattr(idoly_local, "app_runtime", sys.modules["idoly_local.app_runtime"], raising=False)
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.start()
    assert entered.wait(timeout=3)
    controller.stop()
    finish.set()
    wait_until(lambda: controller.worker is None)
    assert runtime.stops == 1
    assert controller.runtime is None
    assert controller.status()["running"] is False
    controller.close()


def test_stop_failure_retains_owned_runtime_for_retry(tmp_path):
    class RetryRuntime(Runtime):
        def stop(self):
            self.stops += 1
            self.running = False
            if self.stops == 1:
                raise RuntimeError("retry cleanup")

    runtime = RetryRuntime()
    controller = engine.Controller(tmp_path, tmp_path / "ServerData.zip", emit_event=lambda *args, **kwargs: None)
    controller.runtime = runtime
    assert controller.stop()["can_stop"] is True
    assert controller.runtime is runtime
    assert controller.stop()["can_stop"] is False
    assert controller.runtime is None
    assert runtime.stops == 2
