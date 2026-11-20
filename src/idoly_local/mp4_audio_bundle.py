"""Prepare a private, readable AudioClip bundle without touching game storage.

Only manifest-verified sud_music_* bundles with the audited serialized-file 22
AudioClip/AssetBundle schemas are accepted. UnityFS blocks are decoded with a
bounded pure-Python LZ4 decoder and repacked uncompressed. The FSB resource stays
byte-for-byte identical: Unity's original decoder supplies PCM later.

No paths, URLs, runtime dependencies or original cache mutations are involved.
The caller must publish the returned bytes in its private export workspace and
keep them alive until the private AssetBundle and AudioClip are unloaded.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
import secrets
import struct

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 96 * 1024 * 1024
MAX_SERIALIZED_BYTES = 1024 * 1024
_NAME = re.compile(r"sud_music_[a-z0-9][a-z0-9_-]{0,111}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CAB = re.compile(r"CAB-([0-9a-f]{32})\Z")
# Standard Unity type-tree common-string offsets used by the admitted schemas.
_COMMON = {49: "Array", 55: "Base", 76: "bool", 81: "char", 106: "data",
    155: "first", 161: "float", 222: "int", 241: "map", 427: "m_Name", 543: "pair",
    633: "PPtr<Object>", 778: "second", 795: "size", 814: "SInt64", 840: "string",
    921: "UInt64", 934: "unsigned int", 981: "vector", 1152: "FileSize"}
# Independent UnityPy 1.25.4 readback of both pinned Android/iOS samples.
# Hashes cover every type-tree node's depth/type/name/size/flags/version/refhash.
_SCHEMAS = {
    142: ("97da5f4688e45a57c8b42d4f42497297",
          "98045e6af88b5c3e8b66855263dd9595cc227b8837b82271ae794ce9be5c9be3"),
    83: ("57a6370a001d5449abd37c2184ec5138",
         "5ccf4d19ada1aaaef0813bceda3987a1cd5076222b65a0655c8eb222e39a8162"),
}


class AudioBundleError(ValueError):
    """Fixed failure codes, without source paths or remote addresses."""
    def __init__(self, code="audio_bundle_invalid"):
        self.code = code
        super().__init__(code)


def _need(condition, code="audio_bundle_invalid"):
    if not condition:
        raise AudioBundleError(code)


class _Reader:
    def __init__(self, data, endian=">", *, start=0, end=None):
        self.data, self.endian, self.pos = data, endian, start
        self.end = len(data) if end is None else end
        _need(0 <= self.pos <= self.end <= len(data))

    def take(self, size):
        _need(type(size) is int and 0 <= size <= self.end - self.pos)
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def number(self, code):
        size = struct.calcsize(code)
        return struct.unpack(self.endian + code, self.take(size))[0]

    def align(self, size=4):
        aligned = (self.pos + size - 1) // size * size
        _need(aligned <= self.end and not any(self.take(aligned - self.pos)))

    def cstring(self, limit=256):
        stop = self.data.find(b"\0", self.pos, min(self.end, self.pos + limit + 1))
        _need(stop >= self.pos)
        try:
            value = self.data[self.pos:stop].decode("ascii")
        except UnicodeError:
            raise AudioBundleError() from None
        self.pos = stop + 1
        return value


def _lz4(raw, size):
    _need(type(raw) is bytes and type(size) is int and 0 < size <= MAX_EXPANDED_BYTES)
    output = bytearray()
    at = 0
    while at < len(raw):
        token = raw[at]
        at += 1
        literal = token >> 4
        if literal == 15:
            while True:
                _need(at < len(raw))
                extra = raw[at]; at += 1
                literal += extra
                _need(literal <= size - len(output))
                if extra != 255:
                    break
        _need(literal <= len(raw) - at and literal <= size - len(output))
        output.extend(raw[at:at + literal]); at += literal
        if at == len(raw):
            break
        _need(at + 2 <= len(raw))
        offset = raw[at] | raw[at + 1] << 8
        at += 2
        _need(0 < offset <= len(output))
        count = (token & 15) + 4
        if token & 15 == 15:
            while True:
                _need(at < len(raw))
                extra = raw[at]; at += 1
                count += extra
                _need(count <= size - len(output))
                if extra != 255:
                    break
        _need(count <= size - len(output))
        # A distant four-byte match must not copy the entire dictionary.
        # Total copied match bytes remain proportional to the output bound.
        start = len(output) - offset
        pattern = bytes(output[start:start + min(offset, count)])
        output.extend(pattern * (count // offset) + pattern[:count % offset])
    _need(len(output) == size)
    return bytes(output)


def _decompress(raw, size, flags):
    mode = flags & 63
    _need(flags & ~0x243 == 0 and mode in (0, 2, 3), "audio_bundle_compression_unsupported")
    if mode == 0:
        _need(len(raw) == size)
        return raw
    return _lz4(raw, size)


@dataclass(frozen=True)
class _Entry:
    name: str
    flags: int
    data: bytes


@dataclass(frozen=True)
class _Archive:
    version: int
    player: str
    engine: str
    entries: tuple


def _unpack_fs(raw):
    reader = _Reader(raw)
    _need(reader.cstring(16) == "UnityFS")
    version = reader.number("I")
    _need(version == 8, "audio_bundle_version_unsupported")
    player, engine = reader.cstring(32), reader.cstring(32)
    _need(player == "5.x.x" and engine in ("0.0.0", "2022.3.57f1"),
          "audio_bundle_version_unsupported")
    total, compressed_size, info_size, flags = (reader.number(code) for code in ("Q", "I", "I", "I"))
    _need(total == len(raw) and 0 < compressed_size <= 65536 and 0 < info_size <= 65536)
    _need(flags & ~0x2c3 == 0 and flags & 0x40 and flags & 63 in (0, 2, 3),
          "audio_bundle_compression_unsupported")
    reader.align(16)
    data_start = reader.pos
    if flags & 0x80:
        _need(compressed_size <= len(raw) - data_start)
        compressed = raw[-compressed_size:]
        data_end = len(raw) - compressed_size
    else:
        compressed = reader.take(compressed_size)
        data_start, data_end = reader.pos, len(raw)
    info = _Reader(_decompress(compressed, info_size, flags & ~0x80))
    info.take(16)
    blocks = info.number("i")
    _need(1 <= blocks <= 1024)
    descriptions, expanded, stored = [], 0, 0
    for _ in range(blocks):
        unpacked, packed, block_flags = info.number("I"), info.number("I"), info.number("H")
        _need(0 < unpacked <= 8 * 1024 * 1024 and 0 < packed <= MAX_BUNDLE_BYTES)
        expanded += unpacked; stored += packed
        _need(expanded <= MAX_EXPANDED_BYTES and stored <= MAX_BUNDLE_BYTES)
        descriptions.append((unpacked, packed, block_flags))
    count = info.number("i")
    _need(count == 2, "audio_bundle_layout_unsupported")
    nodes = []
    for _ in range(count):
        offset, length, node_flags = info.number("Q"), info.number("Q"), info.number("I")
        name = info.cstring(128)
        _need(0 <= offset <= expanded and 0 < length <= expanded - offset)
        nodes.append((offset, length, node_flags, name))
    _need(info.pos == info.end)
    reader.pos, reader.end = data_start, data_end
    if flags & 0x200:
        reader.align(16)
    _need(stored == reader.end - reader.pos)
    payload = b"".join(_decompress(reader.take(packed), unpacked, block_flags)
                       for unpacked, packed, block_flags in descriptions)
    _need(len(payload) == expanded)
    cursor = 0
    entries = []
    for offset, length, node_flags, name in sorted(nodes):
        _need(offset >= cursor and offset - cursor <= 16 and not any(payload[cursor:offset]))
        entries.append(_Entry(name, node_flags, payload[offset:offset + length]))
        cursor = offset + length
    _need(cursor == len(payload))
    _need(_CAB.fullmatch(entries[0].name) is not None and entries[0].flags == 4
          and entries[1].name == entries[0].name + ".resource" and entries[1].flags == 0,
          "audio_bundle_layout_unsupported")
    _need(len(entries[0].data) <= MAX_SERIALIZED_BYTES and entries[1].data.startswith(b"FSB5"),
          "audio_bundle_layout_unsupported")
    return _Archive(version, player, engine, tuple(entries))


def _pack_fs(archive):
    payload = b"".join(entry.data for entry in archive.entries)
    _need(0 < len(payload) <= MAX_EXPANDED_BYTES)
    info = bytearray(bytes(16))
    block_size = 128 * 1024
    blocks = [payload[start:start + block_size] for start in range(0, len(payload), block_size)]
    info.extend(struct.pack(">i", len(blocks)))
    for block in blocks:
        info.extend(struct.pack(">IIH", len(block), len(block), 0))
    info.extend(struct.pack(">i", len(archive.entries)))
    offset = 0
    for entry in archive.entries:
        info.extend(struct.pack(">QQI", offset, len(entry.data), entry.flags))
        info.extend(entry.name.encode("ascii") + b"\0")
        offset += len(entry.data)
    prefix = b"UnityFS\0" + struct.pack(">I", archive.version)
    prefix += archive.player.encode() + b"\0" + archive.engine.encode() + b"\0"
    header = prefix + struct.pack(">QIII", 0, len(info), len(info), 0x240)
    header += bytes((-len(header)) % 16)
    combined = header + info
    combined += bytes((-len(combined)) % 16)
    combined += payload
    _need(len(combined) <= MAX_EXPANDED_BYTES + 65536)
    return combined[:len(prefix)] + struct.pack(">Q", len(combined)) + combined[len(prefix) + 8:]


@dataclass(frozen=True)
class _Node:
    depth: int
    type: str
    name: str
    size: int
    flags: int
    version: int
    type_flags: int
    ref_hash: int
    children: tuple = ()

    def row(self):
        return [self.depth, self.type, self.name, self.size, self.flags,
                self.version, self.type_flags, self.ref_hash]


def _tree(reader, class_id, type_hash):
    count, string_size = reader.number("i"), reader.number("i")
    _need(1 <= count <= 128 and 1 <= string_size <= 8192)
    raw_nodes = reader.take(count * 32)
    strings = reader.take(string_size)
    def text(offset):
        if offset & 0x80000000:
            result = _COMMON.get(offset & 0x7fffffff)
            _need(result is not None, "audio_bundle_schema_unsupported")
            return result
        _need(offset < len(strings))
        return _Reader(strings, start=offset).cstring(256)
    rows = []
    for node_index, values in enumerate(struct.iter_unpack(reader.endian + "hBBIIiiiQ", raw_nodes)):
        version, depth, type_flags, kind, name, size, index, flags, ref_hash = values
        _need(0 <= depth <= 12 and index == node_index and -1 <= size <= 1024)
        rows.append(_Node(depth, text(kind), text(name), size, flags, version, type_flags, ref_hash))
    digest = hashlib.sha256(json.dumps([row.row() for row in rows], separators=(",", ":")).encode()).hexdigest()
    _need(class_id in _SCHEMAS and (type_hash.hex(), digest) == _SCHEMAS[class_id],
          "audio_bundle_schema_unsupported")
    def build(index):
        row = rows[index]; children = []; following = index + 1
        while following < count and rows[following].depth > row.depth:
            _need(rows[following].depth == row.depth + 1)
            child, following = build(following)
            children.append(child)
        return _Node(*row.row(), tuple(children)), following
    root, end = build(0)
    _need(rows[0].depth == 0 and end == count)
    return root


_PRIMITIVES = {"int": ("i", 4), "unsigned int": ("I", 4), "SInt64": ("q", 8),
    "UInt64": ("Q", 8), "FileSize": ("Q", 8), "float": ("f", 4),
    "bool": ("B", 1), "char": ("B", 1)}


def _walk(node, reader, spans, path=(), budget=None):
    if budget is None:
        budget = [8192]
    budget[0] -= 1
    _need(budget[0] >= 0)
    start = reader.pos
    if node.type == "string":
        length = reader.number("i")
        _need(0 <= length <= 4096)
        at = reader.pos
        try:
            value = reader.take(length).decode("ascii")
        except UnicodeError:
            raise AudioBundleError() from None
        _need("\0" not in value)
        spans[path] = (at, length)
        reader.align()
    elif node.type == "Array":
        _need(len(node.children) == 2 and node.children[0].type == "int")
        count = reader.number("i")
        _need(0 <= count <= 1024)
        value = [_walk(node.children[1], reader, spans, path + (i,), budget) for i in range(count)]
    elif node.type in _PRIMITIVES:
        code, size = _PRIMITIVES[node.type]
        _need(node.size == size and not node.children)
        value = reader.number(code)
        _need(node.type != "bool" or value in (0, 1))
        spans[path] = (start, size)
    elif len(node.children) == 1 and node.children[0].type == "Array":
        value = _walk(node.children[0], reader, spans, path, budget)
    else:
        _need(node.children)
        value = {}
        for child in node.children:
            _need(child.name not in value)
            value[child.name] = _walk(child, reader, spans, path + (child.name,), budget)
    if node.flags & 0x4000:
        reader.align()
    return value


def _serialized(data, expected_name, *, bundle_name=None):
    header = _Reader(data)
    first_size, first_total, version, first_offset = (header.number("I") for _ in range(4))
    _need(version == 22 and first_size == first_total == first_offset == 0,
          "audio_bundle_version_unsupported")
    endian = header.number("B")
    _need(endian == 0 and header.take(3) == bytes(3), "audio_bundle_version_unsupported")
    metadata, total, data_offset, unknown = (header.number(code) for code in ("I", "Q", "Q", "Q"))
    _need(total == len(data) and unknown == 0 and 0 < metadata <= MAX_SERIALIZED_BYTES
          and 48 + metadata <= data_offset <= len(data))
    reader = _Reader(data, "<", start=48, end=48 + metadata)
    unity, platform, enabled = reader.cstring(32), reader.number("i"), reader.number("B")
    _need(unity in ("0.0.0", "2022.3.57f1") and platform in (9, 13) and enabled == 1,
          "audio_bundle_version_unsupported")
    _need(reader.number("i") == 2, "audio_bundle_layout_unsupported")
    types = []
    for _ in range(2):
        class_id, stripped, script_index = reader.number("i"), reader.number("B"), reader.number("h")
        _need(class_id in _SCHEMAS and stripped == 0 and script_index == -1)
        tree = _tree(reader, class_id, reader.take(16))
        _need(reader.number("i") == 0, "audio_bundle_layout_unsupported")
        types.append((class_id, tree))
    _need({kind for kind, _ in types} == {83, 142} and reader.number("i") == 2,
          "audio_bundle_layout_unsupported")
    objects = []
    ids = set()
    for _ in range(2):
        reader.align()
        path_id, offset, length, type_id = (reader.number(code) for code in ("q", "Q", "I", "i"))
        _need(path_id != 0 and path_id not in ids and type_id in (0, 1)
              and 0 < length <= 65536 and offset + length <= len(data) - data_offset)
        ids.add(path_id)
        objects.append((data_offset + offset, length, *types[type_id], path_id))
    _need(reader.number("i") == reader.number("i") == reader.number("i") == 0,
          "audio_bundle_layout_unsupported")
    _need(reader.cstring(32) == "" and reader.pos == reader.end)
    _need(not any(data[reader.end:data_offset]))
    cursor, result = data_offset, {}
    for offset, length, kind, tree, path_id in sorted(objects):
        _need(kind not in result and offset >= cursor and offset - cursor <= 16
              and not any(data[cursor:offset]))
        obj_reader = _Reader(data, "<", start=offset, end=offset + length)
        spans = {}
        value = _walk(tree, obj_reader, spans)
        admitted_name = (bundle_name or expected_name) if kind == 142 else expected_name
        _need(obj_reader.pos == obj_reader.end and value.get("m_Name") == admitted_name,
              "audio_bundle_layout_unsupported")
        result[kind] = (value, spans, path_id)
        cursor = offset + length
    _need(cursor == len(data) and set(result) == {83, 142})
    return result, platform


@dataclass(frozen=True)
class PreparedAudioBundle:
    bundle_bytes: bytes
    clip_name: str
    bundle_name: str
    cab_name: str
    channels: int
    frequency: int
    bits_per_sample: int
    length_seconds: float
    resource_bytes: int
    resource_sha256: str
    source_md5: str
    bundle_sha256: str
    platform: str


def prepare_audio_bundle(raw, *, name, expected_size, expected_md5, expected_sha256=None,
                         expected_platform=None, nonce=None):
    """Return a uniquely named private copy; original raw/game bytes stay intact.

    The trusted manifest caller supplies the selected logical name, exact size
    and MD5. A supplied nonce must be a fresh 32-hex export-session identifier;
    normally this function generates it with the OS random source.
    """
    _need(type(name) is str and _NAME.fullmatch(name) is not None, "audio_bundle_identity_invalid")
    _need(expected_platform is None or type(expected_platform) is str
          and expected_platform in ("android", "ios"), "audio_bundle_identity_invalid")
    _need(type(expected_size) is int and 0 < expected_size <= MAX_BUNDLE_BYTES
          and type(raw) is bytes and len(raw) == expected_size
          and type(expected_md5) is str and _HEX32.fullmatch(expected_md5) is not None
          and hashlib.md5(raw, usedforsecurity=False).hexdigest() == expected_md5,
          "audio_bundle_identity_invalid")
    if expected_sha256 is not None:
        _need(type(expected_sha256) is str and _HEX64.fullmatch(expected_sha256) is not None
              and hashlib.sha256(raw).hexdigest() == expected_sha256, "audio_bundle_identity_invalid")
    if nonce is None:
        nonce = secrets.token_hex(16)
    _need(type(nonce) is str and _HEX32.fullmatch(nonce) is not None, "audio_bundle_identity_invalid")
    if raw.startswith(b"UnityFS\0"):
        decoded = raw
    else:
        seed = bytearray(len(name) * 2)
        for index, value in enumerate(name.encode("ascii")):
            seed[index * 2] = value
            seed[len(seed) - 1 - index * 2] = value ^ 255
        checksum = 0x9b
        for value in seed:
            checksum = ((checksum & 1) << 7 | checksum >> 1) ^ value
        key = bytes(value ^ checksum for value in seed)
        decoded = bytes(value ^ key[index % len(key)] for index, value in enumerate(raw[:256])) + raw[256:]
    archive = _unpack_fs(decoded)
    serialized, resource = archive.entries
    values, platform = _serialized(serialized.data, name)
    platform_name = "android" if platform == 13 else "ios"
    _need(expected_platform is None or expected_platform == platform_name, "audio_bundle_identity_invalid")
    clip, clip_spans, clip_id = values[83]
    bundle, bundle_spans, _bundle_id = values[142]
    source = "archive:/" + serialized.name + "/" + resource.name
    _need(clip["m_LoadType"] == 2 and clip["m_PreloadAudioData"] in (0, 1)
          and clip["m_LoadInBackground"] in (0, 1) and clip["m_IsTrackerFormat"] == 0
          and clip["m_Ambisonic"] == 0 and clip["m_SubsoundIndex"] == 0
          and clip["m_CompressionFormat"] == 1 and clip["m_Resource"]["m_Source"] == source
          and clip["m_Resource"]["m_Offset"] == 0
          and clip["m_Resource"]["m_Size"] == len(resource.data),
          "audio_bundle_clip_unsupported")
    _need(1 <= clip["m_Channels"] <= 8 and 8000 <= clip["m_Frequency"] <= 192000
          and clip["m_BitsPerSample"] in (16, 24, 32)
          and math.isfinite(clip["m_Length"]) and 0 < clip["m_Length"] <= 3600,
          "audio_bundle_clip_unsupported")
    _need(bundle["m_AssetBundleName"] == name and not bundle["m_Dependencies"]
          and bundle["m_IsStreamedSceneAssetBundle"] == 0
          and len(bundle["m_Container"]) == len(bundle["m_PreloadTable"]) == 1
          and bundle["m_Container"][0]["first"] == name
          and bundle["m_Container"][0]["second"]["asset"] == {"m_FileID": 0, "m_PathID": clip_id}
          and bundle["m_PreloadTable"][0] == {"m_FileID": 0, "m_PathID": clip_id},
          "audio_bundle_clip_unsupported")
    cab = "CAB-" + nonce
    unique_name = ("mp4_" + hashlib.sha256((nonce + name).encode()).hexdigest() * 2)[:len(name)]
    _need(cab != serialized.name and unique_name != name)
    changed = bytearray(serialized.data)
    def patch(spans, field, raw_value):
        start, length = spans[field]
        _need(len(raw_value) == length)
        changed[start:start + length] = raw_value
    patch(clip_spans, ("m_LoadType",), struct.pack("<i", 0))
    patch(clip_spans, ("m_PreloadAudioData",), b"\1")
    patch(clip_spans, ("m_LoadInBackground",), b"\0")
    patch(clip_spans, ("m_Resource", "m_Source"), ("archive:/" + cab + "/" + cab + ".resource").encode())
    for field in ("m_Name", "m_AssetBundleName"):
        patch(bundle_spans, (field,), unique_name.encode())
    updated = _Archive(archive.version, archive.player, archive.engine,
        (_Entry(cab, serialized.flags, bytes(changed)), _Entry(cab + ".resource", resource.flags, resource.data)))
    output = _pack_fs(updated)
    # A second metadata read verifies the produced file rather than assuming
    # that dynamic string alignment or object order stayed as expected.
    check = _unpack_fs(output)
    checked, checked_platform = _serialized(check.entries[0].data, name, bundle_name=unique_name)
    _need(checked_platform == platform and check.entries[1].data == resource.data
          and checked[83][0]["m_LoadType"] == 0
          and checked[83][0]["m_PreloadAudioData"] == 1
          and checked[83][0]["m_LoadInBackground"] == 0
          and checked[142][0]["m_AssetBundleName"] == unique_name)
    return PreparedAudioBundle(output, name, unique_name, cab, clip["m_Channels"], clip["m_Frequency"],
        clip["m_BitsPerSample"], clip["m_Length"], len(resource.data),
        hashlib.sha256(resource.data).hexdigest(), expected_md5, hashlib.sha256(output).hexdigest(),
        platform_name)
