"""Finite UnityFS/serialized22 conversion; no decoder or game cache mutation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from idoly_local import mp4_audio_bundle as audio
from idoly_local.mp4_audio_bundle import AudioBundleError, prepare_audio_bundle

NAME = "sud_music_short_tri-004"
CAB = "CAB-a6930837b387dee77f81c34c3fd30443"
RESOURCE = b"FSB5" + bytes(range(256)) * 7
AUDIO_ROWS = [[0,"AudioClip","Base",-1,32768,1,0,0],[1,"string","m_Name",-1,557057,1,0,0],[2,"Array","Array",-1,540673,1,1,0],[3,"int","size",4,524289,1,0,0],[3,"char","data",1,524289,1,0,0],[1,"int","m_LoadType",4,0,1,0,0],[1,"int","m_Channels",4,0,1,0,0],[1,"int","m_Frequency",4,0,1,0,0],[1,"int","m_BitsPerSample",4,0,1,0,0],[1,"float","m_Length",4,0,1,0,0],[1,"bool","m_IsTrackerFormat",1,0,1,0,0],[1,"bool","m_Ambisonic",1,16384,1,0,0],[1,"int","m_SubsoundIndex",4,0,1,0,0],[1,"bool","m_PreloadAudioData",1,0,1,0,0],[1,"bool","m_LoadInBackground",1,0,1,0,0],[1,"bool","m_Legacy3D",1,16384,1,0,0],[1,"StreamedResource","m_Resource",-1,32768,1,0,0],[2,"string","m_Source",-1,32769,1,0,0],[3,"Array","Array",-1,16385,1,1,0],[4,"int","size",4,1,1,0,0],[4,"char","data",1,1,1,0,0],[2,"FileSize","m_Offset",8,1,1,0,0],[2,"UInt64","m_Size",8,1,1,0,0],[1,"int","m_CompressionFormat",4,16384,1,0,0]]
BUNDLE_ROWS = [[0,"AssetBundle","Base",-1,32768,3,0,0],[1,"string","m_Name",-1,557057,1,0,0],[2,"Array","Array",-1,540673,1,1,0],[3,"int","size",4,524289,1,0,0],[3,"char","data",1,524289,1,0,0],[1,"vector","m_PreloadTable",-1,32768,1,0,0],[2,"Array","Array",-1,16384,1,1,0],[3,"int","size",4,0,1,0,0],[3,"PPtr<Object>","data",12,0,1,0,0],[4,"int","m_FileID",4,8388609,1,0,0],[4,"SInt64","m_PathID",8,8388609,1,0,0],[1,"map","m_Container",-1,32768,1,0,0],[2,"Array","Array",-1,32768,1,1,0],[3,"int","size",4,0,1,0,0],[3,"pair","data",-1,32768,1,0,0],[4,"string","first",-1,32768,1,0,0],[5,"Array","Array",-1,16385,1,1,0],[6,"int","size",4,1,1,0,0],[6,"char","data",1,1,1,0,0],[4,"AssetInfo","second",20,0,1,0,0],[5,"int","preloadIndex",4,0,1,0,0],[5,"int","preloadSize",4,0,1,0,0],[5,"PPtr<Object>","asset",12,0,1,0,0],[6,"int","m_FileID",4,8388609,1,0,0],[6,"SInt64","m_PathID",8,8388609,1,0,0],[1,"AssetInfo","m_MainAsset",20,0,1,0,0],[2,"int","preloadIndex",4,0,1,0,0],[2,"int","preloadSize",4,0,1,0,0],[2,"PPtr<Object>","asset",12,0,1,0,0],[3,"int","m_FileID",4,8388609,1,0,0],[3,"SInt64","m_PathID",8,8388609,1,0,0],[1,"unsigned int","m_RuntimeCompatibility",4,0,1,0,0],[1,"string","m_AssetBundleName",-1,32768,1,0,0],[2,"Array","Array",-1,16385,1,1,0],[3,"int","size",4,1,1,0,0],[3,"char","data",1,1,1,0,0],[1,"vector","m_Dependencies",-1,32768,1,0,0],[2,"Array","Array",-1,49152,1,1,0],[3,"int","size",4,0,1,0,0],[3,"string","data",-1,32768,1,0,0],[4,"Array","Array",-1,16385,1,1,0],[5,"int","size",4,1,1,0,0],[5,"char","data",1,1,1,0,0],[1,"bool","m_IsStreamedSceneAssetBundle",1,16384,1,0,0],[1,"int","m_ExplicitDataLayout",4,0,1,0,0],[1,"int","m_PathFlags",4,0,1,0,0],[1,"map","m_SceneHashes",-1,32768,1,0,0],[2,"Array","Array",-1,32768,1,1,0],[3,"int","size",4,0,1,0,0],[3,"pair","data",-1,32768,1,0,0],[4,"string","first",-1,32768,1,0,0],[5,"Array","Array",-1,16385,1,1,0],[6,"int","size",4,1,1,0,0],[6,"char","data",1,1,1,0,0],[4,"string","second",-1,32768,1,0,0],[5,"Array","Array",-1,16385,1,1,0],[6,"int","size",4,1,1,0,0],[6,"char","data",1,1,1,0,0]]


def aligned_string(value):
    value = value.encode()
    result = struct.pack("<i", len(value)) + value
    return result + bytes(-len(result) % 4)


def tree_blob(rows):
    strings, offsets = bytearray(), {}
    for row in rows:
        for value in row[1:3]:
            if value not in offsets:
                offsets[value] = len(strings)
                strings.extend(value.encode() + b"\0")
    nodes = bytearray()
    for index, (depth, kind, name, size, flags, version, type_flags, ref_hash) in enumerate(rows):
        nodes.extend(struct.pack("<hBBIIiiiQ", version, depth, type_flags, offsets[kind],
            offsets[name], size, index, flags, ref_hash))
    return struct.pack("<ii", len(rows), len(strings)) + nodes + strings


def serialized(name=NAME, *, platform=13, audio_values=None, tree_rows=None, resource=RESOURCE):
    source = "archive:/" + CAB + "/" + CAB + ".resource"
    bundle = aligned_string(name) + struct.pack("<iiq", 1, 0, 23)
    bundle += struct.pack("<i", 1) + aligned_string(name) + struct.pack("<iiiq", 0, 1, 0, 23)
    bundle += struct.pack("<iiiqI", 0, 0, 0, 0, 1) + aligned_string(name)
    bundle += struct.pack("<iB", 0, 0) + bytes(3) + struct.pack("<iii", 1, 0, 0)
    values = dict(load=2, channels=2, frequency=48000, bits=16, length=116.0,
        tracker=0, ambisonic=0, subsound=0, preload=1, background=0, legacy=1,
        source=source, offset=0, size=len(resource), compression=1)
    values.update(audio_values or {})
    clip = aligned_string(name) + struct.pack("<iiiifBB", values["load"], values["channels"],
        values["frequency"], values["bits"], values["length"], values["tracker"], values["ambisonic"])
    clip += bytes(-len(clip) % 4) + struct.pack("<iBBB", values["subsound"], values["preload"],
        values["background"], values["legacy"])
    clip += bytes(-len(clip) % 4) + aligned_string(values["source"])
    clip += struct.pack("<QQi", values["offset"], values["size"], values["compression"])
    clip += bytes(-len(clip) % 4)
    metadata = b"0.0.0\0" + struct.pack("<iBi", platform, 1, 2)
    for class_id, rows in ((142, BUNDLE_ROWS), (83, tree_rows or AUDIO_ROWS)):
        metadata += struct.pack("<iBh", class_id, 0, -1) + bytes.fromhex(audio._SCHEMAS[class_id][0])
        metadata += tree_blob(rows) + struct.pack("<i", 0)
    metadata += struct.pack("<i", 2)
    metadata += bytes(-(len(metadata) + 48) % 4)
    metadata += struct.pack("<qQIi", 1, 0, len(bundle), 0)
    metadata += struct.pack("<qQIi", 23, len(bundle), len(clip), 1)
    metadata += struct.pack("<iii", 0, 0, 0) + b"\0"
    data_offset = (48 + len(metadata) + 15) // 16 * 16
    total = data_offset + len(bundle) + len(clip)
    header = struct.pack(">IIIIB3sIQQQ", 0, 0, 22, 0, 0, bytes(3), len(metadata), total, data_offset, 0)
    return header + metadata + bytes(data_offset - 48 - len(metadata)) + bundle + clip


def bundle(name=NAME, *, resource=RESOURCE, **kwargs):
    return audio._pack_fs(audio._Archive(8, "5.x.x", "0.0.0", (
        audio._Entry(CAB, 4, serialized(name, resource=resource, **kwargs)),
        audio._Entry(CAB + ".resource", 0, resource))))


def prepare(raw, name=NAME, **kwargs):
    return prepare_audio_bundle(raw, name=name, expected_size=len(raw),
        expected_md5=hashlib.md5(raw, usedforsecurity=False).hexdigest(), **kwargs)


def masked(raw, name):
    seed = bytearray(len(name) * 2)
    for index, value in enumerate(name.encode()):
        seed[index * 2] = value
        seed[len(seed) - 1 - index * 2] = value ^ 255
    checksum = 155
    for value in seed:
        checksum = ((checksum & 1) << 7 | checksum >> 1) ^ value
    key = bytes(value ^ checksum for value in seed)
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(raw[:256])) + raw[256:]


@pytest.mark.parametrize("platform,label", [(13, "android"), (9, "ios")])
@pytest.mark.parametrize("name", [NAME, "sud_music_x", "sud_music_" + "a" * 80])
def test_metadata_driven_patch_preserves_resource_and_only_changes_private_clip_loading(platform, label, name):
    original = bundle(name, platform=platform)
    result = prepare(masked(original, name), name, nonce="1" * 32)
    parsed = audio._unpack_fs(result.bundle_bytes)
    values, actual_platform = audio._serialized(parsed.entries[0].data, name, bundle_name=result.bundle_name)
    clip, clip_spans, _ = values[83]
    asset_bundle, spans, _ = values[142]
    assert result.platform == label and actual_platform == platform
    assert clip["m_Name"] == result.clip_name == name
    assert (clip["m_LoadType"], clip["m_PreloadAudioData"], clip["m_LoadInBackground"]) == (0, 1, 0)
    assert clip["m_Resource"]["m_Source"] == "archive:/" + result.cab_name + "/" + result.cab_name + ".resource"
    assert asset_bundle["m_Name"] == asset_bundle["m_AssetBundleName"] == result.bundle_name != name
    assert len(result.bundle_name) == len(name)
    assert asset_bundle["m_Container"][0]["first"] == name
    assert parsed.entries[0].name == result.cab_name and parsed.entries[1].name == result.cab_name + ".resource"
    assert parsed.entries[1].data == RESOURCE
    assert result.resource_sha256 == hashlib.sha256(RESOURCE).hexdigest() and result.resource_bytes == len(RESOURCE)
    assert (result.channels, result.frequency, result.bits_per_sample, result.length_seconds) == (2, 48000, 16, 116.0)
    assert result.bundle_sha256 == hashlib.sha256(result.bundle_bytes).hexdigest()
    assert original == bundle(name, platform=platform)
    # This proves exact field spans, rather than a search/replace over the FSB.
    old, _ = audio._serialized(audio._unpack_fs(original).entries[0].data, name)
    allowed = set()
    for key in (("m_LoadType",), ("m_PreloadAudioData",), ("m_LoadInBackground",), ("m_Resource", "m_Source")):
        at, size = old[83][1][key]; allowed.update(range(at, at + size))
    for key in (("m_Name",), ("m_AssetBundleName",)):
        at, size = old[142][1][key]; allowed.update(range(at, at + size))
    before, after = audio._unpack_fs(original).entries[0].data, parsed.entries[0].data
    assert len(before) == len(after)
    assert all(a == b or index in allowed for index, (a, b) in enumerate(zip(before, after)))


def test_resource_matching_cab_and_bundle_text_is_never_replaced():
    resource = b"FSB5" + CAB.encode() + NAME.encode() + bytes(range(100))
    result = prepare(bundle(resource=resource))
    assert audio._unpack_fs(result.bundle_bytes).entries[1].data == resource


def test_concurrent_exports_have_distinct_cab_and_bundle_names_and_deterministic_nonce_is_supported():
    raw = bundle()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: prepare(raw), range(12)))
    assert len({result.cab_name for result in results}) == len({result.bundle_name for result in results}) == 12
    assert prepare(raw, nonce="2" * 32).bundle_bytes == prepare(raw, nonce="2" * 32).bundle_bytes


@pytest.mark.parametrize("kwargs", [{"name": "../sud_music_test"}, {"name": "mdl_other"},
    {"name": "sud_music_X"}, {"expected_size": True}, {"expected_size": audio.MAX_BUNDLE_BYTES + 1},
    {"expected_size": 1}, {"expected_md5": "0" * 32}, {"expected_md5": "A" * 32},
    {"expected_sha256": "0" * 64}, {"nonce": "bad"}, {"nonce": CAB[4:]}])
def test_identity_and_private_namespace_fail_closed(kwargs, monkeypatch):
    raw = bundle()
    arguments = dict(name=NAME, expected_size=len(raw),
        expected_md5=hashlib.md5(raw, usedforsecurity=False).hexdigest())
    arguments.update(kwargs)
    with pytest.raises(AudioBundleError):
        prepare_audio_bundle(raw, **arguments)


@pytest.mark.parametrize("platform", ["ios", "windows", True, 13])
def test_requested_platform_must_match_original_unity_target(platform):
    with pytest.raises(AudioBundleError, match="identity_invalid"):
        prepare(bundle(platform=13), expected_platform=platform)


@pytest.mark.parametrize("values", [{"load": 0}, {"channels": 0}, {"channels": 9},
    {"frequency": 0}, {"bits": 8}, {"length": float("nan")}, {"length": 0},
    {"tracker": 1}, {"ambisonic": 1}, {"subsound": 1}, {"compression": 2},
    {"offset": 1}, {"size": len(RESOURCE) - 1}, {"source": "https://foreign.invalid/file"}])
def test_unsupported_clip_or_resource_identity_is_rejected(values):
    with pytest.raises(AudioBundleError):
        prepare(bundle(audio_values=values))


def test_modified_schema_is_rejected_instead_of_using_a_fixed_object_offset():
    rows = [list(row) for row in AUDIO_ROWS]
    rows[5][2] = "m_NotLoadType"
    with pytest.raises(AudioBundleError, match="schema_unsupported"):
        prepare(bundle(tree_rows=rows))


@pytest.mark.parametrize("raw,size", [(b"", 1), (b"\x10", 1), (b"\x10a", 2),
    (b"\x00\x00\x00", 4), (b"\xf0\xff", 100), (b"\x10a\x02\x00", 5),
    (b"\x1fa\x01\x00\xff", 600), (b"\x10a\x01", 5)])
def test_lz4_truncated_invalid_offsets_and_output_bounds(raw, size):
    with pytest.raises(AudioBundleError):
        audio._lz4(raw, size)


def test_lz4_literals_overlapping_matches_and_extended_match_lengths():
    assert audio._lz4(b"\x32abc\x03\x00", 9) == b"abcabcabc"
    assert audio._lz4(b"\x1fa\x01\x00\xff\x00", 275) == b"a" * 275
    assert audio._lz4(b"\xf0\x05" + b"b" * 20, 20) == b"b" * 20


@pytest.mark.parametrize("offset,raw_value", [(8, struct.pack(">I", 7)), (len(b"UnityFS\0")+4+6+6, b"\0"*8)])
def test_unityfs_header_version_and_extent_are_checked(offset, raw_value):
    raw = bytearray(bundle())
    raw[offset:offset + len(raw_value)] = raw_value
    with pytest.raises(AudioBundleError):
        prepare(bytes(raw))


def test_truncated_and_excess_trailing_unityfs_bytes_fail_closed():
    raw = bundle()
    for changed in (raw[:-1], raw[:48], raw + b"garbage"):
        with pytest.raises(AudioBundleError):
            prepare(changed)


def test_no_production_dependency_or_file_network_side_effects(monkeypatch):
    import builtins
    raw = bundle()
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: pytest.fail("No file access in byte preparation"))
    result = prepare(raw)
    assert result.bundle_bytes.startswith(b"UnityFS\0")


SAMPLES = Path("/workspace/shared/idoly-sdk-cache-analysis")

@pytest.mark.parametrize("platform", ["android", "ios"])
def test_actual_audited_song_bundles_have_identical_resource_after_private_roundtrip(platform):
    directory = SAMPLES / ("mp4-" + platform + "-analysis")
    if not (directory / "song-asset-proof.json").is_file():
        pytest.skip("Pinned public song sample is an optional local audit input")
    proof = json.loads((directory / "song-asset-proof.json").read_text())
    row = proof["row"]; source = directory / (row["name"] + ".bin")
    before = source.read_bytes()
    result = prepare_audio_bundle(before, name=row["name"], expected_size=row["size"],
        expected_md5=row["md5"], expected_sha256=proof["raw_sha256"])
    assert result.platform == platform and result.resource_bytes == 2414880
    assert result.resource_sha256 == "e56096ca71957c65a034191fead878a9187c15673b4868d4e0705ba29fb9e6b9"
    assert result.length_seconds == 116.0 and source.read_bytes() == before
    parsed = audio._unpack_fs(result.bundle_bytes)
    values, _ = audio._serialized(parsed.entries[0].data, row["name"], bundle_name=result.bundle_name)
    assert values[83][0]["m_LoadType"] == 0 and values[142][0]["m_Name"] == result.bundle_name


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_independent_pinned_unitypy_readback_keeps_original_clip_name_and_resource(platform, tmp_path):
    python = Path(os.environ.get("IDOLY_UNITYPY_PYTHON", "/workspace/.setup/venvs/toolkit/bin/python"))
    directory = SAMPLES / ("mp4-" + platform + "-analysis")
    if not python.is_file() or not (directory / "song-asset-proof.json").is_file():
        pytest.skip("Independent pinned UnityPy audit environment is optional")
    proof = json.loads((directory / "song-asset-proof.json").read_text())
    row = proof["row"]; raw = (directory / (row["name"] + ".bin")).read_bytes()
    result = prepare_audio_bundle(raw, name=row["name"], expected_size=row["size"], expected_md5=row["md5"])
    target = tmp_path / "private.bundle"; target.write_bytes(result.bundle_bytes)
    script = """
