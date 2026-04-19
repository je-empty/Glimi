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
from datetime import datetime
from typing import Optional

from src import db

# ── 설정 ─────────────────────────────────────────────

RAW_WINDOW = 15          # runtime이 직접 주입하는 원본 대화 개수
L1_BATCH_SIZE = 5        # L1 요약 단위 (메시지 N개 → 1 L1)
L1_MAX_KEEP = 10         # injection 시 current-channel L1 최대 개수
L2_BATCH_SIZE = 5        # L2 rollup 단위 (L1 N개 → 1 L2)
L2_MAX_KEEP = 5
L3_BATCH_SIZE = 5        # L3 rollup 단위 (L2 N개 → 1 L3)

STALE_L1_HOURS = 24
STALE_L2_DAYS = 3
VERY_STALE_DAYS = 7

MEMORY_TYPES = ("event", "fact", "emotion", "relationship")

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_AVAILABLE = shutil.which("claude") is not None

# Injection budgets (문자 길이 기준, 대략 4자 = 1 토큰)
BUDGET_PINNED = 400
BUDGET_RELATIONSHIP = 200
BUDGET_EPISODIC_CURRENT = 700
BUDGET_EPISODIC_RETRIEVED = 400
BUDGET_FACTS = 400

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
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _format_age(created_at: str) -> str:
    dt = _parse_iso(created_at)
    if not dt:
        return ""
    secs = (datetime.utcnow() - dt).total_seconds()
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
    return (datetime.utcnow() - dt).total_seconds() >= hours * 3600


def _days_since(created_at: str) -> float:
    dt = _parse_iso(created_at)
    if not dt:
        return 9999.0
    return max(0.0, (datetime.utcnow() - dt).total_seconds() / 86400.0)


def _owner_aliases() -> list[str]:
    """오너 이름 + 별명(nickname) 목록. 엔티티 정규화용 (심재빈/빈이/재빈 → 동일인)."""
    try:
        from .profile import get_user_name, get_user_profile
        aliases: list[str] = []
        name = (get_user_name() or "").strip()
        if name:
            aliases.append(name)
        try:
            prof = get_user_profile() or {}
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
        return aliases
    except Exception:
        return []


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
    """현재 채널의 대화 상대 (에이전트 이름)."""
    from .profile import load_profile
    my_profile = load_profile(agent_id)
    my_name = my_profile["name"] if my_profile else ""

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
    name = _resolve_partner_name(agent_id, channel)
    if not name:
        return None
    a = db.get_agent_by_name(name)
    return a["id"] if a else None


# ────────────────────────────────────────────────────
# Async worker (백그라운드 Haiku 추출)
# ────────────────────────────────────────────────────

_extract_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_worker_loop, daemon=True, name="memory-extractor")
        t.start()


def _worker_loop():
    while True:
        try:
            job = _extract_queue.get()
        except Exception:
            continue
        if job is None:
            break
        try:
            _run_extraction(*job)
        except Exception as e:
            print(f"[Memory] extraction error for {job}: {e}")


def enqueue_extraction(agent_id: str, channel: str):
    """메시지 저장 직후 호출 — 비동기로 L1/L2/L3 처리."""
    _ensure_worker()
    _extract_queue.put((agent_id, channel))


def check_and_summarize(agent_id: str, channel: str):
    """기존 API 유지 — 이제 비동기 enqueue로만 동작."""
    enqueue_extraction(agent_id, channel)


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

