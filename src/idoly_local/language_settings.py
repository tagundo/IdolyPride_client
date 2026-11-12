"""Choose prebuilt text catalogs at startup; never translate a rendering frame."""
from __future__ import annotations

import json
from pathlib import Path
import threading

LANGUAGES = ("ja", "ko", "en")
MAX_BYTES = 8192


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate language field")
        result[key] = value
    return result


def validate_settings(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "language"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or type(value["language"]) is not str or value["language"] not in LANGUAGES):
        raise ValueError("Invalid language settings")
    return dict(value)


class LanguageSettingsState:
    """Read one public preference file; invalid edits retain the last valid value."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._settings = {"schema": 1, "language": "ja"}
        self._invalid_file = False

    def settings(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES+1)
            if not 0 < len(raw) <= MAX_BYTES:
                raise ValueError("Language file size")
            value = validate_settings(json.loads(raw.decode("utf-8"), object_pairs_hook=_object))
        except FileNotFoundError:
            value = {"schema": 1, "language": "ja"}
        except (OSError, ValueError, UnicodeError, RecursionError):
            with self._lock:
                self._invalid_file = True
                return dict(self._settings)
        with self._lock:
            self._settings, self._invalid_file = value, False
            return dict(value)

    def status(self):
        settings = self.settings()
        with self._lock:
            return {"settings": settings, "invalid_settings_file": self._invalid_file}


def select_language_tag(master_tag, locale):
    """Select a complete prebuilt ordinary/media tag before profile initialization."""
    if type(locale) is not str or locale not in LANGUAGES:
        raise ValueError("Unknown language")
    path = Path(master_tag)
    if path.name not in ("master-tag.json", "media-master-tag.json"):
        raise ValueError("Unknown master tag kind")
    if locale == "ja":
        return path
    selected = path.parent / "languages" / locale / path.name
    if not selected.is_file() or selected.is_symlink():
        raise ValueError("Requested prebuilt language catalog is missing")
    return selected
