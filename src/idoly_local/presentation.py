"""Public visual preferences and bounded acknowledgements from the local game.

This file never opens account state or changes Unity from the server process.
The graphics-enabled game consumes these values on its own Unity thread.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time


MAX_BYTES = 8192
SETTINGS_PATH = "/client/presentation"
STATUS_PATH = SETTINGS_PATH + "/status"
DEFAULTS = {"schema": 1, "revision": 0, "custom_graphics": False, "quality": 0,
    "target_fps": 0, "render_scale": 1.0, "max_buffer_pixel": 4096,
    "anti_aliasing": -1, "shadow_resolution": 0, "expand_photography": False}
CAPABILITIES = frozenset(("fps", "quality", "resolution", "anti_aliasing", "shadow", "expanded_photography"))
METRICS = frozenset(("screen_width", "screen_height", "render_width", "render_height",
                    "camera_aspect", "base_vertical_fov", "vertical_fov"))
STATUSES = frozenset(("waiting", "applied", "disabled", "unsupported", "waiting_for_scene", "init_failed"))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate presentation field")
        result[key] = value
    return result


def _decode(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Invalid presentation message size")
    return json.loads(raw, object_pairs_hook=_object)


def validate_settings(value):
    if not isinstance(value, dict) or value.keys() != DEFAULTS.keys():
        raise ValueError("Invalid presentation settings fields")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("Unsupported presentation schema")
    if type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**63 - 1:
        raise ValueError("Invalid presentation revision")
    for name in ("custom_graphics", "expand_photography"):
        if type(value[name]) is not bool:
            raise ValueError("Invalid presentation switch")
    for name, allowed in (("quality", (0, 10, 20, 30, 40, 100)),
            ("target_fps", (0, 30, 60, 90, 120)), ("anti_aliasing", (-1, 0, 1, 2)),
            ("shadow_resolution", (0, 512, 1024, 2048, 4096))):
        if type(value[name]) is not int or value[name] not in allowed:
            raise ValueError("Invalid presentation option")
    scale, limit = value["render_scale"], value["max_buffer_pixel"]
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .25 <= scale <= 2:
        raise ValueError("Invalid render scale")
    if type(limit) is not int or not 256 <= limit <= 4096 or limit % 2:
        raise ValueError("Invalid render limit")
    return dict(value)


def validate_report(value):
    fields = {"schema", "bridge_version", "revision", "status", "capabilities", "metrics"}
    if not isinstance(value, dict) or value.keys() != fields:
        raise ValueError("Invalid presentation report fields")
    if (type(value["schema"]) is not int or value["schema"] != 1
            or type(value["bridge_version"]) is not int or value["bridge_version"] != 1
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**63 - 1
            or not isinstance(value["status"], str) or value["status"] not in STATUSES):
        raise ValueError("Invalid presentation report identity")
    caps, metrics = value["capabilities"], value["metrics"]
    if (not isinstance(caps, dict) or caps.keys() != CAPABILITIES
            or any(type(flag) is not bool for flag in caps.values())
            or not isinstance(metrics, dict) or metrics.keys() != METRICS):
        raise ValueError("Invalid presentation capabilities")
    for name, number in metrics.items():
        limit = 179 if name.endswith("fov") else 100 if name == "camera_aspect" else 32768
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= limit:
            raise ValueError("Invalid presentation metric")
    return {**value, "capabilities": dict(caps), "metrics": dict(metrics)}


class PresentationState:
    """Read one fixed preferences file; ACKs are observations, never commands."""

    def __init__(self, path, *, clock=time.monotonic):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self._settings = dict(DEFAULTS)
        self._invalid_file = False
        self._client = None
        self._received = None

    def settings(self):
        try:
            with self.path.open("rb") as stream:
                settings = validate_settings(_decode(stream.read(MAX_BYTES + 1)))
        except FileNotFoundError:
            settings = dict(DEFAULTS)
        except (OSError, ValueError, UnicodeError):
            with self._lock:
                self._invalid_file = True
                return dict(self._settings)
        with self._lock:
            self._settings = settings
            self._invalid_file = False
            return dict(settings)

    def receive(self, raw):
        report = validate_report(_decode(raw))
        with self._lock:
            self._client = report
            self._received = self.clock()
        return {"accepted": True}

    def status(self):
        settings = self.settings()
        with self._lock:
            client = self._client
            if client is None or self._received is None or self.clock() - self._received > 10:
                client = {"status": "waiting", "revision": 0, "bridge_version": 1}
            else:
                client = {**client, "capabilities": dict(client["capabilities"]),
                          "metrics": dict(client["metrics"])}
                if client["revision"] != settings["revision"] and client["status"] in ("applied", "disabled"):
                    client["status"] = "waiting"
            return {"settings": settings, "client": client, "invalid_settings_file": self._invalid_file}
