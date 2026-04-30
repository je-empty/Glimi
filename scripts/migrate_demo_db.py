"""Demo community DB 최신 스키마/데이터 마이그레이션.

작업:
  1. 백업 → backups/demo-pre-fullname-{ts}/
  2. 스키마 동기화 — init_db (dev 타입 추가, self_aware 컬럼 등)
  3. 에이전트 이름 풀네임으로 — 매니저 (서유나/윤하나) + 페르소나 7명
  4. profile_data JSON 의 name 필드도 동일 갱신
  5. dm-{nickname} 채널 → dm-{fullname} (channels + conversations 양쪽)
  6. 매니저류 관계 row 시드 (mgr/creator/dev ↔ owner) — 동적 갱신 가능
  7. dev 에이전트 (한세나) 시드
  8. 슈퍼바이저 snapshot 갱신 (.supervisors.json)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["GLIMI_COMMUNITY"] = "demo"
from src.community import set_community
set_community("demo")
from src import db
from src.core.profile import get_user_id


# ── 풀네임 매핑 ──────────────────────────────────────────────
# 매니저류 — 기존 코드/시드와 일치
NAME_MAP = {
    "agent-mgr-001":     "서유나",
    "agent-creator-001": "윤하나",
    "agent-dev-001":     "한세나",
    # 페르소나 — 기존 닉네임에 어울리는 성 붙임 (자연스러운 한국 이름)
    "agent-persona-001": "박소은",  # 지우
    "agent-persona-002": "김민서",  # 민서
    "agent-persona-003": "한서아",  # 서아
    "agent-persona-004": "정예린",  # 예린
    "agent-persona-005": "이하린",  # 하린
    "agent-persona-006": "최수연",  # 수연
    "agent-persona-007": "강수진",  # 수진
}

OLD_NICKNAMES = {
    "agent-mgr-001":     "유나",
    "agent-creator-001": "하나",
    "agent-persona-001": "지우",
    "agent-persona-002": "민서",
    "agent-persona-003": "서아",
    "agent-persona-004": "예린",
    "agent-persona-005": "하린",
    "agent-persona-006": "수연",
    "agent-persona-007": "수진",
}


def backup() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ROOT / "communities/demo/backups" / f"demo-pre-fullname-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for s in ("", "-shm", "-wal"):
        p = ROOT / f"communities/demo/community.db{s}"
        if p.exists():
            shutil.copy2(p, dest / p.name)
    print(f"[backup] {dest}")
    return dest


def schema_sync():
    """init_db 호출 — 누락 컬럼/CHECK 자동 추가."""
    db.init_db()
    print("[schema] 동기화 완료 (init_db)")


def update_names():
    """agents.name 갱신 + relationship_templates 의 dynamics 안에 박힌 닉네임도 풀네임으로.
    프로필 본체는 agents 테이블에 분산 저장돼 있어서 name 컬럼만 갱신하면 끝."""
    conn = db.get_conn()
    try:
        for aid, full_name in NAME_MAP.items():
            row = conn.execute("SELECT name FROM agents WHERE id=?", (aid,)).fetchone()
            if not row:
                continue
            old_name = row["name"]
            if old_name == full_name:
                continue
            conn.execute("UPDATE agents SET name=? WHERE id=?", (full_name, aid))
            # relationship_templates.pet_name 있으면 닉네임 보존
            nick = OLD_NICKNAMES.get(aid)
            if nick:
                conn.execute(
                    "UPDATE agent_relationship_templates SET pet_name=? "
                    "WHERE agent_id=? AND (pet_name IS NULL OR pet_name='')",
                    (nick, aid),
                )
            print(f"  [name] {aid}: {old_name!r} → {full_name!r}")
        conn.commit()
    finally:
        conn.close()


def rename_channels():
    """dm-{nickname} → dm-{fullname} 전환. channels + conversations 일관 유지."""
    conn = db.get_conn()
    try:
        for aid, full_name in NAME_MAP.items():
            old_nick = OLD_NICKNAMES.get(aid)
            if not old_nick:
                continue
            old_dm = f"dm-{old_nick}"
            new_dm = f"dm-{full_name}"
            if old_dm == new_dm:
                continue
            # 기존 dm-{full_name} 가 이미 있으면 충돌 — 일단 skip 로깅
            existing_new = conn.execute(
                "SELECT 1 FROM channels WHERE channel=?", (new_dm,)
            ).fetchone()
            if existing_new:
                print(f"  [channels] {new_dm} 이미 존재 — skip rename")
                continue
            # channels.channel 갱신
            cur = conn.execute(
                "UPDATE channels SET channel=? WHERE channel=?", (new_dm, old_dm)
            )
            if cur.rowcount > 0:
                # conversations 의 channel 컬럼도 같이 갱신
                conn.execute(
                    "UPDATE conversations SET channel=? WHERE channel=?", (new_dm, old_dm)
                )
                print(f"  [channels] {old_dm} → {new_dm}")
        conn.commit()
    finally:
        conn.close()


def seed_dev():
    """한세나 (dev) — assets/seed_agents.json 에서 로드, name 강제 풀네임."""
    if db.get_agent("agent-dev-001"):
        # name 만 갱신
        conn = db.get_conn()
        conn.execute(
            "UPDATE agents SET name=? WHERE id=?", ("한세나", "agent-dev-001")
        )
        conn.commit()
        conn.close()
        print("  [dev] 이미 존재 — name 갱신")
        return
    seed_path = ROOT / "assets/seed_agents.json"
    with open(seed_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)
    dev_seed = next((a for a in seeds if a.get("id") == "agent-dev-001"), None)
    if not dev_seed:
        print("  [dev] seed 없음 (skip)")
        return
    dev_seed["name"] = "한세나"
    db.save_agent_profile(dev_seed)
    print("  [dev] 시드 등록 — 한세나")


def seed_manager_relationships():
    """매니저류 (mgr/creator/dev) ↔ owner 관계 row 시드 — 동적 갱신 가능하도록."""
    owner_id = get_user_id() or "owner"
    seeds = [
        ("agent-mgr-001",     "매니저",     "매니저 — 커뮤니티 운영 도와줌"),
        ("agent-creator-001", "크리에이터", "크리에이터 — 친구 만들어주는 역할"),
        ("agent-dev-001",     "개발 담당",  "개발 담당 — 시스템 이슈 처리"),
    ]
    for aid, rtype, rdyn in seeds:
        if not db.get_agent(aid):
            continue
        existing = db.get_relationship(owner_id, aid) or db.get_relationship(aid, owner_id)
        if existing:
            print(f"  [rel] {aid} 이미 존재 (intimacy={existing['intimacy_score']})")
            continue
        db.add_relationship(owner_id, aid, rtype, intimacy=db.INTIMACY_SCALE_DEFAULT, dynamics=rdyn)
        print(f"  [rel] {aid} 시드 ({rtype} / 30 / {rdyn})")


def seed_persona_owner_relationships():
    """페르소나 ↔ owner 관계 row 가 없으면 default 친구 60 시드 (데모 — 이미 친한 친구들).
    데모 컨셉이 '오너의 진짜 친구들' 이므로 어색(30) 보다 친한 친구(60) 가 맞음.
    """
    owner_id = get_user_id() or "owner"
    DEMO_PERSONA_INTIMACY = 60
    for aid, full_name in NAME_MAP.items():
        if not aid.startswith("agent-persona-"):
            continue
        if not db.get_agent(aid):
            continue
        existing = db.get_relationship(owner_id, aid) or db.get_relationship(aid, owner_id)
        if existing:
            # 데모 — 기존 값 존중하되 비어있으면 채움
            continue
        db.add_relationship(
            owner_id, aid, "친구",
            intimacy=DEMO_PERSONA_INTIMACY,
            dynamics="오랜 친구 — 자주 연락",
        )
        print(f"  [rel] {aid} ({full_name}) 시드 (친구 / {DEMO_PERSONA_INTIMACY})")


def write_supervisor_snapshot():
    """현재 시스템 supervisor 3종 (orchestrator/dev.queue/commitment.tracker) 을
    .supervisors.json 에 기록 — 봇이 안 떠도 대시보드가 그래프에 노드 표시 가능."""
    import time as _t
    snap = {
        "community_id": "demo",
        "updated_at": _t.time(),
        "items": [
            {
                "id": "orchestrator", "kind": "system",
                "display_name": "오케스트레이터",
                "scope": {}, "active": True, "registered": True,
            },
            {
                "id": "dev.queue", "kind": "system",
                "display_name": "Dev 큐 감시 (세나)",
                "scope": {}, "active": False, "registered": True,
            },
            {
                "id": "commitment.tracker", "kind": "system",
                "display_name": "약속 이행 추적",
                "scope": {}, "active": False, "registered": True,
            },
        ],
    }
    log_dir = ROOT / "communities/demo/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / ".supervisors.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print(f"  [supervisors] snapshot 기록 → {path}")


def main():
    print("=== Demo DB 마이그레이션 시작 ===")
    backup()
    print("\n[1/7] 스키마 동기화")
    schema_sync()
    print("\n[2/7] 에이전트 이름 풀네임 갱신")
    update_names()
    print("\n[3/7] dm 채널 rename")
    rename_channels()
    print("\n[4/7] dev 에이전트 (한세나) 시드")
    seed_dev()
    print("\n[5/7] 매니저류 관계 row 시드")
    seed_manager_relationships()
    print("\n[6/7] 페르소나 관계 row 시드 (누락분만)")
    seed_persona_owner_relationships()
    print("\n[7/7] supervisor snapshot 기록")
    write_supervisor_snapshot()
    print("\n=== 완료 ===")
    # 검증
    print("\n[검증]")
    conn = db.get_conn()
    for r in conn.execute("SELECT id, name, type FROM agents").fetchall():
        print(f"  {r['id']:25} {r['name']:8} ({r['type']})")
    print(f"  관계: {conn.execute('SELECT COUNT(*) FROM relationships').fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
