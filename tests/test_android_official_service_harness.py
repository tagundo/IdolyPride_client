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



def test_official_ui_polling_quiets_idle_and_unchanged_jobs_and_unblocks_terminal_workers(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The required native UI polling harness needs a JDK"
    activity = (ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java").read_text()
    declarations = [method(activity, "    private final Runnable officialRefresh =") + ";"]
    declarations += [method(activity, marker) for marker in (
        "    private boolean shouldPollOfficial(", "    private void scheduleOfficialRefresh(",
        "    private boolean officialJobChanged(", "    private void renderOfficialJob(",
        "    private void updateOfficialControls(", "    private static JSONObject accountPayload(",
        "    private boolean deferOfficialSubmission(", "    private void clearDeferredOfficial(",
        "    private void drainDeferredOfficial(")]
    source = r'''
import java.util.*;
public final class OfficialPollingHarness {
 static int writes;
 static void check(boolean value,String message) { if(!value)throw new AssertionError(message); }
 static final int TEXT_PRIMARY=1,WARNING=2,OFFICIAL_WARNING_CLEANUP=1,OFFICIAL_WARNING_REFRESH=2;
 static final class View { static final int VISIBLE=0,GONE=8; }
 static class Control {
  boolean enabled=true;int visibility=View.VISIBLE;
  void setEnabled(boolean value) { if(enabled!=value) { enabled=value;writes++; } }
  void setVisibility(int value) { if(visibility!=value) { visibility=value;writes++; } }
 }
 static class Label extends Control {
  final LinkedHashMap<Runnable,Long> timers=new LinkedHashMap<>();
  void setText(Object value) { writes++; }
  void setText(int value) { writes++; }
  void setTextColor(int value) { writes++; }
  void removeCallbacks(Runnable value) { timers.remove(value); }
  void postDelayed(Runnable value,long delay) { check(delay>=2000,"too-frequent native poll");timers.put(value,delay); }
  void fire() { check(timers.size()==1,"poll timer not singular");Runnable next=timers.keySet().iterator().next();timers.remove(next);next.run(); }
 }
 static final class CheckBox { boolean checked;boolean isChecked(){return checked;} }
 static final class R { static final class string {
  static final int official_preview=1,official_counts=2,official_expiry=3,official_ready_notice=4,
   official_completed_notice=5,official_committed_cleanup=6,official_committed_refresh=7,official_completed_short=8;
 } }
 static final class org { static final class json { static final class JSONException extends Exception {} } }
 static final class JSONObject {
  static final Object NULL=new Object();final LinkedHashMap<String,Object> fields=new LinkedHashMap<>();
  JSONObject put(String key,Object value) throws org.json.JSONException { fields.put(key,value);return this; }
  Object remove(String key) { return fields.remove(key); }
  String optString(String key) { return optString(key,""); }
  String optString(String key,String fallback) { Object value=fields.get(key);return value==null||value==NULL?fallback:String.valueOf(value); }
  boolean optBoolean(String key,boolean fallback) { Object value=fields.get(key);return value instanceof Boolean?(Boolean)value:fallback; }
  int optInt(String key) { return optInt(key,0); }
  int optInt(String key,int fallback) { Object value=fields.get(key);return value instanceof Integer?(Integer)value:fallback; }
  JSONObject optJSONObject(String key) { Object value=fields.get(key);return value instanceof JSONObject?(JSONObject)value:null; }
  static String quote(String value) { return "\""+value.replace("\\","\\\\").replace("\"","\\\"")+"\""; }
  public String toString() {
   StringJoiner result=new StringJoiner(",","{","}");fields.forEach((key,value)->result.add(quote(key)+":"+
    (value==NULL?"null":value instanceof String?quote((String)value):String.valueOf(value))));return result.toString();
  }
 }
 static final class ServerService {
  static boolean busy,managing;
  static boolean isImportingOfficial(){return busy;}
  static boolean isManagingAccounts(){return managing;}
 }
 boolean presentationObserved=true,officialRequest,officialPolling,presentationServerRunning,accountLifecycleBusy;
 int officialWarnings,officialLastError,queries,submissions;
 String officialRenderedJob,officialDeferredAction,lastAction;
 JSONObject officialJob=new JSONObject(),officialAppliedAccount,officialDeferredPayload,accountStatus=new JSONObject(),target;
 Object officialCredentials,officialWizardDialog;
 CheckBox mediaMode=new CheckBox();
 Label officialStatus=new Label(),officialPreview=new Label();
 Control officialProgress=new Control(),officialInspect=new Control(),officialFetch=new Control(),officialNew=new Control(),
  officialReplace=new Control(),officialCancel=new Control(),officialSelect=new Control(),officialNormal=new Control(),officialLocalRefresh=new Control();
 JSONObject selectedAccount(){return target;}
 int officialStage(String value){return 100;}
 int officialError(String value){return 200;}
 String getString(int id,Object... args){return id+Arrays.toString(args);}
 void requestOfficial(String action,JSONObject payload,boolean poll){
  if(poll){queries++;officialRequest=true;officialPolling=true;ServerService.busy=true;updateOfficialControls();}
  else {submissions++;lastAction=action;}
 }
 void complete(JSONObject job){
  officialRequest=false;officialPolling=false;ServerService.busy=false;officialJob=job;renderOfficialJob();drainDeferredOfficial();
 }
''' + "\n".join(declarations) + r'''
 static JSONObject job(String state,boolean busy,String progress,int expiry) throws Exception {
  return new JSONObject().put("schema",1).put("state",state).put("busy",busy).put("job_id","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
   .put("progress",progress).put("expires_in_seconds",expiry).put("error_code",JSONObject.NULL)
   .put("counts",new JSONObject().put("cards",1).put("items",2).put("photos",3));
 }
 public static void main(String[] unused) throws Exception {
  OfficialPollingHarness h=new OfficialPollingHarness();h.renderOfficialJob();writes=0;
  h.officialRefresh.run();check(h.queries==1&&writes==0,"initial status query repainted idle controls");
  h.complete(job("idle",false,"idle",0));check(h.officialStatus.timers.isEmpty(),"idle job kept polling");
  int idleQueries=h.queries;check(idleQueries==1,"idle issued duplicate queries");
  h.officialJob=job("checking",true,"checking",590);h.renderOfficialJob();check(h.officialStatus.timers.size()==1,"checking not polled");
  writes=0;h.officialStatus.fire();check(writes==0,"status pending toggled native views");
  h.complete(job("checking",true,"checking",580));check(writes==0&&h.officialStatus.timers.size()==1,"expiry-only update repainted views or lost timer");
  h.complete(job("fetching",true,"account",570));check(writes>0&&h.officialStatus.timers.size()==1,"real progress not rendered");
  h.complete(job("verified",false,"verified",560));writes=0;h.officialStatus.fire();h.complete(job("verified",false,"verified",550));
  check(writes==0,"verified countdown repainted views");
  h.complete(job("ready",false,"ready",540));writes=0;h.officialStatus.fire();h.complete(job("ready",false,"ready",530));
  check(writes==0,"ready countdown repainted views");
  h.officialJob.put("preview",new JSONObject().put("manager_name","synthetic").put("manager_level",2).put("public_id","synthetic-public"));
  h.renderOfficialJob();check(writes>0,"preview change omitted");writes=0;
  h.officialJob.put("counts",new JSONObject().put("cards",4).put("items",2).put("photos",3));h.renderOfficialJob();check(writes>0,"count change omitted");writes=0;
  h.accountStatus.put("selection_revision","changed");h.renderOfficialJob();check(writes>0,"local selection change omitted");writes=0;
  h.officialWarnings=OFFICIAL_WARNING_CLEANUP;h.renderOfficialJob();check(writes>0,"committed warning omitted");
  for(String terminal:new String[]{"cancelled","failed","completed"}){
   h.complete(job(terminal,true,terminal,0));check(h.officialStatus.timers.size()==1,"terminal worker unwind lost poll: "+terminal);
   h.complete(job(terminal,false,terminal,0));check(h.officialStatus.timers.isEmpty(),"terminal job kept polling: "+terminal);
  }
  h.complete(job("ready",false,"ready",500));int before=h.queries;h.officialWizardDialog=new Object();writes=0;h.officialStatus.fire();
  check(h.queries==before&&writes==0&&h.officialStatus.timers.size()==1,"dialog did not pause silent status query");h.officialWizardDialog=null;
  h.presentationObserved=false;h.scheduleOfficialRefresh();check(h.officialStatus.timers.isEmpty(),"stopped screen retained timer");h.officialRefresh.run();check(h.queries==before,"stopped screen queried backend");
  h.presentationObserved=true;h.officialRequest=true;h.officialPolling=true;
  JSONObject secret=new JSONObject().put("user_id","synthetic-id").put("password","synthetic-password");
  check(h.deferOfficialSubmission("official_inspect",secret,false),"user submission was lost behind a status read");
  check(!h.deferOfficialSubmission("official_inspect",new JSONObject(),false),"multiple deferred submissions accepted");
  h.clearDeferredOfficial();check(!secret.fields.containsKey("user_id")&&!secret.fields.containsKey("password")&&h.officialDeferredPayload==null,"stopped screen retained deferred credentials");
  h.officialDeferredAction="official_cancel";h.officialDeferredPayload=new JSONObject();h.drainDeferredOfficial();
  check(h.submissions==1&&h.lastAction.equals("official_cancel")&&h.officialDeferredPayload==null,"deferred user action was not drained once");
  h.drainDeferredOfficial();check(h.submissions==1,"deferred action replayed");
  System.out.println("official-polling-harness PASS");
 }
}
'''
    unit = tmp_path / "OfficialPollingHarness.java"
    unit.write_text(source)
    built = subprocess.run([javac, "-encoding", "UTF-8", "--release", "17", str(unit)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([java, "-cp", str(tmp_path), "OfficialPollingHarness"], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout.strip() == "official-polling-harness PASS"
