"""Memory extraction validation smoke test.

LLM 호출 없이 `_validate_fact` 파이프라인이 올바르게 필터링·정규화하는지 검증.
Usage: GLIMI_COMMUNITY=qa .venv/bin/python scripts/smoke_memory_extraction.py
"""
import os
import sys

# Default to qa community for smoke test (실존 이름 풀 사용)
os.environ.setdefault("GLIMI_COMMUNITY", "qa")

# 프로젝트 루트 path 설정
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.core import memory as mem  # noqa: E402
from src import db  # noqa: E402


def _expect(cond: bool, label: str):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    return cond


def main():
    print(f"community: {os.environ['GLIMI_COMMUNITY']}")
    print(f"db path: {db._get_db_path()}")
    agents = [a.get("name") for a in db.list_agents()]
    print(f"agents: {agents}")

    allowed = mem._known_real_subjects()
    print(f"allowed subjects: {sorted(allowed)}")

    # 자기자신 fact 검증용 — 윤하나 agent_id 찾기
    hana = db.get_agent_by_name("윤하나")
    hana_id = hana["id"] if hana else None
    yuna = db.get_agent_by_name("서유나")
    yuna_id = yuna["id"] if yuna else None
    print(f"hana_id={hana_id}  yuna_id={yuna_id}")

    all_pass = True

    # ──── Case 1: 추상 subject drop ────
    print("\n[Case 1] 추상/집합 subject drop")
    cases = [
        ("새_멤버", "성격", "밝고 활발한 여자"),
        ("새 멤버", "personality", "밝음"),
        ("이 커뮤니티", "환영하는_활동", "게임과_논쟁"),
        ("멤버들", "특징", "성향이_다양함"),
        ("친구들", "likes", "게임"),
        ("신규에이전트", "취미", "그림"),
        ("캐릭터", "성격", "밝음"),
    ]
    for s, p, o in cases:
        r = mem._validate_fact(yuna_id or "x", s, p, o, allowed_subjects=allowed)
        all_pass &= _expect(r is None, f"drop abstract subject: '{s}'")

    # ──── Case 2: 존재하지 않는 subject drop ────
    print("\n[Case 2] 존재하지 않는 subject drop")
    r = mem._validate_fact(yuna_id or "x", "홍길동", "personality", "활발", allowed_subjects=allowed)
    all_pass &= _expect(r is None, "drop unknown person subject: '홍길동'")

    # ──── Case 3: Predicate 정규화 (동의어 canonical 로) ────
    print("\n[Case 3] Predicate 정규화")
    pred_tests = [
        ("원하는친구특성", "preferred_friend_type"),
        ("원하는_친구의_성향", "preferred_friend_type"),
        ("선호하는캐릭터유형", "preferred_friend_type"),
        ("원하는_신규멤버_특징", "preferred_friend_type"),
        ("취미", "hobby"),
        ("성격", "personality"),
        ("성격특징", "personality"),
        ("직업", "occupation"),
        ("말투", "speech_style"),
        ("MBTI", "mbti"),
    ]
    for raw, expected in pred_tests:
        canon = mem._canonical_predicate(raw)
        all_pass &= _expect(canon == expected, f"'{raw}' → '{canon}' (want '{expected}')")

    # 실제 validate 호출로도 확인 — subject 는 실존 인물
    r = mem._validate_fact(yuna_id or "x", "심재빈", "원하는_친구의_성향",
                           "밝고 활발한 여자", allowed_subjects=allowed)
    all_pass &= _expect(r is not None and r[1] == "preferred_friend_type",
                         f"심재빈 + alias predicate → canonical: {r}")

    # ──── Case 4: 자기 자신 profile 중복 drop ────
    print("\n[Case 4] 자기 자신 profile 중복 drop")
    if hana_id:
        # profile 에 traits=["창의적인", "장난기 있는", "디테일에 강한", "캐릭터 덕후"]
        r = mem._validate_fact(hana_id, "윤하나", "성격", "창의적인",
                               allowed_subjects=allowed)
        all_pass &= _expect(r is None, "skip self-fact already in profile (traits)")
        # profile 에 없는 값은 통과해야 함
        r = mem._validate_fact(hana_id, "윤하나", "personality", "요즘 좀 피곤함",
                               allowed_subjects=allowed)
        all_pass &= _expect(r is not None, "allow self-fact NOT in profile")

    # mgr persona "서유나" 은 traits 가 '또래보다 생각이 깊고 똑부러짐' 등
    if yuna_id:
        # 동일 값 아니라도 비슷하면 skip 되어야. 여기선 완전히 다른 값을 통과시켜 본다.
        r = mem._validate_fact(yuna_id, "서유나", "personality", "냉정한 분석가",
                               allowed_subjects=allowed)
        all_pass &= _expect(r is not None, "allow self-fact with new insight")

    # ──── Case 5: 일시 상태 object drop ────
    print("\n[Case 5] 일시 상태 drop")
    transient_cases = [
        ("심재빈", "방문주기", "오랜만"),
        ("심재빈", "상태", "지금"),
        ("심재빈", "상태", "방금"),
        ("심재빈", "시간", "나중"),
        ("심재빈", "활동", "이따"),
    ]
    for s, p, o in transient_cases:
        r = mem._validate_fact(yuna_id or "x", s, p, o, allowed_subjects=allowed)
        all_pass &= _expect(r is None, f"drop transient object: '{o}'")

    # ──── Case 6: 정상 case 통과 ────
    print("\n[Case 6] 정상 fact 통과")
    r = mem._validate_fact(yuna_id or "x", "심재빈", "직업", "개발자",
                           allowed_subjects=allowed)
    all_pass &= _expect(r == ("심재빈", "occupation", "개발자"), f"normalize 직업→occupation: {r}")

    r = mem._validate_fact(yuna_id or "x", "심재빈", "MBTI", "ENTP",
                           allowed_subjects=allowed)
    all_pass &= _expect(r == ("심재빈", "mbti", "ENTP"), f"MBTI→mbti: {r}")

    # ──── 결과 ────
    print("\n" + ("=" * 50))
    print("ALL PASS" if all_pass else "SOME FAILED")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
