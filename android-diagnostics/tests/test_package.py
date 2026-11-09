from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("package_diagnostic_client", ROOT / "tools/package_diagnostic_client.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def decoded_client(root, identity=package.PACKAGE):
    (root / "dex").mkdir()
    for name in ("classes.dex", "classes2.dex", "classes3.dex", "classes4.dex"):
        (root / "dex" / name).write_bytes(name.encode())
    (root / "AndroidManifest.xml").write_text(
        f'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{identity}"><application /></manifest>')


def test_private_provider_uses_distinct_identity_and_preserves_original_dex(tmp_path):
    decoded_client(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / "dex").iterdir()}
    assert package.add_provider(tmp_path) == "classes5.dex"
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "dex").iterdir()}
    provider = ET.parse(tmp_path / "AndroidManifest.xml").find("application/provider")
    assert provider.get(package.ANDROID + "name") == package.PROVIDER
    assert provider.get(package.ANDROID + "authorities") == package.PACKAGE + ".bootstrap"
    assert provider.get(package.ANDROID + "exported") == "false"
    assert provider.get(package.ANDROID + "initOrder") == "1"
    with pytest.raises(ValueError, match="already contains"):
        package.add_provider(tmp_path)


@pytest.mark.parametrize("identity", ["game.qualiarts.idolypride", "game.qualiarts.idolypride.local"])
def test_provider_rejects_installed_game_identities(tmp_path, identity):
    decoded_client(tmp_path, identity)
    with pytest.raises(ValueError, match="separate"):
        package.add_provider(tmp_path)


@pytest.mark.parametrize("name", ["LogSanitizer", "TrafficSampler"])
def test_pure_java_diagnostics_contracts(tmp_path, name):
    javac = shutil.which("javac")
    if not javac:
        candidate = Path(os.environ.get("JAVA_HOME", "/nonexistent")) / "bin/javac"
        javac = str(candidate) if candidate.is_file() else None
    if not javac:
        pytest.skip("A JDK is required for the pure Java diagnostics harness")
    java = Path(javac).resolve().with_name("java")
    source = ROOT / ("android-diagnostics/src/game/qualiarts/idolypride/diagnostics/" + name + ".java")
    harness = ROOT / ("android-diagnostics/tests/" + name + "Test.java")
    subprocess.run([javac, "--release", "8", "-encoding", "UTF-8", "-d", str(tmp_path), str(source), str(harness)], check=True, capture_output=True)
    result = subprocess.run([str(java), "-cp", str(tmp_path), name + "Test"], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == name + "Test passed"
