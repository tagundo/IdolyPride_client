"""Real encrypted Home.Enter previews agree with atomic ordinary claims."""
from idoly_local import lessons
from idoly_local.tutorial_qa import run_tutorial_continuation

from test_tutorial_continuation_application import continuation, connected


def test_post_tutorial_home_and_receive_share_one_persistent_clock(continuation, monkeypatch):
    schema, state, master, token, _fixtures = continuation
    now = [1800000000000]
    monkeypatch.setattr(lessons, "_now_ms", lambda: now[0])
    with connected(continuation) as invoke:
        run_tutorial_continuation(schema, invoke, master)
        before = state.snapshot("sandbox")
        home = invoke("/api.Home/Enter", schema.request_type("/api.Home/Enter")())
        assert home.lessonProgress == home.lessonInfo.lessonProgress
        assert home.lessonProgress.maxRewardTime - home.lessonProgress.lastReceiveTime == 43200000
        assert home.lessonProgress.rewardGoldAmount == 0
        assert state.snapshot("sandbox") == before
        saved_clock = state.lesson_progress("sandbox")
        now[0] += 29999
        pending = invoke("/api.Home/Enter", schema.request_type("/api.Home/Enter")())
        assert pending.lessonProgress == pending.lessonInfo.lessonProgress
        assert (pending.lessonProgress.rewardGoldAmount, pending.lessonProgress.rewardManagerExpAmount,
                pending.lessonProgress.rewardCardEnhanceItemAmount) == (10, 16, 6)
        assert state.snapshot("sandbox") == before and state.lesson_progress("sandbox") == saved_clock
        claimed = invoke("/api.Activity/ReceiveLessonReward", schema.request_type("/api.Activity/ReceiveLessonReward")())
        assert [(r.resourceType, r.resourceId, r.amount) for r in claimed.rewards] == [
            (8, "", 10), (14, "", 16), (1, "item-card_enhance", 6)]
        assert claimed.progress.lastReceiveTime == now[0] - 9999
        after = state.snapshot("sandbox")
        retry = invoke("/api.Activity/ReceiveLessonReward", schema.request_type("/api.Activity/ReceiveLessonReward")())
        assert not retry.rewards and state.snapshot("sandbox") == after
        assert retry.commonResponse.updatedData.user == claimed.commonResponse.updatedData.user
    assert state.authenticated(token, "sandbox")
