"""Run the real completed-output registry against durable and unsafe file fixtures."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.localserver"
SOURCE = ROOT / "android-server/app/src/main/java" / PACKAGE.replace(".", "/") / "Mp4CompletedExports.java"


HARNESS = r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.nio.file.*;import java.nio.file.attribute.FileTime;import java.nio.file.attribute.PosixFilePermissions;import java.util.*;
public final class CompletedExportsHarness {
 static final byte[] VIDEO=new byte[]{8,6,7,5,3,0,9};
 static void need(boolean value,String message){if(!value)throw new AssertionError(message);}
 interface Action {void run()throws Exception;}
 static void rejected(Action action,String message)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError(message);}
 static final class Store implements Mp4CompletedExports.Store {
  Set<String> saved=new LinkedHashSet<>();boolean fail;int writes;
  public Set<String> read(){return new LinkedHashSet<>(saved);}
  public boolean write(Set<String> rows){writes++;if(fail)return false;saved=new LinkedHashSet<>(rows);return true;}
 }
 static File directory(File parent,String name)throws Exception{File result=new File(parent,name).getCanonicalFile();need(result.mkdir(),"fresh fixture directory");return result;}
 static File video(File root,String id)throws Exception{File result=new File(root,id+".mp4");Files.write(result.toPath(),VIDEO);return result;}
 static Set<String> ids(Mp4CompletedExports registry){Set<String> result=new TreeSet<>();for(Mp4CompletedExports.Entry entry:registry.entries())result.add(entry.outputId);return result;}
 static void unchanged(File file)throws Exception{need(Arrays.equals(Files.readAllBytes(file.toPath()),VIDEO),"registry operations preserve source bytes: "+file.getName());}
 static String record(int type,String root,String id,String job,boolean trailing)throws Exception{
  ByteArrayOutputStream bytes=new ByteArrayOutputStream();
  try(DataOutputStream output=new DataOutputStream(bytes)){
   output.writeInt(type);if(root!=null)output.writeUTF(root);
   if(type==1){output.writeUTF(id);output.writeUTF(job==null?"":job);}
   if(trailing)output.writeByte(42);
  }
  return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray());
 }
 static void publishedAfterKill(File files)throws Exception{
  Store store=new Store();File one=directory(files,"trusted-one-shot"),queue=directory(files,"unregistered-queue");
  Mp4CompletedExports before=new Mp4CompletedExports(files,store);
  need(before.rememberDirectory(one)&&!store.saved.isEmpty(),"trusted one-shot root is persisted before capture");
  need(before.entries().isEmpty(),"registering an empty root fabricates no completed output");
  // The native producer atomically publishes a final file, then the process
  // dies before Java observes completion or writes an individual bookmark.
  Path partial=new File(one,"first.partial.mp4").toPath();Files.write(partial,VIDEO);
  File first=new File(one,"first.mp4");Files.move(partial,first.toPath(),StandardCopyOption.ATOMIC_MOVE);
  File second=video(one,"second"),unregistered=video(queue,"queue_result");
  Files.setLastModifiedTime(first.toPath(),FileTime.fromMillis(1000));Files.setLastModifiedTime(second.toPath(),FileTime.fromMillis(2000));
  Files.write(new File(one,"unfinished.partial.mp4").toPath(),VIDEO);
  Files.write(new File(one,"empty.mp4").toPath(),new byte[0]);
  Files.write(new File(one,"not-a-video.txt").toPath(),VIDEO);
  Files.write(new File(one,"bad.name.mp4").toPath(),VIDEO);
  Files.createSymbolicLink(new File(one,"linked.mp4").toPath(),first.toPath());
  need(new File(one,"directory.mp4").mkdir(),"directory named as video fixture");
  Mp4CompletedExports restarted=new Mp4CompletedExports(files,store);
  need(ids(restarted).equals(new TreeSet<>(Arrays.asList("first","second"))),"only valid nonempty final regular files in a registered root survive process death");
  need(restarted.entries().get(0).outputId.equals("second"),"multiple completed outputs are ordered newest first");
  for(Mp4CompletedExports.Entry entry:restarted.entries())need(entry.root.equals(one)&&entry.jobId==null,"scan admits only trusted one-shot ownership");
  unchanged(first);unchanged(second);unchanged(unregistered);
  need(!ids(restarted).contains("queue_result"),"an unregistered queue directory is never scanned or adopted");
  need(restarted.remember(one,"first",null)&&restarted.entries().size()==2,"an observed completion deduplicates an already discovered final file");
 }
 static void malformedMetadata(File files)throws Exception{
  Store store=new Store();File valid=directory(files,"valid"),outside=directory(files.getParentFile(),"outside"),lookalike=directory(files.getParentFile(),files.getName()+"-lookalike");
  File validFile=video(valid,"owned"),outsideFile=video(outside,"foreign"),lookalikeFile=video(lookalike,"foreign");
  File alias=new File(files,"alias");Files.createSymbolicLink(alias.toPath(),valid.toPath());
  store.saved.add(record(1,valid.getPath(),"owned",null,false));
  store.saved.add("not!base64");store.saved.add("");store.saved.add(null);store.saved.add("x".repeat(16385));
  store.saved.add(record(99,valid.getPath(),null,null,false));
  store.saved.add(Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[]{0,0,0,1}));
  store.saved.add(Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[]{0,0,0,2}));
  store.saved.add(record(1,valid.getPath(),"owned",null,true));
  store.saved.add(record(2,valid.getPath(),null,null,true));
  store.saved.add(record(1,valid.getPath(),"../foreign",null,false));
  store.saved.add(record(1,valid.getPath(),"owned","../job",false));
  store.saved.add(record(1,outside.getPath(),"foreign",null,false));
  store.saved.add(record(1,lookalike.getPath(),"foreign",null,false));
  store.saved.add(record(1,files.getPath(),"foreign",null,false));
  store.saved.add(record(1,alias.getAbsolutePath(),"owned",null,false));
  store.saved.add(record(2,alias.getAbsolutePath(),null,null,false));
  store.saved.add(record(2,outside.getPath(),null,null,false));
  store.saved.add(record(2,lookalike.getPath(),null,null,false));
  store.saved.add(record(2,new File(valid,"../valid").getAbsolutePath(),null,null,false));
  store.saved.add(record(1,"relative","owned",null,false));
  store.saved.add(record(2,"relative",null,null,false));
  Mp4CompletedExports restored=new Mp4CompletedExports(files,store);
  need(ids(restored).equals(Collections.singleton("owned")),"malformed, corrupt, aliased and outside-root records cannot authorize adoption");
  need(store.writes==0,"loading corrupt metadata never rewrites files or silently claims a durable update");
  unchanged(validFile);unchanged(outsideFile);unchanged(lookalikeFile);
 }
 static void directPathsAndReplacement(File files)throws Exception{
  Store store=new Store();File safe=directory(files,"safe"),outside=directory(files.getParentFile(),"outside");
  File owned=video(safe,"owned"),foreign=video(outside,"foreign"),empty=new File(safe,"empty.mp4");Files.write(empty.toPath(),new byte[0]);
  File alias=new File(files,"aliased-root");Files.createSymbolicLink(alias.toPath(),safe.toPath());
  Files.createSymbolicLink(new File(safe,"linked.mp4").toPath(),foreign.toPath());
  Mp4CompletedExports registry=new Mp4CompletedExports(files,store);
  rejected(()->registry.rememberDirectory(alias),"symlink root registration must fail");
  rejected(()->registry.rememberDirectory(outside),"outside directory registration must fail");
  rejected(()->registry.rememberDirectory(files),"the private root itself is not an export directory");
  rejected(()->registry.remember(safe,"../owned",null),"traversal identity must fail");
  rejected(()->registry.remember(safe,"owned","../job"),"traversal job identity must fail");
  rejected(()->registry.remember(safe,"linked",null),"symlink output must fail");
  rejected(()->registry.remember(safe,"empty",null),"empty output must fail");
  rejected(()->registry.remember(safe,"missing",null),"missing output must fail");
  need(registry.entries().isEmpty()&&store.writes==0,"failed admission never mutates registry ownership");
  need(registry.rememberDirectory(safe),"valid one-shot root can be registered");
  File moved=new File(files,"moved-safe");Files.move(safe.toPath(),moved.toPath());
  Files.createSymbolicLink(safe.toPath(),outside.toPath());
  need(registry.entries().isEmpty(),"a registered root replaced with a symlink cannot authorize an outside file");
  need(new Mp4CompletedExports(files,store).entries().isEmpty(),"rehydration also rejects a replaced root symlink");
  unchanged(new File(moved,"owned.mp4"));unchanged(foreign);
 }
 static void forgetIsMetadataOnly(File files)throws Exception{
  Store store=new Store();File queue=directory(files,"queue-root");File first=video(queue,"first"),second=video(queue,"second");
  Mp4CompletedExports registry=new Mp4CompletedExports(files,store);
  need(registry.remember(queue,"first","job_first")&&registry.remember(queue,"second","job_second"),"known queue completions can be individually bookmarked");
  Mp4CompletedExports reopened=new Mp4CompletedExports(files,store);need(reopened.entries().size()==2,"constructor rehydrates multiple valid individual records");
  need(reopened.forget(new Mp4CompletedExports.Entry(queue,"first","job_first")),"forget persists the metadata removal");
  need(ids(new Mp4CompletedExports(files,store)).equals(Collections.singleton("second")),"unregistered queue root does not rediscover a forgotten queue bookmark");
  unchanged(first);unchanged(second);
  need(reopened.forget(null)&&reopened.forget(new Mp4CompletedExports.Entry(queue,"unknown",null)),"absent metadata removal remains safe");
  unchanged(first);unchanged(second);
 }
 static void failedWritesRetry(File files)throws Exception{
  Store store=new Store();store.fail=true;File queue=directory(files,"queue"),one=directory(files,"one-shot");File output=video(queue,"owned");
  Mp4CompletedExports registry=new Mp4CompletedExports(files,store);
  need(!registry.remember(queue,"owned","job")&&registry.entries().size()==1&&store.saved.isEmpty(),"failed entry write retains live ownership without claiming durability");
  store.fail=false;need(registry.remember(queue,"owned","job")&&store.writes==2,"an unchanged existing entry retries dirty metadata");
  need(new Mp4CompletedExports(files,store).entries().size()==1,"retry survives a fresh registry instance");
  store.fail=true;need(!registry.rememberDirectory(one),"failed trusted directory write is reported");
  store.fail=false;int attempts=store.writes;need(registry.rememberDirectory(one)&&store.writes==attempts+1,"unchanged directory registration retries a failed write");
  File finalOne=video(one,"published_after_retry");need(ids(new Mp4CompletedExports(files,store)).contains("published_after_retry"),"retried directory marker recovers a later atomic final publication");
  store.fail=true;need(!registry.forget(new Mp4CompletedExports.Entry(queue,"owned","job")),"failed forget is reported rather than silently called durable");
  need(ids(new Mp4CompletedExports(files,store)).contains("owned"),"failed removal leaves previously durable metadata intact");
  store.fail=false;need(registry.forget(null),"a subsequent operation retries pending dirty removal");
  need(!ids(new Mp4CompletedExports(files,store)).contains("owned"),"retried metadata removal is durable without scanning queue roots");
  unchanged(output);unchanged(finalOne);
 }
 static File legacy(File parent,String suffix)throws Exception{
  File broker=directory(parent,".idoly-mp4-audio-"+suffix);Files.setPosixFilePermissions(broker.toPath(),PosixFilePermissions.fromString("rwx------"));
  File exports=directory(broker,"exports");Files.setPosixFilePermissions(exports.toPath(),PosixFilePermissions.fromString("rwx------"));return exports;
 }
 static File privateVideo(File root,String id)throws Exception{File file=video(root,id);Files.setPosixFilePermissions(file.toPath(),PosixFilePermissions.fromString("rw-------"));return file;}
 static void strictLegacyMigration(File files)throws Exception{
  Store store=new Store();String validId="1".repeat(32);File valid=legacy(files,"a".repeat(32));File recovered=privateVideo(valid,validId);
  File wrongPrefix=directory(files,".idoly-mp4-audio-wrong");File wrongExports=directory(wrongPrefix,"exports");File wrong=privateVideo(wrongExports,"2".repeat(32));
  File nestedParent=directory(files,"nested");File deep=legacy(nestedParent,"b".repeat(32));File deepFile=privateVideo(deep,"3".repeat(32));
  File modeRoot=legacy(files,"c".repeat(32));File modeFile=privateVideo(modeRoot,"4".repeat(32));Files.setPosixFilePermissions(modeRoot.toPath(),PosixFilePermissions.fromString("rwxr-xr-x"));
  File sourceMode=legacy(files,"d".repeat(32));File publicFile=video(sourceMode,"5".repeat(32));Files.setPosixFilePermissions(publicFile.toPath(),PosixFilePermissions.fromString("rw-r--r--"));
  File hardRoot=legacy(files,"e".repeat(32));File hard=privateVideo(hardRoot,"6".repeat(32));Files.createLink(new File(files,"hard-alias").toPath(),hard.toPath());
  File linkedRoot=legacy(files,"f".repeat(32));Files.createSymbolicLink(new File(linkedRoot,"7".repeat(32)+".mp4").toPath(),recovered.toPath());
  File aliasBroker=new File(files,".idoly-mp4-audio-"+"0".repeat(32));Files.createSymbolicLink(aliasBroker.toPath(),valid.getParentFile().toPath());
  File missing=directory(files,".idoly-mp4-audio-"+"9".repeat(32));Files.setPosixFilePermissions(missing.toPath(),PosixFilePermissions.fromString("rwx------"));
  File unusual=legacy(files,"8".repeat(32));privateVideo(unusual,"bad-name");privateVideo(unusual,"A".repeat(32));
  File empty=new File(unusual,"b".repeat(32)+".mp4");Files.write(empty.toPath(),new byte[0]);Files.setPosixFilePermissions(empty.toPath(),PosixFilePermissions.fromString("rw-------"));
  File nonregular=new File(unusual,"c".repeat(32)+".mp4");need(nonregular.mkdir(),"nonregular legacy output fixture");
  File queue=directory(files,".idoly-mp4-library");File queueExports=directory(queue,"exports");File queued=privateVideo(queueExports,"d".repeat(32));
  Mp4CompletedExports registry=new Mp4CompletedExports(files,store);registry.recoverLegacyOneShots();
  need(ids(registry).equals(Collections.singleton(validId)),"legacy recovery admits only a private regular single-link exact-name final in an exact direct private broker root");
  need(ids(new Mp4CompletedExports(files,store)).equals(Collections.singleton(validId)),"valid legacy recovery persists a durable individual bookmark");
  for(File file:new File[]{recovered,wrong,deepFile,modeFile,publicFile,hard,queued})unchanged(file);
  need(((Number)Files.getAttribute(hard.toPath(),"unix:nlink")).longValue()==2,"legacy rejection never unlinks another alias");
 }
 public static void main(String[]args)throws Exception{
  File files=new File(args[1]).getCanonicalFile();need(files.mkdirs(),"fresh private files fixture");
  switch(args[0]){
   case "published_after_kill":publishedAfterKill(files);break;
   case "malformed_metadata":malformedMetadata(files);break;
   case "unsafe_paths":directPathsAndReplacement(files);break;
   case "metadata_only_forget":forgetIsMetadataOnly(files);break;
   case "failed_write_retry":failedWritesRetry(files);break;
   case "strict_legacy_migration":strictLegacyMigration(files);break;
   default:throw new AssertionError("unknown test case");
  }
  System.out.println("PASS "+args[0]);
 }
}
'''


@pytest.fixture(scope="module")
def registry_java(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "JDK required for real completed-output registry regression"
    directory = tmp_path_factory.mktemp("completed-exports-jvm")
    harness = directory / "CompletedExportsHarness.java"
    harness.write_text(HARNESS)
    classes = directory / "classes"
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(classes), str(SOURCE), str(harness)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    return java, classes


@pytest.mark.parametrize("case", ["published_after_kill", "malformed_metadata", "unsafe_paths",
                                 "metadata_only_forget", "failed_write_retry", "strict_legacy_migration"])
def test_real_completed_registry_durability_and_private_file_ownership(registry_java, tmp_path, case):
    java, classes = registry_java
    executed = subprocess.run([java, "-Xmx128m", "-cp", str(classes), PACKAGE + ".CompletedExportsHarness",
                               case, str(tmp_path / "files")], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS " + case
