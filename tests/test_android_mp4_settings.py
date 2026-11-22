"""Exercise the durable Android editor draft and exact native export contract."""
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver"
RES = ROOT / "android-server/app/src/main/res"


def _actual_method(source, name):
    match = re.search(r"^    private [^\n]+\b" + name + r"\([^\n]*\)\s*\{", source, re.M)
    assert match, name
    start, depth = source.index("{", match.start()), 1
    end = start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


def test_actual_activity_edit_and_recreation_callbacks_restore_the_same_draft(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    # Execute the production adapter and Activity callbacks. Only Android's
    # preferences and controls are substituted; policy and wiring are original.
    source = (JAVA / "MainActivity.java").read_text()
    methods = "\n".join(_actual_method(source, name) for name in (
        "mp4OptionsStore", "restoreMp4Options", "saveMp4Options"))
    preferences = tmp_path / "android/content/SharedPreferences.java"
    preferences.parent.mkdir(parents=True)
    preferences.write_text(r'''package android.content;
import java.util.*;
public final class SharedPreferences {
  final Map<String,String> disk=new LinkedHashMap<>();
  public String getString(String key,String fallback){return disk.getOrDefault(key,fallback);}
  public Editor edit(){return new Editor();}
  public final class Editor {
    final Map<String,String> pending=new LinkedHashMap<>();
    public Editor putString(String key,String value){pending.put(key,value);return this;}
    public void apply(){disk.putAll(pending);}
  }
}''')
    harness = tmp_path / "Mp4ActivitySettingsHarness.java"
    harness.write_text(r'''package game.qualiarts.idolypride.localserver;
import java.util.*;
public final class Mp4ActivitySettingsHarness {
  static final int MODE_PRIVATE=0;
  static final android.content.SharedPreferences DISK=new android.content.SharedPreferences();
  android.content.SharedPreferences getSharedPreferences(String name,int mode){
    need(name.equals("mp4_export")&&mode==MODE_PRIVATE,"the same app-private preference file is used after recreation");return DISK;
  }
  static class View {}
  static class AdapterView<T> extends View {
    interface OnItemSelectedListener {void onItemSelected(AdapterView<?> parent,View view,int position,long id);void onNothingSelected(AdapterView<?> parent);}
  }
  static class Spinner extends AdapterView<Object> {
    int selected;OnItemSelectedListener listener;
    void setSelection(int value){selected=value;if(listener!=null)listener.onItemSelected(this,this,value,value);}
    int getSelectedItemPosition(){return selected;}
    void setOnItemSelectedListener(OnItemSelectedListener value){listener=value;listener.onItemSelected(this,this,selected,selected);}
  }
  interface Editable extends CharSequence {}
  interface TextWatcher {void beforeTextChanged(CharSequence text,int start,int count,int after);void onTextChanged(CharSequence text,int start,int before,int count);void afterTextChanged(Editable text);}
  static class EditText {
    String value="";final List<TextWatcher> listeners=new ArrayList<>();
    String getText(){return value;}
    void setText(String text){value=text;for(TextWatcher listener:listeners)listener.onTextChanged(value,0,0,value.length());}
    void addTextChangedListener(TextWatcher listener){listeners.add(listener);}
  }
  static class TextView {}
  final Spinner mp4Fps=new Spinner(),mp4Codec=new Spinner(),mp4Bitrate=new Spinner(),mp4Resolution=new Spinner();
  final EditText mp4BitrateValue=new EditText(),mp4Width=new EditText(),mp4Height=new EditText();
  Mp4ExportSettings mp4Settings;boolean mp4OptionsLoading;Object mp4Enqueue;TextView mp4Status;
  void refreshMp4Options(){}void refreshMp4(){}
  static void need(boolean condition,String message){if(!condition)throw new AssertionError(message);}
''' + methods + r'''
  public static void main(String[]args){
    Mp4ActivitySettingsHarness first=new Mp4ActivitySettingsHarness();first.restoreMp4Options();
    need(first.mp4Fps.selected==0&&first.mp4Codec.selected==0&&first.mp4Bitrate.selected==0,"fresh Activity has automatic defaults");
    first.mp4Fps.setSelection(1);first.mp4Codec.setSelection(1);first.mp4Bitrate.setSelection(1);first.mp4Resolution.setSelection(1);
    first.mp4BitrateValue.setText("17.25");first.mp4Width.setText("3840");first.mp4Height.setText("2160");
    need(first.mp4Settings.valid()&&first.mp4Settings.requestBitrate()==17250000,"production listeners save decimal options without an Export or Save button");
    Mp4ActivitySettingsHarness rotated=new Mp4ActivitySettingsHarness();rotated.restoreMp4Options();
    need(rotated.mp4Fps.selected==1&&rotated.mp4Codec.selected==1&&rotated.mp4Bitrate.selected==1&&rotated.mp4Resolution.selected==1,"Activity recreation restores all four selectors");
    need(rotated.mp4BitrateValue.value.equals("17.25")&&rotated.mp4Width.value.equals("3840")&&rotated.mp4Height.value.equals("2160"),"recreation retains raw numeric values despite immediate Spinner callbacks");
    rotated.mp4Fps.setSelection(2);
    Mp4ActivitySettingsHarness highRate=new Mp4ActivitySettingsHarness();highRate.restoreMp4Options();
    need(highRate.mp4Fps.selected==2&&highRate.mp4Settings.fps==120,"actual120fps spinner survives Activity recreation without30fps coercion");
    rotated.mp4BitrateValue.setText("");rotated.mp4Width.setText("3841");
    Mp4ActivitySettingsHarness reopened=new Mp4ActivitySettingsHarness();reopened.restoreMp4Options();
    need(reopened.mp4BitrateValue.value.isEmpty()&&reopened.mp4Width.value.equals("3841")&&!reopened.mp4Settings.valid(),"menu reopen retains an unfinished draft and rejects it rather than restoring old valid values");
    reopened.mp4Bitrate.setSelection(0);reopened.mp4Resolution.setSelection(0);
    need(reopened.mp4Settings.valid()&&reopened.mp4Settings.requestBitrate()==0&&reopened.mp4Settings.requestWidth()==0,"automatic modes explicitly request native recommendation and current size");
    reopened.mp4Bitrate.setSelection(1);reopened.mp4Resolution.setSelection(1);
    need(reopened.mp4BitrateValue.value.isEmpty()&&reopened.mp4Width.value.equals("3841")&&!reopened.mp4Settings.valid(),"mode changes preserve hidden custom edits");
    System.out.println("PASS actual Activity MP4 autosave and recreation callbacks");
  }
}''')
    classes = tmp_path / "classes"
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes),
                            str(JAVA / "Mp4ExportSettings.java"), str(preferences), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(classes),
                          "game.qualiarts.idolypride.localserver.Mp4ActivitySettingsHarness"],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS actual Activity MP4 autosave and recreation callbacks"


