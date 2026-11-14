"""Build-only final Korean UI phrases for the pinned Localify data.

Localify particle tokens need surrounding display context at runtime. These
reviewed complete phrases avoid that dependency in a prebuilt I18n CSV. Only
an exact key and its exact upstream Korean value authorize a replacement.
"""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from string import Formatter

from .ui_translation_build import translate_localization_csv

POLICY = "prebuilt-korean-ui-final-phrases-v1"
PROFILE_PATH = Path(__file__).resolve().parents[2] / "client-presentation/translations/ko-ui-final-phrases-v1.json"
PROFILE_SHA256 = "0577c2f4034dce252ab862dd266f5edb266575b730b80786d4a9cd5c05da9739"
MAX_PROFILE_BYTES = 32 * 1024
MAX_CSV_BYTES = 8 * 1024 * 1024
_PARTICLE = re.compile(r"\[(?:은/는|이/가|을/를|과/와|으로/로|으/로|아/야|이/라|이/랑)\]")
_TAGS = re.compile(r"<[^<>]*>")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "Duplicate curated UI profile key")
        result[key] = value
    return result


def _fields(value):
    try:
        return Counter((field, spec, conversion) for _, field, spec, conversion
                       in Formatter().parse(value) if field is not None)
    except ValueError as exc:
        raise ValueError("Malformed curated UI format placeholder") from exc


def _profile():
    _need(not PROFILE_PATH.is_symlink() and PROFILE_PATH.is_file(), "Expected the regular curated UI source profile")
    with PROFILE_PATH.open("rb") as source:
        raw = source.read(MAX_PROFILE_BYTES + 1)
    _need(0 < len(raw) <= MAX_PROFILE_BYTES and _sha(raw) == PROFILE_SHA256,
          "Curated UI source profile differs from the reviewed source")
    profile = json.loads(raw, object_pairs_hook=_object)
    _need(isinstance(profile, dict) and profile.get("schema") == 1
          and profile.get("policy") == POLICY and isinstance(profile.get("entries"), list)
          and len(profile["entries"]) == 33, "Curated UI profile identity differs")
    keys = set()
    for entry in profile["entries"]:
        _need(isinstance(entry, dict) and set(entry) == {"key", "expected_ko", "final_ko"},
              "Malformed curated UI phrase")
        key, expected, final = (entry[name] for name in ("key", "expected_ko", "final_ko"))
        _need(all(isinstance(value, str) and value and "\0" not in value
                  and len(value.encode("utf-8")) <= 8192 for value in (key, expected, final))
              and key not in keys and _PARTICLE.search(expected) and not _PARTICLE.search(final),
              "Curated UI key or final phrase is invalid")
        _need(_fields(expected) == _fields(final) and _TAGS.findall(expected) == _TAGS.findall(final),
              "Curated UI phrase changes a format placeholder or markup tag")
        keys.add(key)
    return profile


def _rows(raw):
    _need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_CSV_BYTES
          and raw.startswith(b"KEY,") and b"\0" not in raw,
          "Expected a bounded, BOM-free UI CSV")
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""),
                            skipinitialspace=True, strict=True)
        _need(next(reader, None) == ["KEY", "Japanese"], "Preserve the original UI CSV header")
        rows = {}
        for row in reader:
            if not row or not row[0] or row[0].startswith("//"):
                continue
            _need(len(row) >= 2 and row[0] not in rows, "Duplicate or incomplete UI CSV record")
            rows[row[0]] = row
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Malformed curated UI CSV input") from exc


def _newlines(value):
    # The stock I18n reader expands exactly this escape after CSV parsing.
    # No trimming, Unicode normalization, or custom text rewriting occurs.
    return value.replace("\\n", "\n")


def apply_csv(csv_bytes):
    """Return a finalized CSV and exact coverage, preserving custom values.

    Missing keys and independently customized translations are left intact.
    Calling the helper again is byte-identical and reports already-final keys.
    The caller still owns the full original-client CSV/proof validation.
    """
    profile = _profile()
    before = _rows(csv_bytes)
    translations = {}
    already_final, skipped = [], []
    for entry in profile["entries"]:
        key, expected, final = (entry[name] for name in ("key", "expected_ko", "final_ko"))
        row = before.get(key)
        if row is None:
            skipped.append({"key": key, "reason": "key_absent"})
        elif _newlines(row[1]) == _newlines(final):
            already_final.append(key)
        elif _newlines(row[1]) == _newlines(expected):
            translations[key] = final
        else:
            skipped.append({"key": key, "reason": "custom_or_other_language_value"})
    if translations:
        result, changed = translate_localization_csv(csv_bytes, translations)
        changed_keys = changed["changed_keys"]
    else:
        result, changed_keys = csv_bytes, []
    after = _rows(result)
    _need(tuple(before) == tuple(after) and set(changed_keys) == set(translations),
          "Curated UI rewrite changed its key roster or selected phrases")
    for key, row in before.items():
        target = after[key]
        _need(row[0] == target[0] and row[2:] == target[2:]
              and (target[1] == row[1] if key not in translations
                   else _newlines(target[1]) == _newlines(translations[key])),
              "Curated UI rewrite changed an unrelated field")
    return result, {"schema": 1, "policy": POLICY, "source_profile_sha256": PROFILE_SHA256,
                    "input_sha256": _sha(csv_bytes), "output_sha256": _sha(result),
                    "output_bytes": len(result), "reviewed_keys": len(profile["entries"]),
                    "changed_keys": changed_keys, "changed_key_count": len(changed_keys),
                    "already_final_keys": already_final, "skipped_keys": skipped,
                    "runtime_particle_resolver_added": False}
