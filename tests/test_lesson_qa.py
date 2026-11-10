"""Check native QA's independent reward oracle and persistence assertions."""
import json

import pytest

from idoly_local import lesson_qa as qa
from test_lessons import game, schema, progression_game


@pytest.fixture
def native_flow(game, monkeypatch):
    provider, state, master, rows, token, clock = game
    def finish(raw):
        snapshot = provider.schema.response_type("/api.User/Get").FromString(raw)
        snapshot.user.tutorialClearedTime = 1790000000000
        # One base step must cross the public ManagerLevel threshold 115.
        snapshot.user.managerExp, snapshot.user.managerLevel = 110, 2
        return snapshot.SerializeToString() + b"\x80\x4b\x7b"
    state.mutate_snapshot("player", provider.schema.fingerprint, finish)
    elapsed = [0.0]
    calls = []

    def sleep(seconds):
        elapsed[0] += seconds
        clock[0] += round(seconds * 1000)

    def invoke(path, request):
        calls.append(path)
        if path == "/api.User/Get":
            return provider.schema.response_type(path).FromString(state.snapshot("player")[0])
        if path == "/api.Home/Enter":
            result = provider.schema.response_type(path)()
            result.lessonProgress.CopyFrom(provider.progress("area-main-001"))
            result.lessonInfo.lessonProgress.CopyFrom(result.lessonProgress)
            return result
        assert path == "/api.Activity/ReceiveLessonReward"
        return provider.schema.response_type(path).FromString(provider.handle(path, request.SerializeToString()))

    monkeypatch.setattr(qa.time, "sleep", sleep)
    monkeypatch.setattr(qa.time, "monotonic", lambda: elapsed[0])
    return provider, state, master, invoke, calls, elapsed, clock


def test_native_oracle_observes_ten_seconds_base_delta_retry_and_shared_home_clock(native_flow):
    provider, state, master, invoke, calls, elapsed, clock = native_flow
    receipt = qa.run_ordinary_lesson_claim(provider.schema, invoke, master)
    assert receipt["waited_milliseconds"] == 10100 and receipt["elapsed_steps"] == 1
    assert (receipt["gold_delta"], receipt["manager_exp_delta"], receipt["enhance_item_delta"]) == (5, 8, 3)
    assert receipt["resource_totals"] == {"gold": 12, "manager_exp": 118, "manager_level": 3,
        "enhance_items": 103, "lifetime_gold": 10}
    assert all(receipt[key] is True for key in ("immediate_retry_no_grant", "home_shared_clock",
        "home_previews_preserve_snapshot", "unrelated_snapshot_preserved"))
    receives = [index for index, path in enumerate(calls) if path == "/api.Activity/ReceiveLessonReward"]
    assert receives[1] == receives[0] + 1
    qa.assert_ordinary_lesson_snapshot(provider.schema, state.snapshot("player")[0], receipt)
    qa.assert_ordinary_lesson_progress(provider.schema, state.lesson_progress("player")[0], receipt)
    clock[0] += 30000
    # A read-only post-restart Home preview may show newly pending amounts.
    qa.assert_ordinary_lesson_home(provider.schema, invoke("/api.Home/Enter", None), receipt)
    qa.assert_ordinary_lesson_snapshot(provider.schema, state.snapshot("player")[0], receipt)
    assert "local-" not in json.dumps(receipt)


def test_native_oracle_cannot_claim_real_wait_if_the_clock_did_not_advance(native_flow, monkeypatch):
    provider, _state, master, invoke, calls, _elapsed, _clock = native_flow
    monkeypatch.setattr(qa.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="complete real ten-second"):
        qa.run_ordinary_lesson_claim(provider.schema, invoke, master)
    assert "/api.Activity/ReceiveLessonReward" not in calls


@pytest.mark.parametrize("bug", ("home-clock-reset", "bad-base-reward", "retry-double-grant",
                                  "campaign", "unrelated-user-change"))
def test_native_oracle_rejects_false_clock_reward_or_preservation_evidence(native_flow, bug):
    provider, _state, master, real, _calls, _elapsed, _clock = native_flow
    counts = {}

    def invoke(path, request):
        counts[path] = counts.get(path, 0) + 1
        response = real(path, request)
        if bug == "home-clock-reset" and path == "/api.Home/Enter" and counts[path] == 2:
            response.lessonProgress.lastReceiveTime += 1000
            response.lessonProgress.maxRewardTime += 1000
            response.lessonInfo.lessonProgress.CopyFrom(response.lessonProgress)
        if path == "/api.Activity/ReceiveLessonReward":
            if bug == "bad-base-reward" and counts[path] == 1:
                response.rewards[0].amount += 5
            if bug == "retry-double-grant" and counts[path] == 2:
                response.rewards.add(resourceType=8, amount=5)
            if bug == "campaign":
                response.campaignDropRewards.add(resourceType=8, amount=1)
        if bug == "unrelated-user-change" and path == "/api.User/Get" and counts[path] >= 4:
            response.user.name = "Unexpected renamed account"
        return response

    with pytest.raises(RuntimeError):
        qa.run_ordinary_lesson_claim(provider.schema, invoke, master)


def test_native_persistence_guards_reject_lost_resources_or_rebased_clock(native_flow):
    provider, state, master, invoke, _calls, _elapsed, _clock = native_flow
    receipt = qa.run_ordinary_lesson_claim(provider.schema, invoke, master)
    changed = provider.schema.response_type("/api.User/Get").FromString(state.snapshot("player")[0])
    changed.items[0].amount -= 3
    with pytest.raises(RuntimeError, match="claimed snapshot"):
        qa.assert_ordinary_lesson_snapshot(provider.schema, changed, receipt)
    progress = type(provider.schema.response_type("/api.Activity/ReceiveLessonReward")().progress).FromString(
        state.lesson_progress("player")[0])
    progress.lastReceiveTime += 10000
    progress.maxRewardTime += 10000
    with pytest.raises(RuntimeError, match="persistent lesson clock"):
        qa.assert_ordinary_lesson_progress(provider.schema, progress, receipt)