def test_settings_roundtrip_retains_invalid_drafts_and_exact_numeric_requests(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    harness = tmp_path / "Mp4SettingsHarness.java"
    harness.write_text(r'''package game.qualiarts.idolypride.localserver;
import java.util.*;
public final class Mp4SettingsHarness {
  static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
  static final class Disk implements Mp4ExportSettings.Store {
    final Map<String,String> values=new LinkedHashMap<>();int writes;
    public String read(String key,String fallback){return values.getOrDefault(key,fallback);}
    public void write(Map<String,String> pending){writes++;values.putAll(new LinkedHashMap<>(pending));}
  }
  public static void main(String[]args){
    Disk disk=new Disk();Mp4ExportSettings settings=Mp4ExportSettings.load(disk);
    need(settings.fps==30&&settings.codec==1&&!settings.customBitrate&&!settings.customResolution,"fresh editor uses current-size recommendation");
    need(settings.valid()&&settings.requestBitrate()==0&&settings.requestWidth()==0&&settings.requestHeight()==0,"auto sentinels preserve actual native geometry resolution");
    new Mp4ExportSettings(60,2,true,"17.25",true,"3840","2160").save(disk);
    settings=Mp4ExportSettings.load(disk);
    need(settings.fps==60&&settings.codec==2&&settings.customBitrate&&settings.customResolution,"new Activity restores selectors after recreation or language change");
    need(settings.valid()&&settings.requestBitrate()==17250000&&settings.requestWidth()==3840&&settings.requestHeight()==2160,"numeric preferences reach native request without preset coercion");
    need(disk.writes==1&&disk.values.size()==7,"one edit writes a complete independent editor snapshot");
    new Mp4ExportSettings(120,2,false,"17.25",true,"3840","2160").save(disk);
    settings=Mp4ExportSettings.load(disk);need(settings.fps==120&&settings.codec==2,"120fps survives durable reload");
    need(Mp4ExportSettings.fpsAt(Mp4ExportSettings.fpsPosition(120))==120,"120fps spinner round trip");
    need(Mp4ExportSettings.recommendedBitrate(1920,1080,120,1)==34840000,"120fps recommendation uses twice60fps rate");
    new Mp4ExportSettings(60,2,true,"",true,"3841","").save(disk);
    settings=Mp4ExportSettings.load(disk);
    need(!settings.valid()&&!settings.bitrateValid()&&!settings.resolutionValid(),"unfinished and odd drafts block export");
    need(settings.bitrateMbps.isEmpty()&&settings.width.equals("3841")&&settings.height.isEmpty(),"invalid draft survives reopening instead of silently exporting old settings");
    need(settings.requestBitrate()==-1&&settings.requestWidth()==-1&&settings.requestHeight()==-1,"no invalid draft becomes auto or an old valid value");
    new Mp4ExportSettings(60,2,false,"",false,"3841","").save(disk);
    settings=Mp4ExportSettings.load(disk);
    need(settings.valid()&&settings.requestBitrate()==0&&settings.requestWidth()==0,"selecting automatic modes ignores but preserves hidden custom drafts");
    need(settings.bitrateMbps.isEmpty()&&settings.width.equals("3841"),"mode change never erases an unfinished custom draft");
    need(Mp4ExportSettings.parseBitrate("0.1")==100000&&Mp4ExportSettings.parseBitrate("200")==200000000,"documented bitrate bounds are exact");
    need(Mp4ExportSettings.parseBitrate("1.000001")==1000001,"decimal Mbps maps exactly to whole bps");
    for(String raw:new String[]{"0","0.099999","200.000001","NaN","Infinity","1e2","1,5","1.0000001","-5"," 16","16 ","","1."})
      need(Mp4ExportSettings.parseBitrate(raw)==-1,"malformed, imprecise or out-of-range Mbps is rejected: "+raw);
    for(String raw:new String[]{"16","1920","4096"})need(Mp4ExportSettings.parseEdge(raw)==Integer.parseInt(raw),"valid even pixels "+raw);
    for(String raw:new String[]{"0","15","17","4097","1000000","1e3","1920.0","-1920",""," 1920"})need(Mp4ExportSettings.parseEdge(raw)==-1,"invalid pixels "+raw);
    need(!Mp4ExportSettings.validResolution(0,1080)&&!Mp4ExportSettings.validResolution(1920,0),"mixed auto and explicit dimensions never reach native capture");
    need(Mp4ExportSettings.recommendedBitrate(1920,1080,30,1)==8710000,"H264 uses Elichika .14 and rounds to two-decimal Mbps");
    need(Mp4ExportSettings.recommendedBitrate(1920,1080,60,2)==11200000,"HEVC uses Elichika .09 with selected frame rate");
    need(Mp4ExportSettings.recommendedBitrate(16,16,30,1)==250000,"recommendation minimum is 0.25 Mbps");
    need(Mp4ExportSettings.recommendedBitrate(4096,4096,60,1)==140930000,"largest supported frame stays within native encoder limits");
    need(Mp4ExportSettings.recommendedBitrate(4097,2160,30,1)==-1&&Mp4ExportSettings.recommendedBitrate(1920,1080,90,1)==-1,"unsupported geometry/clock cannot invent a recommendation");
    System.out.println("PASS durable MP4 settings and exact option contract");
  }
}''')
    classes = tmp_path / "classes"
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes),
                            str(JAVA / "Mp4ExportSettings.java"), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([java, "-Xmx128m", "-cp", str(classes),
                          "game.qualiarts.idolypride.localserver.Mp4SettingsHarness"],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "PASS durable MP4 settings and exact option contract"


def test_editor_resources_keep_all_languages_and_validation_units():
    localized = {}
    for folder in ("values", "values-en", "values-ja"):
        root = ET.parse(RES / folder / "strings_mp4.xml").getroot()
        values = {row.attrib["name"]: row.text or "" for row in root}
        assert len(values) == len(root)
        localized[folder] = values
    reference = localized["values"]
    for values in localized.values():
        assert values.keys() == reference.keys()
        assert all(value.strip() for value in values.values())
        assert "200" in values["mp4_bitrate_invalid"] and "Mbps" in values["mp4_bitrate_invalid"]
        assert "4096" in values["mp4_resolution_invalid"]
        for name in reference:
            assert sorted(re.findall(r"%\d+\$[ds]", values[name])) == sorted(re.findall(r"%\d+\$[ds]", reference[name]))
