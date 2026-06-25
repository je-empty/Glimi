# SPDX-License-Identifier: AGPL-3.0-or-later
"""방문자 세션 추적 — 공개 비콘(/api/track) + 관리자 세션 조회(/api/admin/sessions).

공개 랜딩/데모 페이지의 익명 방문을 ``sid``(탭 세션) 단위로 묶어, 누가 어떤 페이지에
몇 초 머물렀는지를 세션 타임라인으로 본다. path·referrer·체류시간·UA·IP 만 수집한다
(폼/키 입력 추적 아님). 조회는 admin 인증 필수. je-empty resume.iruyo.com 이식.

엔드포인트:
  POST /api/track            — 공개 비콘. 진입 INSERT / 이탈(dwell_ms) UPDATE.
  GET  /api/admin/sessions   — admin. visit_log 를 sid 로 묶은 세션 저니 JSON.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from community.core.timeutil import now_utc_iso

from ..auth import require_admin
from ..db import conn

router = APIRouter()

# 분리 배포 대비: 공개 데모 인스턴스와 내부 admin 인스턴스가 서로 다른 platform.db 를
# 쓰면 공개 방문이 admin 에 안 보인다. GLIMI_VISITS_DB 로 방문기록만 공유 SQLite 에 모은다.
# 미설정(개발/단일 인스턴스)이면 공유 platform.db 그대로 — 즉 동작/테스트 불변.
_VISITS_DB = (os.environ.get("GLIMI_VISITS_DB") or "").strip()
_VISIT_DDL = """
CREATE TABLE IF NOT EXISTS visit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ts_epoch REAL NOT NULL,
    ip TEXT, country TEXT, city TEXT, asorg TEXT, asn TEXT, ua TEXT, path TEXT, referrer TEXT,
    is_owner INTEGER DEFAULT 0, sid TEXT, dwell_ms INTEGER );
