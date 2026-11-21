"""Run actual controller transition/path methods without substituting the game lifecycle."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Export.java"


def method(source, name, occurrence=0):
    matches = list(re.finditer(r"^    (?:private )?static [^\n]+\b" + name + r"\([^\n]*\)\s*(?:throws [^{]+)?\{", source, re.M))
    assert len(matches) > occurrence, name
    match = matches[occurrence]
    start = source.index("{", match.start())
    depth = 1
    at = start + 1
    while depth:
        depth += (source[at] == "{") - (source[at] == "}")
        at += 1
    return source[match.start():at]


def test_generic_save_resolves_completed_queue_ownership_and_preserves_one_shots(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    selected = [method(source, name) for name in ["queuedSaveTarget", "currentSaveTarget", "canSave", "openSave", "requestSave", "completedFile"]]
    fixture = tmp_path / "SaveHarness.java"
    fixture.write_text(r'''
import java.io.*;import java.nio.file.*;import java.util.*;
public class SaveHarness {
  static File exportRoot,persistentExportRoot,pendingSaveRoot;static String pendingSaveId;static boolean saving;
  static final int SAVE_DOCUMENT=50057;static JSONObject last=new JSONObject(),lastQueue=new JSONObject();
  static class SaveTarget {final File root;final String outputId,jobId;
    SaveTarget(File root,String outputId,String jobId){this.root=root;this.outputId=outputId;this.jobId=jobId;}}
  static class JSONObject {Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}
    String optString(String k){Object v=map.get(k);return v==null?"":v.toString();}
    JSONArray optJSONArray(String k){return map.get(k) instanceof JSONArray?(JSONArray)map.get(k):null;}}
  static class JSONArray {ArrayList<JSONObject> values=new ArrayList<>();JSONArray put(JSONObject v){values.add(v);return this;}
    int length(){return values.size();}JSONObject optJSONObject(int i){return values.get(i);}}
  static class Intent {static final String ACTION_CREATE_DOCUMENT="create",CATEGORY_OPENABLE="openable",EXTRA_TITLE="title";
    String action,type,title;Intent(String action){this.action=action;}Intent addCategory(String ignored){return this;}
    Intent setType(String type){this.type=type;return this;}Intent putExtra(String k,String value){title=value;return this;}}
  static class Activity {int launches,request;Intent picker;String getString(int id,Object... args){return "IdolyPride-MV-"+args[0]+".mp4";}
    void startActivityForResult(Intent intent,int request){launches++;picker=intent;this.request=request;}}
  static class R {static class string {static final int mp4_export_filename=1,mp4_save_failed=2;}}
  static class Toast {static final int LENGTH_LONG=1;static Toast makeText(Activity a,int s,int l){return new Toast();}void show(){}}
  static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
  static void file(File root,String id)throws Exception{Files.write(new File(root,id+".mp4").toPath(),new byte[]{1,2,3});}
  static JSONObject job(String id,String output,String state){return new JSONObject().put("job_id",id).put("output_id",output).put("state",state);}
''' + "\n".join(selected) + r'''
  public static void main(String[] args)throws Exception {
    File root=new File(args[0]).getCanonicalFile();root.mkdirs();
    exportRoot=new File(root,"temporary");exportRoot.mkdir();persistentExportRoot=new File(root,"completed");persistentExportRoot.mkdir();
    file(exportRoot,"queued_a");file(persistentExportRoot,"queued_a");
    last.put("phase","completed").put("export_id","queued_a");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","completed")));
    SaveTarget queued=currentSaveTarget();
    need(canSave()&&queued.root.equals(persistentExportRoot)&&queued.jobId.equals("stable_job"),"queued completion uses persistent owned output");
    Activity activity=new Activity();requestSave(activity);
    need(activity.launches==1&&activity.request==SAVE_DOCUMENT&&pendingSaveRoot.equals(persistentExportRoot)&&pendingSaveId.equals("queued_a"),"generic overlay Save opens the queued file");
    need(activity.picker.type.equals("video/mp4")&&activity.picker.title.equals("IdolyPride-MV-queued_a.mp4"),"picker exposes only a filename");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","running")));
    need(!canSave(),"queued running state never falls back to same-named temporary file");requestSave(activity);need(activity.launches==1,"unconfirmed output cannot open picker");
    lastQueue.put("jobs",new JSONArray().put(job("../foreign","queued_a","completed")));
    need(!canSave(),"malformed stable identity rejected");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","completed")));
    file(persistentExportRoot,"foreign");last.put("export_id","foreign");
    need(!canSave(),"unknown persistent file is not an owned queue result");requestSave(activity);need(activity.launches==1,"foreign output cannot open picker");
    last.put("export_id","../foreign");need(!canSave(),"path traversal rejected");
    last.put("export_id","queued_a");File queuedFile=new File(persistentExportRoot,"queued_a.mp4");queuedFile.delete();
    Files.createSymbolicLink(queuedFile.toPath(),new File(persistentExportRoot,"foreign.mp4").toPath());
    need(!canSave(),"symlink cannot bypass persistent file ownership or fall back to temporary output");
    file(exportRoot,"one_shot");last.put("export_id","one_shot");SaveTarget one=currentSaveTarget();
    need(canSave()&&one.root.equals(exportRoot)&&one.jobId==null,"one-shot output keeps its original directory");
    requestSave(activity);need(activity.launches==2&&pendingSaveRoot.equals(exportRoot)&&pendingSaveId.equals("one_shot"),"one-shot picker still works");
    saving=true;need(!canSave(),"do not overlap document writes");requestSave(activity);need(activity.launches==2,"busy write cannot start a second picker");
    System.out.println("PASS owned queued and one-shot Save");
  }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(fixture)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "SaveHarness", str(tmp_path / "files")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS owned queued and one-shot Save"


def test_controller_waits_for_live_game_and_resumes_without_recreating_it(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    selected = [method(source, name) for name in ["privateDirectory", "completedFile", "busy", "ready", "observeForegroundReadiness", "requestStart", "requestEnqueue",
                "beginPending", "gameResumed", "gamePaused", "gameStarted", "gameStopped", "suspendForLifecycle",
                "resumeForLifecycle", "togglePause", "requestPause", "requestResume", "focusChanged", "gameDestroyed", "cancel",
                "requestQueueRun", "bringQueueToForeground", "serverMenuOpening", "serverMenuOpenFailed", "geometryChanged"]]
    selected += [method(source, "requestStart", 1), method(source, "requestEnqueue", 1)]
    prefix = r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.nio.file.*;import java.lang.ref.WeakReference;import java.util.*;
public final class ControllerHarness {
  static boolean configured=true,initialized=true,queueConfigured=true,saving,resumed,stopped=true,userPaused,allowNative=true,dismissed=true,pendingQueueRun,gameFocused,foregroundSelectionReady;
  static int[] pending,startedOptions,enqueuedOptions;static long pendingDeadline,menuHandoffDeadline;static int starts,cancels,suspends,resumes,reason,wakes,enqueues,queueRuns,backgroundPrepares;static boolean enqueueWasResumed,allowQueueRun=true;
  static WeakReference<Activity> game=new WeakReference<>(null);
  static JSONObject last=new JSONObject(),lastQueue=new JSONObject();static final Handler MAIN=new Handler();static final Runnable BEGIN=()->{};
  static ViewGroup overlay;static Object overlayText,overlaySave,overlayCancel,overlayPause,overlayDismiss;
  static class JSONObject {Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}
    String optString(String k){return optString(k,"");}
    boolean optBoolean(String k){return Boolean.TRUE.equals(map.get(k));}
    String optString(String k,String d){return map.containsKey(k)?map.get(k).toString():d;}}
  static class Handler {int scheduled;void postDelayed(Runnable r,long delay){scheduled++;}void removeCallbacks(Runnable r){}}
  static class Activity {Intent intent;boolean destroyed,finishing,multiWindow;boolean isDestroyed(){return destroyed;}boolean isFinishing(){return finishing;}
    boolean isInMultiWindowMode(){return multiWindow;}
    void startActivity(Intent i){intent=i;}}
  static class Intent {static final int FLAG_ACTIVITY_REORDER_TO_FRONT=1,FLAG_ACTIVITY_SINGLE_TOP=2;int flags;Class<?> target;
    Intent(Activity c,Class<?> t){target=t;}Intent addFlags(int f){flags=f;return this;}}
  static class ViewGroup {Object getParent(){return null;}void removeView(Object v){}}
  static class R {static class string {static final int mp4_not_ready=1,mp4_unavailable=2;}}
  static class Toast {static final int LENGTH_LONG=1;static Toast makeText(Activity a,int s,int l){return new Toast();}void show(){}}
  static boolean nativeReady(){return allowNative;}
  static int nativeStartV2(int n,int d,int c,int v,int a,int width,int height){starts++;startedOptions=new int[]{n,d,c,v,a,width,height};return 0;}
  static void nativeCancel(){cancels++;}static void nativeSuspend(int value){suspends++;reason=value;}
  static void nativeResume(){resumes++;}static void wake(){wakes++;}
  static int nativeQueueRun(){if(!allowQueueRun)return -1;queueRuns++;return 0;}static void prepareBackground(Activity a){backgroundPrepares++;}
  static int nativeQueueEnqueueV2(int n,int d,int c,int v,int a,int width,int height){enqueues++;enqueueWasResumed=resumed;enqueuedOptions=new int[]{n,d,c,v,a,width,height};return 0;}
  static class UnifiedMP4Background {static void stopCurrent(){}static void focusLost(Activity a){}static boolean ownsSurface(Activity a){return false;}}
  static void require(boolean b,String message){if(!b)throw new AssertionError(message);}
  interface Action {void run()throws Exception;}
  static void rejects(Action a)throws Exception {try{a.run();}catch(IOException expected){return;}throw new AssertionError("unsafe path accepted");}
'''
    suffix = r'''
  public static void main(String[] args)throws Exception {
    Activity live=new Activity(),menu=new Activity();game=new WeakReference<>(live);
    require(requestStart(menu,60,2,17250000,3840,2160),"custom bitrate and output geometry accepted");
    require(!dismissed,"next job restores dismissed progress UI");
    require(menu.intent.target==live.getClass()&&menu.intent.flags==3,"existing explicit game/reorder/singleTop");
    require(starts==0,"never start while original Unity is paused");
    beginPending();require(starts==0&&pending!=null&&MAIN.scheduled>0,"wait for original onResume");
    resumed=true;allowNative=false;beginPending();require(starts==0&&pending!=null,"MV readiness recheck");
    allowNative=true;beginPending();require(starts==1&&pending==null&&busy(),"accepted start visible immediately");
    require(Arrays.equals(startedOptions,new int[]{60,1,2,17250000,192000,3840,2160}),"exact codec clock, numeric bitrate, and output geometry options");
    gamePaused(new Activity());require(suspends==0,"stale instance cannot pause current export");
    gamePaused(live);require(suspends==1&&reason==1&&cancels==0&&!resumed,"background parks current session");
    last.put("phase","paused");require(busy()&&!ready(),"paused export retains ownership");
    gameResumed(live);require(resumes==1&&!stopped,"foreground resumes the existing export");
    last.put("phase","rendering");togglePause();require(userPaused&&suspends==2&&reason==3,"explicit user pause");
    gamePaused(live);gameResumed(live);require(userPaused&&resumes==1&&suspends==2,"foreground preserves explicit user pause");
    togglePause();require(!userPaused&&resumes==2,"user resumes the same export");
    live.multiWindow=true;gamePaused(live);focusChanged(live,false);
    require(suspends==2&&cancels==0,"visible unfocused multi-window keeps rendering");
    gameStopped(live);require(stopped&&suspends==3&&reason==1,"hidden multi-window parks before original onStop");
    require(requestResume(menu)&&menu.intent.target==live.getClass()&&resumes==2,"server resume reorders original player before native resume");
    gameStarted(live);require(!stopped&&resumes==3,"visible multi-window restarts at original onStart");
    live.multiWindow=false;
    last=new JSONObject();pending=new int[]{30,1,1,8000000,192000};gamePaused(live);
    require(cancels==0&&suspends==3&&pending!=null,"menu-to-game transition is not mistaken for export backgrounding");
    android.os.SystemClock.now=pendingDeadline+1;beginPending();require(pending==null&&starts==1,"bounded stale launch");
    pending=new int[]{30,1,1,8000000,192000};gameDestroyed(live);
    require(game.get()==null&&pending==null&&cancels==1&&stopped,"destroy clears weak owner and pending work");
    Activity selected=new Activity();game=new WeakReference<>(selected);last=new JSONObject();
    allowNative=true;resumed=true;gameFocused=true;observeForegroundReadiness(true);
    gamePaused(selected);allowNative=false;
    observeForegroundReadiness(false);
    require(ready(),"opening server menu preserves a verified paused MV selection");
    Mp4QueueUiState.Controls menuControls=new Mp4QueueUiState.Controls(true,false,false,false,false,ready(),true,0,0);
    require(menuControls.immediate&&menuControls.enqueue,"both real server-menu buttons stay enabled for paused MV");
    require(requestEnqueue(menu,30,1,8000000)&&enqueues==1&&!enqueueWasResumed,"queue request retains selection identity before returning to game");
    require(starts==1,"adding a paused selection does not capture while original Unity is stopped");
    require(requestStart(menu,30,1,8000000),"one-shot request accepted from paused server menu");
    beginPending();require(starts==1&&pending!=null,"do not capture before original Activity resume");
    gameResumed(selected);beginPending();require(starts==1&&pending!=null,"foreground cache cannot bypass genuine resumed native readiness");
    allowNative=true;beginPending();require(starts==2&&pending==null,"capture starts only after resumed native revalidation");
    last=new JSONObject();allowNative=false;gameFocused=true;observeForegroundReadiness(false);
    require(!foregroundSelectionReady&&!ready(),"leaving MV while focused invalidates cached eligibility");
    resumed=false;require(!ready()&&!requestEnqueue(menu,30,1,8000000)&&enqueues==1,"cold or invalid selections remain disabled");
    gameDestroyed(selected);require(!foregroundSelectionReady&&!ready(),"destroyed owner cannot keep MV eligibility");
    // A photo/live presenter may become ready just before focus is lost, before
    // the 400ms foreground poll has stored its first positive observation.
    Activity photo=new Activity();game=new WeakReference<>(photo);last=new JSONObject();
    resumed=true;stopped=false;gameFocused=false;foregroundSelectionReady=false;allowNative=true;
    gamePaused(photo);allowNative=false;
    require(foregroundSelectionReady&&ready(),"onPause captures a positive native MV before Unity pauses even without a focused poll");
    int startsBeforeQueue=starts,preparesBeforeQueue=backgroundPrepares,resumesBeforeQueue=resumes;
    menu.intent=null;
    require(requestEnqueue(menu,60,2,0,1920,1080)&&enqueues==2&&!enqueueWasResumed,"paused cached MV accepts its exact V2 queue request");
    require(Arrays.equals(enqueuedOptions,new int[]{60,1,2,0,192000,1920,1080}),"recommended bitrate sentinel and custom dimensions reach queue admission unchanged");
    require(game.get()==photo&&menu.intent.target==photo.getClass()&&menu.intent.flags==3,"enqueue brings the existing live Activity forward without creating another player");
    require(pending==null&&!pendingQueueRun&&starts==startsBeforeQueue,"enqueue does not silently start a one-shot or start the queue");
    gameResumed(photo);beginPending();
    require(resumes==resumesBeforeQueue+1&&starts==startsBeforeQueue,"original onResume clears the lifecycle park while native source reconstruction remains independent");
    // The production C++ capture_resume_* tests execute the target wait and
    // immutable admission. Here a failed native Run must not reorder the UI.
    allowQueueRun=false;menu.intent=null;
    require(!requestQueueRun(menu)&&menu.intent==null&&!pendingQueueRun,"a still-pending native admission cannot launch queue rendering");
    allowQueueRun=true;allowNative=true;gamePaused(photo);allowNative=false;
    require(requestQueueRun(menu)&&queueRuns==1&&pendingQueueRun,"persisted queue Run is accepted from the paused server Activity");
    require(game.get()==photo&&menu.intent.target==photo.getClass()&&menu.intent.flags==3,"Run restores the same owner with reorder/singleTop");
    beginPending();require(pendingQueueRun&&backgroundPrepares==preparesBeforeQueue,"BEGIN waits for original Activity resume before preparing a queue transport");
    gameResumed(photo);beginPending();
    require(!pendingQueueRun&&backgroundPrepares==preparesBeforeQueue+1&&starts==startsBeforeQueue,"BEGIN resumes the queue path without invoking a second one-shot export");
    pendingQueueRun=true;pendingDeadline=android.os.SystemClock.now-1;
    beginPending();require(!pendingQueueRun&&starts==startsBeforeQueue,"expired foreground bookkeeping clears without invoking a one-shot exporter");
    gameDestroyed(photo);
    Activity rotating=new Activity();game=new WeakReference<>(rotating);last=new JSONObject();
    resumed=true;stopped=false;gameFocused=true;foregroundSelectionReady=false;allowNative=true;
    gamePaused(rotating);allowNative=false;int cancelsBeforeGeometry=cancels,enqueuesBeforeGeometry=enqueues;
    geometryChanged(rotating);
    require(foregroundSelectionReady&&ready(),"landscape MV -> paused portrait server resize preserves the verified logical selection");
    require(cancels==cancelsBeforeGeometry+1,"a geometry change still cancels any existing capture");
    require(requestEnqueue(menu,30,1,16000000)&&enqueues==enqueuesBeforeGeometry+1,"retained logical selection can enqueue for native identity/source revalidation");
    gameResumed(rotating);gameFocused=true;geometryChanged(rotating);
    require(!foregroundSelectionReady&&!ready(),"a real foreground resize keeps the original readiness invalidation");
    resumed=false;stopped=true;foregroundSelectionReady=false;geometryChanged(rotating);
    require(!foregroundSelectionReady&&!ready(),"a background resize never invents a previously unverified MV");
    resumed=true;stopped=false;serverMenuOpening(rotating);gamePaused(rotating);geometryChanged(rotating);
    require(!foregroundSelectionReady&&!ready(),"an explicit menu handoff with native readiness false cannot fabricate an eligible MV");
    gameResumed(rotating);
    resumed=true;stopped=false;gameFocused=true;allowNative=true;serverMenuOpening(rotating);
    require(menuHandoffDeadline>android.os.SystemClock.now&&foregroundSelectionReady,"menu launch captures only a real positive native selection");
    allowNative=false;geometryChanged(rotating);
    require(foregroundSelectionReady&&!ready(),"pre-onPause menu configuration retains logical eligibility but never makes an active invalid source ready");
    observeForegroundReadiness(false);
    require(foregroundSelectionReady,"a queued negative poll between menu configuration and onPause cannot erase the verified handoff selection");
    gamePaused(rotating);geometryChanged(rotating);require(ready(),"after onPause the same verified menu handoff remains requestable");
    gameResumed(rotating);gameFocused=true;require(menuHandoffDeadline==0,"returning to the game clears the menu-only resize exemption");
    geometryChanged(rotating);require(!foregroundSelectionReady,"foreground resize invalidates again immediately after return");
    allowNative=true;serverMenuOpening(rotating);allowNative=false;serverMenuOpenFailed(rotating);
    geometryChanged(rotating);require(menuHandoffDeadline==0&&!foregroundSelectionReady,"failed menu launch cannot leave an active-window exemption");
    allowNative=true;serverMenuOpening(rotating);allowNative=false;
    android.os.SystemClock.now=menuHandoffDeadline+1;observeForegroundReadiness(false);
    require(!foregroundSelectionReady,"an expired handoff cannot hide a new foreground selection failure");
    geometryChanged(rotating);
    require(!foregroundSelectionReady,"an uncompleted menu handoff cannot exempt foreground resizes forever");
    menuHandoffDeadline=0;rotating.multiWindow=true;resumed=false;stopped=false;foregroundSelectionReady=true;
    geometryChanged(rotating);require(!foregroundSelectionReady,"visible unfocused multi-window resize still invalidates the active surface");
    stopped=true;foregroundSelectionReady=true;last.put("phase","rendering");cancelsBeforeGeometry=cancels;
    geometryChanged(rotating);
    require(foregroundSelectionReady&&cancels==cancelsBeforeGeometry+1&&!ready(),"background selection retention never suppresses active capture cancellation or busy ownership");
    last=new JSONObject();allowNative=true;serverMenuOpening(rotating);gameDestroyed(rotating);
    require(!foregroundSelectionReady&&menuHandoffDeadline==0&&!ready(),"destroy clears both logical eligibility and menu ownership");
    File root=new File(args[0]).getCanonicalFile();root.mkdirs();File out=new File(root,"exports");out.mkdir();
    require(privateDirectory(root,out.getPath()).equals(out),"private output root");
    rejects(()->privateDirectory(root,new File(root,"../elsewhere").getPath()));
    File file=new File(out,"owned_01.mp4");Files.write(file.toPath(),new byte[]{1,2});
    require(completedFile(out,"owned_01").equals(file),"completed owned file");
    rejects(()->completedFile(out,"../owned_01"));rejects(()->completedFile(out,"owned_01.mp4"));
    rejects(()->completedFile(out,""));rejects(()->completedFile(out,"missing"));
    File external=new File(root,"external.mp4");Files.write(external.toPath(),new byte[]{3});
    Files.createSymbolicLink(new File(out,"linked.mp4").toPath(),external.toPath());
    rejects(()->completedFile(out,"linked"));
    Files.createSymbolicLink(new File(root,"aliased").toPath(),out.toPath());
    rejects(()->privateDirectory(root,new File(root,"aliased").getPath()));
    System.out.println("PASS controller");
  }
}
'''
    harness = tmp_path / "ControllerHarness.java"
    harness.write_text(prefix + "\n".join(selected) + suffix)
    clock = tmp_path / "android/os/SystemClock.java"
    clock.parent.mkdir(parents=True)
    clock.write_text("package android.os; public class SystemClock {public static long now;public static long uptimeMillis(){return now;}}")
    policy = SOURCE.with_name("Mp4QueueUiState.java")
    compile_result = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(tmp_path / "classes"), str(harness), str(clock), str(policy), str(SOURCE.with_name("Mp4ExportSettings.java"))],
                                    capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(tmp_path / "classes"), "game.qualiarts.idolypride.localserver.ControllerHarness", str(tmp_path / "files")],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS controller"


def test_diagnostics_copies_only_bounded_public_state_without_private_payloads(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    selected = method(SOURCE.read_text(), "diagnostics")
    fixture = tmp_path / "DiagnosticsHarness.java"
    fixture.write_text(r'''
import java.util.*;import java.lang.ref.WeakReference;
public class DiagnosticsHarness {
 static boolean configured=true,initialized=true,resumed,gameFocused,stopped=true,foregroundSelectionReady=true;
 static class Activity {boolean isDestroyed(){return false;}boolean isFinishing(){return false;}}
 static WeakReference<Activity> game=new WeakReference<>(new Activity());static boolean queueConfigured=true;
 static JSONObject state=new JSONObject(),queue=new JSONObject(),nativeValue=new JSONObject();
 static class JSONObject {static final Map<String,JSONObject> refs=new HashMap<>();final Map<String,Object> map=new LinkedHashMap<>();
  JSONObject(){}JSONObject(String raw){map.putAll(refs.get(raw).map);}JSONObject put(String k,Object v){map.put(k,v);return this;}
  boolean optBoolean(String k){return Boolean.TRUE.equals(map.get(k));}String optString(String k,String fallback){Object v=map.get(k);return v instanceof String?(String)v:fallback;}
  long optLong(String k){Object v=map.get(k);return v instanceof Number?((Number)v).longValue():0;}
  JSONArray optJSONArray(String k){return map.get(k) instanceof JSONArray?(JSONArray)map.get(k):null;}}
 static class JSONArray {int size;JSONArray(int n){size=n;}int length(){return size;}}
 static JSONObject snapshot(){return state;}static JSONObject queueSnapshot(){return queue;}
 static String nativeStatus(){JSONObject.refs.put("native",nativeValue);return "native";}
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
''' + selected + r'''
 public static void main(String[] args){
  state.put("phase","stale");
  nativeValue.put("ready",false).put("phase","idle").put("readiness_error","selected_capture_geometry_unsupported")
   .put("error_code","../private/broker.capability").put("pause_reason","none")
   .put("width",0).put("height",0).put("source_width",4095).put("source_height",2457)
   .put("fps_num",60).put("fps_den",1).put("video_bitrate",17250000).put("unity_ticks",51L).put("capture_acks",-1L)
   .put("frames",Long.MAX_VALUE).put("total_frames",100L)
   .put("directory","/private/broker").put("capability","b6bcf1ca5802a5b5bd5376fb893ff190")
   .put("export_id","01234567890123456789012345678901").put("pcm_path","/private/exports/private.pcm");
  queue.put("available",true).put("running",false).put("paused",true).put("jobs",new JSONArray(100))
   .put("queue_root","/private/queue").put("selected_characters","unpublished private payload");
  JSONObject result=diagnostics();
  need(result.map.get("phase").equals("idle"),"diagnostics obtains current native status rather than stale UI snapshot");
  need(result.map.get("readiness_error").equals("selected_capture_geometry_unsupported"),"actual readiness reason survives");
  need(result.map.get("error_code").equals("unknown"),"non-code/path error text is not copied");
  need(result.map.get("source_width").equals(4095L)&&result.map.get("source_height").equals(2457L),"idle source geometry survives");
  need(result.map.get("video_bitrate").equals(17250000L)&&result.map.get("fps_num").equals(60L),"actual encoder scalars survive");
  need(result.map.get("capture_acks").equals(0L)&&result.map.get("frames").equals(9007199254740991L),"numeric fields bounded");
  need(result.map.get("queue_job_count").equals(8)&&result.map.get("queue_paused").equals(true),"queue count bounded without job contents");
  for(String key:new String[]{"directory","capability","export_id","pcm_path","jobs","queue_root","selected_characters"})
   need(!result.map.containsKey(key),"private field omitted: "+key);
  need(result.map.get("verified_foreground_selection").equals(true)&&result.map.get("game_attached").equals(true),"lifecycle facts preserved");
  initialized=false;JSONObject cold=diagnostics();need(cold.map.get("phase").equals("stale"),"cold diagnostics never tries unavailable JNI");
  System.out.println("PASS bounded public MP4 diagnostics");
 }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(fixture)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "DiagnosticsHarness"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS bounded public MP4 diagnostics"


def test_status_keeps_queue_handoffs_distinct_from_idle_or_previous_completion(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    production = "\n".join(method(source, name) for name in ("backgroundQueueHasWork", "statusText"))
    resources = sorted(set(re.findall(r"R\.string\.([a-z0-9_]+)", production)))
    declarations = "".join(f"static final int {name}={index};" for index, name in enumerate(resources, 1))
    harness = tmp_path / "QueueStatusHarness.java"
    harness.write_text(r'''import java.util.*;
public final class QueueStatusHarness {
 static boolean configured=true,saving,pendingQueueRun,mvReady;static int[] pending;static int readyCalls;
 static JSONObject last=new JSONObject(),lastQueue=new JSONObject();
 static final class JSONObject {
  final Map<String,Object> values=new HashMap<>();
  JSONObject put(String key,Object value){values.put(key,value);return this;}
  boolean optBoolean(String key){return Boolean.TRUE.equals(values.get(key));}
  long optLong(String key){Object value=values.get(key);return value instanceof Number?((Number)value).longValue():0;}
  String optString(String key){return optString(key,"");}
  String optString(String key,String fallback){Object value=values.get(key);return value instanceof String?(String)value:fallback;}
 }
 static final class Context {String getString(int resource,Object...args){return "resource="+resource+Arrays.toString(args);}}
 static final class R {static final class string {''' + declarations + r'''}}
 static boolean ready(){readyCalls++;return mvReady;}
 static void need(boolean condition,String message){if(!condition)throw new AssertionError(message);}
 static void expect(Context context,int resource,String message){need(statusText(context).startsWith("resource="+resource+"["),message);}
''' + production + r'''
 public static void main(String[]arguments){
  Context context=new Context();
  last.put("phase","idle").put("readiness_error","open_selected_mv_first");lastQueue.put("command_pending",true);
  expect(context,R.string.mp4_queue_waiting_scene,"pending enqueue reports original scene preparation rather than telling the user to reopen the MV");
  need(readyCalls==0,"a queue handoff does not consult unrelated idle selection eligibility");
  lastQueue=new JSONObject();pendingQueueRun=true;last.put("phase","");
  expect(context,R.string.mp4_queue_waiting_scene,"accepted queue Run reports a pending game foreground handoff");
  pendingQueueRun=false;lastQueue.put("running",true);last.put("phase","completed");
  expect(context,R.string.mp4_queue_waiting_scene,"the previous completed MV cannot claim the next queued MV is already complete");
  for(String phase:new String[]{"idle","completed","failed","cancelled"}){
   last.put("phase",phase);expect(context,R.string.mp4_queue_waiting_scene,"next-scene work takes priority over stale terminal state: "+phase);
  }
  last.put("phase","preparing_audio");expect(context,R.string.mp4_preparing_audio,"actual soundtrack preparation remains visible");
  last.put("total_audio_frames",48000L).put("audio_frames",24000L);
  expect(context,R.string.mp4_preparing_audio_progress,"actual soundtrack progress remains visible");
  last.put("phase","rendering").put("frames",18L).put("total_frames",60L).put("width",1920L).put("height",1080L).put("fps_num",60L);
  expect(context,R.string.mp4_rendering,"actual rendering is not relabeled as scene preparation");
  need(statusText(context).contains("resource="+R.string.mp4_geometry+"[1920, 1080, 60]"),"actual render geometry and frame rate are retained");
  last.put("phase","paused").put("pause_reason","user_paused");expect(context,R.string.mp4_paused,"explicit user pause remains visible");
  last.put("pause_reason","lifecycle_background");expect(context,R.string.mp4_background_paused,"lifecycle pause remains visible");
  last.put("phase","pausing");expect(context,R.string.mp4_pausing,"safe pause progress remains visible");
  for(String phase:new String[]{"finishing","cancelling"}){last.put("phase",phase);expect(context,R.string.mp4_finishing,"active finalization remains visible");}
  last.put("phase","completed");pending=new int[]{30};expect(context,R.string.mp4_preparing_audio,"a real pending single export retains its existing status");
  saving=true;expect(context,R.string.mp4_finishing,"an active document save retains its existing status");saving=false;pending=null;
  lastQueue=new JSONObject();last.put("phase","completed");expect(context,R.string.mp4_completed,"completion returns after all queue work ends");
  last.put("phase","failed").put("error_code","encoder_failed");expect(context,R.string.mp4_failed,"a terminal error outside queue work is not hidden");
  last.put("phase","cancelled");expect(context,R.string.mp4_cancelled,"a real terminal cancellation outside queue work is not hidden");
  last.put("phase","idle");expect(context,R.string.mp4_not_ready,"an ordinary idle scene still requests the MV");
  mvReady=true;expect(context,R.string.mp4_idle,"a genuinely ready idle MV retains the idle message");
  configured=false;expect(context,R.string.mp4_unavailable,"an unavailable idle exporter retains its existing status");
  System.out.println("PASS queue-aware Android MP4 status");
 }
}''')
    classes = tmp_path / "classes"
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "QueueStatusHarness"],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS queue-aware Android MP4 status"


def test_server_stop_parks_native_queue_before_disabling_it_and_cancelling_session(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    production = method(SOURCE.read_text(), "serverStopped")
    harness = tmp_path / "ServerStopHarness.java"
    harness.write_text(r'''import java.util.*;
public final class ServerStopHarness {
 static boolean configured,initialized,queueConfigured,foregroundSelectionReady,throwPause,queueParked;
 static long menuHandoffDeadline;static int[] pending;static int pauseResult;
 static final List<String> events=new ArrayList<>();static final Handler MAIN=new Handler();
 static final class Handler {
  final List<Runnable> work=new ArrayList<>();void post(Runnable task){work.add(task);}
  void drain(){for(Runnable task:new ArrayList<>(work))task.run();work.clear();}
 }
 static int nativeQueuePause(){
  need(configured&&initialized&&queueConfigured,"the queue pause must be accepted before its host configuration is retired");
  events.add("pause");if(throwPause)throw new UnsatisfiedLinkError("optional addon unavailable");
  if(pauseResult==0)queueParked=true;return pauseResult;
 }
 static void cancel(){events.add("cancel");}
 static void wake(){events.add("wake");}
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
 static void reset(boolean loaded,boolean queued){
  configured=true;initialized=loaded;queueConfigured=queued;foregroundSelectionReady=true;menuHandoffDeadline=8000;
  pending=new int[]{60,1,2};throwPause=false;queueParked=false;pauseResult=0;events.clear();MAIN.work.clear();
 }
''' + production + r'''
 public static void main(String[]arguments){
  reset(true,true);serverStopped();
  need(events.equals(Arrays.asList("pause"))&&queueParked,"native queue is parked synchronously without waiting for the paused Unity main loop");
  need(!configured&&!queueConfigured&&!foregroundSelectionReady&&menuHandoffDeadline==0,"server stop retires host availability and cached menu eligibility");
  need(MAIN.work.size()==1&&pending!=null,"existing main-thread session cleanup remains deferred");
  MAIN.drain();need(events.equals(Arrays.asList("pause","cancel","wake"))&&pending==null&&queueParked,"session cancellation follows queue parking without resuming the queue");
  serverStopped();need(Collections.frequency(events,"pause")==1,"a repeated stop cannot call an already-retired queue");MAIN.drain();
  reset(true,false);serverStopped();need(events.isEmpty(),"an unconfigured queue never receives JNI pause");MAIN.drain();
  need(events.equals(Arrays.asList("cancel","wake")),"queue absence preserves existing session cleanup");
  reset(false,true);serverStopped();need(events.isEmpty(),"an uninitialized optional native addon never receives queue pause");MAIN.drain();
  reset(true,true);throwPause=true;serverStopped();MAIN.drain();
  need(events.equals(Arrays.asList("pause","cancel","wake"))&&!configured&&!queueConfigured&&pending==null,"optional JNI absence cannot prevent server/session retirement");
  reset(true,true);pauseResult=-1;serverStopped();MAIN.drain();
  need(events.equals(Arrays.asList("pause","cancel","wake"))&&!configured&&!queueConfigured,"a rejected host pause cannot prevent safe host cleanup");
  System.out.println("PASS queue parking before server retirement");
 }
}''')
    classes = tmp_path / "classes"
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "ServerStopHarness"],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS queue parking before server retirement"
