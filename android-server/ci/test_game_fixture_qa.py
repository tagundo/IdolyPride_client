from types import SimpleNamespace
import json
import xml.etree.ElementTree as ET

import pytest

import qa_game_boot
from qa_game_boot import GAME, GameQA, game_launch_args, prepare_restarted_tutorial


def test_restarted_tutorial_fixture_calls_only_login_name_init_and_read():
    calls = []
    token = "private-test-session-not-in-report"

    def invoke(method, values, received):
        calls.append((method, values, received))
        if method == "/api.Auth/Login":
            return SimpleNamespace(gameAuthToken=token)
        if method == "/api.Tutorial/Init":
            return SimpleNamespace()
        return SimpleNamespace(tutorials=[SimpleNamespace(tutorialType=1, step=10)],
                               user=SimpleNamespace(name="QAManager", tutorialClearedTime=0))

    report = prepare_restarted_tutorial(None, 50051, caller=invoke)
    assert calls == [("/api.Auth/Login", {"firebaseIDToken": "local"}, None),
                     ("/api.Tutorial/Init", {"name": "QAManager"}, token),
                     ("/api.User/Get", {}, token)]
    assert token not in json.dumps(report)
    assert report["completed_tutorial_step"] == 10
    assert report["expected_client_next_tutorial_step"] == 100
    assert report["client_next_step_visually_verified"] is False
    assert report["tutorial_progress_or_skip_called"] is False
    assert report["purchase_or_grant_called"] is False
    assert all(row["origin"] == "profile_fixture" for row in report["rpc_calls"])


@pytest.mark.parametrize("step,cleared", [(0, 0), (150, 0), (10, 123)])
def test_fixture_rejects_unexpected_persistent_state_without_progress_or_skip(step, cleared):
    methods = []

    def invoke(method, values, token):
        methods.append(method)
        if method == "/api.Auth/Login":
            return SimpleNamespace(gameAuthToken="local-session")
        return SimpleNamespace(tutorials=[SimpleNamespace(tutorialType=1, step=step)],
                               user=SimpleNamespace(name="QAManager", tutorialClearedTime=cleared))

    with pytest.raises(RuntimeError, match="unprogressed disposable"):
        prepare_restarted_tutorial(None, 50051, caller=invoke)
    assert methods == ["/api.Auth/Login", "/api.Tutorial/Init", "/api.User/Get"]


def test_game_package_allowlist_keeps_override_on_qa_apps():
    assert game_launch_args(True, GAME + ".diagnostics")[5].startswith(GAME + ".diagnostics/")
    with pytest.raises(ValueError, match="dedicated local QA"):
        game_launch_args(False, "game.qualiarts.idolypride")


def test_server_capture_retries_observed_empty_tree_then_checks_fresh_package(tmp_path, monkeypatch):
    qa = GameQA("adb", "emulator-disposable", tmp_path)
    stages = []
    expected = ET.fromstring('<hierarchy><node package="game.qualiarts.idolypride.localserver"/></hierarchy>')

    def capture(stage):
        stages.append(stage)
        if len(stages) == 1:
            raise RuntimeError("uiautomator did not return a UI hierarchy")
        return expected

    monkeypatch.setattr(qa, "capture", capture)
    monkeypatch.setattr(qa, "adb", lambda *args, **kwargs: b"fresh screenshot")
    monkeypatch.setattr(qa_game_boot.time, "sleep", lambda delay: None)
    assert qa.capture_server("server-after-game") is expected
    assert stages == ["server-after-game", "server-after-game-retry-1"]
    assert "uiautomator" in (tmp_path / "server-after-game.error.txt").read_text()
    assert (tmp_path / "server-after-game.png").read_bytes() == b"fresh screenshot"


def test_server_capture_does_not_mask_persistent_or_other_failures(tmp_path, monkeypatch):
    qa = GameQA("adb", "emulator-disposable", tmp_path)
    calls = []

    def wrong_app(stage):
        calls.append(stage)
        return ET.fromstring('<hierarchy><node package="game.qualiarts.idolypride.local"/></hierarchy>')

    monkeypatch.setattr(qa, "capture", wrong_app)
    monkeypatch.setattr(qa, "adb", lambda *args, **kwargs: b"fresh screenshot")
    monkeypatch.setattr(qa_game_boot.time, "sleep", lambda delay: None)
    with pytest.raises(RuntimeError, match="not reached foreground"):
        qa.capture_server("server-after-game")
    assert len(calls) == 3

    def unrelated(stage):
        raise RuntimeError("adb command failed")

    monkeypatch.setattr(qa, "capture", unrelated)
    with pytest.raises(RuntimeError, match="adb command failed"):
        qa.capture_server("unrelated")
