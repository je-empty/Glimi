"""
프로필 매니저: DB 기반 프로필 로드/관리 + system prompt 빌드
"""
import json
import os
from pathlib import Path
from typing import Optional
from community import db, community


_YUNA_KNOWLEDGE_CACHE: dict = {"text": None, "mtime": 0}


def _load_yuna_knowledge() -> str:
    """docs/yuna_knowledge.md 를 로드해 유나 system prompt 에 삽입.
    파일 mtime 바뀌면 자동 재로드 (개발 중 편집해도 봇 재시작 불필요).
    파일 없으면 빈 섹션 반환."""
    try:
        p = Path(__file__).resolve().parent.parent.parent / "docs" / "yuna_knowledge.md"
        if not p.exists():
            return ""
        mtime = p.stat().st_mtime
        if _YUNA_KNOWLEDGE_CACHE["text"] and _YUNA_KNOWLEDGE_CACHE["mtime"] == mtime:
            return _YUNA_KNOWLEDGE_CACHE["text"]
        body = p.read_text(encoding="utf-8")
        wrapped = (
            "--- 지식 베이스 (사용자 질의 대응용) ---\n"
            "아래는 네가 프로젝트에 대해 사용자에게 설명할 수 있는 내용. "
            "공개 가능 / 금지 경계 엄수. 금지 주제는 자연스럽게 회피해.\n\n"
            + body
            + "\n--- /지식 베이스 ---"
        )
        _YUNA_KNOWLEDGE_CACHE["text"] = wrapped
        _YUNA_KNOWLEDGE_CACHE["mtime"] = mtime
        return wrapped
    except Exception as e:
        print(f"[yuna_knowledge] 로드 실패: {e}")
        return ""

# 레거시 경로 (마이그레이션용)
PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
IMAGE_DIR = os.path.join(PROFILES_DIR, "agent-profile-image")

# 캐시
_profile_cache: dict[str, dict] = {}
_user_summary_cache: Optional[str] = None
_user_profile_cache: Optional[dict] = None


def get_user_profile(user_id: Optional[str] = None) -> dict:
    """오너(봇 오너) 프로필 로드 — DB 기반"""
    global _user_profile_cache
    if _user_profile_cache is not None and user_id is None:
        return _user_profile_cache
    u = db.get_user(user_id)
    if u:
        _user_profile_cache = u
        return u
    _user_profile_cache = {"id": "owner", "name": "오너"}
    return _user_profile_cache


def get_user_name() -> str:
    """오너 표시 이름"""
    return get_user_profile().get("name", "유저")


def get_user_id() -> str:
    """오너 ID"""
    return get_user_profile().get("id", "owner")


def get_user_display_name() -> str:
    """오너 표시 이름 (대화 이력/UI 표기용) — 별칭 > 이름 > fallback"""
    call = get_owner_call_name()
    if call:
        return call
    return get_user_name()


def get_agent_display_name(agent_id: str) -> str:
    """에이전트 표시 이름 — DB에서 조회, 없으면 id 그대로"""
    p = load_profile(agent_id)
    if p and p.get("name"):
        return p["name"]
    a = db.get_agent(agent_id)
    if a and a.get("name"):
        return a["name"]
    return agent_id


def load_profile(agent_id: str) -> Optional[dict]:
    """프로필 로드 — DB 기반 (캐시)"""
    if agent_id in _profile_cache:
        return _profile_cache[agent_id]
    data = db.get_agent_profile(agent_id)
    if not data:
        return None
    _profile_cache[agent_id] = data
    return data


def invalidate_cache(agent_id: str = None):
    """캐시 무효화 (프로필 수정 시).

    agent_id 주면 해당 에이전트만, 없으면 에이전트 전체 + 유저 프로필 요약 모두 초기화.
    유저 프로필 캐시(`_user_profile_cache`)도 같이 비워야 `update_profile` 직후
    mgr/creator 시스템 프롬프트에 갱신된 값이 반영됨."""
    global _user_summary_cache, _user_profile_cache
    if agent_id:
        _profile_cache.pop(agent_id, None)
    else:
        _profile_cache.clear()
        _user_profile_cache = None
    _user_summary_cache = None


