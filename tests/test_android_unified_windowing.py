"""Run the actual wrapper through resize/display/lifecycle events using bounded JVM stubs."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_window_changes_keep_game_and_cancel_old_touch_without_restart(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required for Android wrapper lifecycle fixture")
    sources = {
        "android/os/Bundle.java": "package android.os; public class Bundle {}",
        "android/os/Looper.java": "package android.os; public class Looper { public static Looper getMainLooper(){return null;} }",
        "android/os/SystemClock.java": "package android.os; public class SystemClock { public static long now; public static long uptimeMillis(){return now;} }",
        "android/os/Handler.java": '''package android.os; import java.util.*;
          public class Handler { public Handler(Looper l){} static class Job {Runnable r;long at;Job(Runnable r,long t){this.r=r;at=t;}}
            static final List<Job> jobs=new ArrayList<>();
            public void removeCallbacks(Runnable r){jobs.removeIf(j->j.r==r);}
            public void postDelayed(Runnable r,long delay){jobs.add(new Job(r,SystemClock.now+delay));}
            public static void advance(long now){SystemClock.now=now;
              for(;;){Job due=null;for(Job j:jobs)if(j.at<=now){due=j;break;}if(due==null)return;
                jobs.remove(due);due.r.run();}}
          }''',
        "android/util/DisplayMetrics.java": "package android.util; public class DisplayMetrics { public float density=1; }",
        "android/content/res/Configuration.java": "package android.content.res; public class Configuration {}",
        "android/content/res/Resources.java": '''package android.content.res; public class Resources {
          public final android.util.DisplayMetrics metrics=new android.util.DisplayMetrics();
          public android.util.DisplayMetrics getDisplayMetrics(){return metrics;} }''',
        "android/content/Context.java": "package android.content; public class Context {}",
        "android/view/Display.java": '''package android.view; public class Display {
          public static final int INVALID_DISPLAY=-1;public int id;public int getDisplayId(){return id;} }''',
        "android/content/Intent.java": '''package android.content; public class Intent {
          public static final int FLAG_ACTIVITY_CLEAR_TOP=1,FLAG_ACTIVITY_SINGLE_TOP=2,FLAG_ACTIVITY_REORDER_TO_FRONT=4;
          public int flags;public Class<?> target;public Intent(Context c,Class<?> t){target=t;}
          public Intent addFlags(int f){flags|=f;return this;} }''',
        "android/view/View.java": '''package android.view; import java.util.*;public class View {
          public interface OnLayoutChangeListener {void onLayoutChange(View v,int l,int t,int r,int b,int ol,int ot,int or,int ob);}
          final List<OnLayoutChangeListener> listeners=new ArrayList<>();int left,top,right=1000,bottom=800;
          public final Display display=new Display();public Display getDisplay(){return display;}
          public int getWidth(){return right-left;}public int getHeight(){return bottom-top;}
          public void addOnLayoutChangeListener(OnLayoutChangeListener l){listeners.add(l);}
          public void removeOnLayoutChangeListener(OnLayoutChangeListener l){listeners.remove(l);}
          public int listenerCount(){return listeners.size();}
          public void layout(int l,int t,int r,int b){int ol=left,ot=top,or=right,ob=bottom;left=l;top=t;right=r;bottom=b;
            for(OnLayoutChangeListener listener:new ArrayList<>(listeners))listener.onLayoutChange(this,l,t,r,b,ol,ot,or,ob);}
        }''',
        "android/view/Window.java": '''package android.view; public class Window {
          public final View decor=new View();public View getDecorView(){return decor;} }''',
        "android/view/ViewConfiguration.java": '''package android.view; public class ViewConfiguration {
          public static ViewConfiguration get(android.content.Context c){return new ViewConfiguration();}
          public int getScaledTouchSlop(){return 8;} }''',
        "android/view/MotionEvent.java": '''package android.view; public class MotionEvent {
          public static final int ACTION_DOWN=0,ACTION_UP=1,ACTION_MOVE=2,ACTION_CANCEL=3,ACTION_OUTSIDE=4,ACTION_POINTER_DOWN=5,ACTION_POINTER_UP=6;
          public static int obtained,recycled;int action,pointers;float x,y;long time;boolean dead;
          public MotionEvent(int a,int n,float x,float y,long t){action=a;pointers=n;this.x=x;this.y=y;time=t;}
          public int getActionMasked(){return action;}public int getPointerCount(){return pointers;}
          public float getX(){return x;}public float getY(){return y;}public long getEventTime(){return time;}
          public void setAction(int a){action=a;}public static MotionEvent obtain(MotionEvent e){obtained++;return new MotionEvent(e.action,e.pointers,e.x,e.y,e.time);}
          public void recycle(){if(dead)throw new AssertionError("double recycle");dead=true;recycled++;}
        }''',
        "android/app/Activity.java": '''package android.app; import android.content.res.Configuration;
          public class Activity extends android.content.Context {
            public final android.view.Window window=new android.view.Window();
            public final android.content.res.Resources resources=new android.content.res.Resources();
            public int creates,pauses,resumes,destroys,starts,dispatches,cancels,configs,multiWindows,focusEvents;
            public boolean lastFocus,multiWindow;public Configuration lastConfig,lastMultiConfig;
            public android.content.Intent started;
            protected void onCreate(android.os.Bundle b){creates++;}protected void onPause(){pauses++;}protected void onDestroy(){destroys++;}
            protected void onResume(){resumes++;}public boolean isInMultiWindowMode(){return multiWindow;}
            public boolean dispatchTouchEvent(android.view.MotionEvent e){dispatches++;if(e.getActionMasked()==3)cancels++;return false;}
            public void onConfigurationChanged(Configuration c){configs++;lastConfig=c;}
            public void onMultiWindowModeChanged(boolean m,Configuration c){multiWindows++;lastMultiConfig=c;multiWindow=m;}
            public void onWindowFocusChanged(boolean f){focusEvents++;lastFocus=f;}
            public String getPackageCodePath(){return "installed.apk";}public android.content.Intent getIntent(){return null;}
            public android.view.Window getWindow(){return window;}public android.content.res.Resources getResources(){return resources;}
            public boolean isFinishing(){return false;}public boolean isDestroyed(){return false;}
            public void startActivity(android.content.Intent i){started=i;starts++;}
          }''',
        "com/google/firebase/MessagingUnityPlayerActivity.java": '''package com.google.firebase;
          public class MessagingUnityPlayerActivity extends android.app.Activity {}''',
    }
    package = "game/qualiarts/idolypride/localserver/"
    sources[package + "UnifiedRuntime.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedRuntime {static int installs;static boolean isEnabled(android.content.Context c){return true;}
        static void installResources(android.content.Context c){installs++;}static String expectedLanguage(android.content.Intent i){return "ko";} }'''
    sources[package + "UnifiedGameAssets.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedGameAssets {static int freezes;static String freeze(android.content.Context c,String l)throws java.io.IOException{freezes++;return "selected-data.zip";} }'''
    sources[package + "MainActivity.java"] = "package game.qualiarts.idolypride.localserver; public class MainActivity extends android.app.Activity {}"
    sources[package + "UnifiedWindowing.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedWindowing {static int calls;static boolean mode;static void update(boolean m){calls++;mode=m;} }'''
    sources[package + "WindowFixture.java"] = '''package game.qualiarts.idolypride.localserver;
      import android.os.Handler;import android.os.SystemClock;import android.view.MotionEvent;
      import android.view.View;import android.content.res.Configuration;
      public class WindowFixture {
        static void need(boolean b,String message){if(!b)throw new AssertionError(message);}
        static MotionEvent event(int action,float x,float y){return new MotionEvent(action,1,x,y,SystemClock.now);}
        static void down(UnifiedGameActivity a,float x,float y){a.dispatchTouchEvent(event(0,x,y));}
        static void up(UnifiedGameActivity a,float x,float y){a.dispatchTouchEvent(event(1,x,y));}
        static void alive(UnifiedGameActivity a){need(a.creates==1&&a.destroys==0,"game recreated");
          need(UnifiedGameAssets.freezes==1&&UnifiedRuntime.installs==1,"startup repeated");
          need("selected-data.zip".equals(a.getPackageCodePath()),"Data path changed");}
        public static void main(String[] args){
          UnifiedGameActivity a=new UnifiedGameActivity();a.onCreate(null);View decor=a.getWindow().getDecorView();
          need(UnifiedWindowing.calls==1&&!UnifiedWindowing.mode,"initial window mode missing");
          need(decor.listenerCount()==1,"missing listener");alive(a);
          down(a,900,50);decor.layout(0,0,400,800);need(a.cancels==1,"old touch not cancelled once");
          int dispatched=a.dispatches;Handler.advance(2000);need(a.starts==0,"resize fired stale hold");
          up(a,900,50);need(a.dispatches==dispatched,"old resized stream leaked");
          down(a,150,30);Handler.advance(4000);need(a.starts==0,"old window region reused");up(a,150,30);
          down(a,350,30);Handler.advance(6000);need(a.starts==1,"new narrow corner unavailable");up(a,350,30);
          a.resources.metrics.density=2;Configuration density=new Configuration();a.onConfigurationChanged(density);
          need(a.configs==1&&a.lastConfig==density,"parent configuration lost");
          down(a,150,30);Handler.advance(8000);need(a.starts==2,"new density not applied");up(a,150,30);alive(a);
          decor.layout(0,0,800,400);down(a,700,40);int before=a.cancels;
          Configuration multi=new Configuration(),config=new Configuration();
          a.onMultiWindowModeChanged(true,multi);a.onConfigurationChanged(config);
          need(UnifiedWindowing.mode,"multiwindow mode not propagated");
          decor.layout(0,0,700,500);need(a.cancels==before+1,"duplicate touch cancel");
          Handler.advance(10000);need(a.starts==2,"window transition fired hold");up(a,700,40);
          need(a.configs==2&&a.lastConfig==config,"configuration forwarded twice");
          need(a.multiWindows==1&&a.lastMultiConfig==multi,"multiwindow callback lost");
          need(a.pauses==0&&a.resumes==0&&a.destroys==0,"resize invoked manual lifecycle");alive(a);
          down(a,650,40);before=a.cancels;decor.display.id=2;Handler.advance(12000);
          need(a.starts==2&&a.cancels==before+1,"same-size display move fired hold");up(a,650,40);alive(a);
          down(a,650,40);before=a.cancels;decor.layout(10,20,710,520);Handler.advance(14000);
          need(a.starts==2&&a.cancels==before+1,"same-size position move fired hold");up(a,650,40);
          down(a,650,40);a.onWindowFocusChanged(false);a.onWindowFocusChanged(true);Handler.advance(16000);
          need(a.starts==2&&a.focusEvents==2&&a.lastFocus,"focus lifecycle changed");up(a,650,40);
          down(a,650,40);a.onPause();Handler.advance(18000);need(a.pauses==1&&a.starts==2,"pause timer leaked");
          need(UnifiedWindowing.mode,"pause cleared live multiwindow mode");
          a.multiWindow=false;a.onResume();need(a.resumes==1&&!UnifiedWindowing.mode,"resume did not refresh current OS mode");
          down(a,650,40);a.onDestroy();need(decor.listenerCount()==0&&a.destroys==1,"listener leaked");
          int after=a.cancels;decor.layout(0,0,1000,800);Handler.advance(20000);
          need(a.cancels==after&&a.starts==2,"destroyed window callback active");
          need(MotionEvent.obtained==MotionEvent.recycled,"event copy leaked");
          UnifiedGameActivity old=new UnifiedGameActivity();old.onCreate(null);
          UnifiedGameActivity current=new UnifiedGameActivity();current.multiWindow=true;current.onCreate(null);
          need(UnifiedWindowing.mode,"new game failed to own window mode");int calls=UnifiedWindowing.calls;
          old.onDestroy();need(UnifiedWindowing.calls==calls&&UnifiedWindowing.mode,"old destroy cleared current mode");
          current.onDestroy();need(UnifiedWindowing.calls==calls+1&&!UnifiedWindowing.mode,"current destroy did not clear mode");
        }
      }'''
    repo = Path(__file__).resolve().parents[1]
    source_root = repo / "android-unified/src/main/java" / package
    for name in ("UnifiedGameActivity", "UnifiedMenuGesture"):
        sources[package + name + ".java"] = (source_root / (name + ".java")).read_text()
    paths = []
    for name, raw in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        paths.append(str(path))
    classes = tmp_path / "classes"
    classes.mkdir()
    compile_result = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-d", str(classes), *paths],
                                    capture_output=True, text=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes),
                             "game.qualiarts.idolypride.localserver.WindowFixture"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
