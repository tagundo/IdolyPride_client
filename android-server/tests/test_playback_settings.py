"""Exercise the actual strict Android settings/ACK policy on the host JVM."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


def test_strict_playback_settings_revision_and_fresh_ack(tmp_path):
    root = Path(__file__).resolve().parents[2]
    cached = root.parent / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin"
    javac = cached / "javac" if (cached / "javac").is_file() else shutil.which("javac")
    java = cached / "java" if (cached / "java").is_file() else shutil.which("java")
    if not javac or not java:
        pytest.skip("Host JDK unavailable")
    package = Path("game/qualiarts/idolypride/localserver")
    sources = [root / "android-server/app/src/main/java" / package / "PlaybackSettings.java",
               root / "android-server/tests/java" / package / "PlaybackSettingsHostTest.java"]
    flags = ["-Xms16m", "-Xmx64m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
             "-XX:MaxMetaspaceSize=48m", "-XX:CompressedClassSpaceSize=8m", "-XX:ReservedCodeCacheSize=16m"]
    env = dict(os.environ)
    subprocess.run([str(javac), *("-J" + flag for flag in flags), "-encoding", "UTF-8", "-d", str(tmp_path),
                    *(str(source) for source in sources)], check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(java), *flags, "-cp", str(tmp_path),
                             "game.qualiarts.idolypride.localserver.PlaybackSettingsHostTest"],
                            check=True, text=True, capture_output=True, timeout=10, env=env)
    assert "playback settings and acknowledgement checks" in result.stdout
