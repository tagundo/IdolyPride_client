"""Run actual controller transition/path methods without substituting the game lifecycle."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Export.java"


def method(source, name):
    match = re.search(r"^    (?:private )?static [^\n]+\b" + name + r"\([^\n]*\)\s*(?:throws [^{]+)?\{", source, re.M)
    assert match, name
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
                "resumeForLifecycle", "togglePause", "requestPause", "requestResume", "focusChanged", "gameDestroyed", "cancel"]]
    prefix = r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.nio.file.*;import java.lang.ref.WeakReference;import java.util.*;
public final class ControllerHarness {
  static boolean configured=true,initialized=true,queueConfigured=true,saving,resumed,stopped=true,userPaused,allowNative=true,dismissed=true,pendingQueueRun,gameFocused,foregroundSelectionReady;
  static int[] pending,startedOptions;static long pendingDeadline;static int starts,cancels,suspends,resumes,reason,wakes,enqueues;static boolean enqueueWasResumed;
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
  static int nativeStart(int n,int d,int c,int v,int a){starts++;startedOptions=new int[]{n,d,c,v,a};return 0;}
  static void nativeCancel(){cancels++;}static void nativeSuspend(int value){suspends++;reason=value;}
  static void nativeResume(){resumes++;}static void wake(){wakes++;}
  static int nativeQueueRun(){return 0;}static void prepareBackground(Activity a){}
  static int nativeQueueEnqueue(int n,int d,int c,int v,int a){enqueues++;enqueueWasResumed=resumed;return 0;}
  static class UnifiedMP4Background {static void stopCurrent(){}static void focusLost(Activity a){}}
  static void require(boolean b,String message){if(!b)throw new AssertionError(message);}
  interface Action {void run()throws Exception;}
  static void rejects(Action a)throws Exception {try{a.run();}catch(IOException expected){return;}throw new AssertionError("unsafe path accepted");}
'''
    suffix = r'''
  public static void main(String[] args)throws Exception {
    Activity live=new Activity(),menu=new Activity();game=new WeakReference<>(live);
    require(requestStart(menu,60,2,16000000),"start accepted");
    require(!dismissed,"next job restores dismissed progress UI");
    require(menu.intent.target==live.getClass()&&menu.intent.flags==3,"existing explicit game/reorder/singleTop");
    require(starts==0,"never start while original Unity is paused");
    beginPending();require(starts==0&&pending!=null&&MAIN.scheduled>0,"wait for original onResume");
    resumed=true;allowNative=false;beginPending();require(starts==0&&pending!=null,"MV readiness recheck");
    allowNative=true;beginPending();require(starts==1&&pending==null&&busy(),"accepted start visible immediately");
    require(Arrays.equals(startedOptions,new int[]{60,1,2,16000000,192000}),"exact codec clock/bitrate options");
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
    compile_result = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(tmp_path / "classes"), str(harness), str(clock), str(policy)],
                                    capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(tmp_path / "classes"), "game.qualiarts.idolypride.localserver.ControllerHarness", str(tmp_path / "files")],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS controller"
