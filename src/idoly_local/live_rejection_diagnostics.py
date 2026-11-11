"""Allowlisted, read-only diagnostics for an unsupported Quest.Start request.

Never format exception text or identifiers supplied by a client or native engine.
Request observations contain only finite categories and booleans, and are not
retained after the transport finishes that request.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import codec
from .rpc import RpcCode


_PATH = "/api.Quest/Start"
_FIRST_QUEST = "qt-main-1-001-01"
_MAX_REQUEST = 16 * 1024 * 1024
_REQUEST_MODE = "request_mode_unsupported"
_REASONS = {
    "No local handler or response fixture for /api.Quest/Start": "no_handler_or_disabled",
    "Experimental main live: only the first main quest with one ordinary saved-deck play is supported": _REQUEST_MODE,
    "Experimental main live: borrowed deck names are not supported": "deck_name_unsupported",
    "Local live input: this main quest is not supported": "quest_unsupported",
    "Local live input: quest conditions or live bonuses are not supported": "quest_bonus_unsupported",
    "Local live input: live photo and accessory bonuses are not supported": "equipment_unsupported",
    "Borrowed live decks are not available locally": "buddy_unsupported",
    "Card enhancement: initial ability release is unsupported": "card_initial_ability_unsupported",
    "Card enhancement: initial skill upgrade is unsupported": "card_initial_skill_unsupported",
    "Card enhancement: support, rank and evolution are not supported": "card_growth_unsupported",
    "Card enhancement: changed card rarity is not supported": "card_rarity_unsupported",
    "Card enhancement: the next card release or skill upgrade is not supported": "card_release_unsupported",
    "Card enhancement: current card has an unsupported parameter projection": "card_parameters_unsupported",
    "Card enhancement: trained skills are not supported": "card_skill_training_unsupported",
    "Card enhancement: learned abilities are not supported": "card_abilities_unsupported",
}
_LABELS = {
    "no_handler_or_disabled": "실험 라이브 처리기 없음 또는 꺼짐",
    _REQUEST_MODE: "첫 퀘스트·일반 1회·모드 조건 미지원",
    "deck_name_unsupported": "저장 덱 이름과 요청 이름 불일치",
    "quest_unsupported": "지원 범위 밖의 퀘스트",
    "quest_bonus_unsupported": "퀘스트 조건·라이브 보너스 미지원",
    "equipment_unsupported": "포토·액세서리 장비 미지원",
    "buddy_unsupported": "대여 버디 미지원",
    "card_initial_ability_unsupported": "카드 초기 능력 해금 미지원",
    "card_initial_skill_unsupported": "카드 초기 스킬 강화 미지원",
    "card_growth_unsupported": "카드 서포트·랭크·진화 상태 미지원",
    "card_rarity_unsupported": "카드 레어리티 변경 상태 미지원",
    "card_release_unsupported": "다음 카드 해금·스킬 강화 경계 미지원",
    "card_parameters_unsupported": "현재 카드 능력치 계산 형태 미지원",
    "card_skill_training_unsupported": "카드 스킬 훈련 상태 미지원",
    "card_abilities_unsupported": "습득한 카드 능력 미지원",
    "native_unsupported": "네이티브 계산기가 미지원 입력을 거절함",
    "unclassified": "알려진 거절 사유에 해당하지 않음",
}


@dataclass(frozen=True)
class QuestStartFacts:
    first_quest: bool
    play_once: bool
    is_auto: bool
    is_skip: bool
    daily_ticket: bool
    buddy_positions: bool


def _reason(code, details):
    if code != RpcCode.UNIMPLEMENTED or type(details) is not str:
        return "unclassified"
    if details.startswith("Native live engine: "):
        return "native_unsupported"
    # Exact fixed strings only; future or reflected details are never copied.
    return _REASONS.get(details, "unclassified")


def quest_start_facts(path, code, details, schema, raw):
    """Observe only a combined request-mode rejection, without reading state."""
    try:
        if path != _PATH or code != RpcCode.UNIMPLEMENTED or _reason(code, details) != _REQUEST_MODE:
            return None
        if type(raw) is not bytes or len(raw) > _MAX_REQUEST:
            return None
        request = schema.request_type(_PATH).FromString(codec.decode(raw))
        return QuestStartFacts(request.questId == _FIRST_QUEST, request.playCount == 1,
            bool(request.isAuto), bool(request.isSkip), bool(request.useDailyTicket),
            bool(request.userBuddyDeckPositions))
    except Exception:
        # Diagnostics must not replace the original RPC failure.
        return None


def format_quest_start_rejection(path, code, details, facts=None):
    """Return a fixed safe log suffix, or None outside the narrowly scoped RPC."""
    try:
        if path != _PATH or code != RpcCode.UNIMPLEMENTED:
            return None
        reason = _reason(code, details)
        result = "live_rejection=" + reason + " · " + _LABELS[reason]
        if reason != _REQUEST_MODE:
            return result
        if type(facts) is not QuestStartFacts:
            return result + " facts=unavailable"
        values = (facts.first_quest, facts.play_once, facts.is_auto, facts.is_skip,
                  facts.daily_ticket, facts.buddy_positions)
        if any(type(value) is not bool for value in values):
            return result + " facts=unavailable"
        return (result + " quest=" + (_FIRST_QUEST if facts.first_quest else "other")
            + " play=" + ("one" if facts.play_once else "other")
            + " auto=" + str(int(facts.is_auto)) + " skip=" + str(int(facts.is_skip))
            + " daily_ticket=" + str(int(facts.daily_ticket))
            + " buddy_positions=" + str(int(facts.buddy_positions)))
    except Exception:
        return ("live_rejection=unclassified · " + _LABELS["unclassified"]
                if path == _PATH and code == RpcCode.UNIMPLEMENTED else None)
