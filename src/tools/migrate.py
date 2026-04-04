#!/usr/bin/env python3
"""
프로필 마이그레이션 스크립트

용도 1: JSON → DB (현재 프로젝트의 profiles/*.json을 DB로 이전)
  python -m src.tools.migrate

용도 2: 기존 DB 업그레이드 (이전 형식 DB를 새 스키마로)
  python -m src.tools.migrate --upgrade-db path/to/old/chaos.db
"""
import json
import os
import sys
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src import db, community


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES_DIR = os.path.join(_PROJECT_ROOT, "profiles")
IMAGE_DIR = os.path.join(PROFILES_DIR, "agent-profile-image")
# assets/ 폴백
ASSETS_AVATAR_DIR = os.path.join(_PROJECT_ROOT, "assets", "avatars")


def _find_avatar(agent_id: str) -> str | None:
    """에이전트 ID에 매칭되는 아바타 파일명 찾기 (레거시 → assets 순서)"""
    for search_dir in (IMAGE_DIR, ASSETS_AVATAR_DIR):
        if not os.path.isdir(search_dir):
            continue
        for ext in ("png", "jpg", "jpeg", "webp"):
            fname = f"{agent_id}.{ext}"
            if os.path.exists(os.path.join(search_dir, fname)):
                return fname
    return None


