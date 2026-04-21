"""
대화 엔진: 에이전트 간 자동 대화 관리

- 에이전트끼리 자발적으로 대화
- 턴 제한으로 무한 대화 방지
- 유나가 위에서 모니터링
"""
import asyncio
import random
import re
from typing import Optional, Callable, Awaitable
from src import db
from .runtime import runtime

# ── 설정 ─────────────────────────────────────────────

DEFAULT_MAX_TURNS = 8           # 기본 최대 턴 수
MIN_TURNS = 3                   # 최소 보장 턴
TURN_DELAY_MIN = 2.0            # 턴 간 최소 딜레이 (초)
TURN_DELAY_MAX = 5.0            # 턴 간 최대 딜레이 (초)

# 대화 종료 신호 패턴 (자연스러운 마무리 감지)
CLOSURE_PATTERNS = [
    r"(그래|응|ㅇㅇ|알겠|알았|그럼|잘자|바이|또\s*봐|끊을게|나중에|가봐야|바쁘다|가야)",
    r"(ㅋㅋ+\s*$)",  # ㅋㅋ로만 끝나는 메시지
    r"^(\.{2,}|…)$",  # ..., … 만 있는 메시지
]
_closure_re = [re.compile(p) for p in CLOSURE_PATTERNS]

# 강한 종료 신호 — 발견 시 progress 무관 즉시 종료 (drift 방지).
# "곧 봐", "가버렸", "대화 끝", "마무리됐" 같은 closing 후 persona 가 storyteller drift 빠지는 주 경로 차단.
STRONG_CLOSURE_PATTERNS = [
    r"(곧\s*봐|이따\s*봐|또\s*봐|먼저\s*가|그럼\s*이만|바이바이|굿밤|잘자)",
    r"(손\s*흔들어|갈게\b|갈게요\b)",
]
_strong_closure_re = [re.compile(p) for p in STRONG_CLOSURE_PATTERNS]


# ── 활성 대화 상태 추적 ──────────────────────────────

class ConversationState:
    def __init__(self, channel_name: str, participants: list[str], max_turns: int = DEFAULT_MAX_TURNS):
        self.channel_name = channel_name
        self.participants = participants        # [agent_id, agent_id, ...]
        self.max_turns = max_turns
        self.turn_count = 0
        self.active = True
        self.messages: list[dict] = []          # {"speaker": id, "message": text}

    def next_speaker(self) -> Optional[str]:
        """다음 발화자 결정"""
        if not self.active or self.turn_count >= self.max_turns:
            return None
        # 순서대로 돌아가면서 (2인이면 교대)
        return self.participants[self.turn_count % len(self.participants)]

    def record_turn(self, speaker_id: str, messages: list[str]):
        self.turn_count += 1
        db.increment_channel_turn(self.channel_name)
        for msg in messages:
            self.messages.append({"speaker": speaker_id, "message": msg})

    def should_end(self, last_messages: list[str]) -> bool:
        """대화가 자연스럽게 끝나야 하는지 판단"""
        if self.turn_count >= self.max_turns:
            return True
        if self.turn_count < MIN_TURNS:
            return False

        # 맥락 반복 감지 — 최근 4턴의 메시지들이 비슷한 단어 반복하면 종료
        if len(self.messages) >= 4:
            recent_words = set()
            old_words = set()
            for m in self.messages[-2:]:
                recent_words.update(w for w in m["message"].split() if len(w) >= 2)
            for m in self.messages[-4:-2]:
                old_words.update(w for w in m["message"].split() if len(w) >= 2)
            if recent_words and old_words:
                overlap = len(recent_words & old_words) / max(len(recent_words), 1)
                if overlap > 0.5:
                    return True

        # 강한 종료 신호 — progress 무관 즉시 종료 (drift 방지)
        for msg in last_messages:
            for pattern in _strong_closure_re:
                if pattern.search(msg):
                    return True

        # 마지막 메시지에서 종료 신호 감지 (확률적)
        for msg in last_messages:
            for pattern in _closure_re:
                if pattern.search(msg):
                    progress = self.turn_count / self.max_turns
                    if random.random() < progress:
                        return True
        return False


