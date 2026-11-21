from __future__ import annotations

from array import array
import copy
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from tools import build_android_mp4_qa as qa


def report():
    cases = []
    for name, frames, numerator, denominator in (("avc30", 30, 30, 1), ("avc60000_1001", 60, 60000, 1001)):
        cases.append({"name": name, "required": True, "status": "passed", "frames": frames,
            "decoded_video_frames": frames, "fps_numerator": numerator, "fps_denominator": denominator,
            "ordered_video_pts": True, "corner_pixels_verified": True, "source_preserved": True,
            "private_partial_permissions": True, "private_final_permissions": True,
            "file": name + "/complete.mp4", "audio": {"raw_decoded_frames": 51200, "logical_frames": 48000,
                "aac_packets": 50, "priming_samples": 1600, "impulses_verified": True, "edit_list_exact": True},
            "encoder": {"phase": "completed", "aac_priming_samples": 1600, "audio_packets": 50}})
    cases += [{"name": "cancel", "required": True, "status": "passed", "terminal_cleanup": True,
               "source_preserved": True, "output_absent": True},
              {"name": "no_overwrite", "required": True, "status": "passed", "sentinel_preserved": True, "partial_absent": True},
              {"name": "hevc30", "required": False, "status": "unsupported", "capability_checked": True,
               "reason": "device_has_no_supported_hevc_encoder"}]
    return {"schema": 1, "package": qa.PACKAGE, "phase": "completed", "passed": True, "cases": cases}


def pcm(shift=0):
    values = array("f", [0]) * (48000 * 2)
    for channel in range(2):
        values[(8000 + shift) * 2 + channel] = 0.8
        values[(32000 + shift) * 2 + channel] = -0.6
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def test_report_requires_actual_decode_and_all_terminal_ownership_checks():
    value = report()
    assert qa.validate_runtime_report(value) == value
    hevc = copy.deepcopy(value["cases"][0])
    hevc.update(name="hevc30", required=False, file="hevc30/complete.mp4")
    value["cases"][-1] = hevc
    assert qa.validate_runtime_report(value) == value


@pytest.mark.parametrize("key,value", [("phase", "running"), ("phase", "failed"), ("passed", False),
    ("passed", 1), ("package", "game.qualiarts.idolypride.local.diagnostics"), ("error", "decoder failed")])
def test_never_accept_build_only_failed_or_another_app(key, value):
    proof = report(); proof[key] = value
    with pytest.raises(ValueError):
        qa.validate_runtime_report(proof)


@pytest.mark.parametrize("index,section,key,value", [
    (0, None, "status", "unsupported"), (0, None, "decoded_video_frames", 29),
    (0, None, "ordered_video_pts", False), (0, None, "corner_pixels_verified", False),
    (0, None, "source_preserved", False), (0, None, "required", False),
    (0, None, "private_partial_permissions", False), (0, None, "private_final_permissions", False),
    (0, None, "file", "../../other.mp4"), (1, None, "fps_denominator", 1000),
    (0, "audio", "raw_decoded_frames", 48000), (0, "audio", "aac_packets", 49),
    (0, "audio", "logical_frames", 48128), (0, "audio", "priming_samples", -1),
    (0, "audio", "impulses_verified", False), (0, "audio", "edit_list_exact", False),
    (0, "encoder", "phase", "finishing"), (0, "encoder", "aac_priming_samples", 2048),
    (0, "encoder", "audio_packets", 49), (2, None, "terminal_cleanup", False),
    (2, None, "output_absent", False), (3, None, "sentinel_preserved", False),
    (3, None, "partial_absent", False), (4, None, "status", "failed"),
    (4, None, "capability_checked", False), (4, None, "reason", "any decoder failure"),
])
def test_case_proofs_are_strict(index, section, key, value):
    proof = report()
    target = proof["cases"][index]
    if section is not None:
        target = target[section]
    target[key] = value
    with pytest.raises(ValueError):
        qa.validate_runtime_report(proof)


def test_missing_and_duplicate_cases_cannot_pass():
    for cases in (report()["cases"][:-1], report()["cases"] + [report()["cases"][0]]):
        with pytest.raises(ValueError):
            qa.validate_runtime_report(dict(report(), cases=cases))


def test_independent_audio_checks_logical_samples_polarity_and_both_channels():
    proof = qa.validate_independent_pcm(pcm())
    assert proof["presented_sample_frames"] == 48000
    assert proof["channel_peaks"] == [{"positive_sample": 8000, "negative_sample": 32000}] * 2
    assert qa.validate_independent_pcm(pcm(1))["impulses_verified"] is True
    for raw in (pcm()[:-8], pcm() + b"\0" * 1024, pcm(448), b"\0" * len(pcm())):
        with pytest.raises(ValueError):
            qa.validate_independent_pcm(raw)
    values = array("f"); values.frombytes(pcm())
    values[0] = float("nan")
    with pytest.raises(ValueError):
        qa.validate_independent_pcm(values.tobytes())


