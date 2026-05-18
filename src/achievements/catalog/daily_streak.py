"""꾸준한 친구 — 같은 친구와 7일 연속 대화."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from src import db
from src.achievements.base import Achievement


def _norm(ch: str) -> str:
    """Discord channel name normalization (공백 → 하이픈, 소문자) 대용 — sync 모듈 의존 회피."""
    try:
        from src.core.sync import _norm_channel_name
        return _norm_channel_name(ch)
    except Exception:
        return (ch or "").strip().lower().replace(" ", "-")


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel, DATE(timestamp) as d FROM conversations "
        "WHERE channel LIKE 'dm-%' AND speaker=? GROUP BY channel, d ORDER BY channel, d",
        (user_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return None
    by_ch: dict[str, list] = {}
    for r in rows:
        if not r["d"]:
            continue
        try:
            y, m, d = r["d"].split("-")
            dt = date(int(y), int(m), int(d))
        except Exception:
            continue
        key = _norm(r["channel"])
        by_ch.setdefault(key, []).append(dt)
    best_streak = 0
    best_ch = None
    for ch, dates in by_ch.items():
        dates = sorted(set(dates))
        cur = 1
        for i in range(1, len(dates)):
            if dates[i] - dates[i-1] == timedelta(days=1):
                cur += 1
                if cur > best_streak:
                    best_streak, best_ch = cur, ch
            else:
                cur = 1
        if 1 > best_streak:
            best_streak, best_ch = 1, ch
    if best_streak >= 7:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": best_ch, "streak": best_streak}}
    if best_streak >= 3:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"channel": best_ch, "streak": best_streak, "need": 7}}
    return None


ACHIEVEMENT = Achievement(
    key="daily_streak",
    title="꾸준한 친구",
    description="같은 친구와 7일 연속 대화.",
    icon="🔥",
    check=_check,
)
