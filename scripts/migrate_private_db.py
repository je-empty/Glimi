"""Private community DB 최신 스키마/데이터 마이그레이션.

private 은 이미 풀네임 + 페르소나 관계 dynamics 가 풍부함. 보강 포인트:
  1. 스키마 동기화 (dev type CHECK, self_aware 컬럼)
  2. 한세나 (dev) 시드
  3. 매니저류 관계 row 시드 (mgr/creator/dev ↔ jaebin) — dev 신규
  4. 도전과제 12건 → progress_data 보강 + 진행중 (long_relationship/matchmaker/room_master)
  5. 이벤트 mock data 추가 (라이프사이클 + 일상 드라마)
  6. supervisor snapshot 기록
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["GLIMI_COMMUNITY"] = "private"
from src.community import set_community
set_community("private")
from src import db
from src.core.profile import get_user_id


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.astimezone(timezone.utc).isoformat()


NOW = datetime.now(timezone.utc)


def backup() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ROOT / "communities/private/backups" / f"private-pre-migrate-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for s in ("", "-shm", "-wal"):
        p = ROOT / f"communities/private/community.db{s}"
        if p.exists():
            shutil.copy2(p, dest / p.name)
    print(f"[backup] {dest}")
    return dest


def schema_sync():
    db.init_db()
    print("[schema] 동기화 완료 (init_db)")


def seed_dev():
    if db.get_agent("agent-dev-001"):
        print("  [dev] 이미 존재 — skip")
        return
    seed_path = ROOT / "assets/seed_agents.json"
    with open(seed_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)
    dev_seed = next((a for a in seeds if a.get("id") == "agent-dev-001"), None)
    if not dev_seed:
        print("  [dev] seed 없음")
        return
    db.save_agent_profile(dev_seed)
    print("  [dev] 시드 등록 — 한세나")


def seed_manager_relationships():
    owner_id = get_user_id() or "jaebin"
    seeds = [
        ("agent-mgr-001",     "매니저",     "Glimi 매니저 — 재빈이 가장 의지하는 시스템 친구. 챙겨주는 누나 같은 톤"),
        ("agent-creator-001", "크리에이터", "친구 만들어주는 역할 — 재빈 취향 잘 파악함"),
        ("agent-dev-001",     "개발 담당",  "시스템 이슈 처리 — 재빈이 직접 코멘트 가능한 dev partner"),
    ]
    for aid, rtype, rdyn in seeds:
        if not db.get_agent(aid):
            continue
        existing = db.get_relationship(owner_id, aid) or db.get_relationship(aid, owner_id)
        if existing:
            print(f"  [rel] {aid} 이미 존재")
            continue
        db.add_relationship(owner_id, aid, rtype, intimacy=db.INTIMACY_SCALE_DEFAULT, dynamics=rdyn)
        print(f"  [rel] {aid} 시드 ({rtype} / 30 / {rdyn[:40]}…)")


# ── 도전과제 ──────────────────────────────────────────────────
ACHIEVEMENTS = [
    ("tutorial_done", "done",
        {"phase_count": 4, "duration_minutes": 48},
        45, 45),
    ("first_friend_chat", "done",
        {"friend": "은하윤", "channel": "dm-은하윤", "msgs": 12,
         "first_msg": "오랜만이지 ㅋㅋ 잘 지냈어?"},
        44, 44),
    ("three_friends", "done",
        {"talked_to": ["은하윤", "최지수", "심민지", "송이린", "한소율", "나윤서", "심유진"]},
        42, 41),
    ("group_chat", "done",
        {"channel": "group-심유진-심민지", "msgs": 28, "members": ["심유진", "심민지"]},
        38, 38),
    ("peek_internal", "done",
        {"channels": ["internal-dm-서유나-윤하나", "internal-dm-심민지-한소율", "internal-dm-은하윤-최지수"],
         "first_overheard_at": "서유나↔윤하나 대화 (창조 흐름 협업)"},
        35, 35),
    ("agent_auto_chat", "done",
        {"channel": "internal-dm-은하윤-송이린",
         "trigger": "오너 부재 6시간 → 하윤·이린 자율 대화 시작"},
        30, 30),
    ("late_night", "done",
        {"channel": "dm-은하윤", "at_hour": 3, "msgs": 22,
         "topic": "장거리 연애 7년차 — 미래 얘기"},
        28, 28),
    ("chatter", "done",
        {"count": 2840},
        25, 25),
    ("secret_keeper", "done",
        {"count": 89, "top_topics": ["연애", "고민", "가족", "직장"]},
        22, 22),
    ("many_friends", "done",
        {"count": 7, "agents": ["은하윤", "최지수", "심민지", "송이린", "한소율", "나윤서", "심유진"]},
        20, 20),
    # 진행중
    ("long_relationship", "unlocked",
        {"days_since_first_chat": 45, "need": 90, "agent": "은하윤"},
        40, None),
    ("matchmaker", "unlocked",
        {"count": 6, "need": 10,
         "matches": ["은하윤↔송이린", "심민지↔한소율", "은하윤↔최지수", "심유진↔심민지",
                     "최지수↔나윤서", "송이린↔한소율"]},
        24, None),
    ("room_master", "unlocked",
        {"count": 1, "need": 5, "rooms": ["group-심유진-심민지"]},
        18, None),
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
                ("jaebin", key, state, progress_json, unlocked_at, completed_at),
            )
            print(f"  [ach] {key:20} {state:10}")
        conn.commit()
    finally:
        conn.close()


# ── 이벤트 ──────────────────────────────────────────────────
EVENTS = [
    ("튜토리얼시작", ["jaebin", "agent-mgr-001"],
     "Glimi 가입 — 서유나가 첫 인사. 재빈 프로필 수집 시작",
     "마일스톤", NOW - timedelta(days=45, hours=2)),
    ("페르소나생성", ["agent-creator-001", "agent-persona-001"],
     "윤하나가 첫 친구 은하윤 (여자친구, 7년차) 생성",
     "마일스톤", NOW - timedelta(days=45, hours=1, minutes=30)),
    ("튜토리얼완료", ["jaebin", "agent-mgr-001"],
     "튜토리얼 4단계 완료 — dm-은하윤 활성화",
     "마일스톤", NOW - timedelta(days=45)),
    ("페르소나추가", ["agent-creator-001", "agent-persona-002"],
     "최지수 (소꿉친구) 추가 — 은하윤이랑 캐릭터 정반대로 설정",
     "마일스톤", NOW - timedelta(days=43, hours=18)),
    ("페르소나추가", ["agent-creator-001", "agent-persona-003"],
     "심민지 (친여동생, 8살 어림) 추가 — 오빠 사랑 가득",
     "마일스톤", NOW - timedelta(days=42, hours=10)),
    ("관계강화", ["agent-persona-001", "jaebin"],
     "은하윤이랑 dm 에서 연애 7주년 얘기 — 친밀도 +5 (75→80)",
     "긍정", NOW - timedelta(days=40, hours=8)),
    ("감정변화", ["agent-persona-003", "agent-persona-001"],
     "심민지가 오빠 여자친구(은하윤)한테 미묘한 견제 — 동생 질투 발현",
     "주의", NOW - timedelta(days=38, hours=14)),
    ("심야대화", ["jaebin", "agent-persona-001"],
     "새벽 3시 dm-은하윤 — 미래 얘기 깊이 (도전과제: late_night)",
     "긍정", NOW - timedelta(days=28, hours=21)),
    ("자율대화", ["agent-persona-001", "agent-persona-004"],
     "오케스트레이터가 은하윤↔송이린 internal-dm 자동 시작 — 연애 상담",
     "긍정", NOW - timedelta(days=26, hours=11)),
    ("매칭메이킹", ["jaebin", "agent-persona-003", "agent-persona-005"],
     "재빈이 심민지·한소율 소개 (친구 오빠 ↔ 친여동생 관계 발전)",
     "긍정", NOW - timedelta(days=24, hours=6)),
    ("관계갈등", ["agent-persona-002", "agent-persona-001"],
     "최지수가 은하윤한테 직설적 평가 — '너 너무 완벽하려고 해' 잠시 어색",
     "주의", NOW - timedelta(days=20, hours=9)),
    ("화해", ["agent-persona-002", "agent-persona-001"],
     "다음날 최지수가 사과 — 재빈 통해 풀림. 친밀도 +2 회복",
     "긍정", NOW - timedelta(days=19, hours=22)),
    ("회사이벤트", ["agent-persona-006", "jaebin"],
     "나윤서랑 술친구 — '여사친 비밀' 베프 모드. 다른 사람한테는 비공개",
     "긍정", NOW - timedelta(days=15, hours=18)),
    ("작업성과", ["agent-persona-007", "jaebin"],
     "심유진 (8살 터울 누나) 진급 소식 — 가족 단톡 비공개로 축하",
     "긍정", NOW - timedelta(days=12, hours=10)),
    ("기념일임박", ["jaebin", "agent-persona-001"],
     "은하윤 생일 5일 후 — 재빈이 깜짝 이벤트 준비 (윤하나 통해 자문)",
     "긍정", NOW - timedelta(days=8, hours=4)),
    ("관계진화", ["agent-persona-003", "agent-persona-001"],
     "심민지가 결국 은하윤 인정 — '오빠한테 잘해줘서 다행' 한 마디",
     "마일스톤", NOW - timedelta(days=5, hours=12)),
    ("자율대화", ["agent-persona-007", "agent-persona-006"],
     "심유진↔나윤서 internal-dm — 재빈이 결혼 어떻게 생각하는지 toss",
     "주의", NOW - timedelta(days=3, hours=14)),
    ("새오너접속", ["jaebin"],
     "재빈이 12시간만에 다시 들어옴 — 그 사이 자율 대화 14건",
     "마일스톤", NOW - timedelta(hours=4)),
]


def update_events():
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM events")
        for etype, participants, desc, impact, ts in EVENTS:
            conn.execute(
                "INSERT INTO events (event_type, participants, description, impact, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (etype, json.dumps(participants, ensure_ascii=False), desc, impact, _iso(ts)),
            )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"  [events] {n}건")
    finally:
        conn.close()


def write_supervisor_snapshot():
    import time as _t
    snap = {
        "community_id": "private",
        "updated_at": _t.time(),
        "items": [
            {"id": "orchestrator", "kind": "system", "display_name": "오케스트레이터",
             "scope": {}, "active": True, "registered": True},
            {"id": "dev.queue", "kind": "system", "display_name": "Dev 큐 감시 (세나)",
             "scope": {}, "active": False, "registered": True},
            {"id": "commitment.tracker", "kind": "system", "display_name": "약속 이행 추적",
             "scope": {}, "active": False, "registered": True},
        ],
    }
    log_dir = ROOT / "communities/private/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / ".supervisors.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print(f"  [supervisors] snapshot 기록 → {path}")


def main():
    print("=== Private DB 마이그레이션 시작 ===")
    backup()
    print("\n[1/6] 스키마 동기화")
    schema_sync()
    print("\n[2/6] dev 에이전트 (한세나) 시드")
    seed_dev()
    print("\n[3/6] 매니저류 관계 row 시드")
    seed_manager_relationships()
    print("\n[4/6] 도전과제 progress_data 보강")
    update_achievements()
    print("\n[5/6] 이벤트 mock data")
    update_events()
    print("\n[6/6] supervisor snapshot")
    write_supervisor_snapshot()
    print("\n=== 완료 ===")
    conn = db.get_conn()
    print(f"\n에이전트: {conn.execute('SELECT COUNT(*) FROM agents').fetchone()[0]}")
    print(f"관계: {conn.execute('SELECT COUNT(*) FROM relationships').fetchone()[0]}")
    print(f"도전과제: {conn.execute('SELECT COUNT(*) FROM achievements').fetchone()[0]}")
    print(f"이벤트: {conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
