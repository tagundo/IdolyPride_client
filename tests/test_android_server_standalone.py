"""Shipping server boundaries after separating client APK installation."""

from pathlib import Path
import re
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android-server/app/src/main"
JAVA = MAIN / "java/game/qualiarts/idolypride/localserver"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_server_keeps_runtime_permissions_and_only_known_client_visibility():
    manifest = ET.parse(MAIN / "AndroidManifest.xml").getroot()
    permissions = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
    assert permissions == {
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.MANAGE_EXTERNAL_STORAGE",
    }
    assert {node.get(ANDROID + "name") for node in manifest.findall("queries/package")} == {
        "game.qualiarts.idolypride.local",
        "game.qualiarts.idolypride.local.resources",
        "game.qualiarts.idolypride.local.diagnostics",
    }
    application = manifest.find("application")
    assert {node.get(ANDROID + "name") for node in application.findall("activity")} == {".MainActivity"}
    assert application.find("service").get(ANDROID + "exported") == "false"


def test_downloads_storage_is_explicit_permission_gated_and_keeps_old_android_fallback():
    activity = (JAVA / "MainActivity.java").read_text()
    service = (JAVA / "ServerService.java").read_text()
    transfers = (JAVA / "ResourceTransfers.java").read_text()
    assert "Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION" in activity
    assert 'Uri.parse("package:" + getPackageName())' in activity
    assert "retryStartAfterStoragePermission" in activity and "protected void onResume()" in activity
    assert "Environment.isExternalStorageManager()" in activity and "Environment.isExternalStorageManager()" in service
    assert "choosePrivateStorageAndStart()" in activity
    assert "resourceCacheDirectory" in service and "mediaMode, resourceCacheDirectory" in service
    assert 'Environment.DIRECTORY_DOWNLOADS + "/IdolyPride/exports"' in transfers
    assert "DocumentsContract.EXTRA_INITIAL_URI" in activity and "primary:Download/IdolyPride/exports" in activity
    manifest = ET.parse(MAIN / "AndroidManifest.xml").getroot()
    permissions = {node.get(ANDROID + "name") for node in manifest.findall("uses-permission")}
    assert "android.permission.REQUEST_INSTALL_PACKAGES" not in permissions
    assert "android.permission.READ_EXTERNAL_STORAGE" not in permissions
    assert "android.permission.WRITE_EXTERNAL_STORAGE" not in permissions


def test_graphics_and_playback_controls_remain_without_any_apk_installation_path():
    activity = (JAVA / "MainActivity.java").read_text()
    java_sources = "\n".join(path.read_text() for path in JAVA.glob("*.java"))
    for forbidden in ["PackageInstaller", "canRequestPackageInstalls", "ACTION_MANAGE_UNKNOWN_APP_SOURCES",
                      "PresentationAddonInstaller", "PresentationInstallActivity", "PresentationStorage"]:
        assert forbidden not in java_sources
    for removed in ["PresentationAddonInstaller.java", "PresentationInstallActivity.java", "PresentationStorage.java"]:
        assert not (JAVA / removed).exists()
    for control in ["addPlaybackControls(body)", "addPresentationControls(body)",
                    "getLaunchIntentForPackage(packageName)", "savePresentationControls()"]:
        assert control in activity
    resources = ET.parse(MAIN / "res/values/strings.xml").getroot()
    strings = {node.get("name") for node in resources.findall("string")}
    assert "presentation_client_notice" in strings and "presentation_launch_missing" in strings
    assert not any(name.startswith("presentation_install_") for name in strings)
    # All current Java string references must resolve after deleting old install UI.
    assert set(re.findall(r"R\.string\.([A-Za-z0-9_]+)", java_sources)) <= strings


def test_current_client_is_the_only_launcher_target_and_keeps_diagnostics_export():
    activity = (JAVA / "MainActivity.java").read_text()
    resources = ET.parse(MAIN / "res/values/strings.xml").getroot()
    labels = {node.get("name"): node.text for node in resources.findall("string")}
    routes = re.findall(r"launchClient\(R\.string\.[A-Za-z0-9_]+,([^)]*)\)", activity)
    assert len(routes) == 2  # Main action and the graphics settings shortcut.
    assert all(re.findall(r'"([^"]+)"', route) == [
        "game.qualiarts.idolypride.local.diagnostics"] for route in routes)
    assert activity.count("button(R.string.launch_diagnostic_client)") == 1
    assert "button(R.string.launch_client)" not in activity
    assert labels["launch_diagnostic_client"] == labels["presentation_launch_button"] == "아이프라 실행"
    assert "export = button(R.string.export_diagnostics)" in activity
    assert '"IdolyPride-diagnostics.json"' in activity
