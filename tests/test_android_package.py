"""Android clone configuration boundaries without game inputs or SDK rebuilds."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from idoly_local.android_package import (
    AndroidPackagingError,
    configure_android,
    package_android,
    strip_apk_signatures,
)


ANDROID = "{http://schemas.android.com/apk/res/android}"
ORIGINAL = "game.qualiarts.idolypride"
LOCAL = ORIGINAL + ".local"


@pytest.fixture
def decoded(tmp_path):
    root = tmp_path / "decoded"
    resource = root / "resources/package_1"
    (resource / "res/values").mkdir(parents=True)
    (resource / "res/xml").mkdir()
    (root / "AndroidManifest.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{ORIGINAL}" android:versionCode="414">
  <uses-sdk android:minSdkVersion="28" android:targetSdkVersion="36" />
  <permission android:name="{ORIGINAL}.LOCAL_PERMISSION" android:protectionLevel="signature" />
  <uses-permission android:name="{ORIGINAL}.LOCAL_PERMISSION" />
  <uses-permission android:name="android.permission.INTERNET" />
  <application android:label="@string/app_name" android:name=".GameApplication" android:networkSecurityConfig="@xml/network_security_config">
    <activity android:name="com.google.firebase.MessagingUnityPlayerActivity" />
    <activity android:name=".LocalActivity" />
    <service android:name="SimpleService" />
    <receiver android:name="{ORIGINAL}.GameReceiver" android:permission="{ORIGINAL}.LOCAL_PERMISSION" />
    <provider android:name="com.example.FullyQualifiedProvider" android:authorities="{ORIGINAL}.files;{ORIGINAL}.images" android:exported="false" />
    <activity android:name="com.example.CallbackActivity">
      <intent-filter><data android:scheme="{ORIGINAL}.twitter" /></intent-filter>
      <intent-filter><data android:scheme="idolypride.android.app" android:host="stat.game-idolypride.jp" /></intent-filter>
    </activity>
  </application>
</manifest>''', encoding="utf-8")
    (resource / "package.json").write_text(json.dumps({"package_name": ORIGINAL, "package_id": 127, "specs": [{"spec": {"id": 1}}]}))
    (resource / "res/values/public.xml").write_text(f'<resources package="{ORIGINAL}" id="0x7f"><public id="0x7f010000" type="string" name="app_name" /></resources>')
    (resource / "res/xml/network_security_config.xml").write_text('''<network-security-config>
  <base-config><trust-anchors><certificates src="system" /></trust-anchors></base-config>
  <debug-overrides><trust-anchors><certificates src="user" /></trust-anchors></debug-overrides>
</network-security-config>''')
    return root


def files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_clone_updates_install_identity_and_preserves_java_components(decoded):
    result = configure_android(decoded, "http://192.168.0.20:50051", package=LOCAL, label="아이프라 로컬")
    assert isinstance(result, dict)
    manifest = ET.parse(decoded / "AndroidManifest.xml").getroot()
    assert manifest.get("package") == LOCAL
    assert manifest.get(ANDROID + "versionCode") == "414"
    application = manifest.find("application")
    assert application.get(ANDROID + "label") == "아이프라 로컬"
    assert application.get(ANDROID + "name") == ORIGINAL + ".GameApplication"
    components = {element.tag: [] for element in application if element.get(ANDROID + "name")}
    for element in application:
        if element.get(ANDROID + "name"):
            components[element.tag].append(element.get(ANDROID + "name"))
    assert "com.google.firebase.MessagingUnityPlayerActivity" in components["activity"]
    assert ORIGINAL + ".LocalActivity" in components["activity"]
    assert components["service"] == [ORIGINAL + ".SimpleService"]
    assert components["receiver"] == [ORIGINAL + ".GameReceiver"]
    assert components["provider"] == ["com.example.FullyQualifiedProvider"]
    assert manifest.find("permission").get(ANDROID + "name") == LOCAL + ".LOCAL_PERMISSION"
    assert [element.get(ANDROID + "name") for element in manifest.findall("uses-permission")] == [
        LOCAL + ".LOCAL_PERMISSION", "android.permission.INTERNET"]
    assert application.find("provider").get(ANDROID + "authorities") == LOCAL + ".files;" + LOCAL + ".images"
    assert application.find("receiver").get(ANDROID + "permission") == LOCAL + ".LOCAL_PERMISSION"
    assert application.find("activity/intent-filter/data").get(ANDROID + "scheme") == LOCAL + ".twitter"
    schemes = [item.get(ANDROID + "scheme") for item in application.findall("activity/intent-filter/data")]
    assert LOCAL in schemes
    assert "idolypride.android.app" not in schemes
    package = json.loads((decoded / "resources/package_1/package.json").read_text())
    assert package["package_name"] == LOCAL
    assert package["package_id"] == 127 and package["specs"] == [{"spec": {"id": 1}}]
    public = ET.parse(decoded / "resources/package_1/res/values/public.xml").getroot()
    assert public.get("package") == LOCAL
    assert public.find("public").get("id") == "0x7f010000"


def test_http_cleartext_exception_is_scoped_to_local_endpoint(decoded):
    configure_android(decoded, "http://192.168.0.20:50051")
    manifest = ET.parse(decoded / "AndroidManifest.xml").getroot()
    assert manifest.find("application").get(ANDROID + "usesCleartextTraffic") != "true"
    config = ET.parse(decoded / "resources/package_1/res/xml/network_security_config.xml").getroot()
    assert config.find("base-config/trust-anchors/certificates").get("src") == "system"
    assert config.find("base-config").get("cleartextTrafficPermitted") != "true"
    exceptions = [node for node in config.findall("domain-config") if node.get("cleartextTrafficPermitted") == "true"]
    assert exceptions
    domains = [domain for node in exceptions for domain in node.findall("domain")]
    assert [domain.text for domain in domains] == ["192.168.0.20"]
    assert all(domain.get("includeSubdomains", "false") == "false" for domain in domains)


@pytest.mark.parametrize("package", [ORIGINAL, "", ".bad", "bad..package", "bad/package", "white space.package"])
def test_invalid_package_rejected_before_editing(decoded, package):
    before = files(decoded)
    with pytest.raises(AndroidPackagingError):
        configure_android(decoded, "http://127.0.0.1:50051", package=package)
    assert files(decoded) == before


@pytest.mark.parametrize("endpoint", ["", "localhost:50051", "ftp://localhost:50051", "http://user:password@localhost:50051",
                                      "http://localhost:50051/api", "http://localhost:50051?token=secret",
                                      "http://localhost:50051#fragment", "http://localhost:notaport"])
def test_invalid_endpoint_rejected_before_editing(decoded, endpoint):
    before = files(decoded)
    with pytest.raises(AndroidPackagingError):
        configure_android(decoded, endpoint)
    assert files(decoded) == before


def test_package_never_overwrites_existing_output_or_touches_source(tmp_path, monkeypatch):
    source, output = tmp_path / "original.apk", tmp_path / "existing.apk"
    with ZipFile(source, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"fixture-input")
    output.write_bytes(b"keep-existing-installable-artifact")
    before = source.read_bytes()

    def no_process(*args, **kwargs):
        raise AssertionError("No tool may launch before the no-overwrite check")

    monkeypatch.setattr("subprocess.run", no_process)
    monkeypatch.setattr("subprocess.Popen", no_process)
    with pytest.raises(AndroidPackagingError):
        package_android(source, output, endpoint="http://127.0.0.1:50051")
    assert source.read_bytes() == before
    assert output.read_bytes() == b"keep-existing-installable-artifact"


def test_signature_strip_retains_non_signature_metadata_and_native_compression(tmp_path):
    source, target = tmp_path / "signed.apk", tmp_path / "unsigned.apk"
    members = {
        "META-INF/MANIFEST.MF": b"old-digests",
        "META-INF/CERT.SF": b"old-signature-file",
        "META-INF/CERT.RSA": b"old-signature",
        "META-INF/CERT.DSA": b"old-signature",
        "META-INF/CERT.EC": b"old-signature",
        "META-INF/androidx.core_core.version": b"1.0",
        "META-INF/services/example.Service": b"example.Implementation",
        "assets/META-INF/CERT.RSA": b"not-a-root-apk-signature",
        "AndroidManifest.xml": b"manifest-fixture",
        "lib/arm64-v8a/libexample.so": b"ELF-native-fixture" * 100,
    }
    with ZipFile(source, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload, compress_type=ZIP_STORED if name.endswith(".so") else ZIP_DEFLATED)
    original = source.read_bytes()
    strip_apk_signatures(source, target)
    with ZipFile(target) as archive:
        assert not any(name in archive.namelist() for name in ("META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA", "META-INF/CERT.DSA", "META-INF/CERT.EC"))
        for name in ("META-INF/androidx.core_core.version", "META-INF/services/example.Service",
                     "assets/META-INF/CERT.RSA", "AndroidManifest.xml", "lib/arm64-v8a/libexample.so"):
            assert archive.read(name) == members[name]
        assert archive.getinfo("lib/arm64-v8a/libexample.so").compress_type == ZIP_STORED
    assert source.read_bytes() == original
