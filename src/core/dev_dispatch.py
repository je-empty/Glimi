"""Dev dispatch — Claude Code (Opus) subprocess + auto-commit/push.

Called by the dev manager (세나) via `dev_dispatch_fix` tool when a bug fix is
HIGH-confidence (small, well-isolated). Spawns a `claude` CLI subprocess with the
task brief, lets Claude Code edit files inside the project, then commits + pushes
the result.

Safety guardrails:
  - Only operates inside the project root (never touches paths outside).
  - Commits with a structured message linking the dev_requests row.
  - If subprocess exits with non-zero status, marks request as failed (no partial commit).
  - Hard timeout — 600s (Opus may need to read multiple files + edit).
  - Auto-push only if `dev_config.auto_push` is true (defaults true via seed).

Returns dict: {ok, commit_sha?, files_changed?, summary?, error?}.
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import subprocess
from pathlib import Path
from typing import Optional

from src import log_writer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPUS_MODEL = "claude-opus-4-7"
DISPATCH_TIMEOUT_SEC = 600  # 10 min


def _build_prompt(request_id: int, task_brief: str, files_hint: list, payload: dict) -> str:
    """Claude Code 에 전달할 단일 prompt 구성. payload 는 원래 request 의 JSON dict."""
    payload_json = _json.dumps(payload.get("payload_json") or {}, ensure_ascii=False, indent=2) \
        if isinstance(payload.get("payload_json"), dict) else (payload.get("payload_json") or "")
    if not payload_json or payload_json == "{}":
        # raw JSON string from DB
        payload_json = payload.get("payload_json", "{}")
    files_str = ", ".join(files_hint) if files_hint else "(none — explore as needed)"
    return f"""You are operating as the Glimi dev assistant for request #{request_id}.

ORIGINAL REPORT (JSON):
{payload_json}

TASK BRIEF (from dev manager):
{task_brief}

FILES HINT: {files_str}

INSTRUCTIONS:
1. Read the relevant code (use Read / Grep / Bash tools as needed).
2. Make the minimal change that fixes the reported issue. Do NOT refactor unrelated code.
3. Stay within {{1, 2, 3}} files. If your change requires more, STOP and reply with
   `<<DISPATCH_ABORT>>: <reason>` so the dev manager can escalate to human review.
4. Do NOT modify: .env, secrets, anything in analysis/, db schema migrations.
5. After editing, output a JSON summary on the LAST line:
   `<<DISPATCH_RESULT>>: {{"summary": "<1-2 line plain-English summary>", "files_changed": ["..."]}}`
6. Do NOT run git commit / push yourself — the runner handles that.

Begin.
"""


async def run_claude_code_fix(
    request_id: int,
    task_brief: str,
    files_hint: list,
    payload: dict,
) -> dict:
    """Spawn Claude Code subprocess + parse result + commit/push if successful.

    Returns the result dict the dev_dispatch_fix tool handler stores in dev_requests.
    """
    prompt = _build_prompt(request_id, task_brief, files_hint, payload)

    log_writer.system(f"[dev] dispatch #{request_id} → Claude Code (Opus)")

    # subprocess.run in executor (don't block event loop).
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["claude", "-p", prompt, "--model", OPUS_MODEL, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=DISPATCH_TIMEOUT_SEC,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            ),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Claude Code timeout after {DISPATCH_TIMEOUT_SEC}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found in PATH"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    if result.returncode != 0:
        return {"ok": False, "error": f"Claude Code exit {result.returncode}: {result.stderr[:300]}"}

    out = result.stdout.strip()

    # ABORT detection
    if "<<DISPATCH_ABORT>>" in out:
        reason_line = next((l for l in out.splitlines() if "<<DISPATCH_ABORT>>" in l), "")
        return {"ok": False, "error": f"abort by dispatcher: {reason_line[:200]}"}

    # Result parse
    summary = ""
    files_changed: list[str] = []
    for line in reversed(out.splitlines()):
        if "<<DISPATCH_RESULT>>" in line:
            try:
                json_part = line.split("<<DISPATCH_RESULT>>", 1)[1].lstrip(": \t")
                parsed = _json.loads(json_part)
                summary = parsed.get("summary", "")
                files_changed = parsed.get("files_changed", []) or []
            except Exception as e:
                log_writer.system(f"[dev] dispatch result parse 실패: {e}")
            break

    # Verify there are actual changes via git status
    git_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if git_status.returncode != 0:
        return {"ok": False, "error": f"git status failed: {git_status.stderr[:200]}"}
    if not git_status.stdout.strip():
        return {"ok": False, "error": "no file changes after dispatch (Claude Code may have refused)"}

    # Auto-commit
    commit_msg = f"dev: auto-fix #{request_id}"
    if summary:
        commit_msg = f"dev: auto-fix #{request_id} — {summary[:120]}"
    add = subprocess.run(["git", "add", "-A"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if add.returncode != 0:
        return {"ok": False, "error": f"git add failed: {add.stderr[:200]}"}
    commit = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if commit.returncode != 0:
        return {"ok": False, "error": f"git commit failed: {commit.stderr[:200]}"}

    # SHA fetch
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    commit_sha = sha_result.stdout.strip()[:12] if sha_result.returncode == 0 else "?"

    # Auto-push (best-effort — failure here is reported but doesn't fail the dispatch)
    push_ok = True
    push_err = ""
    push_result = subprocess.run(
        ["git", "push"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120,
    )
    if push_result.returncode != 0:
        push_ok = False
        push_err = push_result.stderr[:200]

    log_writer.system(
        f"[dev] dispatch #{request_id} 완료 — commit {commit_sha}, push={'ok' if push_ok else 'fail'}"
    )
    return {
        "ok": True,
        "commit_sha": commit_sha,
        "summary": summary,
        "files_changed": files_changed,
        "push_ok": push_ok,
        "push_err": push_err,
    }


__all__ = ["run_claude_code_fix"]
