package game.qualiarts.idolypride.localserver;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
final class PresentationFailurePolicyHostTest {
 static int checks;
 static void eq(Object expected,Object actual) {checks++; if(!expected.equals(actual)) throw new AssertionError("Expected "+expected+" but got "+actual);}
 static final class SecretException extends Exception { SecretException(){super("/data/user/0/account secret-token");} }
 interface CheckedAction { void run() throws Exception; }
 static void rejects(String reason,CheckedAction action) throws Exception {
  try { action.run(); throw new AssertionError("Expected rejection: "+reason); }
  catch(PresentationAddonInstaller.ExistingApkException error) {eq(reason,error.reason);}
 }
 static void existingPlanChecks() throws Exception {
  Path dir=Files.createTempDirectory("presentation-existing-apks-");
  try {
   Path base=dir.resolve("base.apk"); Path feature=dir.resolve("feature.apk");
   Files.write(base,new byte[10]); Files.write(feature,new byte[7]);
   String b=base.toString(),f=feature.toString();
   eq("split_config.en.apk",PresentationAddonInstaller.ExistingApkPolicy.sessionName("config.en"));
   eq("split_config.arm64_v8a.apk",PresentationAddonInstaller.ExistingApkPolicy.sessionName("config.arm64_v8a"));
   eq(true,PresentationAddonInstaller.ExistingApkPolicy.sessionName("../escape")==null);
   eq(true,PresentationAddonInstaller.ExistingApkPolicy.sessionName("a/escape")==null);
   eq(true,PresentationAddonInstaller.ExistingApkPolicy.sessionName("a".repeat(101))==null);
   eq(false,PresentationAddonInstaller.ExistingApkPolicy.validFileSize(0));
   eq(false,PresentationAddonInstaller.ExistingApkPolicy.validFileSize(-1));
   eq(true,PresentationAddonInstaller.ExistingApkPolicy.validFileSize(256L*1024*1024));
   eq(false,PresentationAddonInstaller.ExistingApkPolicy.validFileSize(256L*1024*1024+1));
   eq(-1L,PresentationAddonInstaller.ExistingApkPolicy.addSize(Long.MAX_VALUE,1));
   eq(-1L,PresentationAddonInstaller.ExistingApkPolicy.addSize(512L*1024*1024,1));
   eq(512L*1024*1024,PresentationAddonInstaller.ExistingApkPolicy.addSize(256L*1024*1024,256L*1024*1024));
   String[] names={"feature","idoly_presentation"};
   String[] paths={f,dir.resolve("excluded-old-feature-does-not-need-reading.apk").toString()};
   PresentationAddonInstaller.ExistingPlan plan=PresentationAddonInstaller.ExistingApkPolicy.plan(b,names,paths,100);
   eq(2,plan.files.size()); eq(117L,plan.sessionBytes);
   eq("base.apk",plan.files.get(0).sessionName); eq("split_feature.apk",plan.files.get(1).sessionName);
   eq(true,plan.samePaths(b,names,paths));
   String[] originalNames=names.clone(),originalPaths=paths.clone();
   names[0]="changed"; paths[0]=b;
   eq(true,plan.samePaths(b,originalNames,originalPaths)); eq(false,plan.samePaths(b,names,paths));
   try {plan.files.clear(); throw new AssertionError("Plan must be immutable");}
   catch(UnsupportedOperationException expected){checks++;}
   eq(true,plan.files.get(0).unchanged()); Files.write(base,new byte[11]); eq(false,plan.files.get(0).unchanged());
   Files.write(base,new byte[10]);
   eq(1,PresentationAddonInstaller.ExistingApkPolicy.plan(b,null,null,1).files.size());
   rejects("split_layout_mismatch",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"feature"},null,1));
   rejects("existing_apk_duplicate",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"feature","feature"},new String[]{f,f},1));
   rejects("existing_apk_duplicate",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"feature","other"},new String[]{f,f},1));
   rejects("existing_apk_duplicate",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"feature"},new String[]{b},1));
   rejects("existing_apk_name_invalid",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"../escape"},new String[]{f},1));
   rejects("existing_apk_missing",()->PresentationAddonInstaller.ExistingApkPolicy.plan(dir.toString(),null,null,1));
   rejects("existing_apk_missing",()->PresentationAddonInstaller.ExistingApkPolicy.plan(dir.resolve("missing").toString(),null,null,1));
   rejects("existing_apk_missing",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[]{"feature"},new String[]{null},1));
   rejects("existing_apk_total_limit",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,null,null,0));
   rejects("existing_apk_total_limit",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,null,null,1024*1024+1));
   rejects("existing_apk_count_limit",()->PresentationAddonInstaller.ExistingApkPolicy.plan(b,new String[33],new String[33],1));
   String[] maxNames=new String[32],maxPaths=new String[32];
   for(int i=0;i<32;i++){Path split=dir.resolve("split"+i+".apk");Files.write(split,new byte[]{1});maxNames[i]="part"+i;maxPaths[i]=split.toString();}
   eq(33,PresentationAddonInstaller.ExistingApkPolicy.plan(b,maxNames,maxPaths,1).files.size());
   Path big=dir.resolve("big.apk"),big2=dir.resolve("big2.apk");
   try(RandomAccessFile file=new RandomAccessFile(big.toFile(),"rw")){file.setLength(256L*1024*1024);}
   try(RandomAccessFile file=new RandomAccessFile(big2.toFile(),"rw")){file.setLength(256L*1024*1024);}
   eq(256L*1024*1024+1,PresentationAddonInstaller.ExistingApkPolicy.plan(big.toString(),null,null,1).sessionBytes);
   rejects("existing_apk_total_limit",()->PresentationAddonInstaller.ExistingApkPolicy.plan(big.toString(),new String[]{"feature"},new String[]{big2.toString()},1));
   try(RandomAccessFile file=new RandomAccessFile(big.toFile(),"rw")){file.setLength(256L*1024*1024+1);}
   rejects("existing_apk_size_limit",()->PresentationAddonInstaller.ExistingApkPolicy.plan(big.toString(),null,null,1));
   eq("existing_apk_copy",PresentationAddonInstaller.FailurePolicy.stage("existing_apk_copy"));
   eq("android_result",PresentationAddonInstaller.FailurePolicy.stage("android_result"));
  } finally {
   try(var files=Files.walk(dir)){for(Path path:files.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}
  }
 }
 public static void main(String[] args) throws Exception {
  eq("",PresentationAddonInstaller.FailurePolicy.installToken(null));
  eq("INSTALL_FAILED_INVALID_APK",PresentationAddonInstaller.FailurePolicy.installToken("/data/private/account: INSTALL_FAILED_INVALID_APK: secret"));
  eq("",PresentationAddonInstaller.FailurePolicy.installToken("account /data/user/0/private"));
  eq("",PresentationAddonInstaller.FailurePolicy.installToken("prefixINSTALL_FAILED_INVALID_APK"));
  eq("",PresentationAddonInstaller.FailurePolicy.installToken("INSTALL_FAILED_INVALID_APKsuffix"));
  eq("",PresentationAddonInstaller.FailurePolicy.installToken("INSTALL_"+"A".repeat(65)));
  eq("",PresentationAddonInstaller.FailurePolicy.installToken("x".repeat(4100)+" INSTALL_FAILED_INVALID_APK"));
  eq("native_library_extract_failed",PresentationAddonInstaller.FailurePolicy.osReason("Failed to extract native libraries, res=-2 /private/path"));
  eq("abi_mismatch",PresentationAddonInstaller.FailurePolicy.osReason("INSTALL_FAILED_NO_MATCHING_ABIS: No matching ABIs"));
  eq("storage_insufficient",PresentationAddonInstaller.FailurePolicy.osReason("Insufficient storage at /private/path"));
  eq("signer_mismatch",PresentationAddonInstaller.FailurePolicy.osReason("Signatures do not match /private/name"));
  eq("user_rejected",PresentationAddonInstaller.FailurePolicy.osReason("User cancelled install"));
  eq("os_rejected",PresentationAddonInstaller.FailurePolicy.osReason("/private/account anything else"));
  eq("libil2cpp.so",PresentationAddonInstaller.FailurePolicy.publicMember("lib/arm64-v8a/libil2cpp.so"));
  eq("libshadowhook.so",PresentationAddonInstaller.FailurePolicy.publicMember("libshadowhook.so"));
  eq("",PresentationAddonInstaller.FailurePolicy.publicMember("/data/user/0/account/libil2cpp.so"));
  eq("",PresentationAddonInstaller.FailurePolicy.publicMember("lib/arm64-v8a/unknown.so"));
  eq("a".repeat(12),PresentationAddonInstaller.FailurePolicy.shortSha("a".repeat(64)));
  eq("",PresentationAddonInstaller.FailurePolicy.shortSha("a".repeat(63)));
  eq("",PresentationAddonInstaller.FailurePolicy.shortSha("secret"));
  eq("unknown",PresentationAddonInstaller.FailurePolicy.stage("/private/account"));
  eq("unknown",PresentationAddonInstaller.FailurePolicy.reason("raw secret message"));
  eq("OtherException",PresentationAddonInstaller.FailurePolicy.exceptionClass("SecretException"));
  eq("IOException",PresentationAddonInstaller.FailurePolicy.exceptionClass("IOException"));
  eq("stale_session",PresentationAddonInstaller.FailurePolicy.reason("stale_session"));
  eq("session_interrupted",PresentationAddonInstaller.FailurePolicy.reason("session_interrupted"));
  eq("confirmation_missing",PresentationAddonInstaller.FailurePolicy.reason("confirmation_missing"));
  eq("confirmation_start_failed",PresentationAddonInstaller.FailurePolicy.reason("confirmation_start_failed"));
  PresentationAddonInstaller.Failure f=PresentationAddonInstaller.FailurePolicy.make("callback","native_library_extract_failed",new IOException("/data/user/0/account secret"),"lib/arm64-v8a/libil2cpp.so","a".repeat(64),"b".repeat(64),5,-2,"INSTALL_FAILED_INVALID_APK /private/user");
  eq(5,f.status); eq(-2,f.legacyStatus); eq("IOException",f.exceptionClass); eq("a".repeat(12),f.expectedSha); eq("b".repeat(12),f.actualSha); eq("INSTALL_FAILED_INVALID_APK",f.installToken);
  String joined=f.stage+f.reason+f.exceptionClass+f.member+f.expectedSha+f.actualSha+f.installToken;
  eq(false,joined.contains("secret")); eq(false,joined.contains("/private")); eq(false,joined.contains("/data"));
  eq("OtherException",PresentationAddonInstaller.FailurePolicy.make("callback","os_rejected",new SecretException(),null,null,null,1,-2,null).exceptionClass);
  existingPlanChecks();
  System.out.println("PASS: "+checks+" failure-policy and existing-APK semantic checks; no Android runtime needed.");
 }
}
