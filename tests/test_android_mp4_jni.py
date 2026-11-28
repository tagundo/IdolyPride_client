"""Run the real C ABI/JNI adapter in a JVM, including a foreign producer thread."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_real_jni_adapter_owns_frames_and_serializes_terminal_lifetime(tmp_path):
    javac, java, cxx = shutil.which("javac"), shutil.which("java"), shutil.which("g++")
    if not javac or not java or not cxx:
        pytest.skip("JDK and C++ compiler required")
    root = Path(__file__).resolve().parents[1]
    include = Path(javac).resolve().parents[1] / "include"
    if not (include / "jni.h").is_file():
        pytest.skip("JDK JNI development headers required")
    mock = tmp_path / "OfflineMp4Encoder.java"
    mock.write_text(r'''
package game.qualiarts.idolypride.localserver.mp4;
import java.nio.ByteBuffer;
public final class OfflineMp4Encoder {
  private int accepted,phase=1,reads;private boolean retried,terminal;private byte[] copied;
  public static OfflineMp4Encoder create(int w,int h,int num,int den,int vb,int rate,int ch,int ab,
      long samples,long frames,String pcm,String part,String dest,int codec) {
    if(w!=16||h!=16||num!=30||den!=1||vb!=1000000||rate!=48000||ch!=2||ab!=192000||samples!=48000||frames!=30
       ||!pcm.equals("/private/audio.f32")||!part.equals("/private/partial.mp4")||!dest.equals("/private/final.mp4")||codec!=1)
      throw new IllegalArgumentException("wrong C ABI argument mapping");
    return new OfflineMp4Encoder();
  }
  // The native adapter converts RGBA to I420 before Java sees the frame.
  public int appendI420(ByteBuffer i420,long index) {
    if(index==9)throw new IllegalStateException("/private/path-must-not-escape");
    if(index!=accepted||!i420.isDirect()||i420.remaining()!=384)throw new AssertionError("frame mapping");
    if(!retried){retried=true;return 1;}
    copied=new byte[384];i420.get(copied);accepted++;phase=2;return 0;
  }
  public long[] nativeStatus() {
    // RGB 23 is BT.709 code 10, so limited-range luma 25 and neutral chroma 128.
    if(copied!=null&&((copied[0]&255)!=25||(copied[255]&255)!=25||(copied[256]&255)!=128||(copied[383]&255)!=128))
      throw new AssertionError("native I420 conversion or copied ownership");
    if(phase==3&&++reads>1){phase=4;terminal=true;}
    return new long[]{phase,0,accepted,accepted,48000,1234,terminal?1:0};
  }
  public int finish(){phase=3;return 0;} public void cancel(){phase=6;terminal=true;}
  public boolean isTerminal(){return terminal;} public String errorCode(){return "";}
}
''')
    harness = tmp_path / "Harness.java"
    harness.write_text(r'''
package game.qualiarts.idolypride.localserver;
import game.qualiarts.idolypride.localserver.mp4.OfflineMp4Encoder;
final class UnifiedMP4Export {static native boolean nativeInitializeEncoder(Class<?> type);}
public final class Harness {
  private static native String exercise();
  public static void main(String[] args)throws Exception {
    System.load(args[0]);
    if(!UnifiedMP4Export.nativeInitializeEncoder(OfflineMp4Encoder.class))throw new AssertionError("bootstrap");
    if(!UnifiedMP4Export.nativeInitializeEncoder(OfflineMp4Encoder.class))throw new AssertionError("idempotent bootstrap");
    if(UnifiedMP4Export.nativeInitializeEncoder(String.class))throw new AssertionError("classloader mismatch accepted");
    String error=exercise();if(!error.isEmpty())throw new AssertionError(error);
    System.out.println("PASS JNI");
  }
}
''')
    native = tmp_path / "jni_test.cpp"
    native.write_text(r'''
#include "mp4_android_encoder.hpp"
#include <string>
#include <thread>
#include <vector>
extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_Harness_exercise(JNIEnv*env,jclass){
  std::string failure;
  std::thread producer([&]{
    auto check=[&](bool ok,const char*why){if(!ok&&failure.empty())failure=why;};
    IDMP4EncoderConfig c={};c.struct_size=sizeof(c);c.abi_version=1;c.width=16;c.height=16;c.fps_num=30;c.fps_den=1;
    c.video_codec=IDMP4_H264;c.video_bitrate=1000000;c.audio_sample_rate=48000;c.audio_channels=2;c.audio_bitrate=192000;
    c.audio_sample_frames=48000;c.video_frame_count=30;c.pcm_f32_path="/private/audio.f32";c.partial_path="/private/partial.mp4";c.final_path="/private/final.mp4";
    char error[192]={};
    c.reserved=1;check(!IDMP4EncoderCreate(&c,error,sizeof(error))&&std::string(error)=="invalid_encoder_config","invalid config gate");c.reserved=0;
    auto h=IDMP4EncoderCreate(&c,error,sizeof(error));check(h&&!*error,"foreign thread create");if(!h)return;
    std::vector<uint8_t> rgba(1024,23);
    check(IDMP4EncoderAppendFrame(h,rgba.data(),64,0)==IDMP4_RETRY,"backpressure");
    check(IDMP4EncoderAppendFrame(h,rgba.data(),64,0)==IDMP4_ACCEPTED,"same-index retry");rgba[0]=99;
    IDMP4EncoderStatus s={};s.struct_size=sizeof(s);s.abi_version=1;
    check(IDMP4EncoderPoll(h,&s)==0&&s.submitted_frames==1&&s.audio_frames==48000&&s.bytes_written==1234,"status fields and copied input");
    check(IDMP4EncoderDestroy(h)==IDMP4_RETRY,"premature destroy");
    check(IDMP4EncoderAppendFrame(h,rgba.data(),64,9)==IDMP4_ERROR,"Java exception mapped");
    check(IDMP4EncoderPoll(h,&s)==0&&std::string(s.error_code)=="encoder_java_exception","stable sanitized error");
    check(IDMP4EncoderFinish(h)==0,"async finish");
    check(IDMP4EncoderPoll(h,&s)==0&&s.phase==IDMP4_FINISHING,"finishing phase");
    check(IDMP4EncoderDestroy(h)==IDMP4_RETRY,"worker cleanup gate");
    check(IDMP4EncoderPoll(h,&s)==0&&s.phase==IDMP4_COMPLETED,"completion phase");
    check(IDMP4EncoderDestroy(h)==0,"terminal destroy");
    h=IDMP4EncoderCreate(&c,error,sizeof(error));check(h!=nullptr,"second create");if(!h)return;
    IDMP4EncoderCancel(h);check(IDMP4EncoderPoll(h,&s)==0&&s.phase==IDMP4_CANCELLED,"cancel phase");
    check(IDMP4EncoderDestroy(h)==0,"cancel destroy");check(IDMP4EncoderDestroy(nullptr)==0,"null destroy");
  });producer.join();return env->NewStringUTF(failure.c_str());
}
''')
    library = tmp_path / "libencoder_jni_test.so"
    build = subprocess.run([cxx, "-std=c++17", "-shared", "-fPIC", "-pthread", "-fvisibility=hidden",
                            "-Wall", "-Wextra", "-Werror", "-I", str(include), "-I", str(include / "linux"),
                            "-I", str(root / "client-presentation/native"), str(native), "-o", str(library)],
                           capture_output=True, text=True, timeout=45)
    assert build.returncode == 0, build.stderr
    classes = tmp_path / "classes"
    build = subprocess.run([javac, "-J-Xmx256m", "--release", "17", "-d", str(classes), str(mock), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([java, "-Xcheck:jni", "-Xmx128m", "-cp", str(classes),
                          "game.qualiarts.idolypride/localserver/Harness".replace("/", "."), str(library)],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.strip() == "PASS JNI"
    assert "WARNING in native method" not in run.stderr + run.stdout


def test_real_session_jni_invalidates_host_snapshot_without_unity(tmp_path):
    javac, java, cxx = shutil.which("javac"), shutil.which("java"), shutil.which("g++")
    if not javac or not java or not cxx:
        pytest.skip("JDK and C++ compiler required")
    root = Path(__file__).resolve().parents[1]
    include = Path(javac).resolve().parents[1] / "include"
    if not (include / "jni.h").is_file():
        pytest.skip("JDK JNI development headers required")
    source = tmp_path / "session.cpp"
    source.write_text(r'''
#include "mp4_android_encoder.hpp"
#include "mp4_runtime.hpp"
#include "mp4_android_session.hpp"
extern "C" JNIEXPORT jlong JNICALL Java_game_qualiarts_idolypride_localserver_SessionHarness_generation(JNIEnv*,jclass){
    pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);
    const auto value=idoly_mp4_runtime::queue_selection_generation;
    pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);return static_cast<jlong>(value);
}
''')
    harness = tmp_path / "SessionHarness.java"
    harness.write_text(r'''
package game.qualiarts.idolypride.localserver;
final class UnifiedMP4Export {
  static native void nativeInvalidateQueueSelection();
  static native boolean nativeReady();
  static native int nativeQueueEnqueueV2(int n,int d,int codec,int bitrate,int audio,int width,int height);
  static native String nativeQueueStatus();
}
public final class SessionHarness {
  static native long generation();
  public static void main(String[] args)throws Exception {
    System.load(args[0]);long before=generation();
    UnifiedMP4Export.nativeInvalidateQueueSelection();
    Thread foreign=new Thread(UnifiedMP4Export::nativeInvalidateQueueSelection);foreign.start();foreign.join();
    if(generation()!=before+2)throw new AssertionError("real JNI did not reach scalar invalidation");
    if(UnifiedMP4Export.nativeReady())throw new AssertionError("cold runtime became ready");
    if(UnifiedMP4Export.nativeQueueEnqueueV2(30,1,1,0,192000,0,0)!=-1)
      throw new AssertionError("cold host admission accepted without captured Unity selection");
    if(!UnifiedMP4Export.nativeQueueStatus().contains("queue_not_configured"))
      throw new AssertionError("actual native queue status missing");
    System.out.println("PASS SESSION JNI");
  }
}
''')
    library = tmp_path / "libsession.so"
    compiled = subprocess.run([cxx,"-std=c++17","-shared","-fPIC","-pthread","-fvisibility=hidden",
        "-Wall","-Wextra","-Werror","-I",str(include),"-I",str(include / "linux"),
        "-I",str(root / "client-presentation/native"),str(source),"-o",str(library)],capture_output=True,text=True,timeout=45)
    assert compiled.returncode == 0,compiled.stderr
    classes = tmp_path / "classes"
    compiled = subprocess.run([javac,"-J-Xmx256m","--release","17","-d",str(classes),str(harness)],capture_output=True,text=True,timeout=30)
    assert compiled.returncode == 0,compiled.stderr
    result = subprocess.run([java,"-Xcheck:jni","-Xmx128m","-cp",str(classes),
        "game.qualiarts.idolypride.localserver.SessionHarness",str(library)],capture_output=True,text=True,timeout=30)
    assert result.returncode == 0,result.stdout + result.stderr
    assert result.stdout.strip() == "PASS SESSION JNI"
    assert "WARNING in native method" not in result.stderr + result.stdout
