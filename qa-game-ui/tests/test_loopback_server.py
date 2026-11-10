"""Exercise the actual pure-Java HTTP bridge without Android or game data."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_authenticated_bounded_semantic_http_protocol(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("Host JDK is unavailable; the APK builder separately requires javac and D8")
    sources = [ROOT / "java/game/qualiarts/idolypride/qa/ui/LoopbackUiServer.java",
               ROOT / "tests/LoopbackHarness.java"]
    subprocess.run([javac, "--release", "8", "-encoding", "UTF-8", "-d", str(tmp_path),
                    *map(str, sources)], check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([java, "-cp", str(tmp_path), "game.qualiarts.idolypride.qa.ui.LoopbackHarness"],
                            check=True, capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == "QA loopback protocol checks passed"
