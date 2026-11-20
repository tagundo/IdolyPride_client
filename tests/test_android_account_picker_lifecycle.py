"""Exercise the production picker lifecycle against a single-worker JVM seam.

Android delivers a document result around onStart; a status read must not take
the account worker before the selected ZIP can be saved or inspected.
"""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java"


def block(source, marker):
    begin = source.index(marker)
    cursor = source.index("{", begin) + 1
    depth = 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[begin:cursor]


def test_document_action_is_restored_before_start_and_uses_one_launcher():
    source = ACTIVITY.read_text()
    create = block(source, "    @Override public void onCreate(")
    saved = block(source, "    @Override protected void onSaveInstanceState(")
    assert 'pendingAccountPicker = restoredAccountPicker(savedInstanceState.getInt("account_picker", 0));' in create
    assert 'state.putInt("account_picker", pendingAccountPicker);' in saved
    assert source.count("openAccountDocumentPicker(picker, IMPORT_ACCOUNT);") == 1
    assert source.count("openAccountDocumentPicker(picker, EXPORT_ACCOUNT);") == 1
    result = block(source, "        if (requestCode == EXPORT_ACCOUNT || requestCode == IMPORT_ACCOUNT) {")
    assert result.index("pendingAccountPicker = 0;") < result.index("ServerService.previewAccountDocument")
    assert result.index("pendingAccountPicker = 0;") < result.index("ServerService.saveAccountDocument")


def test_real_lifecycle_reserves_worker_for_export_import_cancel_and_recreation(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The required picker lifecycle harness needs a JDK"
    source = ACTIVITY.read_text()
    actual = "\n".join(block(source, marker) for marker in (
        "    private static int restoredAccountPicker(",
        "    private void openAccountDocumentPicker(",
        "    @Override protected void onStart(",
    ))
    result = block(source, "        if (requestCode == EXPORT_ACCOUNT || requestCode == IMPORT_ACCOUNT) {")
    harness = r'''
import java.util.*;
class Parent { protected void onStart() {} }
public final class PickerLifecycleHarness extends Parent {
 static final int EXPORT_ACCOUNT=50055,IMPORT_ACCOUNT=50056,RESULT_OK=-1;
 int pendingAccountPicker,statusReads,pickerCalls;boolean launchFails,presentationObserved;
 String error;JSONObject pendingAccountExport;
 final FakeView playbackStatus=new FakeView(),officialStatus=new FakeView(),accountOperation=new FakeView(),mp4Status=new FakeView();
 final Runnable playbackRefresh=()->{},officialRefresh=()->{},mp4Refresh=()->{};
 static final class UnifiedMP4Export { static void observe(Runnable observer) {} }
 static final class FakeView {
  void removeCallbacks(Runnable callback) {} void post(Runnable callback) {} void setText(int value) {}
 }
 static final class R { static final class string { static final int accounts_working=1; } }
 static final class Intent { Object uri=new Object();Object getData(){return uri;} }
 static final class JSONObject {
  final String path;JSONObject(String value){path=value;}String optString(String name){return path;}
 }
 static final class ServerService {
  static boolean busy;static int saves,previews,discards;static JSONObject receipt;
  static boolean isManagingAccounts(){return busy;}
  static void observe(Object observer){}
  static void begin(){check(!busy,"document result rejected by competing status read");busy=true;}
  static void saveAccountDocument(Object context,Object uri,JSONObject value,Object callback){begin();saves++;receipt=value;}
  static void previewAccountDocument(Object context,Object uri,Object callback){begin();previews++;}
  static void discardAccountDocument(Object context,String path){discards++;}
 }
 Object getApplicationContext(){return this;}Object accountCallback(String action){return action;}
 void accountError(String value){error=value;}void updateAccountControls(){}void refreshEventSettings(boolean value){}
 void refreshAccounts(){check(!ServerService.busy,"duplicate worker refresh");statusReads++;ServerService.busy=true;}
 void startActivityForResult(Intent picker,int action){
  check(pendingAccountPicker==action,"picker was not reserved before launch");
  pickerCalls++;if(launchFails)throw new IllegalStateException();
 }
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 __ACTUAL__
 void receive(int requestCode,int resultCode,Intent data){__RESULT__}
 static PickerLifecycleHarness fresh(){ServerService.busy=false;return new PickerLifecycleHarness();}
 public static void main(String[] args){
  PickerLifecycleHarness export=fresh();JSONObject receipt=new JSONObject("owned-export");export.pendingAccountExport=receipt;
  export.openAccountDocumentPicker(new Intent(),EXPORT_ACCOUNT);export.onStart();
  check(export.statusReads==0,"onStart consumed worker before export result");
  export.receive(EXPORT_ACCOUNT,RESULT_OK,new Intent());
  check(export.pendingAccountPicker==0&&ServerService.saves==1&&ServerService.receipt==receipt,"export receipt lost");
  export.onStart();check(export.statusReads==0,"refresh competed with active save");
  ServerService.busy=false;export.onStart();check(export.statusReads==1,"normal refresh did not resume");

  PickerLifecycleHarness imported=fresh();imported.openAccountDocumentPicker(new Intent(),IMPORT_ACCOUNT);
  imported.receive(IMPORT_ACCOUNT,RESULT_OK,new Intent());imported.onStart();
  check(imported.pendingAccountPicker==0&&ServerService.previews==1&&imported.statusReads==0,"result-before-start import race");

  for(int action:new int[]{EXPORT_ACCOUNT,IMPORT_ACCOUNT}){
   PickerLifecycleHarness recreated=fresh();recreated.pendingAccountPicker=restoredAccountPicker(action);
   recreated.onStart();check(recreated.statusReads==0,"restored pending picker was refreshed");
   if(action==EXPORT_ACCOUNT)recreated.pendingAccountExport=new JSONObject("owned-export");
   recreated.receive(action,0,null);
   check(recreated.pendingAccountPicker==0&&recreated.statusReads==1,"canceled picker did not recover refresh");
   check(action!=EXPORT_ACCOUNT||recreated.pendingAccountExport==null,"canceled export retained receipt");
  }
  PickerLifecycleHarness noUri=fresh();noUri.pendingAccountPicker=IMPORT_ACCOUNT;
  Intent missing=new Intent();missing.uri=null;noUri.receive(IMPORT_ACCOUNT,RESULT_OK,missing);
  check(noUri.pendingAccountPicker==0&&noUri.statusReads==1,"missing URI retained picker marker");
  PickerLifecycleHarness failed=fresh();failed.launchFails=true;
  failed.openAccountDocumentPicker(new Intent(),IMPORT_ACCOUNT);
  check(failed.pendingAccountPicker==0&&"account_picker_unavailable".equals(failed.error),"launch failure did not clear marker");
  failed.onStart();check(failed.statusReads==1,"failed picker blocked later refresh");
  check(restoredAccountPicker(0)==0&&restoredAccountPicker(-1)==0&&restoredAccountPicker(999)==0,"unknown restored action accepted");
  System.out.println("PASS picker lifecycle");
 }
}
'''.replace("__ACTUAL__", actual).replace("__RESULT__", result)
    path = tmp_path / "PickerLifecycleHarness.java"
    path.write_text(harness)
    subprocess.run([javac, str(path)], check=True, capture_output=True, text=True, timeout=30)
    completed = subprocess.run([java, "-cp", str(tmp_path), "PickerLifecycleHarness"],
                               check=True, capture_output=True, text=True, timeout=30)
    assert completed.stdout.strip() == "PASS picker lifecycle"
