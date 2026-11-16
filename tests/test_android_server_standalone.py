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
    for control in ["addPlaybackControls(", "addPresentationControls(",
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
    assert len(routes) == 1  # One game launch action; graphics has no duplicate.
    assert all(re.findall(r'"([^"]+)"', route) == [
        "game.qualiarts.idolypride.local.diagnostics"] for route in routes)
    assert activity.count("button(R.string.launch_diagnostic_client)") == 1
    assert "button(R.string.launch_client)" not in activity
    assert "button(R.string.presentation_launch_button)" not in activity
    assert labels["launch_diagnostic_client"] == "아이프라 실행"
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


def test_combined_diagnostics_export_contains_server_records_in_one_document():
    activity = (JAVA / "MainActivity.java").read_text()
    service = (JAVA / "ServerService.java").read_text()
    labels = {node.get("name"): node.text for node in ET.parse(MAIN / "res/values/strings.xml").getroot().findall("string")}
    assert labels["export_diagnostics"] == "진단·서버 기록 내보내기"
    assert activity.count("export = button(R.string.export_diagnostics)") == 1
    assert "button(R.string.export_server_logs)" not in activity
    assert "EXPORT_SERVER_LOGS" not in activity and "pendingServerLogSnapshot" not in activity
    request = _java_method(activity, "private void requestDiagnosticsExport()")
    finish = _java_method(activity, "private void finishDiagnosticsExport(int resultCode, Intent data)")
    assert "Intent.ACTION_CREATE_DOCUMENT" in request and "Intent.CATEGORY_OPENABLE" in request
    assert 'setType("application/json")' in request and '"IdolyPride-diagnostics.json"' in request
    assert "Intent.FLAG_GRANT_WRITE_URI_PERMISSION" in request
    assert "startActivityForResult(destination, EXPORT_DIAGNOSTICS)" in request
    assert "ServerService.exportDiagnostics(getApplicationContext(), destination)" in finish
    assert "LOG_LIMIT = 400" in service and "line.length() > 2000" in service
    export = _java_method(service, "private static void writeExport(Context context, Uri destination, String snapshot)")
    assert export.index("EXPORT_IO.execute(") < export.index("openOutputStream(")
    for field in ("runtime", "diagnostics", "server_logs", "server_version", "bundled_data_sha256"):
        assert 'document.put("' + field + '"' in export


def test_actual_combined_android_export_and_exception_methods_on_host_java(tmp_path):
    import base64
    import json
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
    request = _java_method(activity, "private void requestDiagnosticsExport()")
    finish = _java_method(activity, "private void finishDiagnosticsExport(int resultCode, Intent data)")
    capture = _java_method(service, "private String captureDiagnostics()")
    export = _java_method(service, "public static void exportDiagnostics(Context context, Uri destination)")
    write = _java_method(service, "private static void writeExport(Context context, Uri destination, String snapshot)")
    frame_policy = _java_method(activity, "private static boolean infrastructureExceptionFrame(String frame)")
    frame_summary = _java_method(activity, "private static String exceptionFrameSummary(org.json.JSONArray frames)")
    # Native APIs and JSON construction are seams. The shipping export methods
    # execute unchanged; Python independently parses the exact document bytes.
    harness = r"""import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
public final class CombinedDiagnosticExportHost {
 static final class Uri {}
 static final class Intent {
  static final String ACTION_CREATE_DOCUMENT="create",CATEGORY_OPENABLE="openable",EXTRA_TITLE="title";
  static final int FLAG_GRANT_WRITE_URI_PERMISSION=2;
  Uri uri; String action,category,type,title; int flags;
  Intent(String action) { this.action=action; }
  Intent addCategory(String category) { this.category=category;return this; }
  Intent addFlags(int flags) { this.flags|=flags;return this; }
  Intent setType(String type) { this.type=type;return this; }
  Intent putExtra(String key,String value) { check(EXTRA_TITLE.equals(key),"document title");this.title=value;return this; }
  Uri getData() { return uri; }
 }
 static final class R { static final class string {
  static final int export_picker_failed=1,export_saved=2,export_failed=3;
 } }
 static final class BuildConfig {
  static final String VERSION_NAME="fixture-version",SERVER_DATA_SHA256="fixture-data-sha";
  static final int VERSION_CODE=52;
 }
 static final class Toast {
  static final int LENGTH_LONG=1;static int shown;final int message;
  Toast(int message) { this.message=message; }
  static Toast makeText(Object context,int message,int duration) { return new Toast(message); }
  void show() { shown=message; }
 }
 static final class Log { static void w(String tag,String message) {} }
 static final class TrackingStream extends OutputStream {
  final ByteArrayOutputStream bytes=new ByteArrayOutputStream();boolean closed,failWrite,failClose;
  public void write(int value) throws IOException {
   if(failWrite)throw new IOException("write failure");bytes.write(value);
  }
  public void close() throws IOException { closed=true;if(failClose)throw new IOException("close failure"); }
 }
 static final class Resolver {
  TrackingStream stream=new TrackingStream();int opens;boolean nullStream;
  OutputStream openOutputStream(Uri uri,String mode) {
   check(uri!=null&&"wt".equals(mode),"chosen document truncation mode");opens++;return nullStream?null:stream;
  }
 }
 static class Context {
  final Resolver resolver=new Resolver();Context getApplicationContext() { return this; }
  Resolver getContentResolver() { return resolver; }
 }
 static final class Queue {
  final ArrayDeque<Runnable> tasks=new ArrayDeque<>();boolean rejected;
  void execute(Runnable task) { if(rejected)throw new RejectedExecutionException("stopped worker");tasks.add(task); }
  void drain() { while(!tasks.isEmpty())tasks.remove().run(); }
 }
 static final class Main { void post(Runnable task) { task.run(); } }
 static String quote(String value) {
  StringBuilder result=new StringBuilder("\"");
  for(int i=0;i<value.length();i++) {
   char c=value.charAt(i);
   switch(c) {
    case '"':result.append("\\\"");break;case '\\':result.append("\\\\");break;
    case '\n':result.append("\\n");break;case '\r':result.append("\\r");break;
    case '\t':result.append("\\t");break;
    default:if(c<32)result.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else result.append(c);
   }
  }
  return result.append('"').toString();
 }
 static String encode(Object value) {
  if(value==null)return "null";
  if(value instanceof String)return quote((String)value);
  return value.toString();
 }
 static final class JSONObject {
  final LinkedHashMap<String,Object> fields=new LinkedHashMap<>();final String raw;
  JSONObject() { raw=null; }
  JSONObject(String raw) {
   if(raw==null||!raw.startsWith("{")||!raw.endsWith("}"))throw new IllegalArgumentException("object fixture");
   this.raw=raw;
  }
  JSONObject put(String key,Object value) { fields.put(key,value);return this; }
  public String toString() {
   if(raw!=null)return raw;
   StringJoiner result=new StringJoiner(",","{","}");
   fields.forEach((key,value)->result.add(quote(key)+":"+encode(value)));return result.toString();
  }
  String toString(int indentation) { return toString(); }
 }
 static final class JSONArray {
  final List<?> values;JSONArray(List<?> values) { this.values=new ArrayList<>(values); }
  public String toString() {
   StringJoiner result=new StringJoiner(",","[","]");for(Object value:values)result.add(encode(value));return result.toString();
  }
 }
 static final class RuntimeSnapshot {
  String value;int calls;boolean failed;
  RuntimeSnapshot(String value) { this.value=value; }
  String callAttr(String method) {
   check("diagnostics_json".equals(method),"diagnostic capture command");calls++;
   if(failed)throw new IllegalStateException("capture unavailable");return value;
  }
 }
 static final class Activity extends Context {
  static final int RESULT_OK=-1,EXPORT_DIAGNOSTICS=50052;boolean pickerFails;Intent shown;int requestCode;
  void startActivityForResult(Intent destination,int code) {
   if(pickerFails)throw new IllegalStateException("no picker");shown=destination;requestCode=code;
  }
""" + request + "\n" + finish + r"""
 }
 static final class ServerService {
  static final AtomicBoolean EXPORT_BUSY=new AtomicBoolean();
  static final Queue EXPORT_IO=new Queue();static final Main MAIN=new Main();
  static final ArrayDeque<String> LOGS=new ArrayDeque<>();
  static String runtimeDetails="{}",lastDiagnostics="{}";static ServerService activeService;
  final Queue worker=new Queue();RuntimeSnapshot runtime;boolean destroyed;
  static void dispatch() {}
  static JSONObject readServerSettings(Context context) {
   return new JSONObject("{\"startup_checks\":{\"scope\":\"previous_run\"},\"durable_history\":{\"retained_records\":3}}");
  }
""" + capture + "\n" + export + "\n" + write + r"""
 }
 static final class org { static final class json { static final class JSONArray {
  final String[] values;int maxRead=-1;JSONArray(String... values) { this.values=values; }
  int length() { return values.length; }
  String optString(int index,String fallback) { maxRead=Math.max(maxRead,index);return values[index]==null?fallback:values[index]; }
 } } }
""" + frame_policy + "\n" + frame_summary + r"""
 static void check(boolean valid,String message) { if(!valid)throw new AssertionError(message); }
 static Intent picked() { Intent data=new Intent("result");data.uri=new Uri();return data; }
 static void idle() { check(!ServerService.EXPORT_BUSY.get()&&ServerService.EXPORT_IO.tasks.isEmpty(),"idle export"); }
 static void emit(Activity activity) {
  check(activity.resolver.stream.closed&&Toast.shown==R.string.export_saved,"closed successful document");
  System.out.println("JSON:"+Base64.getEncoder().encodeToString(activity.resolver.stream.bytes.toByteArray()));
 }
 static void freshStream(Activity activity) {
  activity.resolver.stream=new TrackingStream();activity.resolver.nullStream=false;
 }
 public static void main(String[] args) {
  Activity activity=new Activity();
  activity.requestDiagnosticsExport();
  check("create".equals(activity.shown.action)&&"openable".equals(activity.shown.category),"explicit document picker");
  check("application/json".equals(activity.shown.type)&&"IdolyPride-diagnostics.json".equals(activity.shown.title),"one JSON document");
  check(activity.shown.flags==Intent.FLAG_GRANT_WRITE_URI_PERMISSION&&activity.requestCode==Activity.EXPORT_DIAGNOSTICS,"write grant and diagnostic request");
  activity.finishDiagnosticsExport(0,null);activity.finishDiagnosticsExport(-1,null);
  activity.finishDiagnosticsExport(-1,new Intent("missing URI"));idle();
  check(activity.resolver.opens==0,"cancel and absent URI do not write");
  activity.pickerFails=true;activity.requestDiagnosticsExport();
  check(Toast.shown==R.string.export_picker_failed,"picker failure reported");idle();activity.pickerFails=false;

  ServerService service=new ServerService();service.runtime=new RuntimeSnapshot("{\"phase\":\"home\",\"received_events\":7}");
  ServerService.activeService=service;ServerService.runtimeDetails="{\"running\":true,\"http\":{\"completed\":3}}";
  List<String> original=List.of("서버 시작\nHTTP 200 · 파일 전송","quote \" and slash \\");
  ServerService.LOGS.addAll(original);
  activity.finishDiagnosticsExport(-1,picked());
  check(service.worker.tasks.size()==1&&ServerService.EXPORT_IO.tasks.isEmpty()&&activity.resolver.opens==0,"capture on service worker before document I/O");
  check(ServerService.EXPORT_BUSY.get(),"export busy");
  ServerService.exportDiagnostics(activity,new Uri());
  check(service.worker.tasks.size()==1,"busy export must not queue twice");
  service.worker.drain();
  check(service.runtime.calls==1&&ServerService.EXPORT_IO.tasks.size()==1&&activity.resolver.opens==0,"write deferred off capture worker");
  ServerService.LOGS.clear();ServerService.LOGS.add("later visible records");ServerService.runtimeDetails="{\"running\":false}";
  ServerService.EXPORT_IO.drain();idle();emit(activity);
  check(ServerService.LOGS.size()==1&&ServerService.LOGS.peek().equals("later visible records"),"success preserves newer server records");

  freshStream(activity);ServerService.activeService=null;ServerService.runtimeDetails="{\"running\":false}";
  ServerService.LOGS.clear();ServerService.LOGS.add("보관된 기록");
  ServerService.exportDiagnostics(activity,new Uri());
  check(service.worker.tasks.isEmpty()&&ServerService.EXPORT_IO.tasks.size()==1,"stopped service uses retained diagnostic snapshot");
  ServerService.EXPORT_IO.drain();idle();emit(activity);

  freshStream(activity);ServerService.activeService=service;service.worker.rejected=true;
  ServerService.lastDiagnostics="{\"phase\":\"retained\"}";ServerService.LOGS.clear();ServerService.LOGS.add("retained log");
  ServerService.exportDiagnostics(activity,new Uri());
  check(service.worker.tasks.isEmpty()&&ServerService.EXPORT_IO.tasks.size()==1&&service.runtime.calls==1,"rejected capture worker falls back");
  ServerService.EXPORT_IO.drain();idle();emit(activity);

  freshStream(activity);service.worker.rejected=false;service.runtime.failed=true;
  ServerService.exportDiagnostics(activity,new Uri());service.worker.drain();
  check(service.runtime.calls==2&&ServerService.EXPORT_IO.tasks.size()==1,"capture exception uses retained snapshot");
  ServerService.EXPORT_IO.drain();idle();emit(activity);

  ServerService.activeService=null;
  for(int failure=0;failure<3;failure++) {
   freshStream(activity);activity.resolver.stream.failWrite=failure==0;
   activity.resolver.stream.failClose=failure==1;activity.resolver.nullStream=failure==2;
   ServerService.exportDiagnostics(activity,new Uri());ServerService.EXPORT_IO.drain();idle();
   check(Toast.shown==R.string.export_failed,"write/close/null-stream failure reported");
   check(failure==2||activity.resolver.stream.closed,"failure closes document");
   check(ServerService.LOGS.peek().equals("retained log"),"failure preserves retained records");
  }
  String caller="Game.Home.ShowIn";
  for(String prefix:new String[]{"System.","Cysharp.Threading.Tasks.","UnityEngine.","Unity.","Google.Protobuf.","Grpc."}) {
   String first=prefix+"Infrastructure";org.json.JSONArray frames=new org.json.JSONArray(first,"","UnityEngine.Wait",caller);
   check((caller+" ["+first+"]").equals(exceptionFrameSummary(frames)),"first game caller with infrastructure origin");
   check(first.equals(frames.values[0])&&caller.equals(frames.values[3]),"frames remain unchanged");
  }
  check(caller.equals(exceptionFrameSummary(new org.json.JSONArray(caller,"Other.Caller"))),"game first unchanged");
  check("System.Linq.Where".equals(exceptionFrameSummary(new org.json.JSONArray("System.Linq.Where","Unity.Wait"))),"all infrastructure fallback");
  check("".equals(exceptionFrameSummary(null))&&"".equals(exceptionFrameSummary(new org.json.JSONArray())),"empty unchanged");
  check("".equals(exceptionFrameSummary(new org.json.JSONArray("",caller))),"empty first unchanged");
  String[] longFrames=new String[18];java.util.Arrays.fill(longFrames,"System.Wait");longFrames[16]=caller;
  org.json.JSONArray bounded=new org.json.JSONArray(longFrames);
  check("System.Wait".equals(exceptionFrameSummary(bounded))&&bounded.maxRead==15,"at most sixteen frames");
  longFrames[15]=caller;
  check((caller+" [System.Wait]").equals(exceptionFrameSummary(new org.json.JSONArray(longFrames))),"sixteenth frame included");
  System.out.println("combined diagnostic export and exception caller checks passed");
 }
}
"""
    source = tmp_path / "CombinedDiagnosticExportHost.java"
    source.write_text(harness)
    flags = ["-Xms16m", "-Xmx64m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
             "-XX:MaxMetaspaceSize=48m", "-XX:CompressedClassSpaceSize=8m", "-XX:ReservedCodeCacheSize=16m"]
    env = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"):
        env.pop(key, None)
    subprocess.run([str(javac), *("-J" + flag for flag in flags), "-encoding", "UTF-8", "-d", str(tmp_path), str(source)],
                   check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(java), *flags, "-cp", str(tmp_path), "CombinedDiagnosticExportHost"],
                            check=True, text=True, capture_output=True, timeout=10, env=env)
    assert "combined diagnostic export and exception caller checks passed" in result.stdout
    documents = [json.loads(base64.b64decode(line.removeprefix("JSON:"), validate=True))
                 for line in result.stdout.splitlines() if line.startswith("JSON:")]
    assert len(documents) == 4
    for document in documents:
        assert set(document) == {"schema", "server_version", "server_version_code", "bundled_data_sha256",
                                 "runtime", "diagnostics", "server_logs", "server_settings"}
        assert document["schema"] == 1 and document["server_version"] == "fixture-version"
        assert document["server_settings"] == {"startup_checks": {"scope": "previous_run"}, "durable_history": {"retained_records": 3}}
        assert document["server_version_code"] == 52 and document["bundled_data_sha256"] == "fixture-data-sha"
    assert documents[0]["runtime"] == {"running": True, "http": {"completed": 3}}
    assert documents[0]["diagnostics"] == {"phase": "home", "received_events": 7}
    assert documents[0]["server_logs"] == ["서버 시작\nHTTP 200 · 파일 전송", 'quote " and slash \\']
    assert documents[1]["runtime"] == {"running": False}
    assert documents[1]["diagnostics"] == documents[0]["diagnostics"]
    assert documents[1]["server_logs"] == ["보관된 기록"]
    assert all(document["diagnostics"] == {"phase": "retained"} and document["server_logs"] == ["retained log"]
               for document in documents[2:])
