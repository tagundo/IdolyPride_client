from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import pytest

from idoly_local import font_assets as font


def cmap_font(groups=None, *, glyphs=12000, second=None):
    groups = groups or [(0x20, 0x7E, 1), (0xAC00, 0xD7A3, 100)]
    def mapping(values):
        return struct.pack('>HHIII', 12, 0, 16 + 12 * len(values), 0, len(values)) + b''.join(
            struct.pack('>III', *value) for value in values)
    table = mapping(groups)
    records = 1 if second is None else 2
    head = struct.pack('>HH', 0, records)
    if second is None:
        cmap = head + struct.pack('>HHI', 3, 10, 12) + table
    else:
        other = mapping(second)
        cmap = head + struct.pack('>HHI', 0, 4, 20) + struct.pack('>HHI', 3, 10, 20 + len(table)) + table + other
    directory = struct.pack('>4sHHHH', b'OTTO', 2, 0, 0, 0)
    directory += struct.pack('>4sIII', b'maxp', 0, 44, 6)
    directory += struct.pack('>4sIII', b'cmap', 0, 52, len(cmap))
    return directory + struct.pack('>IH', 0x5000, glyphs) + b'\0\0' + cmap


def test_complete_modern_hangul_and_basic_latin_have_real_nonzero_glyphs():
    assert font.unicode_coverage(cmap_font()) == {
        'modern_hangul_syllables': 11172, 'required_modern_hangul_syllables': 11172,
        'basic_latin_characters': 95, 'required_basic_latin_characters': 95,
        'unicode_format': 12, 'unicode_maps_agree': True,
    }


def test_sparse_and_glyph_zero_maps_are_not_called_complete():
    sparse = font.unicode_coverage(cmap_font([(0x20, 0x7E, 1), (0xAC01, 0xD7A3, 100)]))
    assert sparse['modern_hangul_syllables'] == 11171
    zero = font.unicode_coverage(cmap_font([(0x20, 0x7E, 0), (0xAC00, 0xD7A3, 100)]))
    assert zero['basic_latin_characters'] == 94


@pytest.mark.parametrize('groups', [
    [(0x20, 0x7E, 1), (0x7E, 0x80, 100)],
    [(0xAC00, 0xD7A3, 1000)],
    [(0x110000, 0x110001, 1)],
    [(0xD7A3, 0xAC00, 1)],
])
def test_overlapping_reversed_outside_unicode_and_outside_glyph_ranges_rejected(groups):
    with pytest.raises(ValueError, match='glyph range'):
        font.unicode_coverage(cmap_font(groups, glyphs=11500))


def test_disagreeing_unicode_platforms_are_rejected():
    with pytest.raises(ValueError, match='disagree'):
        font.unicode_coverage(cmap_font(second=[(0x20, 0x7E, 1), (0xAC01, 0xD7A3, 100)]))


@pytest.mark.parametrize('mutation', ['header', 'table_count', 'table_offset', 'group_length', 'truncated'])
def test_malformed_cmap_bounds_fail_closed(mutation):
    raw = bytearray(cmap_font())
    if mutation == 'header': raw[:4] = b'wOF2'
    elif mutation == 'table_count': struct.pack_into('>H', raw, 4, 65535)
    elif mutation == 'table_offset': struct.pack_into('>I', raw, 36, len(raw))
    elif mutation == 'group_length': struct.pack_into('>I', raw, 52 + 12 + 4, 9999999)
    else: del raw[-1:]
    with pytest.raises(ValueError):
        font.unicode_coverage(bytes(raw))


def test_build_only_font_and_asset_pins_reject_untrusted_inputs_before_unitypy_import():
    with pytest.raises(ValueError, match='audited Pretendard'):
        font.validate_font(cmap_font())
    for platform in ('ios', 'android'):
        with pytest.raises(ValueError, match='Original sharedassets0'):
            font.patch_bytes(b'not a game asset', b'not a font', platform)
    for platform in ('desktop', [], None):
        with pytest.raises(ValueError, match='Unknown font asset platform'):
            font.patch_bytes(b'asset', b'font', platform)


def test_font_license_and_marker_are_pinned_and_exclude_large_per_object_ledgers(tmp_path):
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'client-presentation/fonts/pretendard-jp-v1.json').read_text())
    assert (policy['bytes'], policy['sha256']) == (font.FONT_BYTES, font.FONT_SHA256)
    license = font.read_license(root / policy['license_file'])
    report = {'schema': 2, 'policy': font.POLICY, 'font': {'sha256': font.FONT_SHA256},
              'object_sha256_before': {'17': 'old'}, 'object_sha256_after': {'17': 'new'}}
    notices = font.package_notices(report, license)
    assert set(notices) == {'IdolyFontSupport.json', 'OFL-Pretendard.txt'}
    assert notices['OFL-Pretendard.txt'] == license
    marker = json.loads(notices['IdolyFontSupport.json'])
    assert 'object_sha256_before' not in marker and 'object_sha256_after' not in marker
    assert marker['license']['sha256'] == hashlib.sha256(license).hexdigest()
    assert marker['license']['reserved_font_names_retained'] is True
    report['notice_members'] = {'IdolyFontSupport.json': {'sha256': 'self-reference'}}
    assert font.package_notices(report, license) == notices
    bad = tmp_path / 'bad-license.txt'
    bad.write_bytes(license + b'changed')
    with pytest.raises(ValueError, match='license differs'):
        font.read_license(bad)
    link = tmp_path / 'font-link.otf'
    link.symlink_to(bad)
    with pytest.raises(ValueError, match='regular'):
        font.read_font(link)