def migrate_json_to_db():
    """profiles/*.json → DB 마이그레이션"""
    db.init_db()

    # 1. 에이전트 프로필 마이그레이션
    agent_count = 0
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not (fname.startswith("agent-") and fname.endswith(".json")):
            continue
        path = os.path.join(PROFILES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)

        # 아바타 파일명 매핑
        avatar = _find_avatar(profile["id"])
        if avatar:
            profile["avatar_filename"] = avatar

        db.save_agent_profile(profile)
        agent_count += 1
        print(f"  [에이전트] {profile['id']} ({profile['name']})")

    # 2. 유저 프로필 마이그레이션
    user_count = 0
    for fname in os.listdir(PROFILES_DIR):
        if fname.startswith("agent-") or not fname.endswith(".json"):
            continue
        path = os.path.join(PROFILES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        if user.get("type") not in ("user", "owner"):
            continue

        db.save_user(user)
        db.set_meta("active_user_id", user["id"])
        user_count += 1
        print(f"  [유저] {user['id']} ({user['name']})")

    # 3. 검증
    print(f"\n마이그레이션 완료: 에이전트 {agent_count}개, 유저 {user_count}명")

    # 로드 검증
    errors = 0
    for fname in sorted(os.listdir(PROFILES_DIR)):
        if not (fname.startswith("agent-") and fname.endswith(".json")):
            continue
        path = os.path.join(PROFILES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            original = json.load(f)

        loaded = db.get_agent_profile(original["id"])
        if not loaded:
            print(f"  ✗ {original['id']} — DB에서 로드 실패!")
            errors += 1
            continue

        # 핵심 필드 비교
        for field in ("name", "type", "age", "mbti"):
            orig_val = original.get(field)
            load_val = loaded.get(field)
            if orig_val != load_val:
                print(f"  ✗ {original['id']}.{field}: {orig_val!r} != {load_val!r}")
                errors += 1

        # 중첩 필드 비교
        for section in ("personality", "speech"):
            orig_sec = original.get(section, {})
            load_sec = loaded.get(section, {})
            for key in orig_sec:
                if orig_sec[key] != load_sec.get(key):
                    print(f"  ✗ {original['id']}.{section}.{key}: mismatch")
                    errors += 1

    if errors == 0:
        print("검증 통과! 모든 프로필이 DB에 정확히 저장됨")
    else:
        print(f"경고: {errors}개 필드 불일치 발견")


def upgrade_old_db(old_db_path: str):
    """기존 형식 DB를 새 스키마로 업그레이드 + 프로필 데이터까지 자동 이전

    기존 DB에는 agents, relationships, conversations, memories, events 테이블만 있고
    프로필 위성 테이블(agent_personality 등)이 없음.

    처리 순서:
    1. 백업 생성
    2. 스키마 업그레이드 (새 테이블 + 컬럼 추가)
    3. JSON 프로필에서 프로필 데이터 병합 (기존 emotion/status 보존)
    4. 유저 프로필 마이그레이션
    5. 검증
    """
    if not os.path.exists(old_db_path):
        print(f"파일 없음: {old_db_path}")
        return

    # ── 1. 백업 ──
    backup_path = old_db_path + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(old_db_path, backup_path)
    print(f"백업 생성: {backup_path}")

    # 기존 DB 경로를 임시로 설정
    original_path = db.DB_PATH
    db.DB_PATH = os.path.abspath(old_db_path)

    try:
        # ── 2. 스키마 업그레이드 ──
        db.init_db()
        print(f"스키마 업그레이드 완료")

        # ── 3. 기존 agents 런타임 상태 스냅샷 ──
        conn = db.get_conn()
        existing_agents = {}
        for row in conn.execute("SELECT * FROM agents").fetchall():
            r = dict(row)
            existing_agents[r["id"]] = {
                "current_emotion": r.get("current_emotion", "평온"),
                "emotion_intensity": r.get("emotion_intensity", 5),
                "last_active": r.get("last_active"),
                "status": r.get("status", "active"),
            }
        conn.close()
        print(f"기존 에이전트 {len(existing_agents)}개 감지")

        # ── 4. JSON 프로필 → DB 병합 ──
        agent_count = 0
        for fname in sorted(os.listdir(PROFILES_DIR)):
            if not (fname.startswith("agent-") and fname.endswith(".json")):
                continue
            path = os.path.join(PROFILES_DIR, fname)
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)

            agent_id = profile["id"]

            # 아바타 파일명 매핑
            avatar = _find_avatar(agent_id)
            if avatar:
                profile["avatar_filename"] = avatar

            # 기존 런타임 상태 복원 (emotion, status 등은 기존 DB 값 유지)
            if agent_id in existing_agents:
                old = existing_agents[agent_id]
                profile["current_emotion"] = old["current_emotion"]
                profile["emotion_intensity"] = old["emotion_intensity"]
                profile["status"] = old["status"]

            db.save_agent_profile(profile)

            # emotion/status는 save_agent_profile이 건드리지 않으므로 직접 반영
            if agent_id in existing_agents:
                old = existing_agents[agent_id]
                c = db.get_conn()
                c.execute(
                    "UPDATE agents SET current_emotion=?, emotion_intensity=?, last_active=?, status=? WHERE id=?",
                    (old["current_emotion"], old["emotion_intensity"], old["last_active"], old["status"], agent_id)
                )
                c.commit()
                c.close()

            status = "업데이트" if agent_id in existing_agents else "신규"
            agent_count += 1
            print(f"  [{status}] {agent_id} ({profile['name']})")

        # JSON에 없는 기존 에이전트 경고
        json_ids = set()
        for fname in os.listdir(PROFILES_DIR):
            if fname.startswith("agent-") and fname.endswith(".json"):
                with open(os.path.join(PROFILES_DIR, fname), "r", encoding="utf-8") as f:
                    json_ids.add(json.load(f)["id"])
        orphans = set(existing_agents.keys()) - json_ids
        for oid in orphans:
            print(f"  [경고] {oid} — DB에만 존재 (JSON 프로필 없음, 대화/메모리는 보존됨)")

        # ── 5. 유저 프로필 마이그레이션 ──
        user_count = 0
        for fname in os.listdir(PROFILES_DIR):
            if fname.startswith("agent-") or not fname.endswith(".json"):
                continue
            path = os.path.join(PROFILES_DIR, fname)
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            if user.get("type") not in ("user", "owner"):
                continue

            db.save_user(user)
            db.set_meta("active_user_id", user["id"])
            user_count += 1
            print(f"  [유저] {user['id']} ({user['name']})")

        # ── 6. 검증 ──
        print(f"\n마이그레이션 완료: 에이전트 {agent_count}개, 유저 {user_count}명")
        _verify_migration(existing_agents)

    finally:
        db.DB_PATH = original_path


def _verify_migration(original_states: dict):
    """마이그레이션 결과 검증"""
    errors = 0

    # 모든 에이전트가 프로필 로드 가능한지 확인
    conn = db.get_conn()
    agents = conn.execute("SELECT id FROM agents").fetchall()
    conn.close()

    for row in agents:
        agent_id = row["id"]
        profile = db.get_agent_profile(agent_id)
        if not profile:
            print(f"  ✗ {agent_id} — 프로필 로드 실패")
            errors += 1
            continue

        # 위성 테이블 데이터 존재 확인
        missing = []
        for section in ("personality", "speech", "appearance", "daily_life"):
            if not profile.get(section):
                missing.append(section)
        if missing:
            print(f"  △ {agent_id} — 빈 섹션: {', '.join(missing)}")

        # 기존 런타임 상태 보존 확인
        if agent_id in original_states:
            old = original_states[agent_id]
            agent = db.get_agent(agent_id)
            if agent["current_emotion"] != old["current_emotion"]:
                print(f"  ✗ {agent_id} — emotion 불일치: {old['current_emotion']} → {agent['current_emotion']}")
                errors += 1
            if agent["emotion_intensity"] != old["emotion_intensity"]:
                print(f"  ✗ {agent_id} — intensity 불일치: {old['emotion_intensity']} → {agent['emotion_intensity']}")
                errors += 1

    # 대화/메모리 보존 확인
    conn = db.get_conn()
    msg_count = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
    mem_count = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    rel_count = conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
    evt_count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
    conn.close()
    print(f"\n보존된 데이터: 대화 {msg_count}건, 메모리 {mem_count}건, 관계 {rel_count}건, 이벤트 {evt_count}건")

    if errors == 0:
        print("검증 통과!")
    else:
        print(f"경고: {errors}개 문제 발견")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--upgrade-db":
        if len(sys.argv) < 3:
            print("사용법: python -m src.tools.migrate --upgrade-db path/to/chaos.db")
            sys.exit(1)
        upgrade_old_db(sys.argv[2])
    else:
        migrate_json_to_db()
