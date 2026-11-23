"""Execute production background progress policy and compile real Android APIs."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver"


def test_shared_default_egl_display_cleanup_balances_only_owned_initialization(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = (JAVA / "UnifiedMP4Background.java").read_text().split("private static final class Drain", 1)[1]
    start = source.index("        void release() {")
    cursor = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    cleanup = source[start:cursor]
    fixture = tmp_path / "EglOwnershipFixture.java"
    fixture.write_text(r'''
public class EglOwnershipFixture {
  static int refs,terminates,contexts,pbuffers,textures,consumers,eglThreads,stoppedThreads,unbinds;
  static final Object SHARED_DISPLAY=new Object(),OWNED_CONTEXT=new Object(),OWNED_PBUFFER=new Object();
  static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
  static class EGL14 {
    static final Object EGL_NO_DISPLAY=new Object(),EGL_NO_CONTEXT=new Object(),EGL_NO_SURFACE=new Object();
    static void eglMakeCurrent(Object d,Object draw,Object read,Object c){
      need(d==SHARED_DISPLAY&&draw==EGL_NO_SURFACE&&read==EGL_NO_SURFACE&&c==EGL_NO_CONTEXT,"unbind only this EGL thread");unbinds++;}
    static void eglDestroySurface(Object d,Object s){need(d==SHARED_DISPLAY&&s==OWNED_PBUFFER,"only owned pbuffer");pbuffers++;}
    static void eglDestroyContext(Object d,Object c){need(d==SHARED_DISPLAY&&c==OWNED_CONTEXT,"only owned context");contexts++;}
    static void eglReleaseThread(){eglThreads++;}
    static void eglTerminate(Object d){need(d==SHARED_DISPLAY,"known display");refs--;terminates++;}
  }
  static class GLES20 {static void glDeleteTextures(int n,int[] ids,int offset){need(n==1&&ids[offset]==7,"only owned texture");textures++;}}
  static class Consumer {void release(){consumers++;}void setOnFrameAvailableListener(Object listener){need(listener==null,"remove callback");}}
  static class Worker {void quitSafely(){stoppedThreads++;}}
  static class Drain {
    Object display=SHARED_DISPLAY,context=EGL14.EGL_NO_CONTEXT,pbuffer=EGL14.EGL_NO_SURFACE;
    Consumer surface,texture;int textureId;boolean closed,initializedDisplay;
    Worker thread=new Worker();
''' + cleanup + r'''
  }
  static void reset(){refs=1;terminates=contexts=pbuffers=textures=consumers=eglThreads=stoppedThreads=unbinds=0;}
  public static void main(String[] args){
    reset();Drain failed=new Drain();failed.release();failed.release();
    need(refs==1&&terminates==0&&unbinds==0&&contexts==0&&pbuffers==0,"failed initialize cannot terminate Unity's reference");
    need(stoppedThreads==1,"failed setup cleanup is idempotent");
    reset();Drain complete=new Drain();refs++;complete.initializedDisplay=true;
    complete.context=OWNED_CONTEXT;complete.pbuffer=OWNED_PBUFFER;complete.textureId=7;
    complete.surface=new Consumer();complete.texture=new Consumer();complete.release();complete.release();
    need(refs==1&&terminates==1,"balance precisely one helper reference, preserving Unity");
    need(contexts==1&&pbuffers==1&&textures==1&&consumers==2&&eglThreads==1&&stoppedThreads==1,"release only owned resources once");
    need(!complete.initializedDisplay&&complete.closed,"ownership cleared before repeated cleanup");
    reset();Drain partial=new Drain();refs++;partial.initializedDisplay=true;partial.release();
    need(refs==1&&terminates==1&&contexts==0&&pbuffers==0,"post-initialize setup failure balances its own reference");
    System.out.println("PASS shared EGL reference ownership");
  }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(fixture)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "EglOwnershipFixture"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS shared EGL reference ownership"


def test_real_android_transport_compiles_and_progress_gate_checks_actual_capture(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    homes = [Path(os.environ.get("ANDROID_HOME", "/nonexistent")), Path("/workspace/.setup/android-sdk")]
    android = next((home / "platforms/android-34/android.jar" for home in homes
                    if (home / "platforms/android-34/android.jar").is_file()), None)
    if not javac or not java or android is None:
        pytest.skip("JDK and actual Android SDK34 required")
    package = "game.qualiarts.idolypride.localserver"
    sources = {
        "UnifiedMP4Export.java": f"""package {package}; final class UnifiedMP4Export {{
            static void cancel(){{}}static boolean queuePause(){{return true;}}
            static String statusText(android.content.Context c){{return "status";}}
            static boolean backgroundQueueHasWork(){{return false;}} }}""",
        "UnifiedRuntime.java": f"""package {package}; final class UnifiedRuntime {{
            static int notificationIcon(android.content.Context c,int fallback){{return fallback;}} }}""",
        "MainActivity.java": f"package {package}; public class MainActivity extends android.app.Activity {{}}",
        "R.java": f"""package {package}; final class R {{static class drawable {{static int ic_server=1;}}
            static class string {{static int mp4_progress_title=2,mp4_rendering=3,mp4_cancel=4;}} }}""",
        "BackgroundGateFixture.java": f"""package {package};
