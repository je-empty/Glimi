"""
메모리 매니저 — 5 레이어 기억 시스템

레이어:
  Layer 0 — Raw Archive: conversations 테이블 (영구)
  Layer 1 — Working Window: 최근 N개 raw (runtime이 직접 주입)
  Layer 2 — Episodic Chronicle: L1/L2/L3 rollup (memories 테이블)
  Layer 3 — Semantic Facts: (subject, predicate, object) with supersession (agent_facts)
  Layer 4 — Relationship State: relationships + relationship_history
  Layer 5 — Pinned Memories: memories.is_pinned=1 (오너/유나가 고정)

각 에이전트는 통합 메모리 1개. related_entities 태그로 "누구에 관한 건지" 관리.
저장은 영구, 주입만 budget 기반 선별.

추출: 백그라운드 Haiku worker가 큐 소비. 단일 패스 JSON 추출:
  summary + type + entities + importance + facts[] + relationships[]

주입: get_memory_context() 가 Pinned / Relationship / Episodic(current+retrieved) / Facts 순으로
budget 내에서 조합. Cross-channel 근황은 runtime._get_cross_channel_recent 가 담당.

Disclosure: 내부 대화(internal-*) 메모리를 오너 채널에 주입할 때는 마커 부착.
"""
import os
import re as _re
import json as _json
import math
import queue
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional


# ── 커널 의존성 주입 (Phase 2) — memory 도 DB/프로필/관측을 추상 인터페이스로만 접근.
# 커널은 앱 어댑터를 import 하지 않는다 (standalone 설치 가능). 앱이 set_store()/
# set_profiles()/set_owner()/set_observer() 로 주입 (src/core/memory.py shim 참조).
from .observability import NullObserver

_store = None
_profiles = None
_owner = None
_observer = NullObserver()


def set_store(store):
    global _store
    _store = store


def set_profiles(provider):
    global _profiles
    _profiles = provider


def set_owner(owner):
    global _owner
    _owner = owner


def set_observer(obs):
    global _observer
    _observer = obs


# ── 설정 ─────────────────────────────────────────────

RAW_WINDOW = 15          # runtime이 직접 주입하는 원본 대화 개수
L1_BATCH_SIZE = 5        # L1 요약 단위 (메시지 N개 → 1 L1). 라이브 freshness 우선.
L1_BACKFILL_BATCH = 25   # 백로그 클 때 자동 boost: 한 번에 더 많은 메시지 한 호출에 처리.
L1_BACKFILL_THRESHOLD = 30  # unsummarized > 이 값이면 백필 모드 (큰 배치)
L1_MAX_KEEP = 10         # injection 시 current-channel L1 최대 개수
L2_BATCH_SIZE = 5        # L2 rollup 단위 (L1 N개 → 1 L2)
L2_MAX_KEEP = 5
L3_BATCH_SIZE = 5        # L3 rollup 단위 (L2 N개 → 1 L3)
EXTRACT_WORKER_COUNT = int(os.environ.get("GLIMI_MEMORY_WORKERS", "3"))  # 추출 워커 풀 (병렬)

STALE_L1_HOURS = 24
STALE_L2_DAYS = 3
VERY_STALE_DAYS = 7

MEMORY_TYPES = ("event", "fact", "emotion", "relationship")

EXTRACTION_MODEL = "claude-haiku-4-5"
CLAUDE_AVAILABLE = shutil.which("claude") is not None

# Injection budgets (문자 길이 기준, 대략 4자 = 1 토큰)
BUDGET_PINNED = 400
BUDGET_RELATIONSHIP = 200
BUDGET_EPISODIC_CURRENT = 1800  # 700 → 1800 — 풍부한 L2 가 끝부터 잘려 자각/최신 메모리 손실 회귀 fix
BUDGET_EPISODIC_RETRIEVED = 400
BUDGET_FACTS = 400
BUDGET_SELF_RECENT = 500

# 동적 컨텍스트 예산 — get_memory_context(scale=) 가 설정. num_ctx 작으면 <1, 크면 >1.
# 모든 budget 사용처는 _scaled() 로 감싸 이 배수를 반영. floor 60자 (레이어 완전 증발 방지).
import contextvars as _ctxvars
_MEM_SCALE: _ctxvars.ContextVar = _ctxvars.ContextVar("glimi_mem_scale", default=1.0)


def _scaled(budget: int) -> int:
    """현재 메모리 scale 을 적용한 budget (floor 60자)."""
    s = _MEM_SCALE.get()
    if s >= 0.999:
        return budget
    return max(60, int(budget * s))

# Self-recent cross-channel: 본인이 다른 채널에서 방금 한 발화 — L1 rollup 전이라
# retrieved/facts 블록이 못 잡는 짧은 시간창 cover. 떡볶이 회귀 (그룹채팅에서 1분 전
# "떡볶이 좋아" → dm 에서 "갑자기 왜?" 모르는 척) 가 대표 사례.
SELF_RECENT_WITHIN_MINUTES = 90
SELF_RECENT_LIMIT = 8

# Retrieval scoring 가중치
W_SEMANTIC = 0.4
W_IMPORTANCE = 0.3
W_RECENCY = 0.2
W_RELATIONAL = 0.1
RECENCY_HALFLIFE_DAYS = 30


# ────────────────────────────────────────────────────
# 유틸리티
# ────────────────────────────────────────────────────

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return None
    # 저장 포맷 혼재: 마이그레이션 이후 행은 tz-aware(+00:00), SQLite CURRENT_TIMESTAMP 행은 naive.
    # naive 는 UTC 로 간주해 항상 tz-aware 로 정규화 → 이후 datetime.now(timezone.utc) 와 안전하게 연산.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_age(created_at: str) -> str:
    dt = _parse_iso(created_at)
    if not dt:
        return ""
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "방금"
    if secs < 3600:
        return f"{int(secs/60)}분 전"
    if secs < 86400:
        return f"{int(secs/3600)}시간 전"
    return f"{int(secs/86400)}일 전"


def _is_stale(created_at: str, hours: float) -> bool:
    dt = _parse_iso(created_at)
    if not dt:
        return False
    return (datetime.now(timezone.utc) - dt).total_seconds() >= hours * 3600


def _days_since(created_at: str) -> float:
    dt = _parse_iso(created_at)
    if not dt:
        return 9999.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


_OWNER_ROLE_TERMS = ("오너", "owner", "user", "유저", "사용자", "서버 주인")


def _owner_aliases() -> list[str]:
    """오너 canonical name + 별명(nickname) + 역할어(오너/owner/user/유저) 목록.
    엔티티 정규화용. 예: 심재빈/빈이/재빈/오너/user → 심재빈 으로 통일.
    이유: 유저가 nickname 바꾸거나 LLM이 '오너' 라는 역할어로 엔티티 저장 시 헷갈림 방지.
    """
    try:
        aliases: list[str] = []
        name = (_owner.name() or "").strip()
        if name:
            aliases.append(name)
        try:
            prof = _owner.profile() or {}
            pers = prof.get("personality")
            if isinstance(pers, str):
                import json as _json
                try:
                    pers = _json.loads(pers)
                except Exception:
                    pers = {}
            pers = pers or {}
            nick = (pers.get("nickname") or "").strip()
            if nick and nick not in aliases:
                aliases.append(nick)
        except Exception:
            pass
        for role in _OWNER_ROLE_TERMS:
            if role not in aliases:
                aliases.append(role)
        return aliases
    except Exception:
        return list(_OWNER_ROLE_TERMS)


def _normalize_entity(name: str) -> str:
    """엔티티 정규화. 오너 alias(빈이, 재빈, 심재빈) → canonical(심재빈)."""
    if not name:
        return name
    s = str(name).strip()
    aliases = _owner_aliases()
    if not aliases:
        return s
    canonical = aliases[0]
    if s in aliases:
        return canonical
    # "재빈" 같은 줄임형 — canonical 의 뒷부분과 매칭
    if len(s) >= 2 and canonical.endswith(s):
        return canonical
    return s


_META_SUBJECT_PAT = _re.compile(
    r'^(신규\s*에이전트|새_?에이전트|새_?친구|새\s*친구|에이전트|페르소나|봇|시스템|'
    r'캐릭터|멤버|신규\s*멤버|새\s*멤버|친구\s*\d*|사람|user|agent|member|bot|character|'
    r'멤버들|친구들|사람들|모두|전체|다들|일동|'
    r'이\s*커뮤니티|우리\s*커뮤니티|커뮤니티|서버|방|채널|그룹)$',
    _re.IGNORECASE,
)


def _is_meta_subject(s: str) -> bool:
    """사람 이름 아닌 일반화된 메타 단어인가? (fact subject 부적절).

    "새 멤버", "이 커뮤니티", "멤버들" 같은 추상/집합 명사는 fact subject 로 부적합.
    agents/users 실체에 있는 사람 이름만 허용.
    """
    if not s or not s.strip():
        return True
    s = s.strip()
    if _META_SUBJECT_PAT.match(s):
        return True
    # 너무 짧거나 (1자), 숫자로만 된 것
    if len(s) == 1 or s.isdigit():
        return True
    return False


# ────────────────────────────────────────────────────
# Fact validation — subject 실체성 / predicate 정규화 / profile 중복 / 일시상태
# ────────────────────────────────────────────────────

