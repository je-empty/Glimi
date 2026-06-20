"""/admin/dev-requests — 글로벌 admin 페이지 백엔드 API.

admin role 만 접근 가능 (require_admin). dev_requests / dev_runs 는 platform.db 글로벌
테이블이라 community 격리 없음 — 모든 요청을 한 곳에서 통합 관리.

Endpoints:
  GET  /api/admin/dev-requests              — list (필터: community/status/severity)
  GET  /api/admin/dev-requests/{id}         — detail
  POST /api/admin/dev-requests/{id}/approve — analyzed → approved
  POST /api/admin/dev-requests/{id}/reject  — analyzed/needs_human_review → rejected
  POST /api/admin/dev-requests/run          — approved 일괄 → tmux dispatch
  GET  /api/admin/dev-requests/run/active   — 현재 active run 메타
  GET  /api/admin/dev-requests/run/{run_id}/live — 라이브 출력 stream (since byte)
  POST /api/admin/dev-requests/run/{run_id}/abort — 강제 abort (tmux kill)
  POST /api/admin/dev-requests/{id}/merge   — PR merge + bot 재가동 (현재는 단순 트리거)
  GET  /api/admin/dev-requests/communities  — 필터 칩용 distinct community list
"""
from __future__ import annotations

import json as _json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..auth import require_admin


router = APIRouter()


# ── List + detail ──────────────────────────────────────────

@router.get("/api/admin/dev-requests")
async def list_dev_requests(
    community: Optional[str] = None,
    status: Optional[str] = None,        # comma-separated
    severity: Optional[str] = None,
    limit: int = Query(default=200, le=500),
    user: dict = Depends(require_admin),
):
    from community.core import dev_agent
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()] or None
    rows = dev_agent.list_requests(
        community_id=community, statuses=statuses, limit=limit,
    )
    if severity:
        sev_set = {s.strip() for s in severity.split(",") if s.strip()}
        rows = [r for r in rows if (r.get("severity") or "") in sev_set]
    # payload_json 을 dict 로 풀어서 클라이언트가 다시 파싱 안 해도 되게.
    for r in rows:
        try:
            r["payload"] = _json.loads(r.get("payload_json") or "{}")
        except Exception:
            r["payload"] = {}
        try:
            r["files_hint_list"] = _json.loads(r.get("files_hint") or "[]") or []
        except Exception:
            r["files_hint_list"] = []
        try:
            r["result"] = _json.loads(r.get("result_json") or "{}") if r.get("result_json") else None
        except Exception:
            r["result"] = None
    return JSONResponse({"items": rows, "count": len(rows)})


@router.get("/api/admin/dev-requests/communities")
async def distinct_communities(user: dict = Depends(require_admin)):
    from community.core import dev_agent
    conn = dev_agent._platform_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT community_id FROM dev_requests ORDER BY community_id"
        ).fetchall()
    finally:
        conn.close()
    return JSONResponse({"items": [r[0] for r in rows]})


@router.get("/api/admin/dev-requests/{request_id}")
async def get_dev_request(request_id: int, user: dict = Depends(require_admin)):
    from community.core import dev_agent
    r = dev_agent.get_request(request_id)
    if not r:
        raise HTTPException(404, f"request #{request_id} not found")
    try:
        r["payload"] = _json.loads(r.get("payload_json") or "{}")
    except Exception:
        r["payload"] = {}
    try:
        r["files_hint_list"] = _json.loads(r.get("files_hint") or "[]") or []
    except Exception:
        r["files_hint_list"] = []
    try:
        r["result"] = _json.loads(r.get("result_json") or "{}") if r.get("result_json") else None
    except Exception:
        r["result"] = None
    return JSONResponse(r)


# ── Approve / reject ───────────────────────────────────────

@router.post("/api/admin/dev-requests/{request_id}/approve")
async def approve_dev_request(request_id: int, user: dict = Depends(require_admin)):
    from community.core import dev_agent
    r = dev_agent.get_request(request_id)
    if not r:
        raise HTTPException(404, "not found")
    if r["status"] not in ("analyzed", "needs_human_review"):
        raise HTTPException(400, f"cannot approve from status {r['status']}")
    dev_agent.mark_approved(request_id, str(user.get("id") or user.get("username") or "admin"))
    return JSONResponse({"ok": True, "status": "approved"})