public class BackgroundGateFixture {{
  static void need(boolean value,String message){{if(!value)throw new AssertionError(message);}}
  public static void main(String[] args){{
    UnifiedMP4Background.ProgressGate gate=new UnifiedMP4Background.ProgressGate();
    gate.begin(0,10,3);
    need(gate.sample(4000,11,3,false,0)&&gate.heartbeatVerified&&!gate.captureVerified,"audio heartbeat is not render proof");
    for(int i=2;i<=12;i++)need(gate.sample(i*4000L,10+i,3,false,0),"long audio preparation must not hit render timeout");
    need(gate.sample(49000,23,4,true,1)&&!gate.captureVerified,"one capture is insufficient");
    need(gate.sample(50000,24,5,true,1)&&!gate.captureVerified,"consumer must also drain the surface");
    need(gate.sample(51000,25,5,true,2)&&gate.captureVerified,"two real captures plus drain and heartbeat");
    need(!gate.sample(56000,25,5,true,2),"stalled Unity must park after five seconds");
    gate.begin(0,1,1);need(gate.sample(100,2,3,true,2),"capture begins");
    need(!gate.sample(5100,100,3,true,99),"heartbeat alone cannot hide a later capture stall");
    gate.begin(0,1,1);need(gate.sample(100,2,3,true,2),"first queued job verified");
    need(gate.sample(20000,100,3,false,40),"next soundtrack can take longer than render timeout");
    need(gate.sample(21000,101,4,true,41)&&!gate.captureVerified,"next job starts a fresh capture gate");
    need(gate.sample(22000,102,5,true,42)&&gate.captureVerified,"next queued MV proves its own capture");
    gate.begin(0,100,100);
    need(gate.sample(1000,101,100,true,20),"probe starts");
    need(!gate.sample(6000,106,100,true,30),"surface-only progress cannot masquerade as capture");
    gate.begin(0,100,100);
    need(!gate.sample(1,99,100,false,0),"counter reset invalidates ownership proof");
    gate.begin(0,100,100);
    need(!gate.sample(5000,100,100,false,0),"audio also needs a live original Unity heartbeat");
    gate.begin(0,100,100);
    need(gate.sample(10,101,102,true,2)&&gate.captureVerified,"fresh probe can progress");
    gate.begin(20,101,102);
    need(!gate.heartbeatVerified&&!gate.captureVerified,"new transport must not inherit earlier evidence");
    System.out.println("PASS real Android background API compile and progress gate");
  }}
}}""",
    }
    paths = []
    for name, text in sources.items():
        path = tmp_path / name
        path.write_text(text)
        paths.append(path)
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-cp", str(android), "-d", str(classes),
                               str(JAVA / "UnifiedMP4Background.java"), str(JAVA / "UnifiedMP4Service.java"), *map(str, paths)],
                              capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", os.pathsep.join((str(classes), str(android))),
                             package + ".BackgroundGateFixture"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS real Android background API compile and progress gate"
