"""Host-only parser/loopback transport; no native code, key, Android or network."""
from pathlib import Path
import importlib.util
import os
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "client-presentation"
JDK = Path("/workspace/.setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin")
SPEC = importlib.util.spec_from_file_location("presentation_addon_protocol", HERE / "build_addon.py")
ADDON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADDON)


def test_java_protocol_and_transport_boundaries(tmp_path):
    sources = [HERE / "java/game/qualiarts/idolypride/presentation/PresentationClient.java",
               HERE / "tests/PresentationHarness.java"]
    flags = ["-Xmx128m", "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=32m",
             "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1"]
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK / "javac"), *["-J" + flag for flag in flags], *ADDON.JAVAC_ARGUMENTS,
                    "-d", str(tmp_path), *map(str, sources)], check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(JDK / "java"), *flags, "-cp", str(tmp_path),
        "game.qualiarts.idolypride.presentation.PresentationHarness"], check=True,
        capture_output=True, text=True, timeout=30, env=env)
    assert result.stdout.startswith("PASS ") and int(result.stdout.split()[1]) >= 45


def test_java_playback_protocol_transport_and_native_default_retention(tmp_path):
    sources = [HERE / "java/game/qualiarts/idolypride/presentation/PresentationClient.java",
               HERE / "tests/PlaybackHarness.java"]
    flags = ["-Xmx128m", "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=32m",
             "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1"]
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK / "javac"), *["-J" + flag for flag in flags], *ADDON.JAVAC_ARGUMENTS,
                    "-d", str(tmp_path), *map(str, sources)], check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(JDK / "java"), *flags, "-cp", str(tmp_path),
        "game.qualiarts.idolypride.presentation.PlaybackHarness"], check=True,
        capture_output=True, text=True, timeout=30, env=env)
    assert result.stdout.startswith("PASS ") and int(result.stdout.split()[1]) >= 90


def test_java_render_probe_nullable_contract_optional_endpoint_and_transport(tmp_path):
    sources = [HERE / "java/game/qualiarts/idolypride/presentation/PresentationClient.java",
               HERE / "tests/RenderProbeHarness.java"]
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    subprocess.run([str(JDK / "javac"), *["-J" + flag for flag in ADDON.JAVA_FLAGS], *ADDON.JAVAC_ARGUMENTS,
                    "-d", str(tmp_path), *map(str, sources)], check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(JDK / "java"), *ADDON.JAVA_FLAGS, "-cp", str(tmp_path),
        "game.qualiarts.idolypride.presentation.RenderProbeHarness"], check=True,
        capture_output=True, text=True, timeout=30, env=env)
    assert result.stdout.startswith("PASS ") and int(result.stdout.split()[1]) >= 250


def test_jdk21_captured_parameter_metadata_compiles_through_cached_d8(tmp_path):
    """Exercise real production classes at the former D8 null-name boundary."""
    android = Path("/workspace/.setup/android-sdk/platforms/android-34/android.jar")
    d8 = Path("/workspace/.setup/android-sdk/build-tools/34.0.0/lib/d8.jar")
    classes, dex = tmp_path / "classes", tmp_path / "dex"
    classes.mkdir(); dex.mkdir()
    env = dict(os.environ, MALLOC_ARENA_MAX="2")
    sources = sorted((HERE / "java").rglob("*.java"))
    subprocess.run([str(JDK / "javac"), *["-J" + flag for flag in ADDON.JAVA_FLAGS],
        *ADDON.JAVAC_ARGUMENTS, "-classpath", str(android), "-d", str(classes), *map(str, sources)],
        check=True, capture_output=True, timeout=30, env=env)
    subprocess.run([str(JDK / "java"), *ADDON.JAVA_FLAGS, "-cp", str(d8), "com.android.tools.r8.D8",
        "--release", "--min-api", "28", "--lib", str(android), "--output", str(dex),
        *map(str, sorted(classes.rglob("*.class")))], check=True, capture_output=True, timeout=30, env=env)
    assert [path.name for path in dex.iterdir()] == ["classes.dex"]
    raw = (dex / "classes.dex").read_bytes()
    assert raw[:8] == b"dex\n039\0" and 0 < len(raw) < 65536
