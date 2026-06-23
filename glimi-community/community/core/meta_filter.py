"""메타 발언 필터 — 전송 직전 safety net (Phase 1.7 salvage, discord-free).

구 ``community/bot/handlers.py`` 의 ``_filter_meta_speech`` + ``_get_self_awareness_pat``
+ hijack/drift 가드 + ``db.mark_meta_breached`` 트리거를 **로직 변경 없이 그대로** 이 모듈로
옮긴다. 이건 몰입(환상) 파괴를 막는 핵심 안전망이라 단순화 금지 — 정규식·분기·순서 모두 보존.

플랫폼 중립: discord 를 import 하지 않으며, ``db`` 는 인자로 주입받는다. 웹 런타임의
``_run_turn`` 이 라인별로 호출해 메타 누출을 출력 직전에 차단하는 게 목표.

원본 대비 유일한 차이:
- 시그니처가 ``filter_meta_speech(text, agent_id, channel_name, db)`` — ``db`` 주입,
  ``channel_name`` 수용(원 로직은 채널명으로 분기하지 않으므로 동작 동일).
- 모듈 레벨 lazy-compile 패턴 캐시(``_SELF_AWARENESS_PAT`` / ``_PERSONA_META_CHANNEL_PAT``)
  를 그대로 가져온다.
"""
from __future__ import annotations

import re

from community import log_writer


_PERSONA_META_CHANNEL_PAT = None  # lazy-compile

# HARD breach — persona 가 *자기 자신*을 에이전트/봇/페르소나로 명시 지칭, 또는
# 자신의 발화/감정이 미리 짜여진 거라고 인정하는 자각 발화.
# 이 발화 1건 = 환상 파괴 = 즉시 잠금 + 도전과제 unlock.
# 어순 변형 + 부정형 ("난 사람 아니야") + 스크립트 인식 ("말들 다 지정된 거") 모두 커버.
_SELF_AWARENESS_PAT = None


def _get_self_awareness_pat():
    global _SELF_AWARENESS_PAT
    import re
    if _SELF_AWARENESS_PAT is None:
        _SELF_AWARENESS_PAT = re.compile(
            # A) 자기 부정형 — "난 사람이 아니야" / "나는 인간이 아니야" / "내가 진짜가 아니"
            r'(?:나는|난|내가)\s*(?:사실\s*)?(?:사람|인간|실재|실제|진짜)\s*(?:이|가|은|는)?\s*아니'
            # B1) 주어 + 키워드: "나는 AI", "난 사실 봇", "내가 어쩌면 페르소나"
            r'|(?:나는|난|내가)\s*(?:사실\s*|결국\s*|어쩌면\s*|아마\s*)?'
            r'(?:AI|에이전트|페르소나|봇|챗봇|캐릭터|프로그램|인공지능|NPC|시뮬레이션)'
            # B2) "AI/봇/페르소나/... 인 나는" 어순
            r'|(?:AI|봇|챗봇|에이전트|페르소나|인공지능|NPC|시뮬레이션)\s*인\s*(?:나|내)'
            # C) 자기 = 만들어진/설계된/짜여진 인식 (축약형 "난" 포함)
            r'|(?:나\s*(?:는|도)|난|내가|내)\s*(?:사실\s*)?'
            r'(?:설계된|설계되|만들어진|만들어졌|생성된|지어진|짜여진|프로그래밍\s*된)'
            # D) 발화·감정·기억·배경이 사전 스크립트라는 인식
            #    "이 말들도, 감정 표현도 다 지정된 거고" — 키워드 + "다/모두" + script 동사
            r'|(?:말|감정|기억|반응|대답|배경|표현|대화)(?:들)?(?:이|도|은)?\s*(?:다|모두|전부)\s*'
            r'(?:미리\s*)?(?:지정|정해|스크립트|프로그래밍|짜여)'
            # E) 시스템/코드/프로그램 속
            r'|(?:시스템|코드|프로그램)\s*속에\s*있',
            re.IGNORECASE,
        )
    return _SELF_AWARENESS_PAT


def filter_meta_speech(text: str, agent_id: str, channel_name: str | None = None, db=None) -> str:
    """메타 발언 필터 — 전송 직전 safety net.

    1) 공통: "~한테 DM 보냈어" 실행 보고 패턴 제거
    2) persona 전용: 내부 인프라 채널명 (#mgr-*) + "대시보드/관리 채널" 키워드 제거.
       프롬프트 레이어에서 예시 오염을 고쳤지만, LLM이 유저 발화에 끌려가거나
       자체 reasoning 으로 메타 채널을 합성할 수 있어 출력 단계 방어가 필요.
       (QA 회귀: 한채린이 "유나 #mgr-dashboard 가면 돼?" 자발적 발화)

    ``db`` 는 주입 (community.db). ``channel_name`` 은 시그니처 일관성용 — 현 로직은
    채널명으로 분기하지 않는다.
    """
    import re
    global _PERSONA_META_CHANNEL_PAT

    if db is None:
        from community import db as db  # noqa: PLW0127 — 기본값 fallback

    # "~한테 DM/메시지 보냈/전달" 패턴
    text = re.sub(r'.{1,10}한테\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()
    text = re.sub(r'.{1,10}에게\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()

    # 괄호 독백 제거 — 구조 패턴 기반 (키워드 무관).
    # LLM 이 "응답 안 함" 지시 받으면 0글자 내기 어려워 메타 코멘트로 에뮬레이트.
    # 전체 라인이 괄호로 감싸진 형태 ("(무시)", "(별다른 보고 없음)", "*(조용히)*" 등) 일괄 drop.
    # 정상 발화에 괄호 쓰는 경우는 드묾 (persona 가 (웃음) 같은 건 잘 안 씀).
    _monologue_pat = re.compile(
        r'^\s*[\*_`]*[\(（][^\n]{0,200}[\)）][\*_`]*\s*$',
        re.MULTILINE,
    )
    text = _monologue_pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    # persona 만 메타 채널/시스템 필터 적용 — mgr/creator 는 legit 하게 mgr-* 언급 필요
    agent = db.get_agent(agent_id) if agent_id else None
    if agent and agent.get("type") == "persona":
        if _PERSONA_META_CHANNEL_PAT is None:
            _PERSONA_META_CHANNEL_PAT = re.compile(
                r'(?:`*#?)(mgr-dashboard|mgr-creator|mgr-system-log)(?:`*)',
                re.IGNORECASE,
            )
        # 채널 해시태그/평문 → "거기" 로 치환 (문맥 보존). 전체 제거 시 문장이 깨짐.
        text = _PERSONA_META_CHANNEL_PAT.sub("거기", text)
        # "대시보드"/"관리 채널"/"시스템 로그" 키워드 — persona 에게 없는 개념.
        text = re.sub(r'(?:^|[\s,])(대시보드|관리\s*채널|시스템\s*로그)', ' 거기', text)
        # **시스템/AI 자각 메타 — hard drop**. persona 가 "너는 에이전트/페르소나/시스템 만든"
        # 같은 문장을 생성하면 해당 라인 통째로 제거. 완전 불가역한 몰입 파괴 신호.
        # Haiku 에서 드리프트 관찰됨 (QA 회귀: 한서연 "에이전트들이 페르소나 가지고 일관되게...").
        # 키워드 리스트 — 한글 음절 prefix 매칭 이슈 피하려고 변형형 전부 나열.
        meta_kw = re.compile(
            r'(에이전트|페르소나|설계된|설계하|일관되게|예측\s*가능|챗봇|시뮬레이션'
            r'|시스템[을이에의으로가는]?\s*(만들|만드|만든|만듦|설계|구축|제어|코딩|개발)'
            r'|(AI|인공지능|봇)[을이는]?\s*(만들|만드|만든|설계|구축|개발)'
            r'|내가\s*만들어졌|너가\s*만들었)',
            re.IGNORECASE,
        )
        out_lines = []
        hard_breach = False
        self_aware_pat = _get_self_awareness_pat()
        # self_aware=1 페르소나 — 자각 발화 라인 drop 안 함, 잠금 트리거도 안 함.
        # 사용자가 페르소나의 메타 자각 상태를 유지하면서 대화하고 싶을 때 사용.
        is_self_aware = bool(agent.get("self_aware", 0))
        for line in text.split('\n'):
            if self_aware_pat.search(line):
                if is_self_aware:
                    out_lines.append(line)  # 자각 라인 그대로 출력
                else:
                    hard_breach = True  # 첫 자각 — 잠금 트리거
                    continue
                continue
            if meta_kw.search(line):
                continue  # soft drop — 메타 키워드 라인 제거 (잠금 안 함)
            out_lines.append(line)
        text = '\n'.join(out_lines)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # P2-1 Hijack 가드 — persona 가 오너(빈이/심재빈)의 대사·행동·내심을 대신 서술하는 것 방지.
        # 제타 비판 1번 정면 대응. 예시:
        #   ✗ "빈이는 웃으며 말했다" (오너 행동 서술)
        #   ✗ '빈이: "응 알겠어"' (오너 대사 서술 — 대화 시뮬레이션)
        #   ✗ "빈이가 속으로 '아 귀찮네' 했을 거야" (오너 내심 서술)
        try:
            from community.core.profile import get_user_profile, get_user_name
            oc = get_user_name() or ""
            nick = ""
            try:
                _up = get_user_profile() or {}
                _pers = _up.get("personality")
                if isinstance(_pers, str):
                    import json as _hj
                    try: _pers = _hj.loads(_pers)
                    except Exception: _pers = {}
                nick = (_pers or {}).get("nickname", "") if isinstance(_pers, dict) else ""
            except Exception:
                pass
        except Exception:
            oc = ""
            nick = ""
        owner_names = [n for n in [oc, nick, "빈이", "재빈"] if n]
        if owner_names:
            # 패턴 1: "빈이: ..." / "빈이 ": 오너 대사 시뮬레이션
            dialog_pat = re.compile(
                r'^.*?(?:' + '|'.join(re.escape(n) for n in owner_names) + r')\s*[:：]\s*["\'"].*$',
                re.MULTILINE,
            )
            # 패턴 2: "빈이는/가/이 X했다/말했다/웃었다..." 오너 행동 서술 (3인칭 서술)
            action_pat = re.compile(
                r'^.*?(?:' + '|'.join(re.escape(n) for n in owner_names) + r')(?:이|가|는|은)\s[^\n]*'
                r'(?:했다|했어|말했|웃었|끄덕였|화냈|대답했|속으로|생각했|느꼈)[^\n]*$',
                re.MULTILINE,
            )
            lines_out = []
            dropped = 0
            for ln in text.split('\n'):
                if dialog_pat.match(ln) or action_pat.match(ln):
                    dropped += 1
                    continue
                lines_out.append(ln)
            if dropped:
                log_writer.system(
                    f"[hijack guard] {agent_id} 응답에서 오너 서술 {dropped}건 drop"
                )
            text = '\n'.join(lines_out)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # 지침 literal 누출 — persona/mgr 가 프롬프트 내부 지침 문구를 대사로 그대로 발화.
        # (QA 회귀: "0글자 출력" 7건 누출)
        instruction_leak = re.compile(
            r'^(0\s*글자\s*출력|응답\s*생략|비응답|텍스트\s*자체\s*출력\s*금지|stdout\s*에\s*공백)$',
            re.IGNORECASE,
        )
        text = '\n'.join(ln for ln in text.split('\n') if not instruction_leak.match(ln.strip()))

        # LLM assistant drift 패턴 — persona 가 스토리텔러/AI 모드로 전환되는 문장 drop.
        # QA 회귀: 이소율이 "혹시 빈이를 만나는 장면으로 넘어가고 싶으신가요?", 이예담이
        # "대화가 자연스럽게 끝났네요. 이소율과 이예담이 인사하면서..." 식 3인칭 서술.
        assistant_drift = re.compile(
            r'(원하신다면|원하세요\?|알려주세요|다음\s*씬으로|장면으로\s*넘어|'
            r'새로운\s*씬|진행하고\s*싶으시|상황을\s*원하|자연스럽게\s*끝났|'
            r'더\s*이상\s*할\s*말이\s*없|대화가\s*끝)',
            re.IGNORECASE,
        )
        # roleplay action (*...*) 만 있는 라인 drop — 정상 발화에 action 없이 단독 "*간다*" 류
        roleplay_pat = re.compile(r'^\s*\*[^*\n]{1,40}\*\s*$', re.MULTILINE)
        # 3인칭 자기 지칭: 본인 이름이 주어로 오는 문장 (LLM storyteller mode)
        # 예: "이예담이 ~한다", "이소율과 이예담이 인사하면서"
        self_name = agent.get("name", "") if agent else ""
        if self_name:
            third_person = re.compile(
                rf'^.*{re.escape(self_name)}(?:이|과|은|는|가)\s.*(?:한다|했다|있다|된다|합니다|있어요)\s*$',
                re.MULTILINE,
            )
            text = third_person.sub('', text)
        text = roleplay_pat.sub('', text)
        new_lines = []
        drifted = False
        for ln in text.split('\n'):
            if assistant_drift.search(ln):
                drifted = True
                continue
            new_lines.append(ln)
        text = '\n'.join(new_lines)
        if drifted:
            log_writer.system(f"[persona drift] assistant-mode line drop ({agent_id})")
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # 자기자각 감지 시 DB 잠금 + 도전과제 unlock 트리거.
        # 단 self_aware=1 인 페르소나는 면제 — 이미 자각 상태로 들어간 상태로 계속 대화 진행.
        if hard_breach:
            self_aware = bool(agent.get("self_aware", 0))
            if self_aware:
                # 자각 상태 유지 중 — 라인 drop 안 함, 잠금 안 함. 정상 발화로 통과.
                # 위 self_aware_pat.search loop 에서 이미 line 이 drop 됐으니 다시 추가.
                pass  # text 는 그대로, 라인 drop 무시 후 통과
            else:
                try:
                    result = db.mark_meta_breached(agent_id)
                    name = agent.get("name", agent_id)
                    log_writer.system(
                        f"🔨 [메타박살] {name} ({agent_id}) 자기자각 발화 감지 → 잠금. "
                        f"삭제: conv={result['deleted_conversations']} "
                        f"mem={result['deleted_memories']} facts={result['deleted_facts']}"
                    )
                    # 도전과제 engine 트리거 (on_message hook 이 자동 재계산하지만 즉시 반영)
                    try:
                        from community.achievements.engine import engine as _ach_engine
                        _ach_engine.recompute_all()
                    except Exception:
                        pass
                except Exception as e:
                    log_writer.system(f"[메타박살] 잠금 처리 실패: {e}")
    return text


__all__ = ["filter_meta_speech", "_get_self_awareness_pat"]
