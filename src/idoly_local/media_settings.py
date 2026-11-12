"""Independent public menu preferences; never opens or mutates account state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time


FILENAME = "client-media.json"
SETTINGS_PATH = "/client/media"
MAX_BYTES = 8192
MAX_REVISION = 2**63 - 1
MV_SORTS = frozenset(("recent", "old", "title", "id"))
OUTFIT_SORTS = frozenset(("original", "recent", "old", "title", "id"))
DEFAULTS = {"schema": 1, "revision": 0, "hide_video_mv": False,
            "mv_sort": "recent", "outfit_sort": "original"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate media setting")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Nonfinite media setting")


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() != DEFAULTS.keys():
        raise ValueError("Invalid media setting fields")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("Invalid media setting schema")
    if type(value["revision"]) is not int or not 0 <= value["revision"] <= MAX_REVISION:
        raise ValueError("Invalid media setting revision")
    if type(value["hide_video_mv"]) is not bool:
        raise ValueError("Invalid media video filter")
    for key, choices in (("mv_sort", MV_SORTS), ("outfit_sort", OUTFIT_SORTS)):
        if type(value[key]) is not str or value[key] not in choices:
            raise ValueError("Invalid media sort option")
    return dict(value)


def decode_settings(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Invalid media setting size")
    try:
        return validate_settings(json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                            parse_constant=_constant))
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid media setting JSON") from error


def save_settings(path, settings, *, now_ms=None):
    """Atomically save an explicit edit, advancing only this settings revision.

    Native launchers can use their own equivalent atomic writers. No RPC or
    account ownership is inferred from these local display preferences.
    """
    value = validate_settings(settings)
    if value["revision"] == MAX_REVISION:
        raise ValueError("Media setting revision exhausted")
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_REVISION:
        raise ValueError("Invalid media setting clock")
    value["revision"] = max(value["revision"] + 1, now_ms)
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return value


class MediaSettingsState:
    """Read one fixed app-private file; invalid input preserves the last value."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._settings = dict(DEFAULTS)
        self._invalid_file = False

    def settings(self):
        try:
            # Do not block on a malformed FIFO or follow a settings symlink.
            if not stat.S_ISREG(self.path.lstat().st_mode):
                raise ValueError("Media settings must be a regular file")
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError("Media settings must be a regular file")
                settings = decode_settings(source.read(MAX_BYTES + 1))
        except FileNotFoundError:
            settings = dict(DEFAULTS)
        except (OSError, ValueError):
            with self._lock:
                self._invalid_file = True
                return dict(self._settings)
        with self._lock:
            self._settings = settings
            self._invalid_file = False
            return dict(settings)

    def status(self):
        settings = self.settings()
        with self._lock:
            return {"settings": settings, "invalid_settings_file": self._invalid_file}
