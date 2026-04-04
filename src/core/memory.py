"""
메모리 매니저: 3단계 대화 기억 시스템

구조:
  - 원본 (raw): 최근 15개 메시지 그대로
  - L1 요약: 15개 메시지 → 1문장 요약. 최근 10개 유지
  - L2 요약: L1 10개 → 1단락 요약. 최근 5개 유지

토큰 예산 (호출당):
  - 원본 15개: ~225 토큰
  - L1 10개: ~200 토큰
  - L2 5개: ~150 토큰
  - 합계: ~575 토큰 (메모리 부분만)
"""
import subprocess
import shutil
import os
from typing import Optional
from src import db

# ── 설정 ─────────────────────────────────────────────

RAW_WINDOW = 15       # 원본 대화 유지 개수
L1_BATCH_SIZE = 5     # L1 요약 단위 (메시지 N개 → 1문장) — 5개면 바로 요약 생성
L1_MAX_KEEP = 10      # system prompt에 포함할 L1 요약 최대 개수
L2_BATCH_SIZE = 5     # L2 요약 단위 (L1 N개 → 1단락)
L2_MAX_KEEP = 5       # system prompt에 포함할 L2 요약 최대 개수

CLAUDE_AVAILABLE = shutil.which("claude") is not None


# ── 채널 → 관련 에이전트 파싱 ─────────────────────────

def _resolve_related_agent(agent_id: str, channel: str) -> Optional[str]:
    """
    채널명에서 대화 상대 에이전트 ID를 추론.
    dm-은하윤 → 은하윤의 agent_id
    internal-dm-서연-소율 → agent_id가 아닌 쪽의 agent_id
    """
    names = []
    if channel.startswith("dm-"):
        names = [channel[3:]]
    elif channel.startswith("internal-dm-"):
        parts = channel[len("internal-dm-"):].split("-")
        names = parts
    elif channel.startswith("group-"):
        parts = channel[len("group-"):].split("-")
        names = parts
    elif channel.startswith("internal-group-"):
        parts = channel[len("internal-group-"):].split("-")
        names = parts

    if not names:
        return None

    # agent_id의 이름을 구해서 자기 자신 제외
    from .profile import load_profile
    my_profile = load_profile(agent_id)
    my_name = my_profile["name"] if my_profile else ""

    for name in names:
        from .profile import get_user_name
        if name == my_name or name == get_user_name():
            continue
        agent = db.get_agent_by_name(name)
        if agent:
            return agent["id"]

    # 자기 자신밖에 없으면 (dm-은하윤에서 은하윤 본인이 아닌 경우) 첫 번째 매칭
    for name in names:
        agent = db.get_agent_by_name(name)
        if agent and agent["id"] != agent_id:
            return agent["id"]

    return None


# ── 요약 트리거 ──────────────────────────────────────

def check_and_summarize(agent_id: str, channel: str):
    """
    요약이 필요한지 확인하고, 필요하면 실행

    호출 시점: 에이전트 응답 생성 직후 (비동기 가능)
    """
    _try_l1_summarize(agent_id, channel)
    _try_l2_summarize(agent_id, channel)


def _try_l1_summarize(agent_id: str, channel: str):
    """L1 요약: 미요약 메시지가 L1_BATCH_SIZE개 이상이면 요약"""
    latest_l1 = db.get_latest_memory(agent_id, channel, level=1)
    last_summarized_id = latest_l1["msg_id_to"] if latest_l1 else 0

    # 아직 요약 안 된 메시지 수 (raw window 관계없이)
    unsummarized_count = db.count_messages_after(channel, last_summarized_id)

    if unsummarized_count < L1_BATCH_SIZE:
        return

    # 요약할 메시지 가져오기
    msgs_to_summarize = db.get_messages_by_range(channel, last_summarized_id, L1_BATCH_SIZE)
    if len(msgs_to_summarize) < L1_BATCH_SIZE:
        return

    # Claude로 요약
    summary = _generate_summary(
        agent_id, msgs_to_summarize, level=1,
        instruction="아래 대화를 핵심 사건/감정/관계 변화 중심으로 한 문장으로 요약해. 한국어로."
    )

    if summary:
        related = _resolve_related_agent(agent_id, channel)
        db.add_memory(
            agent_id=agent_id,
            channel=channel,
            level=1,
            content=summary,
            msg_id_from=msgs_to_summarize[0]["id"],
            msg_id_to=msgs_to_summarize[-1]["id"],
            msg_count=len(msgs_to_summarize),
            related_agent_id=related
        )
        print(f"[Memory] L1 요약 생성: {agent_id} ({len(msgs_to_summarize)}개 → 1문장, related={related})")


