"""Run the actual encoder selection method with explicit codec capability fixtures."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
ENCODER = ROOT / "android-unified/src/main/java/game/qualiarts/idolypride/localserver/mp4/OfflineMp4Encoder.java"

HARNESS = r'''
import java.io.IOException;
import java.util.*;
final class RateAdmissionHarness {
  static final class Config {int width=1920,height=1080,fpsNumerator=120,fpsDenominator=1,bitrate=32000000;String mime(){return "video/avc";}}
  Config config=new Config();String videoCodecName;
  static int creates=0,rateQueries=0;
  void check(){}
  // ACTUAL_OPEN_VIDEO
  static final class MediaFormat {
    static final String KEY_COLOR_FORMAT="color",KEY_BIT_RATE="bitrate",KEY_FRAME_RATE="fps",KEY_I_FRAME_INTERVAL="interval",KEY_MAX_B_FRAMES="b",KEY_COLOR_STANDARD="standard",KEY_COLOR_RANGE="range",KEY_COLOR_TRANSFER="transfer";
    static final int COLOR_STANDARD_BT709=1,COLOR_RANGE_LIMITED=2,COLOR_TRANSFER_SDR_VIDEO=3;
    final Map<String,Number> values=new HashMap<>();
    static MediaFormat createVideoFormat(String mime,int width,int height){if(!mime.equals("video/avc")||width!=1920||height!=1080)throw new AssertionError("unexpected selected mode");return new MediaFormat();}
    void setInteger(String k,int v){values.put(k,v);}void setFloat(String k,float v){values.put(k,v);}
  }
  static final class MediaCodecInfo {
    final String name;final boolean size,rate,throwsCaps;
    MediaCodecInfo(String n,boolean s,boolean r){name=n;size=s;rate=r;throwsCaps=false;}
    boolean isEncoder(){return true;}String getName(){return name;}
    CodecCapabilities getCapabilitiesForType(String mime){if(throwsCaps)throw new IllegalArgumentException("unavailable");return new CodecCapabilities(this);}
    static final class CodecCapabilities {static final int COLOR_FormatYUV420Flexible=1;int[]colorFormats={1};final MediaCodecInfo info;CodecCapabilities(MediaCodecInfo i){info=i;}VideoCapabilities getVideoCapabilities(){return new VideoCapabilities(info);}}
    static final class VideoCapabilities {final MediaCodecInfo info;VideoCapabilities(MediaCodecInfo i){info=i;}boolean isSizeSupported(int w,int h){return info.size;}boolean areSizeAndRateSupported(int w,int h,double rate){rateQueries++;if(w!=1920||h!=1080||rate!=120)throw new AssertionError("capability must use exact mode");return info.rate;}}
  }
  static final class MediaCodecList {static final int REGULAR_CODECS=0;static MediaCodecInfo[]infos;MediaCodecList(int ignored){}MediaCodecInfo[]getCodecInfos(){return infos;}}
  static final class MediaCodec {
    static final int CONFIGURE_FLAG_ENCODE=1;static final List<Float> rates=new ArrayList<>();final String name;
    MediaCodec(String n){name=n;}static MediaCodec createByCodecName(String n)throws IOException{creates++;return new MediaCodec(n);}
    void configure(MediaFormat f,Object surface,Object crypto,int flags){if(flags!=1)throw new AssertionError("encoder flags");rates.add(f.values.get("fps").floatValue());}
    void start()throws IOException{if(name.equals("configure_failure"))throw new IOException("real codec startup rejected mode");}
  }
  static final class AacPrimingProbe {static void close(MediaCodec ignored){}}
  public static void main(String[]args)throws Exception {
    String mode=args[0];RateAdmissionHarness h=new RateAdmissionHarness();
    if(mode.equals("unsupported120")){MediaCodecList.infos=new MediaCodecInfo[]{new MediaCodecInfo("lower_only",true,false)};boolean refused=false;try{h.openVideo();}catch(IOException expected){refused=true;}if(!refused||creates!=0||rateQueries!=1)throw new AssertionError("unsupported120 must refuse before configuring");}
    else if(mode.equals("accepted120")){MediaCodecList.infos=new MediaCodecInfo[]{new MediaCodecInfo("lower_only",true,false),new MediaCodecInfo("selected120",true,true)};h.openVideo();if(!h.videoCodecName.equals("selected120")||creates!=1||rateQueries!=2||!MediaCodec.rates.equals(List.of(120f)))throw new AssertionError("exact120 selection");}
    else if(mode.equals("no_rate_fallback")){MediaCodecList.infos=new MediaCodecInfo[]{new MediaCodecInfo("configure_failure",true,true),new MediaCodecInfo("lower_only",true,false)};boolean refused=false;try{h.openVideo();}catch(IOException expected){refused=true;}if(!refused||creates!=1||!MediaCodec.rates.equals(List.of(120f)))throw new AssertionError("startup rejection must not downgrade");}
    else if(mode.equals("rational120")){h.config.fpsNumerator=120000;h.config.fpsDenominator=1000;MediaCodecList.infos=new MediaCodecInfo[]{new MediaCodecInfo("rational",true,true)};h.openVideo();if(rateQueries!=1||!MediaCodec.rates.equals(List.of(120f)))throw new AssertionError("rational120 exact gate");}
    else {h.config.fpsNumerator=mode.equals("legacy30")?30:60;MediaCodecList.infos=new MediaCodecInfo[]{new MediaCodecInfo("legacy_offline",false,false)};h.openVideo();if(rateQueries!=0||creates!=1||!MediaCodec.rates.equals(List.of((float)h.config.fpsNumerator)))throw new AssertionError("legacy advisory admission changed");}
  }
}
'''


@pytest.fixture(scope="module")
def rate_admission_binary(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = ENCODER.read_text()
    start = source.index("private MediaCodec openVideo()")
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    folder = tmp_path_factory.mktemp("mp4-rate-admission")
    code = folder / "RateAdmissionHarness.java"
    code.write_text(HARNESS.replace("// ACTUAL_OPEN_VIDEO", source[start:end]))
    built = subprocess.run([javac, "--release", "17", "-d", str(folder), str(code)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    return java, folder


@pytest.mark.parametrize("mode", ["unsupported120", "accepted120", "no_rate_fallback", "rational120", "legacy30", "legacy60"])
def test_exact_requested_encoder_rate_admission(rate_admission_binary, mode):
    java, folder = rate_admission_binary
    run = subprocess.run([java, "-cp", str(folder), "RateAdmissionHarness", mode], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr
