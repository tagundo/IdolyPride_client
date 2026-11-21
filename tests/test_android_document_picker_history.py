"""Execute the bounded, persisted document-origin diagnostic policy on the JVM."""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/DocumentPickerHistory.java"


def test_real_document_history_is_bounded_fixed_and_has_no_uri_or_path_inputs(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java
    source = tmp_path / "DocumentHistoryHarness.java"
    source.write_text(r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.util.*;
public final class DocumentHistoryHarness {
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
 static final class Store implements DocumentPickerHistory.Store {
  String value="";boolean fail;int writes;
  public String read(){return value;}
  public void write(String value){writes++;if(fail)throw new IllegalStateException("unavailable");this.value=value;}
 }
 static String forged(int count,String action,String mime,String origin,boolean trailing)throws Exception {
  ByteArrayOutputStream bytes=new ByteArrayOutputStream();
  try(DataOutputStream output=new DataOutputStream(bytes)){
   output.writeInt(1);output.writeInt(count);
   if(count==1){output.writeInt(50057);output.writeUTF("launch");output.writeUTF(action);output.writeUTF(mime);output.writeUTF(origin);output.writeUTF("requested");}
   if(trailing)output.writeByte(1);
  }
  return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray());
 }
 public static void main(String[]args)throws Exception {
  String create="android.intent.action.CREATE_DOCUMENT",open="android.intent.action.OPEN_DOCUMENT";
  Store store=new Store();DocumentPickerHistory history=new DocumentPickerHistory(store);
  history.launch(50057,create,"video/mp4","mp4_save");history.result(50057,"cancelled");
  List<DocumentPickerHistory.Event> events=history.snapshot();need(events.size()==2,"launch and cancel recorded separately");
  DocumentPickerHistory.Event cancelled=events.get(1);
  need(cancelled.request==50057&&cancelled.event.equals("result")&&cancelled.result.equals("cancelled")&&cancelled.origin.equals("mp4_save")&&cancelled.mime.equals("video/mp4"),"a cancellation retains the exact fixed launch identity");
  need(new DocumentPickerHistory(store).snapshot().size()==2,"last observations survive a new process instance");
  int writes=store.writes;
  for(String unsafe:new String[]{"content://private/document/1","/data/user/0/private","video/mp4\nprivate","unknown"}){
   history.launch(50057,unsafe,"video/mp4","mp4_save");history.launch(50057,create,unsafe,"mp4_save");history.launch(50057,create,"video/mp4",unsafe);
  }
  history.launch(50057,create,"application/zip","account_export");history.result(50051,"ok");history.result(50058,"ok");history.result(50057,"/private/result");
  need(history.snapshot().size()==2&&store.writes==writes,"unsafe values and colliding unrelated request IDs never enter diagnostics");
  String[] origins={"diagnostics_export","resource_export","resource_import","account_export","account_import","mp4_save"};
  for(int round=0;round<3;round++)for(int request=50052;request<=50057;request++){
   String action=request==50054||request==50056?open:create,mime=request==50052?"application/json":request==50057?"video/mp4":"application/zip";
   history.launch(request,action,mime,origins[request-50052]);history.result(request,"ok");
  }
  need(history.snapshot().size()==8&&new DocumentPickerHistory(store).snapshot().size()==8,"the ring stays at the exact last eight events before and after persistence");
  history.snapshot().clear();need(history.snapshot().size()==8,"callers cannot mutate diagnostic state through a snapshot");
  for(String invalid:new String[]{"!", "x".repeat(8193),forged(-1,create,"video/mp4","mp4_save",false),forged(9,create,"video/mp4","mp4_save",false),
    forged(1,create,"video/mp4","/private/origin",false),forged(1,create,"application/zip","account_export",false),forged(1,create,"video/mp4","mp4_save",true)}){
   Store corrupt=new Store();corrupt.value=invalid;need(new DocumentPickerHistory(corrupt).snapshot().isEmpty(),"untrusted or malformed retained diagnostics fail closed");
  }
  Store unavailable=new Store();unavailable.fail=true;DocumentPickerHistory optional=new DocumentPickerHistory(unavailable);
  for(int index=0;index<20;index++)optional.result(50057,"unavailable");
  need(optional.snapshot().size()==8&&optional.snapshot().get(0).origin.equals("unknown"),"failed optional persistence neither fabricates a launch source nor grows unbounded");
  System.out.println("PASS fixed bounded document origins");
 }
}''')
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(JAVA), str(source)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes), "game.qualiarts.idolypride.localserver.DocumentHistoryHarness"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS fixed bounded document origins"
