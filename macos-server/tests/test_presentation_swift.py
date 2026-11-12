"""Pure Foundation behavior tests; compile on the existing Darwin build host."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="Swift Foundation tests run on the macOS build host")
def test_presentation_preferences_and_ack_policy(tmp_path):
    swift = shutil.which("swiftc")
    if swift is None:
        swift = subprocess.check_output(["/usr/bin/xcrun", "--find", "swiftc"], text=True).strip()
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "PresentationSettingsTests"
    subprocess.run([swift, "-swift-version", "5", "-parse-as-library", str(root / "PresentationSettings.swift"),
                    str(root / "tests/PresentationSettingsTests.swift"), "-o", str(output)], check=True, timeout=120)
    result = subprocess.run([str(output)], check=True, text=True, capture_output=True, timeout=30)
    assert "presentation codec, preservation, ACK and polling checks" in result.stdout
