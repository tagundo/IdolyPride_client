"""Optional immutable-original audit of the actual shipping origin bindings."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def originals():
    path = Path(os.environ.get("IDOLY_MP4_ORIGINALS", "/workspace/shared/idoly-sdk-cache-analysis"))
    if not all((path / name).is_file() for name in (
            "android-metadata.dat", "android-native.so", "ios-metadata.dat", "ios-native.bin",
            "mp4-android-analysis/libunity.so")):
        pytest.skip("Immutable original images are optional audit inputs")
    return path


def run_audit(tmp_path, extra=()):
    result = subprocess.run([sys.executable, str(ROOT / "tools/audit_mp4_persistent_origin.py"),
                             "--originals", str(originals()), "--out", str(tmp_path / "origin.json"),
                             "--check-shipping", *extra], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_actual_original_persistent_origin_native_pins(tmp_path):
    run_audit(tmp_path)


def test_actual_original_serialized_scene_role_origins(tmp_path):
    pytest.importorskip("UnityPy")
    folder = Path(os.environ.get("IDOLY_MP4_ORIGINAL_SCENES",
                                 "/workspace/shared/mp4-renderer-program-audit/downloaded-source-shaders"))
    android = folder / "android-tln_live_thrx-006.unity3d"
    ios = folder / "ios-tln_live_thrx-006.unity3d"
    if not android.is_file() or not ios.is_file():
        pytest.skip("Immutable decoded original Scene inputs are optional")
    run_audit(tmp_path, ("--android-scene", str(android), "--ios-scene", str(ios)))
