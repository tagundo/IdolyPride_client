"""Optional immutable-original verification of shipping producer pins."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_actual_original_capture_queue_pins(tmp_path):
    originals = Path(os.environ.get("IDOLY_MP4_ORIGINALS", "/workspace/shared/idoly-sdk-cache-analysis"))
    if not all((originals / name).is_file() for name in (
            "android-metadata.dat", "android-native.so", "ios-metadata.dat", "ios-native.bin",
            "mp4-android-analysis/libunity.so")):
        pytest.skip("Pinned original images are optional source-audit inputs")
    result = subprocess.run([sys.executable, str(ROOT / "tools/audit_mp4_capture_queue.py"),
                             "--originals", str(originals), "--out", str(tmp_path / "source.json"),
                             "--check-shipping"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
