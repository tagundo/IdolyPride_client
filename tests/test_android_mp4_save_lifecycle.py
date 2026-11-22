"""Execute the production Android save controller with a durable JNI queue fixture.

Only Android UI/JSON containers and the game/native producer are substituted.
The actual controller owns lifecycle, picker admission, output validation and copy.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.localserver"
JAVA = ROOT / "android-server/app/src/main/java" / PACKAGE.replace(".", "/")


def _write(directory, name, text):
    target = directory / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def _android_stubs():
    return {
        "android/content/SharedPreferences.java": r'''package android.content;
import java.util.*;
public interface SharedPreferences {
 String getString(String k,String d);Set<String> getStringSet(String k,Set<String> d);boolean getBoolean(String k,boolean d);long getLong(String k,long d);int getInt(String k,int d);
 boolean contains(String k);Map<String,?> getAll();Editor edit();
 interface Editor {Editor putString(String k,String v);Editor putStringSet(String k,Set<String> v);Editor putBoolean(String k,boolean v);Editor putLong(String k,long v);Editor putInt(String k,int v);Editor remove(String k);Editor clear();void apply();boolean commit();}
}''',
        "android/content/Context.java": r'''package android.content;
import java.io.*;import java.util.*;import android.content.res.Resources;
public class Context {
 public static final int MODE_PRIVATE=0;private final File files;private static final Map<String,Preferences> stores=new HashMap<>();
 public final ContentResolver resolver=new ContentResolver();public Context(File files){this.files=files;}
 public Context getApplicationContext(){return this;}public File getFilesDir(){return files;}
 public Resources getResources(){return new Resources();}
 public String getString(int key,Object...args){StringBuilder b=new StringBuilder("resource:").append(key);for(Object a:args)b.append(':').append(a);return b.toString();}
 public SharedPreferences getSharedPreferences(String name,int mode){return stores.computeIfAbsent(files.getAbsolutePath()+":"+name,k->new Preferences());}
 static final class Preferences implements SharedPreferences,SharedPreferences.Editor {
  final Map<String,Object> data=new HashMap<>();public String getString(String k,String d){Object v=data.get(k);return v instanceof String?(String)v:d;}
  public Set<String> getStringSet(String k,Set<String> d){Object v=data.get(k);if(!(v instanceof Set<?>))return d;Set<String> r=new HashSet<>();for(Object item:(Set<?>)v)r.add((String)item);return r;}
  public boolean getBoolean(String k,boolean d){Object v=data.get(k);return v instanceof Boolean?(Boolean)v:d;}
  public long getLong(String k,long d){Object v=data.get(k);return v instanceof Number?((Number)v).longValue():d;}
  public int getInt(String k,int d){return (int)getLong(k,d);}public boolean contains(String k){return data.containsKey(k);}
  public Map<String,?> getAll(){return new HashMap<>(data);}public Editor edit(){return this;}
  public Editor putString(String k,String v){data.put(k,v);return this;}public Editor putBoolean(String k,boolean v){data.put(k,v);return this;}
  public Editor putStringSet(String k,Set<String> v){data.put(k,new HashSet<>(v));return this;}
  public Editor putLong(String k,long v){data.put(k,v);return this;}public Editor putInt(String k,int v){data.put(k,v);return this;}
  public Editor remove(String k){data.remove(k);return this;}public Editor clear(){data.clear();return this;}public void apply(){}public boolean commit(){return true;}
 }
 public ContentResolver getContentResolver(){return resolver;}
}''',
        "android/content/ContentResolver.java": r'''package android.content;
import android.net.Uri;import java.io.*;import java.util.*;
public class ContentResolver {
 public static final Map<String,byte[]> outputs=new HashMap<>();public static boolean failWrites;
 public OutputStream openOutputStream(Uri uri,String mode)throws IOException {
  if(failWrites)throw new IOException("fixture provider failure");
  return new ByteArrayOutputStream(){public void close()throws IOException{super.close();outputs.put(uri.toString(),toByteArray());}};
 }
}''',
        "android/content/Intent.java": r'''package android.content;
import android.net.Uri;import java.util.*;
public class Intent {
 public static final String ACTION_CREATE_DOCUMENT="android.intent.action.CREATE_DOCUMENT",ACTION_OPEN_DOCUMENT="android.intent.action.OPEN_DOCUMENT",CATEGORY_OPENABLE="android.intent.category.OPENABLE",EXTRA_TITLE="android.intent.extra.TITLE";
 public static final int FLAG_ACTIVITY_REORDER_TO_FRONT=1,FLAG_ACTIVITY_SINGLE_TOP=2,FLAG_GRANT_WRITE_URI_PERMISSION=4;
 public String action,type;public int flags;public final Map<String,Object> extras=new HashMap<>();private Uri data;
 public Intent(String a){action=a;}public Intent(Context owner,Class<?> target){action=target.getName();}
 public Intent addCategory(String c){return this;}public Intent setType(String t){type=t;return this;}
 public Intent putExtra(String k,String v){extras.put(k,v);return this;}public Intent addFlags(int f){flags|=f;return this;}
 public Uri getData(){return data;}public Intent setData(Uri u){data=u;return this;}
 public String getAction(){return action;}public String getType(){return type;}
}''',
        "android/app/Activity.java": r'''package android.app;
import android.content.*;import android.view.*;import java.io.*;import java.util.*;
public class Activity extends Context {
 public static final int RESULT_OK=-1,RESULT_CANCELED=0;
 public boolean destroyed,finishing,multiWindow,throwPicker;public int pickerLaunches,activityLaunches,lastRequest;public Intent lastPicker;
 public Activity(File root){super(root);}public boolean isDestroyed(){return destroyed;}public boolean isFinishing(){return finishing;}
 public boolean isInMultiWindowMode(){return multiWindow;}public void addContentView(View view,ViewGroup.LayoutParams p){}
 public void startActivity(Intent i){activityLaunches++;}
 public void startActivityForResult(Intent i,int request){if(throwPicker)throw new IllegalStateException("no picker");pickerLaunches++;lastPicker=i;lastRequest=request;}
}''',
        "android/content/res/Resources.java": r'''package android.content.res;
public class Resources {public android.util.DisplayMetrics getDisplayMetrics(){return new android.util.DisplayMetrics();}}''',
        "android/util/DisplayMetrics.java": "package android.util;public class DisplayMetrics {public float density=1;}",
        "android/graphics/Color.java": "package android.graphics;public final class Color {public static final int WHITE=-1;}",
        "android/net/Uri.java": r'''package android.net;public final class Uri {private final String value;private Uri(String v){value=v;}public static Uri parse(String v){return new Uri(v);}public String toString(){return value;}}''',
        "android/os/Bundle.java": r'''package android.os;import java.util.*;public class Bundle {final Map<String,String> values=new HashMap<>();public void putString(String k,String v){values.put(k,v);}public String getString(String k){return values.get(k);}}''',
        "android/os/Looper.java": "package android.os;public class Looper {public static Looper getMainLooper(){return new Looper();}}",
        "android/os/SystemClock.java": "package android.os;public class SystemClock {public static long uptimeMillis(){return 10000;}}",
        "android/os/Handler.java": r'''package android.os;import java.util.concurrent.ConcurrentLinkedQueue;
public class Handler {
 static final ConcurrentLinkedQueue<Runnable> posted=new ConcurrentLinkedQueue<>();public Handler(Looper l){}
 public boolean post(Runnable r){posted.add(r);return true;}public boolean postDelayed(Runnable r,long ms){return true;}
 public void removeCallbacks(Runnable r){posted.removeIf(v->v==r);}
 public static void drain(){for(int steps=0;;steps++){Runnable next=posted.poll();if(next==null)return;if(steps>100)throw new AssertionError("unbounded immediate UI loop");next.run();}}
 public static void clear(){posted.clear();}
}''',
        "android/view/Gravity.java": "package android.view;public class Gravity {public static final int CENTER_VERTICAL=16,BOTTOM=80;}",
        "android/view/View.java": r'''package android.view;import android.content.Context;
public class View {
 public static final int VISIBLE=0,INVISIBLE=4,GONE=8;public int visibility=VISIBLE,cancelledPendingInput;public boolean enabled=true,pressed;public Object tag;public ViewGroup parent;public final Context context;
 public interface OnClickListener {void onClick(View v);}public OnClickListener click;
 public View(Context c){context=c;}public void setVisibility(int v){visibility=v;}public int getVisibility(){return visibility;}
 public void setEnabled(boolean v){enabled=v;}public boolean isEnabled(){return enabled;}
 public void setOnClickListener(OnClickListener l){click=l;}public boolean performClick(){if(!enabled||visibility!=VISIBLE)return false;if(click!=null)click.onClick(this);return true;}
 public Object getParent(){return parent;}public void setPadding(int a,int b,int c,int d){}public void setBackgroundColor(int c){}
 public Context getContext(){return context;}public void setContentDescription(CharSequence value){}
 public void cancelPendingInputEvents(){cancelledPendingInput++;}public void setPressed(boolean value){pressed=value;}
 public void setTag(Object value){tag=value;}public Object getTag(){return tag;}
}''',
        "android/view/ViewGroup.java": r'''package android.view;import android.content.Context;import java.util.*;
public class ViewGroup extends View {
 public final ArrayList<View> children=new ArrayList<>();public ViewGroup(Context c){super(c);}
 public void addView(View v){children.add(v);v.parent=this;}public void addView(View v,LayoutParams p){addView(v);}
 public void removeView(View v){children.remove(v);v.parent=null;}public void removeAllViews(){for(View v:children)v.parent=null;children.clear();}
 public static class LayoutParams {public int width,height;public LayoutParams(int w,int h){width=w;height=h;}}
}''',
        "android/widget/TextView.java": r'''package android.widget;import android.content.Context;import android.view.View;
public class TextView extends View {public CharSequence text="";public TextView(Context c){super(c);}public void setText(int r){text=context.getString(r);}public void setText(CharSequence s){text=s;}
 public CharSequence getText(){return text;}public void setTextColor(int c){}public void setTextSize(float f){}}
''',
        "android/widget/Button.java": "package android.widget;public class Button extends TextView {public Button(android.content.Context c){super(c);}}",
        "android/widget/LinearLayout.java": r'''package android.widget;import android.content.Context;import android.view.ViewGroup;
public class LinearLayout extends ViewGroup {public static final int HORIZONTAL=0,VERTICAL=1;public LinearLayout(Context c){super(c);}public void setOrientation(int v){}public void setGravity(int g){}
 public static class LayoutParams extends ViewGroup.LayoutParams {public LayoutParams(int w,int h){super(w,h);}public LayoutParams(int w,int h,float f){super(w,h);}}}''',
        "android/widget/FrameLayout.java": r'''package android.widget;import android.content.Context;import android.view.ViewGroup;
public class FrameLayout extends ViewGroup {public FrameLayout(Context c){super(c);}public static class LayoutParams extends ViewGroup.LayoutParams {public LayoutParams(int w,int h,int g){super(w,h);}}}''',
        "android/widget/Toast.java": r'''package android.widget;import android.content.Context;
public class Toast {public static final int LENGTH_LONG=1;public static Toast makeText(Context c,int r,int duration){return new Toast();}public void show(){}}''',
    }


def _json_stubs():
    return {
        "org/json/JSONObject.java": r'''package org.json;
import java.util.*;
public final class JSONObject {
 public static final Object NULL=new Object();final LinkedHashMap<String,Object> values=new LinkedHashMap<>();static final Map<String,JSONObject> encoded=new HashMap<>();
 public JSONObject(){}public JSONObject(String text){JSONObject source=encoded.get(text);if(source==null)throw new IllegalArgumentException("unknown fixture JSON: "+text);values.putAll(source.copy().values);}
 JSONObject copy(){JSONObject result=new JSONObject();for(Map.Entry<String,Object> e:values.entrySet()){Object v=e.getValue();result.values.put(e.getKey(),v instanceof JSONObject?((JSONObject)v).copy():v instanceof JSONArray?((JSONArray)v).copy():v);}return result;}
 public JSONObject put(String k,Object v){values.put(k,v);return this;}public Object opt(String k){return values.get(k);}public Object remove(String k){return values.remove(k);}
 public boolean has(String k){return values.containsKey(k);}public int length(){return values.size();}public Iterator<String> keys(){return values.keySet().iterator();}
 public JSONObject optJSONObject(String k){Object v=opt(k);return v instanceof JSONObject?(JSONObject)v:null;}
 public JSONArray optJSONArray(String k){Object v=opt(k);return v instanceof JSONArray?(JSONArray)v:null;}
 public String optString(String k){return optString(k,"");}public String optString(String k,String d){Object v=opt(k);return v instanceof String?(String)v:d;}
 public boolean optBoolean(String k){return optBoolean(k,false);}public boolean optBoolean(String k,boolean d){Object v=opt(k);return v instanceof Boolean?(Boolean)v:d;}
 public long optLong(String k){return optLong(k,0);}public long optLong(String k,long d){Object v=opt(k);return v instanceof Number?((Number)v).longValue():d;}
 public int optInt(String k){return optInt(k,0);}public int optInt(String k,int d){return (int)optLong(k,d);}
 public String getString(String k){if(!(opt(k) instanceof String))throw new IllegalArgumentException(k);return (String)opt(k);}
 public int getInt(String k){if(!(opt(k) instanceof Number))throw new IllegalArgumentException(k);return ((Number)opt(k)).intValue();}
 public long getLong(String k){if(!(opt(k) instanceof Number))throw new IllegalArgumentException(k);return ((Number)opt(k)).longValue();}
 public boolean getBoolean(String k){if(!(opt(k) instanceof Boolean))throw new IllegalArgumentException(k);return (Boolean)opt(k);}
 static String quote(String s){return "\""+s.replace("\\","\\\\").replace("\"","\\\"")+"\"";}static String value(Object v){return v instanceof String?quote((String)v):v==null||v==NULL?"null":v.toString();}
 public String toString(){StringBuilder b=new StringBuilder("{");for(Map.Entry<String,Object> e:values.entrySet()){if(b.length()>1)b.append(',');b.append(quote(e.getKey())).append(':').append(value(e.getValue()));}String text=b.append('}').toString();encoded.put(text,copy());return text;}
}''',
        "org/json/JSONArray.java": r'''package org.json;import java.util.*;
public final class JSONArray {final ArrayList<Object> values=new ArrayList<>();public JSONArray(){}
 public JSONArray put(Object v){values.add(v);return this;}public int length(){return values.size();}public JSONObject optJSONObject(int i){return i>=0&&i<values.size()&&values.get(i) instanceof JSONObject?(JSONObject)values.get(i):null;}
 public JSONObject getJSONObject(int i){JSONObject v=optJSONObject(i);if(v==null)throw new IllegalArgumentException();return v;}
 JSONArray copy(){JSONArray r=new JSONArray();for(Object v:values)r.put(v instanceof JSONObject?((JSONObject)v).copy():v);return r;}
 public String toString(){StringBuilder b=new StringBuilder("[");for(Object v:values){if(b.length()>1)b.append(',');b.append(JSONObject.value(v));}return b.append(']').toString();}}
''',
    }


def _support_stubs(source):
    resources = sorted(set(re.findall(r"R\.string\.([A-Za-z0-9_]+)", source)))
    constants = "".join(f"public static final int {name}={at};" for at, name in enumerate(resources, 1))
    return {
        PACKAGE.replace(".", "/") + "/R.java": f"package {PACKAGE};public final class R {{public static final class string {{{constants}}}}}",
        PACKAGE.replace(".", "/") + "/UnifiedRuntime.java": f"package {PACKAGE};final class UnifiedRuntime {{static boolean isEnabled(android.content.Context c){{return false;}}}}",
        PACKAGE.replace(".", "/") + "/UnifiedMP4Background.java": f'''package {PACKAGE};
final class UnifiedMP4Background {{
 interface Host {{org.json.JSONObject status();void park();void resume();boolean userPaused();void changed();}}
 static org.json.JSONObject snapshot(){{return new org.json.JSONObject().put("state","off");}}
 static void prepare(android.app.Activity a,Host host){{}}static void stopCurrent(){{}}static void backgrounded(android.app.Activity a){{}}
 static void foregrounding(android.app.Activity a){{}}static void focusLost(android.app.Activity a){{}}
 static boolean ownsSurface(android.app.Activity a){{return false;}}static void sample(org.json.JSONObject value){{}}static boolean expectsService(){{return false;}}
}}''',
    }


HARNESS = r'''package game.qualiarts.idolypride.localserver;
import android.app.Activity;import android.content.*;import android.net.Uri;import android.os.*;import android.view.*;
import java.io.*;import java.nio.file.*;import java.lang.reflect.*;import java.util.*;import org.json.*;
public final class SaveLifecycleHarness {
 static final String JOB="0123456789abcdef0123456789abcdef",OUTPUT="abcdef0123456789abcdef0123456789",ONE="11111111111111111111111111111111",SECOND="22222222222222222222222222222222";
 public static String nativeSession,nativeQueue,queueIdentity,nativeDiagnosticJson;public static int cancelCalls,queueCommands,queueOperation,queuePosition;public static boolean allowNativeReady;
 static final byte[] VIDEO=new byte[]{7,9,3,5,1,8};
 static final class ForeignActivity extends Activity {ForeignActivity(File root){super(root);}}
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
 static Object field(String name)throws Exception{Field f=UnifiedMP4Export.class.getDeclaredField(name);f.setAccessible(true);return f.get(null);}
 static void set(String name,Object value)throws Exception{Field f=UnifiedMP4Export.class.getDeclaredField(name);f.setAccessible(true);f.set(null,value);}
 static void poll()throws Exception{Method m=UnifiedMP4Export.class.getDeclaredMethod("poll");m.setAccessible(true);m.invoke(null);Handler.drain();}
 static void phase(String phase){phase(phase,OUTPUT);}static void phase(String phase,String output){nativeSession=new JSONObject().put("phase",phase).put("export_id",output).put("ready",false).toString();}
 public static void cancelledFromNative(){cancelCalls++;phase("idle");}
 static void nativeQueueFixture(){nativeQueueFixture("completed");}static void nativeQueueFixture(String state){nativeQueue=new JSONObject().put("available",true).put("running",!state.equals("completed")).put("paused",false)
  .put("jobs",new JSONArray().put(new JSONObject().put("job_id",JOB).put("output_id",OUTPUT).put("state",state).put("timeline","tln_live_test"))).toString();}
 static View saveButton()throws Exception{return (View)field("overlaySave");}
 static void settled()throws Exception{for(int count=0;count<200;count++){Handler.drain();if(!((Boolean)field("saving")))return;Thread.sleep(5);}throw new AssertionError("document copy did not settle");}
 static final class BookmarkStore implements Mp4CompletedExports.Store {
  Set<String> saved=new LinkedHashSet<>();boolean fail=true;int writes;
  public Set<String> read(){return new LinkedHashSet<>(saved);}
  public boolean write(Set<String> rows){writes++;if(fail)return false;saved=new LinkedHashSet<>(rows);return true;}
 }
 public static void main(String[]args)throws Exception{
  System.load(args[0]);File files=new File(args[1]).getCanonicalFile();files.mkdirs();
  File transientRoot=new File(files,"transient"),durable=new File(files,"completed");transientRoot.mkdir();durable.mkdir();
  File source=new File(durable,OUTPUT+".mp4");Files.write(source.toPath(),VIDEO);nativeQueueFixture("running");phase("rendering");
  BookmarkStore flakyStore=new BookmarkStore();Mp4CompletedExports bookmarks=new Mp4CompletedExports(files,flakyStore);
  need(!bookmarks.remember(durable,OUTPUT,JOB)&&bookmarks.entries().size()==1&&flakyStore.saved.isEmpty(),"failed durable metadata write keeps live output reachable without claiming persistence");
  flakyStore.fail=false;need(bookmarks.remember(durable,OUTPUT,JOB)&&flakyStore.writes==2,"remembering an unchanged output retries a previously failed bookmark write");
  need(new Mp4CompletedExports(files,flakyStore).entries().size()==1&&Arrays.equals(Files.readAllBytes(source.toPath()),VIDEO),"retried durable metadata rehydrates without modifying the video");
  set("configured",true);set("initialized",true);set("queueConfigured",true);set("exportRoot",transientRoot);set("persistentExportRoot",durable);
  Activity first=new Activity(files);UnifiedMP4Export.restoreState(first,null);UnifiedMP4Export.attachGame(first);UnifiedMP4Export.gameResumed(first);
  Object originalRegistry=field("completedExports");set("completedExports",bookmarks);flakyStore.fail=true;allowNativeReady=true;
  need(!UnifiedMP4Export.oneShotCompletionReady(),"one-shot completion cannot claim recovery when trusted directory persistence fails");
  need(!UnifiedMP4Export.requestStart(first,30,1,16000000)&&first.activityLaunches==0&&field("pending")==null,"failed completion recovery registration rejects capture before navigation or pending work");
  flakyStore.fail=false;need(UnifiedMP4Export.oneShotCompletionReady(),"trusted directory persistence retries before capture becomes eligible");
  set("completedExports",originalRegistry);allowNativeReady=false;poll();
  View.OnClickListener pendingOldClick=saveButton().click;
  need(first.pickerLaunches==0,"capture progress cannot launch any external document picker");
  phase("completed");nativeQueueFixture();for(int i=0;i<5;i++)poll();
  need(first.pickerLaunches==0,"completion and repeated polls never launch the Downloads picker");
  need(UnifiedMP4Export.canSave()&&saveButton().isEnabled(),"completion exposes an explicit user Save");
  if(pendingOldClick!=null)pendingOldClick.onClick(saveButton());
  need(first.pickerLaunches==0,"a pending click bound before completion cannot turn into a Save tap");
  need(saveButton().performClick(),"fresh explicit completed Save click is actionable");
  need(first.pickerLaunches==1&&first.lastRequest==UnifiedMP4Export.SAVE_DOCUMENT,"one deliberate Save opens exactly one document picker");
  UnifiedMP4Export.SaveTarget queuedTarget=UnifiedMP4Export.completedOutputs().get(0);
  need(!UnifiedMP4Export.deleteCompleted(queuedTarget)&&source.isFile()&&queueCommands==0,"a pending picker blocks even an explicit completed-output deletion request");
  need(Intent.ACTION_CREATE_DOCUMENT.equals(first.lastPicker.action)&&"video/mp4".equals(first.lastPicker.type),"only explicit MP4 destination selection is launched");
  UnifiedMP4Export.activityResult(new ForeignActivity(files),UnifiedMP4Export.SAVE_DOCUMENT,Activity.RESULT_CANCELED,null);
  need(field("pendingSaveId")!=null&&source.isFile(),"another Activity class cannot consume the live owner's pending picker result");
  UnifiedMP4Export.requestSave(first,JOB);UnifiedMP4Export.requestSave(first);
  need(first.pickerLaunches==1,"an outstanding picker prevents duplicate or reentrant Save launch");
  Bundle pickerState=new Bundle();UnifiedMP4Export.saveState(pickerState);UnifiedMP4Export.gamePaused(first);UnifiedMP4Export.gameStopped(first);
  UnifiedMP4Export.gameDestroyed(first);first.destroyed=true;
  set("pendingSaveId",null);set("pendingSaveRoot",null);set("completedExports",null);set("application",null);
  // Android recreates the Activity while the document picker remains in front;
  // the native session is idle, while the durable native queue retains output.
  Activity replacement=new Activity(files);UnifiedMP4Export.restoreState(replacement,pickerState);UnifiedMP4Export.attachGame(replacement);
  need(replacement.pickerLaunches==0,"restoring an outstanding picker never launches another picker");
  UnifiedMP4Export.requestSave(replacement,JOB);need(replacement.pickerLaunches==0,"rehydrated pending picker blocks duplicate launch");
  need(UnifiedMP4Export.activityResult(replacement,UnifiedMP4Export.SAVE_DOCUMENT,Activity.RESULT_CANCELED,null),"picker cancellation is handled by the recreated owner");
  UnifiedMP4Export.gameResumed(replacement);poll();
  need(UnifiedMP4Export.canSave()&&saveButton().getVisibility()==View.VISIBLE&&saveButton().isEnabled(),"cancel/return preserves reachable Save despite native completed-to-idle transition");
  need(Arrays.equals(Files.readAllBytes(source.toPath()),VIDEO)&&queueCommands==0,"cancel and Activity destruction never delete the private completed source or durable queue job");
  need(replacement.pickerLaunches==0,"returning from a cancelled picker cannot automatically reopen it");
  UnifiedMP4Export.requestSave(replacement,JOB);
  need(replacement.pickerLaunches==1,"a fresh explicit Save remains available after cancellation and recreation");
  Intent chosen=new Intent("fixture-result").setData(Uri.parse("content://test/saved.mp4"));
  need(UnifiedMP4Export.activityResult(replacement,UnifiedMP4Export.SAVE_DOCUMENT,Activity.RESULT_OK,chosen),"chosen destination is copied");settled();
  need(Arrays.equals(ContentResolver.outputs.get("content://test/saved.mp4"),VIDEO),"document provider receives the complete original bytes");
  need(Arrays.equals(Files.readAllBytes(source.toPath()),VIDEO)&&queueCommands==0,"successful Save copies rather than consuming or removing the completed output");
  poll();need(UnifiedMP4Export.canSave(),"a copied export stays available for another explicit Save until confirmed deletion");
  UnifiedMP4Export.requestSave(replacement,JOB);ContentResolver.failWrites=true;
  UnifiedMP4Export.activityResult(replacement,UnifiedMP4Export.SAVE_DOCUMENT,Activity.RESULT_OK,new Intent("failed").setData(Uri.parse("content://test/unavailable.mp4")));settled();
  need(Arrays.equals(Files.readAllBytes(source.toPath()),VIDEO)&&UnifiedMP4Export.canSave(),"provider failure retains the source and retry action");
  ContentResolver.failWrites=false;
  File oneShot=new File(transientRoot,ONE+".mp4");byte[] oneBytes=new byte[]{2,4,6,8};Files.write(oneShot.toPath(),oneBytes);
  phase("completed",ONE);poll();need(UnifiedMP4Export.completedOutputs().size()==2,"separate completed one-shot joins durable output inventory");
  View.OnClickListener completedClick=saveButton().click;
  int pickerCountBeforeNextJob=replacement.pickerLaunches;
  phase("rendering",SECOND);poll();if(completedClick!=null)completedClick.onClick(saveButton());
  need(replacement.pickerLaunches==pickerCountBeforeNextJob,"a click rendered for a previous output cannot save during the next job");
  need(UnifiedMP4Export.completedOutputs().size()==2,"a new job never consumes earlier completed outputs");
  phase("idle",SECOND);nativeQueue=new JSONObject().put("available",false).put("jobs",new JSONArray()).toString();
  UnifiedMP4Export.gameDestroyed(replacement);replacement.destroyed=true;
  set("completedExports",null);set("application",null);set("last",new JSONObject());set("lastQueue",new JSONObject());set("queueConfigured",false);
  Activity reopened=new Activity(files);UnifiedMP4Export.restoreState(reopened,null);UnifiedMP4Export.attachGame(reopened);UnifiedMP4Export.gameResumed(reopened);poll();
  need(UnifiedMP4Export.completedOutputs().size()==2&&UnifiedMP4Export.canSave(),"null Bundle restores completed inventory from durable preferences without a current native completed session");
  UnifiedMP4Export.requestSave(reopened);
  need(reopened.pickerLaunches==1,"restored newest one-shot remains explicitly saveable");
  UnifiedMP4Export.SaveTarget oneTarget=UnifiedMP4Export.completedOutputs().get(0);
  need(oneTarget.outputId.equals(ONE)&&!UnifiedMP4Export.deleteCompleted(oneTarget)&&oneShot.isFile(),"a pending one-shot picker also retains its source until it closes");
  UnifiedMP4Export.activityResult(reopened,UnifiedMP4Export.SAVE_DOCUMENT,Activity.RESULT_OK,new Intent("restored").setData(Uri.parse("content://test/one-shot.mp4")));settled();
  need(Arrays.equals(ContentResolver.outputs.get("content://test/one-shot.mp4"),oneBytes)&&Arrays.equals(Files.readAllBytes(oneShot.toPath()),oneBytes),"persisted one-shot copy preserves its source");
  need(queueCommands==0,"save lifecycle never issues the destructive queue command");
  need(UnifiedMP4Export.deleteCompleted(oneTarget)&&!oneShot.exists(),"only the explicit deletion entry point consumes a completed one-shot after its picker closes");
  need(source.isFile()&&queueCommands==0,"one-shot deletion cannot consume another output or queued job");
  need(!UnifiedMP4Export.deleteCompleted(queuedTarget)&&source.isFile()&&queueCommands==0,"an unavailable native queue cannot falsely confirm queued output deletion");
  set("queueConfigured",true);nativeQueueFixture();poll();
  need(UnifiedMP4Export.deleteCompleted(queuedTarget)&&queueCommands==1&&queueOperation==2&&queuePosition==1&&JOB.equals(queueIdentity),"explicit queued deletion alone supplies native output-delete consent");
  need(UnifiedMP4Export.diagnostics().optString("last_save_failure_stage").equals("save_open_document"),"actual failed document-provider stage survives the process-style restore");
  JSONArray traceRows=new JSONArray();
  for(int i=0;i<20;i++)traceRows.put(new JSONObject().put("sequence",i+1).put("stage","source_admission").put("code","offline_pipeline_not_verified").put("frame",i).put("tick",i*2).put("path","/private/not-exported"));
  traceRows.put(new JSONObject().put("stage","/private/path").put("code","bad").put("sequence",Long.MAX_VALUE));
  JSONObject modules=new JSONObject().put("scene_control",false).put("native_clock",true).put("/private/path",true).put("capability","secret");
  for(int i=0;i<40;i++)modules.put("module_"+i,false);
  JSONObject trace=new JSONObject().put("schema",1).put("current_stage","source_admission").put("last_error","offline_pipeline_not_verified")
   .put("events",traceRows).put("modules",modules).put("capability","secret").put("address","0x123");
  nativeDiagnosticJson=new JSONObject().put("export_trace",trace).toString();poll();
  JSONObject exported=UnifiedMP4Export.diagnostics().optJSONObject("export_trace");
  need(exported!=null&&exported.optString("current_stage").equals("source_admission")&&exported.optString("last_error").equals("offline_pipeline_not_verified"),"actual separate JNI diagnostics reaches the exported bundle");
  need(exported.optJSONArray("events").length()==15&&exported.optJSONArray("events").optJSONObject(0).optLong("sequence")==6,"only the last16 native rows are considered and malformed rows are excluded");
  need(exported.optJSONObject("modules").length()==24&&!exported.optJSONObject("modules").has("capability")&&!exported.optJSONObject("modules").has("/private/path"),"module map is bounded boolean facts only");
  need(!exported.has("capability")&&!exported.has("address")&&!exported.optJSONArray("events").optJSONObject(0).has("path"),"native trace redacts paths, addresses, payloads and unknown keys");
  set("lastNativeTrace",null);set("initialized",false);nativeDiagnosticJson=null;
  JSONObject restarted=UnifiedMP4Export.diagnostics();
  need(restarted.optJSONObject("export_trace")!=null&&restarted.optJSONObject("last_failed_export_trace")!=null,"persisted bounded failure trace remains available without live JNI after restart");
  set("initialized",true);nativeDiagnosticJson=new JSONObject().put("export_trace",new JSONObject().put("schema",1).put("current_stage","idle").put("last_error","none")).toString();poll();
  need(UnifiedMP4Export.diagnostics().optJSONObject("last_failed_export_trace").optString("last_error").equals("offline_pipeline_not_verified"),"fresh idle cannot erase a previous failed attempt");
  nativeDiagnosticJson=new JSONObject().put("export_trace",new JSONObject().put("schema",2).put("current_stage","untrusted")).toString();set("lastNativeTrace",null);
  need(!UnifiedMP4Export.diagnostics().optJSONObject("export_trace").optString("current_stage").equals("untrusted"),"unknown native diagnostic schema never enters the report");
  System.out.println("PASS actual controller explicit Save, durable completion, recreation, cancel and source retention");
 }
}
'''


NATIVE = r'''#include <jni.h>
static jclass fixture(JNIEnv* env){return env->FindClass("game/qualiarts/idolypride/localserver/SaveLifecycleHarness");}
static jstring value(JNIEnv* env,const char* name){jclass type=fixture(env);return static_cast<jstring>(env->GetStaticObjectField(type,env->GetStaticFieldID(type,name,"Ljava/lang/String;")));}
extern "C" {
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStatus(JNIEnv* e,jclass){return value(e,"nativeSession");}
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeDiagnostics(JNIEnv* e,jclass){return value(e,"nativeDiagnosticJson");}
JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueStatus(JNIEnv* e,jclass){return value(e,"nativeQueue");}
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeCancel(JNIEnv* e,jclass){jclass type=fixture(e);e->CallStaticVoidMethod(type,e->GetStaticMethodID(type,"cancelledFromNative","()V"));}
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeInvalidateQueueSelection(JNIEnv*,jclass){}
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeSuspend(JNIEnv*,jclass,jint){}
JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeResume(JNIEnv*,jclass){}
JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeReady(JNIEnv* e,jclass){jclass type=fixture(e);return e->GetStaticBooleanField(type,e->GetStaticFieldID(type,"allowNativeReady","Z"));}
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueuePause(JNIEnv*,jclass){return 0;}
JNIEXPORT jint JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueCommand(JNIEnv* e,jclass,jint operation,jstring id,jint position){jclass type=fixture(e);jfieldID count=e->GetStaticFieldID(type,"queueCommands","I");e->SetStaticIntField(type,count,e->GetStaticIntField(type,count)+1);e->SetStaticIntField(type,e->GetStaticFieldID(type,"queueOperation","I"),operation);e->SetStaticIntField(type,e->GetStaticFieldID(type,"queuePosition","I"),position);e->SetStaticObjectField(type,e->GetStaticFieldID(type,"queueIdentity","Ljava/lang/String;"),id);return 0;}
}
'''


def test_actual_controller_explicit_save_survives_native_idle_recreation_and_picker_cancel(tmp_path):
    javac, java, compiler = shutil.which("javac"), shutil.which("java"), shutil.which("c++")
    assert javac and java and compiler, "JDK and C++ compiler required for actual Java/JNI lifecycle regression"
    java_home = Path(javac).resolve().parents[1]
    headers = java_home / "include"
    assert (headers / "jni.h").is_file() and (headers / "linux/jni_md.h").is_file()
    source = (JAVA / "UnifiedMP4Export.java").read_text()
    paths = [_write(tmp_path, name, text) for name, text in {
        **_android_stubs(), **_json_stubs(), **_support_stubs(source),
        PACKAGE.replace(".", "/") + "/SaveLifecycleHarness.java": HARNESS,
    }.items()]
    native = _write(tmp_path, "native.cpp", NATIVE)
    library = tmp_path / "libsave_lifecycle_fixture.so"
    compiled_native = subprocess.run([compiler, "-std=c++17", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                                      "-I", str(headers), "-I", str(headers / "linux"), str(native), "-o", str(library)],
                                     capture_output=True, text=True, timeout=30)
    assert compiled_native.returncode == 0, compiled_native.stderr
    classes = tmp_path / "classes"
    production = [JAVA / "UnifiedMP4Export.java", *JAVA.glob("Mp4*.java")]
    if (JAVA / "DocumentPickerHistory.java").exists():
        production.append(JAVA / "DocumentPickerHistory.java")
    compiled = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-encoding", "UTF-8", "-d", str(classes),
                               *map(str, production), *map(str, paths)],
                              capture_output=True, text=True, timeout=60)
    assert compiled.returncode == 0, compiled.stderr
    environment = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        environment.pop(key, None)
    executed = subprocess.run([java, "-Xmx256m", "-cp", str(classes), PACKAGE + ".SaveLifecycleHarness",
                               str(library), str(tmp_path / "files")], capture_output=True, text=True,
                              env=environment, timeout=30)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS actual controller explicit Save, durable completion, recreation, cancel and source retention"
