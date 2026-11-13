"""Account-free observations of the original Android wardrobe transitions."""
from __future__ import annotations

import json
import threading
import time
from copy import deepcopy

FIELDS = {"schema", "phase", "show_failures", "released_waits", "sequence", "sample_age_ms"}
PHASES = {"idle", "show_begin", "show_failed", "hide_wait_released", "owner_closed"}
LABELS = {"show_begin": "의상룸 캐릭터 표시 시작",
          "show_failed": "의상룸 캐릭터 표시 취소·실패 확인",
          "hide_wait_released": "의상룸의 취소된 표시 완료 대기를 해제했습니다.",
          "owner_closed": "의상룸 표시 상태 정리"}
MAXIMUM = 2**63 - 1
EXIT_FIELDS = {"schema", "room", "phase", "active", "in_original", "elapsed_ms",
               "last_sync_ms", "max_sync_ms", "max_sync_stage", "sequence", "spans"}
EXIT_STAGES = {"back", "preclose", "hide", "disable", "selection_show", "selection_open", "gc", "unload"}
EXIT_PHASES = EXIT_STAGES | {"idle", "completed"}
EXIT_ROOMS = {"none", "character_costume", "fitting_room"}
EXIT_IDLE = {"schema": 1, "room": "none", "phase": "idle", "active": False,
             "in_original": False, "elapsed_ms": None, "last_sync_ms": 0,
             "max_sync_ms": 0, "max_sync_stage": "none", "sequence": 0, "spans": []}
EXIT_LABELS = {"idle": "종료 추적 대기", "back": "뒤로가기", "preclose": "종료 전 처리",
               "hide": "화면 숨김", "disable": "화면 비활성화", "selection_show": "캐릭터 선택창 표시",
               "selection_open": "캐릭터 선택창 열기", "gc": "가비지 수집", "unload": "미사용 리소스 정리",
               "completed": "캐릭터 선택창 복귀 콜백 반환", "none": "측정 없음"}


def _counter(value):
    return type(value) is int and 0 <= value <= MAXIMUM


def _exit_observation(row):
    if (not isinstance(row, dict) or set(row) != EXIT_FIELDS
            or type(row["schema"]) is not int or row["schema"] != 1
            or type(row["room"]) is not str or row["room"] not in EXIT_ROOMS
            or type(row["phase"]) is not str or row["phase"] not in EXIT_PHASES
            or type(row["active"]) is not bool or type(row["in_original"]) is not bool
            or row["elapsed_ms"] is not None and not _counter(row["elapsed_ms"])
            or any(not _counter(row[key]) for key in ("last_sync_ms", "max_sync_ms", "sequence"))
            or type(row["max_sync_stage"]) is not str
            or row["max_sync_stage"] not in EXIT_STAGES | {"none"}
            or not isinstance(row["spans"], list) or len(row["spans"]) > 8):
        raise ValueError("Invalid wardrobe exit observation")
    for span in row["spans"]:
        if (not isinstance(span, dict) or set(span) != {"stage", "duration_ms"}
                or type(span["stage"]) is not str or span["stage"] not in EXIT_STAGES
                or not _counter(span["duration_ms"])):
            raise ValueError("Invalid wardrobe exit span")
    if row["phase"] == "idle" and row != EXIT_IDLE:
        raise ValueError("Invalid initial wardrobe exit observation")
    # Clock failures and expiry may leave elapsed=null or active=false while
    # an original synchronous call is still running. Never infer completion
    # from these fields, and a bounded ring need not contain the lifetime max.
    return row


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
    if (not isinstance(row, dict) or type(row.get("schema")) is not int
            or row["schema"] not in (1, 2)
            or set(row) != (FIELDS | {"exit"} if row["schema"] == 2 else FIELDS)
            or type(row["phase"]) is not str or row["phase"] not in PHASES):
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
    if row["schema"] == 2:
        _exit_observation(row["exit"])
    return row


class WardrobeDiagnostics:
    def __init__(self, log_callback=None, *, clock=time.monotonic):
        self._log, self._clock = log_callback, clock
        self._lock = threading.Lock()
        self._client = self._received = self._identity = None
        self._exit_sequence = None

    def receive(self, raw):
        row = decode(raw)
        identity = tuple(row[k] for k in ("phase", "sequence", "show_failures", "released_waits"))
        exit_row = row.get("exit")
        exit_sequence = None if exit_row is None else exit_row["sequence"]
        with self._lock:
            changed = identity != self._identity
            exit_changed = exit_sequence != self._exit_sequence
            self._client, self._received, self._identity = deepcopy(row), self._clock(), identity
            self._exit_sequence = exit_sequence
        messages = []
        if changed and row["phase"] in LABELS:
            messages.append(LABELS[row["phase"]])
        if exit_changed and exit_row is not None and exit_row["phase"] != "idle":
            elapsed = "측정 불가" if exit_row["elapsed_ms"] is None else str(exit_row["elapsed_ms"]) + " ms"
            messages.append("의상룸 종료 · " + EXIT_LABELS[exit_row["phase"]] + " · 경과 " + elapsed
                            + " · 최장 동기 처리 " + str(exit_row["max_sync_ms"]) + " ms ("
                            + EXIT_LABELS[exit_row["max_sync_stage"]] + ")")
        for message in messages if self._log is not None else ():
            try:
                self._log(message)
            except Exception:
                pass
        return {"accepted": True}

    def status(self):
        with self._lock:
            client = deepcopy(self._client)
            received = self._received
        age = None if received is None else max(0, self._clock() - received)
        return {"client": client, "age_seconds": age}
