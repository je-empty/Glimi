"""Demo 도전과제·이벤트·튜토리얼 mock data 보강.

- achievements.progress_data 채워서 "누구로 인해/얼마나" 정보 표시
- events 에 튜토리얼 시작/완료, 페르소나 추가, 첫 internal-dm 등 라이프사이클 이벤트 추가
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["GLIMI_COMMUNITY"] = "demo"
from src.community import set_community
set_community("demo")
from src import db


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.astimezone(timezone.utc).isoformat()


# 데모 타임라인 — 30일 전 가입, 점진적 도전과제 달성
NOW = datetime.now(timezone.utc)
T_TUTORIAL_START = NOW - timedelta(days=30, hours=2)
T_TUTORIAL_DONE  = NOW - timedelta(days=30, hours=1)


# ── 도전과제 progress_data 보강 ──
ACHIEVEMENTS = [
    # key, state, progress_data, unlocked_offset_days, completed_offset_days
    ("tutorial_done", "done",
        {"phase_count": 4, "duration_minutes": 62},
        30, 30),
    ("first_friend_chat", "done",
        {"friend": "박지우", "channel": "dm-박지우", "msgs": 8},
        29, 29),
    ("three_friends", "done",
        {"talked_to": ["박지우", "김민서", "정예린"]},
        27, 26),
    ("group_chat", "done",
        {"channel": "group-친구들", "msgs": 14, "members": ["박지우", "김민서", "정예린"]},
        24, 24),
    ("peek_internal", "done",
        {"channels": ["internal-dm-박지우-정예린"], "first_overheard_at": "박지우↔정예린 대화"},
        22, 22),
    ("agent_auto_chat", "done",
        {"channel": "group-친구들", "trigger": "오너 부재 4시간 → orchestrator group revive"},
        20, 20),
    ("late_night", "done",
        {"channel": "dm-박지우", "at_hour": 2, "msgs": 6},
        18, 18),
    ("chatter", "done",
        {"count": 1200},
        15, 15),
    ("secret_keeper", "done",
        {"count": 47, "top_topics": ["고민", "관계", "꿈"]},
        12, 12),
    ("many_friends", "done",
        {"count": 7, "agents": ["박지우", "김민서", "한서아", "정예린", "이하린", "최수연", "강수진"]},
        10, 10),
    # 진행 중 (unlocked, 미완)
    ("long_relationship", "unlocked",
        {"days_since_first_chat": 30, "need": 90, "agent": "박지우"},
        25, None),
    ("matchmaker", "unlocked",
        {"count": 4, "need": 10, "matches": ["박지우↔정예린", "김민서↔최수연", "이하린↔정예린", "강수진↔최수연"]},
        14, None),
    ("room_master", "unlocked",
        {"count": 3, "need": 5, "rooms": ["group-친구들", "group-회사", "group-동네맛집"]},
        8, None),
]


def update_achievements():
    conn = db.get_conn()
    try:
        for key, state, progress, ulock_d, comp_d in ACHIEVEMENTS:
            unlocked_at = _iso(NOW - timedelta(days=ulock_d))
            completed_at = _iso(NOW - timedelta(days=comp_d)) if comp_d is not None else None
            progress_json = json.dumps(progress, ensure_ascii=False)
            conn.execute(
                "INSERT OR REPLACE INTO achievements "
                "(user_id, key, state, progress_data, unlocked_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("owner", key, state, progress_json, unlocked_at, completed_at),
            )
            print(f"  [ach] {key:20} {state:10} → {progress_json[:80]}")
        conn.commit()
    finally:
        conn.close()


# ── Events 보강 ──
# 기존 5개 + 라이프사이클 이벤트 + 더 다양한 일상 추가
NEW_EVENTS = [
    ("튜토리얼시작", ["owner", "agent-mgr-001"],
     "Glimi 가입 — 서유나가 첫 인사. 페르소나 생성 흐름 안내",
     "마일스톤", T_TUTORIAL_START),
    ("페르소나생성", ["agent-creator-001", "agent-persona-001"],
     "윤하나가 첫 친구 박지우 만들어줌 — ENFP, 26세, 조용하지만 통찰력 있음",
     "마일스톤", T_TUTORIAL_START + timedelta(minutes=20)),
    ("튜토리얼완료", ["owner", "agent-mgr-001"],
     "튜토리얼 4단계 모두 통과 — 첫 친구 박지우와 dm-박지우 채널 활성화",
     "마일스톤", T_TUTORIAL_DONE),
    ("페르소나추가", ["agent-creator-001", "agent-persona-002"],
     "김민서 추가 (ENTJ, 28세) — 직설적이고 솔직, 박지우와 묘한 케미",
     "마일스톤", NOW - timedelta(days=28, hours=4)),
    ("그룹생성", ["owner", "agent-persona-001", "agent-persona-002", "agent-persona-004"],
     "오너가 박지우·김민서·정예린 묶어 group-친구들 채널 생성",
     "마일스톤", NOW - timedelta(days=24, hours=6)),
    ("관계강화", ["agent-persona-003", "agent-persona-005"],
     "한서아·이하린 동아리 모임 후 친밀도 +4",
     "긍정", NOW - timedelta(days=8, hours=2)),
    ("감정변화", ["agent-persona-001", "agent-persona-003"],
     "박지우가 한서아와 오너의 친밀도 살짝 신경 쓰기 시작",
     "주의", NOW - timedelta(days=7, hours=8)),
    ("기념일임박", ["owner", "agent-persona-001"],
     "오너 생일 다음달 — 박지우·정예린이 공동 선물 준비 중",
     "긍정", NOW - timedelta(days=6, hours=14)),
    ("회사이벤트", ["agent-persona-006", "owner"],
     "다음달 팀 워크샵 — 오너 리드 기회 검토 중 (최수연·강수진 논의)",
     "긍정", NOW - timedelta(days=5, hours=10)),
    ("작업성과", ["agent-persona-004"],
     "정예린 개인전 준비 완료 — 다음달 15일 오프닝",
     "긍정", NOW - timedelta(days=4, hours=20)),
    ("자율대화", ["agent-persona-001", "agent-persona-002"],
     "오케스트레이터가 박지우↔김민서 internal-dm 자동 시작 — 둘이 게임 얘기로 1시간 수다",
     "긍정", NOW - timedelta(days=3, hours=12)),
    ("매칭메이킹", ["owner", "agent-persona-005", "agent-persona-004"],
     "오너가 이하린·정예린 소개 — 둘 다 예술 쪽이라 자연스럽게 친해짐",
     "긍정", NOW - timedelta(days=2, hours=18)),
    ("심야대화", ["owner", "agent-persona-001"],
     "새벽 2시 dm-박지우 — 인생 고민 공유 (도전과제: late_night)",
     "긍정", NOW - timedelta(days=18, hours=22)),
    ("관계갈등", ["agent-persona-002", "agent-persona-006"],
     "김민서가 최수연한테 직설적으로 평가 — 잠시 어색해짐. 친밀도 -3",
     "주의", NOW - timedelta(days=2, hours=4)),
    ("화해", ["agent-persona-002", "agent-persona-006"],
     "다음날 김민서가 사과 — 친밀도 회복",
     "긍정", NOW - timedelta(days=1, hours=8)),
    ("새오너접속", ["owner"],
     "오너가 8시간만에 다시 들어옴 — orchestrator 가 그 동안 자율 대화 9건 생성",
     "마일스톤", NOW - timedelta(hours=3)),
]


def update_events():
    conn = db.get_conn()
    try:
        # 기존 events 다 지우고 새로 작성 (일관성 / 정렬 위해)
        conn.execute("DELETE FROM events")
        for etype, participants, desc, impact, ts in NEW_EVENTS:
            conn.execute(
                "INSERT INTO events (event_type, participants, description, impact, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (etype, json.dumps(participants, ensure_ascii=False), desc, impact, _iso(ts)),
            )
        conn.commit()
        rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"  [events] {rows}건 (전체 갱신)")
    finally:
        conn.close()


def main():
    print("=== Demo 도전과제·이벤트 mock data 보강 ===")
    print("\n[1/2] 도전과제 progress_data 갱신")
    update_achievements()
    print("\n[2/2] 이벤트 보강")
    update_events()
    print("\n=== 완료 ===")


if __name__ == "__main__":
    main()