def _call_claude(prompt: str, model: str = EXTRACTION_MODEL, timeout: int = 30) -> str:
    if not CLAUDE_AVAILABLE:
        return ""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt,
             "--output-format", "text", "--model", model],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"[Memory] Claude 호출 실패: {e}")
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
    from .profile import load_profile, get_user_name, get_user_id

    profile = load_profile(agent_id)
    agent_name = profile["name"] if profile else agent_id
    user_name = get_user_name() or "오너"
    user_id = get_user_id()

    conv_text = "\n".join(
        f"{user_name if m['speaker'] == user_id else (db.get_agent(m['speaker'])['name'] if m['speaker'].startswith('agent-') and db.get_agent(m['speaker']) else m['speaker'])}: {m['message']}"
        for m in msgs
    )

    prompt = (
        f"너는 {agent_name}의 기억 추출기야. 아래 대화 {len(msgs)}건에서 {agent_name} 관점의 기억을 추출해.\n\n"
        "하나의 JSON으로 다음 필드를 추출:\n"
        "- summary: 글머리표 2-5개. 구체적 명사·결정·미해결 사항 그대로. '\\n- '로 구분.\n"
        "- type: event|fact|emotion|relationship 중 지배적 것 하나\n"
        "- entities: 언급된 사람 이름 배열 (자신·오너 제외, 다른 사람만)\n"
        "- importance: 1-10 (인사/잡담=2-3, 일상공유=4-5, 중요결정/감정변화=7+)\n"
        "- facts: 새로 알게 된 개인정보/선호 배열. 각 항목 {subject, predicate, object, importance}\n"
        "- relationships: 관계 변화 배열. 각 항목 {other, type(intimacy|dynamics|speech_style), from, to, reason}\n\n"
        "예시:\n"
        '{"summary":"- 지우가 떡볶이 제안\\n- 주말 약속 보류","type":"event","entities":["지우"],"importance":5,'
        '"facts":[{"subject":"지우","predicate":"좋아하는음식","object":"떡볶이","importance":4}],'
        '"relationships":[]}\n\n'
        "규칙:\n"
        "- 잡담·인사만 있으면 summary는 짧게, importance 낮게.\n"
        "- facts는 확실한 것만 (추측 금지). 없으면 빈 배열.\n"
        "- relationships는 명확한 관계 변화만. 없으면 빈 배열.\n"
        "- JSON만 출력. 다른 텍스트 없이.\n\n"
        f"대화:\n{conv_text}"
    )

    raw = _call_claude(prompt, model=EXTRACTION_MODEL, timeout=30)
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

    return {
        "summary": summary,
        "type": mem_type,
        "entities": entities,
        "importance": importance,
        "facts": facts,
        "relationships": relationships,
    }