@router.post("/api/admin/dev-requests/{request_id}/reject")
async def reject_dev_request(request_id: int, user: dict = Depends(require_admin)):
    from community.core import dev_agent
    r = dev_agent.get_request(request_id)
    if not r:
        raise HTTPException(404, "not found")
    if r["status"] in ("processing", "queued"):
        raise HTTPException(400, f"cannot reject while {r['status']}")
    dev_agent.mark_rejected(request_id, str(user.get("id") or user.get("username") or "admin"))
    return JSONResponse({"ok": True, "status": "rejected"})


# ── Run all approved ───────────────────────────────────────

class _RunRequest:
    """body: {request_ids?: [int]}"""
    pass


@router.post("/api/admin/dev-requests/run")
async def run_dev_requests(request: Request, user: dict = Depends(require_admin)):
    """approved 항목들 일괄 dispatch. body.request_ids 지정 안 하면 전부 approved 항목."""
    from community.core import dev_agent, dev_runner

    body_bytes = await request.body()
    try:
        body = _json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        body = {}
    request_ids = body.get("request_ids") or []

    if not request_ids:
        approved = dev_agent.list_requests(statuses=["approved"], limit=500)
        request_ids = [r["id"] for r in approved]

    if not request_ids:
        raise HTTPException(400, "no approved requests to run")

    # 동시 1개 run 만
    if dev_agent.get_active_run():
        raise HTTPException(409, "another dev run is already in progress")

    started_by = str(user.get("id") or user.get("username") or "admin")
    result = dev_runner.start_dev_run(request_ids, started_by)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "dispatch failed"))
    return JSONResponse(result)


@router.get("/api/admin/dev-requests/run/active")
async def get_active_run(user: dict = Depends(require_admin)):
    from community.core import dev_agent
    run = dev_agent.get_active_run()
    if not run:
        return JSONResponse({"active": None})
    return JSONResponse({"active": run})


@router.get("/api/admin/dev-requests/run/{run_id}/live")
async def stream_run_output(
    run_id: int,
    since: int = Query(default=0, ge=0),
    user: dict = Depends(require_admin),
):
    from community.core import dev_agent, dev_runner
    run = dev_agent.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    log_path = run.get("log_path")
    if not log_path:
        return JSONResponse({"bytes_read": 0, "next_byte": since, "content": "", "finished": True})
    out = dev_runner.tail_log(log_path, since_byte=since)
    out["status"] = run.get("status")
    return JSONResponse(out)


@router.post("/api/admin/dev-requests/run/{run_id}/abort")
async def abort_run(run_id: int, user: dict = Depends(require_admin)):
    from community.core import dev_agent, dev_runner
    run = dev_agent.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if run["status"] not in ("starting", "running"):
        raise HTTPException(400, f"cannot abort run with status {run['status']}")
    killed = dev_runner.kill_tmux_session()
    dev_agent.update_run_status(run_id, "aborted", error="aborted by admin")
    return JSONResponse({"ok": True, "killed": killed})


@router.get("/api/admin/dev-requests/runs")
async def list_runs(limit: int = Query(default=30, le=100),
                    user: dict = Depends(require_admin)):
    from community.core import dev_agent
    return JSONResponse({"items": dev_agent.list_runs(limit=limit)})


# ── PR merge ───────────────────────────────────────────────

@router.post("/api/admin/dev-requests/run/{run_id}/merge")
async def merge_run_pr(run_id: int, user: dict = Depends(require_admin)):
    """Run 의 PR 을 develop 으로 merge + bot 재가동.

    현재 구현: gh pr merge 호출. 실패 시 admin 이 GitHub 에서 직접 merge 권장.
    """
    from community.core import dev_agent
    import subprocess
    run = dev_agent.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if run["status"] != "completed":
        raise HTTPException(400, f"run status is {run['status']}, not completed")
    pr_url = run.get("pr_url")
    if not pr_url:
        raise HTTPException(400, "no PR URL on this run")

    # gh pr merge — squash merge default
    proc = subprocess.run(
        ["gh", "pr", "merge", pr_url, "--squash", "--delete-branch"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"gh pr merge failed: {proc.stderr[:300]}")
    # mark all completed requests of this run as pr_merged
    requests = dev_agent.list_requests(limit=500)
    for r in requests:
        if r.get("run_id") == run_id and r.get("status") == "completed":
            dev_agent.mark_pr_merged(r["id"])
    dev_agent.update_run_status(run_id, "completed", pr_merged_at=dev_agent._now_iso())
    return JSONResponse({"ok": True, "merged": True, "pr_url": pr_url})
