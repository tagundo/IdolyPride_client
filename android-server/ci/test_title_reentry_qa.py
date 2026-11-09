import json

import pytest

import qa_game_boot as boot


TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
TITLE_TSV = TSV_HEADER + (
    "5\t1\t1\t1\t1\t1\t339\t1979\t104\t39\t96.541397\tTAP\n"
    "5\t1\t1\t1\t1\t2\t467\t1956\t272\t110\t91.106514\tTOSTART\n")


def frame(when, name, **changes):
    result = {**boot.observed_title(TITLE_TSV, 1080, 2280), "captured_at": when,
              "source_image": name + ".png", "image_size": [1080, 2280],
              "foreground_game": True, "raw_ocr_has_words": True, "raw_loading_detected": False}
    result.update(changes)
    return result


def test_exact_title_and_loading_from_raw_frame_are_separate_checks():
    assert boot.observed_title(TITLE_TSV, 1080, 2280)["point"] == [539, 2011]
    assert boot.raw_loading_state(TITLE_TSV) == {"raw_ocr_has_words": True, "raw_loading_detected": False}
    loading = TITLE_TSV + "5\t1\t2\t1\t1\t1\t5\t5\t40\t20\t2.0\tLOADING...\n"
    assert boot.observed_title(loading, 1080, 2280)
    assert boot.raw_loading_state(loading)["raw_loading_detected"] is True
    split = TSV_HEADER + "".join(
        f"5\t1\t1\t1\t1\t{i}\t5\t5\t40\t20\t50\t{text}\n"
        for i, text in enumerate(("LOA", "DING"), 1))
    assert boot.raw_loading_state(split)["raw_loading_detected"] is True
    assert boot.raw_loading_state(TSV_HEADER)["raw_ocr_has_words"] is False
    assert boot.observed_title(TITLE_TSV.replace("TOSTART", "TOSTOP"), 1080, 2280) is None


@pytest.mark.parametrize("changes", [
    {"captured_at": 102.99}, {"source_image": "first.png"}, {"foreground_game": False},
    {"raw_ocr_has_words": False}, {"raw_loading_detected": True}, {"image_size": [720, 1280]},
    {"bounds": [400, 1956, 800, 2066]}, {"phrase": "START"},
])
def test_second_title_requires_two_fresh_stable_nonloading_foreground_frames(changes):
    first, second = frame(100, "first"), frame(103, "second", **changes)
    assert not boot.stable_title_pair(first, second)


def test_stable_title_pair_accepts_three_second_gap_and_current_bounds():
    assert boot.stable_title_pair(frame(100, "first"), frame(103, "second", bounds=[340, 1957, 740, 2067]))
    assert not boot.stable_title_pair(None, frame(103, "second"))


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        assert delay >= 0
        self.now += delay


@pytest.fixture
def title_qa(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(boot.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(boot.time, "sleep", clock.sleep)
    qa = boot.GameQA("adb", "emulator-disposable", tmp_path)
    qa.started = 0
    qa.max_title_taps = 2
    inputs = []
    monkeypatch.setattr(qa, "adb", lambda *args, **kwargs: inputs.append((clock.now, args)) or "")
    qa._perform_title_action(frame(clock.now, "first-title"))
    return qa, clock, inputs


def test_second_title_waits_twenty_seconds_then_two_fresh_frames_and_preserves_first_record(title_qa, monkeypatch):
    qa, clock, inputs = title_qa
    first_record = (qa.artifacts / "observed-title-action.json").read_bytes()

    def observe(prefix, *, inspect_loading):
        assert inspect_loading
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    action = qa.tap_observed_title_reentry()
    assert [when for when, args in inputs] == [100, 124]
    assert action["action_number"] == 2
    assert action["captured_at"] - action["stable_previous_observation"]["captured_at"] == 3
    assert action["stable_previous_observation"]["captured_at"] >= 120
    assert (qa.artifacts / "observed-title-action.json").read_bytes() == first_record
    assert (qa.artifacts / "observed-title-action-1.json").read_bytes() == first_record
    assert len(json.loads((qa.artifacts / "observed-title-actions.json").read_text())) == 2
    with pytest.raises(RuntimeError, match="limit was reached"):
        qa._perform_title_action(frame(clock.now, "third-title"))
    with pytest.raises(RuntimeError, match="one completed action"):
        qa.tap_observed_title_reentry()


def test_bad_second_frame_resets_stability_instead_of_using_old_candidate(title_qa, monkeypatch):
    qa, clock, inputs = title_qa

    def observe(prefix, *, inspect_loading):
        return frame(clock.now, prefix, foreground_game=clock.now != 124)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    action = qa.tap_observed_title_reentry()
    assert inputs[-1][0] == 130
    assert action["stable_previous_observation"]["captured_at"] == 127


@pytest.mark.parametrize("blocked", ["absent", "loading", "wrong_foreground", "empty_raw_ocr"])
def test_optional_reentry_absence_or_blockers_do_not_fail_or_tap(title_qa, monkeypatch, blocked):
    qa, clock, inputs = title_qa

    def observe(prefix, *, inspect_loading):
        if blocked == "absent":
            return None
        return frame(clock.now, prefix, raw_loading_detected=blocked == "loading",
                     foreground_game=blocked != "wrong_foreground",
                     raw_ocr_has_words=blocked != "empty_raw_ocr")

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    assert qa.tap_observed_title_reentry() is None
    assert clock.now == 280
    assert len(inputs) == 1
    report = json.loads((qa.artifacts / "title-reentry-result.json").read_text())
    assert report["performed"] is False
    assert report["timeout_seconds"] == report["waited_seconds"] == 180


def test_observed_late_title_reentry_after_full_master_download_can_receive_second_tap(title_qa, monkeypatch):
    qa, clock, inputs = title_qa

    def observe(prefix, *, inspect_loading):
        # The actual probe was still loading within 90s and showed title again
        # roughly 110..140s after the first action. Do not infer a title earlier.
        if clock.now < 220:
            return None
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    action = qa.tap_observed_title_reentry()
    assert [when for when, args in inputs] == [100, 223]
    assert action["stable_previous_observation"]["captured_at"] == 220
    assert action["captured_at"] == 223
    assert action["performed_seconds"] - qa.title_actions[0]["performed_seconds"] == 123
    report = json.loads((qa.artifacts / "title-reentry-result.json").read_text())
    assert report["performed"] is True
    assert report["timeout_seconds"] == 180


def test_second_title_is_disabled_by_default(title_qa):
    qa, clock, inputs = title_qa
    del qa.max_title_taps
    with pytest.raises(RuntimeError, match="opt-in max-title-taps=2"):
        qa.tap_observed_title_reentry()
    assert len(inputs) == 1
