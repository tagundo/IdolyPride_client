import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools/capture_android_mv_performance.py"
SPEC = importlib.util.spec_from_file_location("capture_android_mv_performance", SOURCE)
mv = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mv
SPEC.loader.exec_module(mv)
PACKAGE = "game.example.client"
LAYER = f"SurfaceView[{PACKAGE}/Unity Activity] (BLAST) $value#9"


def latency(milliseconds, period=16_666_667):
    return str(period) + "\n" + "\n".join(f"1 {int(value * 1_000_000)} 3" for value in milliseconds)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeAdb:
    def __init__(self, samples, layers=None):
        self.samples = samples
        self.layers = layers
        self.index = 0
        self.calls = []

    def shell(self, *parts, timeout=2):
        self.calls.append((parts, timeout))
        if parts[-1] == "--list":
            value = self.layers(self.index) if self.layers else LAYER
            return mv.Reply(value)
        if "--latency" in parts:
            value = self.samples(self.index)
            self.index += 1
            return value if isinstance(value, mv.Reply) else mv.Reply(value)
        return mv.Reply(error="unsupported_command")


def capture(fake):
    clock = Clock()
    return mv.capture(fake, PACKAGE, LAYER, [LAYER], 20, clock, clock.sleep)


def test_actual_present_column_pending_duplicates_and_backward_rows():
    raw = f"16666667\n100 200 300\n0 0 0\n2 {mv.PENDING} 4\n3 190 5\n4 200 6\n5 250 7\nnot-supported\n"
    parsed = mv.parse_latency(raw)
    assert parsed["timestamps"] == [200, 250]
    assert parsed["period_ns"] == 16_666_667
    assert parsed["invalid_or_pending"] == 2
    assert parsed["duplicate_rows"] == parsed["backward_rows"] == parsed["malformed_rows"] == 1


def test_layer_selection_never_guesses_among_surfaceviews_or_package_prefixes():
    second = f"SurfaceView[{PACKAGE}/Other]#10"
    raw = f"{LAYER}\nBackground for {LAYER}\nSurfaceView[{PACKAGE}.other/Main]#3\nSome View[{PACKAGE}]\n{second}\n"
    selected = mv.candidates(raw, PACKAGE)
    assert selected == sorted([LAYER, second])
    assert mv.choose_layer(selected, None) is None
    assert mv.choose_layer(selected, LAYER) == LAYER
    assert mv.choose_layer(selected, "SurfaceView[private.other/Main]") is None
    assert mv.choose_layer([LAYER], None) == LAYER
    assert mv.choose_layer([LAYER], LAYER + "\n") is None


def test_remote_shell_command_is_fully_quoted_not_just_host_argv():
    commands = []

    def runner(argv, timeout):
        commands.append((argv, timeout))
        return mv.Reply("ok")

    adb = mv.Adb("192.0.2.1:5555", runner=runner)
    adb.shell("dumpsys", "SurfaceFlinger", "--latency", LAYER)
    argv, timeout = commands[0]
    assert argv[:4] == ["adb", "-s", "192.0.2.1:5555", "shell"]
    assert len(argv) == 5
    assert shlex.split(argv[4]) == ["dumpsys", "SurfaceFlinger", "--latency", LAYER]
    assert timeout == 2
    with pytest.raises(ValueError):
        mv.Adb("serial; unexpected-command")


def test_transport_output_limit_kills_only_the_owned_adb_client(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"123456789")
    os.close(write_fd)

    class OwnedProcess:
        stdout = os.fdopen(read_fd, "rb", buffering=0)
        returncode = None
        killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    owned = OwnedProcess()
    monkeypatch.setattr(mv.subprocess, "Popen", lambda *args, **kwargs: owned)
    monkeypatch.setattr(mv, "MAX_OUTPUT", 8)
    result = mv.bounded_command(["fake-adb-only"], 1)
    assert result.error == "output_limit" and result.text == ""
    assert owned.killed and owned.stdout.closed


def test_transport_timeout_is_bounded_and_kills_only_owned_client(monkeypatch):
    read_fd, write_fd = os.pipe()
    clock = Clock()

    class OwnedProcess:
        stdout = os.fdopen(read_fd, "rb", buffering=0)
        returncode = None
        killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    class SilentSelector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def register(self, *args):
            pass

        def get_map(self):
            return {read_fd: True}

        def select(self, timeout):
            clock.sleep(timeout)
            return []

    owned = OwnedProcess()
    monkeypatch.setattr(mv.subprocess, "Popen", lambda *args, **kwargs: owned)
    monkeypatch.setattr(mv.selectors, "DefaultSelector", SilentSelector)
    monkeypatch.setattr(mv.time, "monotonic", clock)
    try:
        result = mv.bounded_command(["fake-adb-only"], 1)
        assert result.error == "command_timeout" and result.text == ""
        assert owned.killed and owned.stdout.closed and clock.now == 1
    finally:
        os.close(write_fd)


