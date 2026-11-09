"""Strict, bounded diagnostics from the isolated Android game client.

The HTTP transport belongs to ``assets``. This module accepts only structured
exception identities and four known collector signals; raw Unity/logcat lines,
URLs, arguments, timestamps and authentication data are outside the contract.
Snapshots describe the latest observations, not a proof that a wait has ended.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
import re
import threading


MAX_BODY_BYTES = 32768
MAX_BATCH_EVENTS = 32
MAX_STORED_EVENTS = 200
MAX_FRAMES = 16
MAX_FRAME_LENGTH = 192
MAX_TYPE_LENGTH = 128

_TYPE_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:[.+][A-Za-z_][A-Za-z0-9_]*)*", re.ASCII
)
_FRAME_PATTERN = re.compile(
    r"[A-Za-z_<][A-Za-z0-9_`<>]*(?:[.+][A-Za-z_<][A-Za-z0-9_`<>]*)+",
    re.ASCII,
)
_STATUS = {
    "collector_started": ("collector_started", "게임 진단 수집 시작"),
    "logcat_started": ("collecting", "게임 로그 수집 시작"),
    "logcat_stopped": ("collector_stopped", "게임 로그 수집 중지"),
    "shader_warmup_wait": ("shader_wait", "셰이더 준비 완료 대기 중"),
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate client diagnostics field")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Invalid client diagnostics JSON constant")


def _event(value):
    if not isinstance(value, dict):
        raise ValueError("Client diagnostics event must be an object")
    if value.get("kind") == "status":
        if (set(value) != {"kind", "code"} or not isinstance(value["code"], str)
                or value["code"] not in _STATUS):
            raise ValueError("Invalid client diagnostics status")
        return {"kind": "status", "code": value["code"]}
    if value.get("kind") != "exception" or set(value) != {"kind", "type", "frames"}:
        raise ValueError("Invalid client diagnostics event fields")
    name = value["type"]
    if (not isinstance(name, str) or not 1 <= len(name) <= MAX_TYPE_LENGTH
            or _TYPE_PATTERN.fullmatch(name) is None
            or not name.rsplit(".", 1)[-1].rsplit("+", 1)[-1].endswith(("Exception", "Error"))):
        raise ValueError("Invalid client diagnostics exception class")
    frames = value["frames"]
    if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
        raise ValueError("Invalid client diagnostics frames")
    for frame in frames:
        if (not isinstance(frame, str) or not 1 <= len(frame) <= MAX_FRAME_LENGTH
                or _FRAME_PATTERN.fullmatch(frame) is None):
            raise ValueError("Invalid client diagnostics static frame")
    return {"kind": "exception", "type": name, "frames": list(frames)}


def _batch(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY_BYTES:
        raise ValueError("Client diagnostics body must contain at most 32768 bytes")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("Invalid client diagnostics JSON") from error
    if not isinstance(body, dict) or set(body) != {"schema", "source", "events"}:
        raise ValueError("Invalid client diagnostics envelope fields")
    if type(body["schema"]) is not int or body["schema"] != 1 or body["source"] != "android-game":
        raise ValueError("Unsupported client diagnostics schema or source")
    events = body["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_BATCH_EVENTS:
        raise ValueError("Client diagnostics batch must contain 1 to 32 events")
    # Validate the whole batch before changing any state or calling the UI.
    return [_event(value) for value in events]


def _summary(event):
    if event["kind"] == "status":
        return _STATUS[event["code"]][1]
    text = "게임 예외: " + event["type"]
    if event["frames"]:
        text += " @ " + event["frames"][0]
    return text


class ClientDiagnostics:
    """Thread-safe ring of 200 validated events and latest UI observations.

    ``receive`` accepts a UTF-8 JSON byte body, returning an acknowledgement
    containing only the accepted count and canonical final summary. A rejected
    batch raises ``ValueError`` without storing or logging any of its events.
    ``log_callback``, if supplied, receives one canonical string per event;
    callback failures cannot interrupt diagnostics intake.
    """

    def __init__(self, log_callback=None):
        if log_callback is not None and not callable(log_callback):
            raise ValueError("Log callback must accept one message string")
        self._callback = log_callback
        self._lock = threading.Lock()
        self._events = deque(maxlen=MAX_STORED_EVENTS)
        self._received = 0
        self._summary = "게임 진단 대기 중"
        self._stage = "waiting_for_client"
        self._collector_started = False
        self._logcat_running = False
        self._shader_warmup_wait = False
        self._latest_exception = None

    def receive(self, raw: bytes) -> dict:
        events = _batch(raw)
        summaries = [_summary(event) for event in events]
        with self._lock:
            for event, summary in zip(events, summaries):
                self._events.append(event)
                self._received += 1
                self._summary = summary
                if event["kind"] == "exception":
                    self._stage = "unity_exception"
                    self._latest_exception = event
                else:
                    code = event["code"]
                    self._stage = _STATUS[code][0]
                    if code == "collector_started":
                        self._collector_started = True
                    elif code == "logcat_started":
                        self._logcat_running = True
                    elif code == "logcat_stopped":
                        self._logcat_running = False
                    elif code == "shader_warmup_wait":
                        self._shader_warmup_wait = True
        if self._callback is not None:
            for summary in summaries:
                try:
                    self._callback(summary)
                except Exception:
                    # Native UI logging is advisory and cannot own intake.
                    pass
        return {"accepted": len(events), "summary": summaries[-1]}

    def status(self) -> dict:
        """Return an independent, JSON-serializable snapshot of safe fields."""
        with self._lock:
            return deepcopy({
                "received_events": self._received,
                "stored_events": len(self._events),
                "summary": self._summary,
                "progress": {"stage": self._stage, "summary": self._summary},
                "collector_started": self._collector_started,
                "logcat_running": self._logcat_running,
                "shader_warmup_wait": self._shader_warmup_wait,
                "latest_exception": self._latest_exception,
                "events": list(self._events),
            })
