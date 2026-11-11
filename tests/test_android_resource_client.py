import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from idoly_local.android_package import ANDROID
from tools import package_android_resource_client as tool


def decoded_fixture(root):
    root.mkdir()
    (root / "root/res/raw").mkdir(parents=True)
    (root / "root/res/raw/keep.xml").write_bytes(b"original raw resource")
    (root / "resources/package_1/res/xml").mkdir(parents=True)
    (root / "resources/package_1/package.json").write_text(json.dumps({"package_name": "game.qualiarts.idolypride"}))
    (root / "resources/package_1/res/xml/network_security_config.xml").write_text(
        '<network-security-config><base-config><trust-anchors><certificates src="system"/>'
        '</trust-anchors></base-config></network-security-config>')
    (root / "AndroidManifest.xml").write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
      package="game.qualiarts.idolypride"><permission android:name="game.qualiarts.idolypride.P"/>
      <uses-permission android:name="game.qualiarts.idolypride.P"/>
      <application android:networkSecurityConfig="@xml/network_security_config">
      <activity android:name=".GameActivity"/><provider android:name="com.google.firebase.provider.FirebaseInitProvider"
      android:authorities="game.qualiarts.idolypride.firebaseinitprovider"/>
      <receiver android:name="Receiver" android:permission="game.qualiarts.idolypride.P"/>
      </application></manifest>''')
    for name in ("archive-info.json", "uncompressed-files.json", "path-map.json"):
        (root / name).write_text("{}")


def test_small_resource_stage_renames_identity_and_preserves_sdk_component_names(tmp_path):
    decoded_fixture(tmp_path / "original")
    original_xml = (tmp_path / "original/AndroidManifest.xml").read_bytes()
    result = tool.stage_resources(tmp_path / "original", tmp_path / "stage")
    tree = ET.parse(tmp_path / "stage/AndroidManifest.xml")
    assert tree.getroot().get("package") == tool.PACKAGE
    app = tree.find("application")
    assert app.get(ANDROID + "label") == tool.LABEL
    assert app.find("provider").get(ANDROID + "authorities") == tool.PACKAGE + ".firebaseinitprovider"
    assert app.find("provider").get(ANDROID + "name") == "com.google.firebase.provider.FirebaseInitProvider"
    assert app.find("activity").get(ANDROID + "name") == "game.qualiarts.idolypride.GameActivity"
    assert app.find("receiver").get(ANDROID + "permission") == tool.PACKAGE + ".P"
    assert tree.find("permission").get(ANDROID + "name") == tool.PACKAGE + ".P"
    assert (tmp_path / "original/AndroidManifest.xml").read_bytes() == original_xml
    assert result["endpoint"] == tool.API_ORIGIN
    assert (tmp_path / "stage/root/res/raw/keep.xml").read_bytes() == b"original raw resource"
    assert json.loads((tmp_path / "stage/resources/package_1/package.json").read_text())["package_name"] == tool.PACKAGE
    security = ET.parse(tmp_path / "stage/resources/package_1/res/xml/network_security_config.xml")
    domain = security.find("domain-config")
    assert domain.get("cleartextTrafficPermitted") == "true" and domain.find("domain").text == "127.0.0.1"


def test_stream_uses_only_approved_normal_native_not_qa_observer(tmp_path):
    source, normal, output = (tmp_path / x for x in ("original.apk", "normal-source.apk", "out.apk"))
    original = {"classes.dex": b"original SDK", tool.NATIVE: b"original native",
                "AndroidManifest.xml": b"old manifest", tool.octo.METADATA: b"old metadata",
                tool.UNITY_SETTINGS: b"old PlayerSettings", "META-INF/OLD.SF": b"sig"}
    with ZipFile(source, "w") as z:
        for k, v in original.items():
            z.writestr(k, v)
    with ZipFile(normal, "w") as z:
        z.writestr(tool.NATIVE, b"approved normal native")
        z.writestr("classes5.dex", b"QA must not be copied")
        z.writestr("lib/arm64-v8a/libidoly_qa_ui_bridge.so", b"QA must not be copied")
    replacements = {"AndroidManifest.xml": b"new manifest", tool.octo.METADATA: b"new metadata",
                    tool.UNITY_SETTINGS: b"one audited PlayerSettings field changed", tool.MARKER: b"new provenance"}
    tool.stream_apk(source, normal, output, replacements)
    with ZipFile(output) as z:
        assert z.read("classes.dex") == b"original SDK"
        assert z.read(tool.NATIVE) == b"approved normal native"
        assert z.read(tool.MARKER) == b"new provenance"
        assert z.read(tool.octo.METADATA) == b"new metadata"
        assert z.read(tool.UNITY_SETTINGS) == b"one audited PlayerSettings field changed"
        assert not tool.FORBIDDEN & set(z.namelist())
        assert "META-INF/OLD.SF" not in z.namelist()


def test_resource_decode_input_is_bound_to_only_original_apk_resource_bytes(tmp_path):
    source, target = tmp_path / "source.apk", tmp_path / "resources.apk"
    members = {"AndroidManifest.xml": b"original manifest", "resources.arsc": b"original table",
               "res/xml/network_security_config.xml": b"original policy", "res/raw/keep.xml": b"original keep",
               "classes.dex": b"must not extract SDK", tool.NATIVE: b"must not extract native",
               "assets/private-lookalike": b"must not extract assets"}
    with ZipFile(source, "w") as z:
        for name, raw in members.items():
            z.writestr(name, raw)
    tool.write_resource_input(source, target)
    with ZipFile(target) as z:
        assert set(z.namelist()) == {k for k in members if k.startswith("res/") or k in ("AndroidManifest.xml", "resources.arsc")}
        for name in z.namelist():
            assert z.read(name) == members[name]


def test_badging_resource_package_and_stale_authorities_rejected():
    badging = f"package: name='{tool.PACKAGE}' versionCode='414' versionName='6.1.1'\napplication-label:'{tool.LABEL}'\nnative-code: 'arm64-v8a'"
    resources = f"Package name={tool.PACKAGE} id=7f"
    good = f'A: android:authorities(0x01010018)="{tool.PACKAGE}.firebaseinitprovider"'
    tool.validate_identity(badging, good, resources)
    tool.validate_identity(badging, good + '\nA: android:debuggable(0x0101000f)=false', resources)
    for manifest in ['A: android:authorities(0x01010018)="game.qualiarts.idolypride.firebaseinitprovider"',
                     'A: android:permission(0x01010006)="game.qualiarts.idolypride.local.P"',
                     'game.qualiarts.idolypride.qa.ui.QaUiProvider', 'A: android:debuggable(0x0101000f)=true']:
        with pytest.raises(ValueError):
            tool.validate_identity(badging, manifest, resources)
    with pytest.raises(ValueError):
        tool.validate_identity(badging, good, "Package name=game.qualiarts.idolypride id=7f")


def test_private_signing_material_stat_only(tmp_path, monkeypatch):
    path = tmp_path / "password"
    path.write_bytes(b"synthetic test value")
    path.chmod(0o600)
    monkeypatch.setattr(Path, "read_bytes", lambda *args: pytest.fail("password value read"))
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("password value read"))
    assert tool.private_regular_file(path) == path
    path.chmod(0o644)
    with pytest.raises(ValueError):
        tool.private_regular_file(path)


def test_resource_identity_mapping_excludes_values_but_detects_id_or_name_change():
    a = "    resource 0x7f010001 string/google_app_id\n      () value"
    assert tool.resource_ids(a) == [("0x7f010001", "string/google_app_id")]
    assert tool.resource_ids(a) != tool.resource_ids(a.replace("0x7f010001", "0x7f010002"))


def test_single_line_password_file_is_consumed_once_without_secret_extraction(tmp_path):
    password = tmp_path / "one-line-password"
    command = tool.signing_command(["java", "-Xmx128m", "-jar", "apksigner.jar"],
                                   tmp_path / "key.p12", password, "idoly-local", tmp_path / "app.apk")
    assert command.count("file:" + str(password)) == 1
    assert "--key-pass" not in command
    assert "--ks-pass" in command
