"""Shared preview lifecycle plus the original Android Bind/pin integration."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent


def test_common_preview_helper_preserves_original_and_user_visibility(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    # This existing semantic fixture now includes the compatibility wrapper,
    # which aliases the SAME source-bound class used by the Android bridge.
    fixture = NATIVE.parent / "ios/tests/photography_ui_test.cpp"
    executable = tmp_path / "shared-preview-ui"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(fixture),
                    "-o", str(executable)], check=True, capture_output=True, timeout=20)
    subprocess.run([str(executable)], check=True, capture_output=True, timeout=5)
    wrapper = (NATIVE.parent / "ios/photography_ui.hpp").read_text()
    assert '#include "../native/photography_ui.hpp"' in wrapper
    assert "namespace ios_photography_ui = photography_ui;" in wrapper


def test_android_preview_original_fields_and_bind_are_source_bound():
    profile = json.loads((NATIVE / "profile.json").read_text())
    entries = profile["aliases"]
    assert len(entries) == 149
    for name, rva, result, parameters in [
        ("preview_ui_bind", "0x5657df0", "System.Void", 0),
        ("preview_ui_get", "0x5657a7c", "System.Boolean", 0),
        ("preview_ui_set", "0x5657ac4", "System.Void", 1),
    ]:
        entry = entries[name]
        assert entry["rva"] == rva and not entry["is_static"]
        assert entry["return_type"]["class"] == result
        assert len(entry["parameters"]) == parameters
    assert entries["preview_ui_set"]["parameters"][0]["type"]["class"] == "System.Boolean"
    policy = profile["preview_default_off"]
    assert (policy["presenter_model_offset"], policy["model_property_offset"], policy["model_end_offset"]) == (0x40, 0x10, 0x18)
    text = (NATIVE / "bridge.cpp").read_text()
    pre_profile = text.split('#ifdef IDOLY_DARWIN_BRIDGE\n#include "ios_profile.hpp"', 1)[0]
    assert '#include "photography_ui.hpp"' in pre_profile
    bind = text.split("void preview_ui_bind_hook(", 1)[1].split("\n}\n", 1)[0]
    assert "#else" in bind and "ready.load(std::memory_order_acquire) && game_call(true)" in bind
    assert "HOOK(preview_ui_bind,preview_ui_bind_hook,preview_ui_bind_original)" in text
    assert "!rotation::ready_for_publish() || !preview_ui.ready() || !korean_fallback.ready() || !korean_list_factory.ready() || !wardrobe_lifecycle.ready()" in text
    assert "|| !wardrobe_exit_tracker.ready()" in text
    load = text.split("void load_calls() {", 1)[1].split("\n#undef CALL", 1)[0]
    assert load.index("#endif", load.index("CALL(mv_ui_hide")) < load.index("preview_ui_calls.weak_new")
    assert "CALL(preview_ui_calls.ui_get, preview_ui_get); CALL(preview_ui_calls.ui_set, preview_ui_set);" in load
    builder = (NATIVE.parent / "ios/build_native.py").read_text()
    assert "sorted((here.parent/'native').glob('*.hpp'))" in builder
