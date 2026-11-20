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


def test_controller_waits_for_live_game_and_cancels_without_recreating_it(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = SOURCE.read_text()
    selected = [method(source, name) for name in ["privateDirectory", "completedFile", "busy", "ready", "requestStart",
                "beginPending", "gamePaused", "gameDestroyed", "cancel"]]
    prefix = r'''
import java.io.*;import java.nio.file.*;import java.lang.ref.WeakReference;import java.util.*;
public final class ControllerHarness {
  static boolean configured=true,initialized=true,saving,resumed,allowNative=true,dismissed=true;
  static int[] pending,startedOptions;static long pendingDeadline;static int starts,cancels,wakes;
  static WeakReference<Activity> game=new WeakReference<>(null);
  static JSONObject last=new JSONObject();static final Handler MAIN=new Handler();static final Runnable BEGIN=()->{};
  static ViewGroup overlay;static Object overlayText,overlaySave,overlayCancel,overlayDismiss;
  static class JSONObject {Map<String,Object> map=new HashMap<>();JSONObject put(String k,Object v){map.put(k,v);return this;}
    String optString(String k,String d){return map.containsKey(k)?map.get(k).toString():d;}}
  static class Handler {int scheduled;void postDelayed(Runnable r,long delay){scheduled++;}void removeCallbacks(Runnable r){}}
  static class Activity {Intent intent;boolean destroyed,finishing;boolean isDestroyed(){return destroyed;}boolean isFinishing(){return finishing;}
    void startActivity(Intent i){intent=i;}}
  static class Intent {static final int FLAG_ACTIVITY_REORDER_TO_FRONT=1,FLAG_ACTIVITY_SINGLE_TOP=2;int flags;Class<?> target;
    Intent(Activity c,Class<?> t){target=t;}Intent addFlags(int f){flags=f;return this;}}
  static class ViewGroup {Object getParent(){return null;}void removeView(Object v){}}
  static class R {static class string {static final int mp4_not_ready=1,mp4_unavailable=2;}}
  static class Toast {static final int LENGTH_LONG=1;static Toast makeText(Activity a,int s,int l){return new Toast();}void show(){}}
  static boolean nativeReady(){return allowNative;}
  static int nativeStart(int n,int d,int c,int v,int a){starts++;startedOptions=new int[]{n,d,c,v,a};return 0;}
  static void nativeCancel(){cancels++;}static void wake(){wakes++;}
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
    gamePaused(new Activity());require(cancels==0,"stale instance cannot cancel current export");
    gamePaused(live);require(cancels==1&&!resumed,"background cancels current session");
    last=new JSONObject();pending=new int[]{30,1,1,8000000,192000};gamePaused(live);
    require(cancels==1&&pending!=null,"menu-to-game transition is not mistaken for export backgrounding");
    android.os.SystemClock.now=pendingDeadline+1;beginPending();require(pending==null&&starts==1,"bounded stale launch");
    pending=new int[]{30,1,1,8000000,192000};gameDestroyed(live);
    require(game.get()==null&&pending==null&&cancels==2,"destroy clears weak owner and pending work");
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
    compile_result = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(tmp_path / "classes"), str(harness), str(clock)],
                                    capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(tmp_path / "classes"), "ControllerHarness", str(tmp_path / "files")],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS controller"
