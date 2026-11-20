from __future__ import annotations

import copy
import io
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import struct
from pathlib import Path
import shutil
import subprocess

import pytest

from tools import package_android_unified as unified


A = unified.ANDROID


def manifest():
    return f'''<manifest xmlns:android="{A[1:-1]}" package="{unified.PACKAGE}"
        android:versionCode="414" android:versionName="6.1.1">
        <uses-sdk android:minSdkVersion="28" android:targetSdkVersion="36"/>
        <application android:icon="@mipmap/app_icon" android:networkSecurityConfig="@xml/network_security_config"
            android:appComponentFactory="androidx.core.app.CoreComponentFactory" android:resizeableActivity="false">
          <meta-data android:name="android.max_aspect" android:value="2.33334"/>
          <activity android:name="{unified.ORIGINAL_ACTIVITY}" android:theme="@style/UnityThemeSelector"
              android:exported="true" android:launchMode="singleTask" android:screenOrientation="fullUser"
              android:configChanges="orientation|screenSize" android:maxAspectRatio="2.33334" android:resizeableActivity="false">
            <intent-filter><action android:name="android.intent.action.MAIN"/>
              <category android:name="android.intent.category.LAUNCHER"/></intent-filter>
            <intent-filter><action android:name="android.intent.action.VIEW"/>
              <category android:name="android.intent.category.BROWSABLE"/>
              <data android:scheme="{unified.PACKAGE}" android:host="stat.game-idolypride.jp" android:pathPrefix="/app"/>
            </intent-filter><meta-data android:name="unityplayer.UnityActivity" android:value="true"/>
          </activity>
          <provider android:name="sdk.SomeProvider" android:authorities="{unified.PACKAGE}.sdk" android:exported="false"/>
          <meta-data android:name="custom_notification_android_activity" android:value="{unified.ORIGINAL_ACTIVITY}"/>
        </application></manifest>'''.encode()


def test_only_server_is_launcher_and_unity_alias_keeps_deep_links():
    before = ET.fromstring(manifest())
    after = ET.fromstring(unified.transform_manifest(manifest()))
    app = after.find("application")
    assert after.find("uses-sdk").attrib == {A + "minSdkVersion": "30", A + "targetSdkVersion": "36"}
    assert app.get(A + "networkSecurityConfig") == before.find("application").get(A + "networkSecurityConfig")
    providers = app.findall("provider")
    assert [n.attrib for n in providers] == [n.attrib for n in before.find("application").findall("provider")]
    activities = {n.get(A + "name"): n for n in app.findall("activity")}
    game = activities[unified.GAME_ACTIVITY]
    original = before.find("application/activity")
    for name, value in original.attrib.items():
        if name not in (A + "name", A + "exported", A + "resizeableActivity", A + "configChanges", A + "maxAspectRatio"):
            assert game.get(name) == value
    assert game.get(A + "resizeableActivity") == app.get(A + "resizeableActivity") == "true"
    assert not game.get(A + "maxAspectRatio")
    assert set(original.get(A + "configChanges").split("|")) <= set(game.get(A + "configChanges").split("|"))
    assert set(unified.WINDOW_CONFIG_CHANGES) <= set(game.get(A + "configChanges").split("|"))
    assert not any(n.get(A + "name") == "android.max_aspect" for n in app.findall("meta-data"))
    assert game.find("meta-data").attrib == original.find("meta-data").attrib
    assert not game.findall("intent-filter")
    alias = app.find("activity-alias")
    assert list(app).index(activities[unified.MENU_ACTIVITY]) < list(app).index(alias)
    assert alias.get(A + "name") == unified.ORIGINAL_ACTIVITY
    assert alias.get(A + "targetActivity") == unified.MENU_ACTIVITY
    assert alias.find("intent-filter/data").attrib == original.findall("intent-filter")[1].find("data").attrib
    launchers = [n.get(A + "name") for n in app for f in n.findall("intent-filter")
                 if any(c.get(A + "name") == "android.intent.category.LAUNCHER" for c in f.findall("category"))]
    assert launchers == [unified.MENU_ACTIVITY]
    assert app.get(A + "extractNativeLibs") == "true"
    assert app.get(A + "appComponentFactory") == unified.COMPONENT_FACTORY
    assert not app.get(A + "name")


