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
        if clock.now == 103:
            return frame(clock.now, prefix, phrase=None, raw_loading_detected=True)
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    action = qa.tap_observed_title_reentry()
    assert [when for when, args in inputs] == [100, 124]
    assert action["action_number"] == 2
    assert action["returned_after_loading_observation"]["captured_at"] == 103
    assert action["returned_after_loading_observation"]["phrase"] is None
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
        if clock.now == 103:
            return frame(clock.now, prefix, phrase=None, raw_loading_detected=True)
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
            return frame(clock.now, prefix, phrase=None, raw_loading_detected=True)
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



def test_same_initial_title_cannot_consume_second_tap_without_positive_loading(title_qa, monkeypatch):
    qa, clock, inputs = title_qa
    monkeypatch.setattr(qa, "_observe_title_frame", lambda prefix, **kwargs: frame(clock.now, prefix))
    assert qa.tap_observed_title_reentry() is None
    assert clock.now == 280
    assert [when for when, args in inputs] == [100]
    result = json.loads((qa.artifacts / "title-reentry-result.json").read_text())
    assert result["busy_phase_observed"] is False
    assert "No positive foreground loading" in result["reason"]


@pytest.mark.parametrize("invalid_busy", [
    {"foreground_game": False}, {"raw_ocr_has_words": False},
    {"captured_at": 100}, {"source_image": "first-title.png"},
    {"raw_loading_detected": False},
])
def test_only_fresh_positive_foreground_loading_can_arm_returned_title(title_qa, monkeypatch, invalid_busy):
    qa, clock, inputs = title_qa

    def observe(prefix, **kwargs):
        if clock.now == 103:
            return frame(clock.now, prefix, **{**{"phrase": None, "raw_loading_detected": True}, **invalid_busy})
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    assert qa.tap_observed_title_reentry() is None
    assert len(inputs) == 1



def test_initial_title_then_real_busy_then_returned_title_is_ordered(title_qa, monkeypatch):
    qa, clock, inputs = title_qa

    def observe(prefix, **kwargs):
        # More than 50s of stable initial title is not reentry evidence.
        if 151 <= clock.now < 160:
            return frame(clock.now, prefix, phrase=None, raw_loading_detected=True)
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    action = qa.tap_observed_title_reentry()
    assert [when for when, args in inputs] == [100, 163]
    assert action["returned_after_loading_observation"]["captured_at"] == 157
    assert action["stable_previous_observation"]["captured_at"] == 160
    assert action["captured_at"] == 163



def test_ocr_absence_after_initial_title_does_not_infer_loading(title_qa, monkeypatch):
    qa, clock, inputs = title_qa

    def observe(prefix, **kwargs):
        if 130 <= clock.now < 160:
            return {"phrase": None, "captured_at": clock.now, "source_image": prefix + ".png",
                    "foreground_game": True, "raw_ocr_has_words": False, "raw_loading_detected": False}
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    assert qa.tap_observed_title_reentry() is None
    assert len(inputs) == 1



def test_frame_records_raw_loading_without_a_masked_title_phrase(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import struct

    qa = boot.GameQA("adb", "emulator-disposable", tmp_path)
    qa.started = 0
    raw_loading = TSV_HEADER + "5\t1\t1\t1\t1\t1\t5\t5\t40\t20\t2.0\tLOADING...\n"
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1080, 2280)
    calls = []
    monkeypatch.setattr(boot.shutil, "which", lambda name: "/fake/" + name)
    monkeypatch.setattr(qa, "adb", lambda *args, **kwargs: png if kwargs.get("binary") else
                        "mResumedActivity: " + boot.GAME + "/.Activity")

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "tesseract":
            return SimpleNamespace(stdout=TSV_HEADER if "ocr-mask" in command[1] else raw_loading)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(boot.subprocess, "run", run)
    observation = qa._observe_title_frame("busy-no-title", inspect_loading=True)
    assert observation["phrase"] is None
    assert observation["raw_loading_detected"] is True
    assert observation["foreground_game"] is True
    assert len([call for call in calls if call[0] == "tesseract"]) == 2
    assert json.loads((tmp_path / "busy-no-title.observation.json").read_text()) == observation



def test_first_title_tap_also_requires_phrase_and_raw_loading_veto(tmp_path, monkeypatch):
    clock = Clock()
    qa = boot.GameQA("adb", "emulator-disposable", tmp_path)
    qa.started = 0
    inputs = []
    monkeypatch.setattr(boot.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(boot.time, "sleep", clock.sleep)
    monkeypatch.setattr(qa, "adb", lambda *args, **kwargs: inputs.append((clock.now, args)) or "")

    def observe(prefix, *, inspect_loading):
        assert inspect_loading
        if clock.now == 100:
            return frame(clock.now, prefix, phrase=None, raw_loading_detected=True)
        if clock.now == 105:
            return frame(clock.now, prefix, raw_loading_detected=True)
        return frame(clock.now, prefix)

    monkeypatch.setattr(qa, "_observe_title_frame", observe)
    assert qa.tap_observed_title(timeout=20)["captured_at"] == 110
    assert [when for when, args in inputs] == [110]


@pytest.mark.parametrize("timeout", [0, -1, 180.01, 300])
def test_reentry_window_cannot_exceed_180_seconds_or_be_nonpositive(title_qa, timeout):
    qa, clock, inputs = title_qa
    with pytest.raises(ValueError, match="at most 180"):
        qa.tap_observed_title_reentry(timeout=timeout)
    assert len(inputs) == 1
