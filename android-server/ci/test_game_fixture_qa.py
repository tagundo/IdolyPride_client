from types import SimpleNamespace
import json

import pytest

from qa_game_boot import GAME, game_launch_args, prepare_restarted_tutorial


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