def test_fold_resize_preserves_all_unity_handlers_and_unrelated_sdk_policy():
    before = ET.fromstring(manifest())
    app = before.find("application")
    original = app.find("activity")
    original_changes = ("mcc|mnc|locale|touchscreen|keyboard|keyboardHidden|navigation|orientation|"
                        "screenLayout|uiMode|screenSize|smallestScreenSize|density|layoutDirection|fontScale|colorMode")
    original.set(A + "configChanges", original_changes)
    original.set(A + "minAspectRatio", "1.4")
    app.set(A + "maxAspectRatio", "2.33334")
    sdk = ET.SubElement(app, "activity", {A + "name": "sdk.ExternalActivity", A + "resizeableActivity": "false",
                                        A + "configChanges": "orientation|screenSize", A + "screenOrientation": "portrait"})
    after = ET.fromstring(unified.transform_manifest(ET.tostring(before))).find("application")
    game = next(n for n in after.findall("activity") if n.get(A + "name") == unified.GAME_ACTIVITY)
    menu = next(n for n in after.findall("activity") if n.get(A + "name") == unified.MENU_ACTIVITY)
    assert game.get(A + "configChanges") == original_changes
    assert game.get(A + "screenOrientation") == "fullUser"
    assert not game.get(A + "minAspectRatio") and not after.get(A + "maxAspectRatio")
    assert menu.get(A + "resizeableActivity") == "true"
    # Native menu recreation recalculates its columns and restores state; the
    # original Unity instance receives its configuration through its superclass.
    assert menu.get(A + "configChanges") is None
    assert next(n for n in after.findall("activity") if n.get(A + "name") == "sdk.ExternalActivity").attrib == sdk.attrib


@pytest.mark.parametrize("mutation", [
    lambda t: t.set("package", "official.package"),
    lambda t: t.set(A + "versionCode", "415"),
    lambda t: t.find("uses-sdk").set(A + "minSdkVersion", "29"),
    lambda t: t.find("application").set(A + "name", "sdk.SomeApplication"),
    lambda t: t.find("application").set(A + "appComponentFactory", "sdk.OtherFactory"),
    lambda t: t.find("application/provider").set(A + "process", ":other"),
    lambda t: t.find("application").append(copy.deepcopy(t.find("application/activity"))),
])
def test_manifest_source_drift_rejected(mutation):
    tree = ET.fromstring(manifest())
    mutation(tree)
    with pytest.raises(ValueError):
        unified.transform_manifest(ET.tostring(tree))


@pytest.mark.parametrize("names", [
    ["../escape"], ["/absolute"], ["a\\b"], ["a/./b"], ["a", "A"], ["a", "a"],
])
@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_unsafe_inventory_rejected(names):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    with ZipFile(buffer) as archive, pytest.raises(ValueError):
        unified.inventory(archive)


def test_inventory_rejects_symlink():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        info = ZipInfo("assets/file")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target")
    with ZipFile(buffer) as archive, pytest.raises(ValueError):
        unified.inventory(archive)


def test_merge_rejects_namespace_collision_and_missing_marker():
    additions = {unified.MARKER, unified.RESOURCES_ASSET, "classes7.dex"}
    unified.validate_merge({"classes.dex", "resources.arsc"}, {"assets/chaquopy/app.imy"}, additions)
    for host, extra in [({"resources.arsc"}, additions), ({"classes7.dex"}, additions),
                        ({"assets/a"}, additions - {unified.MARKER})]:
        with pytest.raises(ValueError):
            unified.validate_merge({"classes.dex", "resources.arsc"}, host, extra)


def test_only_signature_material_is_removed():
    assert unified.signature_member("META-INF/CERT.RSA")
    assert unified.signature_member("META-INF/MANIFEST.MF")
    assert not unified.signature_member("META-INF/licenses/NOTICE")
    assert not unified.signature_member("META-INF/services/a.Service")


def test_dex_indexing_and_malformed_dex():
    assert unified.next_dex_name(["classes.dex", "classes2.dex", "res/a"]) == "classes3.dex"
    for names in [[], ["classes2.dex"], ["classes.dex", "classes3.dex"]]:
        with pytest.raises(ValueError):
            unified.next_dex_name(names)
    for raw in (b"", b"dex\n038\0" + bytes(200), bytes(32 * unified.MIB + 1)):
        with pytest.raises(ValueError):
            unified.dex_classes(raw)


def test_build_config_includes_all_integrity_fields():
    text = unified.build_config(unified.SERVER_ASSETS).decode()
    assert f'APPLICATION_ID = "{unified.PACKAGE}"' in text
    for name in ("SERVER_DATA", "BUNDLED_TRANSLATIONS", "STARTUP_TRANSLATIONS"):
        assert name + "_SHA256" in text
        assert name + "_BYTES" in text