CREATE INDEX IF NOT EXISTS idx_visit_ip  ON visit_log(ip);
CREATE INDEX IF NOT EXISTS idx_visit_ts  ON visit_log(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_visit_sid ON visit_log(sid);
"""


@contextmanager
def _vconn():
    """방문기록 DB 연결. GLIMI_VISITS_DB 설정 시 그 전용 파일(여러 인스턴스 공유, WAL),
    아니면 공유 platform.db(``conn``)."""
    if not _VISITS_DB:
        with conn() as c:
            yield c
        return
    Path(_VISITS_DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_VISITS_DB, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")  # 멀티프로세스 동시 read/write
        c.executescript(_VISIT_DDL)           # 전용 DB 에 테이블 보장
        yield c
    finally:
        c.close()

# 운영자(자기) IP — GLIMI_OWNER_IPS="1.2.3.4,5.6.7.8". 비우면 항상 방문자로 취급.
_OWNER_IPS = {ip.strip() for ip in (os.environ.get("GLIMI_OWNER_IPS") or "").split(",") if ip.strip()}
# 관리자/내부 경로는 추적 제외 (비콘도 프론트에서 막지만 백엔드에서도 방어).
_EXCLUDE_PREFIXES = ("/admin", "/api/", "/static/", "/login", "/setup", "/logo", "/favicon")
_MAX_DWELL_MS = 6 * 3600 * 1000  # 6h cap — 탭 백그라운드 누적 방지


class VisitIn(BaseModel):
    path: str = ""
    ref: str = ""
    sid: str = ""
    dwell_ms: int | None = None


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/api/track")
async def track_visit(v: VisitIn, request: Request):
    """공개 비콘. 인증 없음. 진입(INSERT) 또는 이탈(dwell UPDATE)."""
    sid = (v.sid or "")[:64]
    path = (v.path or "")[:300]
    if any(path.startswith(p) for p in _EXCLUDE_PREFIXES):
        return {"ok": True}  # 추적 제외 경로

    if v.dwell_ms is not None:
        # 이탈 비콘 — 같은 sid·path 의 가장 최근 진입 행(dwell 미기록)에 체류시간 기록.
        if not sid:
            return {"ok": True}
        dwell = max(0, min(int(v.dwell_ms), _MAX_DWELL_MS))
        with _vconn() as c:
            c.execute(
                "UPDATE visit_log SET dwell_ms = ? WHERE id = ("
                "  SELECT id FROM visit_log WHERE sid = ? AND path = ? AND dwell_ms IS NULL "
                "  ORDER BY ts_epoch DESC LIMIT 1)",
                (dwell, sid, path),
            )
            c.commit()
        return {"ok": True}

    # 진입 비콘
    hdr = request.headers
    ip = _client_ip(request)
    with _vconn() as c:
        c.execute(
            "INSERT INTO visit_log (ts, ts_epoch, ip, country, city, asorg, asn, ua, "
            "path, referrer, is_owner, sid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now_utc_iso(), time.time(), ip,
                hdr.get("cf-ipcountry", "") or hdr.get("x-client-country", ""),
                hdr.get("x-client-city", ""),
                hdr.get("x-client-asorg", ""),
                hdr.get("x-client-asn", ""),
                (hdr.get("user-agent", ""))[:400],
                path, (v.ref or "")[:300],
                1 if ip in _OWNER_IPS else 0,
                sid,
            ),
        )
        c.commit()
    return {"ok": True}


@router.get("/api/admin/sessions")
async def admin_sessions(
    request: Request,
    limit: int = 200,
    user: dict = Depends(require_admin),
):
    """visit_log 를 sid 로 묶은 세션 저니. sid 없는 구방문은 IP+30분으로 복원.

    반환: {sessions:[{sid, legacy, ip, country, city, asorg, ua, is_owner, start_ts,
    page_count, total_dwell_ms, duration_ms, events:[{path, ts, dwell_ms}]}], total, visitors}
    """
    with _vconn() as c:
        rows = c.execute(
            "SELECT ts, ts_epoch, ip, country, city, asorg, asn, ua, path, referrer, "
            "COALESCE(is_owner,0) AS is_owner, sid, dwell_ms "
            "FROM visit_log ORDER BY ts_epoch ASC"
        ).fetchall()

    LEGACY_GAP = 1800  # 30분 — sid 없는 구방문 묶음 간격
    sess: dict = {}
    last_by_ip: dict = {}
    for r in rows:
        d = dict(r)
        sid = d.get("sid") or ""
        legacy = not sid
        if legacy:
            prev = last_by_ip.get(d["ip"])
            if prev and (d["ts_epoch"] - prev[1]) <= LEGACY_GAP:
                key = prev[0]
            else:
                key = f"legacy:{d['ip']}:{d['ts_epoch']}"
            last_by_ip[d["ip"]] = (key, d["ts_epoch"])
        else:
            key = sid
        s = sess.get(key)
        if not s:
            s = sess[key] = {
                "sid": key, "legacy": legacy, "ip": d["ip"], "country": d["country"],
                "city": d["city"], "asorg": d["asorg"], "asn": d["asn"], "ua": d["ua"],
                "is_owner": d["is_owner"], "start": d["ts_epoch"], "end": d["ts_epoch"],
                "start_ts": d["ts"], "events": [],
            }
        s["end"] = max(s["end"], d["ts_epoch"])
        for k in ("ip", "country", "city", "asorg", "asn", "ua"):
            if d[k] and not s[k]:
                s[k] = d[k]
        if d["is_owner"]:
            s["is_owner"] = 1
        s["events"].append({
            "path": d["path"], "ts": d["ts"], "ts_epoch": d["ts_epoch"],
            "referrer": d["referrer"], "dwell_ms": d["dwell_ms"],
        })

    out = []
    for s in sess.values():
        s["events"].sort(key=lambda e: e["ts_epoch"])
        s["page_count"] = len(s["events"])
        s["total_dwell_ms"] = sum(e.get("dwell_ms") or 0 for e in s["events"])
        s["duration_ms"] = int((s["end"] - s["start"]) * 1000)
        out.append(s)
    out.sort(key=lambda s: s["end"], reverse=True)

    visitor_ips = {s["ip"] for s in out if not s["is_owner"] and s["ip"]}
    return {
        "sessions": out[:limit],
        "total": len(out),
        "visitors": len(visitor_ips),
        "owner_sessions": sum(1 for s in out if s["is_owner"]),
    }
