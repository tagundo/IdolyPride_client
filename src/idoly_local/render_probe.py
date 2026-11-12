"""Transient native renderer observations, independent of requested settings."""
from __future__ import annotations

import json
import math
import threading
import time

MAX_BYTES = 8192  # The wire message must be strictly smaller than this bound.
STALE_SECONDS = 10
_FIELDS = {"schema", "state", "actual_mode", "graphics_api", "callback_tid",
           "observations", "sample_age_ms", "cpu_frame_ms", "gpu_frame_ms", "timing_age_ms"}
_NULLABLE = _FIELDS - {"schema", "state", "observations"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate render probe field")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Nonfinite render probe number")


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def validate_report(value):
    """Accept only fixed public readbacks; no launch request implies a mode."""
    if not isinstance(value, dict) or value.keys() != _FIELDS:
        raise ValueError("Invalid render probe fields")
    if (type(value["schema"]) is not int or value["schema"] != 1
            or type(value["state"]) is not str
            or value["state"] not in ("waiting", "observed", "unsupported", "init_failed")
            or not _integer(value["observations"], 0, 2**63-1)):
        raise ValueError("Invalid render probe identity")
    for key, minimum, maximum in (("actual_mode", 0, 5), ("graphics_api", 0, 255),
                                  ("callback_tid", 1, 2**31-1),
                                  ("sample_age_ms", 0, 2**63-1), ("timing_age_ms", 0, 2**63-1)):
        if value[key] is not None and not _integer(value[key], minimum, maximum):
            raise ValueError("Invalid render probe integer")
    for key in ("cpu_frame_ms", "gpu_frame_ms"):
        number = value[key]
        if number is not None and (type(number) not in (int, float)
                                   or not 0 < number <= 60000 or not math.isfinite(number)):
            raise ValueError("Invalid render probe timing")
    has_timing = value["cpu_frame_ms"] is not None or value["gpu_frame_ms"] is not None
    if has_timing != (value["timing_age_ms"] is not None):
        raise ValueError("Missing or unobserved timing age")
    state = value["state"]
    if state in ("waiting", "init_failed"):
        if value["observations"] != 0 or any(value[key] is not None for key in _NULLABLE):
            raise ValueError("Unobserved render probe contains observations")
    elif value["observations"] < 1:
        raise ValueError("Render probe requires an observation")
    elif state == "observed":
        if any(value[key] is None for key in ("actual_mode", "graphics_api", "callback_tid", "sample_age_ms")):
            raise ValueError("Incomplete renderer observation")
    elif value["actual_mode"] is not None:
        raise ValueError("Unsupported renderer has no known mode")
    return dict(value)


class RenderProbeState:
    """Keep one bounded, process-local report; never read or write account files."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._client = self._received = None
        self._observation_identity = self._observed_at = None

    def receive(self, raw):
        if not isinstance(raw, bytes) or not 0 < len(raw) < MAX_BYTES:
            raise ValueError("Invalid render probe message size")
        try:
            report = validate_report(json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                                parse_constant=_constant))
        except (UnicodeError, RecursionError) as error:
            raise ValueError("Invalid render probe JSON") from error
        with self._lock:
            now = self._clock()
            identity = observed_at = None
            if report["state"] == "observed":
                identity = tuple(report[key] for key in ("actual_mode", "graphics_api", "callback_tid", "observations"))
                observed_at = now - report["sample_age_ms"] / 1000
                if identity == self._observation_identity:
                    observed_at = min(observed_at, self._observed_at)
            # A changed counter (including a lower counter after process restart)
            # establishes a new sample. An identical cached sample cannot renew
            # its inferred timestamp merely by repeating the HTTP POST.
            self._observation_identity, self._observed_at = identity, observed_at
            self._client, self._received = report, now
        return {"accepted": True}

    def status(self):
        with self._lock:
            if self._client is None:
                return {"client": None, "age_seconds": None, "stale": True}
            now = self._clock()
            age = max(0.0, now - self._received)
            client = dict(self._client)
            observation_age = None if self._observed_at is None else now - self._observed_at
        # A newly received POST can carry an old native observation. Receipt
        # age alone must never turn that cached sample into a fresh readback.
        stale = (client["state"] != "observed"
                 or max(client["sample_age_ms"] / 1000 + age, observation_age) >= STALE_SECONDS)
        return {"client": client, "age_seconds": age, "stale": stale}
