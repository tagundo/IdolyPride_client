"""Run actual controller transition/path methods without substituting the game lifecycle."""
from pathlib import Path
import os
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


def test_current_session_save_preserves_queue_ownership_without_falling_back_to_other_outputs(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    selected = [method(source, name) for name in ["queuedSaveTarget", "sessionSaveTarget", "completedFile"]]
    fixture = tmp_path / "SaveHarness.java"
    fixture.write_text(r'''
import java.io.*;import java.nio.file.*;import java.util.*;
public class SaveHarness {
  static File exportRoot,persistentExportRoot;static JSONObject last=new JSONObject(),lastQueue=new JSONObject();
  static class SaveTarget {final File root;final String outputId,jobId;
    SaveTarget(File root,String outputId,String jobId){this.root=root;this.outputId=outputId;this.jobId=jobId;}}
  static class JSONObject {Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}
    String optString(String k){Object v=map.get(k);return v==null?"":v.toString();}
    JSONArray optJSONArray(String k){return map.get(k) instanceof JSONArray?(JSONArray)map.get(k):null;}}
  static class JSONArray {ArrayList<JSONObject> values=new ArrayList<>();JSONArray put(JSONObject v){values.add(v);return this;}
    int length(){return values.size();}JSONObject optJSONObject(int i){return values.get(i);}}
  static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
  interface Read {SaveTarget run()throws IOException;}
  static void rejects(Read action,String message)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError(message);}
  static void file(File root,String id)throws Exception{Files.write(new File(root,id+".mp4").toPath(),new byte[]{1,2,3});}
  static JSONObject job(String id,String output,String state){return new JSONObject().put("job_id",id).put("output_id",output).put("state",state);}
''' + "\n".join(selected) + r'''
  public static void main(String[] args)throws Exception {
    File root=new File(args[0]).getCanonicalFile();root.mkdirs();
    exportRoot=new File(root,"temporary");exportRoot.mkdir();persistentExportRoot=new File(root,"completed");persistentExportRoot.mkdir();
    file(exportRoot,"queued_a");file(persistentExportRoot,"queued_a");
    last.put("phase","completed").put("export_id","queued_a");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","completed")));
    SaveTarget queued=sessionSaveTarget();
    need(queued.root.equals(persistentExportRoot)&&queued.jobId.equals("stable_job"),"current queued completion uses persistent owned output");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","running")));
    rejects(()->sessionSaveTarget(),"queued running state must not fall back to same-named temporary file");
    lastQueue.put("jobs",new JSONArray().put(job("../foreign","queued_a","completed")));
    rejects(()->sessionSaveTarget(),"malformed stable queue identity must be rejected");
    lastQueue.put("jobs",new JSONArray().put(job("stable_job","queued_a","completed")));
    file(persistentExportRoot,"foreign");last.put("export_id","foreign");
    rejects(()->sessionSaveTarget(),"unknown persistent file must not become the current session result");
    last.put("export_id","../foreign");rejects(()->sessionSaveTarget(),"path traversal must be rejected");
    last.put("export_id","queued_a");File queuedFile=new File(persistentExportRoot,"queued_a.mp4");queuedFile.delete();
    Files.createSymbolicLink(queuedFile.toPath(),new File(persistentExportRoot,"foreign.mp4").toPath());
    rejects(()->sessionSaveTarget(),"symlink must not bypass persistent ownership or fall back to temporary output");
    file(exportRoot,"one_shot");last.put("export_id","one_shot");SaveTarget one=sessionSaveTarget();
    need(one.root.equals(exportRoot)&&one.jobId==null,"current one-shot keeps its original directory");
    last.put("phase","idle");rejects(()->sessionSaveTarget(),"an idle native session must not claim a previous completed output");
    last.put("phase","rendering");rejects(()->sessionSaveTarget(),"an active native session must not claim an earlier owned output");
    System.out.println("PASS current session output ownership");
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
    assert result.stdout.strip() == "PASS current session output ownership"


def test_controller_waits_for_live_game_and_resumes_without_recreating_it(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    selected = [method(source, name) for name in ["privateDirectory", "completedFile", "busy", "ready", "selectedMv", "canEnqueueSelection", "observeForegroundReadiness", "observeForegroundSelection", "requestStart", "requestEnqueue",
                "beginPending", "gameResumed", "gamePaused", "gameStarted", "gameStopped", "suspendForLifecycle",
                "resumeForLifecycle", "togglePause", "requestPause", "requestResume", "focusChanged", "gameDestroyed", "cancel",
                "requestQueueRun", "bringQueueToForeground", "serverMenuOpening", "serverMenuOpenFailed", "geometryChanged",
                "invalidateQueueSelection", "observeGameOwner", "cancelFrom", "geometryFreeStage"]]
    selected += [method(source, "requestStart", 1), method(source, "requestEnqueue", 1)]
    prefix = r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.nio.file.*;import java.lang.ref.WeakReference;import java.util.*;
public final class ControllerHarness {
  static boolean configured=true,initialized=true,queueConfigured=true,saving,resumed,stopped=true,userPaused,allowNative=true,dismissed=true,pendingQueueRun,gameFocused,foregroundSelectionReady,foregroundMvSelected,completionStorageReady=true;
  static int[] pending,startedOptions,enqueuedOptions;static long pendingDeadline,menuHandoffDeadline;static int starts,cancels,suspends,resumes,reason,wakes,enqueues,queueRuns,backgroundPrepares,invalidations,enqueueCalls;static boolean enqueueWasResumed,allowQueueRun=true,allowEnqueue=true,backgroundOwns;
  static WeakReference<Activity> game=new WeakReference<>(null);
  static JSONObject last=new JSONObject(),lastQueue=new JSONObject();static final Handler MAIN=new Handler();static final Runnable BEGIN=()->{};
  static ViewGroup overlay;static Object overlayText,overlaySave,overlayCancel,overlayPause,overlayDismiss;
  static String cancelOrigin="unknown";static final List<String> cancelOrigins=new ArrayList<>();static void recordCancel(String origin){cancelOrigins.add(origin);}
  static class JSONObject {Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}
    String optString(String k){return optString(k,"");}
    Object opt(String k){return map.get(k);}
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
  static boolean nativeSelectionReady(){return allowNative;}
  static JSONObject queueSnapshot(){return lastQueue;}
  static boolean oneShotCompletionReady(){return completionStorageReady;}
  static int nativeStartV2(int n,int d,int c,int v,int a,int width,int height){starts++;startedOptions=new int[]{n,d,c,v,a,width,height};return 0;}
  static void nativeCancel(){cancels++;}static void nativeSuspend(int value){suspends++;reason=value;}
  static void nativeResume(){resumes++;}static void wake(){wakes++;}
  static void nativeInvalidateQueueSelection(){invalidations++;}
  static int nativeQueueRun(){if(!allowQueueRun)return -1;queueRuns++;return 0;}static void prepareBackground(Activity a){backgroundPrepares++;}
  static int nativeQueueEnqueueV2(int n,int d,int c,int v,int a,int width,int height){enqueueCalls++;if(!allowEnqueue)return -1;enqueues++;enqueueWasResumed=resumed;enqueuedOptions=new int[]{n,d,c,v,a,width,height};return 0;}
  static class UnifiedMP4Background {static void stopCurrent(){}static void focusLost(Activity a){}static boolean ownsSurface(Activity a){return backgroundOwns;}}
  static void require(boolean b,String message){if(!b)throw new AssertionError(message);}
  interface Action {void run()throws Exception;}
  static void rejects(Action a)throws Exception {try{a.run();}catch(IOException expected){return;}throw new AssertionError("unsafe path accepted");}
'''
    suffix = r'''
  public static void main(String[] args)throws Exception {
    Activity live=new Activity(),menu=new Activity();game=new WeakReference<>(live);
    completionStorageReady=false;
    require(!requestStart(menu,60,2,17250000,3840,2160)&&menu.intent==null&&pending==null&&starts==0,"failed completion recovery admission cannot navigate or start capture");
    lastQueue.put("running",true);last.put("phase","idle");
    require(busy()&&!ready(),"queued scene preparation retains progress and ownership before encoder starts");
    lastQueue.put("running",false).put("command_pending",true);
    require(busy()&&!ready(),"accepted queue command retains progress before its first Unity callback");
    lastQueue.put("command_pending",false);
    completionStorageReady=true;
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
    lastQueue.put("can_add",true);
    menu.intent=null;int resumesBeforeAdd=resumes,preparesBeforeAdd=backgroundPrepares;long deadlineBeforeAdd=pendingDeadline;
    completionStorageReady=false;
    require(requestEnqueue(menu,30,1,8000000)&&enqueues==1&&!enqueueWasResumed,"queue admission remains independent of one-shot recovery admission");
    completionStorageReady=true;
    require(menu.intent==null&&resumes==resumesBeforeAdd&&backgroundPrepares==preparesBeforeAdd&&pendingDeadline==deadlineBeforeAdd,
      "Add keeps server UI, lifecycle and background transport unchanged");
    require(starts==1,"adding a paused selection does not capture while original Unity is stopped");
    require(requestStart(menu,30,1,8000000),"one-shot request accepted from paused server menu");
    beginPending();require(starts==1&&pending!=null,"do not capture before original Activity resume");
    gameResumed(selected);beginPending();require(starts==1&&pending!=null,"foreground cache cannot bypass genuine resumed native readiness");
    allowNative=true;beginPending();require(starts==2&&pending==null,"capture starts only after resumed native revalidation");
    last=new JSONObject();allowNative=false;gameFocused=true;observeForegroundReadiness(false);observeForegroundSelection(false);
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
    require(game.get()==photo&&menu.intent==null&&!resumed,"Add leaves the existing paused player and server Activity in place");
    require(pending==null&&!pendingQueueRun&&starts==startsBeforeQueue,"enqueue does not silently start a one-shot or start the queue");
    require(resumes==resumesBeforeQueue&&backgroundPrepares==preparesBeforeQueue,"Add never resumes Unity or prepares offscreen capture");
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
    require(cancelOrigins.get(cancelOrigins.size()-1).equals("game_destroyed"),"a destroyed game owner attributes its cancel");
    Activity rotating=new Activity();game=new WeakReference<>(rotating);last=new JSONObject();
    resumed=true;stopped=false;gameFocused=true;foregroundSelectionReady=false;allowNative=true;
    gamePaused(rotating);allowNative=false;
    for(String stage:new String[]{"idle","begin","scene_acquire","audio_setup","audio_request","audio_response","audio_load","audio_mix","audio_finalize","render_setup","encoder_finish_save","restore_retire"}){
      last=new JSONObject().put("job_stage",stage);int before=cancels;geometryChanged(rotating);
      require(cancels==before,"the fresh scene reload reshapes the window before render setup; "+stage+" must not cancel");}
    for(String stage:new String[]{"frame_request","encoder_append"}){
      last=new JSONObject().put("job_stage",stage);int before=cancels;geometryChanged(rotating);
      require(cancels==before+1,"a running capture still cancels on a geometry change: "+stage);}
    last=new JSONObject().put("job_stage","frame_readback");foregroundSelectionReady=true;
    int cancelsBeforeGeometry=cancels,enqueuesBeforeGeometry=enqueues;
    geometryChanged(rotating);
    require(foregroundSelectionReady&&ready(),"landscape MV -> paused portrait server resize preserves the verified logical selection");
    require(cancels==cancelsBeforeGeometry+1,"a geometry change still cancels any existing capture");
    require(cancelOrigins.get(cancelOrigins.size()-1).equals("geometry_changed")&&"unknown".equals(cancelOrigin),"a geometry cancel is attributed once, then the origin resets");
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
    int invalidationsBeforeOwner=invalidations;
    Activity split=new Activity();observeGameOwner(split);split.multiWindow=true;last=new JSONObject();allowNative=true;
    require(invalidations==invalidationsBeforeOwner+1&&!resumed&&stopped,"a new Activity cannot inherit the prior owner's immutable selection or lifecycle");
    gameResumed(split);gameFocused=true;observeForegroundReadiness(true);gamePaused(split);allowNative=false;
    menu.intent=null;resumesBeforeAdd=resumes;preparesBeforeAdd=backgroundPrepares;deadlineBeforeAdd=pendingDeadline;
    int invalidationsBeforePause=invalidations;userPaused=true;
    require(requestEnqueue(menu,30,1,16000000)&&menu.intent==null,"split-window Add does not reorder either window");
    require(userPaused&&!pendingQueueRun&&pending==null&&resumes==resumesBeforeAdd&&backgroundPrepares==preparesBeforeAdd&&pendingDeadline==deadlineBeforeAdd,
      "Add preserves explicit pause and all execution bookkeeping");
    gameStopped(split);
    require(invalidations==invalidationsBeforePause&&foregroundSelectionReady,"onPause and onStop preserve the immutable logical selection");
    require(requestEnqueue(menu,30,1,16000000)&&menu.intent==null,"a stopped original player can add its validated snapshot without navigation");
    int accepted=enqueues,calls=enqueueCalls;allowEnqueue=false;
    require(!requestEnqueue(menu,30,1,16000000)&&enqueues==accepted&&enqueueCalls==calls+1&&menu.intent==null,
      "native snapshot rejection never becomes UI success or a foreground launch");allowEnqueue=true;
    split.destroyed=true;calls=enqueueCalls;
    require(!requestEnqueue(menu,30,1,16000000)&&enqueueCalls==calls&&menu.intent==null,"destroyed owner rejects before JNI");split.destroyed=false;
    split.finishing=true;require(!requestEnqueue(menu,30,1,16000000)&&enqueueCalls==calls,"finishing owner rejects before JNI");split.finishing=false;
    foregroundSelectionReady=false;lastQueue.put("can_add",false);
    require(!requestEnqueue(menu,30,1,16000000)&&enqueueCalls==calls,"a rejected native immutable candidate cannot be overridden by a detected source");
    lastQueue.put("can_add",true);
    foregroundSelectionReady=true;
    require(!requestEnqueue(menu,24,1,16000000)&&!requestEnqueue(menu,30,3,16000000)
      &&!requestEnqueue(menu,30,1,1)&&!requestEnqueue(menu,30,1,16000000,1919,1080)&&enqueueCalls==calls,"invalid options do not reach JNI");
    int beforeSameOwner=invalidations;observeGameOwner(split);require(invalidations==beforeSameOwner,"reattaching the same Activity does not discard native selection");
    Activity replacement=new Activity();observeGameOwner(replacement);
    require(invalidations==beforeSameOwner+1&&!foregroundSelectionReady&&game.get()==replacement,"replacement Activity retires the old owner snapshot");
    int beforeStaleDestroy=invalidations;gameDestroyed(split);require(invalidations==beforeStaleDestroy&&game.get()==replacement,"stale owner destruction cannot invalidate the replacement");
    resumed=true;stopped=false;allowNative=true;serverMenuOpening(replacement);int beforeHandoff=invalidations;
    geometryChanged(replacement);gamePaused(replacement);gameStopped(replacement);geometryChanged(replacement);
    require(invalidations==beforeHandoff&&foregroundSelectionReady,"menu handoff geometry and pause/stop keep the same snapshot");
    gameResumed(replacement);allowNative=false;gameFocused=true;geometryChanged(replacement);
    require(invalidations==beforeHandoff+1&&!foregroundSelectionReady,"real active-window resize invalidates native and Java snapshot eligibility");
    foregroundSelectionReady=true;pending=new int[]{30,1,1,16000000,192000};int cancelsBeforePending=cancels;
    geometryChanged(replacement);require(invalidations==beforeHandoff+2&&pending!=null&&cancels==cancelsBeforePending,"pending immediate start still invalidates stale Add geometry without cancelling its own resume wait");pending=null;
    backgroundOwns=true;foregroundSelectionReady=true;int beforeOwnedGeometry=invalidations;
    geometryChanged(replacement);require(invalidations==beforeOwnedGeometry&&foregroundSelectionReady,"owned offscreen transport geometry is not replaced by a UI-window resize");backgroundOwns=false;
    gameDestroyed(replacement);require(invalidations==beforeOwnedGeometry+1,"current owner destruction retires the native snapshot");
    Activity found=new Activity();observeGameOwner(found);resumed=false;stopped=true;gameFocused=false;
    foregroundMvSelected=true;foregroundSelectionReady=false;allowNative=false;lastQueue.put("can_add",true);menu.intent=null;
    int recognitionStarts=starts,recognitionResumes=resumes,recognitionAdds=enqueues;
    require(selectedMv()&&!ready()&&canEnqueueSelection(),"a real selected MV remains recognized while offline export is unbound");
    require(requestEnqueue(menu,30,1,16000000)&&enqueues==recognitionAdds+1&&menu.intent==null&&starts==recognitionStarts&&resumes==recognitionResumes,"selection-only Add preserves the server menu and cannot start or resume rendering");
    for(Object invalid:new Object[]{"true",1,true==false,null}){
      lastQueue.put("can_add",invalid);require(!canEnqueueSelection(),"only a native Boolean true can authorize Add");
    }
    gameDestroyed(found);require(!selectedMv()&&!foregroundMvSelected,"destroyed owner retires recognition independently from export readiness");
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
    // A user pause survives natively past Cancel; hand it back to the real
    // lifecycle so the next queued job is never parked by a stale request.
    Activity owner=new Activity();game=new WeakReference<>(owner);resumed=true;stopped=false;userPaused=true;
    int beforeResumes=resumes,beforeSuspends=suspends,beforeCancels=cancels;
    cancel();require(!userPaused&&cancels==beforeCancels+1&&resumes==beforeResumes+1&&suspends==beforeSuspends,"a visible player's cancelled user pause is released");
    userPaused=true;resumed=false;stopped=true;
    cancel();require(resumes==beforeResumes+1&&suspends==beforeSuspends+1&&reason==1,"a hidden player's cancelled user pause becomes a lifecycle park");
    userPaused=false;resumed=true;stopped=false;
    cancel();require(resumes==beforeResumes+1&&suspends==beforeSuspends+1,"an ordinary cancel leaves lifecycle state untouched");
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
    source = SOURCE.read_text()
    selected = "\n".join(method(source, name) for name in ("controllerDiscovery", "snapshot", "traceInteger", "mergeSessionProgress", "diagnostics"))
    fixture = tmp_path / "DiagnosticsHarness.java"
    fixture.write_text(r'''
import java.util.*;import java.lang.ref.WeakReference;
public class DiagnosticsHarness {
 static boolean configured=true,initialized=true,resumed,gameFocused,stopped=true,foregroundSelectionReady=true,saving;
 static String pendingSaveId;
 static class Activity {boolean isDestroyed(){return false;}boolean isFinishing(){return false;}}
 static WeakReference<Activity> game=new WeakReference<>(new Activity());static boolean queueConfigured=true;
 static JSONObject last=new JSONObject(),queue=new JSONObject(),nativeValue=new JSONObject();
 static JSONObject lastNativeTrace;static Context application;static boolean foregroundMvSelected=true;
 static class Context {static final int MODE_PRIVATE=0;Preferences getSharedPreferences(String k,int mode){return new Preferences();}}
 static class Preferences {String getString(String k,String fallback){return fallback;}boolean getBoolean(String k,boolean fallback){return true;}}
 static boolean userPaused=true,pendingQueueRun;static boolean experimentalBackgroundEnabled(Context c){return c.getSharedPreferences("mp4_export",0).getBoolean("experimental_background",false);}
 static class UnifiedMP4Background {static JSONObject snapshot(){return new JSONObject().put("state","probing").put("error_code","/private/surface")
  .put("heartbeat_verified",true).put("capture_verified",false).put("raw_surface","0xdead");}}
 static JSONObject progressDocument;static JSONObject readNativeDiagnostics(){return progressDocument;}static JSONObject exportTrace(JSONObject document){return null;}
 static JSONObject savedNativeTrace(String key){return null;}static JSONObject javaCrashDiagnostics(Context c){return null;}static JSONObject lastCancelDiagnostics(Context c){return null;}

 static class JSONObject {static final Map<String,JSONObject> refs=new HashMap<>();final Map<String,Object> map=new LinkedHashMap<>();
  JSONObject(){}JSONObject(String raw){map.putAll(refs.get(raw).map);}JSONObject put(String k,Object v){map.put(k,v);return this;}
  Object opt(String key){return map.get(key);}Object remove(String key){return map.remove(key);}int length(){return map.size();}
  JSONObject optJSONObject(String key){return map.get(key) instanceof JSONObject?(JSONObject)map.get(key):null;}
  public String toString(){String key="json_"+refs.size();refs.put(key,this);return key;}
  boolean optBoolean(String k){return Boolean.TRUE.equals(map.get(k));}String optString(String k,String fallback){Object v=map.get(k);return v instanceof String?(String)v:fallback;}
  long optLong(String k){Object v=map.get(k);return v instanceof Number?((Number)v).longValue():0;}
  JSONArray optJSONArray(String k){return map.get(k) instanceof JSONArray?(JSONArray)map.get(k):null;}}
 static class JSONArray {int size;final Map<Integer,Object> rows=new HashMap<>();JSONArray(){}JSONArray(int n){size=n;}
  int length(){return size;}JSONArray put(Object value){rows.put(size++,value);return this;}
  JSONObject optJSONObject(int index){Object value=rows.get(index);return value instanceof JSONObject?(JSONObject)value:null;}}
 static JSONArray documentDiagnostics(){return new JSONArray(0);}
 static JSONObject queueSnapshot(){return queue;}
 static String nativeStatus(){JSONObject.refs.put("native",nativeValue);return "native";}
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
''' + selected + r'''
 public static void main(String[] args){
  last.put("phase","stale");
  nativeValue.put("ready",false).put("phase","idle").put("readiness_error","selected_capture_geometry_unsupported")
   .put("pipeline_mode","fresh_original_scene")
   .put("error_code","../private/broker.capability").put("restoration_error","fresh_logical_restore_failed").put("pause_reason","none")
   .put("width",0).put("height",0).put("source_width",4095).put("source_height",2457)
   .put("fps_num",60).put("fps_den",1).put("video_bitrate",17250000).put("unity_ticks",51L).put("capture_acks",-1L)
   .put("frames",Long.MAX_VALUE).put("total_frames",100L)
   .put("directory","/private/broker").put("capability","b6bcf1ca5802a5b5bd5376fb893ff190")
   .put("export_id","01234567890123456789012345678901").put("pcm_path","/private/exports/private.pcm");
  JSONObject discovered=new JSONObject().put("reason","selected_render_controller_missing").put("source","camera_component")
   .put("listed_directors",17).put("unique_directors",8L).put("assets",32).put("output_tracks",65537L)
   .put("camera_tracks",Long.MAX_VALUE).put("null_assets",Long.MIN_VALUE).put("candidate_controllers",0)
   .put("raw_address","0x1234abcd").put("director_pointer",123456789L).put("capability","private")
   .put("controllers",new JSONArray(1000)).put("unknown",new JSONObject().put("nested_address","0xfeed"));
  nativeValue.put("controller_discovery",discovered);
  queue.put("available",true).put("running",false).put("paused",true).put("jobs",new JSONArray(100))
   .put("error_code","queue_install_new_failed").put("storage_stage","install_new").put("storage_errno",1)
   .put("queue_root","/private/queue").put("selected_characters","unpublished private payload");
  JSONObject result=diagnostics();
  need(result.map.get("phase").equals("idle"),"diagnostics obtains current native status rather than stale UI snapshot");
  need(result.map.get("readiness_error").equals("selected_capture_geometry_unsupported"),"actual readiness reason survives");
  need(result.map.get("pipeline_mode").equals("fresh_original_scene"),"actual original-scene mode survives without inventing legacy verification");
  need(result.map.get("user_paused").equals(true)&&result.map.get("pending_queue_run").equals(false)&&result.map.get("experimental_background").equals(false),
   "lifecycle pause and experimental transport flags are explicit (no application context means not enabled)");
  JSONObject transport=(JSONObject)result.map.get("background");
  need(transport.map.get("state").equals("probing")&&transport.map.get("error_code").equals("unknown")&&transport.map.get("heartbeat_verified").equals(true)
   &&transport.map.get("capture_verified").equals(false)&&!transport.map.containsKey("raw_surface"),"experimental transport state is bounded");
  need(result.map.get("job_stage").equals("idle")&&result.map.get("cleanup_stage").equals("none")&&result.map.get("cleanup_wait_ms").equals(0L),
   "an absent separate progress ABI reports idle with no pending cleanup");
  progressDocument=new JSONObject().put("session_progress",new JSONObject().put("job_stage","restore_retire")
   .put("cleanup_stage","fresh_cleanup_awaiting_actor_reset").put("cleanup_wait_ms",61000L).put("boundary_entries",4242L).put("path","/private/x"));
  JSONObject cleanup=diagnostics();
  need(cleanup.map.get("job_stage").equals("restore_retire")&&cleanup.map.get("cleanup_stage").equals("fresh_cleanup_awaiting_actor_reset")
   &&cleanup.map.get("cleanup_wait_ms").equals(61000L)&&cleanup.map.get("boundary_entries").equals(4242L)&&!cleanup.map.containsKey("path"),"the pending original cleanup join and its age are exported as bounded scalars");
  progressDocument=new JSONObject().put("session_progress",new JSONObject().put("job_stage","../private").put("cleanup_stage","/private/stage").put("cleanup_wait_ms",-5L));
  JSONObject hostile=diagnostics();
  need(hostile.map.get("job_stage").equals("unknown")&&hostile.map.get("cleanup_stage").equals("none")&&hostile.map.get("cleanup_wait_ms").equals(0L),"progress values are bounded codes");
  progressDocument=null;
  for(Object mode:new Object[]{"/private/path","unknown",true,1,new JSONObject()}){
   nativeValue.put("pipeline_mode",mode);need(!diagnostics().map.containsKey("pipeline_mode"),"unknown pipeline values are not copied");
  }
  nativeValue.put("pipeline_mode","legacy_owned_scene");need(diagnostics().map.get("pipeline_mode").equals("legacy_owned_scene"),"legacy mode remains explicit");
  need(result.map.get("error_code").equals("unknown"),"non-code/path error text is not copied");
  need(result.map.get("restoration_error").equals("fresh_logical_restore_failed"),"media completion retains separate restoration warning");
  need(result.map.get("source_width").equals(4095L)&&result.map.get("source_height").equals(2457L),"idle source geometry survives");
  need(result.map.get("video_bitrate").equals(17250000L)&&result.map.get("fps_num").equals(60L),"actual encoder scalars survive");
  need(result.map.get("capture_acks").equals(0L)&&result.map.get("frames").equals(9007199254740991L),"numeric fields bounded");
  need(result.map.get("queue_job_count").equals(8)&&result.map.get("queue_paused").equals(true),"queue count bounded without job contents");
  need(result.map.get("queue_error_code").equals("queue_install_new_failed")
   &&result.map.get("queue_storage_stage").equals("install_new")&&result.map.get("queue_storage_errno").equals(1L),"queue storage stage and errno survive without paths");
  JSONArray detailedJobs=new JSONArray().put(new JSONObject().put("state","failed")
   .put("error_code","fresh_audio_source_mixer_unsupported").put("job_id","secret-id").put("path","/private/video"));
  for(int i=1;i<12;i++)detailedJobs.put(new JSONObject().put("state","/private/state").put("error_code","../private/error"));
  queue.put("phase","failed").put("jobs",detailedJobs);
  JSONObject detail=diagnostics();JSONArray states=detail.optJSONArray("queue_job_states");
  need(detail.map.get("queue_phase").equals("failed")&&states.length()==8,"queue stage and at most eight job observations survive");
  JSONObject failedJob=states.optJSONObject(0);
  need(failedJob.length()==3&&failedJob.map.get("position").equals(0)&&failedJob.map.get("state").equals("failed")
   &&failedJob.map.get("error_code").equals("fresh_audio_source_mixer_unsupported"),"actual per-job failure survives without identity or path");
  need(states.optJSONObject(1).map.get("state").equals("unknown")
   &&states.optJSONObject(1).map.get("error_code").equals("unknown"),"job diagnostic fields never include paths");
  queue.put("phase","/private/phase");need(diagnostics().map.get("queue_phase").equals("unknown"),"queue phase is a bounded code");
  queue.put("error_code","/private/queue").put("storage_stage","/private/path").put("storage_errno",Long.MAX_VALUE);
  JSONObject invalidStorage=diagnostics();
  need(invalidStorage.map.get("queue_error_code").equals("unknown")&&!invalidStorage.map.containsKey("queue_storage_stage")
   &&invalidStorage.map.get("queue_storage_errno").equals(4095L),"storage observations reject paths and saturate integers");
  for(Object invalid:new Object[]{"1",true,1.0,Double.NaN,new JSONObject()}){
   queue.put("storage_errno",invalid);need(!diagnostics().map.containsKey("queue_storage_errno"),"storage errno never coerces noninteger input");
  }
  queue.put("storage_stage","unknown_private_token").put("storage_errno",Long.MIN_VALUE);
  need(!diagnostics().map.containsKey("queue_storage_stage")&&diagnostics().map.get("queue_storage_errno").equals(0L),"only known stage tokens and bounded errno are exported");
  for(String key:new String[]{"directory","capability","export_id","pcm_path","jobs","queue_root","selected_characters"})
   need(!result.map.containsKey(key),"private field omitted: "+key);
  need(result.map.get("verified_foreground_selection").equals(true)&&result.map.get("game_attached").equals(true),"lifecycle facts preserved");
  JSONObject copied=result.optJSONObject("controller_discovery");
  need(copied!=null&&copied.length()==9,"only the nine whitelisted discovery fields survive");
  need(copied.map.get("reason").equals("selected_render_controller_missing")&&copied.map.get("source").equals("camera_component"),"current native controller reason and source survive diagnostics");
  need(copied.map.get("listed_directors").equals(17L)&&copied.map.get("unique_directors").equals(8L)&&copied.map.get("assets").equals(32L),"integer observations preserved");
  need(copied.map.get("output_tracks").equals(65536L)&&copied.map.get("camera_tracks").equals(65536L)&&copied.map.get("null_assets").equals(0L),"discovery counts saturate without overflow");
  for(String key:new String[]{"raw_address","director_pointer","capability","controllers","unknown"})need(!copied.map.containsKey(key),"discovery field redacted: "+key);
  last.put("phase","paused").put("export_id","owned_output").put("controller_discovery",discovered);
  JSONObject ui=snapshot();JSONObject uiDiscovery=ui.optJSONObject("controller_discovery");
  need(ui.map.get("phase").equals("paused")&&ui.map.get("export_id").equals("owned_output"),"existing snapshot fields remain unchanged");
  need(uiDiscovery!=null&&uiDiscovery.length()==9,"the actual UI snapshot uses the same bounded discovery whitelist");
  uiDiscovery.put("reason","changed_copy");need(discovered.map.get("reason").equals("selected_render_controller_missing"),"sanitized copies cannot mutate native state");
  need(discovered.map.containsKey("raw_address"),"sanitizing output never mutates source observations");
  for(String origin:new String[]{"none","observed","singleton","camera_component"}){
   last.put("controller_discovery",new JSONObject().put("source",origin));
   need(snapshot().optJSONObject("controller_discovery").map.get("source").equals(origin),"known discovery source survives: "+origin);
  }
  for(Object invalid:new Object[]{"",new JSONArray(2),"/private/path","0x1234abcd","unknown_source",new String(new char[25]).replace('\0','a'),17,true}){
   last.put("controller_discovery",new JSONObject().put("reason","safe_reason").put("source",invalid));
   need(!snapshot().optJSONObject("controller_discovery").map.containsKey("source"),"unknown or malformed source omitted");
  }
  String exactReason=new String(new char[96]).replace('\0','a');
  last.put("controller_discovery",new JSONObject().put("reason",exactReason));
  need(snapshot().optJSONObject("controller_discovery").map.get("reason").equals(exactReason),"96 character ASCII reason allowed");
  for(Object invalid:new Object[]{"",exactReason+"a","private/address","line\nbreak","한글",17,true,new JSONObject()}){
   last.put("controller_discovery",new JSONObject().put("reason",invalid).put("assets",2));
   JSONObject safe=snapshot().optJSONObject("controller_discovery");need(safe.length()==1&&safe.map.get("assets").equals(2L),"invalid reason omitted without discarding valid counters");
  }
  last.put("controller_discovery",new JSONObject().put("listed_directors","10").put("unique_directors",true)
   .put("assets",1.5).put("output_tracks",1.0).put("camera_tracks",Double.NaN).put("null_assets",Double.POSITIVE_INFINITY)
   .put("candidate_controllers",new JSONObject()));
  need(snapshot().optJSONObject("controller_discovery")==null,"noninteger values are not coerced to public counts");
  for(Object invalid:new Object[]{"0xraw",new JSONArray(4),new JSONObject().put("raw_pointer","0xabc")}){
   last.put("controller_discovery",invalid);need(!snapshot().map.containsKey("controller_discovery"),"invalid or unknown-only discovery omitted");
  }
  last.remove("controller_discovery");need(!snapshot().map.containsKey("controller_discovery"),"absent optional discovery stays absent");
  nativeValue.put("controller_discovery",new JSONObject().put("raw_address","0xabc"));
  need(!diagnostics().map.containsKey("controller_discovery"),"unknown-only current native object cannot leak into exported diagnostics");
  last.put("phase","stale");
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
    production = "\n".join(method(source, name) for name in ("backgroundQueueHasWork", "publicCode", "sessionOwnsCurrentQueueJob",
                                                             "cleanupText", "statusText", "enqueueFailureText"))
    resources = sorted(set(re.findall(r"R\.string\.([a-z0-9_]+)", production)))
    declarations = "".join(f"static final int {name}={index};" for index, name in enumerate(resources, 1))
    harness = tmp_path / "QueueStatusHarness.java"
    harness.write_text(r'''import java.util.*;
public final class QueueStatusHarness {
 static boolean configured=true,saving,pendingQueueRun,mvReady,mvSelected,completedOutput;static int[] pending;static int readyCalls;
 static JSONObject last=new JSONObject(),lastQueue=new JSONObject();
 static final class JSONObject {
  final Map<String,Object> values=new HashMap<>();
  JSONObject put(String key,Object value){values.put(key,value);return this;}
  Object remove(String key){return values.remove(key);}
  boolean optBoolean(String key){return Boolean.TRUE.equals(values.get(key));}
  long optLong(String key){Object value=values.get(key);return value instanceof Number?((Number)value).longValue():0;}
  String optString(String key){return optString(key,"");}
  String optString(String key,String fallback){Object value=values.get(key);return value instanceof String?(String)value:fallback;}
  JSONArray optJSONArray(String key){Object value=values.get(key);return value instanceof JSONArray?(JSONArray)value:null;}
 }
 static final class JSONArray {final List<JSONObject> rows=new ArrayList<>();JSONArray put(JSONObject row){rows.add(row);return this;}
  int length(){return rows.size();}JSONObject optJSONObject(int index){return rows.get(index);}}
 static final class Context {String getString(int resource,Object...args){return "resource="+resource+Arrays.toString(args);}}
 static final class R {static final class string {''' + declarations + r'''}}
 static boolean ready(){readyCalls++;return mvReady;}
 static boolean selectedMv(){return mvSelected;}
 static JSONObject queueSnapshot(){return lastQueue;}
 static boolean hasCompletedOutput(){return completedOutput;}
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
  last.put("phase","failed").put("error_code","fresh_audio_source_mixer_unsupported");
  lastQueue.put("error_code","fresh_audio_source_mixer_unsupported");
  expect(context,R.string.mp4_failed,"current preparation failure is visible while the original cleanup join is still running");
  need(statusText(context).contains("fresh_audio_source_mixer_unsupported"),"the actual failure code is never replaced by a generic preparing message");
  lastQueue.put("error_code","none").put("current_job_id","job2").put("jobs",new JSONArray().put(new JSONObject().put("job_id","job2").put("output_id","out2").put("state","running")));
  last.put("phase","failed").put("error_code","fresh_scene_acquire_timeout").put("export_id","out2")
   .put("cleanup_stage","fresh_cleanup_awaiting_actor_reset").put("cleanup_wait_ms",75000L);
  expect(context,R.string.mp4_failed,"the running job's own failure in cleanup is never relabeled as scene preparation");
  need(statusText(context).contains("fresh_scene_acquire_timeout"),"the current job's actual failure code is shown");
  need(statusText(context).contains("resource="+R.string.mp4_cleanup_waiting+"[fresh_cleanup_awaiting_actor_reset, 75]"),"the pending original cleanup join and its age are named");
  need(statusText(context).contains("resource="+R.string.mp4_cleanup_stalled+"[75]"),"a long cleanup stall offers restart guidance");
  last.put("cleanup_stage","none").put("cleanup_wait_ms",0L);
  expect(context,R.string.mp4_failed,"the current job's terminal row is identified by its exact output identity");
  last.put("phase","cancelled");expect(context,R.string.mp4_cancelled,"the current job's cancellation stays visible through cleanup");
  last.put("export_id","out1").put("phase","failed");
  expect(context,R.string.mp4_queue_waiting_scene,"an older job's terminal row still yields to the next queued scene");
  lastQueue.put("phase","restoring_selection").put("error_code","queued_scene_readiness_timeout");
  expect(context,R.string.mp4_failed,"a queue preparation failure stays visible through its original cleanup join");
  need(statusText(context).contains("queued_scene_readiness_timeout"),"the queue preparation failure code is shown");
  lastQueue.put("phase","saving_selection").put("error_code","none");
  expect(context,R.string.mp4_queue_waiting_scene,"genuine queue preparation still reports scene preparation");
  need(statusText(context).endsWith("(saving_selection)"),"the actual queue preparation phase is named");
  lastQueue.remove("phase");lastQueue.remove("current_job_id");lastQueue.remove("jobs");
  last.remove("export_id");last.remove("cleanup_stage");last.remove("cleanup_wait_ms");
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
  lastQueue.put("can_run",true).put("jobs",new JSONArray().put(new JSONObject().put("state","pending")));
  expect(context,R.string.mp4_queue_ready,"a saved runnable queue never asks the user to play an MV");
  lastQueue.put("can_run",false);expect(context,R.string.mp4_not_ready,"a queue snapshot alone does not invent engine readiness");
  completedOutput=true;expect(context,R.string.mp4_completed,"a retained completed output remains discoverable after native idle");
  completedOutput=false;
  mvSelected=true;last.put("readiness_error","offline_pipeline_not_verified");
  expect(context,R.string.mp4_selected_not_ready_reason,"a detected MV with an unbound renderer must never ask the user to reopen it");
  last.put("readiness_error","none");expect(context,R.string.mp4_selected_not_ready,"a selected source remains visible independently of export readiness");
  lastQueue.put("add_error","selected_snapshot_changed");
  need(enqueueFailureText(context).startsWith("resource="+R.string.mp4_queue_error+"["),"stale Add rejection names its actual immutable snapshot error");
  lastQueue.put("add_error","/private/path");
  need(enqueueFailureText(context).startsWith("resource="+R.string.mp4_selected_not_ready+"["),"malformed Add details cannot turn a detected MV into the open-MV instruction or leak a path");
  lastQueue.remove("add_error");
  mvSelected=false;last.put("selection_error","native_bridge_init_failed");expect(context,R.string.mp4_not_ready_reason,"initialization failure remains an explicit selection error");
  last.remove("selection_error");
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
    production = "\n".join(method(SOURCE.read_text(), name) for name in ("serverStopped", "invalidateQueueSelection"))
    harness = tmp_path / "ServerStopHarness.java"
    harness.write_text(r'''import java.util.*;
public final class ServerStopHarness {
 static boolean configured,initialized,queueConfigured,foregroundSelectionReady,foregroundMvSelected,throwPause,throwInvalidate,queueParked;
 static long menuHandoffDeadline;static int[] pending;static int pauseResult;
 static final class JSONObject {final Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}}
 static JSONObject lastQueue=new JSONObject();
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
 static void nativeInvalidateQueueSelection(){events.add("invalidate");if(throwInvalidate)throw new UnsatisfiedLinkError("optional snapshot addon unavailable");}
 static void cancel(){events.add("cancel");}static void cancelFrom(String origin){cancel();}
 static void wake(){events.add("wake");}
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
 static void reset(boolean loaded,boolean queued){
  configured=true;initialized=loaded;queueConfigured=queued;foregroundSelectionReady=true;menuHandoffDeadline=8000;
  pending=new int[]{60,1,2};throwPause=false;throwInvalidate=false;queueParked=false;pauseResult=0;events.clear();MAIN.work.clear();
 }
''' + production + r'''
 public static void main(String[]arguments){
  reset(true,true);lastQueue=new JSONObject().put("running",true);serverStopped();
  need(events.equals(Arrays.asList("pause","invalidate"))&&queueParked,"native queue is parked and its Add snapshot retired synchronously without waiting for paused Unity");
  need(!configured&&!queueConfigured&&!foregroundSelectionReady&&menuHandoffDeadline==0,"server stop retires host availability and cached menu eligibility");
  need(MAIN.work.size()==1&&pending!=null,"existing main-thread session cleanup remains deferred");
  MAIN.drain();need(events.equals(Arrays.asList("pause","invalidate","cancel","wake"))&&pending==null&&queueParked,"session cancellation follows queue parking without resuming the queue");
  need(lastQueue.map.isEmpty(),"an unconfigured queue's last running snapshot never stays visible as live work");
  serverStopped();need(Collections.frequency(events,"pause")==1,"a repeated stop cannot call an already-retired queue");MAIN.drain();
  reset(true,false);serverStopped();need(events.equals(Arrays.asList("invalidate")),"an unconfigured queue still retires cached selection without receiving pause");MAIN.drain();
  need(events.equals(Arrays.asList("invalidate","cancel","wake")),"queue absence preserves existing session cleanup");
  reset(false,true);serverStopped();need(events.isEmpty(),"an uninitialized optional native addon never receives queue pause");MAIN.drain();
  reset(true,true);throwPause=true;serverStopped();MAIN.drain();
  need(events.equals(Arrays.asList("pause","invalidate","cancel","wake"))&&!configured&&!queueConfigured&&pending==null,"optional JNI absence cannot prevent server/session retirement");
  reset(true,true);pauseResult=-1;serverStopped();MAIN.drain();
  need(events.equals(Arrays.asList("pause","invalidate","cancel","wake"))&&!configured&&!queueConfigured,"a rejected host pause cannot prevent safe host cleanup");
  reset(true,true);throwInvalidate=true;serverStopped();MAIN.drain();
  need(events.equals(Arrays.asList("pause","invalidate","cancel","wake"))&&!configured&&!queueConfigured&&!foregroundSelectionReady,"optional snapshot JNI absence cannot preserve stale UI eligibility or block cleanup");
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


def test_real_android_controller_and_json_snapshot_api_compile(tmp_path):
    javac = shutil.which("javac")
    homes = [Path(os.environ.get("ANDROID_HOME", "/nonexistent")), Path("/workspace/.setup/android-sdk")]
    android = next((home / f"platforms/android-{version}/android.jar"
                    for version in (35, 34) for home in homes
                    if (home / f"platforms/android-{version}/android.jar").is_file()), None)
    if not javac or android is None:
        pytest.skip("JDK and actual Android SDK required")
    package = "game.qualiarts.idolypride.localserver"
    resource_names = sorted(set(re.findall(r"R\.string\.([A-Za-z0-9_]+)", SOURCE.read_text())))
    resources = "".join(f"static final int {name}={index};" for index, name in enumerate(resource_names, 1))
    stubs = {
        "R.java": f"package {package}; final class R {{static class string {{{resources}}}}}",
        "UnifiedRuntime.java": f"package {package}; final class UnifiedRuntime {{static boolean isEnabled(android.content.Context c){{return false;}}}}",
        "UnifiedMP4Background.java": f"""package {package};
final class UnifiedMP4Background {{
 interface Host {{org.json.JSONObject status();void park();void resume();boolean userPaused();void changed();}}
 static org.json.JSONObject snapshot(){{return new org.json.JSONObject();}}
 static void prepare(android.app.Activity a,Host host){{}}
 static void stopCurrent(){{}}static void backgrounded(android.app.Activity a){{}}
 static void foregrounding(android.app.Activity a){{}}static void focusLost(android.app.Activity a){{}}
 static boolean ownsSurface(android.app.Activity a){{return false;}}
 static void sample(org.json.JSONObject state){{}}static boolean expectsService(){{return false;}}
}}""",
        "UnifiedMP4Service.java": f"package {package}; final class UnifiedMP4Service {{static void update(String text,long frames,long total){{}}}}",
    }
    paths = []
    for name, content in stubs.items():
        path = tmp_path / name
        path.write_text(content)
        paths.append(path)
    compiled = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-cp", str(android),
                               "-d", str(tmp_path / "classes"), str(SOURCE),
                               str(SOURCE.with_name("Mp4TitleCatalog.java")), str(SOURCE.with_name("Mp4ExportSettings.java")),
                               str(SOURCE.with_name("Mp4CompletedExports.java")),
                               str(SOURCE.with_name("DocumentPickerHistory.java")),
                               *map(str, paths)], capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stderr