def test_tmp_source_font_and_dynamic_mode_are_verified_without_mutating_the_asset(monkeypatch):
    raw = bytearray(1056)
    def string_at(position, value):
        encoded = value.encode()
        struct.pack_into('<i', raw, position, len(encoded))
        raw[position+4:position+4+len(encoded)] = encoded
        return (position+4+len(encoded)+3)&~3
    position = string_at(28, 'SourceSansPro-Regular SDF') + 20
    position = string_at(position, '1.1.0')
    position = string_at(position, '43fa2ca56150741f682409d5e57bbc2b')
    assert position == 128
    struct.pack_into('<iqi', raw, position, 0, 17, 1)
    monkeypatch.setitem(font.TMP_SOURCE_SHA256, 'ios', hashlib.sha256(raw).hexdigest())
    before = bytes(raw)
    result = font._source_tmp(before, 'ios')
    assert before == bytes(raw)
    assert result['source_Font_reference'] == {'file_id': 0, 'path_id': 17}
    assert result['atlas_population_mode_name'] == 'Dynamic'
    for reference, mode in [(18, 1), (17, 0), (17, 2)]:
        struct.pack_into('<iqi', raw, position, 0, reference, mode)
        monkeypatch.setitem(font.TMP_SOURCE_SHA256, 'ios', hashlib.sha256(raw).hexdigest())
        with pytest.raises(ValueError, match='Font17 in Dynamic'):
            font._source_tmp(bytes(raw), 'ios')


def test_explicit_glyph_coverage_distinguishes_horizontal_bar_from_two_em_dash():
    raw = cmap_font([(0x2015, 0x2015, 1), (0x2E3A, 0x2E3B, 5)])
    assert font.unicode_glyphs(raw, (0x2015, 0x2E3A, 0x2E3B, 0x005F)) == {
        0x2015: 1, 0x2E3A: 5, 0x2E3B: 6, 0x005F: 0}
    for invalid in (-1, 0x110000, True, '2015'):
        with pytest.raises(ValueError, match='code point'):
            font.unicode_glyphs(raw, (invalid,))


def original_dash_tmp(monkeypatch):
    raw = bytearray(1056)
    def text(at, value):
        data = value.encode()
        struct.pack_into('<i', raw, at, len(data))
        raw[at+4:at+4+len(data)] = data
    text(28, 'SourceSansPro-Regular SDF')
    struct.pack_into('<IiqI', raw, 60, font._tmp_hash('SourceSansPro-Regular SDF'),
                     0, 2, font._tmp_hash('SourceSansPro-Regular Atlas Material'))
    text(80, '1.1.0')
    text(92, '43fa2ca56150741f682409d5e57bbc2b')
    struct.pack_into('<iqi', raw, 128, 0, 17, 1)
    text(148, 'Source Sans Pro'); text(168, 'Regular')
    struct.pack_into('<I', raw, 252, 2)
    struct.pack_into('<I', raw, 360, 2)
    for i, codepoint in enumerate((0x2E3A, 0x2E3B)):
        struct.pack_into('<IIIf', raw, 364+16*i, 1, codepoint, 1127+i, 1.)
    struct.pack_into('<iiq', raw, 396, 1, 0, 8)
    struct.pack_into('<I', raw, 424, 2); struct.pack_into('<I', raw, 460, 3)
    struct.pack_into('<ii', raw, 608, 128, 64)
    struct.pack_into('<ii', raw, 700, 128, 64)
    text(652, '43fa2ca56150741f682409d5e57bbc2b')
    text(712, '2E3A-2E3B'); text(728, 'ad7a71ee6bd7e467d9bd41506fada03a')
    monkeypatch.setitem(font.TMP_SOURCE_SHA256, 'android', hashlib.sha256(raw).hexdigest())
    return bytes(raw)


