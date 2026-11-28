"""Run the shipping bounded exit collector with adversarial owned streams."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/PreviousProcessExits.java"
PACKAGE = "game.qualiarts.idolypride.localserver"


def jdk():
    cached = ROOT.parent / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin"
    javac = cached / "javac" if (cached / "javac").is_file() else shutil.which("javac")
    java = cached / "java" if (cached / "java").is_file() else shutil.which("java")
    if not javac or not java:
        pytest.skip("Host JDK required")
    return str(javac), str(java)


@pytest.fixture(scope="module")
def collector(tmp_path_factory):
    javac, java = jdk()
    folder = tmp_path_factory.mktemp("previous-process-exits")
    files = {
        "android/os/Build.java": "package android.os; public final class Build {public static final class VERSION {public static int SDK_INT=34;}}",
        "android/util/Base64.java": "package android.util; public final class Base64 {public static final int NO_WRAP=2;public static String encodeToString(byte[] bytes,int flags){if(flags!=NO_WRAP)throw new AssertionError();return java.util.Base64.getEncoder().encodeToString(bytes);}}",
        "android/content/Context.java": """package android.content; public class Context {
          public static final String ACTIVITY_SERVICE="activity";public final android.app.ActivityManager manager=new android.app.ActivityManager();
          public Context getApplicationContext(){return this;}public String getPackageName(){return "app.owned.package";}
          public Object getSystemService(String name){if(!name.equals(ACTIVITY_SERVICE))throw new AssertionError();return manager;}}""",
        "android/app/ActivityManager.java": """package android.app;public class ActivityManager {
          public java.util.List<ApplicationExitInfo> records=new java.util.ArrayList<>();public int calls,pid,maximum;public String requestedPackage,thread;
          public java.util.List<ApplicationExitInfo> getHistoricalProcessExitReasons(String name,int p,int n){
            calls++;requestedPackage=name;pid=p;maximum=n;thread=Thread.currentThread().getName();return records;}}""",
        "android/app/ApplicationExitInfo.java": """package android.app;public class ApplicationExitInfo {
          public int reason=5,status=11,pid=1234,importance=100,traceCalls;public long timestamp=123456789000L;
          public String processName="app.owned.package:game";public java.io.InputStream stream;
          public int getReason(){return reason;}public int getStatus(){return status;}public int getPid(){return pid;}
          public int getImportance(){return importance;}public long getTimestamp(){return timestamp;}public String getProcessName(){return processName;}
          public java.io.InputStream getTraceInputStream()throws java.io.IOException{traceCalls++;return stream;}}""",
        "org/json/JSONException.java": "package org.json;public class JSONException extends Exception {private static final long serialVersionUID=1L;}",
        "org/json/JSONObject.java": r'''package org.json;import java.util.*;public class JSONObject {
          public final Map<String,Object> fields=new LinkedHashMap<>();
          public JSONObject put(String key,Object value)throws JSONException{if(key==null)throw new JSONException();fields.put(key,value);return this;}
          static String quote(String value){StringBuilder out=new StringBuilder("\"");for(int i=0;i<value.length();i++){char c=value.charAt(i);
            if(c=='"'||c=='\\')out.append('\\').append(c);else if(c<32)out.append(String.format("\\u%04x",(int)c));else out.append(c);}return out.append('"').toString();}
          static String encode(Object value){return value==null?"null":value instanceof String?quote((String)value):value.toString();}
          public String toString(){StringJoiner out=new StringJoiner(",","{","}");fields.forEach((k,v)->out.add(quote(k)+":"+encode(v)));return out.toString();}}''',
        "org/json/JSONArray.java": """package org.json;import java.util.*;public class JSONArray {
          public final List<Object> values=new ArrayList<>();public JSONArray put(Object value){values.add(value);return this;}
          public String toString(){StringJoiner out=new StringJoiner(",","[","]");for(Object value:values)out.add(JSONObject.encode(value));return out.toString();}}""",
        PACKAGE.replace(".", "/") + "/PreviousProcessExits.java": SOURCE.read_text(),
        PACKAGE.replace(".", "/") + "/ExitCollectorHost.java": r'''package game.qualiarts.idolypride.localserver;
import java.io.*;import java.util.*;import java.util.concurrent.*;import java.util.concurrent.atomic.*;import org.json.*;
public final class ExitCollectorHost {
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 static final class Stream extends InputStream {
  final int length;int position,reads;final AtomicInteger closes=new AtomicInteger();
  boolean failClose,zero;CountDownLatch readGate,closeGate;
  Stream(int length){this.length=length;}
  public int read(){throw new AssertionError("bounded bulk reads only");}
  public int read(byte[] target,int offset,int count)throws IOException{
   check(count>0&&count<=4096,"bounded read request");reads++;
   if(readGate!=null)awaitIgnoringInterrupts(readGate);
   if(zero)return 0;if(position>=length)return -1;int n=Math.min(count,length-position);
   for(int i=0;i<n;i++)target[offset+i]=(byte)((position+i)%256);position+=n;return n;
  }
  public void close()throws IOException{closes.incrementAndGet();if(readGate!=null)readGate.countDown();if(closeGate!=null)awaitIgnoringInterrupts(closeGate);if(failClose)throw new IOException("sensitive-provider-path");}
 }
 static void awaitIgnoringInterrupts(CountDownLatch latch){while(true)try{latch.await();return;}catch(InterruptedException ignored){}}
 static final class Record implements PreviousProcessExits.ExitRecord {
  final Stream stream;int traceCalls;boolean failOpen;Record(Stream stream){this.stream=stream;}
  public int reason(){return 5;}public int status(){return 11;}public long timestamp(){return 123456789000L;}
  public int importance(){return 100;}public int pid(){return 1234;}public String processName(){return "app.owned.package:game";}
  public InputStream trace()throws IOException{traceCalls++;if(failOpen)throw new IOException("sensitive-provider-path");return stream;}
 }
 static JSONObject envelope(JSONObject document,Stream stream)throws Exception{
  return new JSONObject().put("diagnostic",document).put("reads",stream==null?0:stream.reads).put("consumed",stream==null?0:stream.position).put("closes",stream==null?0:stream.closes.get());
 }
 public static void main(String[] args)throws Exception{
  String mode=args[0];PreviousProcessExits.Collector collector=new PreviousProcessExits.Collector();
  if(mode.equals("platform")||mode.equals("older")){
   android.content.Context context=new android.content.Context();android.os.Build.VERSION.SDK_INT=mode.equals("older")?29:34;
   android.app.ApplicationExitInfo nativeExit=new android.app.ApplicationExitInfo();nativeExit.stream=new Stream(9);context.manager.records.add(nativeExit);
   android.app.ApplicationExitInfo anr=new android.app.ApplicationExitInfo();anr.reason=6;anr.stream=new Stream(7);context.manager.records.add(anr);
   android.app.ApplicationExitInfo other=new android.app.ApplicationExitInfo();other.reason=3;other.stream=new Stream(1);context.manager.records.add(other);
   JSONObject result=PreviousProcessExits.collect(context);
   if(mode.equals("older"))check(context.manager.calls==0,"unsupported API must not touch ActivityManager");
   else{check(context.manager.calls==1&&context.manager.requestedPackage.equals(context.getPackageName())&&context.manager.pid==0&&context.manager.maximum==5,"query only this package, all its PIDs, maximum5");
     check(context.manager.thread.equals("previous-process-exits"),"platform query off main/export worker");check(other.traceCalls==0,"unrelated reasons do not open trace");}
   System.out.println(result);return;
  }
  if(mode.equals("bounded")){
   List<Record> records=new ArrayList<>();for(int i=0;i<8;i++)records.add(new Record(new Stream(500000)));
   JSONObject result=collector.collect(maximum->{check(maximum==5,"request maximum5");return new ArrayList<PreviousProcessExits.ExitRecord>(records);},34,2000);
   for(int i=0;i<8;i++){Stream stream=records.get(i).stream;check(stream.position==(i<5?131072:0)&&stream.closes.get()==(i<5?1:0),"five records, exact read bound and single close");}
   System.out.println(result);return;
  }
  if(mode.equals("query_error")){
   System.out.println(collector.collect(maximum->{throw new SecurityException("sensitive-device-details");},34,500));return;
  }
  if(mode.equals("blocked_query")){
   CountDownLatch release=new CountDownLatch(1);AtomicInteger calls=new AtomicInteger();long started=System.nanoTime();
   JSONObject result=collector.collect(maximum->{calls.incrementAndGet();awaitIgnoringInterrupts(release);return Collections.emptyList();},34,300);
   check(TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-started)<1500,"query timeout does not block export");
   JSONObject second=collector.collect(maximum->{throw new AssertionError("a stuck query must not spawn another");},34,300);
   check(calls.get()==1,"one outstanding query");release.countDown();
   System.out.println(new JSONObject().put("first",result).put("second",second));return;
  }
  Stream stream=new Stream(mode.equals("null_stream")||mode.equals("blocked_close")?0:4);Record record=new Record(mode.equals("null_stream")?null:stream);
  if(mode.equals("trace_error"))record.failOpen=true;
  if(mode.equals("zero_read"))stream.zero=true;
  if(mode.equals("close_error"))stream.failClose=true;
  if(mode.equals("blocked_read")){stream.readGate=new CountDownLatch(1);}
  long started=System.nanoTime();
  if(mode.equals("blocked_close"))stream.closeGate=new CountDownLatch(1);
  JSONObject result=collector.collect(maximum->Collections.singletonList(record),34,mode.startsWith("blocked_")?300:1000);
  check(TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-started)<1500,"trace/close deadline does not block export");
  if(mode.equals("blocked_close")){
   JSONObject second=collector.collect(maximum->{throw new AssertionError("blocked close must not start another reader");},34,300);
   check(second.toString().contains("previous_collection_pending"),"blocked close remains guarded");stream.closeGate.countDown();
  }
  if(mode.equals("blocked_read"))for(int i=0;i<100&&stream.closes.get()==0;i++)Thread.sleep(5);
  System.out.println(envelope(result,stream));
 }
}''',
    }
    paths = []
    for name, body in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        paths.append(str(path))
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-encoding", "UTF-8", "-d", str(folder / "classes"), *paths], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr

    def run(mode):
        result = subprocess.run([java, "-Xmx64m", "-XX:ActiveProcessorCount=1", "-cp", str(folder / "classes"), PACKAGE + ".ExitCollectorHost", mode], capture_output=True, text=True, timeout=6)
        assert result.returncode == 0, result.stderr
        assert "sensitive-provider-path" not in result.stdout and "sensitive-device-details" not in result.stdout
        return json.loads(result.stdout)
    return run


def test_android_platform_query_is_package_scoped_and_older_android_is_explicitly_unsupported(collector):
    result = collector("platform")
    assert result["supported"] is True and result["scope"] == "self_package"
    assert result["status"] == "complete" and len(result["records"]) == 3
    row = result["records"][0]
    assert {key: row[key] for key in ("reason", "status", "pid", "importance", "timestamp_ms", "process_name")} == {
        "reason": 5, "status": 11, "pid": 1234, "importance": 100, "timestamp_ms": 123456789000, "process_name": "app.owned.package:game"}
    assert row["trace"]["encoding"] == "base64" and row["trace"]["format"] == "android_native_tombstone_proto"
    assert result["records"][1]["trace"]["format"] == "android_anr_trace"
    assert result["records"][2]["trace"]["status"] == "not_applicable"
    older = collector("older")
    assert older["status"] == "unsupported" and older["supported"] is False and older["records"] == []


def test_collector_never_reads_past_128kib_or_more_than_five_records_and_closes_all_streams(collector):
    result = collector("bounded")
    assert len(result["records"]) == result["max_records"] == 5
    for row in result["records"]:
        trace = row["trace"]
        assert trace["status"] == "truncated" and trace["bytes"] == trace["limit_bytes"] == 128 * 1024
        raw = base64.b64decode(trace["data"], validate=True)
        assert len(raw) == 128 * 1024 and raw[:256] == bytes(range(256))


@pytest.mark.parametrize("mode,error", [("trace_error", "trace_read_failed"), ("zero_read", "trace_read_failed"), ("close_error", "trace_close_failed")])
def test_trace_failures_keep_exit_metadata_and_export_safe_failure_codes(collector, mode, error):
    result = collector(mode)
    assert result["diagnostic"]["status"] == "partial"
    row = result["diagnostic"]["records"][0]
    assert row["reason"] == 5 and row["status"] == 11 and row["trace"]["error_code"] == error
    assert result["closes"] == (0 if mode == "trace_error" else 1)
    if mode == "zero_read":
        assert result["reads"] == 16


def test_null_trace_and_query_failure_are_explicit_without_failing_export(collector):
    assert collector("null_stream")["diagnostic"]["records"][0]["trace"]["status"] == "unavailable"
    assert collector("query_error")["error_code"] == "history_query_failed"


@pytest.mark.parametrize("mode", ["blocked_read", "blocked_close"])
def test_uninterruptible_trace_read_or_close_cannot_hang_export(collector, mode):
    result = collector(mode)
    assert result["diagnostic"]["error_code"] == "history_collection_timeout"
    assert result["diagnostic"]["records"][0]["pid"] == 1234
    assert result["diagnostic"]["records"][0]["trace"]["status"] == "timed_out"
    assert result["closes"] == 1


def test_uninterruptible_binder_query_is_bounded_and_cannot_spawn_duplicate_collectors(collector):
    result = collector("blocked_query")
    assert result["first"]["status"] == "timed_out" and result["first"]["error_code"] == "history_collection_timeout"
    assert result["second"]["status"] == "busy" and result["second"]["error_code"] == "previous_collection_pending"


def test_shipping_helper_compiles_with_actual_android_sdk_api_signatures(tmp_path):
    javac, _ = jdk()
    homes = [Path(os.environ.get("ANDROID_HOME", "/nonexistent")), ROOT.parent / ".setup/android-sdk"]
    android = next((home / "platforms/android-34/android.jar" for home in homes if (home / "platforms/android-34/android.jar").is_file()), None)
    if android is None:
        pytest.skip("Actual Android SDK34 required")
    compiled = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-classpath", str(android), "-d", str(tmp_path), str(SOURCE)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    assert (tmp_path / PACKAGE.replace(".", "/") / "PreviousProcessExits.class").is_file()