# Predicate 정규화 맵. Haiku 가 동의어 predicate 을 마구 찍어내는 것을 한 canonical 로 합쳐
# 같은 의미의 fact 가 8 가지 이름으로 중복 저장되는 문제 방지.
# alias → canonical. alias 도 canonical 도 모두 lowercase/공백제거 후 비교.
PREDICATE_ALIASES: dict[str, str] = {
    # preferred_friend_type — "어떤 친구를 원하는가"
    "원하는친구특성": "preferred_friend_type",
    "원하는친구타입": "preferred_friend_type",
    "원하는친구특징": "preferred_friend_type",
    "원하는친구유형": "preferred_friend_type",
    "원하는친구의성향": "preferred_friend_type",
    "원하는캐릭터특성": "preferred_friend_type",
    "원하는캐릭터유형": "preferred_friend_type",
    "선호하는캐릭터유형": "preferred_friend_type",
    "선호하는캐릭터특징": "preferred_friend_type",
    "선호캐릭터타입": "preferred_friend_type",
    "원하는친구": "preferred_friend_type",
    "원하는신규멤버특징": "preferred_friend_type",
    "찾는친구의성향": "preferred_friend_type",
    "찾는친구의선호": "preferred_friend_type",
    # personality — 성격
    "성격": "personality",
    "성격특징": "personality",
    "성격유형": "personality",
    "특징": "personality",
    "성향": "personality",
    # hobby / likes
    "취미": "hobby",
    "좋아하는것": "likes",
    "좋아하는취미": "hobby",
    "좋아하는활동": "likes",
    "즐기는활동": "likes",
    "관심사": "likes",
    "관심있는것": "likes",
    # dislikes
    "싫어하는것": "dislikes",
    "싫어함": "dislikes",
    # speech_style
    "말투": "speech_style",
    "말투특징": "speech_style",
    "어투": "speech_style",
    # occupation / role
    "직업": "occupation",
    "직책": "occupation",
    "담당": "occupation",
    # mbti
    "mbti": "mbti",
    # preference — 분위기/장소 선호
    "선호하는분위기": "preferred_mood",
    "좋아하는분위기": "preferred_mood",
    # request — 오너의 요청 (일시적일 수 있음)
    "요청": "request",
    "원하는것": "request",
    "원함": "request",
    "요청함": "request",
}


def _canonical_predicate(pred: str) -> str:
    """predicate 정규화. alias → canonical. alias 에 없으면 lowercase 후 공백 정리만."""
    if not pred:
        return pred
    raw = str(pred).strip()
    # 공백·언더스코어 제거한 key 로 매칭 (alias 테이블은 이미 공백 없는 형태)
    key = _re.sub(r'[\s_]+', '', raw).lower()
    if key in PREDICATE_ALIASES:
        return PREDICATE_ALIASES[key]
    # 언더스코어 포함 원본 유지하되, 다중 공백은 단일로
    return _re.sub(r'\s+', '_', raw)


# 일시 상태 키워드 — object 이 이 단어만으로 이루어지면 fact 가치 없음 (시간 지나면 무의미).
_TRANSIENT_OBJECT_PAT = _re.compile(
    r'^(오늘|지금|방금|오랜만|잠깐|이따|나중에?|곧|아까|어제|내일|모레|'
    r'요즘|최근|현재|당장|막|이제|금방)$'
)


def _is_transient_object(obj: str) -> bool:
    """object 이 일시적 상태 단어만 담고 있나? ('오랜만', '지금' 등)."""
    if not obj:
        return False
    s = str(obj).strip()
    return bool(_TRANSIENT_OBJECT_PAT.match(s))


def _known_real_subjects() -> set[str]:
    """agents + users 테이블에 실제로 존재하는 사람 이름 집합.
    fact subject 가 여기에 없으면 drop (추상/가상 subject 방지).
    오너 별명(빈이, 재빈) 도 alias 로 허용 — 나중에 _normalize_entity 가 canonical 로 합침.
    """
    names: set[str] = set()
    try:
        for a in _store.list_agents():
            n = (a.get("name") or "").strip()
            if n:
                names.add(n)
    except Exception:
        pass
    try:
        un = (_owner.name() or "").strip()
        if un:
            names.add(un)
    except Exception:
        pass
    try:
        for u in _store.list_users():
            n = (u.get("name") or "").strip()
            if n:
                names.add(n)
    except Exception:
        pass
    # 오너 alias (nickname 포함) 도 허용
    try:
        for a in _owner_aliases():
            if a and a not in _OWNER_ROLE_TERMS:
                names.add(a)
    except Exception:
        pass
    return names


# Profile 필드 ↔ predicate 매핑. 자기 자신 fact 가 이미 profile 에 있는 정보면 skip.
# canonical predicate → profile 내 검사 경로 (lambda).
def _profile_has_value(agent_id: str, canonical_pred: str, obj: str) -> bool:
    """agent 의 profile 에 이미 같은 정보가 있는가?
    canonical_pred ('personality', 'likes', 'dislikes', 'speech_style', 'occupation', 'hobby')
    에 대해 profile 의 해당 필드와 값 비교 (substring / fuzzy contains).
    """
    try:
        prof = _profiles.get(agent_id)
        if not prof:
            return False
    except Exception:
        return False
    obj_norm = _re.sub(r'[\s,，·、/]+', '', str(obj or "")).lower()
    if not obj_norm:
        return False

    def _flatten(v) -> str:
        if v is None:
            return ""
        if isinstance(v, list):
            return " ".join(str(x) for x in v)
        if isinstance(v, dict):
            return " ".join(str(x) for x in v.values())
        return str(v)

    def _unwrap(v):
        """profile 위성 테이블은 {"data": {...}} 로 wrap 되어 저장됨 (agent_personality.data). unwrap."""
        if isinstance(v, str):
            try:
                v = _json.loads(v)
            except Exception:
                return {}
        if isinstance(v, dict) and "data" in v and isinstance(v["data"], dict) and len(v) == 1:
            return v["data"]
        return v or {}

    pers = _unwrap(prof.get("personality"))
    speech = _unwrap(prof.get("speech"))
    daily = _unwrap(prof.get("daily_life"))

    candidates: list[str] = []
    if canonical_pred == "personality":
        candidates.append(_flatten(pers.get("traits")))
        candidates.append(_flatten(pers.get("values")))
    elif canonical_pred == "likes" or canonical_pred == "hobby":
        candidates.append(_flatten(pers.get("likes")))
        candidates.append(_flatten(pers.get("hobby")))
    elif canonical_pred == "dislikes":
        candidates.append(_flatten(pers.get("dislikes")))
    elif canonical_pred == "speech_style":
        candidates.append(_flatten(speech.get("style_description")))
        candidates.append(_flatten(speech.get("style")))
        candidates.append(_flatten(speech.get("tone")))
    elif canonical_pred == "occupation":
        candidates.append(_flatten(prof.get("background")))
        candidates.append(_flatten(daily.get("occupation")))
    elif canonical_pred == "mbti":
        candidates.append(_flatten(prof.get("mbti")))
    else:
        return False

    for c in candidates:
        c_norm = _re.sub(r'[\s,，·、/]+', '', c).lower()
        if not c_norm:
            continue
        # substring 양방향 — obj 가 더 짧으면 c 안에, c 가 더 짧으면 obj 안에
        if obj_norm in c_norm or c_norm in obj_norm:
            return True
    return False


def _validate_fact(agent_id: str, subject: str, predicate: str, obj: str,
                   allowed_subjects: Optional[set[str]] = None) -> Optional[tuple[str, str, str]]:
    """저장 직전 fact 검증. 반환 (subject, canonical_predicate, obj) 또는 None(drop).

    검증:
      1. subject 가 meta/추상 명사면 drop
      2. subject 가 실존 (agents/users) 에 없으면 drop
      3. predicate 정규화 (alias → canonical)
      4. 자기 자신 fact 이고 profile 과 중복이면 skip
      5. object 가 일시 상태 ("오랜만", "지금") 만이면 drop
    """
    if not (subject and predicate and obj):
        return None
    s = _normalize_entity(str(subject).strip())
    p = str(predicate).strip()
    o = str(obj).strip()
    if _is_meta_subject(s):
        return None
    if _is_transient_object(o):
        return None
    known = allowed_subjects if allowed_subjects is not None else _known_real_subjects()
    if known and s not in known:
        # 실존 사람 아닌 subject — drop (보수 기본은 drop 이 아니지만, meta-subject 외에도
        # "새_멤버" 처럼 등록 안 된 가상 인물을 차단해야 함).
        return None
    canon = _canonical_predicate(p)
    # 자기 자신 fact ↔ profile 중복
    try:
        my_prof = _profiles.get(agent_id)
        my_name = my_prof.get("name") if my_prof else None
        if my_name and s == my_name and _profile_has_value(agent_id, canon, o):
            return None
    except Exception:
        pass
    return (s, canon, o)


def _normalize_entities(entities: list) -> list:
    """엔티티 리스트 정규화 + dedup."""
    if not entities:
        return []
    out: list = []
    seen: set = set()
    for e in entities:
        norm = _normalize_entity(str(e))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _replace_nicknames_with_name(text: str) -> str:
    """텍스트 안의 오너 별명/줄임형 등장을 실명으로 치환.
    memory content / summary / fact object / relationship reason 등에 별명이 섞여
    들어가는 걸 막는 후처리. alias 목록 중 canonical (aliases[0] = 실명) 로 통일.
    """
    if not text:
        return text
    aliases = _owner_aliases()
    if len(aliases) < 2:
        return text
    canonical = aliases[0]
    s = str(text)
    # canonical 을 먼저 placeholder 로 보호 — 안 그러면 예: canonical="심재빈", nickname="빈이"
    # 일 때 "심재빈이가" 안의 "빈이" 가 부분매칭돼서 "심재심재빈가" 로 중복 생성됨.
    placeholder = "\x00__GLIMI_OWNER_CANON__\x00"
    s = s.replace(canonical, placeholder)
    for alias in aliases[1:]:
        if not alias or alias == canonical:
            continue
        s = s.replace(alias, canonical)
    s = s.replace(placeholder, canonical)
    return s


