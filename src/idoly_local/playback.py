"""Independent public MV rotation preferences and client receipt observations."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time

MAX_BYTES = 8192


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate playback field")
        result[key] = value
    return result


def _decode(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Invalid playback message size")
    return json.loads(raw, object_pairs_hook=_object)


def _identity(value):
    if (type(value["schema"]) is not int or value["schema"] != 1
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**63-1
            or type(value["wait_for_orientation"]) is not bool):
        raise ValueError("Invalid playback identity")


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() != {"schema", "revision", "wait_for_orientation"}:
        raise ValueError("Invalid playback settings fields")
    _identity(value)
    return dict(value)


def validate_report(value):
    fields = {"schema", "bridge_version", "revision", "wait_for_orientation", "supported", "applied"}
    if not isinstance(value, dict) or value.keys() != fields:
        raise ValueError("Invalid playback report fields")
    _identity(value)
    if (type(value["bridge_version"]) is not int or value["bridge_version"] != 1
            or type(value["supported"]) is not bool or type(value["applied"]) is not bool
            or (value["applied"] and not value["supported"])):
        raise ValueError("Invalid playback receipt")
    return dict(value)


class PlaybackState:
    """Read one fixed file; receipt confirms configuration, not MV completion."""

    def __init__(self, path, *, default_wait=True, clock=time.monotonic):
        if type(default_wait) is not bool:
            raise ValueError("Playback default must be a boolean")
        self.path, self.clock = Path(path), clock
        self._default = {"schema": 1, "revision": 0, "wait_for_orientation": default_wait}
        self._settings = dict(self._default)
        self._lock = threading.Lock()
        self._invalid_file = False
        self._client = self._received = None

    def settings(self):
        try:
            with self.path.open("rb") as stream:
                settings = validate_settings(_decode(stream.read(MAX_BYTES+1)))
        except FileNotFoundError:
            settings = dict(self._default)
        except (OSError, ValueError, UnicodeError):
            with self._lock:
                self._invalid_file = True
                return dict(self._settings)
        with self._lock:
            self._settings, self._invalid_file = settings, False
            return dict(settings)

    def receive(self, raw):
        report = validate_report(_decode(raw))
        with self._lock:
            self._client, self._received = report, self.clock()
        return {"accepted": True}

    def status(self):
        settings = self.settings()
        with self._lock:
            if self._client is None or self._received is None or self.clock()-self._received > 10:
                client = {**self._default, "bridge_version": 1, "supported": False, "applied": False}
            else:
                client = dict(self._client)
                if (client["revision"] != settings["revision"]
                        or client["wait_for_orientation"] != settings["wait_for_orientation"]):
                    client["applied"] = False
            return {"settings": settings, "client": client, "invalid_settings_file": self._invalid_file}