import hashlib,json,sys
from pathlib import Path
import UnityPy
assert UnityPy.__version__ == '1.25.4'
UnityPy.config.FALLBACK_UNITY_VERSION='2022.3.57f1'
env=UnityPy.load(Path(sys.argv[1]).read_bytes())
values={obj.class_id:obj.read_typetree() for obj in env.objects}
bundle=next(iter(env.files.values()))
resource=next(value.bytes for key,value in bundle.files.items() if key.endswith('.resource'))
print(json.dumps({'clip':values[83], 'bundle':values[142], 'resource_sha256':hashlib.sha256(resource).hexdigest()}))
"""
    output = subprocess.run([str(python), "-c", script, str(target)],
        check=True, capture_output=True, text=True, timeout=20)
    observed = json.loads(output.stdout)
    assert observed["clip"]["m_Name"] == row["name"]
    assert observed["clip"]["m_LoadType"] == 0 and observed["clip"]["m_PreloadAudioData"] is True
    assert observed["clip"]["m_LoadInBackground"] is False
    assert observed["bundle"]["m_Name"] == observed["bundle"]["m_AssetBundleName"] == result.bundle_name
    assert observed["bundle"]["m_Container"][0][0] == row["name"]
    assert observed["resource_sha256"] == result.resource_sha256
