"""Execute the shared public-marker policy without Android, Unity or sockets."""
import os
from pathlib import Path
import subprocess

import pytest


def test_strict_integer_default_and_six_hour_cap(tmp_path):
    root = Path(__file__).resolve().parents[1]
    jdk = Path(os.environ.get("JAVA_HOME", "/workspace/.setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64")) / "bin"
    if not (jdk / "javac").is_file() or not (jdk / "java").is_file():
        pytest.skip("Cached JDK is unavailable")
    harness = tmp_path / "SessionHarness.java"
    harness.write_text('''package game.qualiarts.idolypride.qa.ui;
public final class SessionHarness {
    static void equal(long expected, long actual) { if (expected != actual) throw new AssertionError(); }
    static void reject(Object value) {
        try { LoopbackUiServer.markerSessionMillis(value, true); throw new AssertionError("accepted invalid marker"); }
        catch (IllegalArgumentException expected) { }
    }
    public static void main(String[] args) {
        equal(1800000L, LoopbackUiServer.markerSessionMillis(null, false));
        equal(1L, LoopbackUiServer.markerSessionMillis(Integer.valueOf(1), true));
        equal(1800000L, LoopbackUiServer.markerSessionMillis(Integer.valueOf(1800000), true));
        equal(7200000L, LoopbackUiServer.markerSessionMillis(Integer.valueOf(7200000), true));
        equal(7200000L, LoopbackUiServer.markerSessionMillis(Long.valueOf(7200000L), true));
        equal(21600000L, LoopbackUiServer.markerSessionMillis(Integer.valueOf(21600000), true));
        equal(21600000L, LoopbackUiServer.markerSessionMillis(Long.valueOf(21600000L), true));
        for (Object bad : new Object[]{null, Boolean.TRUE, Boolean.FALSE, "21600000", Double.valueOf(21600000.0),
                Float.valueOf(1800000), Integer.valueOf(0), Integer.valueOf(-1), Integer.valueOf(21600001),
                Long.valueOf(Long.MAX_VALUE), Long.valueOf(Long.MIN_VALUE), new java.math.BigInteger("21600000")}) reject(bad);
        for (long bad : new long[]{0,-1,21600001L,Long.MAX_VALUE}) {
            try { LoopbackUiServer.checkedSessionMillis(bad); throw new AssertionError(); }
            catch (IllegalArgumentException expected) { }
        }
        System.out.println("session policy passed");
    }
}''')
    source = root / "java/game/qualiarts/idolypride/qa/ui/LoopbackUiServer.java"
    subprocess.run([str(jdk / "javac"), "-J-Xmx128m", "--release", "8", "-d", str(tmp_path),
                    str(source), str(harness)], check=True, capture_output=True, timeout=30)
    result = subprocess.run([str(jdk / "java"), "-Xmx128m", "-cp", str(tmp_path),
                             "game.qualiarts.idolypride.qa.ui.SessionHarness"],
                            check=True, capture_output=True, text=True, timeout=15)
    assert result.stdout.strip() == "session policy passed"


def test_provider_passes_validated_marker_duration_to_both_observer_deadlines():
    root = Path(__file__).resolve().parents[1] / "java/game/qualiarts/idolypride/qa/ui"
    provider = (root / "QaUiProvider.java").read_text()
    dispatcher = (root / "UnityDispatcher.java").read_text()
    assert 'LoopbackUiServer.markerSessionMillis(marker.opt("session_millis"), marker.has("session_millis"))' in provider
    assert "new UnityDispatcher(context, sessionMillis)" in provider
    assert "new LoopbackUiServer(token, dispatcher, sessionMillis)" in provider
    assert "LoopbackUiServer.checkedSessionMillis(sessionMillis)" in dispatcher
    assert "private static final long REQUEST_MILLIS = 8000" in dispatcher
