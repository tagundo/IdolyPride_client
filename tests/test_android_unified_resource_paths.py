"""Run the shipping resource extraction against real filesystem alias cases."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedRuntime.java"


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@pytest.fixture(scope="module")
def resource_host(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = JAVA.read_text()
    actual = "\n".join(method(source, signature) for signature in (
        "private static StructStat regular(", "private static String hash(", "private static File resourceFile(",
    ))
    prefix = r'''
import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.*;
public final class ResourceHost {
 static final int MAX_RESOURCES=4*1024*1024;
 static IllegalStateException invalid(String code){return new IllegalStateException(code);}
 static final class StructStat {
  long st_dev,st_ino,st_nlink,st_size,st_mtime,st_ctime;int st_mode;
 }
 static final class Os {
  static StructStat lstat(String path)throws Exception {
   Map<String,Object> a=Files.readAttributes(Path.of(path),"unix:*",LinkOption.NOFOLLOW_LINKS);
   StructStat s=new StructStat();s.st_dev=((Number)a.get("dev")).longValue();s.st_ino=((Number)a.get("ino")).longValue();
   s.st_nlink=((Number)a.get("nlink")).longValue();s.st_size=((Number)a.get("size")).longValue();
   s.st_mode=((Number)a.get("mode")).intValue();s.st_mtime=((FileTime)a.get("lastModifiedTime")).toMillis();
   s.st_ctime=((FileTime)a.get("ctime")).toMillis();return s;
  }
 }
 static final class OsConstants {
  static boolean S_ISREG(int mode){return (mode&0xf000)==0x8000;}
  static boolean S_ISDIR(int mode){return (mode&0xf000)==0x4000;}
 }
 static final class JSONObject {
  final Map<String,Object> entries=new HashMap<>();
  JSONObject put(String key,Object value){entries.put(key,value);return this;}
  JSONObject getJSONObject(String key){return (JSONObject)entries.get(key);}
  String getString(String key){return (String)entries.get(key);}
  long getLong(String key){return ((Number)entries.get(key)).longValue();}
 }
 static final class Assets {
  final byte[] bytes;int opens=0;
  Assets(byte[] bytes){this.bytes=bytes;}
  InputStream open(String path){assert path.equals("idoly-unified/server-resources.apk");++opens;return new ByteArrayInputStream(bytes);}
 }
 static final class Context {
  final File root;final Assets assets;
  Context(File root,byte[] bytes){this.root=root;this.assets=new Assets(bytes);}
  File getCodeCacheDir(){return root;}Assets getAssets(){return assets;}
 }
'''
    driver = r'''
 public static void main(String[]args)throws Exception {
  String mode=args[0];Path base=Path.of(args[1]);Files.createDirectories(base);
  Path real=base.resolve("real-cache");Files.createDirectories(real);
  Path selected=real;
  if(mode.equals("trusted-root-alias")){selected=base.resolve("code-cache-alias");Files.createSymbolicLink(selected,real);}
  byte[] bytes=new byte[]{1,3,5,7,9};Context context=new Context(selected.toFile(),bytes);
  String digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
  JSONObject value=new JSONObject().put("resource_pack",new JSONObject().put("sha256",digest)
    .put("bytes",bytes.length).put("asset","idoly-unified/server-resources.apk"));
  Path child=real.resolve("idoly-unified-resources");
  String rejection=null;
  if(mode.equals("child-symlink")){
   Path outside=base.resolve("outside");Files.createDirectories(outside);Files.createSymbolicLink(child,outside);
   rejection="unified_resource_directory_invalid";
  }else if(mode.equals("child-file")){
   Files.write(child,bytes);rejection="unified_resource_directory_invalid";
  }else if(mode.equals("target-symlink")||mode.equals("target-hardlink")||mode.equals("tampered-target")){
   Files.createDirectories(child);Path target=child.resolve(digest+".apk");
   if(mode.equals("tampered-target")){Files.write(target,new byte[]{9,7,5,3,1});rejection="unified_resource_hash_differs";}
   else {Path external=base.resolve("external.apk");Files.write(external,bytes);
    if(mode.equals("target-symlink"))Files.createSymbolicLink(target,external);else Files.createLink(target,external);
    rejection="unified_resource_file_invalid";
   }
  }
  if(rejection!=null){
   try{resourceFile(context,value);throw new AssertionError("accepted "+mode);}
   catch(IllegalStateException e){assert e.getMessage().equals(rejection):e.getMessage();}
   assert context.assets.opens==0;return;
  }
  File target=resourceFile(context,value);
  assert target.toPath().equals(child.resolve(digest+".apk"));
  assert Arrays.equals(Files.readAllBytes(target.toPath()),bytes)&&context.assets.opens==1;
  assert resourceFile(context,value).equals(target)&&context.assets.opens==1;
  try(var files=Files.list(child)){assert files.count()==1;}
 }
}
'''
    folder = tmp_path_factory.mktemp("unified-resource-host")
    test = folder / "ResourceHost.java"
    test.write_text(prefix + actual + driver)
    compiled = subprocess.run([javac, str(test)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return java, folder


@pytest.mark.parametrize("mode", [
    "ordinary", "trusted-root-alias", "child-symlink", "child-file", "target-symlink", "target-hardlink", "tampered-target",
])
def test_actual_resource_directory_alias_and_cache_integrity(resource_host, tmp_path, mode):
    java, classes = resource_host
    run = subprocess.run([java, "-ea", "-cp", str(classes), "ResourceHost", mode, str(tmp_path)],
                         capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stdout + run.stderr
