"""Exercise the actual Java MP4 timing rewrite against independent BMFF fixtures."""
from pathlib import Path
import shutil
import struct
import subprocess

import pytest


U32 = lambda value: struct.pack(">I", value)
U64 = lambda value: struct.pack(">Q", value)


def box(name, payload):
    return U32(len(payload) + 8) + name.encode("ascii") + payload


def full(name, payload, version=0):
    return box(name, bytes([version, 0, 0, 0]) + payload)


def timing(name, scale, duration, version=0):
    if name == "tkhd":
        payload = (bytes(16) + U32(duration) + bytes(60) if version == 0
                   else bytes(24) + U64(duration) + bytes(60))
    else:
        payload = (bytes(8) + U32(scale) + U32(duration) if version == 0
                   else bytes(16) + U32(scale) + U64(duration))
        payload += bytes(80 if name == "mvhd" else 4)
    return full(name, payload, version)


def descriptor(tag, payload):
    assert len(payload) < 128
    return bytes([tag, len(payload)]) + payload


def movie(*, rate=48000, packets=52, logical=50000, delay=2048, movie_scale=1000,
          video_duration=1250, version=0, timing_delta=1024, audio_duration=None,
          existing_edits=False, asc=b"\x11\x90", audio_rate=None, duplicate_audio=False):
    # 0x1190 is AAC-LC/48kHz/stereo/1024 samples; no borrowed reference source.
    specific = descriptor(5, asc)
    decoder = descriptor(4, bytes([0x40, 0x15]) + bytes(11) + specific)
    esds = full("esds", descriptor(3, b"\x00\x01\x00" + decoder + descriptor(6, b"\x02")))
    entry = box("mp4a", bytes(6) + b"\x00\x01" + bytes(8)
                + b"\x00\x02\x00\x10" + bytes(4) + U32((audio_rate or rate) << 16) + esds)
    table = box("stbl", full("stsd", U32(1) + entry)
                + full("stts", U32(1) + U32(packets) + U32(timing_delta))
                + full("stsz", U32(100) + U32(packets))
                + full("stco", U32(1) + U32(32)))
    audio = box("trak", timing("tkhd", 0, 1200, version)
                + (box("edts", full("elst", U32(0))) if existing_edits else b"")
                + box("mdia", timing("mdhd", rate, audio_duration if audio_duration is not None else packets * 1024, version)
                      + full("hdlr", bytes(4) + b"soun" + bytes(12)) + box("minf", table)))
    video = box("trak", timing("tkhd", 0, video_duration, version)
                + box("mdia", timing("mdhd", 90000, 112500, version)
                      + full("hdlr", bytes(4) + b"vide" + bytes(12))))
    metadata = box("moov", timing("mvhd", movie_scale, 1250, version)
                   + video + audio + (audio if duplicate_audio else b"") + box("udta", b"unchanged metadata"))
    prefix = box("ftyp", b"isom" + bytes(4)) + box("mdat", bytes(range(128)))
    return prefix + metadata, (rate, logical, delay, packets), prefix


