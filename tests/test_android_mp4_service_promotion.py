"""Execute the real UnifiedMP4Service start/stop ordering against an AMS model.

The service is started with startService() from the resumed game, so no stop
can violate a startForeground obligation; promotion still precedes any stop.

startForegroundService() obliges the started record to reach startForeground();
bringing that record down first makes system_server crash the whole app
(RemoteServiceException "did not then call Service.startForeground()").
The fixture models only that rule plus the Android calls the service makes.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Service.java"
PACKAGE = "game/qualiarts/idolypride/localserver/"

STUBS = {
    "android/content/Context.java": r'''package android.content;
public class Context {
  public static final String NOTIFICATION_SERVICE="notification",POWER_SERVICE="power";
  public static final java.util.List<String> log=new java.util.ArrayList<>();
  public static int pendingStarts;public static boolean crashed;
  // Only a startForegroundService record carries the startForeground obligation.
  public Object startForegroundService(Intent i){log.add("startForegroundService");pendingStarts++;return null;}
  public Object startService(Intent i){log.add("startService");return null;}
  public boolean stopService(Intent i){log.add("stopService");if(pendingStarts>0)crashed=true;return true;}
  public String getString(int id){return "s"+id;}
  public String getPackageName(){return "pkg";}
  public Object getSystemService(String name){
    return name.equals(NOTIFICATION_SERVICE)?new android.app.NotificationManager():new android.os.PowerManager();}
}''',
    "android/content/Intent.java": r'''package android.content;
public class Intent {String action;public Intent(Context c,Class<?> k){}
  public Intent setAction(String a){action=a;return this;}public String getAction(){return action;}}''',
    "android/app/Service.java": r'''package android.app;
public abstract class Service extends android.content.Context {
  public static final int START_NOT_STICKY=2,STOP_FOREGROUND_REMOVE=1;
  public boolean promoted;public static boolean failPromotion;
  public void onCreate(){}public void onDestroy(){}
  public abstract android.os.IBinder onBind(android.content.Intent i);
  public int onStartCommand(android.content.Intent i,int f,int s){return START_NOT_STICKY;}
  public final void startForeground(int id,Notification n,int type){
    log.add("startForeground");if(failPromotion)throw new IllegalStateException("type");
    promoted=true;if(pendingStarts>0)pendingStarts--;}
  public final void stopForeground(int flags){log.add("stopForeground");promoted=false;}
  public final void stopSelf(){log.add("stopSelf");if(pendingStarts>0)crashed=true;}
}''',
    "android/app/Notification.java": r'''package android.app;
public class Notification {
  public static class Style {}
  public static class BigTextStyle extends Style {public BigTextStyle bigText(CharSequence c){return this;}}
  public static class Action {public static class Builder {
    public Builder(Object icon,CharSequence t,PendingIntent p){}public Action build(){return new Action();}}}
  public static class Builder {
    public Builder(android.content.Context c,String channel){}
    public Builder setSmallIcon(int i){return this;}public Builder setContentTitle(CharSequence c){return this;}
    public Builder setContentText(CharSequence c){return this;}public Builder setStyle(Style s){return this;}
    public Builder setContentIntent(PendingIntent p){return this;}public Builder setOngoing(boolean b){return this;}
    public Builder setOnlyAlertOnce(boolean b){return this;}public Builder addAction(Action a){return this;}
    public Builder setProgress(int m,int p,boolean i){return this;}public Notification build(){return new Notification();}}
}''',
    "android/app/NotificationChannel.java": r'''package android.app;
public class NotificationChannel {public NotificationChannel(String id,CharSequence n,int i){}}''',
    "android/app/NotificationManager.java": r'''package android.app;
public class NotificationManager {public static final int IMPORTANCE_LOW=2;
  public void createNotificationChannel(NotificationChannel c){}public void notify(int id,Notification n){}}''',
    "android/app/PendingIntent.java": r'''package android.app;
public class PendingIntent {public static final int FLAG_UPDATE_CURRENT=1,FLAG_IMMUTABLE=2;
  public static PendingIntent getActivity(android.content.Context c,int r,android.content.Intent i,int f){return new PendingIntent();}
  public static PendingIntent getService(android.content.Context c,int r,android.content.Intent i,int f){return new PendingIntent();}}''',
    "android/os/Build.java": "package android.os; public class Build {public static class VERSION {public static final int SDK_INT=36;}}",
    "android/os/IBinder.java": "package android.os; public interface IBinder {}",
    "android/os/Looper.java": "package android.os; public class Looper {public static Looper getMainLooper(){return null;}}",
    "android/os/Handler.java": r'''package android.os;
public class Handler {public static final java.util.List<Runnable> posted=new java.util.ArrayList<>();
  public Handler(Looper l){}public boolean post(Runnable r){posted.add(r);return true;}
  public boolean postDelayed(Runnable r,long d){return true;}public void removeCallbacks(Runnable r){}}''',
    "android/os/SystemClock.java": "package android.os; public class SystemClock {public static long now=1000;public static long uptimeMillis(){return now;}}",
    "android/os/PowerManager.java": r'''package android.os;
public class PowerManager {public static final int PARTIAL_WAKE_LOCK=1;
  public WakeLock newWakeLock(int l,String t){return new WakeLock();}
  public static class WakeLock {boolean held;public void setReferenceCounted(boolean b){}
    public void acquire(long t){held=true;}public boolean isHeld(){return held;}public void release(){held=false;}}}''',
    PACKAGE + "R.java": r'''package game.qualiarts.idolypride.localserver;
final class R {static final class string {static final int mp4_progress_title=1,mp4_cancel=2;}
  static final class drawable {static final int ic_server=3;}}''',
    PACKAGE + "MainActivity.java": "package game.qualiarts.idolypride.localserver; class MainActivity {}",
    PACKAGE + "UnifiedRuntime.java": r'''package game.qualiarts.idolypride.localserver;
final class UnifiedRuntime {static int notificationIcon(android.content.Context c,int i){return i;}}''',
    PACKAGE + "UnifiedMP4Export.java": r'''package game.qualiarts.idolypride.localserver;
final class UnifiedMP4Export {static String statusText(android.content.Context c){throw new IllegalStateException("never needed to promote");}}''',
    PACKAGE + "UnifiedMP4Background.java": r'''package game.qualiarts.idolypride.localserver;
final class UnifiedMP4Background {static boolean expects=true;static int started,stopped;
  static boolean expectsService(){return expects;}static void serviceStarted(){started++;}
  static void serviceStopped(String reason,boolean cancelled){stopped++;}}''',
    PACKAGE + "PromotionFixture.java": r'''package game.qualiarts.idolypride.localserver;
import android.content.Context;import android.content.Intent;import android.os.SystemClock;
public class PromotionFixture {
  static void need(boolean b,String m){if(!b)throw new AssertionError(m+" log="+Context.log);}
  static void reset(){Context.log.clear();Context.pendingStarts=0;Context.crashed=false;
    android.app.Service.failPromotion=false;UnifiedMP4Background.expects=true;UnifiedMP4Background.started=0;}
  static UnifiedMP4Service deliver(){UnifiedMP4Service s=new UnifiedMP4Service();s.onCreate();s.onStartCommand(new Intent(s,UnifiedMP4Service.class),0,1);return s;}
  public static void main(String[] a){
    Context host=new Context();
    // The resumed game starts the service without a startForeground obligation.
    reset();need(UnifiedMP4Service.start(host),"start");
    need(Context.log.contains("startService")&&!Context.log.contains("startForegroundService"),"start must not create an FGS obligation");
    // A stop that races a pending start is still deferred until promotion.
    UnifiedMP4Service.stop(host);
    need(!Context.log.contains("stopService"),"stop must not bring down a record before startForeground");
    UnifiedMP4Service s=deliver();
    need(Context.log.indexOf("startForeground")>=0&&Context.log.indexOf("startForeground")<Context.log.indexOf("stopSelf"),"promote, then stop");
    need(!Context.crashed&&UnifiedMP4Background.started==0,"no crash and no transport start for a cancelled start");s.onDestroy();
    // An unwanted start (owner already released) is promoted before it stops.
    reset();UnifiedMP4Service.start(host);UnifiedMP4Background.expects=false;s=deliver();
    need(!Context.crashed&&Context.log.indexOf("startForeground")<Context.log.indexOf("stopSelf"),"unwanted start still promotes first");s.onDestroy();
    // Promotion never needs the dynamic status text.
    reset();UnifiedMP4Service.start(host);s=deliver();
    need(s.promoted&&UnifiedMP4Background.started==1&&!Context.log.contains("stopSelf"),"normal start promotes and reports ready");
    UnifiedMP4Service.stop(host);need(Context.log.contains("stopService")&&!Context.crashed,"a promoted service stops directly");s.onDestroy();
    // A start that never reaches onStartCommand does not pin stop() forever.
    reset();UnifiedMP4Service.start(host);SystemClock.now+=10_001;Context.pendingStarts=0;UnifiedMP4Service.stop(host);
    need(Context.log.contains("stopService"),"after the grace window stop() is applied directly");
    // A promotion failure has nothing to keep alive.
    reset();UnifiedMP4Service.start(host);android.app.Service.failPromotion=true;s=deliver();
    need(Context.log.contains("stopSelf")&&UnifiedMP4Background.started==0,"failed promotion stops the job");
    System.out.println("PASS service promotion ordering");
  }
}''',
}


def test_foreground_service_is_promoted_before_any_stop(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source_root = tmp_path / "src"
    for name, text in STUBS.items():
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    service = source_root / PACKAGE / "UnifiedMP4Service.java"
    service.write_text(SERVICE.read_text())
    classes = tmp_path / "classes"
    sources = [str(path) for path in source_root.rglob("*.java")]
    compiled = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-encoding", "UTF-8", "-d", str(classes), *sources],
                              capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "game.qualiarts.idolypride.localserver.PromotionFixture"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "PASS service promotion ordering"
