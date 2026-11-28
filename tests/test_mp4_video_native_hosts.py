"""Execute shipping Video drain/history/private-Creator boundary hosts.

Unity/native decoder/graphics services are modeled. These sanitizer fixtures
exercise the shipping host logic, not actual-device export or decoded MP4 QA.
"""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("host,cases", [("native", 8), ("history", 9), ("creator", 8)])
def test_shipping_video_native_hosts(tmp_path, platform, host, cases):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    camera = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    blocks = {
        "private_video_factory.inc": (bridge, ["MP4_PRIVATE_VIDEO_FACTORY"]),
        "camera_profile.inc": (camera, ["ORIGINAL_CAMERA_STATE_PROFILE"]),
        "video_frame.inc": (camera, ["MP4_VIDEO_FRAME"]),
        "video_texture_host.inc": (bridge, ["MP4_VIDEO_TEXTURE_HOST"]),
        "video_image_host.inc": (bridge, ["MP4_VIDEO_IMAGE_HOST"]),
        "video_native_pins.inc": (bridge, ["MP4_VIDEO_NATIVE_PINS"]),
        "video_native_host.inc": (bridge, ["MP4_VIDEO_NATIVE_HOST"]),
        "video_history_host.inc": (bridge, ["MP4_VIDEO_HISTORY_HOST"]),
        "video_source_pause.inc": (bridge, ["MP4_VIDEO_SOURCE_QUIESCE_HOST"]),
        "video_creator_pins.inc": (bridge, ["MP4_VIDEO_CREATOR_PINS"]),
        "video_creator_host.inc": (bridge, ["MP4_VIDEO_CREATOR_HOST", "MP4_VIDEO_PRIVATE_STEP_HOST"]),
    }
    for name, (source, markers) in blocks.items():
        extracted = []
        for marker in markers:
            start, end = "// BEGIN_" + marker, "// END_" + marker
            assert source.splitlines().count(start) == source.splitlines().count(end) == 1
            extracted.append(source.split(start + "\n", 1)[1].split(end, 1)[0])
        (tmp_path / name).write_text("\n".join(extracted))
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / ("video-" + host)
    flags = ["-DIDOLY_DARWIN_BRIDGE=1"] if platform == "ios" else []
    subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                    *flags, "-I", str(tmp_path), str(ROOT / f"tests/mp4_video_{host}_host_harness.cpp"),
                    "-o", str(binary)], check=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True,
                            env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})
    assert result.stdout.startswith(str(cases) + " ")
