"""Exercise native snapshot code; Unity/device execution is not simulated."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent / "bridge.cpp"
FIELDS = {"schema", "state", "actual_mode", "graphics_api", "callback_tid", "observations",
          "sample_age_ms", "cpu_frame_ms", "gpu_frame_ms", "timing_age_ms"}


def test_render_probe_states_throttle_and_snapshot_freshness(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    text = BRIDGE.read_text()
    start, end = "// BEGIN_READ_ONLY_RENDER_PROBE\n", "// END_READ_ONLY_RENDER_PROBE"
    assert text.count(start) == text.count(end) == 1
    fragment = text.split(start, 1)[1].split(end, 1)[0]
    (tmp_path / "render_probe_fragment.hpp").write_text(fragment)
    output = tmp_path / "render-probe-test"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(tmp_path),
                    str(HERE / "render_probe_test.cpp"), "-o", str(output)],
                   check=True, capture_output=True, timeout=20)
    result = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=5)
    rows = {}
    for line in result.stdout.splitlines():
        name, raw = line.split("\t", 1)
        assert len(raw.encode()) < 512
        row = rows[name] = json.loads(raw)
        assert set(row) == FIELDS and row["schema"] == 1
        assert row["cpu_frame_ms"] is row["gpu_frame_ms"] is row["timing_age_ms"] is None
        assert 0 <= row["observations"] <= (1 << 63) - 1
        if row["state"] in {"waiting", "init_failed"}:
            assert row["observations"] == 0
            assert all(row[field] is None for field in FIELDS - {"schema", "state", "observations"})
        else:
            assert row["observations"] >= 1
            if row["state"] == "observed":
                assert 0 <= row["actual_mode"] <= 5
                assert 0 <= row["graphics_api"] <= 255
                assert 0 < row["callback_tid"] <= (1 << 31) - 1
                assert 0 <= row["sample_age_ms"] <= (1 << 63) - 1
            else:
                assert row["state"] == "unsupported" and row["actual_mode"] is None
    assert rows["waiting"]["state"] == "waiting"
    assert rows["first"]["actual_mode"] == 2 and rows["first"]["sample_age_ms"] == 250
    assert rows["first"]["observations"] == 1
    assert rows["direct"]["actual_mode"] == 0 and rows["direct"]["observations"] == 2
    assert rows["direct"]["sample_age_ms"] == 2000
    assert rows["unknown_mode"]["actual_mode"] is None
    assert rows["unknown_mode"]["graphics_api"] == 21
    assert rows["unknown_api"]["graphics_api"] is None
    assert rows["missing_tid"]["callback_tid"] is None
    assert rows["invalid_tid"]["callback_tid"] is None
    assert rows["age_unknown"]["sample_age_ms"] is None
    assert rows["clock_regressed"]["sample_age_ms"] is None
    assert rows["raw_api"]["actual_mode"] == 5 and rows["raw_api"]["graphics_api"] == 255
    assert rows["maximum_age"]["sample_age_ms"] == (1 << 63) - 1
    assert rows["init_failed"]["state"] == "init_failed"
    assert [rows[f"mode_{mode}"]["actual_mode"] for mode in range(6)] == list(range(6))


def test_probe_is_post_original_only_and_jni_does_not_call_unity():
    text = BRIDGE.read_text()
    body = text.split("void quality_update_hook(", 1)[1].split("\n}\n", 1)[0]
    assert body.count("sample_render_probe();") == 2
    for match in re.finditer(r"sample_render_probe\(\);", body):
        assert body.rfind("quality_update_original(self, method);", 0, match.start()) >= 0
    no_config = body.split("if (!has) {", 1)[1].split("return;", 1)[0]
    assert no_config.index("quality_update_original") < no_config.index("sample_render_probe")
    sampler = text.split("void sample_render_probe() {", 1)[1].split("\n}\n", 1)[0]
    assert "ready.load(std::memory_order_acquire)" in sampler and "!game_call(false)" in sampler
    assert sampler.index("if (!due) return;") < sampler.index("rendering_mode_get(nullptr)")
    assert "static_cast<int64_t>(gettid())" in sampler
    assert text.count("rendering_mode_get(nullptr)") == text.count("graphics_api_get(nullptr)") == 1
    jni = text.split("NativePresentation_renderProbeStatus(", 1)[1].split("\n}\n", 1)[0]
    assert "char json[512]" in jni and "render_probe_status_json" in jni
    assert "sample_render_probe" not in jni and "rendering_mode_get" not in jni
    formatter = text.split("void render_probe_status_json(", 1)[1].split("\n}\n", 1)[0]
    assert "snapshot()" in formatter and "render_probe_monotonic_ms()" in formatter
    assert "_get(" not in formatter and "game_call" not in formatter


def test_android_probe_and_panorama_call_pins_keep_hook_count():
    profile = json.loads((HERE.parent / "profile.json").read_text())
    aliases = profile["aliases"]
    assert len(aliases) == 96
    assert aliases["rendering_mode"]["rva"] == "0x8f8826c"
    assert aliases["graphics_api"]["rva"] == "0x8f8812c"
    for name in ("rendering_mode", "graphics_api"):
        assert aliases[name]["is_static"] and aliases[name]["parameters"] == []
        assert aliases[name]["mode"] == "CALL"
    # Android360 projection/UI support adds CALLs, without changing the probe
    # ABI or adding hooks to any of these getter/transform/model functions.
    for name in ("aspect_reset", "ui_component_transform", "ui_gameobject_transform",
                 "ui_transform_point", "ui_inverse_transform_point", "pano_ui_get", "pano_ui_set"):
        assert name in aliases
    text = BRIDGE.read_text()
    hooks = re.findall(r"HOOK\((\w+),", text)
    assert len(hooks) - 1 == 35  # Exclude the HOOK macro's own entry parameter.
    assert "rendering_mode" not in hooks and "graphics_api" not in hooks
    header = (HERE.parent / "profile.hpp").read_text()
    entries = set(re.findall(r"inline constexpr Entry (\w+)\{", header))
    assert entries == set(aliases)