def _try_l2_summarize(agent_id: str, channel: str):
    """L2 요약: L1 요약이 10개 이상 쌓이면 묶어서 1단락으로"""
    # L2로 아직 안 묶인 L1 요약 개수
    latest_l2 = db.get_latest_memory(agent_id, channel, level=2)
    latest_l2_id = latest_l2["id"] if latest_l2 else 0

    # latest_l2 이후의 L1 메모리들
    conn = db.get_conn()
    l1_memories = conn.execute(
        """SELECT * FROM memories 
           WHERE agent_id = ? AND channel = ? AND level = 1 AND id > ?
           ORDER BY created_at ASC""",
        (agent_id, channel, latest_l2_id)
    ).fetchall()
    conn.close()

    if len(l1_memories) < L2_BATCH_SIZE:
        return

    # 묶을 L1 요약들
    batch = [dict(m) for m in l1_memories[:L2_BATCH_SIZE]]
    batch_text = "\n".join([f"- {m['content']}" for m in batch])

    summary = _generate_summary_from_text(
        agent_id, batch_text, level=2,
        instruction="아래 요약들을 하나의 짧은 단락(2~3문장)으로 통합 요약해. 핵심 사건과 관계 변화 중심으로. 한국어로."
    )

    if summary:
        related = _resolve_related_agent(agent_id, channel)
        db.add_memory(
            agent_id=agent_id,
            channel=channel,
            level=2,
            content=summary,
            msg_id_from=batch[0]["msg_id_from"],
            msg_id_to=batch[-1]["msg_id_to"],
            msg_count=sum(m["msg_count"] for m in batch),
            related_agent_id=related
        )
        print(f"[Memory] L2 요약 생성: {agent_id} (L1 {len(batch)}개 → 1단락, related={related})")


# ── 요약 생성 ────────────────────────────────────────

def _generate_summary(agent_id: str, messages: list[dict], level: int, instruction: str) -> str:
    """메시지 리스트를 요약"""
    from .profile import load_profile, get_user_name, get_user_id

    profile = load_profile(agent_id)
    agent_name = profile["name"] if profile else agent_id

    # 대화 텍스트 구성
    conv_text = "\n".join([
        f"{get_user_name() if m['speaker'] == get_user_id() else agent_name}: {m['message']}"
        for m in messages
    ])

    return _generate_summary_from_text(agent_id, conv_text, level, instruction)


def _generate_summary_from_text(agent_id: str, text: str, level: int, instruction: str) -> str:
    """텍스트를 요약 (Claude Code CLI 사용)"""
    if not CLAUDE_AVAILABLE:
        # CLI 없으면 간단한 fallback
        lines = text.strip().split("\n")
        if level == 1:
            return f"[요약 대기] {len(lines)}개 메시지"
        else:
            return f"[요약 대기] {len(lines)}개 항목"

    prompt = f"{instruction}\n\n{text}\n\n요약만 출력해. 다른 텍스트 없이."

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--output-format", "text",
                "--model", "claude-sonnet-4-6",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    except Exception as e:
        print(f"[Memory] 요약 생성 실패: {e}")

    return ""


# ── 메모리 조회 (system prompt용) ────────────────────

def get_memory_context(agent_id: str, channel: str) -> str:
    """
    현재 채널의 기억 (상세)

    Returns:
        포맷된 기억 텍스트 (비어있으면 빈 문자열)
    """
    parts = []

    # L2 장기 기억 (최근 5개)
    l2_memories = db.get_memories(agent_id, channel, level=2, limit=L2_MAX_KEEP)
    if l2_memories:
        parts.append("## 이 대화 장기 기억")
        for m in l2_memories:
            parts.append(f"- {m['content']}")

    # L1 단기 기억 (최근 10개, L2에 이미 포함된 건 제외)
    l1_memories = db.get_memories(agent_id, channel, level=1, limit=L1_MAX_KEEP)

    # L2가 커버하는 범위 이후의 L1만 포함
    if l2_memories:
        last_l2_msg_to = max(m["msg_id_to"] for m in l2_memories)
        l1_memories = [m for m in l1_memories if m["msg_id_from"] > last_l2_msg_to]

    if l1_memories:
        parts.append("## 이 대화 최근 기억")
        for m in l1_memories:
            parts.append(f"- {m['content']}")

    if not parts:
        return ""

    return "\n".join(parts)