def test_first_history_is_discarded_and_rolling_history_deduplicated():
    result = capture(FakeAdb(lambda i: latency([1000 + 20 * j for j in range(i, i + 4)])))
    assert result["status"] == "completed"
    segment = result["segments"][0]
    assert segment["baseline_discarded"] == 4
    assert segment["actual_present_ns"][0] == 1080_000_000
    assert len(segment["actual_present_ns"]) == len(set(segment["actual_present_ns"])) == 39
    assert segment["interval_ms"] == {"p50": 20.0, "p95": 20.0, "p99": 20.0, "max": 20.0}
    assert segment["intervals_over_50ms"] == 0
    assert result["requested_unity_fps"] is result["unity_render_resolution"] is result["unity_cpu_gpu_times"] is None
    assert result["first_new_present_poll_elapsed"] == 0.5
    assert result["last_new_present_poll_elapsed"] == 19.5
    assert result["stale_tail_seconds"] == 0.5


def test_partial_stale_tail_does_not_present_one_initial_interval_as_full_capture():
    fake = FakeAdb(lambda i: latency([10, 20, 30] if i == 0 else [10, 20, 30, 40, 50]))
    result = capture(fake)
    assert result["status"] == "partial"
    assert result["segments"][0]["interval_ms"]["p50"] == 10.0
    assert result["segments"][0]["interval_count"] == 1
    assert result["first_new_present_poll_elapsed"] == result["last_new_present_poll_elapsed"] == 0.5
    assert result["stale_tail_seconds"] == 19.5
    assert result["stale_tail_partial_threshold_seconds"] == 2.0
    assert any("partial" in warning and "not proof of zero FPS" in warning for warning in result["warnings"])


def test_stale_pending_or_permission_denied_are_unknown_not_zero_fps():
    stale = capture(FakeAdb(lambda i: latency([10, 20, 30])))
    assert stale["status"] == "unknown"
    assert stale["repeated_history_polls"] == 39
    assert stale["segments"][0]["interval_ms"]["p50"] is None
    assert stale["first_new_present_poll_elapsed"] is stale["last_new_present_poll_elapsed"] is None
    assert stale["stale_tail_seconds"] == 20.0
    pending = capture(FakeAdb(lambda i: f"16666667\n0 0 0\n1 {mv.PENDING} 1\n"))
    assert pending["status"] == "unknown" and pending["segments"] == []
    denied = capture(FakeAdb(lambda i: mv.Reply(error="permission_denied")))
    assert denied["status"] == "unknown" and denied["warnings"] == ["permission_denied"]


def test_refresh_reset_and_history_loss_do_not_create_spurious_long_intervals():
    def samples(i):
        if i < 2:
            return latency([10, 20, 30 + i])
        return latency([5000, 5010, 5020 + i], period=8_333_333)

    refresh = capture(FakeAdb(samples))
    assert len(refresh["segments"]) == 2
    assert refresh["segments"][1]["reason"] == "reported_refresh_changed"
    assert all(segment["intervals_over_50ms"] == 0 for segment in refresh["segments"])
    reset = capture(FakeAdb(lambda i: latency([10, 20, 30] if i < 2 else [1, 2, 3])))
    assert [s["reason"] for s in reset["segments"]] == ["initial_history_discarded", "timestamp_reset"]
    lost = capture(FakeAdb(lambda i: latency([10, 20, 30] if i < 2 else [5000, 5010, 5020])))
    assert lost["segments"][1]["reason"] == "history_overlap_lost"
    assert all(segment["intervals_over_50ms"] == 0 for segment in lost["segments"])


def test_layer_transition_stops_with_candidates_without_sampling_another_scene():
    replacement = f"SurfaceView[{PACKAGE}/Next Scene]#99"
    adb = FakeAdb(lambda i: latency([10, 20, 30 + i]), lambda i: LAYER if i < 3 else replacement)
    result = capture(adb)
    assert result["status"] == "layer_changed"
    assert result["segments"][0]["end_reason"] == "layer_changed"
    assert result["last_target_surfaceview_candidates"] == [replacement]
    assert adb.index == 3


def test_missing_refresh_metadata_is_not_carried_forward_as_known():
    def samples(i):
        raw = latency([10, 20, 30 + i])
        return raw if i < 2 else "\n".join(raw.splitlines()[1:])

    result = capture(FakeAdb(samples))
    assert len(result["segments"]) == 2
    assert result["segments"][1]["reason"] == "refresh_metadata_changed"
    assert result["segments"][1]["sf_reported_refresh_hz"] is None


