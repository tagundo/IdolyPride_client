"""Portable host tool discovery for the real Java and pinned Android34 gates.

Discovery is lazy: unrelated parser/packaging tests do not require these tools.
Explicit overrides fail clearly instead of silently skipping a meaningful gate.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
_FLAGS = ("-Xmx32m", "-XX:MaxMetaspaceSize=64m", "-XX:ReservedCodeCacheSize=16m",
          "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1")


def _jdk_bin(path):
    path = Path(path).expanduser().resolve()
    return path if (path / "javac").is_file() else path / "bin"


def _is_jdk21(directory):
    if any(not (directory / name).is_file() or not os.access(directory / name, os.X_OK)
           for name in ("java", "javac")):
        return False
    results = []
    for name, flags in (("javac", ["-J" + flag for flag in _FLAGS]), ("java", _FLAGS)):
        try:
            result = subprocess.run([str(directory / name), *flags, "-version"], check=False,
                capture_output=True, text=True, timeout=10, env=dict(os.environ, MALLOC_ARENA_MAX="2"))
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode or len(result.stdout) + len(result.stderr) > 8192:
            return False
        results.append(result.stdout + "\n" + result.stderr)
    compiler = re.search(r"\bjavac\s+(\d+)(?:[.\s-]|$)", results[0])
    runtime = re.search(r'\bversion\s+"(\d+)(?:[."]|$)', results[1])
    return compiler is not None and runtime is not None and compiler[1] == runtime[1] == "21"


@pytest.fixture(scope="session")
def presentation_jdk():
    """Return the verified JDK21 bin directory, never a JDK home/bin mix."""
    explicit = os.environ.get("IDOLY_TEST_JDK_HOME")
    if explicit:
        selected = _jdk_bin(explicit)
        if not _is_jdk21(selected):
            pytest.fail("IDOLY_TEST_JDK_HOME must provide matching Java and javac21", pytrace=False)
        return selected
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(_jdk_bin(os.environ["JAVA_HOME"]))
    executable = shutil.which("javac")
    if executable:
        candidates.append(Path(executable).resolve().parent)
    candidates.append(ROOT.parent / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin")
    for selected in dict.fromkeys(candidates):
        if _is_jdk21(selected):
            return selected
    pytest.fail("JDK21 is required: set IDOLY_TEST_JDK_HOME or JAVA_HOME, or place JDK21 on PATH", pytrace=False)


def _android34(root):
    root = Path(root).expanduser().resolve()
    android = root / "platforms/android-34/android.jar"
    d8 = root / "build-tools/34.0.0/lib/d8.jar"
    return (android, d8) if android.is_file() and d8.is_file() else None


@pytest.fixture(scope="session")
def presentation_android34_tools():
    """Return the exact API34 library and build-tools34.0.0 D8, without downloads."""
    explicit = os.environ.get("IDOLY_TEST_ANDROID_SDK")
    if explicit:
        selected = _android34(explicit)
        if selected is None:
            pytest.fail("IDOLY_TEST_ANDROID_SDK must contain platform android-34 and build-tools34.0.0", pytrace=False)
        return selected
    candidates = [os.environ[name] for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT") if os.environ.get(name)]
    candidates.append(ROOT.parent / ".setup/android-sdk")
    for candidate in dict.fromkeys(candidates):
        selected = _android34(candidate)
        if selected is not None:
            return selected
    pytest.fail("Android34 and build-tools34.0.0 are required: set ANDROID_HOME or IDOLY_TEST_ANDROID_SDK", pytrace=False)