def audio_metadata():
    packets = []
    for index, start in enumerate(range(-2048, 48000, 1024)):
        packet = {"stream_index": 1, "pts": start, "dts": start, "duration": min(1024, 48000 - start)}
        if index == 0:
            packet["side_data_list"] = [{"side_data_type": "Skip Samples", "skip_samples": 2048,
                                         "discard_padding": 0}]
        packets.append(packet)
    return {"streams": [{"index": 1, "codec_name": "aac", "sample_rate": "48000", "channels": 2,
                         "time_base": "1/48000", "start_pts": 0, "duration_ts": 48000}], "packets": packets}


def test_independent_audio_honors_verified_container_end_and_retains_raw_padding_counts():
    presentation = qa.validate_audio_presentation(audio_metadata())
    assert presentation["last_packet_end"] == 48000 and presentation["priming_samples"] == 2048
    for tail in (0, 128, 1023):
        proof = qa.validate_independent_pcm(pcm() + bytes(tail * 8), presentation)
        assert proof["presented_sample_frames"] == 48000
        assert proof["raw_decoded_frames"] == 48000 + tail
        assert proof["discarded_tail_frames"] == tail
        assert proof["channel_peaks"] == [{"positive_sample": 8000, "negative_sample": 32000}] * 2
    # Padding outside the independently proven interval cannot hide phase errors.
    for raw in (pcm()[:-8], pcm() + bytes(1024 * 8), pcm(2) + bytes(128 * 8), pcm(448) + bytes(128 * 8)):
        with pytest.raises(ValueError):
            qa.validate_independent_pcm(raw, presentation)
    with pytest.raises(ValueError):
        qa.validate_independent_pcm(pcm() + bytes(128 * 8), {})


@pytest.mark.parametrize("key,value", [("duration_ts", 48128), ("duration_ts", 47999),
    ("time_base", "1/44100"), ("start_pts", 1), ("start_pts", False),
    ("sample_rate", "44100"), ("channels", 1), ("codec_name", "mp3")])
def test_independent_audio_rejects_wrong_container_presentation(key, value):
    metadata = audio_metadata()
    metadata["streams"][0][key] = value
    with pytest.raises(ValueError):
        qa.validate_audio_presentation(metadata)


@pytest.mark.parametrize("index,key,value", [(-1, "duration", 1024), (-1, "duration", 895),
    (3, "dts", 1025), (3, "pts", 1025), (3, "duration", 1023), (3, "duration", 2048),
    (3, "stream_index", 2), (3, "side_data_list", [{"side_data_type": "Skip Samples", "skip_samples": 2}]),
    (0, "side_data_list", [{"side_data_type": "Skip Samples", "skip_samples": 1024, "discard_padding": 0}])])
def test_independent_audio_rejects_packet_gaps_offsets_and_unexpected_edits(index, key, value):
    metadata = audio_metadata()
    metadata["packets"][index][key] = value
    with pytest.raises(ValueError):
        qa.validate_audio_presentation(metadata)


def test_independent_audio_rejects_missing_and_extra_packet_blocks():
    metadata = audio_metadata()
    for packets in (metadata["packets"][:-1], metadata["packets"] + [dict(metadata["packets"][-1], dts=48000, pts=48000)]):
        with pytest.raises(ValueError):
            qa.validate_audio_presentation(dict(metadata, packets=packets))


def manifest():
    return f'''<manifest xmlns:android="{qa.ANDROID[1:-1]}" package="{qa.PACKAGE}">
      <uses-sdk android:minSdkVersion="30" android:targetSdkVersion="35"/>
      <application android:debuggable="true" android:allowBackup="false">
        <activity android:name=".CodecProbeActivity" android:exported="true"><intent-filter>
          <action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/>
        </intent-filter></activity>
      </application></manifest>'''.encode()


def test_isolated_qa_manifest_has_no_game_permissions_services_or_backup():
    qa.validate_manifest(manifest())
    for raw in (manifest().replace(qa.PACKAGE.encode(), b"game.other"),
                manifest().replace(b'minSdkVersion="30"', b'minSdkVersion="28"'),
                manifest().replace(b'targetSdkVersion="35"', b'targetSdkVersion="34"'),
                manifest().replace(b'debuggable="true"', b'debuggable="false"'),
                manifest().replace(b'allowBackup="false"', b'allowBackup="true"'),
                manifest().replace(b"<uses-sdk", b'<uses-permission android:name="android.permission.RECORD_AUDIO"/><uses-sdk'),
                manifest().replace(b"</application>", b'<service android:name=".Foreign"/></application>')):
        with pytest.raises(ValueError):
            qa.validate_manifest(raw)


