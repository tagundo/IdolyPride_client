"""Continuation QA admits only the evidenced, complete achievement delta."""
import json
from pathlib import Path

import pytest

from idoly_local.schema import Schema
from idoly_local.tutorial_qa import _assert_enhancement_missions, run_tutorial_continuation
from test_card_level_missions import small_schema
from test_tutorial_continuation_application import continuation, connected


MISSION = "ms-normal-card_level_achievement"
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(params=("small", "client-6.1.1"))
def mission_case(request, tmp_path):
    if request.param == "small":
        schema = small_schema(tmp_path / "schema.pb")
    else:
        source = Path("data/protocol/idolypride-6.1.1.pb")
        if not source.is_file():
            pytest.skip("Optional actual descriptor is unavailable; synthetic contract still runs")
        schema = Schema.from_descriptor_set(source)
    master = tmp_path / "master"
    master.mkdir()
    (master / "Mission.json").write_text(json.dumps([{
        "id": MISSION, "progresses": [{"threshold": "5"}, {"threshold": "10"}]}]))
    before = schema.response_type("/api.User/Get")()
    before.cards.add(cardId="card-a", level=1, lastEnhanceTime=100)
    before.missions.add(missionId="unrelated", currentThreshold=9, progress=7,
                        statusType=1, lastUpdateTime=99).MergeFromString(UNKNOWN)
    saved = before.missions.add(missionId=MISSION, currentThreshold=5, progress=1,
                               statusType=1, lastUpdateTime=1234)
    saved.MergeFromString(UNKNOWN)
    after = type(before).FromString(before.SerializeToString())
    after.cards[0].level, after.cards[0].lastEnhanceTime = 2, 2345
    after.missions[1].progress, after.missions[1].lastUpdateTime = 2, 2345
    response = schema.response_type("/api.Card/Enhance")()
    response.commonResponse.updatedData.missions.add().CopyFrom(after.missions[1])
    return before, after, response, master


def check(case):
    _assert_enhancement_missions(*case, "card-a")


def test_exact_delta_preserves_other_missions_order_and_unknown_fields(mission_case):
    check(mission_case)
    before, after, response, _master = mission_case
    assert UNKNOWN in after.missions[1].SerializeToString()
    assert before.missions[0] == after.missions[0]
    assert response.commonResponse.updatedData.missions[0] == after.missions[1]


@pytest.mark.parametrize("tamper", (
    "other-progress", "other-unknown", "missing-other", "reordered", "threshold",
    "receipt", "missing-unknown", "wrong-progress", "wrong-time", "missing-delta",
    "extra-delta", "wrong-delta", "duplicate-achievement", "new-mission"))
def test_unrelated_or_inexact_mission_changes_are_rejected(mission_case, tamper):
    before, after, response, _master = mission_case
    if tamper == "other-progress": after.missions[0].progress += 1
    elif tamper == "other-unknown": after.missions[0].DiscardUnknownFields()
    elif tamper == "missing-other": del after.missions[0]
    elif tamper == "reordered":
        rows = list(after.missions)
        after.ClearField("missions")
        for row in reversed(rows): after.missions.add().CopyFrom(row)
    elif tamper == "threshold": after.missions[1].currentThreshold = 10
    elif tamper == "receipt": after.missions[1].statusType = 4
    elif tamper == "missing-unknown": after.missions[1].DiscardUnknownFields()
    elif tamper == "wrong-progress": after.missions[1].progress = 3
    elif tamper == "wrong-time": after.missions[1].lastUpdateTime = 2346
    elif tamper == "missing-delta": response.commonResponse.updatedData.ClearField("missions")
    elif tamper == "extra-delta": response.commonResponse.updatedData.missions.add().CopyFrom(after.missions[0])
    elif tamper == "wrong-delta": response.commonResponse.updatedData.missions[0].progress = 99
    elif tamper == "duplicate-achievement": before.missions.add().CopyFrom(before.missions[1])
    elif tamper == "new-mission": after.missions.add(missionId="unexpected")
    with pytest.raises(RuntimeError, match="mission|achievement"):
        check(mission_case)


@pytest.mark.parametrize("status", (2, 3, 4))
def test_claimed_or_unclaimed_receipt_and_future_timestamp_are_preserved(mission_case, status):
    before, after, response, _master = mission_case
    for value in (before, after):
        value.missions[1].currentThreshold = 10
        value.missions[1].statusType = status
        value.missions[1].lastUpdateTime = 1 << 62
    before.missions[1].progress, after.missions[1].progress = 10, 20
    after.cards[0].level = 20
    response.commonResponse.updatedData.missions[0].CopyFrom(after.missions[1])
    check(mission_case)


def test_crossing_threshold_only_allows_progress_to_clear(mission_case):
    before, after, response, _master = mission_case
    after.cards[0].level = after.missions[1].progress = 5
    after.missions[1].statusType = 2
    response.commonResponse.updatedData.missions[0].CopyFrom(after.missions[1])
    check(mission_case)
    after.missions[1].statusType = 3
    response.commonResponse.updatedData.missions[0].CopyFrom(after.missions[1])
    with pytest.raises(RuntimeError, match="unexpected mission state"):
        check(mission_case)


@pytest.mark.parametrize("absent", ("table", "saved"))
def test_old_payload_or_missing_saved_achievement_cannot_gain_delta(mission_case, absent):
    before, after, response, master = mission_case
    if absent == "table":
        (master / "Mission.json").unlink()
    else:
        del before.missions[1]
    after.ClearField("missions")
    for row in before.missions: after.missions.add().CopyFrom(row)
    response.commonResponse.updatedData.ClearField("missions")
    check(mission_case)
    after.missions.add(missionId=MISSION, currentThreshold=5, progress=2, statusType=1)
    with pytest.raises(RuntimeError, match="unexpected mission state"):
        check(mission_case)


def test_historical_highwater_has_no_delta_or_timestamp_change(mission_case):
    before, after, response, _master = mission_case
    before.missions[1].progress = 8
    after.missions[1].CopyFrom(before.missions[1])
    response.commonResponse.updatedData.ClearField("missions")
    check(mission_case)


@pytest.mark.parametrize("problem", ("late-unrelated", "retry-delta"))
def test_real_continuation_rejects_mission_tampering(continuation, problem):
    schema, state, master, *_ = continuation
    payload, *_ = state.snapshot("sandbox")
    user = schema.response_type("/api.User/Get").FromString(payload)
    user.missions.add(missionId="unrelated", currentThreshold=1, progress=0,
                      statusType=1, lastUpdateTime=100).MergeFromString(UNKNOWN)
    state.mutate_snapshot("sandbox", schema.fingerprint, lambda _payload: user.SerializeToString())
    with connected(continuation) as invoke:
        enhancements = 0

        def tampered(path, request):
            nonlocal enhancements
            result = invoke(path, request)
            if problem == "retry-delta" and path == "/api.Card/Enhance":
                enhancements += 1
                if enhancements == 2:
                    result.commonResponse.updatedData.missions.add().CopyFrom(user.missions[-1])
            if (problem == "late-unrelated" and path == "/api.User/Get"
                    and any(r.tutorialType == 1 and r.step == 150 for r in result.tutorials)):
                next(r for r in result.missions if r.missionId == "unrelated").progress = 1
            return result
        reason = "same-level retry emitted a mission delta" if problem == "retry-delta" else "post-enhancement continuation changed mission state"
        with pytest.raises(RuntimeError, match=reason):
            run_tutorial_continuation(schema, tampered, master)