def _scrub_extracted(extracted: dict) -> dict:
    """단일 패스 추출 결과에서 content 류 필드를 nickname → name 으로 후처리."""
    if not extracted:
        return extracted
    if extracted.get("summary"):
        extracted["summary"] = _replace_nicknames_with_name(extracted["summary"])
    facts = extracted.get("facts") or []
    for f in facts:
        if not isinstance(f, dict):
            continue
        for k in ("subject", "object"):
            if f.get(k):
                f[k] = _replace_nicknames_with_name(str(f[k]))
    rels = extracted.get("relationships") or []
    for r in rels:
        if not isinstance(r, dict):
            continue
        for k in ("other", "reason"):
            if r.get(k):
                r[k] = _replace_nicknames_with_name(str(r[k]))
    return extracted


def _channel_knows(channel: str, agent_name: str) -> list[str]:
    """채널명에서 disclosure 범위 (이 대화를 직접 아는 사람) 추정."""
    ch = channel or ""
    knows: set[str] = set()
    if ch.startswith("dm-"):
        knows.update([agent_name, "owner"])
    elif ch.startswith("group-"):
        parts = ch[len("group-"):].split("-")
        knows.update(parts)
        knows.add("owner")
    elif ch.startswith("internal-dm-"):
        parts = ch[len("internal-dm-"):].split("-")
        knows.update(parts)
    elif ch.startswith("internal-group-"):
        parts = ch[len("internal-group-"):].split("-")
        knows.update(parts)
    elif ch.startswith("mgr-"):
        knows.update([agent_name, "owner"])
    return sorted(knows)


def _resolve_partner_name(agent_id: str, channel: str) -> Optional[str]:
    """현재 채널의 대화 상대 (에이전트/오너 이름)."""
    my_profile = _profiles.get(agent_id)
    my_name = my_profile["name"] if my_profile else ""

    # mgr-* 채널 — 매니저 ↔ 오너 1:1. partner = 오너 이름.
    if channel.startswith("mgr-") and channel != "mgr-system-log":
        return _owner.name() or None

    names: list[str] = []
    if channel.startswith("dm-"):
        names = [channel[3:]]
    elif channel.startswith("internal-dm-"):
        names = channel[len("internal-dm-"):].split("-")
    elif channel.startswith("group-"):
        names = channel[len("group-"):].split("-")
    elif channel.startswith("internal-group-"):
        names = channel[len("internal-group-"):].split("-")

    for n in names:
        if n and n != my_name:
            return n
    return None


def _resolve_partner_agent_id(agent_id: str, channel: str) -> Optional[str]:
    """partner 의 ID. 페르소나면 agent_id, 오너면 user_id 반환 — relationships 테이블이
    오너↔매니저 row 도 동일 스키마로 보유 (agent_a='nan' 같이)."""
    name = _resolve_partner_name(agent_id, channel)
    if not name:
        return None
    # 오너 이름이면 user_id 반환 (relationships 테이블에 agent_a='nan' 형태로 저장)
    if name == (_owner.name() or ""):
        return _owner.id() or None
    a = _store.get_agent_by_name(name)
    return a["id"] if a else None


# ────────────────────────────────────────────────────
# Async worker (백그라운드 Haiku 추출)
# ────────────────────────────────────────────────────

_extract_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
# (agent_id, channel) 별 락 — 같은 키를 다중 워커가 동시에 추출하면 중복 L1·msg_id 충돌.
_key_locks: dict[tuple[str, str], threading.Lock] = {}
_key_locks_guard = threading.Lock()


def _get_key_lock(key: tuple[str, str]) -> threading.Lock:
    with _key_locks_guard:
        lk = _key_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _key_locks[key] = lk
        return lk


