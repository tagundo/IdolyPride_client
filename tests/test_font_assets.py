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
    report = {'schema': 1, 'policy': 'hangul-font-v1', 'font': {'sha256': font.FONT_SHA256},
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
