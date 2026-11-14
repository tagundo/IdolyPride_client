"""Build translated CDN image bundles before the server/game is started.

The Octo filename, Unity object IDs, original GPU format and other objects are
preserved. PNG dimensions follow the existing Localify image semantics; changes
to texture dimensions and GPU allocation are explicit in the proof. Pixels are
supplied by pinned translated PNGs and encoded once in
the original GPU texture format inside an LZ4 UnityFS bundle. No runtime texture
hook is used, and compressed textures do not become large RGBA allocations.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from io import BytesIO
import math
import re
import struct

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 4096 * 4096
_NAME = re.compile(r"img_[a-zA-Z0-9_-]{1,160}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bundle_mask(name):
    """Original Octo first-256-byte XOR mask, shared by encode and decode.

    Equivalent to HoshimiToolkit ``string_to_mask_bytes``; this uses the
    manifest's immutable logical asset name, never its CDN objectName.
    """
    _need(isinstance(name, str) and _NAME.fullmatch(name), "Invalid image bundle name")
    source = name.encode("ascii")
    mask = bytearray(len(source) * 2)
    for index, value in enumerate(source):
        mask[index * 2] = value
        mask[len(mask) - 1 - index * 2] = value ^ 255
    checksum = 0x9B
    for value in mask:
        checksum = ((checksum & 1) << 7 | checksum >> 1) ^ value
    return bytes(value ^ checksum for value in mask)


def crypt_header(raw, name):
    _need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BUNDLE_BYTES,
          "Invalid image bundle bytes")
    mask = bundle_mask(name)
    prefix = bytes(value ^ mask[index % len(mask)] for index, value in enumerate(raw[:256]))
    return prefix + raw[256:]


def decode_image_bundle(original, *, name, original_md5):
    """Read a pinned original image for offline caption generation, never URLs."""
    _need(isinstance(name, str) and _NAME.fullmatch(name), "Invalid image bundle name")
    _need(isinstance(original, bytes) and 0 < len(original) <= MAX_BUNDLE_BYTES
          and isinstance(original_md5, str) and re.fullmatch(r"[0-9a-f]{32}", original_md5)
          and hashlib.md5(original, usedforsecurity=False).hexdigest() == original_md5,
          "Original image bundle differs from its manifest")
    _need(importlib.metadata.version("UnityPy") == "1.25.4", "Use the audited UnityPy 1.25.4 reader")
    import UnityPy
    import UnityPy.config
    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.57f1"
    decoded = original if original.startswith(b"UnityFS\0") else crypt_header(original, name)
    _need(decoded.startswith(b"UnityFS\0"), "Original image is not the expected UnityFS bundle")
    environment = UnityPy.load(decoded)
    objects = list(environment.objects)
    _need(0 < len(objects) <= 32, "Unexpected image bundle object count")
    matches = [texture for obj in objects if obj.class_id == 28
               and (texture := obj.read()).m_Name == name]
    _need(len(matches) == 1, "Expected exactly one named image texture")
    texture = matches[0]
    _need(0 < texture.m_Width <= 4096 and 0 < texture.m_Height <= 4096
          and texture.m_Width * texture.m_Height <= MAX_PIXELS, "Original image dimensions exceed producer boundary")
    image = texture.image.convert("RGBA")
    proof = {"original_sha256": _sha(original), "name": name,
        "width": texture.m_Width, "height": texture.m_Height,
        "format": int(texture.m_TextureFormat), "path_id": texture.object_reader.path_id,
        "decoded_RGBA_sha256": _sha(image.tobytes())}
    return image, proof


def _encoded_pixels(canvas, original_format, cache):
    """Preserve GPU format; ASTC is explicitly lossy and built with one thread."""
    from PIL import Image, ImageChops, ImageStat
    source_sha = _sha(canvas.tobytes())
    key = (source_sha, canvas.width, canvas.height, original_format, 60, 1)
    if cache is not None and key in cache:
        return cache[key]
    flipped = canvas.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if original_format == 4:
        encoded = flipped.tobytes()
        decoded = canvas
        encoding = "RGBA32-lossless"
    else:
        import astc_encoder as astc
        _need(importlib.metadata.version("astc-encoder-py") == "0.1.12",
              "Use the audited ASTC encoder 0.1.12")
        _need(original_format in (48, 50), "Unsupported original image GPU format")
        block = 4 if original_format == 48 else 6
        context = astc.ASTCContext(astc.ASTCConfig(astc.ASTCProfile.LDR, block, block,
            block_z=1, quality=60, flags=astc.ASTCConfigFlags.USE_DECODE_UNORM8), threads=1)
        source = astc.ASTCImage(astc.ASTCType.U8, canvas.width, canvas.height, 1, flipped.tobytes())
        encoded = context.compress(source, astc.ASTCSwizzle.from_str("RGBA"))
        result = astc.ASTCImage(astc.ASTCType.U8, canvas.width, canvas.height, 1)
        context.decompress(encoded, result, astc.ASTCSwizzle.from_str("RGBA"))
        decoded = Image.frombytes("RGBA", canvas.size, result.data).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        encoding = "ASTC" + str(block) + "x" + str(block) + "-medium"
    difference = ImageStat.Stat(ImageChops.difference(canvas, decoded))
    measured = {"encoding": encoding, "source_RGBA_sha256": source_sha,
        "decoded_RGBA_sha256": _sha(decoded.tobytes()),
        "rms_RGB": math.sqrt(sum(value * value for value in difference.rms[:3]) / 3),
        "quality": 60, "threads": 1, "GPU_bytes": len(encoded),
        "encoder_version": ("raw" if original_format == 4 else importlib.metadata.version("astc-encoder-py"))}
    result = encoded, measured
    if cache is not None:
        cache[key] = result
    return result


def _check_texture_fields(before, after):
    allowed = {"image_data", "m_Width", "m_Height", "m_CompleteImageSize", "m_StreamData", "m_IsReadable"}
    _need({k: v for k, v in before.items() if k not in allowed}
          == {k: v for k, v in after.items() if k not in allowed},
          "Repacking changed unrelated texture fields")
    old_stream, new_stream = before["m_StreamData"], after["m_StreamData"]
    _need(old_stream is None and new_stream is None
          or isinstance(old_stream, dict) and isinstance(new_stream, dict)
          and old_stream["path"] == new_stream["path"] and old_stream["offset"] == new_stream["offset"],
          "Repacking changed texture stream identity")


def patch_image_bundle(original, png, *, name, original_md5, png_sha256,
                       encoded_texture_cache=None):
    """Return encoded replacement bytes and independently readable provenance.

    The caller binds the original size/MD5 to the platform's original manifest,
    and binds ``png_sha256`` to its checked-in translation image catalog.
    """
    _need(isinstance(name, str) and _NAME.fullmatch(name), "Invalid image bundle name")
    _need(isinstance(original, bytes) and 0 < len(original) <= MAX_BUNDLE_BYTES
          and isinstance(original_md5, str) and re.fullmatch(r"[0-9a-f]{32}", original_md5)
          and hashlib.md5(original, usedforsecurity=False).hexdigest() == original_md5,
          "Original image bundle differs from its manifest")
    _need(isinstance(png, bytes) and 33 <= len(png) <= MAX_PNG_BYTES
          and isinstance(png_sha256, str) and _SHA.fullmatch(png_sha256)
          and _sha(png) == png_sha256 and png[:16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR",
          "Translated PNG differs from the pinned image catalog")
    width, height = struct.unpack_from(">II", png, 16)
    _need(0 < width <= 4096 and 0 < height <= 4096 and width * height <= MAX_PIXELS,
          "Translated image dimensions exceed the producer boundary")
    _need(importlib.metadata.version("UnityPy") == "1.25.4", "Use the audited UnityPy 1.25.4 writer")
    import UnityPy
    import UnityPy.config
    from PIL import Image

    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.57f1"
    obfuscated = not original.startswith(b"UnityFS\0")
    decoded = crypt_header(original, name) if obfuscated else original
    _need(decoded.startswith(b"UnityFS\0"), "Original image is not the expected UnityFS bundle")
    environment = UnityPy.load(decoded)
    objects = {(obj.assets_file.name, obj.path_id): obj for obj in environment.objects}
    _need(0 < len(objects) <= 32, "Unexpected image bundle object count")
    matches = []
    for key, obj in objects.items():
        if obj.class_id == 28:
            texture = obj.read()
            if texture.m_Name == name:
                matches.append((key, obj, texture))
    _need(len(matches) == 1, "Expected exactly one named image texture")
    key, reader, texture = matches[0]
    _need(texture.m_MipCount == 1,
          "Unsupported image mip layout for " + name + ": " + str(texture.m_MipCount))
    import attrs
    original_state = attrs.asdict(texture)
    original_width, original_height = texture.m_Width, texture.m_Height
    geometry_changed = (original_width, original_height) != (width, height)
    if geometry_changed:
        _need(len(objects) == 2 and sorted(obj.class_id for obj in objects.values()) == [28, 142],
              "Resized image must be an isolated Texture2D and AssetBundle pair")
    unchanged = {k: obj.get_raw_data() for k, obj in objects.items() if k != key}
    original_texture = reader.get_raw_data()
    original_readable = texture.m_IsReadable
    original_format = int(texture.m_TextureFormat)
    with Image.open(BytesIO(png)) as loaded:
        _need(loaded.format == "PNG" and loaded.size == (width, height), "PNG decode differs")
        canvas = loaded.convert("RGBA")
    _need(original_format in (4, 48, 50), "Unsupported original image GPU format")
    encoded_pixels, measurement = _encoded_pixels(canvas, original_format, encoded_texture_cache)
    expected_gpu_bytes = (width * height * 4 if original_format == 4 else
        ((width + (3 if original_format == 48 else 5)) // (4 if original_format == 48 else 6))
        * ((height + (3 if original_format == 48 else 5)) // (4 if original_format == 48 else 6)) * 16)
    original_gpu_bytes = texture.m_CompleteImageSize
    old_gpu_bytes = (original_width * original_height * 4 if original_format == 4 else
        ((original_width + (3 if original_format == 48 else 5)) // (4 if original_format == 48 else 6))
        * ((original_height + (3 if original_format == 48 else 5)) // (4 if original_format == 48 else 6)) * 16)
    _need(len(encoded_pixels) == expected_gpu_bytes and original_gpu_bytes == old_gpu_bytes,
          "Original GPU texture allocation differs")
    # Replace only this texture's original stream range. Its path, size, object
    # bytes and every other stream range stay unchanged. Higher-resolution PNGs
    # follow Localify's PNG-sized texture semantics; their changed dimensions
    # and GPU allocation are explicitly reported rather than silently scaled.
    stream = texture.m_StreamData
    replaced_stream = None
    if stream.path:
        from UnityPy.streams import EndianBinaryReader
        stream_name = stream.path.rsplit("/", 1)[-1]
        _need(stream_name in environment.file.files, "Original texture stream is missing")
        source_stream = environment.file.files[stream_name]
        old_pixels = source_stream.bytes
        old_stream_size = stream.size
        _need(stream.size == old_gpu_bytes and 0 <= stream.offset <= len(old_pixels) - stream.size,
              "Original image stream range differs")
        for other_key, obj in objects.items():
            if other_key == key or obj.class_id != 28:
                continue
            other = obj.read().m_StreamData
            if len(encoded_pixels) != old_stream_size:
                _need(not other.path or other.path.rsplit("/", 1)[-1] != stream_name,
                      "A shared texture stream cannot change size")
            _need(not other.path or other.path.rsplit("/", 1)[-1] != stream_name
                  or other.offset + other.size <= stream.offset
                  or other.offset >= stream.offset + stream.size, "Another texture overlaps this stream range")
        replacement = EndianBinaryReader(old_pixels[:stream.offset] + encoded_pixels + old_pixels[stream.offset + old_stream_size:])
        replacement.flags = source_stream.flags
        environment.file.files[stream_name] = replacement
        stream.size = len(encoded_pixels)
        replaced_stream = stream_name
    else:
        _need(len(texture.image_data) == old_gpu_bytes, "Original inline texture size differs")
        texture.image_data = encoded_pixels
    texture.m_Width, texture.m_Height, texture.m_CompleteImageSize = width, height, len(encoded_pixels)
    if not stream.path or texture.m_IsReadable or geometry_changed:
        texture.m_IsReadable = False
        texture.save()
    packed = environment.file.save(packer="lz4")
    _need(0 < len(packed) <= MAX_BUNDLE_BYTES, "Translated image bundle exceeds its producer boundary")
    checked = UnityPy.load(packed)
    checked_objects = {(obj.assets_file.name, obj.path_id): obj for obj in checked.objects}
    _need(set(checked_objects) == set(objects)
          and all(checked_objects[k].class_id == objects[k].class_id for k in objects)
          and all(checked_objects[k].get_raw_data() == raw for k, raw in unchanged.items()),
          "Repacking changed another Unity object")
    output = checked_objects[key].read()
    _need(output.m_Name == name and (output.m_Width, output.m_Height) == (width, height)
          and int(output.m_TextureFormat) == original_format and output.m_MipCount == 1
          and not output.m_IsReadable
          and _sha(output.image.tobytes()) == measurement["decoded_RGBA_sha256"],
          "Translated texture decode readback differs")
    final_state = attrs.asdict(output)
    _check_texture_fields(original_state, final_state)
    if replaced_stream and not original_readable and not geometry_changed:
        _need(checked_objects[key].get_raw_data() == original_texture,
              "Stream-only replacement changed original texture metadata")
    encoded = crypt_header(packed, name) if obfuscated else packed
    _need((crypt_header(encoded, name) if obfuscated else encoded) == packed,
          "Translated bundle header roundtrip differs")
    proof = {"original_sha256": _sha(original), "png": {"bytes": len(png),
        "sha256": png_sha256, "width": width, "height": height},
        "texture": {"name": name, "width": width, "height": height,
            "path_id": reader.path_id, "format_before": original_format, "format_after": original_format,
            "readback_pixel_exact": original_format == 4, **measurement,
            "CPU_pixel_copy_retained": False, "original_other_object_bytes_preserved": True,
            "unrelated_texture_fields_preserved": True,
            "original_width": original_width, "original_height": original_height,
            "GPU_bytes_before": original_gpu_bytes, "GPU_bytes_after": len(encoded_pixels),
            "geometry_policy": "localify-png-size" if geometry_changed else "original"},
        "output_sha256": _sha(encoded), "output_bytes": len(encoded),
        "bundle_compression": "LZ4", "header_obfuscation_preserved": obfuscated,
        "original_stream_replaced": replaced_stream, "runtime_image_hooks": False}
    return encoded, proof
