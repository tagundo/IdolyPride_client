"""Execute platform-independent offline clocks/pixels and AAC probe acceptance on a real JVM."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-unified/src/main/java/game/qualiarts/idolypride/localserver/mp4"


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    folder = tmp_path_factory.mktemp("android-mp4-jvm")
    source = folder / "MathHarness.java"
    source.write_text(r'''
package game.qualiarts.idolypride.localserver.mp4;
import java.util.Arrays;
public final class MathHarness {
  static void equal(long actual,long expected) { if(actual!=expected)throw new AssertionError(actual+" != "+expected); }
  static void rejects(Runnable action) { try { action.run(); } catch(IllegalArgumentException|ArithmeticException expected) { return; } throw new AssertionError("accepted invalid input"); }
  public static void main(String[] args) throws Exception {
    switch(args[0]) {
      case "clocks":
        equal(OfflineMp4Math.timestampUs(30000,30000,1001),1001000000L);
        equal(OfflineMp4Math.timestampUs(1,30000,1001),33366);
        equal(OfflineMp4Math.timestampUs(17280000000L,48000,1),360000000000L);
        equal(OfflineMp4Math.audioBoundary(1,30000,1001,48000),1602);
        // 1602 PCM samples end *after* the fractional first video boundary (1601.6).
        equal(OfflineMp4Math.videoFramesForAudio(1602,30000,1001,48000),2);
        equal(OfflineMp4Math.videoFramesForAudio(1601,30000,1001,48000),1);
        equal(OfflineMp4Math.videoFramesForAudio(44100,60,1,44100),60);
        rejects(()->OfflineMp4Math.timestampUs(Long.MAX_VALUE,1,10000));
        rejects(()->OfflineMp4Math.timestampUs(-1,30,1));
        rejects(()->OfflineMp4Math.audioBoundary(1,0,1,48000));
        rejects(()->OfflineMp4Math.videoFramesForAudio(Long.MAX_VALUE,240,1,1));
        break;
      case "pixels": {
        equal(OfflineMp4Math.pixels(3840,2160),8294400);
        rejects(()->OfflineMp4Math.pixels(3841,2160));
        rejects(()->OfflineMp4Math.pixels(8192,8192));
        byte[] input=new byte[16*16*4],output=new byte[16*16*3/2];
        OfflineMp4Math.rgbaToI420(input,output,16,16);
        for(int i=0;i<256;i++)equal(output[i]&255,16);
        for(int i=256;i<384;i++)equal(output[i]&255,128);
        Arrays.fill(input,(byte)255); OfflineMp4Math.rgbaToI420(input,output,16,16);
        for(int i=0;i<256;i++)equal(output[i]&255,235);
        for(int i=256;i<384;i++)equal(output[i]&255,128);
        for(int i=0;i<input.length;i+=4) { input[i]=(byte)255;input[i+1]=0;input[i+2]=0;input[i+3]=0; }
        OfflineMp4Math.rgbaToI420(input,output,16,16);
        equal(output[0]&255,63);equal(output[256]&255,102);equal(output[320]&255,240);
        // Alpha is excluded and top/bottom rows retain their own luminance.
        for(int y=8;y<16;y++)for(int x=0;x<16;x++) { int p=(y*16+x)*4; input[p]=0;input[p+1]=0;input[p+2]=(byte)255; }
        OfflineMp4Math.rgbaToI420(input,output,16,16);
        equal(output[0]&255,63);equal(output[255]&255,32);equal(output[256+63]&255,240);
        rejects(()->OfflineMp4Math.rgbaToI420(new byte[1],output,16,16));
        break;
      }
      case "pcm":
        equal(OfflineMp4Math.pcm16(-2),-32768);equal(OfflineMp4Math.pcm16(2),32767);
        equal(OfflineMp4Math.pcm16(0),0);equal(OfflineMp4Math.pcm16(0.5f),16384);
        rejects(()->OfflineMp4Math.pcm16(Float.NaN));rejects(()->OfflineMp4Math.pcm16(Float.POSITIVE_INFINITY));
        break;
      default: throw new AssertionError(args[0]);
    }
    System.out.println("PASS "+args[0]);
  }
}
''')
    classes = folder / "classes"
    result = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-d", str(classes),
                             str(JAVA / "OfflineMp4Math.java"), str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return java, classes


@pytest.mark.parametrize("case", ["clocks", "pixels", "pcm"])
def test_offline_export_math(compiled, case):
    java, classes = compiled
    result = subprocess.run([java, "-Xmx128m", "-cp", str(classes),
                             "game.qualiarts.idolypride.localserver.mp4.MathHarness", case],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"PASS {case}"


def test_android_encoder_compiles_and_configuration_is_strict(tmp_path):
    sdk = Path(os.environ.get("ANDROID_HOME", "/workspace/.setup/android-sdk"))
    jar = sdk / "platforms/android-34/android.jar"
    javac, java = shutil.which("javac"), shutil.which("java")
    if not jar.is_file() or not javac or not java:
        pytest.skip("SDK34 and JDK required")
    harness = tmp_path / "ConfigHarness.java"
    harness.write_text(r'''
package game.qualiarts.idolypride.localserver.mp4;
import java.io.*;
public final class ConfigHarness {
  interface Checked { void run() throws Exception; }
  static void rejects(Checked c) throws Exception { try { c.run(); } catch(IllegalArgumentException|IOException expected) { return; } throw new AssertionError("accepted invalid config"); }
  static OfflineMp4Encoder.Config config(File dir,int num,int den,long frames) throws Exception {
    return new OfflineMp4Encoder.Config(16,16,num,den,1000000,48000,2,48000,frames,
      new File(dir,"audio.f32").toString(),new File(dir,"partial.mp4").toString(),new File(dir,"final.mp4").toString(),1);
  }
  public static void main(String[] args)throws Exception {
    File dir=new File(args[0]);dir.mkdirs();
    try(RandomAccessFile f=new RandomAccessFile(new File(dir,"audio.f32"),"rw")) { f.setLength(48000*2*4); }
    config(dir,30,1,30);
    rejects(()->config(dir,30,1,29));rejects(()->config(dir,30,1,31));rejects(()->config(dir,300,1,300));
    new File(dir,"final.mp4").createNewFile();rejects(()->config(dir,30,1,30));new File(dir,"final.mp4").delete();
    new File(dir,"partial.mp4").createNewFile();rejects(()->config(dir,30,1,30));new File(dir,"partial.mp4").delete();
    try(RandomAccessFile f=new RandomAccessFile(new File(dir,"audio.f32"),"rw")) { f.setLength(100); }
    rejects(()->config(dir,30,1,30));
    short[] decoded=new short[60000];decoded[4096+2048]=20000;decoded[20480+2048]=-15000;
    if(AacPrimingProbe.measuredDelay(decoded,decoded.length)!=2048)throw new AssertionError("delay");
    decoded[20480+2048]=0;decoded[20480+2049]=-15000;
    rejects(()->AacPrimingProbe.measuredDelay(decoded,decoded.length));
    rejects(()->AacPrimingProbe.measuredDelay(new short[10],10));
    System.out.println("PASS config");
  }
}
''')
    classes = tmp_path / "classes"
    result = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-cp", str(jar), "-d", str(classes),
                             *map(str, sorted(JAVA.glob("*.java"))), str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", os.pathsep.join([str(classes), str(jar)]),
                             "game.qualiarts.idolypride.localserver.mp4.ConfigHarness", str(tmp_path / "files")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS config"
