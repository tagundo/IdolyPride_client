"""Offline Korean pixels for fourteen original Texture2D IDs.

The source GPU format, name and sampling settings stay intact. iOS stream
textures receive inline ASTC bytes so shared .resS ranges never move or change.
No runtime image replacement or RGBA32 expansion is installed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

from . import static_ui_images as images
from .cdn_image_translation import _encoded_pixels

POLICY = "korean-static-textures-v1"
SOURCE = {"repository": images.SOURCE_REPOSITORY, "revision": images.SOURCE_REVISION,
          "data_terms": "NOASSERTION"}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _profiles():
    path = Path(__file__).resolve().parents[2] / "client-presentation/images/korean-static-textures-v1.json"
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode)
          and 0 < path.stat().st_size <= 64 * 1024, "Expected bounded frozen direct-texture profile")
    data = json.loads(path.read_bytes())
    _need(data.get("schema") == 1 and data.get("policy") == POLICY and data.get("source") == SOURCE,
          "Frozen direct-texture source differs")
    rows = data["inputs"]
    _need(len(rows) == data["input_count"] == 14 and len({row["name"] for row in rows}) == 14,
          "Frozen direct-texture roster differs")
    for row in rows:
        _need(0 < row["png_bytes"] <= images.MAX_PNG_BYTES and row["png_color_type"] in (2, 6)
              and len(row["png_size"]) == 2 and 0 < row["png_size"][0] * row["png_size"][1] <= images.MAX_IMAGE_PIXELS,
              "Frozen direct texture PNG exceeds its boundary")
        for platform in ("android", "ios"):
            target = row[platform]
            _need(target["format"] == 50 and target["mips"] == 1
                  and 0 < target["bytes"] <= images.MAX_TEXTURE_BYTES and target["path_id"] > 0
                  and len(target["object_sha256"]) == 64,
                  "Frozen direct Texture2D target differs")
    return tuple(rows)


PROFILES = _profiles()


def _patch(original, profile, platform, cache):
    import attrs
    from io import BytesIO
    from PIL import Image
    target = profile[platform]
    _need(len(original) == target["bytes"] and _sha(original) == target["object_sha256"],
          "Original direct Texture2D fingerprint differs")
    _, reader = images._mini_asset(original, 28, 13 if platform == "android" else 9)
    texture = reader.read()
    before = attrs.asdict(texture)
    stream = texture.m_StreamData
    _need(texture.m_Name == profile["name"]
          and [texture.m_Width, texture.m_Height] == [target["width"], target["height"]]
          and int(texture.m_TextureFormat) == target["format"] and texture.m_MipCount == target["mips"]
          and {"path": stream.path, "offset": stream.offset, "size": stream.size} == target["stream_data"],
          "Original direct Texture2D layout differs")
    old_gpu = ((texture.m_Width + 5) // 6) * ((texture.m_Height + 5) // 6) * 16
    _need(texture.m_CompleteImageSize == old_gpu
          and (stream.size == old_gpu and not texture.image_data if stream.path
               else len(texture.image_data) == old_gpu), "Original direct GPU allocation differs")
    png = images._png(cache["image_dir"], profile)
    with Image.open(BytesIO(png)) as loaded:
        canvas = loaded.convert("RGBA")
    encoded, measurement = _encoded_pixels(canvas, target["format"], cache["encoded"])
    expected_gpu = ((canvas.width + 5) // 6) * ((canvas.height + 5) // 6) * 16
    _need(len(encoded) == expected_gpu, "Direct ASTC allocation differs")
    texture.image_data = encoded
    texture.m_Width, texture.m_Height = canvas.width, canvas.height
    texture.m_CompleteImageSize = len(encoded)
    texture.m_IsReadable = False
    stream.path, stream.offset, stream.size = "", 0, 0
    texture.save()
    result = bytes(reader.data)
    _, check = images._mini_asset(result, 28, 13 if platform == "android" else 9)
    final = check.read()
    allowed = {"image_data", "m_Width", "m_Height", "m_CompleteImageSize", "m_IsReadable", "m_StreamData"}
    after = attrs.asdict(final)
    _need({k: v for k, v in before.items() if k not in allowed}
          == {k: v for k, v in after.items() if k not in allowed},
          "Unrelated direct Texture2D name/sampling fields changed")
    _need(int(final.m_TextureFormat) == target["format"] and not final.m_IsReadable
          and final.m_MipCount == 1 and not final.m_StreamData.path
          and final.m_StreamData.offset == final.m_StreamData.size == 0
          and _sha(final.image.tobytes()) == measurement["decoded_RGBA_sha256"],
          "Direct translated ASTC readback differs")
    proof = {"name": profile["name"], "path_id": target["path_id"],
             "input_sha256": target["object_sha256"], "output_sha256": _sha(result),
             "output_bytes": len(result), "png_sha256": profile["png_sha256"],
             "original_width": target["width"], "original_height": target["height"],
             "width": canvas.width, "height": canvas.height,
             "format_before": target["format"], "format_after": int(final.m_TextureFormat),
             "GPU_bytes_before": old_gpu, "GPU_bytes_after": len(encoded),
             "CPU_pixel_copy_retained": False, "original_shared_stream_unchanged": True,
             "unrelated_texture_fields_preserved": True, "PNG_resampled": False, **measurement}
    return result, proof


def _proof(platform, language, rows):
    return {"schema": 1, "policy": POLICY, "source": SOURCE, "platform": platform,
            "language": language, "textures": rows, "translated_textures": len(rows),
            "runtime_image_hooks": False, "original_Texture2D_IDs_preserved": True,
            "original_shared_texture_streams_unchanged": True, "GPU_format_preserved": True}


def android_members(archive, *, language="ja", image_dir=None):
    _need(language in ("ja", "ko", "en"), "Unknown direct image language")
    if language != "ko":
        return {}, _proof("android", language, [])
    _need(image_dir is not None, "Korean direct textures require explicit pinned PNG inputs")
    UnityPy, _ = images._imports()
    replacements, rows = {}, []
    cache = {"image_dir": image_dir, "encoded": {}}
    for profile in PROFILES:
        target = profile["android"]; member = target["member"]
        _need(archive.namelist().count(member) == 1
              and archive.getinfo(member).file_size == target["asset_bytes"], "Original direct texture member differs")
        source = archive.read(member)
        _need(_sha(source) == target["asset_sha256"], "Original direct texture asset fingerprint differs")
        env = UnityPy.load(source); asset = next(iter(env.files.values()))
        _need(set(asset.objects) == {1} and asset.objects[1].class_id == 28
              and len(asset.types) == 1 and int(asset.target_platform) == 13, "Original direct texture graph differs")
        result, proof = _patch(asset.objects[1].get_raw_data(), profile, "android", cache)
        asset.objects[1].set_raw_data(result)
        saved = env.file.save(); replacements[member] = saved
        rows.append({**proof, "member": member, "asset_output_sha256": _sha(saved), "asset_output_bytes": len(saved)})
    return replacements, _proof("android", language, rows)


def ios_patches(archive, *, language="ja", image_dir=None):
    _need(language in ("ja", "ko", "en"), "Unknown direct image language")
    if language != "ko":
        return {}, _proof("ios", language, [])
    _need(image_dir is not None, "Korean direct textures require explicit pinned PNG inputs")
    from .ui_assets import ASSETS
    member = "Payload/IDOLY PRIDE.app/Data/resources.assets"
    _need(archive.namelist().count(member) == 1 and archive.getinfo(member).file_size == ASSETS["ios"]["source_bytes"],
          "Original iOS direct texture source differs")
    originals = {}; position = 0
    with archive.open(member) as stream:
        for profile in sorted(PROFILES, key=lambda row: row["ios"]["relative_offset"]):
            target = profile["ios"]; offset = target["asset_data_offset"] + target["relative_offset"]
            _need(offset >= position, "Original direct texture ranges overlap")
            while position < offset:
                part = stream.read(min(65536, offset - position)); _need(bool(part), "Truncated direct texture source")
                position += len(part)
            original = stream.read(target["bytes"]); _need(len(original) == target["bytes"], "Truncated direct Texture2D")
            position += len(original); originals[target["path_id"]] = original
    replacements, rows = {}, []; cache = {"image_dir": image_dir, "encoded": {}}
    for profile in PROFILES:
        target = profile["ios"]
        result, proof = _patch(originals.pop(target["path_id"]), profile, "ios", cache)
        replacements[target["path_id"]] = {"input_sha256": target["object_sha256"], "raw": result}
        rows.append(proof)
    return replacements, _proof("ios", language, rows)