def get_owner_call_name() -> str:
    """에이전트가 오너를 부를 때 사용할 이름 (별칭 > 이름 > fallback)"""
    user = get_user_profile() or {}
    # personality에 nickname 있으면 사용 (미설정/NULL 이면 {} 로 폴백 — 오너 프로필이
    # 아직 비어 있는 새 커뮤니티에서 None.get() 크래시 방지)
    p = user.get("personality") or {}
    if isinstance(p, str):
        try:
            import json
            p = json.loads(p) or {}
        except Exception:
            p = {}
    if not isinstance(p, dict):
        p = {}
    nickname = p.get("nickname", "")
    if nickname:
        return nickname
    name = user.get("name", "")
    if name and name != "오너":
        return name
    return ""


def _load_user_summary() -> str:
    """오너 프로필 요약 (캐시됨) — Yuna/Hana system prompt에 삽입되어
    같은 정보를 반복 질문하지 않도록 함."""
    global _user_summary_cache
    if _user_summary_cache is not None:
        return _user_summary_cache

    user = get_user_profile()
    if not user or not user.get("name"):
        _user_summary_cache = ""
        return ""

    p = user.get("personality") or {}
    a = user.get("appearance") or {}
    d = user.get("daily_life") or {}
    s = user.get("speech") or {}
    name = user.get("name", "?")
    age = user.get("age", "?")
    mbti = user.get("mbti", "") or "?"
    enneagram = user.get("enneagram", "") or "?"
    background = user.get("background", "") or d.get("occupation", "") or "?"
    hobby = p.get("hobby", "") or ", ".join(p.get("likes", []) or []) or "?"
    speech_style = s.get("style_description", "") or s.get("style", "") or "?"

    lines = [
        f"[{name}] age {age} | MBTI: {mbti} | enneagram: {enneagram}",
        f"  job: {background} | hobby: {hobby}",
        f"  speech style: {speech_style}",
    ]
    appearance_summary = a.get("summary", "")
    if appearance_summary:
        lines.append(f"  appearance: {appearance_summary}")

    _user_summary_cache = "\n".join(lines)
    return _user_summary_cache




def save_profile(profile: dict):
    """프로필 DB에 저장"""
    agent_id = profile["id"]
    db.save_agent_profile(profile)
    invalidate_cache(agent_id)
    print(f"[Profile] {agent_id} 저장 완료")


def list_all_profiles() -> list[dict]:
    """모든 에이전트 프로필 로드 — DB 기반"""
    agents = db.list_agents()
    profiles = []
    for a in agents:
        p = load_profile(a["id"])
        if p:
            profiles.append(p)
    return profiles


def register_all_to_db():
    """DB에 등록된 모든 에이전트 확인 (프로필은 이미 DB에 있음)"""
    profiles = list_all_profiles()
    for p in profiles:
        db.register_agent(p["id"], p["type"], p["name"])
    print(f"  [DB] 에이전트 {len(profiles)}개 확인")
    return profiles


def setup_initial_relationships():
    """초기 관계 설정 — DB relationship_templates 기반"""
    conn = db.get_conn()
    templates = conn.execute("SELECT * FROM agent_relationship_templates").fetchall()
    conn.close()

    user_id = get_user_id()
    for t in templates:
        t = dict(t)
        agent_id = t["agent_id"]
        if t["is_owner_relationship"]:
            existing = db.get_relationship(user_id, agent_id)
            if not existing:
                db.add_relationship(
                    user_id, agent_id,
                    t["rel_type"],
                    intimacy=75,
                    dynamics=t.get("dynamics", "")
                )
        else:
            existing = db.get_relationship(agent_id, t["target_id"])
            if not existing:
                db.add_relationship(
                    agent_id, t["target_id"],
                    t["rel_type"],
                    intimacy=60,
                    dynamics=t.get("note", "")
                )


# system prompt 빌더는 src/core/prompts/ 로 분리됨. 외부 호출자 호환성을 위해 재노출.
from community.core.prompts import build_system_prompt  # noqa: E402,F401


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