def test_korean_clone_keeps_original_dash_asset_and_gets_independent_empty_graph(monkeypatch):
    original = original_dash_tmp(monkeypatch)
    new = font._korean_tmp(original, 'android')
    assert len(original) == 1056 and len(new) == 864
    assert font._source_tmp(original, 'android')['all_serialized_bytes_unchanged']
    assert new[32:32+len(font.KOREAN_TMP_NAME)] == font.KOREAN_TMP_NAME.encode()
    assert struct.unpack_from('<IiqI', new, 60) == (
        font._tmp_hash(font.KOREAN_TMP_NAME), 0, 25, font._tmp_hash('Pretendard JP SemiBold SDF Atlas Material'))
    assert struct.unpack_from('<iq', new, 128) == (0, 22)
    assert struct.unpack_from('<ii', new, 252) == (0, 0)
    assert struct.unpack_from('<iiq', new, 260) == (1, 0, 24)
    assert struct.unpack_from('<iiiiii', new, 288) == (0, 1, 0, 0, 1023, 1023)
    assert struct.unpack_from('<ii', new, 408) == (1024, 1024)
    assert struct.unpack_from('<ii', new, 500) == (1024, 1024)
    assert b'2E3A-2E3B' not in new and b'0020-007E,AC00-D7A3' in new
    assert b'43fa2ca56150741f682409d5e57bbc2b' not in new
    assert b'ad7a71ee6bd7e467d9bd41506fada03a' not in new
    assert new.count(font.FONT_SHA256[:32].encode()) == 2
    assert new.count(font.FONT_SHA256[32:].encode()) == 1
    assert original == original_dash_tmp(monkeypatch)


@pytest.mark.parametrize('offset,value', [(64, 9), (360, 1), (404, 9), (424, 1), (608, 256), (704, 512)])
def test_korean_clone_rejects_changed_original_graph_or_tables(monkeypatch, offset, value):
    raw = bytearray(original_dash_tmp(monkeypatch)); struct.pack_into('<i', raw, offset, value)
    monkeypatch.setitem(font.TMP_SOURCE_SHA256, 'android', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='long-dash TMP tables'):
        font._korean_tmp(bytes(raw), 'android')


def test_fallback_append_preserves_original_dash_dependency_and_unrelated_bytes():
    old = b'prefix00' + struct.pack('<iiqiq', 2, 0, 19, 0, 21) + b'original-tail'
    new = font._fallback_array(old, 8, (19, 21), (19, 21, 23))
    assert new[:8] == old[:8] and new[-13:] == old[-13:]
    assert struct.unpack_from('<iiqiqiq', new, 8) == (3, 0, 19, 0, 21, 0, 23)
    with pytest.raises(ValueError, match='fallback array'):
        font._fallback_array(old, 8, (21, 19), (21, 19, 23))


def test_private_atlas_uses_matching_alpha8_dimensions_counts_and_empty_pixels(monkeypatch):
    raw = bytearray(8340)
    name = b'SourceSansPro-Regular SDF Atlas'
    struct.pack_into('<i', raw, 0, len(name)); raw[4:4+len(name)] = name
    struct.pack_into('<iii', raw, 44, 128, 64, 8192)
    struct.pack_into('<i', raw, 60, 1)
    struct.pack_into('<i', raw, 128, 8192)
    raw[132:8324] = b'X' * 8192
    monkeypatch.setattr(font, 'ATLAS_SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    original = bytes(raw)
    new = font._korean_atlas(original)
    assert len(new) == 148 + 1024*1024
    assert struct.unpack_from('<iii', new, 44) == (1024, 1024, 1024*1024)
    assert struct.unpack_from('<i', new, 60) == (1,)
    assert struct.unpack_from('<i', new, 128) == (1024*1024,)
    assert new[132:132+1024*1024] == b'\0' * (1024*1024)
    assert new[-16:] == original[-16:]
    assert original[132:8324] == b'X' * 8192


def test_private_material_points_to_private_texture_and_matches_shader_texel_metrics(monkeypatch):
    raw = bytearray(1764)
    for at, text in [(0, 'SourceSansPro-Regular Atlas Material'), (204, '_MainTex'),
                     (1160, '_TextureHeight'), (1184, '_TextureWidth')]:
        value = text.encode(); struct.pack_into('<i', raw, at, len(value))
        raw[at+4:at+4+len(value)] = value
    struct.pack_into('<iq', raw, 216, 0, 8)
    struct.pack_into('<f', raw, 1180, 64.)
    struct.pack_into('<f', raw, 1204, 128.)
    raw[1400:1419] = b'OTHER SHADER BYTES!'
    monkeypatch.setattr(font, 'MATERIAL_SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    original = bytes(raw)
    new = font._korean_material(original)
    # The longer material name shifts all following serialized fields by eight.
    assert len(new) == len(original) + 8
    assert struct.unpack_from('<iq', new, 224) == (0, 24)
    assert struct.unpack_from('<f', new, 1188) == (1024.,)
    assert struct.unpack_from('<f', new, 1212) == (1024.,)
    assert new[1408:1427] == original[1400:1419]
    assert struct.unpack_from('<iq', original, 216) == (0, 8)
