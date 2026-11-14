import hashlib
import json
from pathlib import Path
import struct

import pytest

from idoly_local.client_patch import literal_rows
from idoly_local import ui_display_literals as display


def fixture(platform, *, target_text=None, number=None):
    index = display.PROFILES[platform]['literal_index']
    number = index + 1 if number is None else number
    original = display.SOURCE_TEXT.encode()
    target = original if target_text is None else target_text.encode()
    identifier = b'comparison-operand'
    pool = identifier + original + target
    rows = [struct.pack('<II', len(identifier), 0)] * number
    if number:
        rows[0] = struct.pack('<II', len(original), len(identifier))
    if index < number:
        rows[index] = struct.pack('<II', len(target), len(identifier) + len(original))
    start = 256 + len(rows) * 8
    padding = b'\0' * (-(start + len(pool)) % 8)
    tail = b'OTHER TABLES AND IDENTIFIERS MUST STAY IDENTICAL'
    header = [0] * 64
    header[:8] = [0xFAB11BAF, 31, 256, len(rows)*8, start, len(pool),
                  start + len(pool) + len(padding), len(tail)]
    return struct.pack('<64I', *header) + b''.join(rows) + pool + padding + tail


@pytest.mark.parametrize('platform', ['android', 'ios'])
@pytest.mark.parametrize('language', ['ko', 'en'])
def test_audited_toast_only_changes_one_index_and_preserves_identical_unreviewed_text(platform, language):
    raw = fixture(platform)
    before_header, before_rows = literal_rows(raw)
    expected = hashlib.sha256(raw).hexdigest()
    result, report = display.patch_bytes(raw, platform, language, expected_sha256=expected)
    after_header, after_rows = literal_rows(result)
    target = display.PROFILES[platform]['literal_index']
    assert after_rows[target][3] == display.TRANSLATIONS[language].encode()
    assert after_rows[0][3] == display.SOURCE_TEXT.encode()
    assert all(a[3] == b[3] for a, b in zip(before_rows, after_rows) if a[0] != target)
    assert result[after_header[6]:] == raw[before_header[6]:]
    assert after_header[6] % 8 == before_header[6] % 8
    assert report['input_sha256'] == expected
    assert report['output_sha256'] == hashlib.sha256(result).hexdigest()
    assert report['changed_indexes'] == report['audited_display_literal_indexes'] == [target]
    assert report['all_other_literals_and_metadata_sections_unchanged']
    assert report['input_bound_to_preceding_producer'] and not report['runtime_translation_work']
    assert report['missing_indexes'] == [] and report['inserted_bytes'] % 8 == 0
    assert raw == fixture(platform)


@pytest.mark.parametrize('platform', ['android', 'ios'])
def test_japanese_keeps_every_metadata_byte_and_still_verifies_the_profile(platform):
    raw = fixture(platform)
    result, report = display.patch_bytes(raw, platform, 'ja', expected_sha256=hashlib.sha256(raw).hexdigest())
    assert result == raw
    assert report['changed_indexes'] == [] and report['missing_indexes'] == []
    assert report['inserted_bytes'] == 0 and report['input_sha256'] == report['output_sha256']


@pytest.mark.parametrize('identity', ['0'*64, 'A'*64, '', None, [], 123])
def test_unverified_preceding_producer_identity_is_rejected(identity):
    with pytest.raises(ValueError, match='preceding verified producer'):
        display.patch_bytes(fixture('android'), 'android', 'ko', expected_sha256=identity)


@pytest.mark.parametrize('platform', ['android', 'ios'])
@pytest.mark.parametrize('language', ['ja', 'ko'])
def test_changed_japanese_text_or_missing_fixed_index_is_rejected(platform, language):
    for raw in (fixture(platform, target_text='comparison-operand'), fixture(platform, number=2)):
        with pytest.raises(ValueError, match='index or Japanese text differs'):
            display.patch_bytes(raw, platform, language, expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('platform,language', [('other', 'ko'), ([], 'ko'), ('android', 'fr'), ('ios', [])])
def test_unknown_platform_or_language_does_not_expand_the_allowlist(platform, language):
    with pytest.raises(ValueError, match='platform or language'):
        display.patch_bytes(b'irrelevant', platform, language, expected_sha256='0'*64)


def test_policy_matches_fixed_manual_translation_and_native_display_audit():
    path = Path(__file__).resolve().parents[1] / 'client-presentation/translations/native-display-literals-v1.json'
    policy = json.loads(path.read_text())
    assert policy['policy'] == display.POLICY and policy['source_text'] == display.SOURCE_TEXT
    assert policy['translations'] == display.TRANSLATIONS and policy['runtime_translation_work'] is False
    for platform, profile in display.PROFILES.items():
        assert all(policy['platforms'][platform][key] == profile[key]
                   for key in ('literal_index', 'original_metadata_sha256', 'method_rva', 'display_call_rva', 'callee_rva'))
