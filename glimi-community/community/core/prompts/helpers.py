"""
프롬프트 빌더 공통 헬퍼.

profile.py 에서 분리됨 (pure move — 로직 변경 없음).
"""
from __future__ import annotations

from pathlib import Path

from community import db


def get_community_language() -> str:
    """현재 커뮤니티 언어"""
    try:
        from community.community import get_language
        return get_language()
    except Exception:
        return "en"


def tools_reference(agent_type: str) -> str:
    """에이전트 타입별 <tools> 도구 레퍼런스 — system prompt 주입용.

    Elastic Prompt: num_ctx 에 맞춰 상세도 동적 조절.
      compact(4096)  = 이름+시그니처만 (build_compact_list)
      standard(8192) = brief (이름+필수파라미터+한줄설명)
      full(16384)    = brief (동일 — 도구 verbose 는 토큰 과다라 on-demand 유지)
    상세는 항상 `get_tool_details(name)` 로 on-demand."""
    try:
        from glimi.tools.reference import build_brief_list, build_compact_list
        from glimi.context_budget import prompt_detail_level
        if prompt_detail_level() == "compact":
            return build_compact_list(agent_type)
        return build_brief_list(agent_type)
    except Exception:
        try:
            from glimi.tools.reference import build_brief_list
            return build_brief_list(agent_type)
        except Exception:
            return ""


def formatting_guide(agent_type: str = "persona") -> str:
    """포맷 가이드 — 에이전트 프롬프트에 주입.
    agent_type 별 예시 분기: persona 에겐 자기 dm/group 만, staff(mgr/creator) 에겐 매니저 DM 포함.
    이전엔 persona 에게도 매니저 채널 예시가 주입돼 메타 누출 회귀 발생.

    Platform decoupling: 이전엔 `community.bot.formatting` 에서 import 하는 소프트 누수였으나
    `community.core.formatting` 으로 이동됨 (Phase 2-C)."""
    try:
        from community.core.formatting import get_formatting_guide
        return get_formatting_guide(agent_type)
    except Exception:
        return ""


def format_speech_section(speech: dict) -> str:
    """말투 섹션 — 압축 포맷"""
    parts = []

    if speech.get("style_description"):
        parts.append(speech['style_description'])
    if speech.get("honorific"):
        parts.append(f"존칭: {speech['honorific']}")
    if speech.get("signature_expressions"):
        parts.append(f"자주 쓰는 표현: {', '.join(speech['signature_expressions'][:4])}")
    if speech.get("emoji_pattern"):
        parts.append(f"이모지: {speech['emoji_pattern']}")

    # few_shot: 2개만, 같은 화자 합침, 한 줄 포맷
    examples = speech.get("few_shot_examples", [])
    if examples:
        parts.append("\n예시(참고만):")
        for ex in examples[:2]:
            merged = []
            prev_speaker = None
            prev_msgs = []
            for d in ex.get("dialogue", []):
                if d["speaker"] == prev_speaker:
                    prev_msgs.append(d["message"])
                else:
                    if prev_speaker and prev_msgs:
                        merged.append(f"{prev_speaker}: {' / '.join(prev_msgs)}")
                    prev_speaker = d["speaker"]
                    prev_msgs = [d["message"]]
            if prev_speaker and prev_msgs:
                merged.append(f"{prev_speaker}: {' / '.join(prev_msgs)}")
            parts.append(f"[{ex.get('situation', '')}] {' → '.join(merged)}")

    return "\n".join(parts)


def build_pet_name_section(agent_id: str) -> str:
    """별칭 정보 (relationships 테이블 기반)"""
    rels = db.get_all_relationships(agent_id)
    if not rels:
        return ""
    lines = ["=== 호칭 ==="]
    for r in rels:
        if r["agent_a"] == agent_id:
            other_id = r["agent_b"]
            my_call = r.get("pet_name_a_to_b")
            their_call = r.get("pet_name_b_to_a")
        else:
            other_id = r["agent_a"]
            my_call = r.get("pet_name_b_to_a")
            their_call = r.get("pet_name_a_to_b")
        other = db.get_agent(other_id)
        if other:
            if my_call:
                lines.append(f"  {other['name']}을(를) '{my_call}'로 불러")
            if their_call:
                lines.append(f"  {other['name']}이(가) 너를 '{their_call}'로 불러")
    return "\n".join(lines) if len(lines) > 1 else ""


def build_channel_summary() -> str:
    """채널 활동 요약 (유나 system prompt용)"""
    try:
        overview = db.get_channel_overview()
        if not overview:
            return "No active channels"
        lines = []
        for ch in overview[:10]:  # 최대 10개
            last = ch["last_active"][:16] if ch["last_active"] else "?"
            lines.append(f"- {ch['channel']}: {ch['msg_count']}건 ({last})")
        return "\n".join(lines)
    except Exception:
        return "조회 실패"


def load_sample_catalog() -> str:
    """샘플 프로필 이미지 카탈로그 로드. status=='ready'인 항목만 하나에게 노출
    (placeholder는 이미지 파일 미생성 상태 — 노출 시 없는 파일 추천하는 환각 유발)."""
    import json as _json
    # profile.py 위치 기준으로 계산되던 경로 — 이 파일은 src/core/prompts/helpers.py 이므로
    # 같은 프로젝트 루트 (src/core/prompts/../../.. == 프로젝트 루트) 를 얻으려면 parents[3].
    catalog_path = Path(__file__).resolve().parents[3] / "assets" / "sample_profile_images" / "catalog.json"
    if not catalog_path.exists():
        return "(샘플 없음)"
    # 이미 사용 중인 sample 원본 파일명 — catalog 에서 제외 (중복 이미지 방지).
    # agents.sample_source_file 에 저장됨 (set_profile_image 시).
    used_samples: set[str] = set()
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT sample_source_file FROM agents "
            "WHERE type='persona' AND sample_source_file IS NOT NULL"
        ).fetchall()
        conn.close()
        for r in rows:
            v = r["sample_source_file"] if hasattr(r, "__getitem__") else r[0]
            if v:
                used_samples.add(v)
    except Exception:
        pass

    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = _json.load(f)
        lines = []
        for item in catalog:
            # placeholder는 스킵 — 실제 이미지 파일 없음
            if item.get("status") == "placeholder":
                continue
            if item["file"] in used_samples:
                continue
            # 구조화 필드 우선, 없으면 legacy tags 사용
            gender = item.get("gender", "")
            age_range = item.get("age_range", "")
            mbti = "/".join(item.get("mbti_primary", []))
            vibe = ", ".join(item.get("vibe_tags", [])[:4]) or ", ".join(item.get("tags", [])[:4])
            meta = " / ".join([x for x in [gender, age_range, mbti] if x])
            lines.append(f"  - {item['file']} [{meta}]: {item['description']} ({vibe})")
        prefix = ""
        if used_samples:
            prefix = f"(이미 사용된 {len(used_samples)}개 샘플 제외됨)\n"
        return prefix + "\n".join(lines) if lines else "(ready 상태 샘플 없음 — placeholder만 존재)"
    except Exception:
        return "(카탈로그 로드 실패)"
