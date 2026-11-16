"""Compile the production native transfer worker against synthetic queue/bridge stubs.

This exercises the actual Java method, no Android device or official network.
"""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/ServerService.java"


def method(source, marker):
    begin = source.index(marker)
    brace = source.index("{", begin)
    depth = 1
    cursor = brace + 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[begin:cursor]


def test_official_native_worker_releases_credentials_and_keeps_all_python_io_off_the_ui_thread(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The required native worker harness needs a JDK"
    production = SERVICE.read_text()
    actual = method(production, "    static void officialImport(")
    failure = method(production, "    private static JSONObject accountFailure(")
    source = r''' 
import java.io.File;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.lang.reflect.Field;

public final class OfficialWorkerHarness {
 static boolean worker;
 static void check(boolean condition,String code) { if(!condition)throw new AssertionError(code); }
 static final Object PYTHON_LOCK=new Object();
 static final AtomicBoolean OFFICIAL_BUSY=new AtomicBoolean();
 static final Queue OFFICIAL_IO=new Queue(true),MAIN=new Queue(false);
 interface AccountCallback { void completed(JSONObject result); }
 static final class Queue {
  final ArrayDeque<Runnable> tasks=new ArrayDeque<>();final boolean background;boolean reject;
  Queue(boolean background) { this.background=background; }
  void execute(Runnable task) { if(reject)throw new RejectedExecutionException();tasks.add(task); }
  void post(Runnable task) { tasks.add(task); }
  void drain() {
   while(!tasks.isEmpty()) {
    boolean previous=worker;worker=background;
    try { tasks.remove().run(); } finally { worker=previous; }
   }
  }
 }
 static final class Context {
  final Object assets=new Object();
  Context getApplicationContext() { return this; }
  File getFilesDir() { return new File("/synthetic-app-files"); }
  Object getAssets() { return assets; }
 }
 static final class AndroidPlatform {
  AndroidPlatform(Context context) { check(worker,"Python initialization on UI thread"); }
 }
 static final class Python {
  static boolean started;static final Python instance=new Python();static final PyObject module=new PyObject(null);
  static boolean isStarted() { check(worker,"Python inspection on UI thread");return started; }
  static void start(AndroidPlatform platform) { check(worker,"Python start on UI thread");started=true; }
  static Python getInstance() { check(worker,"Python lookup on UI thread");return instance; }
  PyObject getModule(String name) { check(worker&&name.equals("android_server_runtime"),"wrong native module");return module; }
 }
 static final class PyObject {
  static Object[] args;static int calls;static boolean fail;static String response="{\"schema\":1,\"ok\":true,\"job\":{\"state\":\"checking\"}}";
  final String raw;PyObject(String raw) { this.raw=raw; }
  PyObject callAttr(String name,Object... values) {
   check(worker&&name.equals("official_command_json"),"wrong Python command/thread");calls++;args=values.clone();
   if(fail)throw new IllegalArgumentException("fakecanarypassword must never reach callbacks");
   return new PyObject(response);
  }
  public String toString() { return raw; }
 }
 static final class org { static final class json { static final class JSONException extends Exception {} } }
 static final class JSONObject {
  final LinkedHashMap<String,Object> fields=new LinkedHashMap<>();final String raw;
  JSONObject() { raw=null; }
  JSONObject(String value) { check(value.startsWith("{")&&value.endsWith("}"),"invalid JSON response fixture");raw=value; }
  JSONObject put(String name,Object value) throws org.json.JSONException { fields.put(name,value);return this; }
  Object remove(String name) { return fields.remove(name); }
  static String quote(String value) { return "\""+value.replace("\\","\\\\").replace("\"","\\\"")+"\""; }
  public String toString() {
   if(raw!=null)return raw;
   StringJoiner result=new StringJoiner(",","{","}");
   fields.forEach((key,value)->result.add(quote(key)+":"+(value instanceof String?quote((String)value):String.valueOf(value))));
   return result.toString();
  }
 }
''' + failure + "\n" + actual + r''' 
 static JSONObject credentials() throws Exception {
  return new JSONObject().put("user_id","Synthetic-ID").put("password","fakecanarypassword With Space").put("platform","android");
 }
 static String[] requestHolder(Runnable task) throws Exception {
  for(Field field:task.getClass().getDeclaredFields())if(field.getType()==String[].class) {
   field.setAccessible(true);return (String[])field.get(task);
  }
  throw new AssertionError("worker must expose its transient request holder to this whitebox harness");
 }
 public static void main(String[] unused) throws Exception {
  Context context=new Context();List<String> results=new ArrayList<>();AccountCallback callback=result->results.add(result.toString());
  JSONObject input=credentials();String expected=input.toString();
  officialImport(context,"official_inspect",input,callback);
  check(!input.fields.containsKey("user_id")&&!input.fields.containsKey("password"),"caller retains credentials");
  check(OFFICIAL_BUSY.get()&&OFFICIAL_IO.tasks.size()==1&&MAIN.tasks.isEmpty()&&PyObject.calls==0,"worker was not asynchronous");
  Runnable submitted=OFFICIAL_IO.tasks.peek();String[] holder=requestHolder(submitted);
  check(holder[0].equals(expected),"credential bytes/case/spaces changed");
  JSONObject duplicate=credentials();officialImport(context,"official_inspect",duplicate,callback);
  check(!duplicate.fields.containsKey("password")&&!duplicate.fields.containsKey("user_id"),"busy caller retains credentials");
  check(OFFICIAL_IO.tasks.size()==1,"duplicate network operation scheduled");MAIN.drain();
  check(results.size()==1&&results.get(0).contains("official_operation_busy"),"busy response unavailable");results.clear();
  OFFICIAL_IO.drain();check(PyObject.calls==1&&holder[0]==null&&!OFFICIAL_BUSY.get(),"worker retains its serialized credentials");
  check(results.isEmpty()&&MAIN.tasks.size()==1,"callback bypassed the UI queue");
  check(PyObject.args.length==4&&PyObject.args[0].equals("/synthetic-app-files")&&PyObject.args[1].equals("official_inspect")&&PyObject.args[2].equals(expected)&&PyObject.args[3]==context.assets,"native boundary arguments differ");
  PyObject.args=null;MAIN.drain();check(results.size()==1&&results.get(0).contains("checking")&&!results.get(0).contains("fakecanary"),"success callback leaked credentials");results.clear();
  PyObject.fail=true;input=credentials();officialImport(context,"official_inspect",input,callback);holder=requestHolder(OFFICIAL_IO.tasks.peek());OFFICIAL_IO.drain();
  check(holder[0]==null&&!OFFICIAL_BUSY.get(),"failed worker retained request or busy state");MAIN.drain();
  check(results.size()==1&&results.get(0).contains("official_operation_failed")&&!results.get(0).contains("fakecanary"),"exception detail escaped into callback");results.clear();PyObject.fail=false;PyObject.args=null;
  PyObject.response="{\"padding\":\""+"x".repeat(2*1024*1024)+"\"}";
  officialImport(context,"official_status",new JSONObject(),callback);holder=requestHolder(OFFICIAL_IO.tasks.peek());OFFICIAL_IO.drain();MAIN.drain();
  check(holder[0]==null&&!OFFICIAL_BUSY.get()&&results.size()==1&&results.get(0).contains("official_operation_failed"),"oversized native response escaped");results.clear();PyObject.response="{}";PyObject.args=null;
  OFFICIAL_IO.reject=true;input=credentials();officialImport(context,"official_inspect",input,callback);
  check(!OFFICIAL_BUSY.get()&&OFFICIAL_IO.tasks.isEmpty()&&!input.fields.containsKey("password"),"rejection failed cleanup");MAIN.drain();
  check(results.size()==1&&results.get(0).contains("official_operation_failed")&&!results.get(0).contains("fakecanary"),"rejection response leaked");
  System.out.println("official-service-harness PASS");
 }
}
'''
    unit = tmp_path / "OfficialWorkerHarness.java"
    unit.write_text(source)
    built = subprocess.run([javac, "-encoding", "UTF-8", "--release", "17", str(unit)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([java, "-cp", str(tmp_path), "OfficialWorkerHarness"], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout.strip() == "official-service-harness PASS"