def tar_file(tmp_path, names):
    path = tmp_path / "proof.tar"
    with tarfile.open(path, "w") as out:
        for name, kind in names:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = 1; out.addfile(member, io.BytesIO(b"x"))
            else:
                member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                member.linkname = "/outside"; out.addfile(member)
    return path


@pytest.mark.parametrize("name,kind", [("../outside", "file"), ("/tmp/outside", "file"),
    ("mp4-qa/../../outside", "file"), ("foreign/file", "file"),
    ("mp4-qa/link", "symlink"), ("mp4-qa/link", "hardlink")])
def test_device_archive_cannot_escape_owned_evidence(tmp_path, name, kind):
    archive = tar_file(tmp_path, [(name, kind)])
    destination = tmp_path / "extracted"
    with pytest.raises(ValueError):
        qa.extract_archive(archive, destination)
    assert not destination.exists()


def test_archive_accepts_regular_evidence_and_rejects_duplicates(tmp_path):
    archive = tar_file(tmp_path, [("mp4-qa/report.json", "file"), ("mp4-qa/avc30/complete.mp4", "file")])
    qa.extract_archive(archive, tmp_path / "out")
    assert (tmp_path / "out/mp4-qa/avc30/complete.mp4").read_bytes() == b"x"
    archive = tar_file(tmp_path, [("mp4-qa/report.json", "file")] * 2)
    with pytest.raises(ValueError):
        qa.extract_archive(archive, tmp_path / "other")


def test_qa_relaunch_claims_only_one_worker_and_never_reuses_case_paths(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK needed for actual QA ownership concurrency test")
    source = qa.ROOT / Path(qa.PROBE).parent / "ProbeRunOwnership.java"
    harness = tmp_path / "ProbeOwnershipFixture.java"
    harness.write_text('''package game.qualiarts.idolypride.mp4qa;
      import java.io.*;import java.nio.file.*;import java.util.concurrent.*;import java.util.concurrent.atomic.*;
      public class ProbeOwnershipFixture { public static void main(String[] args)throws Exception {
        AtomicInteger workers=new AtomicInteger();CountDownLatch ready=new CountDownLatch(32),go=new CountDownLatch(1);
        Thread[] attempts=new Thread[32];for(int i=0;i<attempts.length;i++){
          attempts[i]=new Thread(()->{ready.countDown();try{go.await();}catch(InterruptedException e){throw new RuntimeException(e);}
            if(ProbeRunOwnership.claimProcessRun())workers.incrementAndGet();});attempts[i].start();}
        if(!ready.await(10,TimeUnit.SECONDS))throw new AssertionError("launch attempts did not start");go.countDown();
        for(Thread thread:attempts)thread.join(10000);
        if(workers.get()!=1||ProbeRunOwnership.claimProcessRun())throw new AssertionError("duplicate/recreated activity started a worker");
        File path=new File(args[0],"case");ProbeRunOwnership.createFreshDirectory(path);
        Path sentinel=path.toPath().resolve("proof");Files.write(sentinel,new byte[]{17,29});
        boolean refused=false;try{ProbeRunOwnership.createFreshDirectory(path);}catch(IOException expected){refused=true;}
        if(!refused||Files.readAllBytes(sentinel)[1]!=29)throw new AssertionError("existing case reused or changed");
      }}''')
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(tmp_path), str(source), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    result = subprocess.run([java, "-Xmx128m", "-cp", str(tmp_path),
                             "game.qualiarts.idolypride.mp4qa.ProbeOwnershipFixture", str(tmp_path)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    inventory = qa.sources(qa.ROOT)[1]
    assert source.relative_to(qa.ROOT).as_posix() in inventory
    activity = (qa.ROOT / qa.PROBE).read_text()
    assert "if (!isChangingConfigurations())" in activity


def test_workflow_is_scoped_read_only_and_never_treats_an_artifact_as_a_pass():
    root = Path(__file__).resolve().parents[1]
    raw = (root / ".github/workflows/verify-mp4-codecs.yml").read_text()
    assert "contents: read" in raw and "contents: write" not in raw and "GH_TOKEN" not in raw
    assert "ref: ${{ github.sha }}" in raw and "branches: [feat/ios-unified-server]" in raw
    assert "IdolyMVEncoder.mm" in raw and "mp4_encoder_api.h" in raw
    assert "ios-unified/native/test_mv_encoder.py" in raw and "tools/build_android_mp4_qa.py --run-device --timeout 600" in raw
    assert "api-level: 35" in raw and "arch: x86_64" in raw and "emulator-boot-timeout: 1200" in raw
    assert "test -c /dev/kvm" in raw and "disable-linux-hw-accel: false" in raw
    assert "ffmpeg -version" in raw and raw.count("if: always()") == 2
    assert "continue-on-error" not in raw and "gh release" not in raw
    assert "UnifiedGameActivity.java" not in raw and "mp4_game_adapter.hpp" not in raw
