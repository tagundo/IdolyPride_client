"""Execute the VideoPlayer source texture backup extracted from shipping Bridge.

Native Unity allocation/decoder/GPU services are modeled; this does not claim
that an MP4 was exported or decoded by a device.
"""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_shipping_video_source_texture(tmp_path):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    camera = (ROOT / "client-presentation/native/mp4_camera_owner.hpp").read_text()
    for source, start, end, name in (
        (bridge, "// BEGIN_MP4_PRIVATE_VIDEO_FACTORY", "// END_MP4_PRIVATE_VIDEO_FACTORY", "private_video_factory.inc"),
        (bridge, "// BEGIN_MP4_VIDEO_TEXTURE_HOST", "// END_MP4_VIDEO_TEXTURE_HOST", "video_texture_host.inc"),
        (camera, "// BEGIN_ORIGINAL_CAMERA_STATE_PROFILE", "// END_ORIGINAL_CAMERA_STATE_PROFILE", "camera_profile.inc"),
    ):
        assert source.splitlines().count(start) == source.splitlines().count(end) == 1
        (tmp_path / name).write_text(source.split(start + "\n", 1)[1].split(end, 1)[0])
    compiler = shutil.which("c++")
    assert compiler
    binary = tmp_path / "video-source-texture"
    subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                    "-I", str(tmp_path), str(ROOT / "tests/mp4_video_texture_host_harness.cpp"),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True,
                   env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})
