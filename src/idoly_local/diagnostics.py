"""Strict, bounded diagnostics from the isolated Android game client.

The HTTP transport belongs to ``assets``. This module accepts only structured
exception identities and four known collector signals; raw Unity/logcat lines,
URLs, arguments, wall-clock timestamps and authentication data are outside the contract.
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
    "probe_ready": ("probe_ready", "홈 단계 추적 준비됨"),
    "probe_unavailable": ("probe_unavailable", "홈 단계 추적을 시작하지 못했습니다"),
    "probe_init_failed": ("probe_init_failed", "기기에서 단계 추적 초기화가 실패했습니다"),
    "probe_selftest_failed": ("probe_selftest_failed", "단계 추적 자가 검사를 통과하지 못했습니다"),
    "probe_profile_mismatch": ("probe_profile_mismatch", "게임 버전이 단계 추적 대상과 일치하지 않습니다"),
    "probe_install_failed": ("probe_install_failed", "게임 단계 관측기를 설치하지 못했습니다"),
    "network_unavailable": ("network_unavailable", "게임 전체 네트워크 수신량을 읽을 수 없습니다"),
    "home_enter": ("home_enter", "홈 진입 처리 시작"),
    "environment_begin": ("environment_begin", "홈 환경 전환 요청"),
    "background_begin": ("background_begin", "홈 배경 장면 불러오기 시작"),
    "background_load_returned": ("background_load_returned", "홈 배경 장면 로딩 대기 통과"),
    "shader_completion_flag": ("shader_completion_flag", "셰이더 완료 플래그 기록됨"),
    "shader_wait_begin": ("shader_wait_begin", "셰이더 플래그 대기 진입"),
    "home_open_begin": ("home_open_begin", "홈 페이지 열기 요청"),
    "loading_hide": ("loading_hide", "로딩 화면 숨김 요청"),
    "front_loading_finished": ("front_loading_finished", "전면 로딩 종료 함수 반환"),
    "home_show_in_returned": ("home_show_in_returned", "홈 표시 전환 대기 통과"),
    "actors_begin": ("actors_begin", "홈 배경 캐릭터 불러오기 시작"),
    "actor_motion_wait": ("actor_motion_wait", "캐릭터 모션 로딩 단계"),
    "actor_cache_build": ("actor_cache_build", "캐릭터 캐시 생성 요청"),
    "actor_result_received": ("actor_result_received", "캐릭터 로딩 결과 수신"),
    "actor_cache_wait": ("actor_cache_wait", "캐릭터 캐시 점검 단계"),
    "actor_load_failed": ("actor_load_failed", "캐릭터 로드 실패 기록"),
    "buttons_begin": ("buttons_begin", "홈 버튼 리소스 준비 진입"),
}
_PROBE_CODES = {"probe_ready", "probe_unavailable", "probe_init_failed", "probe_selftest_failed",
                "probe_profile_mismatch", "probe_install_failed"}
_PHASES = set(_STATUS) - _PROBE_CODES - {"collector_started", "logcat_started", "logcat_stopped",
                                       "network_unavailable"}


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
    if value.get("kind") == "network":
        if set(value) != {"kind", "rx_bytes", "tx_bytes", "elapsed_ms"}:
            raise ValueError("Invalid client network observation fields")
        if any(type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1
               for key in ("rx_bytes", "tx_bytes", "elapsed_ms")):
            raise ValueError("Invalid client network observation counters")
        return dict(value)
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
    if event["kind"] == "network":
        return None
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
        self._phase = None
        self._network = None
        self._network_unavailable = False
        self._native_probe_status = None

    def receive(self, raw: bytes) -> dict:
        events = _batch(raw)
        summaries = [_summary(event) for event in events]
        with self._lock:
            for event, summary in zip(events, summaries):
                self._events.append(event)
                self._received += 1
                if summary is not None and event.get("code") != "network_unavailable":
                    self._summary = summary
                if event["kind"] == "exception":
                    self._stage = "unity_exception"
                    self._latest_exception = event
                elif event["kind"] == "network":
                    self._network = {key: event[key] for key in ("rx_bytes", "tx_bytes", "elapsed_ms")}
                    self._network_unavailable = False
                else:
                    code = event["code"]
                    if code != "network_unavailable":
                        self._stage = _STATUS[code][0]
                    if code == "collector_started":
                        self._collector_started = True
                        self._logcat_running = False
                        self._shader_warmup_wait = False
                        self._latest_exception = None
                        self._phase = None
                        self._network = None
                        self._network_unavailable = False
                        self._native_probe_status = None
                    elif code == "logcat_started":
                        self._logcat_running = True
                    elif code == "logcat_stopped":
                        self._logcat_running = False
                    elif code in ("shader_warmup_wait", "shader_wait_begin"):
                        self._shader_warmup_wait = True
                    elif code == "network_unavailable":
                        self._network_unavailable = True
                    elif code in _PROBE_CODES:
                        self._native_probe_status = code
                    if code in _PHASES:
                        self._phase = {"code": code, "summary": summary}
        if self._callback is not None:
            for summary in summaries:
                if summary is None:
                    continue
                try:
                    self._callback(summary)
                except Exception:
                    # Native UI logging is advisory and cannot own intake.
                    pass
        with self._lock:
            return {"accepted": len(events), "summary": self._summary}

    def status(self, *, include_events=True) -> dict:
        """Return detached observations, optionally including the event history.

        Routine launcher polls need only current observations. Explicit exports
        retain the full bounded history by default, without building and then
        discarding that history during every status refresh.
        """
        if type(include_events) is not bool:
            raise ValueError("Diagnostic history choice must be a boolean")
        with self._lock:
            snapshot = {
                "received_events": self._received,
                "stored_events": len(self._events),
                "summary": self._summary,
                "progress": {"stage": self._stage, "summary": self._summary},
                "collector_started": self._collector_started,
                "logcat_running": self._logcat_running,
                "shader_warmup_wait": self._shader_warmup_wait,
                "latest_exception": self._latest_exception,
                "phase": self._phase,
                "network": self._network,
                "network_unavailable": self._network_unavailable,
                "native_probe_status": self._native_probe_status,
            }
            if include_events:
                snapshot["events"] = list(self._events)
            return deepcopy(snapshot)
