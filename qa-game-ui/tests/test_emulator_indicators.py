"""Compile and execute the actual Java emulator predicate without Android runtime."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_exact_cuttlefish_indicators_and_legacy_qemu_property(tmp_path):
    cache = Path("/workspace/.setup")
    java_home = Path(os.environ.get("JAVA_HOME", cache / "jdk-system/usr/lib/jvm/java-21-openjdk-amd64"))
    javac = java_home / "bin/javac"
    java = java_home / "bin/java"
    if not javac.is_file() or not java.is_file():
        javac_name, java_name = shutil.which("javac"), shutil.which("java")
        if not javac_name or not java_name:
            pytest.skip("JDK is required for the executable Java indicator test")
        javac, java = Path(javac_name), Path(java_name)
    sdk = Path(os.environ.get("ANDROID_HOME", cache / "android-sdk"))
    android = sdk / "platforms/android-34/android.jar"
    if not android.is_file():
        pytest.skip("Android34 compile stubs are required; no device execution is needed")
    harness = tmp_path / "IndicatorHarness.java"
    harness.write_text('''package game.qualiarts.idolypride.qa.ui;
public final class IndicatorHarness {
    private static void check(boolean expected, String hardware, String boot, String device, String qemu) {
        if (QaUiProvider.EmulatorIndicators.matches(hardware, boot, device, qemu) != expected)
            throw new AssertionError("unexpected indicator combination");
    }
    public static void main(String[] args) {
        check(true, "cutf_cvm", "cutf_cvm", "vsoc_arm64_only", "");
        check(true, "cutf_cvm", "cutf_cvm", "vsoc_arm64_only", "1");
        check(false, "cutf_cvm", "", "vsoc_arm64_only", "1");
        check(false, "cutf_cvm", "ranchu", "vsoc_arm64_only", "1");
        check(false, "cutf_cvm", "cutf_cvm", "vsoc_x86_64", "1");
        check(false, "cutf_cvm", "cutf_cvm", "physical", "1");
        check(false, "physical", "cutf_cvm", "vsoc_arm64_only", "1");
        check(false, null, "cutf_cvm", "vsoc_arm64_only", "1");
        check(false, "cutf_cvm", null, "vsoc_arm64_only", "1");
        check(false, "cutf_cvm", "cutf_cvm", null, "1");
        check(true, "ranchu", "", "any", "1");
        check(true, "goldfish", "", "any", "1");
        check(false, "ranchu", "", "any", "");
        check(false, "goldfish", "", "any", "0");
        check(false, "ranchu", "", "any", null);
        System.out.println("indicator combinations passed");
    }
}''')
    output = tmp_path / "classes"
    output.mkdir()
    sources = sorted((ROOT / "java").rglob("*.java"))
    subprocess.run([str(javac), "--release", "8", "-classpath", str(android), "-d", str(output),
                    *(str(source) for source in sources), str(harness)], check=True, capture_output=True, timeout=30)
    result = subprocess.run([str(java), "-classpath", str(output),
                             "game.qualiarts.idolypride.qa.ui.IndicatorHarness"],
                            check=True, capture_output=True, text=True, timeout=15)
    assert result.stdout.strip() == "indicator combinations passed"
