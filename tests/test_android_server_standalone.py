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



def _java_method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for index in range(opening + 1, len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError("Unclosed Java method: " + signature)


def test_server_record_export_is_separate_and_snapshots_visible_text_before_saf():
    activity = (JAVA / "MainActivity.java").read_text()
    service = (JAVA / "ServerService.java").read_text()
    labels = {node.get("name"): node.text for node in ET.parse(MAIN / "res/values/strings.xml").getroot().findall("string")}
    assert labels["export_server_logs"] == "서버 기록 내보내기"
    assert activity.index("text(R.string.server_logs,") < activity.index("button(R.string.export_server_logs)") < activity.index("logs = text(")
    request = _java_method(activity, "private void requestServerLogExport()")
    assert request.index("logs.getText().toString()") < request.index("startActivityForResult(")
    assert "Intent.ACTION_CREATE_DOCUMENT" in request and "Intent.CATEGORY_OPENABLE" in request
    assert 'setType("text/plain")' in request and '"IdolyPride-server-records.txt"' in request
    assert "Intent.FLAG_GRANT_WRITE_URI_PERMISSION" in request
    assert "finishServerLogExport(resultCode, data)" in activity
    assert "getLastNonConfigurationInstance()" in activity and "onRetainNonConfigurationInstance()" in activity
    assert "LOG_LIMIT = 400" in service and "line.length() > 2000" in service
    export = _java_method(service, "public static void exportServerLogs(Context context, Uri destination, String snapshot)")
    assert export.index("EXPORT_IO.execute(") < export.index("openOutputStream(")
    assert "LOGS" not in export and "runtime" not in export and "captureDiagnostics" not in export
    assert "export = button(R.string.export_diagnostics)" in activity
    assert 'setType("application/json")' in activity and '"IdolyPride-diagnostics.json"' in activity


def test_actual_android_export_and_exception_methods_on_host_java(tmp_path):
    import os
    import shutil
    import subprocess
    import pytest

    cached = ROOT.parent / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin"
    javac = cached / "javac" if (cached / "javac").is_file() else shutil.which("javac")
    java = cached / "java" if (cached / "java").is_file() else shutil.which("java")
    if not javac or not java:
        pytest.skip("Host JDK unavailable")
    activity = (JAVA / "MainActivity.java").read_text()
    service = (JAVA / "ServerService.java").read_text()
    request = _java_method(activity, "private void requestServerLogExport()")
    finish = _java_method(activity, "private void finishServerLogExport(int resultCode, Intent data)")
    export = _java_method(service, "public static void exportServerLogs(Context context, Uri destination, String snapshot)")
    frame_policy = _java_method(activity, "private static boolean infrastructureExceptionFrame(String frame)")
    frame_summary = _java_method(activity, "private static String exceptionFrameSummary(org.json.JSONArray frames)")
    harness = r"""import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.concurrent.atomic.AtomicBoolean;
public final class ServerLogExportHost {
 static final class Uri {}
 static final class Intent {
  static final String ACTION_CREATE_DOCUMENT="create",CATEGORY_OPENABLE="openable",EXTRA_TITLE="title";
  static final int FLAG_GRANT_WRITE_URI_PERMISSION=2;
  Uri uri; Intent(String action) {} Intent addCategory(String category) { return this; }
  Intent addFlags(int flags) { return this; } Intent setType(String type) { return this; }
  Intent putExtra(String key,String value) { return this; } Uri getData() { return uri; }
 }
 static final class R { static final class string {
  static final int export_picker_failed=1,server_logs_export_saved=2,server_logs_export_failed=3;
 } }
 static final class Toast {
  static final int LENGTH_LONG=1; static int shown; final int message;
  Toast(int message) { this.message=message; }
  static Toast makeText(Object context,int message,int duration) { return new Toast(message); }
  void show() { shown=message; }
 }
 static final class Log { static void w(String tag,String message) {} }
 static final class TrackingStream extends OutputStream {
  final ByteArrayOutputStream bytes=new ByteArrayOutputStream(); boolean closed,failWrite,failClose;
  public void write(int value) throws IOException {
   if (failWrite) throw new IOException("write failure"); bytes.write(value);
  }
  public void close() throws IOException { closed=true; if (failClose) throw new IOException("close failure"); }
 }
 static final class Resolver {
  TrackingStream stream=new TrackingStream(); int opens; boolean nullStream;
  OutputStream openOutputStream(Uri uri,String mode) {
   check("wt".equals(mode),"document truncation mode"); opens++; return nullStream?null:stream;
  }
 }
 static class Context {
  final Resolver resolver=new Resolver(); Context getApplicationContext() { return this; }
  Resolver getContentResolver() { return resolver; }
 }
 static final class Queue {
  final ArrayDeque<Runnable> tasks=new ArrayDeque<>(); void execute(Runnable task) { tasks.add(task); }
  void drain() { while (!tasks.isEmpty()) tasks.remove().run(); }
 }
 static final class Main { void post(Runnable task) { task.run(); } }
 static final class Text { String value=""; CharSequence getText() { return value; } }
 static final class Activity extends Context {
  static final int RESULT_OK=-1,EXPORT_SERVER_LOGS=50055;
  final Text logs=new Text(); String pendingServerLogSnapshot; boolean pickerFails;
  void startActivityForResult(Intent destination,int code) {
   check(code==EXPORT_SERVER_LOGS,"separate request");
   if (pickerFails) throw new IllegalStateException("no picker");
  }
""" + request + "\n" + finish + r"""
 }
 static final class ServerService {
  static final AtomicBoolean EXPORT_BUSY=new AtomicBoolean();
  static final Queue EXPORT_IO=new Queue(); static final Main MAIN=new Main();
  static void dispatch() {}
""" + export + r"""
 }
 static final class org { static final class json { static final class JSONArray {
  final String[] values; int maxRead=-1; JSONArray(String... values) { this.values=values; }
  int length() { return values.length; }
  String optString(int index,String fallback) { maxRead=Math.max(maxRead,index); return values[index]==null?fallback:values[index]; }
 } } }
""" + frame_policy + "\n" + frame_summary + r"""
 static void check(boolean valid,String message) { if (!valid) throw new AssertionError(message); }
 static Intent picked() { Intent data=new Intent("result"); data.uri=new Uri(); return data; }
 static void idle() { check(!ServerService.EXPORT_BUSY.get()&&ServerService.EXPORT_IO.tasks.isEmpty(),"idle export"); }
 public static void main(String[] args) {
  Activity activity=new Activity(); String original="서버 시작\nHTTP 200 · 파일 전송";
  activity.logs.value=original; activity.requestServerLogExport();
  activity.logs.value="later visible records"; String visible=activity.logs.value;
  activity.finishServerLogExport(-1,picked());
  check(activity.pendingServerLogSnapshot==null,"pending snapshot consumed");
  check(activity.resolver.opens==0&&ServerService.EXPORT_IO.tasks.size()==1,"I/O deferred");
  check(ServerService.EXPORT_BUSY.get(),"export busy");
  ServerService.exportServerLogs(activity,new Uri(),"second export must not queue");
  check(ServerService.EXPORT_IO.tasks.size()==1,"busy gate");
  ServerService.EXPORT_IO.drain(); idle();
  check(original.equals(new String(activity.resolver.stream.bytes.toByteArray(),StandardCharsets.UTF_8)),"exact UTF-8 click snapshot");
  check(activity.resolver.stream.closed&&Toast.shown==R.string.server_logs_export_saved,"closed successful document");
  check(visible.equals(activity.logs.value),"success preserves visible logs");
  int opens=activity.resolver.opens;
  activity.requestServerLogExport(); activity.finishServerLogExport(0,null); idle();
  check(activity.pendingServerLogSnapshot==null&&activity.resolver.opens==opens,"cancel has no write");
  activity.requestServerLogExport(); activity.finishServerLogExport(-1,null); idle();
  activity.requestServerLogExport(); activity.finishServerLogExport(-1,new Intent("missing URI")); idle();
  check(activity.resolver.opens==opens&&visible.equals(activity.logs.value),"null result preserves records");
  activity.pickerFails=true; activity.requestServerLogExport(); idle();
  check(activity.pendingServerLogSnapshot==null&&Toast.shown==R.string.export_picker_failed,"picker failure clears only pending");
  activity.pickerFails=false;
  for (int failure=0;failure<3;failure++) {
   activity.resolver.stream=new TrackingStream(); activity.resolver.stream.failWrite=failure==0;
   activity.resolver.stream.failClose=failure==1; activity.resolver.nullStream=failure==2;
   activity.requestServerLogExport(); activity.finishServerLogExport(-1,picked());
   ServerService.EXPORT_IO.drain(); idle();
   check(Toast.shown==R.string.server_logs_export_failed,"write/close/null-stream failure reported");
   check(failure==2||activity.resolver.stream.closed,"failure closes document");
   check(visible.equals(activity.logs.value),"failure preserves visible logs");
  }
  ServerService.exportServerLogs(activity,new Uri(),null); idle();
  check(Toast.shown==R.string.server_logs_export_failed,"missing retained snapshot fails safely");
  String caller="Game.Home.ShowIn";
  for (String prefix:new String[]{"System.","Cysharp.Threading.Tasks.","UnityEngine.","Unity.","Google.Protobuf.","Grpc."}) {
   String first=prefix+"Infrastructure"; org.json.JSONArray frames=new org.json.JSONArray(first,"", "UnityEngine.Wait",caller);
   check((caller+" ["+first+"]").equals(exceptionFrameSummary(frames)),"first game caller with infrastructure origin");
   check(first.equals(frames.values[0])&&caller.equals(frames.values[3]),"frames remain unchanged");
  }
  check(caller.equals(exceptionFrameSummary(new org.json.JSONArray(caller,"Other.Caller"))),"game first unchanged");
  check("System.Linq.Where".equals(exceptionFrameSummary(new org.json.JSONArray("System.Linq.Where","Unity.Wait"))),"all infrastructure fallback");
  check("".equals(exceptionFrameSummary(null))&&"".equals(exceptionFrameSummary(new org.json.JSONArray())),"empty unchanged");
  check("".equals(exceptionFrameSummary(new org.json.JSONArray("",caller))),"empty first unchanged");
  String[] longFrames=new String[18]; java.util.Arrays.fill(longFrames,"System.Wait"); longFrames[16]=caller;
  org.json.JSONArray bounded=new org.json.JSONArray(longFrames);
  check("System.Wait".equals(exceptionFrameSummary(bounded))&&bounded.maxRead==15,"at most sixteen frames");
  longFrames[15]=caller;
  check((caller+" [System.Wait]").equals(exceptionFrameSummary(new org.json.JSONArray(longFrames))),"sixteenth frame included");
  System.out.println("server record export and exception caller checks passed");
 }
}
"""
    source = tmp_path / "ServerLogExportHost.java"
    source.write_text(harness)
    flags = ["-Xms16m", "-Xmx64m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
             "-XX:MaxMetaspaceSize=48m", "-XX:CompressedClassSpaceSize=8m", "-XX:ReservedCodeCacheSize=16m"]
    env = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"):
        env.pop(key, None)
    subprocess.run([str(javac), *("-J" + flag for flag in flags), "-encoding", "UTF-8", "-d", str(tmp_path), str(source)],
                   check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(java), *flags, "-cp", str(tmp_path), "ServerLogExportHost"],
                            check=True, text=True, capture_output=True, timeout=10, env=env)
    assert "server record export and exception caller checks passed" in result.stdout
