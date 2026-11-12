"""Run real bridge refresh/rejection functions with bounded scene/lens mocks."""
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent / "bridge.cpp"


def test_native_projection_refresh_and_failed_retry_sequences(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    source = BRIDGE.read_text()
    for marker, header in [("VERIFIED_PROJECTION_REFRESH", "verified_projection_refresh.hpp"),
                           ("PROJECTION_REJECTION_RETRY", "projection_rejection_retry.hpp")]:
        begin, end = f"// BEGIN_{marker}\n", f"// END_{marker}"
        assert source.count(begin) == source.count(end) == 1
        (tmp_path / header).write_text(source.split(begin, 1)[1].split(end, 1)[0])
    output = tmp_path / "native-projection-retry"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                    "-I", str(tmp_path), "-I", str(HERE.parent),
                    str(HERE / "projection_retry_test.cpp"), "-o", str(output)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(output)], check=True, capture_output=True, timeout=5)


def test_retry_gates_and_original_lifecycle_order_are_wired():
    text = BRIDGE.read_text()
    apply = text.split("bool apply_photography(", 1)[1].split("\n}\n", 1)[0]
    assert apply.index("synchronize_photo_camera(controller, camera)") < apply.index("if (!photo.base_known)")
    assert apply.index("projection_rejected_for(config)") < apply.index("rebuild(controller)")
    assert "!desktop_host" not in apply
    refresh = text.split("// BEGIN_VERIFIED_PROJECTION_REFRESH", 1)[1].split("// END_VERIFIED_PROJECTION_REFRESH", 1)[0]
    assert "desktop_host" not in refresh
    assert "ScopedCleanup automatic(reset_automatic_aspect, camera);" in refresh
    assert refresh.index("ScopedCleanup automatic(") < refresh.index("camera_aspect_set_original(camera, original_aspect")
    assert "frustum_contains(fitted, photo.original_frustum)" in refresh
    load = text.split("void load_calls() {", 1)[1].split("\n#undef CALL", 1)[0]
    aspect_calls = load.index("CALL(camera_aspect_set_original, aspect_set); CALL(camera_aspect_reset, aspect_reset);")
    assert aspect_calls < load.index("#ifdef IDOLY_DARWIN_BRIDGE")
    render = text.split("void rt_hook(", 1)[1].split("\n}\n", 1)[0]
    assert render.index("previous_camera = photo.camera.get(true)") < render.index("photo.camera.set(camera)")
    assert "if (changed) clear_projection_rejection();" in render
    update = text.split("void photo_update(", 1)[1].split("\n}\n", 1)[0]
    assert "clear_projection_rejection()" not in update  # Repeated same-owner updates must not freshen a failure.
    reset = text.split("void photo_reset(", 1)[1].split("\n}\n", 1)[0]
    assert reset.index("clear_photography();") < reset.index("original(self, method);")


def test_android_panorama_layout_and_session_visibility_are_wired():
    text = BRIDGE.read_text()
    common, _platform_profile = text.split('#ifdef IDOLY_DARWIN_BRIDGE\n#include "ios_profile.hpp"', 1)
    assert '#include "panorama_ui_edges.hpp"' in common
    load = text.split("void load_calls() {", 1)[1].split("\n#undef CALL", 1)[0]
    assert load.index("#endif", load.index("CALL(mv_ui_hide")) < load.index("panorama_api.weak_new")
    for alias in ("ui_component_transform", "ui_gameobject_transform", "ui_transform_point",
                  "ui_inverse_transform_point", "pano_ui_get", "pano_ui_set"):
        assert alias in load
    ui = text.split("void update_panorama_ui() {", 1)[1].split("\n}\n", 1)[0]
    assert "#else\n    if (!ready.load(std::memory_order_acquire) || !game_call()) return;" in ui
    assert ui.index("panorama_ui.begin_session(owner)") < ui.index("configuration().expand_photography")
    assert "panorama_ui.update(owner, photo.viewport_parent.get(true)" in ui
