"""Offline UI data writers; no rendering hooks or gameplay-time replacement."""
from __future__ import annotations

import hashlib
import csv
import io
import struct

from .client_patch import HEADER_WORDS, literal_rows


def translate_localization_csv(original, translations):
    """Translate decoded stock I18n CSV with the original parser semantics.

    Stock CsvParser handles quoted commas/quotes/newlines; AddLocalizationText
    then converts literal backslash-n to LF. The KEY header stays literal so
    the stock I18nTextAssetReader recognizes its supported plaintext format.
    Untranslated logical records retain their exact original UTF-8 bytes.
    """
    if not isinstance(original, bytes) or not isinstance(translations, dict):
        raise ValueError("Expected original CSV bytes and a keyed translation table")
    text = original.decode("utf-8-sig")
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    lines, changed, missing = [], [], 0
    physical = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""), skipinitialspace=True, strict=True)
    first = 0
    for row in reader:
        original_record = "".join(physical[first:reader.line_num]); first = reader.line_num
        if len(row) < 2 or not row[0] or row[0].startswith("//") or row[0] == "KEY":
            lines.append(original_record); continue
        key, value = row[:2]
        translated = translations.get(key)
        if not translated:
            missing += 1; lines.append(original_record); continue
        if not isinstance(translated, str) or "\0" in translated:
            raise ValueError("CSV translation requires NUL-free text")
        translated = translated.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        if translated != value:
            changed.append(key)
            ending = "\r\n" if original_record.endswith("\r\n") else "\n"
            output = io.StringIO(newline="")
            # QUOTE_ALL preserves leading tabs/spaces that the stock parser
            # trims from unquoted fields. Header is retained separately above.
            writer = csv.writer(output, lineterminator=ending, quoting=csv.QUOTE_ALL)
            writer.writerow([key, translated, *row[2:]])
            record = output.getvalue()
            if not original_record.endswith(("\r", "\n")):
                record = record[:-len(ending)]
            lines.append(record)
        else:
            lines.append(original_record)
    result = bom + "".join(lines).encode("utf-8")
    return result, {"changed_keys": changed, "missing_keys": missing,
                    "input_sha256": hashlib.sha256(original).hexdigest(),
                    "output_sha256": hashlib.sha256(result).hexdigest()}


def translate_metadata_literals(original, translations, *, allowed_indexes, expected_sha256):
    """Patch audited display literals only, relocating sections like API patching.

    A generic Localify key is NOT sufficient evidence that an IL2CPP literal is
    human text: the same bytes can be an identifier or comparison operand. The
    caller must supply separately audited display literal indexes and the exact
    metadata hash. No implicit match-all mode exists.
    """
    if hashlib.sha256(original).hexdigest() != expected_sha256:
        raise ValueError("UI metadata source identity differs")
    if (not isinstance(translations, dict) or not isinstance(allowed_indexes, (list, tuple, set))
            or any(type(index) is not int or index < 0 for index in allowed_indexes)
            or len(set(allowed_indexes)) != len(allowed_indexes)):
        raise ValueError("An explicit display-literal allowlist is required")
    header, rows = literal_rows(original)
    allowed = set(allowed_indexes)
    if allowed - {row[0] for row in rows}:
        raise ValueError("A selected display literal does not exist")
    insertion, replacements, missing = bytearray(), {}, []
    for number, offset, _index, raw in rows:
        if number not in allowed:
            continue
        try:
            value = translations.get(raw.decode("utf-8"))
        except UnicodeError:
            raise ValueError("An audited display literal is not UTF-8") from None
        if not value:
            missing.append(number); continue
        if not isinstance(value, str) or "\0" in value or len(value.encode("utf-8")) > 16384:
            raise ValueError("Invalid display literal translation")
        encoded = value.encode("utf-8")
        if encoded != raw:
            replacements[number] = (offset, header[5] + len(insertion), encoded)
            insertion.extend(encoded)
    if not replacements:
        return original, {"changed_indexes": [], "missing_indexes": missing,
                          "inserted_bytes": 0, "input_sha256": expected_sha256,
                          "output_sha256": expected_sha256}
    insertion.extend(b"\0" * (-len(insertion) % 8))
    data_end = header[4] + header[5]
    mutable = bytearray(original)
    for offset, index, encoded in replacements.values():
        struct.pack_into("<II", mutable, offset, len(encoded), index)
    result = mutable[:data_end] + insertion + mutable[data_end:]
    changed_header = header.copy()
    for index in range(2, HEADER_WORDS, 2):
        if changed_header[index] >= data_end:
            changed_header[index] += len(insertion)
    changed_header[5] += len(insertion)
    if any(value > 0xffffffff for value in changed_header):
        raise ValueError("Translated metadata exceeds the format bounds")
    struct.pack_into("<64I", result, 0, *changed_header)
    result = bytes(result)
    checked_header, checked = literal_rows(result)
    for before, after in zip(rows, checked):
        expected = replacements[before[0]][2] if before[0] in replacements else before[3]
        if after[3] != expected:
            raise ValueError("UI literal translation roundtrip failed")
    if result[checked_header[6]:] != original[header[6]:]:
        raise ValueError("An unrelated metadata section changed")
    return result, {"changed_indexes": sorted(replacements), "missing_indexes": missing,
                    "inserted_bytes": len(insertion), "input_sha256": expected_sha256,
                    "output_sha256": hashlib.sha256(result).hexdigest()}
