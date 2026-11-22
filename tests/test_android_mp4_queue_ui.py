"""Run the Android queue's real action policy and localized resource contract."""
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.localserver"
JAVA = ROOT / "android-server/app/src/main/java" / PACKAGE.replace(".", "/")
RES = ROOT / "android-server/app/src/main/res"


def test_queue_buttons_follow_job_ownership_and_async_commands(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    harness = tmp_path / "QueueUiHarness.java"
    harness.write_text(r'''package game.qualiarts.idolypride.localserver;
public final class QueueUiHarness {
  static void need(boolean condition,String message){if(!condition)throw new AssertionError(message);}
  public static void main(String[]args){
    Mp4QueueUiState.Controls empty=new Mp4QueueUiState.Controls(true,false,false,false,false,true,true,0,0);
    need(empty.enqueue&&!empty.run&&empty.immediate,"loaded MV can be added or exported; empty queue cannot run");
    Mp4QueueUiState.Controls waiting=new Mp4QueueUiState.Controls(true,false,false,false,false,true,true,2,2);
    need(waiting.enqueue&&waiting.run&&!waiting.pause&&!waiting.resume,"queued independent selections can run");
    int first=Mp4QueueUiState.actions("pending",0,2,false),second=Mp4QueueUiState.actions("pending",1,2,false);
    need((first&Mp4QueueUiState.DOWN)!=0&&(first&Mp4QueueUiState.UP)==0,"first job only moves later");
    need((second&Mp4QueueUiState.UP)!=0&&(second&Mp4QueueUiState.DOWN)==0,"last job only moves earlier");
    need((first&Mp4QueueUiState.REMOVE)!=0&&(first&Mp4QueueUiState.CANCEL)!=0,"waiting job removable or cancellable");
    Mp4QueueUiState.Controls active=new Mp4QueueUiState.Controls(true,false,true,false,true,false,true,1,2);
    need(active.pause&&!active.run&&!active.enqueue&&!active.immediate&&!active.resume,"renderer ownership blocks competing work");
    need(Mp4QueueUiState.actions("running",0,2,false)==Mp4QueueUiState.CANCEL,"active job cannot be removed while runner owns its scene");
    Mp4QueueUiState.Controls paused=new Mp4QueueUiState.Controls(true,false,true,true,true,false,true,1,2);
    need(paused.resume&&!paused.pause&&!paused.run&&!paused.enqueue,"resume retains the active job");
    need(Mp4QueueUiState.actions("paused",0,2,false)==Mp4QueueUiState.CANCEL,"paused job still owns runtime resources");
    for(String state:new String[]{"failed","cancelled","interrupted"}){
      int actions=Mp4QueueUiState.actions(state,0,2,false);
      need(actions==(Mp4QueueUiState.REMOVE|Mp4QueueUiState.RETRY),"terminal failure is restartable, never falsely saveable");
    }
    need(Mp4QueueUiState.actions("completed",0,2,false)==(Mp4QueueUiState.REMOVE|Mp4QueueUiState.SAVE),"completed output can be saved without retry overwrite");
    Mp4QueueUiState.Controls pending=new Mp4QueueUiState.Controls(true,true,false,false,false,true,true,1,1);
    need(!pending.enqueue&&!pending.run&&!pending.pause&&!pending.resume&&!pending.immediate,"async native command disables conflicting controls");
    need(Mp4QueueUiState.actions("completed",0,2,true)==0,"pending command also locks per-job actions");
    Mp4QueueUiState.Controls full=new Mp4QueueUiState.Controls(true,false,false,false,false,true,true,8,8);
    need(!full.enqueue&&full.run,"capacity is enforced without disabling existing jobs");
    Mp4QueueUiState.Controls journalUnavailable=new Mp4QueueUiState.Controls(false,false,false,false,false,true,true,0,0);
    need(!journalUnavailable.enqueue&&!journalUnavailable.run&&journalUnavailable.immediate,"single export survives a journal-only error");
    Mp4QueueUiState.Controls selectedButUnbound=new Mp4QueueUiState.Controls(true,false,false,false,false,true,false,false,0,0);
    need(selectedButUnbound.enqueue&&!selectedButUnbound.immediate&&!selectedButUnbound.run,"real selection can join the list while export stays unbound");
    Mp4QueueUiState.Controls selectedButRefused=new Mp4QueueUiState.Controls(true,false,false,false,false,false,false,false,0,0);
    need(!selectedButRefused.enqueue&&!selectedButRefused.immediate,"selection existence alone cannot override a refused immutable Add candidate");
    Mp4QueueUiState.Controls cold=new Mp4QueueUiState.Controls(true,false,false,false,false,false,false,2,2);
    need(!cold.run&&!cold.resume&&!cold.enqueue&&!cold.immediate,"persisted jobs are inspectable before game start without reopening a blank player");
    Mp4QueueUiState.Controls unavailableWorld=new Mp4QueueUiState.Controls(true,false,true,true,true,false,false,1,2);
    need(!unavailableWorld.resume,"a paused queue cannot reorder an unavailable game world");
    need(Mp4QueueUiState.actions("garbage",0,1,false)==0&&Mp4QueueUiState.actions("pending",0,9,false)==0,"invalid snapshots cannot enable mutation");
    need(Mp4QueueUiState.jobId("0123456789abcdef0123456789abcdef"),"native fixed job identity accepted");
    need(!Mp4QueueUiState.jobId("../video")&&!Mp4QueueUiState.jobId("ABCDEF0123456789abcdef0123456789")&&!Mp4QueueUiState.jobId(null),"no path or malformed identities reach callbacks");
    System.out.println("PASS queue UI policy");
  }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes),
                               str(JAVA / "Mp4QueueUiState.java"), str(harness)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([java, "-Xmx128m", "-cp", str(classes), PACKAGE + ".QueueUiHarness"],
                              capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS queue UI policy"


def test_queue_resources_cover_all_languages_and_keep_format_arguments():
    locales = {}
    for folder in ("values", "values-ja", "values-en"):
        root = ET.parse(RES / folder / "strings_mp4_queue.xml").getroot()
        values = {row.attrib["name"]: row.text or "" for row in root}
        assert len(values) == len(root)
        assert all(value.strip() for value in values.values())
        locales[folder] = values
    reference = locales["values"]
    referenced = set(re.findall(r"R\.string\.(mp4_queue_[a-z_]+)", (JAVA / "MainActivity.java").read_text()))
    assert referenced <= reference.keys()
    for values in locales.values():
        assert values.keys() == reference.keys()
        for name, value in values.items():
            assert sorted(re.findall(r"%\d+\$[ds]", value)) == sorted(re.findall(r"%\d+\$[ds]", reference[name]))
    assert "실험" in reference["mp4_queue_background_experimental"]
    assert "実験" in locales["values-ja"]["mp4_queue_background_experimental"]
    assert "experimental" in locales["values-en"]["mp4_queue_background_experimental"]


def test_completed_removal_waits_for_explicit_file_delete_confirmation(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = (JAVA / "MainActivity.java").read_text()
    start = source.index("    private void requestMp4QueueRemoval(")
    brace = source.index("{", start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    actual_method = source[start:end]
    harness = tmp_path / "RemovalUiHarness.java"
    harness.write_text(r'''package game.qualiarts.idolypride.localserver;
public final class RemovalUiHarness {
  int commands,operation,position;String identity;
  static final class R {static final class string {static final int mp4_queue_delete_file_job=1,mp4_queue_delete_confirm=2;}}
  static final class android {static final class R {static final class string {static final int cancel=3;}}}
  interface Click {void click(Object dialog,int which);}
  static final class AlertDialog {
    static Builder latest;
    static final class Builder {
      int title,message,positiveLabel,negativeLabel;Click positive,negative;
      Builder(Object owner){}
      Builder setTitle(int value){title=value;return this;}
      Builder setMessage(int value){message=value;return this;}
      Builder setPositiveButton(int value,Click action){positiveLabel=value;positive=action;return this;}
      Builder setNegativeButton(int value,Click action){negativeLabel=value;negative=action;return this;}
      AlertDialog show(){latest=this;return new AlertDialog();}
    }
  }
  private void mp4QueueCommand(int op,String id,int where){commands++;operation=op;identity=id;position=where;}
  static void need(boolean condition,String message){if(!condition)throw new AssertionError(message);}
''' + actual_method + r'''
  public static void main(String[]arguments){
    String id="0123456789abcdef0123456789abcdef";
    RemovalUiHarness panel=new RemovalUiHarness();panel.requestMp4QueueRemoval(id,"pending");
    need(panel.commands==1&&panel.operation==2&&panel.position==0&&AlertDialog.latest==null,"waiting job removal never authorizes output deletion");
    panel=new RemovalUiHarness();panel.requestMp4QueueRemoval(id,"completed");
    need(panel.commands==0,"completed output must survive until the user confirms");
    AlertDialog.Builder confirmation=AlertDialog.latest;
    need(confirmation!=null&&confirmation.title==R.string.mp4_queue_delete_file_job&&confirmation.message==R.string.mp4_queue_delete_confirm,"dialog names both the file and job");
    need(confirmation.negativeLabel==android.R.string.cancel&&confirmation.negative==null,"cancel leaves the completed file and job untouched");
    need(confirmation.positiveLabel==R.string.mp4_queue_delete_file_job,"destructive button is explicit");
    confirmation.positive.click(null,1);
    need(panel.commands==1&&panel.operation==2&&panel.position==1&&id.equals(panel.identity),"only affirmative confirmation sets the native delete-output consent flag");
    panel=new RemovalUiHarness();AlertDialog.latest=null;panel.requestMp4QueueRemoval(id,"failed");
    need(panel.commands==1&&panel.position==0&&AlertDialog.latest==null,"failed job removal cannot delete an interrupted final file");
    panel=new RemovalUiHarness();panel.requestMp4QueueRemoval("../other","completed");
    need(panel.commands==0&&AlertDialog.latest==null,"invalid job identity never reaches deletion");
    System.out.println("PASS completed removal confirmation");
  }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes),
                               str(JAVA / "Mp4QueueUiState.java"), str(harness)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([java, "-Xmx128m", "-cp", str(classes), PACKAGE + ".RemovalUiHarness"],
                              capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS completed removal confirmation"


def test_title_enrichment_keeps_native_identity_and_switches_display_language(tmp_path):
    """Execute the real title helper; substitute only Android's JSON container."""
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    json_dir = tmp_path / "org/json"; json_dir.mkdir(parents=True)
    objects = json_dir / "JSONObject.java"
    objects.write_text(r'''package org.json;
import java.util.*;
public final class JSONObject {
  final LinkedHashMap<String,Object> values=new LinkedHashMap<>();
  static final Map<String,JSONObject> encoded=new HashMap<>();
  public JSONObject(){}
  public JSONObject(String text){JSONObject source=encoded.get(text);if(source==null)throw new IllegalArgumentException();values.putAll(source.copy().values);}
  JSONObject copy(){JSONObject result=new JSONObject();for(Map.Entry<String,Object>entry:values.entrySet()){Object value=entry.getValue();result.values.put(entry.getKey(),value instanceof JSONObject?((JSONObject)value).copy():value instanceof JSONArray?((JSONArray)value).copy():value);}return result;}
  public JSONObject put(String key,Object value){values.put(key,value);return this;}
  public int length(){return values.size();}
  public Iterator<String> keys(){return values.keySet().iterator();}
  public Object opt(String key){return values.get(key);}
  public JSONObject optJSONObject(String key){Object value=opt(key);return value instanceof JSONObject?(JSONObject)value:null;}
  public JSONArray optJSONArray(String key){Object value=opt(key);return value instanceof JSONArray?(JSONArray)value:null;}
  public String optString(String key){Object value=opt(key);return value==null?"":value.toString();}
  static String quoted(String text){StringBuilder result=new StringBuilder("\"");for(int at=0;at<text.length();at++){char value=text.charAt(at);if(value=='"'||value=='\\')result.append('\\');result.append(value);}return result.append('"').toString();}
  static String value(Object value){return value instanceof String?quoted((String)value):value==null?"null":value.toString();}
  public String toString(){StringBuilder result=new StringBuilder("{");for(Map.Entry<String,Object>entry:values.entrySet()){if(result.length()>1)result.append(',');result.append(quoted(entry.getKey())).append(':').append(value(entry.getValue()));}String text=result.append('}').toString();encoded.put(text,copy());return text;}
}
''')
    arrays = json_dir / "JSONArray.java"
    arrays.write_text(r'''package org.json;
import java.util.*;
public final class JSONArray {
  final ArrayList<Object>values=new ArrayList<>();
  public JSONArray put(Object value){values.add(value);return this;}
  public int length(){return values.size();}
  public JSONObject optJSONObject(int position){Object value=values.get(position);return value instanceof JSONObject?(JSONObject)value:null;}
  JSONArray copy(){JSONArray result=new JSONArray();for(Object value:values)result.put(value instanceof JSONObject?((JSONObject)value).copy():value);return result;}
  public String toString(){StringBuilder result=new StringBuilder("[");for(Object value:values){if(result.length()>1)result.append(',');result.append(JSONObject.value(value));}return result.append(']').toString();}
}
''')
    harness = tmp_path / "TitleUiHarness.java"
    harness.write_text(r'''package game.qualiarts.idolypride.localserver;
import java.util.Locale;import org.json.*;
public final class TitleUiHarness {
  static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
  static JSONObject catalog(){return new JSONObject().put("ja",new JSONObject().put("tln_live_clb-006","君のこころは輝いてるかい？")).put("ko",new JSONObject().put("tln_live_clb-006","너의 마음은 빛나고 있니?")).put("en",new JSONObject().put("tln_live_clb-006","Kimi no Kokoro wa Kagayaiteru kai?"));}
  public static void main(String[]args){
    JSONObject source=catalog();Mp4TitleCatalog titles=Mp4TitleCatalog.parse(source);
    source.optJSONObject("ko").put("tln_live_clb-006","MUTATED");
    String id="0123456789abcdef0123456789abcdef",output="abcdef0123456789abcdef0123456789";
    JSONObject nativeJob=new JSONObject().put("job_id",id).put("output_id",output).put("timeline","tln_live_clb-006").put("state","completed");
    JSONObject unknown=new JSONObject().put("job_id","11111111111111111111111111111111").put("timeline","tln_live_unknown");
    JSONObject snapshot=new JSONObject().put("jobs",new JSONArray().put(nativeJob).put(unknown));
    JSONObject enriched=titles.enrich(snapshot),job=enriched.optJSONArray("jobs").optJSONObject(0);
    need(id.equals(job.optString("job_id"))&&output.equals(job.optString("output_id"))&&"tln_live_clb-006".equals(job.optString("timeline"))&&"completed".equals(job.optString("state")),"display titles cannot alter native identity or completion");
    need(nativeJob.opt("title_localizations")==null,"native snapshot remains untouched");
    need("너의 마음은 빛나고 있니?".equals(Mp4TitleCatalog.title(job,Locale.KOREAN)),"Korean is copied into immutable display cache");
    need("君のこころは輝いてるかい？".equals(Mp4TitleCatalog.title(job,Locale.JAPANESE)),"language changes use existing job without re-enqueue");
    need("Kimi no Kokoro wa Kagayaiteru kai?".equals(Mp4TitleCatalog.title(job,Locale.ENGLISH)),"English display selected immediately");
    need("너의 마음은 빛나고 있니?".equals(Mp4TitleCatalog.title(job,Locale.FRENCH)),"unsupported locale matches Korean default resources");
    need(Mp4TitleCatalog.title(enriched.optJSONArray("jobs").optJSONObject(1),Locale.ENGLISH).isEmpty(),"unknown title requests generic MV number rather than exposing internal asset name");
    JSONObject invalid=catalog();invalid.optJSONObject("ko").put("tln_live_clb-006","x".repeat(193));
    need(Mp4TitleCatalog.title(Mp4TitleCatalog.parse(invalid).enrich(snapshot).optJSONArray("jobs").optJSONObject(0),Locale.KOREAN).isEmpty(),"oversized optional catalog is ignored safely");
    invalid=catalog();invalid.optJSONObject("ko").put("tln_live_clb-006",new String(new char[]{(char)0xd800}));
    need(Mp4TitleCatalog.title(Mp4TitleCatalog.parse(invalid).enrich(snapshot).optJSONArray("jobs").optJSONObject(0),Locale.KOREAN).isEmpty(),"unpaired UTF16 is not accepted as a title");
    need(Mp4TitleCatalog.title(Mp4TitleCatalog.empty().enrich(snapshot).optJSONArray("jobs").optJSONObject(0),Locale.KOREAN).isEmpty(),"missing catalog does not break queue inspection");
    System.out.println("PASS localized title identity");
  }
}
''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-encoding", "UTF-8", "-d", str(classes),
                               str(JAVA / "Mp4TitleCatalog.java"), str(objects), str(arrays), str(harness)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([java, "-Xmx128m", "-cp", str(classes), PACKAGE + ".TitleUiHarness"],
                              capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS localized title identity"