@pytest.fixture(scope="module")
def java_finalizer(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required for the real Java BMFF finalizer")
    root = tmp_path_factory.mktemp("mp4-timeline-java")
    harness = root / "TimelineHarness.java"
    harness.write_text('''import java.io.File;import java.io.IOException;
      import game.qualiarts.idolypride.localserver.mp4.Mp4AudioTimeline;
      public class TimelineHarness {public static void main(String[] a)throws Exception {
        try {Mp4AudioTimeline.finalizeFile(new File(a[0]),Integer.parseInt(a[1]),
          Long.parseLong(a[2]),Integer.parseInt(a[3]),Long.parseLong(a[4]));}
        catch(IOException e){System.err.println(e.getMessage());System.exit(2);}
      }}''')
    source = Path(__file__).resolve().parents[1] / "android-unified/src/main/java/game/qualiarts/idolypride/localserver/mp4/Mp4AudioTimeline.java"
    built = subprocess.run([javac, "-J-Xmx128m", "--release", "17", "-d", str(root), str(source), str(harness)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr

    def run(path, args):
        return subprocess.run([java, "-Xmx128m", "-cp", str(root), "TimelineHarness", str(path), *map(str, args)],
                              capture_output=True, text=True, timeout=10)
    return run


def children(data):
    offset = 0
    while offset < len(data):
        size, name = struct.unpack_from(">I4s", data, offset)
        assert size >= 8 and size <= len(data) - offset
        yield name.decode(), data[offset + 8:offset + size]
        offset += size
    assert offset == len(data)


def named(data, name):
    return [payload for kind, payload in children(data) if kind == name]


@pytest.mark.parametrize("version", [0, 1])
def test_exact_pcm_edit_and_other_track_duration_preserve_media(java_finalizer, tmp_path, version):
    original, args, prefix = movie(version=version)
    path = tmp_path / "video.mp4"
    path.write_bytes(original)
    result = java_finalizer(path, args)
    assert result.returncode == 0, result.stderr
    output = path.read_bytes()
    assert output.startswith(prefix)  # mdat, chunk offsets and all media bytes retained.
    moov = named(output, "moov")[0]
    mvhd = named(moov, "mvhd")[0]
    scale_offset, duration_offset = (12, 16) if version == 0 else (20, 24)
    duration_format = ">I" if version == 0 else ">Q"
    assert struct.unpack_from(">I", mvhd, scale_offset)[0] == 48000
    assert struct.unpack_from(duration_format, mvhd, duration_offset)[0] == 60000
    video, audio = named(moov, "trak")
    track_offset = 20 if version == 0 else 28
    assert struct.unpack_from(duration_format, named(video, "tkhd")[0], track_offset)[0] == 60000
    assert struct.unpack_from(duration_format, named(audio, "tkhd")[0], track_offset)[0] == 50000
    elst = named(named(audio, "edts")[0], "elst")[0]
    assert elst == bytes([1, 0, 0, 0]) + U32(1) + U64(50000) + U64(2048) + U32(65536)
    mdhd = named(named(audio, "mdia")[0], "mdhd")[0]
    assert struct.unpack_from(duration_format, mdhd, duration_offset)[0] == 52 * 1024
    assert named(moov, "udta")[0] == b"unchanged metadata"


def test_noninteger_millisecond_audio_uses_exact_common_timescale(java_finalizer, tmp_path):
    original, args, _ = movie(rate=44100, asc=b"\x12\x10", logical=50001)
    path = tmp_path / "44100.mp4"
    path.write_bytes(original)
    result = java_finalizer(path, args)
    assert result.returncode == 0, result.stderr
    moov = named(path.read_bytes(), "moov")[0]
    assert struct.unpack_from(">I", named(moov, "mvhd")[0], 12)[0] == 441000
    audio = named(moov, "trak")[1]
    elst = named(named(audio, "edts")[0], "elst")[0]
    assert struct.unpack_from(">Q", elst, 8)[0] == 500010


def test_v1_large_duration_and_extended_moov_header(java_finalizer, tmp_path):
    original, args, prefix = movie(version=1, video_duration=0x100000001)
    moov = original[len(prefix):]
    extended = prefix + U32(1) + b"moov" + U64(len(moov) + 8) + moov[8:]
    path = tmp_path / "extended.mp4"
    path.write_bytes(extended)
    result = java_finalizer(path, args)
    assert result.returncode == 0, result.stderr
    output = path.read_bytes()
    assert output.startswith(prefix)
    mvhd = named(named(output, "moov")[0], "mvhd")[0]
    assert struct.unpack_from(">Q", mvhd, 24)[0] == 0x100000001 * 48


def test_expanded_descriptor_lengths_are_accepted(java_finalizer, tmp_path):
    # Android's writer may use four-byte expandable descriptor lengths.
    original, args, prefix = movie()
    start = original.index(b"esds") - 4
    esds_size = struct.unpack_from(">I", original, start)[0]
    esds = original[start:start + esds_size]
    old = esds[12:]
    assert old[0] == 3 and old[1] < 128
    changed = old[:1] + b"\x80\x80\x80" + old[1:]
    # Rebuild enclosing sizes without relying on finalizer parsing code.
    rebuilt = box("esds", esds[8:12] + changed)
    replacements = ("mp4a", "stsd", "stbl", "minf", "mdia", "trak", "moov")
    # Locate each original containing box and apply its size increase.
    mutated = bytearray(original[:start] + rebuilt + original[start + esds_size:])
    for name in replacements:
        candidates = [pos - 4 for pos in range(4, start) if original[pos:pos + 4] == name.encode()]
        container = next(pos for pos in reversed(candidates)
                         if pos + struct.unpack_from(">I", original, pos)[0] >= start + esds_size)
        struct.pack_into(">I", mutated, container, struct.unpack_from(">I", original, container)[0] + 3)
    path = tmp_path / "expandable.mp4"
    path.write_bytes(mutated)
    result = java_finalizer(path, args)
    assert result.returncode == 0, result.stderr
    assert path.read_bytes().startswith(prefix)


@pytest.mark.parametrize("trailing_free", [False, True])
def test_fast_start_movie_relocated_without_moving_media(java_finalizer, tmp_path, trailing_free):
    original, args, prefix = movie()
    ftyp_size = struct.unpack_from(">I", prefix)[0]
    moov = original[len(prefix):]
    # Relocation never interprets or rewrites chunk offsets. The writer's stco
    # values therefore remain identical when a front moov is retired as free.
    before = prefix[:ftyp_size] + moov + prefix[ftyp_size:]
    if trailing_free:
        before += box("free", bytes(20))
    path = tmp_path / "fast-start.mp4"
    path.write_bytes(before)
    result = java_finalizer(path, args)
    assert result.returncode == 0, result.stderr
    after = path.read_bytes()
    expected_prefix = bytearray(before)
    expected_prefix[ftyp_size + 4:ftyp_size + 8] = b"free"
    assert after[:len(before)] == expected_prefix
    assert [kind for kind, _ in children(after)].count("moov") == 1
    rebuilt = named(after, "moov")[0]
    audio = named(rebuilt, "trak")[1]
    table = named(named(named(audio, "mdia")[0], "minf")[0], "stbl")[0]
    assert named(table, "stco")[0] == bytes(4) + U32(1) + U32(32)
    assert struct.unpack_from(">Q", named(named(audio, "edts")[0], "elst")[0], 8)[0] == 50000


def test_front_movie_with_invalid_clock_never_changes_file(java_finalizer, tmp_path):
    original, args, prefix = movie(timing_delta=960)
    ftyp_size = struct.unpack_from(">I", prefix)[0]
    before = prefix[:ftyp_size] + original[len(prefix):] + prefix[ftyp_size:]
    path = tmp_path / "invalid-front.mp4"
    path.write_bytes(before)
    result = java_finalizer(path, args)
    assert result.returncode == 2
    assert path.read_bytes() == before


@pytest.mark.parametrize("options,args_override,message", [
    ({"existing_edits": True}, None, "Preexisting track edits"),
    ({"timing_delta": 960}, None, "1024 samples"),
    ({"audio_duration": 50000}, None, "media clock"),
    ({"asc": b"\x29\x90"}, None, "AAC-LC"),
    ({"asc": b"\x11"}, None, "Truncated AAC"),
    ({"audio_rate": 44100}, None, "sample entry"),
    ({"duplicate_audio": True}, None, "one AAC track"),
    ({}, (48000, 52000, 2048, 52), "complete logical PCM"),
    ({}, (48000, 50000, 2048, (1 << 63) - 1), "overflow"),
    ({"video_duration": 0xffffffff}, None, "overflows its version"),
    ({"movie_scale": 0xffffffff}, None, "timescale"),
])
def test_invalid_timing_never_changes_file(java_finalizer, tmp_path, options, args_override, message):
    original, args, _ = movie(**options)
    path = tmp_path / "invalid.mp4"
    path.write_bytes(original)
    result = java_finalizer(path, args_override or args)
    assert result.returncode == 2, result.stderr
    assert message in result.stderr
    assert path.read_bytes() == original


@pytest.mark.parametrize("mutate", [
    lambda raw: raw[:-3],
    lambda raw: raw + box("moov", b"duplicate"),
    lambda raw: box("moof", b"") + raw,
    lambda raw: raw[:16] + U32(0xffffffff) + raw[20:],
    lambda raw: raw.replace(b"stts", b"xxxx", 1),
])
def test_invalid_layout_never_changes_file(java_finalizer, tmp_path, mutate):
    original, args, _ = movie()
    damaged = mutate(original)
    path = tmp_path / "damaged.mp4"
    path.write_bytes(damaged)
    result = java_finalizer(path, args)
    assert result.returncode == 2, result.stderr
    assert path.read_bytes() == damaged


def test_missing_file_is_not_created(java_finalizer, tmp_path):
    missing = tmp_path / "missing.mp4"
    result = java_finalizer(missing, (48000, 50000, 2048, 52))
    assert result.returncode == 2 and not missing.exists()
