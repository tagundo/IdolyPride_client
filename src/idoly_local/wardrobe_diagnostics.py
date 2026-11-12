"""Account-free observations of the original Android wardrobe transitions."""
from __future__ import annotations

import json
import threading
import time

FIELDS = {"schema", "phase", "show_failures", "released_waits", "sequence", "sample_age_ms"}
PHASES = {"idle", "show_begin", "show_failed", "hide_wait_released", "owner_closed"}
LABELS = {"show_begin": "의상룸 캐릭터 표시 시작",
          "show_failed": "의상룸 캐릭터 표시 취소·실패 확인",
          "hide_wait_released": "의상룸의 취소된 표시 완료 대기를 해제했습니다.",
          "owner_closed": "의상룸 표시 상태 정리"}
MAXIMUM = 2**63 - 1


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate wardrobe diagnostic field")
        result[key] = value
    return result


def decode(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 2048:
        raise ValueError("Invalid wardrobe diagnostic size")
    try:
        row = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid wardrobe diagnostic JSON") from None
    if (not isinstance(row, dict) or set(row) != FIELDS or type(row["schema"]) is not int
            or row["schema"] != 1 or type(row["phase"]) is not str or row["phase"] not in PHASES):
        raise ValueError("Invalid wardrobe diagnostic fields")
    for key in ("show_failures", "released_waits", "sequence"):
        if type(row[key]) is not int or not 0 <= row[key] <= MAXIMUM:
            raise ValueError("Invalid wardrobe diagnostic counter")
    if row["phase"] == "idle":
        if any(row[k] != 0 for k in ("show_failures", "released_waits", "sequence")) or row["sample_age_ms"] is not None:
            raise ValueError("Invalid initial wardrobe observation")
    elif (row["sequence"] == 0 or type(row["sample_age_ms"]) is not int
          or not 0 <= row["sample_age_ms"] <= MAXIMUM
          or row["show_failures"] > row["sequence"] or row["released_waits"] > row["sequence"]):
        raise ValueError("Invalid wardrobe transition observation")
    if row["phase"] == "show_failed" and row["show_failures"] == 0:
        raise ValueError("Missing real show failure observation")
    if row["phase"] == "hide_wait_released" and row["released_waits"] == 0:
        raise ValueError("Missing released wait observation")
    return row


class WardrobeDiagnostics:
    def __init__(self, log_callback=None, *, clock=time.monotonic):
        self._log, self._clock = log_callback, clock
        self._lock = threading.Lock()
        self._client = self._received = self._identity = None

    def receive(self, raw):
        row = decode(raw)
        identity = tuple(row[k] for k in ("phase", "sequence", "show_failures", "released_waits"))
        with self._lock:
            changed = identity != self._identity
            self._client, self._received, self._identity = dict(row), self._clock(), identity
        if changed and self._log is not None and row["phase"] in LABELS:
            try:
                self._log(LABELS[row["phase"]])
            except Exception:
                pass
        return {"accepted": True}

    def status(self):
        with self._lock:
            client = dict(self._client) if self._client is not None else None
            received = self._received
        age = None if received is None else max(0, self._clock() - received)
        return {"client": client, "age_seconds": age}