def test_interval_over_50ms_is_literal_observation_and_percentiles_are_defined():
    result = mv.summarize({"actual_present_ns": [1, 20_000_001, 70_000_001, 130_000_001], "period_ns": None})
    assert result["intervals_over_50ms"] == 1
    assert result["interval_ms"] == {"p50": 50.0, "p95": 59.0, "p99": 59.8, "max": 60.0}
    assert result["sf_reported_refresh_hz"] is None


def test_context_stores_selected_public_fields_only_and_uses_read_only_commands():
    class ContextAdb:
        calls = []

        def shell(self, *parts):
            self.calls.append(parts)
            mapping = {("getprop", "ro.product.model"): "Measured Model",
                       ("getprop", "ro.build.version.sdk"): "37",
                       ("dumpsys", "display"): "mActiveModeId=7\nPrivate other display content",
                       ("dumpsys", "thermalservice"): "Thermal Status: 2\nOther sensor details",
                       ("cmd", "game", "list-modes", PACKAGE): f"{PACKAGE} current mode: 2",
                       ("cmd", "game", "list-configs", PACKAGE): "fps=60 private other text"}
            return mv.Reply(mapping[parts])

    adb = ContextAdb()
    result = mv.context(adb, PACKAGE, identity=True)
    assert result["model"]["value"] == "Measured Model"
    assert result["thermal"]["status"] == 2
    assert result["game_mode"]["reported_current_mode"] == 2
    assert result["game_configs"]["reported_fps_values"] == [60]
    assert "private" not in json.dumps(result).lower()
    assert all(call[:2] in [("getprop", "ro.product.model"), ("getprop", "ro.build.version.sdk"),
                           ("dumpsys", "display"), ("dumpsys", "thermalservice"), ("cmd", "game")]
               for call in adb.calls)


def test_list_cli_and_ambiguous_abort_never_collect_other_layers_or_context(monkeypatch, capsys):
    layers = f"{LAYER}\nSurfaceView[{PACKAGE}/Other]#2\nSurfaceView[unrelated.private/Screen]#1"
    fake = FakeAdb(lambda i: pytest.fail("must not sample"), lambda i: layers)
    monkeypatch.setattr(mv, "Adb", lambda *args: fake)
    assert mv.main(["--serial", "phone", "--package", PACKAGE, "--list-layers"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["target_surfaceview_candidates"]) == 2
    assert "unrelated.private" not in json.dumps(listed)
    assert mv.main(["--serial", "phone", "--package", PACKAGE]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "ambiguous_or_missing_layer"
    assert all(parts == ("dumpsys", "SurfaceFlinger", "--list") for parts, _ in fake.calls)


@pytest.mark.parametrize("extra", [["--duration", "0"], ["--duration", "nan"], ["--duration", "31"]])
def test_invalid_duration_rejected_before_adb(monkeypatch, extra):
    monkeypatch.setattr(mv, "Adb", lambda *args: pytest.fail("must not call adb"))
    with pytest.raises(SystemExit):
        mv.main(["--serial", "phone", "--package", PACKAGE, *extra])


def test_existing_output_and_invalid_package_rejected_before_adb(monkeypatch, tmp_path):
    monkeypatch.setattr(mv, "Adb", lambda *args: pytest.fail("must not call adb"))
    existing = tmp_path / "keep.json"
    existing.write_text("original")
    with pytest.raises(SystemExit):
        mv.main(["--serial", "phone", "--package", PACKAGE, "--output", str(existing)])
    with pytest.raises(SystemExit):
        mv.main(["--serial", "phone", "--package", PACKAGE + "; command"])
    assert existing.read_text() == "original"


def test_new_output_file_contains_only_the_target_report_and_is_never_overwritten(monkeypatch, tmp_path):
    fake = FakeAdb(lambda i: pytest.fail("no real capture"))
    monkeypatch.setattr(mv, "Adb", lambda *args: fake)
    monkeypatch.setattr(mv, "context", lambda *args, **kwargs: {"thermal": {"status": None}})
    monkeypatch.setattr(mv, "capture", lambda *args: {"status": "completed", "segments": []})
    destination = tmp_path / "new.json"
    args = ["--serial", "phone", "--package", PACKAGE, "--output", str(destination)]
    assert mv.main(args) == 0
    original = destination.read_bytes()
    document = json.loads(original)
    assert document["schema"] == 1 and document["package"] == PACKAGE
    assert document["layer"] == LAYER and document["capture"]["status"] == "completed"
    assert document["perfetto"] == "not_captured; see docs/mv-performance-audit.md"
    with pytest.raises(SystemExit):
        mv.main(args)
    assert destination.read_bytes() == original
    assert len(fake.calls) == 1