def _try_l1_extract(agent_id: str, channel: str):
    """L1: 미추출 메시지 5개 쌓이면 단일 패스로 추출."""
    latest_l1 = db.get_latest_memory(agent_id, channel, level=1)
    last_id = latest_l1["msg_id_to"] if latest_l1 else 0
    unsummarized = db.count_messages_after(channel, last_id)
    if unsummarized < L1_BATCH_SIZE:
        return

    msgs = db.get_messages_by_range(channel, last_id, L1_BATCH_SIZE)
    if len(msgs) < L1_BATCH_SIZE:
        return

    extracted = _single_pass_extract(agent_id, channel, msgs)
    if not extracted:
        return

    from .profile import load_profile
    profile = load_profile(agent_id)
    agent_name = profile["name"] if profile else agent_id
    knows = _channel_knows(channel, agent_name)

    # related_agent_id: 주 파트너 (역호환용)
    partner_id = _resolve_partner_agent_id(agent_id, channel)

    mem_id = db.add_memory(
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

    # Facts → agent_facts
    for f in extracted.get("facts", []):
        if not isinstance(f, dict):
            continue
        subject = _normalize_entity(str(f.get("subject") or "").strip())
        predicate = str(f.get("predicate") or "").strip()
        obj = str(f.get("object") or "").strip()
        if not (subject and predicate and obj):
            continue
        try:
            f_imp = max(1, min(10, int(f.get("importance", 5))))
        except Exception:
            f_imp = 5
        try:
            db.add_fact(
                agent_id=agent_id,
                subject=subject, predicate=predicate, object_value=obj,
                source_channel=channel, source_memory_id=mem_id,
                confidence=1.0, importance=f_imp,
            )
        except Exception as e:
            print(f"[Memory] fact 저장 실패: {e}")

    # Relationship delta → relationship_history
    for r in extracted.get("relationships", []):
        if not isinstance(r, dict):
            continue
        other = str(r.get("other") or "").strip()
        if not other:
            continue
        other_ag = db.get_agent_by_name(other)
        other_id = other_ag["id"] if other_ag else other
        dtype = str(r.get("type") or "dynamics").strip()
        if dtype not in ("intimacy", "dynamics", "speech_style"):
            dtype = "dynamics"
        try:
            db.add_relationship_delta(
                agent_a=agent_id, agent_b=other_id,
                delta_type=dtype,
                from_state=str(r.get("from") or "") or None,
                to_state=str(r.get("to") or "") or None,
                reason=str(r.get("reason") or "") or None,
                source_channel=channel, source_memory_id=mem_id,
            )
        except Exception as e:
            print(f"[Memory] relationship delta 저장 실패: {e}")

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
    return _call_claude(prompt, model=EXTRACTION_MODEL, timeout=30)


def _try_l2_rollup(agent_id: str, channel: str):
    """L1 5개 → L2 1개."""
    conn = db.get_conn()
    latest_l2 = conn.execute(
        "SELECT MAX(msg_id_to) as last_id FROM memories "
        "WHERE agent_id=? AND channel=? AND level=2",
        (agent_id, channel)
    ).fetchone()
    last_l2_msg = latest_l2["last_id"] if latest_l2 and latest_l2["last_id"] else 0

    rows = conn.execute(
        """SELECT * FROM memories
           WHERE agent_id=? AND channel=? AND level=1 AND msg_id_to > ?
           ORDER BY msg_id_to ASC""",
        (agent_id, channel, last_l2_msg)
    ).fetchall()
    conn.close()

    if len(rows) < L2_BATCH_SIZE:
        return
    batch = [dict(r) for r in rows[:L2_BATCH_SIZE]]
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

    db.add_memory(
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
    conn = db.get_conn()
    latest_l3 = conn.execute(
        "SELECT MAX(id) as last_id FROM memories "
        "WHERE agent_id=? AND channel=? AND level=3",
        (agent_id, channel)
    ).fetchone()
    last_l3_mem_id = latest_l3["last_id"] if latest_l3 and latest_l3["last_id"] else 0

    rows = conn.execute(
        """SELECT * FROM memories
           WHERE agent_id=? AND channel=? AND level=2 AND id > ?
           ORDER BY id ASC""",
        (agent_id, channel, last_l3_mem_id)
    ).fetchall()
    conn.close()

    if len(rows) < L3_BATCH_SIZE:
        return
    batch = [dict(r) for r in rows[:L3_BATCH_SIZE]]
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

    db.add_memory(
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
    for a in db.list_agents():
        name = a.get("name") or ""
        if name and name in text:
            out.add(name)
    try:
        from .profile import get_user_name
        un = get_user_name()
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

def get_memory_context(agent_id: str, channel: str, user_message: str = "") -> str:
    """
    현재 채널 기억 + pinned + 관계 스냅샷 — runtime이 system-reminder에 주입.

    user_message: 현재 턴 유저 입력 (없으면 빈 문자열). 엔티티 매칭에 사용.
    """
    parts: list[str] = []

    try:
        _touch_ids: list[int] = []

        # ─ Pinned memories (항상) ─
        pinned = db.get_pinned_memories(agent_id, limit=10)
        if pinned:
            block = [_format_memory_line(m, STALE_L2_DAYS * 24) for m in pinned]
            block = _truncate_block(block, BUDGET_PINNED)
            if block:
                parts.append("## 📌 고정 기억")
                parts.extend(block)
                _touch_ids.extend([m["id"] for m in pinned[:len(block)]])

        # ─ Relationship state (현재 채널 파트너) ─
        partner_name = _resolve_partner_name(agent_id, channel)
        partner_id = _resolve_partner_agent_id(agent_id, channel)
        if partner_id:
            rel = db.get_relationship(agent_id, partner_id) or db.get_relationship(partner_id, agent_id)
            if rel:
                lines = [f"## 💞 {partner_name}과의 관계"]
                itm = rel.get("intimacy_score")
                dyn = rel.get("dynamics")
                rtype = rel.get("type")
                bits = []
                if rtype:
                    bits.append(f"{rtype}")
                if itm is not None:
                    bits.append(f"친밀도 {itm}/100")
                if dyn:
                    bits.append(dyn)
                if bits:
                    lines.append("- " + ", ".join(bits))
                # 최근 관계 변곡점 1-2개
                hist = db.get_relationship_history(agent_id, partner_id, limit=2)
                for h in hist:
                    reason = h.get("reason") or ""
                    if reason:
                        lines.append(f"- [변화] {h.get('delta_type')}: {h.get('from_state') or '?'}→{h.get('to_state') or '?'} ({reason[:40]})")
                parts.append("\n".join(_truncate_block(lines, BUDGET_RELATIONSHIP)))

        # ─ Episodic — current channel (L3/L2/L1) ─
        current_block = _format_current_channel_memories(agent_id, channel)
        if current_block:
            parts.append(current_block)

        # ─ Episodic — retrieved (다른 채널에서 partner/mentioned 에이전트 관련) ─
        query_entities = _mentioned_entities(user_message)
        if partner_name:
            query_entities.add(partner_name)
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
                db.touch_memory_access(_touch_ids)
            except Exception:
                pass

    except Exception as e:
        print(f"[Memory] get_memory_context 오류: {e}")

    if not parts:
        return ""
    return "\n\n".join(parts)


def _format_current_channel_memories(agent_id: str, channel: str) -> str:
    """현재 채널 L3 + L2 + L1 조합."""
    out: list[str] = []
    any_very_stale = False

    # L3 (월 단위, 있으면 최대 2개)
    l3 = db.get_memories(agent_id, channel, level=3, limit=2)
    if l3:
        out.append("## 🗂 장기 (월단위)")
        for m in l3:
            out.append(_format_memory_line(m, VERY_STALE_DAYS * 24))

    # L2 (최근 N개)
    l2 = db.get_memories(agent_id, channel, level=2, limit=L2_MAX_KEEP)
    if l2:
        out.append("## 장기 기억")
        for m in l2:
            out.append(_format_memory_line(m, STALE_L2_DAYS * 24))
            if _is_stale(m.get("created_at", ""), VERY_STALE_DAYS * 24):
                any_very_stale = True

    # L1 — L2 커버 밖의 것만
    l1 = db.get_memories(agent_id, channel, level=1, limit=L1_MAX_KEEP)
    if l2:
        last_l2_covered = max((m["msg_id_to"] or 0) for m in l2)
        l1 = [m for m in l1 if (m.get("msg_id_from") or 0) > last_l2_covered]
    if l1:
        out.append("## 최근 기억")
        for m in l1:
            out.append(_format_memory_line(m, STALE_L1_HOURS))

    if not out:
        return ""

    truncated = _truncate_block(out, BUDGET_EPISODIC_CURRENT)
    if any_very_stale:
        truncated.insert(0, "⚠ 일부 장기 기억이 1주일 이상 지났어. 현재 대화에서 사실 확인 후 업데이트해.")
    return "\n".join(truncated)


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

    conn = db.get_conn()
    rows = conn.execute(
        """SELECT * FROM memories
           WHERE agent_id=? AND channel != ? AND level IN (1,2,3)
           ORDER BY created_at DESC LIMIT 200""",
        (agent_id, exclude_channel)
    ).fetchall()
    conn.close()

    # Hydrate (parse JSON cols)
    candidates: list[dict] = []
    for r in rows:
        m = dict(r)
        for col in ("related_entities", "knows"):
            v = m.get(col)
            if isinstance(v, str) and v:
                try:
                    m[col] = _json.loads(v)
                except Exception:
                    m[col] = []
            elif not v:
                m[col] = []
        # entity 매칭 필터 (적어도 1개 겹쳐야 후보)
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
    from .profile import load_profile
    groups: dict[str, list[dict]] = {}
    for m in top:
        ch = m.get("channel") or ""
        label = None
        rid = m.get("related_agent_id")
        if rid:
            p = load_profile(rid)
            if p:
                label = p["name"]
        if not label:
            for prefix in ("internal-dm-", "internal-group-", "dm-", "group-"):
                if ch.startswith(prefix):
                    label = ch[len(prefix):]
                    break
            label = label or ch
        groups.setdefault(label, []).append(m)

    lines = ["## 🧠 다른 대화에서 관련 기억 (출처 혼동 주의)"]
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

    truncated = _truncate_block(lines, BUDGET_EPISODIC_RETRIEVED)
    return "\n".join(truncated), touched


def _format_facts_block(agent_id: str, query_entities: set[str]) -> str:
    """파트너/언급 엔티티에 대한 facts."""
    if not query_entities:
        return ""
    lines: list[str] = []
    shown = 0
    for ent in query_entities:
        facts = db.get_facts(agent_id, subject=ent, limit=5)
        if not facts:
            continue
        lines.append(f"[{ent} 관련 사실]")
        for f in facts:
            pred = f.get("predicate", "")
            obj = f.get("object", "")
            imp = f.get("importance", 5)
            mark = "⭐" if imp >= 8 else ""
            lines.append(f"- {mark}{pred}: {obj}")
            shown += 1
            if shown >= 10:
                break
        if shown >= 10:
            break
    if not lines:
        return ""
    out = ["## 📚 알고 있는 사실"] + lines
    return "\n".join(_truncate_block(out, BUDGET_FACTS))


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
    conn = db.get_conn()
    sql = "SELECT * FROM memories WHERE agent_id=?"
    args: list = [agent_id]
    if entity:
        sql += " AND related_entities LIKE ?"
        args.append(f'%"{entity}"%')
    if query:
        sql += " AND (content LIKE ? OR mem_type LIKE ?)"
        args.append(f"%{query}%")
        args.append(f"%{query}%")
    if time_range_days:
        sql += f" AND created_at >= datetime('now', ?)"
        args.append(f"-{int(time_range_days)} days")
    sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
    args.append(max(1, min(50, int(limit))))

    rows = conn.execute(sql, args).fetchall()
    conn.close()

    results = []
    for r in rows:
        m = dict(r)
        for col in ("related_entities", "knows"):
            v = m.get(col)
            if isinstance(v, str) and v:
                try:
                    m[col] = _json.loads(v)
                except Exception:
                    m[col] = []
        results.append({
            "id": m["id"], "level": m["level"], "channel": m["channel"],
            "content": m["content"], "mem_type": m.get("mem_type"),
            "importance": m.get("importance"), "created_at": m.get("created_at"),
            "related_entities": m.get("related_entities", []),
            "is_pinned": bool(m.get("is_pinned")),
        })

    if results:
        db.touch_memory_access([r["id"] for r in results])

    return results


def pin_memory(memory_id: int, pinned: bool = True, reason: str = "") -> dict:
    """메모리 고정/해제. reason은 로그에 남김."""
    conn = db.get_conn()
    row = conn.execute("SELECT id, agent_id, content, is_pinned FROM memories WHERE id=?",
                       (memory_id,)).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "memory not found"}
    db.set_pin(memory_id, pinned)
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
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE channel=?",
                         (channel,)).fetchone()["c"]

    def _cnt(level):
        return conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE agent_id=? AND channel=? AND level=?",
            (agent_id, channel, level)
        ).fetchone()["c"]

    l1 = _cnt(1)
    l2 = _cnt(2)
    l3 = _cnt(3)
    pinned = conn.execute(
        "SELECT COUNT(*) as c FROM memories WHERE agent_id=? AND is_pinned=1",
        (agent_id,)
    ).fetchone()["c"]
    facts = conn.execute(
        "SELECT COUNT(*) as c FROM agent_facts WHERE agent_id=? AND valid_to IS NULL",
        (agent_id,)
    ).fetchone()["c"]
    covered = conn.execute(
        "SELECT COALESCE(SUM(msg_count),0) as t FROM memories "
        "WHERE agent_id=? AND channel=? AND level=1",
        (agent_id, channel)
    ).fetchone()["t"]
    conn.close()

    return {
        "total_messages": total,
        "raw_window": RAW_WINDOW,
        "l1_summaries": l1,
        "l2_summaries": l2,
        "l3_summaries": l3,
        "pinned_memories": pinned,
        "facts_active": facts,
        "messages_summarized": covered,
        "memory_coverage": f"{covered + RAW_WINDOW}/{total}",
    }
