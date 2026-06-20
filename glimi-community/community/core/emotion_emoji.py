"""Emotion → emoji 매핑.

레이어:
  1. Static dict (`STATIC_EMOJI`) — 자주 쓰는 한국어 감정 라벨 fallback. 이모지가 일정.
  2. Community-local override (`meta` 테이블의 `emotion_emoji_map` 키, JSON dict).
     LLM 이 set_emotion 호출 시 emoji 같이 제안하면 등록됨. **이미 등록된 라벨은 덮어쓰지
     않음** — "안도" 처음 한 번 🫂 로 등록되면 그 community 안에서 영구 🫂.
     이게 "같은 감정인데 매번 이모지 바뀌는 문제" 방지의 핵심.
  3. Fallback "・" (라벨 등장하면 카드에선 평범한 dot 표시).

조회 우선순위: community override > static > "・"
"""
from __future__ import annotations

import json as _json
from typing import Optional


# 자주 쓰는 한국어 감정 — UI 일관성용 default 매핑.
# 처음 EMOTION_EMOJI 16개 + LLM 이 자주 자유 생성하는 라벨들 추가.
STATIC_EMOJI: dict[str, str] = {
    # 기본 16종 (기존 monitor.py / cli.py 와 동일)
    "기쁨": "😊", "평온": "😌", "서운함": "😢", "화남": "😠",
    "설렘": "💗", "불안": "😰", "신남": "🤩", "슬픔": "😥",
    "지침": "😩", "짜증": "😤", "외로움": "🥺", "감동": "🥹",
    "분노": "😠", "기대": "✨", "실망": "😞", "사랑": "💖",
    # LLM 자유 생성 라벨 — 2026-04-30 ~ 2026-05-01 QA 에서 등장한 라벨들 fallback.
    "안심": "😮‍💨", "혼란": "😵‍💫", "감사": "🙏", "피로": "😮‍💨",
    "안도": "🫂", "미안": "😔", "부끄러움": "😳", "뿌듯함": "😌",
    "재미": "😄", "지루함": "😑", "긴장": "😬", "당황": "😵",
    "후회": "😞", "걱정": "😟", "놀람": "😮", "흥미": "🤔",
    "냉소": "😏", "체념": "😶", "활기": "✨",
    # 자주 쓸 만한 추가 vocab — 자신감/호기심/만족/질투 등
    "자신감": "😎", "호기심": "🤨", "만족": "😌", "불만": "😒",
    "질투": "😤", "부러움": "🥲", "그리움": "🥺", "혐오": "🤢",
    "공포": "😨", "두려움": "😨", "위로": "🫂", "응원": "💪",
    "감격": "🥹", "허탈": "😶‍🌫️", "당혹": "😵", "민망": "😅",
    "씁쓸함": "😑", "아쉬움": "😞", "안쓰러움": "🥺", "뿌듯": "😌",
    "긍정": "😊", "부정": "😞", "중립": "😐",
    # QA 등장 라벨 추가 — 감탄/차분/행복/집중/따뜻함/진지함 등
    "감탄": "😲", "차분": "😌", "행복": "😄", "집중": "🧐",
    "따뜻함": "🤗", "진지함": "🧐", "기특": "🥰", "애틋": "🥺",
    "활기참": "✨", "심심함": "😑", "졸림": "😴", "분주함": "😅",
}

# 라벨이 STATIC 에도 community override 에도 없을 때 fallback emoji.
# 이전엔 "・" (단순 dot) 였는데 카드 badge 에서 거의 안 보임 → 사용자가 "이모지 안 뜸"
# 으로 인지. 일반 감정 표현 emoji 로 대체해서 항상 뭔가 표시되게.
FALLBACK_EMOJI = "💭"


def _get_override_map() -> dict[str, str]:
    """현재 community 의 override 사전 (없으면 빈 dict)."""
    try:
        from community import db
        raw = db.get_meta("emotion_emoji_map")
        if not raw:
            return {}
        d = _json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_override_map(d: dict[str, str]) -> None:
    try:
        from community import db
        db.set_meta("emotion_emoji_map", _json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def emoji_for(emotion: str) -> str:
    """감정 라벨 → 이모지. override > static > FALLBACK_EMOJI (💭).
    이전엔 fallback 이 "・" 였는데 시각적으로 "비어있음" 으로 보임 — 항상 의미있는
    이모지가 뜨도록 보장 (LLM 이 set_emotion 의 emoji 인자 안 주는 케이스 안전망)."""
    if not emotion:
        return FALLBACK_EMOJI
    overrides = _get_override_map()
    if emotion in overrides:
        return overrides[emotion]
    return STATIC_EMOJI.get(emotion, FALLBACK_EMOJI)


def register_emoji_for(emotion: str, emoji: str, *, force: bool = False) -> bool:
    """LLM 이 새 emotion 라벨에 대해 emoji 제안. 이미 등록된 건 덮어쓰지 않음 (force=False).
    반환: True 면 신규 등록됨, False 면 무시됨 (이미 매핑 존재).
    """
    if not emotion or not emoji:
        return False
    emotion = emotion.strip()
    emoji = emoji.strip()
    if not emotion or not emoji:
        return False
    overrides = _get_override_map()
    # 이미 override 또는 static 에 있으면 skip (force 시 override)
    if not force:
        if emotion in overrides or emotion in STATIC_EMOJI:
            return False
    overrides[emotion] = emoji
    _save_override_map(overrides)
    return True


def intensity_band(intensity: int | None) -> str:
    """1-10 강도를 3 단계 라벨로. UI 가 0/10 점수처럼 보이는 회귀 방지."""
    if intensity is None:
        return "low"
    try:
        v = int(intensity)
    except (TypeError, ValueError):
        return "low"
    if v >= 8:
        return "high"
    if v >= 4:
        return "mid"
    return "low"


__all__ = ["STATIC_EMOJI", "emoji_for", "register_emoji_for", "intensity_band"]
