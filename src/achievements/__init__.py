"""
Glimi Achievements (도전과제) — 선택적 유저 가이드 레이어.

씬(Scene) 이 스토리 에피소드라면, Achievement 는 **유저 UX 진척도**.
강제성 없음 — 유저가 미해결 상태로 놔둬도 됨. supervisor 같은 nudge 도 없음.
대시보드에 체크리스트로 보이고, 완료 시점에 유나가 자연스럽게 축하 한마디 (선택).

등록:
    from src.achievements import engine
    engine.install()  # db.add_message_hook 등록

조회/상태:
    from src import db
    db.list_achievements(user_id)
"""
from src.achievements import engine

__all__ = ["engine"]
