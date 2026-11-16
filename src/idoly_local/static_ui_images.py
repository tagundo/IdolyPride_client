"""Offline, pinned Korean sprite data; no game-time image replacement.

Each original Sprite keeps its object ID, normalized pivot, border and scale.
New replacements use the translated PNG rectangle, as Localify does; the
original seven retain their previous padded rectangle for compatibility. Fixed
Love button labels use the original UI rectangle with a centered, uniform fit;
changing their Sprite rectangle alone stretches Korean glyphs in fixed Images.
A separate RGBA32 texture and full rectangle mesh replace its atlas dependency,
so no neighbouring atlas pixels are decoded or recompressed. Original image
translation data remains subject to its upstream terms (NOASSERTION).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import stat
import struct

from . import font_assets

POLICY = "korean-static-sprites-v2"
LEGACY_POLICY = "korean-static-sprites-v1"
TEXT_LAYOUT_POLICY = "original-rect-love-text-v1"
# The reported Love buttons retain their original fixed-size Image rectangle.
# Retain each approved original rectangle, rather than stretching short Korean
# words to the Japanese caption width. PNG identities stay in the frozen input
# catalog. Only MAX needs a small uniform downscale; the rest retain every pixel.
FIXED_LOVE_TEXT = {
    "love_btn_achievement": ((280, 40), (250, 40)),
    "love_btn_fin": ((159, 40), (147, 40)),
    "love_btn_max": ((72, 28), (74, 28)),
    "love_btn_mission": ((80, 40), (78, 37)),
    "love_btn_playing": ((240, 48), (96, 48)),
    "love_btn_present": ((194, 40), (72, 40)),
    "love_btn_setting": ((80, 40), (75, 40)),
    "love_btn_status": ((192, 40), (185, 37)),
    "love_button_start": ((192, 48), (184, 48)),
    "love_header_level_label": ((96, 32), (96, 28)),
}
SOURCE_REPOSITORY = "https://github.com/CyleAR/ipr-translation-data-ko"
SOURCE_REVISION = "f6e5689bcd6878d962996edfd390c1442b926c0f"
TEXTURE_TEMPLATE_BYTES = 8340
TEXTURE_TEMPLATE_SHA256 = "cd14c7a999509a84225972f1de577290fbbbba735fd35bd8296379a7f2e2d463"
TYPE_HASHES = {28: "31f65ae343f671bf462f15c1b41e9768", 213: "7012a9da776ed53774e22013565dbbd2"}
MAX_PNG_BYTES = 1024 * 1024
MAX_SPRITE_BYTES = 64 * 1024
MAX_TEXTURE_BYTES = 16 * 1024 * 1024 + 64 * 1024
MAX_IMAGE_PIXELS = 4 * 1024 * 1024
LEGACY_PROFILES = (
    {"name": "grid_list_select", "png_bytes": 6084,
     "png_sha256": "46730f33157fc47ea508689f9edcc31d908674279628d8fe3bf31defdb6d9a75",
     "png_size": (152, 72), "sprite_size": (152, 72), "padding_offset": (0, 0),
     "android_member": "assets/bin/Data/534689407d2b04772bd983b80d76a59a",
     "android_bytes": 864, "android_sha256": "451b6c609d1d73e42cfd784df1475f82d21f617b699be709e0a9e16fdaef88e4",
     "android_object_sha256": "88c376958b8a9a98aec97a7d69ba59cc9c61d6024ce5a4faea80c0fad0b24b39",
     "ios_path_id": 867, "ios_relative_offset": 10858616, "ios_bytes": 672,
     "ios_sha256": "3d304948c42f5a29cd6a72cd2bef1301e22164c55fb660ed0f1634dba5c41c3f"},
    {"name": "grid_list_select_vertical", "png_bytes": 4073,
     "png_sha256": "7a5d5faa3eb743d23170cf5c4f5340792f6c82fe34a8f97d84ba448d42114686",
     "png_size": (59, 138), "sprite_size": (72, 152), "padding_offset": (7, 7),
     "android_member": "assets/bin/Data/ffda78dbc308644aab9f4ed66e2a3b63",
     "android_bytes": 860, "android_sha256": "40e0da3261dd90cfefb6d4ff5dfb503bd6f5b2731c53295da3bf5be22e450994",
     "android_object_sha256": "76a8150875f9c1151358feceec6caf86a7f5cf4d9a17cb903f31271b3fa0c250",
     "ios_path_id": 1619, "ios_relative_offset": 11604376, "ios_bytes": 668,
     "ios_sha256": "6c036f6d9413722171fc87bbb6b9973983b6bf69caac5e50a92991c1035fec01"},
    {'name': 'home_txt_live', 'png_bytes': 4564, 'png_sha256': '944408c2901917090aee5dbf8af5efdfcd4890cdde9b3763164cd8f8456734bf', 'png_size': (148, 64), 'sprite_size': (148, 64), 'padding_offset': (0, 0), 'android_member': 'assets/bin/Data/0c089c8bc2fe5429eac76b2f9c985e0e', 'android_bytes': 928, 'android_sha256': '39dc9f243ac51fde6f08c799039b803ad58d54a1761f8a8303749b32bf97b680', 'android_object_sha256': '45a1e55226e3755a477c7dcd014fc1e7d91b93ee69a6fceff1e9c9c6e9574b2c', 'ios_path_id': 567, 'ios_relative_offset': 10584424, 'ios_bytes': 736, 'ios_sha256': '5251caaa60bbf8a3ef7ee5f1e7198e3e6115e00066f5aa40df05f17c50a64880'},
    {'name': 'home_mission', 'png_bytes': 4796, 'png_sha256': 'ab00554d60114ae2f9a3a0a2dc39a6eb3f21ba076fb7a674f17ed869f112e61b', 'png_size': (140, 114), 'sprite_size': (140, 114), 'padding_offset': (0, 0), 'android_member': 'assets/bin/Data/501e376bed5594df28041b0df3c8a8b2', 'android_bytes': 1044, 'android_sha256': '685bce115938d27488dc7fc5db449fa49c91e438ccaac8f23d38cb8efcd5f231', 'android_object_sha256': '98f6ff352a85a00bc19a4832bda93888777a6962d1f5223df52a0b57d18be71e', 'ios_path_id': 851, 'ios_relative_offset': 10846928, 'ios_bytes': 852, 'ios_sha256': '2db4592cd64ca4f9ceceaf7a4dfd5811febdbbe7faadda10b9248e5c3c75a2f0'},
    {'name': 'home_new_story', 'png_bytes': 5143, 'png_sha256': 'fd0b8a59e58489e7b7e53cd7f1eae2a2ac72354050c7d1495960c2e4157e213d', 'png_size': (100, 114), 'sprite_size': (100, 114), 'padding_offset': (0, 0), 'android_member': 'assets/bin/Data/9335938c12a4a402da99d09da7c133ec', 'android_bytes': 976, 'android_sha256': 'f964f33e703d24dbcc37a8497847becfbf1de83dbda68d348d17f2f8f62d519b', 'android_object_sha256': '986ce4d8bed8eaf5c40093740c85aa8239adbcd36bbb6b96a82036ce668e32fd', 'ios_path_id': 1138, 'ios_relative_offset': 11140032, 'ios_bytes': 784, 'ios_sha256': '964c281e48f691509750ac952001d90dc3cd4e32d14d39c3f644bdf5f93895d3'},
    {'name': 'home_gift', 'png_bytes': 4700, 'png_sha256': '37c87c383440a0b1e283ca513c9f567c5c90ffa89f5a39f405b0faa398d70597', 'png_size': (100, 114), 'sprite_size': (100, 114), 'padding_offset': (0, 0), 'android_member': 'assets/bin/Data/c9ea5fce491b842d487678b954a703be', 'android_bytes': 904, 'android_sha256': '44959d9b980174d3663fa80d7c58134874baa66ee61b81d5ba2074bc5179b1a9', 'android_object_sha256': 'e6126fca7e32de79e3256332a875006a81cc81e58ffc53696397dd8bee97efdf', 'ios_path_id': 1376, 'ios_relative_offset': 11358592, 'ios_bytes': 712, 'ios_sha256': '054d80417af596b1c1e5abef5dc590e29ea0a221f5b6e51a6725b28bb1fbe275'},
    {'name': 'home_login_bonus', 'png_bytes': 4942, 'png_sha256': '2b2e18ecbe266f954d13aad3bec5aa49112ef907dbe4a38bf4ea19e05ce898ad', 'png_size': (116, 114), 'sprite_size': (116, 114), 'padding_offset': (0, 0), 'android_member': 'assets/bin/Data/df8df258f611a4d5eb279103f9f2be5d', 'android_bytes': 960, 'android_sha256': 'a54a926648925f5e54b47687d75073eb12c7f904a4bff2b962a100f25b7a722d', 'android_object_sha256': '4cfd7820beb5023f55e34207d5230d84cd616ca507b97ca9422e78cf3b049ee1', 'ios_path_id': 1480, 'ios_relative_offset': 11470088, 'ios_bytes': 768, 'ios_sha256': '6263b96ae185cbdf1656ae6ead89aa180b2db47e46504443f24e2da4a682d0b4'},
)


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _text_layout(profile):
    expected = FIXED_LOVE_TEXT.get(profile["name"])
    if expected is None:
        return profile
    size, png_size = expected
    targets = ([profile["android"]] if profile["android"] is not None else []) + profile["ios"]
    _need(tuple(profile["png_size"]) == png_size and targets
          and all(tuple(target["source_layout"]["sprite_size"]) == size for target in targets),
          "Fixed Love text layout differs from the original audited rectangle")
    scale = min(1., size[0] / png_size[0], size[1] / png_size[1])
    content = tuple(max(1, min(bound, round(value * scale))) for bound, value in zip(size, png_size))
    return {**profile, "sprite_size": list(size), "content_size": list(content),
            "padding_offset": [(bound - value) // 2 for bound, value in zip(size, content)],
            "layout_policy": TEXT_LAYOUT_POLICY, "render_key_policy": TEXT_LAYOUT_POLICY}


def _profiles():
    path = Path(__file__).resolve().parents[2] / "client-presentation/images/korean-static-sprites-v2.json"
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode)
          and 0 < path.stat().st_size <= 256 * 1024, "Expected bounded frozen static-image profile")
    data = json.loads(path.read_bytes())
    _need(data.get("schema") == 2 and data.get("policy") == POLICY
          and data.get("source") == {"repository": SOURCE_REPOSITORY, "revision": SOURCE_REVISION,
                                     "data_terms": "NOASSERTION"}, "Frozen static-image provenance differs")
    profiles = data["inputs"]
    _need(len(profiles) == data["input_count"] == 138
          and len({row["name"] for row in profiles}) == len(profiles), "Frozen image roster differs")
    legacy = {row["name"]: row for row in LEGACY_PROFILES}
    for row in profiles:
        _need(row["name"] and all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in row["name"])
              and 0 < row["png_bytes"] <= MAX_PNG_BYTES
              and len(row["png_sha256"]) == 64 and row["png_color_type"] in (2, 6)
              and len(row["png_size"]) == 2
              and all(type(v) is int and 0 < v <= 4096 for v in row["png_size"])
              and row["png_size"][0] * row["png_size"][1] <= MAX_IMAGE_PIXELS,
              "Frozen PNG bounds differ")
        if row["name"] in legacy:
            old = legacy[row["name"]]
            _need(row["layout_policy"] == "preserved-v1-layout"
                  and row["render_key_policy"] == LEGACY_POLICY
                  and tuple(row["sprite_size"]) == old["sprite_size"]
                  and tuple(row["padding_offset"]) == old["padding_offset"]
                  and row["png_sha256"] == old["png_sha256"], "Legacy image layout changed")
        else:
            _need(row["layout_policy"] == "localify-png-rect"
                  and row["render_key_policy"] == POLICY
                  and row["sprite_size"] == row["png_size"] and row["padding_offset"] == [0, 0],
                  "New image must retain its exact translated PNG rectangle")
        for target in ([row["android"]] if row["android"] is not None else []) + row["ios"]:
            layout = target["source_layout"]
            _need(0 < target["bytes"] <= MAX_SPRITE_BYTES and target["path_id"] > 0
                  and len(target["object_sha256"]) == 64
                  and layout["pivot"] == [0.5, 0.5] and layout["offset"] == [0.0, 0.0]
                  and layout["rect_xy"] == [0.0, 0.0] and layout["pixels_per_unit"] == 100
                  and layout["bones"] == 0 and len(layout["border"]) == 4,
                  "Frozen Sprite target/layout differs")
    _need(sum(row["android"] is not None for row in profiles) == data["android_sprites"] == 134
          and sum(len(row["ios"]) for row in profiles) == data["ios_sprites"] == 139,
          "Frozen per-platform Sprite coverage differs")
    by_name = {row["name"]: row for row in profiles}
    # Preserve the seven v1 texture IDs as well as their private GUIDs/pixels.
    order = [row["name"] for row in LEGACY_PROFILES]
    order += sorted(set(by_name) - set(order))
    return tuple(_text_layout(by_name[name]) for name in order)


PROFILES = _profiles()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _imports():
    _need(importlib.metadata.version("UnityPy") == "1.25.4", "Use the audited UnityPy 1.25.4 sprite writer")
    import UnityPy
    from PIL import Image
    return UnityPy, Image


def _png(directory, profile):
    path = Path(directory) / (profile["name"] + ".png")
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "Expected an explicit regular translated PNG")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PNG_BYTES + 1)
    _need(len(raw) == profile["png_bytes"] and _sha(raw) == profile["png_sha256"],
          "Translated sprite PNG differs from the pinned upstream input")
    _need(raw[:16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"
          and struct.unpack_from(">II", raw, 16) == tuple(profile["png_size"])
          and raw[24] == 8 and raw[25] == profile.get("png_color_type", 6)
          and raw[25] in (2, 6), "Translated sprite must retain its audited RGB8/RGBA8 dimensions")
    return raw


def _canvas(png, profile):
    from io import BytesIO
    _, Image = _imports()
    with Image.open(BytesIO(png)) as source:
        _need(source.format == "PNG" and source.mode == ("RGB" if profile.get("png_color_type", 6) == 2 else "RGBA")
              and source.size == tuple(profile["png_size"]),
              "Translated sprite PNG decode differs")
        image = source.convert("RGBA")
    content = tuple(profile.get("content_size", profile["png_size"]))
    if content != image.size:
        scale = min(1., profile["sprite_size"][0] / image.width, profile["sprite_size"][1] / image.height)
        expected = tuple(max(1, min(bound, round(value * scale)))
                         for bound, value in zip(profile["sprite_size"], image.size))
        _need(profile.get("layout_policy") == TEXT_LAYOUT_POLICY and content == expected
              and all(0 < fitted <= original for fitted, original in zip(content, image.size)),
              "Only audited Love text may use a bounded uniform downscale")
        image = image.resize(content, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", profile["sprite_size"], (0, 0, 0, 0))
    x, y = profile["padding_offset"]
    _need(0 <= x and 0 <= y and x + image.width <= canvas.width and y + image.height <= canvas.height,
          "Translated sprite exceeds its original layout rectangle")
    canvas.paste(image, (x, y))
    return canvas


def _template_record(prefix):
    _need(prefix[:16] == struct.pack(">4I", 0, 0, 22, 0) and prefix[16:20] == b"\0" * 4,
          "Expected the original v22 texture template header")
    metadata_size, file_size, data_offset, unknown = struct.unpack_from(">IQQQ", prefix, 20)
    _need(unknown == 0 and 48 + metadata_size <= data_offset <= len(prefix), "Texture template metadata exceeds its bound")
    position = prefix.index(b"\0", 48, 80) + 1
    _need(prefix[48:position] == b"2022.3.57f1\0", "Texture template Unity version differs")
    position += 4
    _need(prefix[position] == 0, "Texture template must preserve disabled type trees")
    position += 1
    count = struct.unpack_from("<i", prefix, position)[0]; position += 4
    _need(0 < count <= 32, "Texture template type count differs")
    classes = []
    for _ in range(count):
        cls, _stripped, _script = struct.unpack_from("<iBh", prefix, position); position += 7
        if cls == 114:
            position += 16
        position += 16
        classes.append(cls)
    count = struct.unpack_from("<i", prefix, position)[0]
    position = (position + 7) & ~3
    _need(count == 21 and position + count * 24 <= 48 + metadata_size, "Texture template object table differs")
    for index in range(count):
        pid, relative, size, tid = struct.unpack_from("<qQIi", prefix, position + 24 * index)
        if pid == 8:
            _need(classes[tid] == 28 and size == TEXTURE_TEMPLATE_BYTES
                  and relative + size <= file_size - data_offset, "Texture template object differs")
            return data_offset + relative, size
    raise ValueError("Original texture template is missing")


def _texture_template(archive, platform):
    profile = font_assets.ASSETS[platform]
    if platform == "android":
        count = (profile["bytes"] + font_assets.SPLIT_BYTES - 1) // font_assets.SPLIT_BYTES
        names = [font_assets.ANDROID_ASSET + ".split" + str(index) for index in range(count)]
    else:
        names = [name for name in archive.namelist() if name.endswith(".app/" + font_assets.IOS_ASSET)]
        _need(len(names) == 1, "Expected one original iOS font schema asset")
    _need(all(archive.namelist().count(name) == 1 for name in names), "Texture schema source members differ")
    _need(sum(archive.getinfo(name).file_size for name in names) == profile["bytes"], "Texture schema source size differs")
    digest, position, raw = hashlib.sha256(), 0, bytearray()
    target = None
    for name in names:
        with archive.open(name) as source:
            while block := source.read(65536):
                digest.update(block)
                if target is None:
                    target = _template_record(block)
                start, size = target
                low, high = max(position, start), min(position + len(block), start + size)
                if high > low:
                    raw.extend(block[low - position:high - position])
                position += len(block)
    raw = bytes(raw)
    _need(position == profile["bytes"] and digest.hexdigest() == profile["sha256"]
          and len(raw) == TEXTURE_TEMPLATE_BYTES and _sha(raw) == TEXTURE_TEMPLATE_SHA256,
          "Original texture schema source fingerprint differs")
    return raw


def _mini_asset(raw, cls, platform):
    """A tiny virtual reader uses the unchanged built-in class schema only."""
    _need(cls in TYPE_HASHES and 0 < len(raw) <= (MAX_SPRITE_BYTES if cls == 213 else MAX_TEXTURE_BYTES)
          and platform in (9, 13),
          "Unsupported virtual sprite/texture schema")
    metadata = bytearray(b"2022.3.57f1\0" + struct.pack("<iBi", platform, 0, 1))
    metadata.extend(struct.pack("<iBh", cls, 0, -1) + bytes.fromhex(TYPE_HASHES[cls]))
    metadata.extend(struct.pack("<i", 1))
    metadata.extend(b"\0" * (-(48 + len(metadata)) % 4))
    metadata.extend(struct.pack("<qQIi", 1, 0, len(raw), 0))
    metadata.extend(struct.pack("<iii", 0, 0, 0) + b"\0")
    offset = (48 + len(metadata) + 15) & ~15
    header = struct.pack(">4I", 0, 0, 22, 0) + b"\0" * 4
    header += struct.pack(">IQQQ", len(metadata), offset + len(raw), offset, 0)
    UnityPy, _ = _imports()
    environment = UnityPy.load(header + metadata + b"\0" * (offset - 48 - len(metadata)) + raw)
    return environment, next(iter(environment.objects))


def _sprite(raw, profile, platform, texture_id, *, target=None):
    from UnityPy.classes import PPtr
    from UnityPy.classes.math import Vector2f, Vector3f, Vector4f
    from UnityPy.classes.generated import Rectf, AABB
    if target is None:
        target = profile["android"] if platform == 13 else profile["ios"][0]
    expected = target["object_sha256"]
    _need(_sha(raw) == expected, "Original sprite payload differs")
    environment, reader = _mini_asset(raw, 213, platform)
    sprite = reader.read()
    width, height = profile["sprite_size"]
    layout = target["source_layout"]
    _need(sprite.m_Name == profile["name"]
          and [sprite.m_Rect.x, sprite.m_Rect.y] == layout["rect_xy"]
          and [sprite.m_Rect.width, sprite.m_Rect.height] == layout["sprite_size"]
          and [sprite.m_Pivot.x, sprite.m_Pivot.y] == layout["pivot"]
          and [sprite.m_Border.x, sprite.m_Border.y, sprite.m_Border.z, sprite.m_Border.w] == layout["border"]
          and sprite.m_PixelsToUnits == layout["pixels_per_unit"]
          and [sprite.m_Offset.x, sprite.m_Offset.y] == layout["offset"]
          and len(sprite.m_Bones) == layout["bones"], "Original translated sprite layout differs")
    # Match Localify's Sprite.Create(PNG rectangle, normalized original pivot,
    # original PPU/border) offline. The seven legacy translations retain v1.
    sprite.m_Rect = Rectf(x=0., y=0., width=float(width), height=float(height))
    sprite.m_AtlasTags = []
    sprite.m_SpriteAtlas = PPtr(m_FileID=0, m_PathID=0, assetsfile=reader.assets_file)
    # The original atlas may still load for other sprites. A private key keeps
    # its packed render-data map from rebinding this now-independent sprite.
    key = copy.copy(sprite.m_RenderDataKey[0])
    key_name = profile["name"]
    key_policy = profile["render_key_policy"]
    if key_policy != LEGACY_POLICY:
        key_name += ":" + str(target["path_id"])
    private_key = hashlib.sha256((key_policy + ":" + key_name).encode("ascii")).digest()[:16]
    for index, value in enumerate(struct.unpack("<4I", private_key)):
        setattr(key, "data_" + str(index) + "_", value)
    _need(key != sprite.m_RenderDataKey[0], "Private sprite render key collides with its original atlas")
    sprite.m_RenderDataKey = (key, sprite.m_RenderDataKey[1])
    sprite.m_IsPolygon = False
    rd = sprite.m_RD
    rd.texture = PPtr(m_FileID=0, m_PathID=texture_id, assetsfile=reader.assets_file)
    rd.alphaTexture = PPtr(m_FileID=0, m_PathID=0, assetsfile=reader.assets_file)
    rd.textureRect = Rectf(x=0., y=0., width=float(width), height=float(height))
    rd.textureRectOffset = Vector2f(0., 0.)
    rd.atlasRectOffset = Vector2f(0., 0.)
    rd.settingsRaw = 64  # unpacked, unrotated, full rectangle mesh
    rd.uvTransform = Vector4f(100., width / 2, 100., height / 2)
    rd.m_IndexBuffer = list(struct.pack("<6H", 0, 1, 2, 0, 2, 3))
    _need(len(rd.m_SubMeshes) == 1, "Original sprite submesh count differs")
    sub = copy.deepcopy(rd.m_SubMeshes[0])
    sub.firstByte = sub.firstVertex = sub.baseVertex = 0
    sub.indexCount, sub.vertexCount = 6, 4
    sub.localAABB = AABB(m_Center=Vector3f(0., 0., 0.),
                         m_Extent=Vector3f(width / 200, height / 200, 0.))
    rd.m_SubMeshes = [sub]
    vertex = rd.m_VertexData
    _need(len(vertex.m_Channels) == 14 and vertex.m_Channels[0].dimension == 3
          and vertex.m_Channels[0].stream == 0 and vertex.m_Channels[0].format == 0
          and vertex.m_Channels[4].dimension == 2 and vertex.m_Channels[4].stream == 1
          and vertex.m_Channels[4].format == 0,
          "Original sprite vertex layout differs")
    vertex.m_VertexCount = 4
    vertex.m_DataSize = struct.pack("<12f", -width / 200, -height / 200, 0,
        width / 200, -height / 200, 0, width / 200, height / 200, 0,
        -width / 200, height / 200, 0) + struct.pack("<8f", 0, 0, 1, 0, 1, 1, 0, 1)
    sprite.save()
    result = bytes(reader.data)
    del environment
    return result


def _texture(raw, canvas, name, platform):
    environment, reader = _mini_asset(raw, 28, platform)
    texture = reader.read()
    texture.m_Name = "Idoly-Korean-" + name
    _need(canvas.width * canvas.height <= MAX_IMAGE_PIXELS, "Static image exceeds its frozen pixel bound")
    texture.set_image(canvas, target_format=4, mipmap_count=1)
    texture.m_IsReadable = False  # Static UI needs no retained CPU pixel copy.
    texture.m_ColorSpace = 1
    texture.m_TextureSettings.m_FilterMode = 1
    texture.m_TextureSettings.m_WrapU = texture.m_TextureSettings.m_WrapV = texture.m_TextureSettings.m_WrapW = 1
    texture.save()
    result = bytes(reader.data)
    del environment
    return result


def _proof(platform, language, rows):
    return {"schema": 2, "policy": POLICY, "platform": platform, "language": language,
            "source": {"repository": SOURCE_REPOSITORY, "revision": SOURCE_REVISION,
                       "data_terms": "NOASSERTION"},
            "sprites": rows, "translated_sprites": len(rows),
            "runtime_image_hooks": False, "atlas_pixels_modified": False,
            "original_sprite_IDs_preserved": True,
            "original_pivots_borders_pixels_per_unit_preserved": True,
            "layout_policy": "preserved-v1-layout, Localify PNG rectangle, or fixed Love text aspect",
            "fixed_text_layout_policy": TEXT_LAYOUT_POLICY,
            "fixed_text_sprites": sum(row["layout_policy"] == TEXT_LAYOUT_POLICY for row in rows),
            "original_layout_preserved": all(row["original_layout_size"] == row["layout_size"] for row in rows),
            "texture_format": "RGBA32", "lossy_recompression": False,
            "private_sprite_render_data_keys": True}


def android_members(archive, *, language="ja", image_dir=None):
    _need(language in ("ja", "ko", "en"), "Unknown static image language")
    if language != "ko":
        return {}, _proof("android", language, [])
    _need(image_dir is not None, "Korean static sprites require explicit pinned PNG inputs")
    UnityPy, _ = _imports()
    template = _texture_template(archive, "android")
    replacements, rows = {}, []
    for profile in PROFILES:
        target = profile["android"]
        if target is None:
            continue
        name = target["member"]
        _need(archive.namelist().count(name) == 1 and archive.getinfo(name).file_size == target["asset_bytes"],
              "Original standalone sprite member differs")
        raw = archive.read(name)
        _need(_sha(raw) == target["asset_sha256"], "Original standalone sprite fingerprint differs")
        env = UnityPy.load(raw); source = next(iter(env.files.values()))
        _need(len(source.objects) == len(source.types) == 1 and 1 in source.objects
              and source.objects[1].class_id == 213 and int(source.target_platform) == 13,
              "Original standalone Sprite object graph differs")
        original = source.objects[1].get_raw_data()
        png = _png(image_dir, profile); canvas = _canvas(png, profile)
        source.objects[1].set_raw_data(_sprite(original, profile, 13, 2, target=target))
        texture = _texture(template, canvas, profile["name"], 13)
        tiny, texture_reader = _mini_asset(texture, 28, 13)
        clone = copy.copy(texture_reader)
        clone.assets_file, clone.path_id, clone.type_id = source, 2, 1
        clone.serialized_type = copy.copy(texture_reader.serialized_type)
        clone.set_raw_data(texture)
        source.types.append(clone.serialized_type); source.objects[2] = clone
        saved = env.file.save(); check = UnityPy.load(saved)
        _need(sorted((obj.path_id, obj.class_id) for obj in check.objects) == [(1, 213), (2, 28)],
              "Localized standalone sprite graph differs")
        checked = next(iter(check.files.values()))
        _need(checked.objects[2].read().image.tobytes() == canvas.tobytes()
              and checked.objects[1].read().image.tobytes() == canvas.tobytes(),
              "Localized sprite pixels differ from the pinned translation")
        replacements[name] = saved
        rows.append({"name": profile["name"], "input_member": name,
                     "input_sha256": target["asset_sha256"], "output_sha256": _sha(saved),
                     "output_bytes": len(saved), "png_sha256": profile["png_sha256"],
                     "sprite_path_id": 1, "private_texture_path_id": 2,
                     "original_layout_size": target["source_layout"]["sprite_size"],
                     "layout_size": list(profile["sprite_size"]), "png_size": list(profile["png_size"]),
                     "layout_policy": profile["layout_policy"],
                     "transparent_padding_offset": list(profile["padding_offset"]),
                     "content_size": list(profile.get("content_size", profile["png_size"])),
                     "PNG_resampled": profile.get("content_size", profile["png_size"]) != profile["png_size"],
                     "readback_pixel_exact": True})
        del env, source, tiny, check
    return replacements, _proof("android", language, rows)


def _ios_originals(archive, member, data_offset):
    targets = sorted((target["relative_offset"], target) for profile in PROFILES for target in profile["ios"])
    originals = {}
    with archive.open(member) as source:
        position = 0
        for relative, target in targets:
            offset = data_offset + relative
            _need(offset >= position, "Original iOS Sprite ranges overlap")
            while position < offset:
                block = source.read(min(65536, offset - position))
                _need(bool(block), "Truncated original iOS Sprite stream")
                position += len(block)
            original = source.read(target["bytes"])
            _need(len(original) == target["bytes"] and _sha(original) == target["object_sha256"],
                  "Original iOS translated Sprite payload differs")
            originals[target["path_id"]] = original
            position += len(original)
    return originals


def ios_patches(archive, *, language="ja", image_dir=None):
    _need(language in ("ja", "ko", "en"), "Unknown static image language")
    if language != "ko":
        return {}, [], _proof("ios", language, [])
    _need(image_dir is not None, "Korean static sprites require explicit pinned PNG inputs")
    from .ui_assets import ASSETS
    profile = ASSETS["ios"]
    names = [name for name in archive.namelist() if name.endswith(".app/Data/resources.assets")]
    _need(len(names) == 1 and archive.getinfo(names[0]).file_size == profile["source_bytes"],
          "Expected one original iOS UI source member")
    template = _texture_template(archive, "ios")
    originals = _ios_originals(archive, names[0], profile["data_offset"])
    replacements, appended, rows = {}, [], []
    for translated in PROFILES:
        png = _png(image_dir, translated); canvas = _canvas(png, translated)
        for target in translated["ios"]:
            original = originals.pop(target["path_id"])
            texture_id = profile["object_count"] + 1 + len(appended)
            sprite = _sprite(original, translated, 9, texture_id, target=target)
            texture = _texture(template, canvas, translated["name"], 9)
            tiny, reader = _mini_asset(texture, 28, 9)
            _need(reader.read().image.tobytes() == canvas.tobytes(), "Localized iOS texture pixels differ")
            replacements[target["path_id"]] = {"input_sha256": target["object_sha256"], "raw": sprite}
            appended.append({"path_id": texture_id, "type_id": 2, "raw": texture})
            rows.append({"name": translated["name"], "sprite_path_id": target["path_id"],
                         "input_sha256": target["object_sha256"], "output_sha256": _sha(sprite),
                         "output_bytes": len(sprite), "png_sha256": translated["png_sha256"],
                         "private_texture_path_id": texture_id, "texture_sha256": _sha(texture),
                         "texture_bytes": len(texture),
                         "original_layout_size": target["source_layout"]["sprite_size"],
                         "layout_size": list(translated["sprite_size"]),
                         "layout_policy": translated["layout_policy"],
                         "png_size": list(translated["png_size"]),
                         "transparent_padding_offset": list(translated["padding_offset"]),
                         "content_size": list(translated.get("content_size", translated["png_size"])),
                         "PNG_resampled": translated.get("content_size", translated["png_size"]) != translated["png_size"],
                         "readback_pixel_exact": True})
            del tiny
    _need(not originals, "Original iOS Sprite inventory was not fully consumed")
    return replacements, appended, _proof("ios", language, rows)