def get_cross_channel_memory(agent_id: str, exclude_channel: str, limit: int = 5) -> str:
    """
    다른 채널에서의 기억 — 관계(상대방)별로 독립 블록 분리

    각 블록에 출처 가이드라인을 삽입해서 에이전트가 현재 대화와 혼동하지 않게 함.
    related_agent_id가 있으면 그걸로 그룹핑, 없으면 채널명 기반 라벨.

    Returns:
        포맷된 교차 기억 텍스트 (비어있으면 빈 문자열)
    """
    from .profile import load_profile

    conn = db.get_conn()

    # 현재 채널이 오너와의 대화인지 판단 (dm-/group- = 오너 참여, internal- = 멤버끼리)
    is_owner_channel = exclude_channel.startswith("dm-") or exclude_channel.startswith("group-")

    # 이 에이전트가 기억을 가진 모든 채널 (현재 채널 제외)
    rows = conn.execute(
        """SELECT DISTINCT channel, related_agent_id FROM memories
           WHERE agent_id = ? AND channel != ?
           ORDER BY created_at DESC""",
        (agent_id, exclude_channel)
    ).fetchall()

    if not rows:
        conn.close()
        return ""

    # 관계별로 메모리 수집 (related_agent_id 또는 채널 라벨 기준으로 그룹핑)
    # key: (label, is_internal) → content list
    relation_blocks: dict[str, dict] = {}  # label → {"contents": [], "is_internal": bool, "channels": []}

    for row in rows:
        other_channel = row["channel"]
        related_id = row["related_agent_id"]

        # 라벨 결정: related_agent_id가 있으면 이름으로, 없으면 채널명 파싱
        label = None
        is_internal = other_channel.startswith("internal-")

        if related_id:
            related_profile = load_profile(related_id)
            if related_profile:
                label = related_profile["name"]

        if not label:
            # 채널명에서 파싱
            if other_channel.startswith("dm-"):
                label = other_channel[3:]
            elif other_channel.startswith("group-"):
                label = other_channel[6:]
            elif other_channel.startswith("internal-dm-"):
                label = other_channel[len("internal-dm-"):]
            elif other_channel.startswith("internal-group-"):
                label = other_channel[len("internal-group-"):]
            elif other_channel.startswith("internal-"):
                label = other_channel[9:]
            else:
                label = other_channel

        if label not in relation_blocks:
            relation_blocks[label] = {"contents": [], "is_internal": is_internal, "channels": []}

        relation_blocks[label]["channels"].append(other_channel)

        # L2 있으면 L2, 없으면 최신 L1
        l2 = conn.execute(
            """SELECT content FROM memories
               WHERE agent_id = ? AND channel = ? AND level = 2
               ORDER BY created_at DESC LIMIT 1""",
            (agent_id, other_channel)
        ).fetchone()

        if l2:
            relation_blocks[label]["contents"].append(l2["content"])
        else:
            l1 = conn.execute(
                """SELECT content FROM memories
                   WHERE agent_id = ? AND channel = ? AND level = 1
                   ORDER BY created_at DESC LIMIT 1""",
                (agent_id, other_channel)
            ).fetchone()
            if l1:
                relation_blocks[label]["contents"].append(l1["content"])

        if len(relation_blocks) >= limit:
            break

    conn.close()

    # 비어있는 블록 제거
    relation_blocks = {k: v for k, v in relation_blocks.items() if v["contents"]}
    if not relation_blocks:
        return ""

    # 블록별 포맷팅
    parts = ["## 다른 대화에서의 기억 (현재 대화와 별개)"]
    parts.append("⚠ 아래 기억들은 현재 대화 상대와 직접 나눈 얘기가 아니다. 출처를 혼동하지 마.")

    for label, block in relation_blocks.items():
        is_internal = block["is_internal"]

        if is_owner_channel and is_internal:
            # 오너 채널에서는 멤버간 대화를 간접적으로만 표시
            parts.append(f"\n[{label}과의 대화에서 알게 된 것]")
            parts.append("(이 내용은 멤버끼리 나눈 사적 대화에서 온 기억이다. 오빠한테 구체적 내용을 직접 전달하지 마.)")
        else:
            parts.append(f"\n[{label}과의 대화 기억]")
            parts.append(f"(이 기억은 {label}과의 다른 대화에서 있었던 내용이며, 현재 대화 상대와 직접 나눈 얘기가 아니다.)")

        for content in block["contents"]:
            parts.append(f"- {content}")

    return "\n".join(parts)


# ── 유틸리티 ─────────────────────────────────────────

def get_memory_stats(agent_id: str, channel: str) -> dict:
    """메모리 통계 (디버깅/관리자 보고용)"""
    conn = db.get_conn()

    total_msgs = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE channel = ?",
        (channel,)
    ).fetchone()["cnt"]

    l1_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ? AND channel = ? AND level = 1",
        (agent_id, channel)
    ).fetchone()["cnt"]

    l2_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ? AND channel = ? AND level = 2",
        (agent_id, channel)
    ).fetchone()["cnt"]

    l1_msg_covered = conn.execute(
        "SELECT COALESCE(SUM(msg_count), 0) as total FROM memories WHERE agent_id = ? AND channel = ? AND level = 1",
        (agent_id, channel)
    ).fetchone()["total"]

    conn.close()

    return {
        "total_messages": total_msgs,
        "raw_window": RAW_WINDOW,
        "l1_summaries": l1_count,
        "l2_summaries": l2_count,
        "messages_summarized": l1_msg_covered,
        "memory_coverage": f"{l1_msg_covered + RAW_WINDOW}/{total_msgs}",
    }