# 활성 대화 저장소
_active_conversations: dict[str, ConversationState] = {}


def get_active_conversation(channel_name: str) -> Optional[ConversationState]:
    return _active_conversations.get(channel_name)


def list_active_conversations() -> list[dict]:
    """유나 보고용: 활성 대화 목록"""
    result = []
    for name, state in _active_conversations.items():
        if state.active:
            names = [runtime.get_agent_name(aid) for aid in state.participants]
            result.append({
                "channel": name,
                "participants": names,
                "turns": state.turn_count,
                "max_turns": state.max_turns,
            })
    return result


# ── 대화 실행 ────────────────────────────────────────

async def start_conversation(
    channel_name: str,
    participants: list[str],
    send_fn: Callable[[str, str], Awaitable[None]],
    context: str = "",
    max_turns: int = DEFAULT_MAX_TURNS,
) -> ConversationState:
    from src.community import is_maintenance_mode
    if is_maintenance_mode():
        from src import log_writer
        log_writer.system(f"[maintenance] start_conversation skip #{channel_name}")
        # 최소 state 리턴 (호출자 기대 타입 유지)
        return ConversationState(channel_name, participants, max_turns=max_turns)
    """
    에이전트 간 자동 대화 시작

    Args:
        channel_name: 디스코드 채널명
        participants: 참여 에이전트 ID 리스트
        send_fn: async 함수(agent_id, message) — 디스코드에 메시지 전송
        context: 대화 시작 상황 설명
        max_turns: 최대 턴 수
    """
    # 에이전트 활성화
    for aid in participants:
        runtime.activate_agent(aid)

    state = ConversationState(channel_name, participants, max_turns)
    _active_conversations[channel_name] = state

    # DB 채널 상태 running으로
    db.set_channel_status(channel_name, "running", max_turns)

    names = [runtime.get_agent_name(aid) for aid in participants]
    print(f"[대화엔진] 시작: {' ↔ '.join(names)} (채널: {channel_name}, 최대 {max_turns}턴)")

    # 방 상황 설명 구성
    if len(participants) == 2:
        room_desc = f"{names[0]}와(과) {names[1]}의 1:1 대화방"
    else:
        room_desc = f"{', '.join(names)} 단톡방"

    # 대화 시작 시점의 각 에이전트 DM 최신 메시지 ID 기록
    _dm_snapshots = {}
    for aid in participants:
        agent_name = runtime.get_agent_name(aid)
        dm_ch = f"dm-{agent_name}"
        latest = db.get_recent_messages(dm_ch, limit=1)
        _dm_snapshots[aid] = latest[0]["id"] if latest else 0

    # 대화 루프
    while state.active:
        speaker_id = state.next_speaker()
        if not speaker_id:
            break

        # 다른 참여자
        other_ids = [aid for aid in participants if aid != speaker_id]
        others = [runtime.get_agent_name(aid) for aid in other_ids]
        listener_str = ", ".join(others)

        # 대화 상황 — 첫 턴이면 context + 방 설명, 이후는 이어가기
        if state.turn_count == 0:
            situation = f"[{room_desc}] "
            if context:
                situation += context
            else:
                situation += f"{listener_str}한테 자연스럽게 말 걸어."
        else:
            situation = f"{listener_str}과(와)의 대화를 자연스럽게 이어가."

        # ── 실시간 DM 체크: 대화 중에 다른 채널에서 새 메시지 왔는지 ──
        speaker_name = runtime.get_agent_name(speaker_id)
        dm_ch = f"dm-{speaker_name}"
        last_known = _dm_snapshots.get(speaker_id, 0)
        new_dms = db.get_messages_by_range(dm_ch, last_known, limit=5)

        if new_dms:
            dm_preview = []
            for m in new_dms:
                from src.core.profile import get_user_name, get_user_id
                s = get_user_name() if m["speaker"] == get_user_id() else runtime.get_agent_name(m["speaker"])
                dm_preview.append(f"{s}: {m['message'][:50]}")
            situation += f"\n\n[방금 {get_user_name()}한테 DM 왔어]\n" + "\n".join(dm_preview)
            # 스냅샷 업데이트
            _dm_snapshots[speaker_id] = new_dms[-1]["id"]

        # 자연스러운 딜레이
        delay = random.uniform(TURN_DELAY_MIN, TURN_DELAY_MAX)
        await asyncio.sleep(delay)

        try:
            # 에이전트간 대화 전용 함수 사용 (오너으로 감싸지 않음)
            listener_id = other_ids[0] if len(other_ids) == 1 else other_ids[state.turn_count % len(other_ids)]
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda sid=speaker_id, lid=listener_id, ch=channel_name, ctx=situation:
                    runtime.generate_agent_to_agent(sid, lid, ch, context=ctx)
            )

            # 디스코드에 전송 (legacy 태그 + <tools> 블록 strip)
            import re
            TAG_RE = re.compile(r'\[(?:CMD|QUERY|ACTION):((?:[^\[\]]|\[[^\]]*\])*)\]')
            TOOLS_RE = re.compile(r'<tools>.*?</tools>', re.IGNORECASE | re.DOTALL)
            for i, msg in enumerate(responses):
                if i > 0:
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                # 모든 태그 제거 후 순수 텍스트만 전송 (legacy + <tools> 블록)
                clean = TAG_RE.sub('', msg)
                clean = TOOLS_RE.sub('', clean).strip()
                # 파편이 남은 케이스 (라인 단위로 메시지 분리된 경우 — 위 block DOTALL
                # 정규식으로 안 걸리는 one-line 잔재)
                if clean.lower() in ("<tools>", "</tools>") or clean.startswith("<call "):
                    continue
                if clean:
                    await send_fn(speaker_id, clean)

            # <tools> 블록에서 파싱된 tool_calls 실행 — runtime에 stash돼 있음
            # (이전에는 internal-dm 경로에서 이 실행이 빠져서 finish_tutorial 호출
            #  시도해도 텍스트만 흘러나가고 실제론 아무 일도 안 일어남)
            from src.bot.mgr_system import parse_and_execute_actions
            from src.bot.core import get_target_guild as _gt
            import discord as _disc
            guild = _gt()
            if guild:
                ch_obj = _disc.utils.get(guild.text_channels, name=channel_name)
                if ch_obj:
                    try:
                        await parse_and_execute_actions(
                            ch_obj, [], guild, caller_agent_id=speaker_id
                        )
                    except Exception as e:
                        print(f"[대화엔진] tool 실행 오류: {e}")

            # 턴 기록
            state.record_turn(speaker_id, responses)

            # 종료 체크
            if state.should_end(responses):
                state.active = False
                print(f"[대화엔진] 자연 종료: {channel_name} ({state.turn_count}턴)")

        except Exception as e:
            print(f"[대화엔진] 오류: {e}")
            state.active = False
            break

    # 대화 완료
    state.active = False
    db.set_channel_status(channel_name, "idle")
    print(f"[대화엔진] 완료: {channel_name} (총 {state.turn_count}턴)")
    return state


def stop_conversation(channel_name: str) -> bool:
    """유나가 대화 강제 중단"""
    state = _active_conversations.get(channel_name)
    if state and state.active:
        state.active = False
        print(f"[대화엔진] 강제 중단: {channel_name}")
        return True
    return False


# ── 톡방 요청 감지 ───────────────────────────────────

# 에이전트 응답에서 톡방 생성 요청 패턴 감지
ROOM_REQUEST_PATTERNS = [
    r"(단톡|톡방|그룹|채팅방).*(만들|파|열)",
    r"(같이|다같이|셋이서|넷이서).*(얘기|대화|톡)",
    r"(불러|초대).*(톡방|단톡|채팅)",
]
_room_request_re = [re.compile(p) for p in ROOM_REQUEST_PATTERNS]


def detect_room_request(message: str) -> bool:
    """에이전트 메시지에서 톡방 생성 의도 감지"""
    for pattern in _room_request_re:
        if pattern.search(message):
            return True
    return False