def _ensure_worker():
    """N 개 워커 풀 lazy 시작. 첫 enqueue 때 한 번만 spawn."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        for i in range(max(1, EXTRACT_WORKER_COUNT)):
            t = threading.Thread(target=_worker_loop, daemon=True,
                                 name=f"memory-extractor-{i+1}")
            t.start()


def _worker_loop():
    """워커 루프 — 큐에서 (agent_id, channel) 꺼내서 같은 키 락 잡고 drain.
    같은 키가 큐에 연속 들어와 있으면 한 워커가 모두 처리 (락 보유 중) → 다른 워커는 다른 키로.
    """
    while True:
        try:
            job = _extract_queue.get()
        except Exception:
            continue
        if job is None:
            break
        agent_id, channel = job
        key = (agent_id, channel)
        lk = _get_key_lock(key)
        # try-acquire: 같은 키 이미 처리 중이면 큐에 그대로 두고 (다른 워커가 이미 함) skip.
        if not lk.acquire(blocking=False):
            continue
        try:
            # Drain mode: 한 키에 대해 batch 가 있는 동안 계속 추출.
            # check_and_summarize 가 한 번만 enqueue 하지만 큰 백로그면 N 배치 누적된 상태.
            for _ in range(50):  # 최대 50 배치/회 (~500 메시지) 안전 상한
                try:
                    advanced = _run_extraction_once(agent_id, channel)
                except Exception as e:
                    print(f"[Memory] extraction error for {key}: {e}")
                    break
                if not advanced:
                    break
        finally:
            lk.release()


def _run_extraction_once(agent_id: str, channel: str) -> bool:
    """한 배치만 추출. 실제 진척 있었으면 True (배치 크기 만큼 메시지 처리됨)."""
    latest_l1 = _store.get_latest_memory(agent_id, channel, level=1)
    last_id = latest_l1["msg_id_to"] if latest_l1 else 0
    unsummarized = _store.count_messages_after(channel, last_id)
    if unsummarized < L1_BATCH_SIZE:
        # L2/L3 rollup 만 시도 (L1 충분 누적된 경우)
        try:
            _try_l2_rollup(agent_id, channel)
        except Exception as e:
            print(f"[Memory] L2 rollup 실패: {e}")
        try:
            _try_l3_rollup(agent_id, channel)
        except Exception as e:
            print(f"[Memory] L3 rollup 실패: {e}")
        return False
    # L1 한 배치 추출
    before_id = last_id
    try:
        _try_l1_extract(agent_id, channel)
    except Exception as e:
        print(f"[Memory] L1 추출 실패: {e}")
        return False
    after_latest = _store.get_latest_memory(agent_id, channel, level=1)
    after_id = after_latest["msg_id_to"] if after_latest else 0
    return after_id > before_id


def enqueue_extraction(agent_id: str, channel: str):
    """메시지 저장 직후 호출 — 비동기로 L1/L2/L3 처리."""
    _ensure_worker()
    _extract_queue.put((agent_id, channel))


def check_and_summarize(agent_id: str, channel: str):
    """기존 API 유지 — 이제 비동기 enqueue로만 동작."""
    enqueue_extraction(agent_id, channel)


_hooks_installed = False


def install_owner_extraction_hook():
    """오너 발화도 메모리 추출 대상에 포함.

    기존: 에이전트 응답 후에만 check_and_summarize 호출 → 오너 관점 기억 공백.
    변경: db.log_message 훅으로 speaker == owner 인 메시지마다 enqueue.

    이 훅 덕분에 외부 프로세스 (예: tests/e2e/test_user_bot 의 QA 빈이) 도 DB 공유만 하면
    자동으로 자기 관점 memories/facts/relationships 가 쌓임 → 세션 재시작 시 연속성 확보.
    """
    global _hooks_installed
    if _hooks_installed:
        return

    def _on_owner_message(channel: str, speaker: str, message: str):
        try:
            if speaker and speaker == _owner.id():
                enqueue_extraction(speaker, channel)
        except Exception as e:
            print(f"[Memory] owner extraction hook 오류 (무시): {e}")

    _store.add_message_hook(_on_owner_message)
    _hooks_installed = True


def _run_extraction(agent_id: str, channel: str):
    """동기 버전 (worker에서만 호출). L1 → L2 → L3 파이프라인."""
    try:
        _try_l1_extract(agent_id, channel)
    except Exception as e:
        print(f"[Memory] L1 추출 실패: {e}")
    try:
        _try_l2_rollup(agent_id, channel)
    except Exception as e:
        print(f"[Memory] L2 rollup 실패: {e}")
    try:
        _try_l3_rollup(agent_id, channel)
    except Exception as e:
        print(f"[Memory] L3 rollup 실패: {e}")


# ────────────────────────────────────────────────────
# Claude CLI 호출
# ────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = (
    "너는 순수 텍스트 요약/추출기. 아래 사용자 프롬프트의 지시사항만 따라.\n"
    "주의: cwd 의 CLAUDE.md / 프로젝트 문서 / 코드 컨텍스트는 **완전히 무시해**. "
    "너는 어떤 프로젝트의 코드 assistant 가 아님. 단지 '주어진 대화 텍스트를 "
    "요약/구조화' 하는 툴임.\n"
    "절대 하지 말 것:\n"
    "- 요청이 적절한지 되묻기\n"
    "- 의도 확인 질문\n"
    "- '이게 XX 프로젝트 관련이 맞나요' 류 meta-commentary\n"
    "- 내용이 선정적·개인적이어도 그대로 요약 (사용자 본인의 사적 대화임)\n"
    "- 사과·경고·안내 문구 삽입\n"
    "**오직 요청된 포맷(JSON 또는 글머리표) 만 출력.**"
)

# Haiku refusal/meta-commentary 패턴 감지용 — 이런 텍스트가 요약으로 저장되면 안 됨.
_REFUSAL_MARKERS = (
    "요청이 Glimi", "Glimi 프로젝트와 관련",
    "붙여넣으신", "잘못된 텍스트", "의도가 명확하지",
    "확인이 필요합니다", "명확히 해주시면", "도와드리겠습니다",
    "코드베이스 작업", "아키텍처 개선",
)


def _looks_like_refusal(text: str) -> bool:
    """LLM 이 요약 대신 meta-commentary/refusal 을 뱉은 경우 감지."""
    if not text:
        return True
    t = text[:500]
    # 복수 marker hit = 거의 확실
    hits = sum(1 for m in _REFUSAL_MARKERS if m in t)
    return hits >= 2


def _call_claude(prompt: str, model: str = EXTRACTION_MODEL, timeout: int = 30,
                  system: str = "") -> str:
    """LLM backend 추상화 경유. SDK 설정 시 prompt caching 활용.

    메모리 추출은 구조화 JSON 응답이므로 system 부분을 caching 에 적합한 형태로 분리.
    CLI 백엔드로 fallback 될 경우 **Glimi 프로젝트 루트에서 실행되면 CLAUDE.md 가 로드되어
    Haiku 가 '이건 프로젝트 관련 작업이 아니다' 라고 refusal 뱉는 버그** 때문에
    neutral cwd (HOME) 에서 subprocess 실행시키고, 강한 override system prompt 주입함.
    """
    import os as _os
    try:
        from .llm import generate
        # 호출자가 명시한 system 이 있으면 우선, 없으면 기본 추출기 system 부여.
        effective_system = system or _EXTRACTION_SYSTEM
        resp = generate(
            system=effective_system,
            user=prompt,
            model=model,
            agent_type="memory_extract",
            timeout=timeout,
            max_tokens=1024,
            cacheable_system=True,
            cli_cwd=_os.path.expanduser("~"),  # CLAUDE.md 회피 — CLI 만 해석, SDK 는 무시
        )
        if resp.text:
            if _looks_like_refusal(resp.text):
                print(f"[Memory] refusal 감지 → drop: {resp.text[:120]}...")
                return ""
            return resp.text
        if resp.error:
            print(f"[Memory] LLM 오류: {resp.error}")
    except Exception as e:
        print(f"[Memory] LLM 호출 실패: {e}")
    return ""


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = _re.sub(r'^```(?:json)?\s*\n?', '', raw)
        raw = _re.sub(r'\n?```\s*$', '', raw)
    return raw.strip()


def _extract_json_object(raw: str) -> Optional[dict]:
    raw = _strip_json_fence(raw)
    # Whole string first
    try:
        return _json.loads(raw)
    except Exception:
        pass
    # First balanced {...} match
    m = _re.search(r'\{.*\}', raw, _re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except Exception:
            return None
    return None


# ────────────────────────────────────────────────────
# L1 추출 (단일 패스 JSON)
# ────────────────────────────────────────────────────

def _single_pass_extract(agent_id: str, channel: str, msgs: list[dict]) -> Optional[dict]:
    """Haiku 1회 호출로 summary + type + entities + importance + facts + relationships 추출."""

    profile = _profiles.get(agent_id)
    agent_name = profile["name"] if profile else agent_id
    user_name = _owner.name() or "오너"
    user_id = _owner.id()

    conv_text = "\n".join(
        f"{user_name if m['speaker'] == user_id else (_store.get_agent(m['speaker'])['name'] if m['speaker'].startswith('agent-') and _store.get_agent(m['speaker']) else m['speaker'])}: {m['message']}"
        for m in msgs
    )

    # 실존 사람 이름 목록 — Haiku 가 여기서 subject 를 고르도록 가이드
    try:
        real_names = sorted(_known_real_subjects())
    except Exception:
        real_names = []
    real_names_hint = ", ".join(real_names) if real_names else "(없음)"

    # canonical predicate 가이드 — 동의어 난립 방지
    canonical_predicates = (
        "personality, likes, dislikes, hobby, speech_style, occupation, mbti, "
        "preferred_friend_type, preferred_mood, request, currently_doing, "
        "current_action_ended"
    )

    prompt = (
        f"너는 {agent_name}의 기억 추출기야. 아래 대화 {len(msgs)}건에서 {agent_name} 관점의 기억을 추출해.\n\n"
        "하나의 JSON으로 다음 필드를 추출:\n"
        "- summary: 글머리표 2-5개. 구체적 명사·결정·미해결 사항 그대로. '\\n- '로 구분.\n"
        "- type: event|fact|emotion|relationship 중 지배적 것 하나\n"
        "- entities: 언급된 사람 **실명(이름)** 배열 (자신·오너 제외, 다른 사람만)\n"
        "- importance: 1-10 (인사/잡담=2-3, 일상공유=4-5, 중요결정/감정변화=7+)\n"
        "- facts: 새로 알게 된 개인정보/선호 배열. 각 항목 {subject, predicate, object, importance}\n"
        "- relationships: 관계 변화 배열. 각 항목 {other, type(intimacy|dynamics|speech_style), from, to, reason}\n"
        f"- emotion: 이번 배치 끝에서의 {agent_name} 감정 한 단어 (예: '평온', '설렘', '짜증', '서운', '기쁨'). 변화 없으면 생략.\n"
        "- emotion_intensity: 1-10 감정 강도 (변화 없으면 생략).\n\n"
        "예시:\n"
        '{"summary":"- 지우가 떡볶이 제안\\n- 주말 약속 보류","type":"event","entities":["지우"],"importance":5,'
        '"facts":[{"subject":"지우","predicate":"likes","object":"떡볶이","importance":4}],'
        '"relationships":[],"emotion":"기쁨","emotion_intensity":6}\n\n'
        "규칙:\n"
        f"- 오너({user_name}) 는 항상 실명(이름) 으로 표기. 별명·호칭·'오너'·'빈이오빠' 같은 변형 금지.\n"
        "  summary·facts·relationships·entities 어디든 오너 언급 시 실명만 사용.\n"
        "- 다른 사람도 별명이 아니라 실명(프로필에 등록된 이름) 으로 기록.\n"
        "- 잡담·인사만 있으면 summary는 짧게, importance 낮게.\n"
        "- facts는 확실한 것만 (추측 금지). 없으면 빈 배열.\n"
        "- relationships는 명확한 관계 변화만. 없으면 빈 배열.\n"
        "- JSON만 출력. 다른 텍스트 없이.\n"
        "\n"
        "★ facts 추출 엄격 규칙:\n"
        f"  1. subject 는 반드시 실존 인물 이름. 허용 이름 목록: [{real_names_hint}].\n"
        "     '새 멤버', '새_멤버', '이 커뮤니티', '멤버들', '친구들', '신규 에이전트', '캐릭터' 같은\n"
        "     추상·집합·가상 명사는 subject 로 쓰지 마. 미래에 생길 사람·그룹 전체는 금지.\n"
        "  2. predicate 은 다음 canonical 목록에서 **우선 선택**:\n"
        f"     {canonical_predicates}.\n"
        "     같은 의미를 다른 이름으로 쓰지 마. 예: '원하는친구특성'·'선호하는캐릭터유형'·'원하는친구유형'\n"
        "     은 모두 'preferred_friend_type' 으로 통일. '취미'·'좋아하는취미' 는 'hobby'. '성격'·'성향'·'특징'\n"
        "     은 'personality'. 목록에 없는 개념이면 짧은 영문 snake_case 로 새로 만들되 동의어 난립 금지.\n"
        "  3. 일시 상태 저장 금지. object 이 '오늘', '지금', '방금', '오랜만', '잠깐', '이따', '나중',\n"
        "     '요즘' 같은 시간성 단어만으로 이루어지면 그 fact 는 넣지 마. 시간 지나면 무의미함.\n"
        "     예외: predicate='currently_doing' 은 본질적으로 시간성이지만 핵심 활동이므로 허용.\n"
        f"  3-1. 활동 종료 신호: {agent_name} 가 진행 중이던 공동 활동/게임/이벤트를 명확히 끝낸다고\n"
        f"     발화하면 (예: '마크 끝났어', '이제 그만할게', '게임 다 했다', '나갈게 안녕'),\n"
        f"     {{\"subject\":\"{agent_name}\", \"predicate\":\"current_action_ended\", \"object\":\"<무슨 활동이었는지>\", \"importance\":5}}\n"
        f"     항목을 facts 에 넣어. 시스템이 자동으로 currently_doing → last_activity 이전 처리.\n"
        f"     단순 자리 비움/잠깐 빠짐(예: '잠깐 화장실 다녀올게', '이따 또 보자')은 종료 아님.\n"
        f"  4. 자기 자신({agent_name}) 에 대한 fact 는 **프로필에 이미 있는 정보면 skip**.\n"
        "     (기본 성격·likes/dislikes·말투·직업·MBTI 는 이미 알고 있으니 중복 저장 금지.\n"
        "     자기 자신 fact 는 오직 '이번 대화에서 새로 드러난 자기 발견' 만 허용.)\n"
        "  5. 추측·가정·가상 상황은 fact 가 아님. 대화에서 확정된 사실만.\n"
        "\n"
        f"대화:\n{conv_text}"
    )

    # CLI cold-start + 동시성 경쟁으로 30s 는 페르소나 채널에서 빈번히 timeout → 메모리 적재 실패.
    # 90s 로 확장 (Haiku 자체는 5-15s, 여유는 subprocess 오버헤드 흡수용).
    raw = _call_claude(prompt, model=EXTRACTION_MODEL, timeout=90)
    if not raw:
        return None
    data = _extract_json_object(raw)
    if not data or not isinstance(data, dict):
        return None

    # Normalize
    summary = str(data.get("summary", "")).strip()
    if not summary:
        return None
    mem_type = data.get("type") if data.get("type") in MEMORY_TYPES else None
    entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    entities = [str(e).strip() for e in entities if e and str(e).strip()]
    # Clamp importance
    try:
        importance = max(1, min(10, int(data.get("importance", 5))))
    except Exception:
        importance = 5
    facts = data.get("facts") if isinstance(data.get("facts"), list) else []
    relationships = data.get("relationships") if isinstance(data.get("relationships"), list) else []
    emotion = data.get("emotion") if isinstance(data.get("emotion"), str) else None
    emotion_intensity = data.get("emotion_intensity")

    return {
        "summary": summary,
        "type": mem_type,
        "entities": entities,
        "importance": importance,
        "facts": facts,
        "relationships": relationships,
        "emotion": emotion,
        "emotion_intensity": emotion_intensity,
    }


def _try_l1_extract(agent_id: str, channel: str):
    """L1: 미추출 메시지 ≥ L1_BATCH_SIZE 면 단일 패스로 추출.

    백로그 클 때 (unsummarized > L1_BACKFILL_THRESHOLD) 자동으로 L1_BACKFILL_BATCH 만큼
    큰 배치로 스위치 — 호출당 더 많은 메시지 처리해서 백필 빠르게 따라잡음.
    평소엔 작은 배치로 라이브 freshness 유지.
    """
    latest_l1 = _store.get_latest_memory(agent_id, channel, level=1)
    last_id = latest_l1["msg_id_to"] if latest_l1 else 0
    unsummarized = _store.count_messages_after(channel, last_id)
    if unsummarized < L1_BATCH_SIZE:
        return

    # 백로그 모드 — 큰 배치로 빠르게 흡수
    batch = L1_BACKFILL_BATCH if unsummarized > L1_BACKFILL_THRESHOLD else L1_BATCH_SIZE
    msgs = _store.get_messages_by_range(channel, last_id, batch)
    if len(msgs) < L1_BATCH_SIZE:
        return

    extracted = _single_pass_extract(agent_id, channel, msgs)
    if not extracted:
        return
    extracted = _scrub_extracted(extracted)

    profile = _profiles.get(agent_id)
    agent_name = profile["name"] if profile else agent_id
    knows = _channel_knows(channel, agent_name)

    # related_agent_id: 주 파트너 (역호환용)
    partner_id = _resolve_partner_agent_id(agent_id, channel)

    # 자연 intimacy 증분 — 같은 채널에서 N 메시지 주고받는 것 자체가 관계 축적.
    # Haiku 가 relationships 델타를 보수적으로만 뽑아서 intimacy 변화 거의 안 뽑힘 →
    # L1 배치 하나당 파트너와 intimacy +1 (상한 100). 대화 많이 하면 자연스레 올라감.
    # importance 높은 배치 (감정/중요 결정 등) 는 +2 까지.
    if partner_id and partner_id != agent_id:
        try:
            rel = _store.get_relationship(agent_id, partner_id) or _store.get_relationship(partner_id, agent_id)
            if rel:
                if rel["agent_a"] == agent_id:
                    key_a, key_b = agent_id, partner_id
                else:
                    key_a, key_b = partner_id, agent_id
                natural_delta = 2 if extracted.get("importance", 5) >= 7 else 1
                _store.update_intimacy(key_a, key_b, natural_delta)
        except Exception as e:
            print(f"[Memory] 자연 intimacy 증분 실패: {e}")

    mem_id = _store.add_memory(
        agent_id=agent_id,
        channel=channel,
        level=1,
        content=extracted["summary"],
        mem_type=extracted["type"],
        # 엔티티 정규화 — 오너 alias (빈이/재빈) 를 canonical(심재빈) 로 합쳐 중복 저장 방지
        related_entities=_normalize_entities(extracted["entities"]),
        knows=knows,
        importance=extracted["importance"],
        msg_id_from=msgs[0]["id"],
        msg_id_to=msgs[-1]["id"],
        msg_count=len(msgs),
        related_agent_id=partner_id,
    )

    # 가시성 — system.log 에 추출 진행 한 줄. 사용자가 "라이브로 따라가고 있나?" 확인 가능.
    try:
        backfill_marker = " 📦백필" if batch > L1_BATCH_SIZE else ""
        _observer.system(f"[Memory] L1 +1 {agent_id}@{channel} (msgs {msgs[0]['id']}~{msgs[-1]['id']}, "
                   f"unsummarized 잔량 {unsummarized - len(msgs)}){backfill_marker}")
    except Exception:
        pass

    # Facts → agent_facts
    # allowed_subjects 한 번 lookup 해서 루프마다 DB 조회 안 하도록
    allowed_subjects = _known_real_subjects()
    dropped = 0
    kept = 0
    for f in extracted.get("facts", []):
        if not isinstance(f, dict):
            continue
        raw_subject = str(f.get("subject") or "").strip()
        raw_pred = str(f.get("predicate") or "").strip()
        raw_obj = str(f.get("object") or "").strip()
        validated = _validate_fact(agent_id, raw_subject, raw_pred, raw_obj,
                                    allowed_subjects=allowed_subjects)
        if not validated:
            dropped += 1
            continue
        subject, canon_pred, obj = validated
        try:
            f_imp = max(1, min(10, int(f.get("importance", 5))))
        except Exception:
            f_imp = 5
        try:
            _store.add_fact(
                agent_id=agent_id,
                subject=subject, predicate=canon_pred, object_value=obj,
                source_channel=channel, source_memory_id=mem_id,
                confidence=1.0, importance=f_imp,
            )
            kept += 1
        except Exception as e:
            print(f"[Memory] fact 저장 실패: {e}")
    if dropped:
        print(f"[Memory] fact validation: kept={kept} dropped={dropped}")

    # Relationship delta → relationship_history + intimacy_score 자동 업데이트
    # 기존: delta 를 relationship_history 에만 로그. 그래서 수백 턴 대화해도 intimacy 고정
    # (core bug — 관계 진화 UX 가 반쪽 짜리). 수정: delta type 별로 실제 state 업데이트.
    for r in extracted.get("relationships", []):
        if not isinstance(r, dict):
            continue
        other = str(r.get("other") or "").strip()
        if not other:
            continue
        other_ag = _store.get_agent_by_name(other)
        other_id = other_ag["id"] if other_ag else other
        dtype = str(r.get("type") or "dynamics").strip()
        if dtype not in ("intimacy", "dynamics", "speech_style"):
            dtype = "dynamics"
        try:
            _store.add_relationship_delta(
                agent_a=agent_id, agent_b=other_id,
                delta_type=dtype,
                from_state=str(r.get("from") or "") or None,
                to_state=str(r.get("to") or "") or None,
                reason=str(r.get("reason") or "") or None,
                source_channel=channel, source_memory_id=mem_id,
            )
        except Exception as e:
            print(f"[Memory] relationship delta 저장 실패: {e}")

        # 실제 state 반영 — 관계 레코드가 없으면 건너뜀 (mgr 가 명시적으로 생성해야 하는 관계 존중).
        try:
            rel = _store.get_relationship(agent_id, other_id) or _store.get_relationship(other_id, agent_id)
            if not rel:
                continue
            # agent_a/agent_b 방향 맞추기
            if rel["agent_a"] == agent_id:
                key_a, key_b = agent_id, other_id
            else:
                key_a, key_b = other_id, agent_id

            if dtype == "intimacy":
                # from/to 가 숫자면 차이만큼, 아니면 소량 +3. importance 반영 (고 importance = 큰 변화).
                frm_s = str(r.get("from") or "").strip()
                to_s = str(r.get("to") or "").strip()
                delta: int = 0
                try:
                    # 숫자 추출 시도
                    import re as _re_num
                    fm = _re_num.search(r"-?\d+", frm_s)
                    tm = _re_num.search(r"-?\d+", to_s)
                    if fm and tm:
                        delta = int(tm.group(0)) - int(fm.group(0))
                except Exception:
                    delta = 0
                if delta == 0:
                    # 방향 추정 — 단어 기반
                    positive_cues = ("가까워", "친해", "좋아", "편해", "신뢰", "애정", "설레")
                    negative_cues = ("거리", "불편", "서운", "짜증", "화", "실망", "싫", "갈등")
                    txt = f"{frm_s} {to_s} {r.get('reason') or ''}"
                    if any(c in txt for c in negative_cues):
                        delta = -3
                    else:
                        delta = 3
                # importance 로 스케일 (5 = 기본). 3 = 반, 8+ = 배
                imp = extracted.get("importance", 5) or 5
                scale = max(0.5, imp / 5.0)
                final_delta = max(-15, min(15, int(round(delta * scale))))
                if final_delta != 0:
                    _store.update_intimacy(key_a, key_b, final_delta)
            elif dtype == "dynamics":
                new_dyn = str(r.get("to") or "").strip()
                if new_dyn and len(new_dyn) < 200:
                    _store.set_relationship_dynamics(key_a, key_b, new_dyn)
        except Exception as e:
            print(f"[Memory] relationship state 업데이트 실패: {e}")

    # 감정 자동 업데이트 — 이번 배치에서 dominant 감정이 있으면 반영.
    # type=='emotion' 이거나 importance 높은 배치일 때만. 과도한 흔들림 방지: max ±2 변화.
    try:
        emo = extracted.get("emotion")
        emo_int = extracted.get("emotion_intensity")
        if emo and isinstance(emo, str) and len(emo) < 30:
            cur = _store.get_agent_emotion(agent_id)
            if cur:
                new_int = cur[1] or 5
                try:
                    if emo_int is not None:
                        target = max(1, min(10, int(emo_int)))
                        # 부드럽게 — 한 배치당 ±2 까지만
                        new_int = max(1, min(10, new_int + max(-2, min(2, target - new_int))))
                except Exception:
                    pass
                _store.set_agent_emotion(agent_id, emo, new_int)
    except Exception as e:
        print(f"[Memory] emotion 업데이트 실패: {e}")

    print(f"[Memory] L1 추출: {agent_id} ch={channel} imp={extracted['importance']} "
          f"ents={len(extracted['entities'])} facts={len(extracted.get('facts', []))} "
          f"rels={len(extracted.get('relationships', []))}")


# ────────────────────────────────────────────────────
# L2 / L3 Rollup
# ────────────────────────────────────────────────────

def _rollup_summarize(batch_text: str, level: int) -> str:
    """여러 lower-level 요약을 통합. importance/type은 호출자가 집계."""
    if level == 2:
        instr = (
            "아래는 L1 요약(글머리표) 5개. 중기 메모(L2)로 통합해.\n"
            "추상화하지 말고 구체적 사실(이름·옵션·결정·미해결)을 그대로 살려.\n"
            "글머리표 4~7개. 각 줄 한 문장. 한국어 구어체. 잡담은 제외.\n"
            "요약만 출력, 다른 텍스트 없이."
        )
    else:  # level == 3
        instr = (
            "아래는 L2 요약 5개 (약 한 달 분량). 장기 기억(L3)으로 통합해.\n"
            "월 단위 큰 흐름·관계 변화·기억할 사건 위주로 6~10개 글머리표.\n"
            "세부 사실보다 패턴·변화·중요 사건 중심. 한국어 구어체.\n"
            "요약만 출력, 다른 텍스트 없이."
        )
    prompt = f"{instr}\n\n{batch_text}"
    return _call_claude(prompt, model=EXTRACTION_MODEL, timeout=90)


def _try_l2_rollup(agent_id: str, channel: str):
    """L1 5개 → L2 1개."""
    # 미커버 L1 메모리 (이미 hydrated — related_entities/knows JSON 파싱됨).
    rows = _store.get_uncovered_memories(agent_id, channel, source_level=1)

    if len(rows) < L2_BATCH_SIZE:
        return
    batch = rows[:L2_BATCH_SIZE]
    batch_text = "\n".join(f"- {m['content']}" for m in batch)

    summary = _rollup_summarize(batch_text, level=2)
    if not summary:
        return

    # 집계: entities union, importance max, type dominant
    all_entities: set[str] = set()
    type_counts: dict[str, int] = {}
    max_importance = 0
    all_knows: set[str] = set()
    for m in batch:
        for e in (m.get("related_entities") or []):
            all_entities.add(str(e))
        t = m.get("mem_type")
        if t:
            type_counts[t] = type_counts.get(t, 0) + 1
        imp = m.get("importance") or 5
        if imp > max_importance:
            max_importance = imp
        for k in (m.get("knows") or []):
            all_knows.add(str(k))
    dominant_type = max(type_counts, key=type_counts.get) if type_counts else None
    partner_id = _resolve_partner_agent_id(agent_id, channel)

    _store.add_memory(
        agent_id=agent_id, channel=channel, level=2,
        content=summary,
        mem_type=dominant_type,
        related_entities=_normalize_entities(sorted(all_entities)),
        knows=sorted(all_knows) if all_knows else None,
        importance=max_importance or 5,
        parent_memory_id=batch[-1]["id"],
        msg_id_from=batch[0]["msg_id_from"],
        msg_id_to=batch[-1]["msg_id_to"],
        msg_count=sum(m.get("msg_count") or 0 for m in batch),
        related_agent_id=partner_id,
    )
    print(f"[Memory] L2 rollup: {agent_id} ch={channel} ({len(batch)}개→1)")


def _try_l3_rollup(agent_id: str, channel: str):
    """L2 5개 → L3 1개 (월 단위)."""
    # 미커버 L2 메모리 (이미 hydrated — entity 글자깨짐 방지).
    rows = _store.get_uncovered_memories(agent_id, channel, source_level=2)

    if len(rows) < L3_BATCH_SIZE:
        return
    batch = rows[:L3_BATCH_SIZE]
    batch_text = "\n\n".join(f"[L2 {i+1}]\n{m['content']}" for i, m in enumerate(batch))

    summary = _rollup_summarize(batch_text, level=3)
    if not summary:
        return

    all_entities: set[str] = set()
    type_counts: dict[str, int] = {}
    max_importance = 0
    for m in batch:
        for e in (m.get("related_entities") or []):
            all_entities.add(str(e))
        t = m.get("mem_type")
        if t:
            type_counts[t] = type_counts.get(t, 0) + 1
        imp = m.get("importance") or 5
        if imp > max_importance:
            max_importance = imp
    dominant_type = max(type_counts, key=type_counts.get) if type_counts else None
    partner_id = _resolve_partner_agent_id(agent_id, channel)

    _store.add_memory(
        agent_id=agent_id, channel=channel, level=3,
        content=summary,
        mem_type=dominant_type,
        related_entities=_normalize_entities(sorted(all_entities)),
        importance=max_importance or 5,
        parent_memory_id=batch[-1]["id"],
        msg_id_from=batch[0]["msg_id_from"],
        msg_id_to=batch[-1]["msg_id_to"],
        msg_count=sum(m.get("msg_count") or 0 for m in batch),
        related_agent_id=partner_id,
    )
    print(f"[Memory] L3 rollup: {agent_id} ch={channel} ({len(batch)}개→1)")


# ────────────────────────────────────────────────────
# Retrieval scoring
# ────────────────────────────────────────────────────

def _score_memory(mem: dict, query_entities: set[str], partner_name: Optional[str]) -> float:
    """0-1 점수. query_entities와 partner_name 기준."""
    ents = set(mem.get("related_entities") or [])
    if query_entities:
        semantic = len(ents & query_entities) / max(1, len(query_entities))
    else:
        semantic = 0.0
    importance = (mem.get("importance") or 5) / 10.0
    days = _days_since(mem.get("last_accessed_at") or mem.get("created_at") or "")
    recency = math.exp(-days / RECENCY_HALFLIFE_DAYS)
    relational = 1.0 if (partner_name and partner_name in ents) else 0.0
    return (W_SEMANTIC * semantic + W_IMPORTANCE * importance +
            W_RECENCY * recency + W_RELATIONAL * relational)


def _mentioned_entities(text: str) -> set[str]:
    """텍스트에서 현재 DB에 있는 에이전트/유저 이름 추출."""
    out: set[str] = set()
    if not text:
        return out
    for a in _store.list_agents():
        name = a.get("name") or ""
        if name and name in text:
            out.add(name)
    try:
        un = _owner.name()
        if un and un in text:
            out.add(un)
    except Exception:
        pass
    return out


# ────────────────────────────────────────────────────
# Formatting
# ────────────────────────────────────────────────────

_TYPE_SYMBOLS = {"event": "◆", "fact": "▪", "emotion": "♥", "relationship": "◎"}


def _format_memory_line(m: dict, stale_hours: float, disclose_marker: bool = False) -> str:
    age = _format_age(m.get("created_at", ""))
    t = m.get("mem_type")
    sym = f"{_TYPE_SYMBOLS.get(t, '·')} " if t else ""
    stale_mark = " ⚠stale" if _is_stale(m.get("created_at", ""), stale_hours) else ""
    age_suffix = f" ({age}{stale_mark})" if age else ""
    marker = " 🔒사적" if disclose_marker else ""
    pin = "📌 " if m.get("is_pinned") else ""
    return f"- {pin}{sym}{m['content']}{age_suffix}{marker}"


def _truncate_block(lines: list[str], budget_chars: int) -> list[str]:
    """문자 budget에 맞춰 자르기 (앞에서부터 유지)."""
    out = []
    used = 0
    for line in lines:
        used += len(line) + 1
        if used > budget_chars and out:
            break
        out.append(line)
    return out


# ────────────────────────────────────────────────────
# 주입: get_memory_context (메인)
# ────────────────────────────────────────────────────

def _affection_behavior_hint(score: int) -> str:
    """호감도 (0-100) → 행동 모더레이터 prompt 라인.

    LLM 이 같은 페르소나여도 점수 따라 톤·반응 다르게 나오도록 명시 힌트.
    100 = 찐사랑 연인, 0 = 차갑고 거리감.
    """
    s = max(0, min(100, score))
    if s >= 95:
        return ("- [톤 가이드] 찐사랑 연인 모드 — 어떤 부탁이든 우선 들어주려는 자세, 노골적 애정 표현 자유, "
                "상대를 자기보다 우선. 부끄러움보다 진심 강조.")
    if s >= 85:
        return ("- [톤 가이드] 깊은 사랑 — 솔직한 애정 표현, 약간의 부끄러움이 매력. "
                "상대 부탁 거의 들어줌, 가까운 거리감.")
    if s >= 70:
        return ("- [톤 가이드] 친한 연인/베프 단계 — 농담 많이, 따뜻함 자유롭게 표현, 가벼운 스킨십 표현 OK.")
    if s >= 55:
        return ("- [톤 가이드] 친한 사이 — 편한 반말톤, 가끔 농담, 진지한 감정 표현은 자제.")
    if s >= 35:
        return ("- [톤 가이드] 보통 친밀 — 정중한 친구 톤, 일정 거리 유지, 사적 이야기 조심스럽게.")
    if s >= 15:
        return ("- [톤 가이드] 어색·거리감 — 형식적 답변, 짧게, 친밀한 표현 회피.")
    return ("- [톤 가이드] 차갑고 무관심 — '왜 갑자기?', '뭐?' 같은 톤. 짧고 무감정. "
            "사적 부탁 거부하는 게 자연스러움.")


def get_memory_context(agent_id: str, channel: str, user_message: str = "",
                       scale: float = 1.0) -> str:
    """
    현재 채널 기억 + pinned + 관계 스냅샷 — runtime이 system-reminder에 주입.

    user_message: 현재 턴 유저 입력 (없으면 빈 문자열). 엔티티 매칭에 사용.
    scale: 컨텍스트 예산 배수 (작은 num_ctx → <1 축소, 큰 num_ctx → >1 풍부). 기본 1.0.
    """
    parts: list[str] = []
    _scale_token = _MEM_SCALE.set(scale)

    try:
        _touch_ids: list[int] = []

        # ─ Pinned memories (항상) ─
        pinned = _store.get_pinned_memories(agent_id, limit=10)
        if pinned:
            block = [_format_memory_line(m, STALE_L2_DAYS * 24) for m in pinned]
            block = _truncate_block(block, _scaled(BUDGET_PINNED))
            if block:
                parts.append("## 📌 고정 기억")
                parts.extend(block)
                _touch_ids.extend([m["id"] for m in pinned[:len(block)]])

        # ─ Relationship state (현재 채널 파트너) ─
        partner_name = _resolve_partner_name(agent_id, channel)
        partner_id = _resolve_partner_agent_id(agent_id, channel)
        if partner_id:
            rel = _store.get_relationship(agent_id, partner_id) or _store.get_relationship(partner_id, agent_id)
            if rel:
                lines = [f"## 💞 {partner_name}과의 관계"]
                itm = rel.get("intimacy_score")
                dyn = rel.get("dynamics")
                rtype = rel.get("type")
                bits = []
                if rtype:
                    bits.append(f"{rtype}")
                if itm is not None:
                    bits.append(f"호감도 {itm}/100")
                if dyn:
                    bits.append(dyn)
                if bits:
                    lines.append("- " + ", ".join(bits))
                # 호감도 → 행동 모더레이터 힌트
                if itm is not None:
                    behavior_hint = _affection_behavior_hint(int(itm))
                    if behavior_hint:
                        lines.append(behavior_hint)
                # 최근 관계 변곡점 1-2개
                hist = _store.get_relationship_history(agent_id, partner_id, limit=2)
                for h in hist:
                    reason = h.get("reason") or ""
                    if reason:
                        lines.append(f"- [변화] {h.get('delta_type')}: {h.get('from_state') or '?'}→{h.get('to_state') or '?'} ({reason[:40]})")
                parts.append("\n".join(_truncate_block(lines, _scaled(BUDGET_RELATIONSHIP))))

        # ─ Episodic — current channel (L3/L2/L1) ─
        current_block = _format_current_channel_memories(agent_id, channel)
        if current_block:
            parts.append(current_block)

        # ─ Self-recent cross-channel (raw, L1 rollup 못 따라잡는 1~2분 발화 cover) ─
        self_recent_block = _format_self_recent_cross_channel(agent_id, channel)
        if self_recent_block:
            parts.append(self_recent_block)

        # ─ Episodic — retrieved (다른 채널에서 partner/mentioned 에이전트 관련) ─
        query_entities = _mentioned_entities(user_message)
        if partner_name:
            query_entities.add(partner_name)
        # 자기 이름도 query_entities 에 추가 — 자기 자신을 entity 로 태깅한
        # 다른 채널 메모리/facts 도 surface (L1 이미 만들어진 케이스 cover).
        my_profile = _profiles.get(agent_id)
        my_name = my_profile.get("name") if my_profile else None
        if my_name:
            query_entities.add(my_name)
        retrieved_block, retrieved_ids = _format_retrieved_memories(
            agent_id, channel, query_entities, partner_name
        )
        if retrieved_block:
            parts.append(retrieved_block)
            _touch_ids.extend(retrieved_ids)

        # ─ Semantic facts (파트너/언급된 엔티티 기준) ─
        facts_block = _format_facts_block(agent_id, query_entities)
        if facts_block:
            parts.append(facts_block)

        # ─ last_accessed_at 갱신 ─
        if _touch_ids:
            try:
                _store.touch_memory_access(_touch_ids)
            except Exception:
                pass

    except Exception as e:
        print(f"[Memory] get_memory_context 오류: {e}")
    finally:
        _MEM_SCALE.reset(_scale_token)

    if not parts:
        return ""
    return "\n\n".join(parts)


def _format_current_channel_memories(agent_id: str, channel: str) -> str:
    """현재 채널 L3 + L2 + L1 조합.

    Budget 초과 시 **오래된 항목부터 drop** — 옛날엔 chronological 출력에 budget 끝에서 자르다보니
    최신 L2/L1 (제일 가치 높은 메모리) 가 잘리는 회귀 발생. 이제 newest 우선 keep, 자르려면 oldest 부터.
    """
    # 헤더 + 라인을 (priority, line) 페어로 모은 후 priority 낮은 (= 오래된) 순으로 drop.
    # priority: L1 최신 > L1 옛 > L2 최신 > L2 옛 > L3. 최신 = 사용자 최근 경험과 가장 연관.
    any_very_stale = False
    sections: list[tuple[str, list[str]]] = []  # (header, lines)

    # L3 (월 단위, 있으면 최대 2개)
    l3 = _store.get_memories(agent_id, channel, level=3, limit=2)
    if l3:
        sections.append(("## 🗂 장기 (월단위)",
                         [_format_memory_line(m, VERY_STALE_DAYS * 24) for m in l3]))

    # L2 (최근 N개) — get_memories 가 oldest-first 로 반환하므로 뒤집어 newest-first 로 prompt 노출
    l2 = _store.get_memories(agent_id, channel, level=2, limit=L2_MAX_KEEP)
    l2_newest_first = list(reversed(l2)) if l2 else []
    if l2_newest_first:
        l2_lines = []
        for m in l2_newest_first:
            l2_lines.append(_format_memory_line(m, STALE_L2_DAYS * 24))
            if _is_stale(m.get("created_at", ""), VERY_STALE_DAYS * 24):
                any_very_stale = True
        sections.append(("## 장기 기억", l2_lines))

    # L1 — L2 커버 밖의 것만, newest-first
    l1 = _store.get_memories(agent_id, channel, level=1, limit=L1_MAX_KEEP)
    if l2:
        last_l2_covered = max((m["msg_id_to"] or 0) for m in l2)
        l1 = [m for m in l1 if (m.get("msg_id_from") or 0) > last_l2_covered]
    l1_newest_first = list(reversed(l1)) if l1 else []
    if l1_newest_first:
        sections.append(("## 최근 기억",
                         [_format_memory_line(m, STALE_L1_HOURS) for m in l1_newest_first]))

    if not sections:
        return ""

    # Budget enforcement — 오래된 라인부터 trim. L1 (최신) 보존 우선.
    # 각 섹션 안에서도 최신 라인 (앞쪽) 우선, 맨 뒤 (오래된) 부터 drop.
    def _total_chars(secs):
        return sum(len(h) + 1 + sum(len(l) + 1 for l in lines) for h, lines in secs)

    budget = _scaled(BUDGET_EPISODIC_CURRENT)
    # priority order to drop from: L3 (가장 거시적) → L2 끝 → L1 끝
    while _total_chars(sections) > budget:
        # 자를 후보 — 오래된 섹션 + 그 안의 가장 오래된 라인
        # 우선 L3 안에서 끝 라인부터, 다음 L2, 마지막 L1.
        for section_idx in range(len(sections)):
            sec_header = sections[section_idx][0]
            if "🗂 장기" in sec_header or "장기 기억" in sec_header:
                if len(sections[section_idx][1]) > 1:
                    sections[section_idx][1].pop()  # drop oldest line in this section
                    break
                elif len(sections[section_idx][1]) == 1:
                    sections.pop(section_idx)
                    break
        else:
            # 모두 1줄짜리거나 섹션 다 비었음 — L1 마지막 라인부터 drop
            for section_idx in range(len(sections)):
                if len(sections[section_idx][1]) > 1:
                    sections[section_idx][1].pop()
                    break
                else:
                    sections.pop(section_idx)
                    break
            else:
                break  # 더 이상 drop 할 게 없음

    out: list[str] = []
    for header, lines in sections:
        out.append(header)
        out.extend(lines)
    if any_very_stale:
        out.insert(0, "⚠ 일부 장기 기억이 1주일 이상 지났어. 현재 대화에서 사실 확인 후 업데이트해.")
    return "\n".join(out)


def _format_retrieved_memories(agent_id: str, exclude_channel: str,
                                query_entities: set[str],
                                partner_name: Optional[str]) -> tuple[str, list[int]]:
    """다른 채널 메모리를 entity/importance/recency 로 scoring → top-N 주입.

    Disclosure: 내부 대화(internal-*) 출처인데 현재 채널이 오너 채널이면 '🔒사적' 마커.
    """
    if not query_entities:
        return "", []

    is_owner_channel = (
        exclude_channel.startswith("dm-") or exclude_channel.startswith("group-")
        or exclude_channel.startswith("mgr-")
    )

    rows = _store.get_memories_across_channels(
        agent_id, exclude_channel, levels=[1, 2, 3], limit=200
    )

    # entity 매칭 필터 (적어도 1개 겹쳐야 후보). rows 는 이미 hydrated.
    candidates: list[dict] = []
    for m in rows:
        ents = set(m.get("related_entities") or [])
        if ents & query_entities:
            candidates.append(m)

    if not candidates:
        return "", []

    # Score + top 5
    scored = [(m, _score_memory(m, query_entities, partner_name)) for m in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [m for m, s in scored[:5] if s > 0]

    if not top:
        return "", []

    # Group by label (related_agent_id 이름 or channel 파싱)
    groups: dict[str, list[dict]] = {}
    for m in top:
        ch = m.get("channel") or ""
        label = None
        rid = m.get("related_agent_id")
        if rid:
            p = _profiles.get(rid)
            if p:
                label = p["name"]
        if not label:
            for prefix in ("internal-dm-", "internal-group-", "dm-", "group-"):
                if ch.startswith(prefix):
                    label = ch[len(prefix):]
                    break
            label = label or ch
        groups.setdefault(label, []).append(m)

    lines = ["## 🧠 다른 대화에서 관련 기억 (참고용 — 지금 상대 앞에서 이 주제 먼저 꺼내지 말 것)"]
    touched: list[int] = []
    for label, mems in groups.items():
        is_internal = any((m.get("channel") or "").startswith("internal-") for m in mems)
        disclosure = is_owner_channel and is_internal
        header = f"[{label}과 나눈 대화]"
        if disclosure:
            header += " (🔒 이 내용은 멤버간 사적 대화 — 오너한테 먼저 꺼내지 마)"
        lines.append(header)
        for m in mems:
            lines.append(_format_memory_line(m, VERY_STALE_DAYS * 24, disclose_marker=disclosure))
            touched.append(m["id"])

    truncated = _truncate_block(lines, _scaled(BUDGET_EPISODIC_RETRIEVED))
    return "\n".join(truncated), touched


def _format_self_recent_cross_channel(
    agent_id: str,
    current_channel: str,
    within_minutes: int = SELF_RECENT_WITHIN_MINUTES,
    limit: int = SELF_RECENT_LIMIT,
) -> str:
    """본인이 최근 N분 내 다른 채널에서 한 발화를 raw conversations 에서 직접 surface.

    L1 rollup 은 5메시지 단위로 비동기 — 1~2분 전 발화는 아직 메모리화 안 돼서
    `_format_retrieved_memories` 에 안 잡힘. 동일 페르소나가 그룹/dm/internal 사이에서
    모순 발화하는 회귀 (떡볶이 케이스: 그룹에서 "떡볶이 좋아" → 1분 후 dm 에서
    "갑자기 왜?" 모르는 척) 를 raw 타임라인 직접 조회로 차단.

    Universe scoping 은 자기 메시지에는 무의미 (동일 페르소나 = 동일 universe).
    Disclosure: 현재가 owner 채널 (dm-/group-) 인데 surface 출처가 internal-* 면
    🔒 마커 부착 — 페르소나가 오너에게 사적 대화 내용 먼저 꺼내지 않게.
    """
    # SQLite datetime('now', '-N minutes') 사용 — naive UTC 기준 비교 (DB 의 기본
    # CURRENT_TIMESTAMP 포맷과 매치). get_messages_in_range 와 동일 패턴.
    rows = _store.get_recent_messages_across_channels(
        agent_id, current_channel, within_minutes, limit
    )

    if not rows:
        return ""

    is_owner_channel_now = (
        current_channel.startswith("dm-")
        or current_channel.startswith("group-")
        or current_channel.startswith("mgr-")
    )

    # Group by channel, oldest first within each group (자연스러운 시간순)
    by_channel: dict[str, list[dict]] = {}
    for r in reversed(rows):
        by_channel.setdefault(r["channel"], []).append(dict(r))

    lines = ["## 🪞 내가 방금 다른 채널에서 한 말 (모순 없게 일관성 유지)"]
    for ch, msgs in by_channel.items():
        is_internal = ch.startswith("internal-")
        disclosure = is_owner_channel_now and is_internal
        # short label
        label = ch
        for prefix in ("internal-dm-", "internal-group-", "dm-", "group-"):
            if ch.startswith(prefix):
                label = ch[len(prefix):]
                break
        header = f"[#{label}]"
        if disclosure:
            header += " (🔒 사적 대화 — 오너 앞에서 먼저 꺼내지 말기)"
        lines.append(header)
        for m in msgs:
            ts = m.get("timestamp", "") or ""
            hhmm = ts[11:16] if len(ts) >= 16 else ""
            msg = (m.get("message") or "").replace("\n", " ")
            if len(msg) > 100:
                msg = msg[:100] + "…"
            lines.append(f"  {hhmm} \"{msg}\"")

    truncated = _truncate_block(lines, _scaled(BUDGET_SELF_RECENT))
    return "\n".join(truncated)


_PRED_LABELS = {
    "currently_doing": "지금 하는 중",
    "last_activity": "최근 활동 (이미 끝남)",
}


def _format_facts_block(agent_id: str, query_entities: set[str]) -> str:
    """파트너/언급 엔티티에 대한 facts."""
    if not query_entities:
        return ""
    lines: list[str] = []
    shown = 0
    for ent in query_entities:
        facts = _store.get_facts(agent_id, subject=ent, limit=5)
        if not facts:
            continue
        lines.append(f"[{ent} 관련 사실]")
        for f in facts:
            pred = f.get("predicate", "")
            obj = f.get("object", "")
            imp = f.get("importance", 5)
            mark = "⭐" if imp >= 8 else ""
            label = _PRED_LABELS.get(pred, pred)
            lines.append(f"- {mark}{label}: {obj}")
            shown += 1
            if shown >= 10:
                break
        if shown >= 10:
            break
    if not lines:
        return ""
    out = ["## 📚 알고 있는 사실"] + lines
    return "\n".join(_truncate_block(out, _scaled(BUDGET_FACTS)))


# ────────────────────────────────────────────────────
# Cross-channel raw peek (기존 API 유지 + entity 필터)
# ────────────────────────────────────────────────────

def get_cross_channel_memory(agent_id: str, exclude_channel: str, limit: int = 5,
                              focus_hint: str = "") -> str:
    """
    기존 API 보존 — runtime이 호출. 이제 _format_retrieved_memories의 얕은 래퍼.

    get_memory_context가 이미 retrieved 블록을 포함하므로, 이 함수는 호환을 위해
    남겨두고 빈 문자열 반환 (중복 방지). runtime에서 제거 가능하면 제거해도 됨.
    """
    # 중복 방지: get_memory_context가 이미 retrieved/disclosure 블록 생성
    return ""


# ────────────────────────────────────────────────────
# recall_memory / pin_memory — 도구에서 호출
# ────────────────────────────────────────────────────

def recall_memory(agent_id: str, query: str = "", entity: str = "",
                  time_range_days: Optional[int] = None, limit: int = 10) -> list[dict]:
    """에이전트가 직접 deep search.

    - entity: 엔티티 이름 (있으면 related_entities 매칭 우선)
    - query: 자연어 쿼리 — 키워드 LIKE 매칭
    - time_range_days: 최근 N일 내만
    - limit: 상위 N개

    Returns: [{id, level, channel, content, mem_type, importance, created_at}, ...]
    """
    rows = _store.search_memories(
        agent_id, entity=(entity or None), query=(query or None),
        time_range_days=time_range_days, limit=limit,
    )

    results = []
    for m in rows:
        results.append({
            "id": m["id"], "level": m["level"], "channel": m["channel"],
            "content": m["content"], "mem_type": m.get("mem_type"),
            "importance": m.get("importance"), "created_at": m.get("created_at"),
            "related_entities": m.get("related_entities", []),
            "is_pinned": bool(m.get("is_pinned")),
        })

    if results:
        _store.touch_memory_access([r["id"] for r in results])

    return results


def pin_memory(memory_id: int, pinned: bool = True, reason: str = "") -> dict:
    """메모리 고정/해제. reason은 로그에 남김."""
    row = _store.get_memory(memory_id)
    if not row:
        return {"ok": False, "error": "memory not found"}
    _store.set_pin(memory_id, pinned)
    action = "pin" if pinned else "unpin"
    msg = f"[Memory] {action} id={memory_id} agent={row['agent_id']}"
    if reason:
        msg += f" reason={reason[:80]}"
    print(msg)
    return {
        "ok": True, "id": memory_id, "pinned": bool(pinned),
        "agent_id": row["agent_id"],
        "preview": (row["content"] or "")[:80],
    }


# ────────────────────────────────────────────────────
# 통계
# ────────────────────────────────────────────────────

def get_memory_stats(agent_id: str, channel: str) -> dict:
    s = _store.get_memory_stats(agent_id, channel)
    total = s["total_messages"]
    covered = s["messages_summarized"]
    return {
        "total_messages": total,
        "raw_window": RAW_WINDOW,
        "l1_summaries": s["l1"],
        "l2_summaries": s["l2"],
        "l3_summaries": s["l3"],
        "pinned_memories": s["pinned"],
        "facts_active": s["facts_active"],
        "messages_summarized": covered,
        "memory_coverage": f"{covered + RAW_WINDOW}/{total}",
    }