def test_raw_writer_preserves_original_compressed_spans(tmp_path):
    original, merged = tmp_path / "input.zip", tmp_path / "output.zip"
    content = b"Unity data with deliberately nondefault deflate parameters\n" * 4096
    with ZipFile(original, "x", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr("assets/bin/Data/level0", content)
    with ZipFile(original) as archive, unified.RawZipWriter(merged) as writer:
        info = archive.getinfo("assets/bin/Data/level0")
        archive.fp.seek(info.header_offset + 26)
        nlen, extra = struct.unpack("<HH", archive.fp.read(4))
        archive.fp.seek(info.header_offset + 30 + nlen + extra)
        encoded_before = archive.fp.read(info.compress_size)
        writer.bytes("prefix", b"new member changes the offsets")
        writer.raw(archive, info)
    with ZipFile(merged) as archive:
        assert archive.read(info.filename) == content
        after = archive.getinfo(info.filename)
        archive.fp.seek(after.header_offset + 26)
        nlen, extra = struct.unpack("<HH", archive.fp.read(4))
        archive.fp.seek(after.header_offset + 30 + nlen + extra)
        assert archive.fp.read(after.compress_size) == encoded_before


def test_raw_writer_aligns_native_members_to_16k(tmp_path):
    target = tmp_path / "native.apk"
    with unified.RawZipWriter(target) as writer:
        writer.bytes("prefix", b"moves the native entry")
        writer.bytes("lib/arm64-v8a/libtest.so", b"ELF fixture")
    with ZipFile(target) as archive:
        info = archive.getinfo("lib/arm64-v8a/libtest.so")
        archive.fp.seek(info.header_offset + 26)
        name, extra = struct.unpack("<HH", archive.fp.read(4))
        assert (info.header_offset + 30 + name + extra) % 16384 == 0
        assert archive.read(info.filename) == b"ELF fixture"


def test_component_factory_cold_restore_uses_plain_activity_and_calls_base_super(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required for actual component-factory fixture")
    sources = {
        "android/os/Bundle.java": "package android.os; public class Bundle {}",
        "android/app/Activity.java": '''package android.app; public class Activity {
          public int supers, finishes; public android.content.Intent incoming, started;
          public android.os.Bundle restored;
          protected void onCreate(android.os.Bundle b) { supers++; restored=b; }
          public android.content.Intent getIntent() { return incoming; }
          public void startActivity(android.content.Intent i) { started=i; }
          public void finish() { finishes++; }
        }''',
        "android/content/Intent.java": '''package android.content; public class Intent {
          public static final String ACTION_MAIN="main";
          public static final int FLAG_ACTIVITY_CLEAR_TOP=1, FLAG_ACTIVITY_SINGLE_TOP=2;
          public String action, language, payload; public Class<?> target; public int flags;
          public Intent(String a) { action=a; }
          public Intent setClass(android.app.Activity a,Class<?> c) { target=c;return this; }
          public Intent addFlags(int f) { flags|=f;return this; }
          public void removeExtra(String name) { language=null; }
        }''',
        "androidx/core/app/CoreComponentFactory.java": '''package androidx.core.app;
          public class CoreComponentFactory { public int calls;
            public android.app.Activity instantiateActivity(ClassLoader l,String n,android.content.Intent i)
              throws InstantiationException,IllegalAccessException,ClassNotFoundException {
                calls++; return (android.app.Activity)l.loadClass(n).newInstance();
            }
          }''',
    }
    package = "game/qualiarts/idolypride/localserver/"
    sources[package + "UnifiedRuntime.java"] = '''package game.qualiarts.idolypride.localserver;
      import android.content.Intent; final class UnifiedRuntime {
        static final String GAME="game.qualiarts.idolypride.localserver.FakeGameActivity",EXPECTED_LANGUAGE="language";
        static String expectedLanguage(Intent i) { return i==null?null:i.language; }
        static void copyLaunchPayload(Intent to,Intent from) { to.action=from.action;to.payload=from.payload; }
      }'''
    sources[package + "UnifiedGameAssets.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedGameAssets { static ReadySnapshot ready;
        static final class ReadySnapshot { final String language; ReadySnapshot(String l) {language=l;} }
        static ReadySnapshot readySnapshot() { return ready; }
      }'''
    sources[package + "ServerService.java"] = '''package game.qualiarts.idolypride.localserver;
      final class ServerService { static boolean running; static boolean resourceServerRunning(){return running;} }'''
    sources[package + "MainActivity.java"] = '''package game.qualiarts.idolypride.localserver;
      public class MainActivity extends android.app.Activity {}'''
    sources[package + "FakeGameActivity.java"] = '''package game.qualiarts.idolypride.localserver;
      public class FakeGameActivity extends android.app.Activity { static int constructed;
        public FakeGameActivity(){constructed++;} }'''
    sources[package + "FactoryFixture.java"] = '''package game.qualiarts.idolypride.localserver;
      import android.app.Activity; import android.content.Intent;
      public class FactoryFixture {
        static void need(boolean b) { if(!b)throw new AssertionError(); }
        public static void main(String[] args) throws Exception {
          UnifiedComponentFactory factory=new UnifiedComponentFactory();
          Intent incoming=new Intent("view");incoming.language="ko";incoming.payload="notification";
          ClassLoader loader=FactoryFixture.class.getClassLoader();
          Activity cold=factory.instantiateActivity(loader,UnifiedRuntime.GAME,incoming);
          need(cold instanceof UnifiedGameRecoveryActivity && FakeGameActivity.constructed==0);
          cold.incoming=incoming;((UnifiedGameRecoveryActivity)cold).onCreate(new android.os.Bundle());
          need(cold.supers==1 && cold.restored==null && cold.finishes==1 && cold.started.target==MainActivity.class);
          need("view".equals(cold.started.action) && "notification".equals(cold.started.payload));
          need(cold.started.language==null && cold.started.flags==3);
          UnifiedGameAssets.ready=new UnifiedGameAssets.ReadySnapshot("ko");
          need(factory.instantiateActivity(loader,UnifiedRuntime.GAME,incoming) instanceof UnifiedGameRecoveryActivity);
          ServerService.running=true;incoming.language="ja";
          need(factory.instantiateActivity(loader,UnifiedRuntime.GAME,incoming) instanceof UnifiedGameRecoveryActivity);
          incoming.language="ko";
          need(factory.instantiateActivity(loader,UnifiedRuntime.GAME,incoming) instanceof FakeGameActivity);
          need(FakeGameActivity.constructed==1);
          need(factory.instantiateActivity(loader,MainActivity.class.getName(),incoming) instanceof MainActivity);
          need(factory.calls==5);
        }
      }'''
    repo = Path(__file__).resolve().parents[1]
    for name in ("UnifiedComponentFactory", "UnifiedGameRecoveryActivity"):
        sources[package + name + ".java"] = (repo / unified.UNIFIED_JAVA_ROOT / package / (name + ".java")).read_text()
    paths = []
    for name, raw in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        paths.append(path)
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-d", str(classes), *map(str, paths)],
                   capture_output=True, check=True, timeout=30)
    subprocess.run([java, "-Xmx128m", "-cp", str(classes), unified.SERVER_PACKAGE + ".FactoryFixture"],
                   capture_output=True, check=True, timeout=30)


def test_game_menu_hold_policy_and_original_touch_dispatch(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required for actual gesture fixture")
    sources = {
        "android/content/res/Configuration.java": "package android.content.res; public class Configuration {}",
        "android/view/Display.java": "package android.view; public class Display {public static final int INVALID_DISPLAY=-1;public int getDisplayId(){return 0;}}",
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
        "android/content/res/Resources.java": '''package android.content.res; public class Resources {
          public android.util.DisplayMetrics getDisplayMetrics(){return new android.util.DisplayMetrics();} }''',
        "android/content/Context.java": "package android.content; public class Context {}",
        "android/content/Intent.java": '''package android.content; public class Intent {
          public static final int FLAG_ACTIVITY_CLEAR_TOP=1,FLAG_ACTIVITY_SINGLE_TOP=2,FLAG_ACTIVITY_REORDER_TO_FRONT=4;
          public int flags;public Class<?> target;public Intent(Context c,Class<?> t){target=t;}
          public Intent addFlags(int f){flags|=f;return this;} }''',
        "android/view/View.java": '''package android.view; public class View {
          public interface OnLayoutChangeListener { void onLayoutChange(View v,int l,int t,int r,int b,int ol,int ot,int or,int ob); }
          public void addOnLayoutChangeListener(OnLayoutChangeListener l){}public void removeOnLayoutChangeListener(OnLayoutChangeListener l){}
          public Display getDisplay(){return new Display();}
          public int getWidth(){return 1000;}public int getHeight(){return 800;} }''',
        "android/view/Window.java": "package android.view; public class Window { public View getDecorView(){return new View();} }",
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
        "android/app/Activity.java": '''package android.app; public class Activity extends android.content.Context {
          public int dispatches,lastAction,pauses,destroys,starts;public android.content.Intent started;
          protected void onCreate(android.os.Bundle b){}protected void onPause(){pauses++;}protected void onDestroy(){destroys++;}
          protected void onResume(){}public boolean isInMultiWindowMode(){return false;}
          public void onConfigurationChanged(android.content.res.Configuration c){}
          public void onMultiWindowModeChanged(boolean m,android.content.res.Configuration c){}
          public void onWindowFocusChanged(boolean focused){}
          public boolean dispatchTouchEvent(android.view.MotionEvent e){dispatches++;lastAction=e.getActionMasked();return false;}
          public String getPackageCodePath(){return "installed.apk";}public android.content.Intent getIntent(){return null;}
          public android.view.Window getWindow(){return new android.view.Window();}
          public android.content.res.Resources getResources(){return new android.content.res.Resources();}
          public boolean isFinishing(){return false;}public boolean isDestroyed(){return false;}
          public void startActivity(android.content.Intent i){started=i;starts++;}
        }''',
        "com/google/firebase/MessagingUnityPlayerActivity.java": '''package com.google.firebase;
          public class MessagingUnityPlayerActivity extends android.app.Activity {}''',
    }
    package = "game/qualiarts/idolypride/localserver/"
    sources[package + "UnifiedRuntime.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedRuntime {static boolean isEnabled(android.content.Context c){return true;}
        static void installResources(android.content.Context c){}static String expectedLanguage(android.content.Intent i){return "ko";} }'''
    sources[package + "UnifiedGameAssets.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedGameAssets {static String freeze(android.content.Context c,String l)throws java.io.IOException{return "data.zip";} }'''
    sources[package + "UnifiedWindowing.java"] = '''package game.qualiarts.idolypride.localserver;
      final class UnifiedWindowing {static void update(boolean mode){} }'''
    sources[package + "MainActivity.java"] = "package game.qualiarts.idolypride.localserver; public class MainActivity extends android.app.Activity {}"
    sources[package + "GestureFixture.java"] = '''package game.qualiarts.idolypride.localserver;
      import android.os.Handler;import android.os.SystemClock;import android.view.MotionEvent;import android.content.Intent;
      public class GestureFixture {
        static void need(boolean b){if(!b)throw new AssertionError();}
        static MotionEvent event(int a,int n,float x,float y){return new MotionEvent(a,n,x,y,SystemClock.now);}
        public static void main(String[] args){
          UnifiedMenuGesture p=new UnifiedMenuGesture();
          p.down(1,700,10,1000,800,1,8,0);need(!p.pending());
          p.down(1,750,200,1000,800,1,8,100);need(p.pending());
          need(!p.claim(2099)&&p.remaining(2099)==1&&p.claim(2100)&&p.claimed());
          p.down(1,241,119,400,400,1,8,0);need(p.pending());
          p.move(1,249,119);need(p.pending());p.move(1,250,119);need(!p.pending());
          p.down(2,399,0,400,400,1,8,0);need(!p.pending());
          p.down(1,399,0,400,400,1,8,0);p.move(2,399,0);need(!p.pending());
          UnifiedGameActivity activity=new UnifiedGameActivity();
          need(!activity.dispatchTouchEvent(event(0,1,900,50))&&activity.dispatches==1);
          Handler.advance(1999);need(activity.starts==0);Handler.advance(2000);
          need(activity.dispatches==2&&activity.lastAction==MotionEvent.ACTION_CANCEL&&activity.starts==1);
          need(activity.started.target==MainActivity.class&&activity.started.flags==(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT|Intent.FLAG_ACTIVITY_SINGLE_TOP));
          need(activity.dispatchTouchEvent(event(1,1,900,50))&&activity.dispatches==2);
          SystemClock.now=3000;activity.dispatchTouchEvent(event(0,1,900,50));
          SystemClock.now=3500;activity.dispatchTouchEvent(event(2,1,920,50));Handler.advance(6000);need(activity.starts==1);
          activity.dispatchTouchEvent(event(0,1,900,50));activity.onPause();Handler.advance(9000);need(activity.starts==1&&activity.pauses==1);
          activity.dispatchTouchEvent(event(0,1,900,50));activity.onDestroy();Handler.advance(12000);need(activity.starts==1&&activity.destroys==1);
          need(MotionEvent.obtained==MotionEvent.recycled);
        }
      }'''
    repo = Path(__file__).resolve().parents[1]
    for name in ("UnifiedGameActivity", "UnifiedMenuGesture"):
        sources[package + name + ".java"] = (repo / unified.UNIFIED_JAVA_ROOT / package / (name + ".java")).read_text()
    paths = []
    for name, raw in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        paths.append(path)
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-d", str(classes), *map(str, paths)],
                   capture_output=True, check=True, timeout=30)
    subprocess.run([java, "-Xmx128m", "-cp", str(classes), unified.SERVER_PACKAGE + ".GestureFixture"],
                   capture_output=True, check=True, timeout=30)
