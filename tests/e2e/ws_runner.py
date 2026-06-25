# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace E2E QA runner — drive the autonomous owner-driver loop.

The Community QA runner drove a TestUser bot over 150 turns through a second
driver bot. The Workspace needs NO second bot: the **owner-agent** is the
driver, so we drive the kernel directly. This
runner:

1. builds a fresh echo/claude_cli ``Glimi`` workspace seeded with the full team
   (Coordinator + Researcher + Builder + Critic) and a concrete test goal;
2. runs :func:`workspace.driver.drive_workspace` for N rounds (default 3,
   ``--rounds``), capturing every turn + lifecycle frame to a live log;
3. snapshots the whole in-memory store (messages / relationships / usage) to a
   JSON file so :mod:`tests.e2e.ws_verdict` can judge the run out-of-process,
   exactly like the Community analyzer reads the qa DB.

The Workspace harness is store-based, not file-DB based: the kernel harness
(``Glimi``) uses an in-memory store, so there is no SQLite file to query. We
therefore dump the store to ``ws-store-<run_id>.json`` (the runner's "DB") and
the verdict reads THAT. Prior run artifacts are backed up before each run, the
same "always back up" policy the Community runner holds.

Honors ``GLIMI_LLM_BACKEND``:
  - ``echo`` (default here) → free, deterministic, $0 — the fast self-test.
  - ``claude_cli`` → real models via the local Claude CLI (no API key). COST —
    only run via ``./scripts/ws_qa.sh``.

Usage::

    GLIMI_LLM_BACKEND=echo  python -m tests.e2e.ws_runner --rounds 2   # fast, $0
    GLIMI_LLM_BACKEND=claude_cli python -m tests.e2e.ws_runner --rounds 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"
BACKUPS_DIR = RESULTS_DIR / "ws-backups"

# Make the flat-dir Workspace app modules importable like run.py does, regardless
# of the runner's cwd (workspace/run.py is run both as a script and as a module).
_WS_DIR = PROJECT_ROOT / "glimi-workspace" / "workspace"
if str(_WS_DIR) not in sys.path:
    sys.path.insert(0, str(_WS_DIR))

# A concrete, software-ish test goal + brief — enough surface for the owner to
# advance across rounds (verify a quickstart → ship a dated plan), and for the
# verdict's "goal advanced" heuristic to see concrete artifacts emerge.
DEFAULT_GOAL = "작은 오픈소스 CLI 도구의 첫 공개 런칭 기획"
DEFAULT_CONTEXT = (
    "정직한 런칭 기조. 과장 없이 실제로 동작하는 것만 보여준다. "
    "깨끗한 환경에서 5분 안에 따라할 수 있는 퀵스타트가 핵심."
)
DEFAULT_BACKLOG = [
    "퀵스타트가 깨끗한 환경에서 실제로 통과하는지 검증",
    "README 의 핵심 차별점 한 문장 확정",
    "런칭 데모(짧은 영상/gif) 시나리오",
    "런칭일과 담당까지 박은 실행 계획",
]

# Owner display name for the run.
OWNER_NAME = "오너"
OWNER_ID = "owner"


def _backend() -> str:
    """Effective LLM backend (env GLIMI_LLM_BACKEND → echo)."""
    return os.environ.get("GLIMI_LLM_BACKEND", "echo") or "echo"


def _backup_prior_runs() -> Path | None:
    """Back up prior ws-run artifacts before a fresh run (always-backup policy).

    Moves the previous ws-run-*.json / ws-store-*.json / ws-run-*.log into a
    timestamped backups/ dir so each run starts clean but nothing is lost for
    regression comparison. Returns the backup dir, or None if nothing to back up.
    """
    if not RESULTS_DIR.exists():
        return None
    artifacts = (
        list(RESULTS_DIR.glob("ws-run-*.json"))
        + list(RESULTS_DIR.glob("ws-store-*.json"))
        + list(RESULTS_DIR.glob("ws-run-*.log"))
    )
    if not artifacts:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS_DIR / f"ws-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in artifacts:
        try:
            shutil.move(str(f), str(dest / f.name))
        except Exception:
            pass
    print(f"[WS-Runner] 이전 run 백업: {dest}")
    return dest


def _build_workspace(goal: str):
    """Construct a fresh Glimi workspace with the full team seeded.

    Mirrors run.main()'s seeding: one Glimi == one shared store, Coordinator +
    three specialists added. English A2A scaffolding (GLIMI_LANG=en) matches the
    Workspace's default; the owner-agent's echo script is language-independent.
    """
    os.environ.setdefault("GLIMI_LANG", "en")
    from glimi import Glimi
    from team import TEAM, WS_AGENT_MODEL

    g = Glimi(backend=_backend(), owner_name=OWNER_NAME, owner_id=OWNER_ID)
    for aid, name, agent_type, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type,
                    model=WS_AGENT_MODEL)
    return g


def _make_logger(log_fh):
    """An on_event sink that streams every driver frame to the live log.

    The driver emits per-turn ``{type:'text', ...}`` frames (the team's turns,
    the owner's instruction posts) and ``{type:'auto', phase, ...}`` lifecycle
    frames. We render each as a readable line, the Workspace analogue of the
    Community's system.log.
    """
    def on_event(frame: dict) -> None:
        try:
            kind = frame.get("type")
            if kind == "text":
                ch = frame.get("channel", "?")
                who = frame.get("speaker") or frame.get("speaker_id") or "?"
                txt = (frame.get("text") or "").replace("\n", " ⏎ ")
                if len(txt) > 400:
                    txt = txt[:400] + "…"
                tag = "[owner]" if frame.get("is_user") else ""
                line = f"  [{ch}] {who}{tag}: {txt}"
            elif kind == "auto":
                phase = frame.get("phase", "?")
                rnd = frame.get("round", "")
                extra = ""
                if frame.get("deliverable_preview"):
                    extra = " — " + frame["deliverable_preview"].replace("\n", " ⏎ ")
                line = f"  ⟦auto⟧ phase={phase} round={rnd}{extra}"
            else:
                line = f"  ⟦{kind}⟧ {frame}"
        except Exception as exc:  # a bad frame must never break the run
            line = f"  ⟦event-error⟧ {type(exc).__name__}: {exc}"
        print(line)
        try:
            log_fh.write(line + "\n")
            log_fh.flush()
        except Exception:
            pass
    return on_event


def _snapshot_store(g) -> dict:
    """Dump the whole in-memory store to a plain-dict snapshot for the verdict.

    Captures every channel's messages (id/speaker/message/timestamp), the
    relationship edges, and the usage records — everything ws_verdict needs to
    judge the run without re-running it.
    """
    store = g.store
    overview = store.get_channel_overview()
    channels: dict[str, list[dict]] = {}
    for ch in overview:
        name = ch["channel"]
        msgs = store.get_recent_messages(name, limit=10000)
        channels[name] = [
            {
                "id": m.get("id"),
                "speaker": m.get("speaker"),
                "message": m.get("message") or "",
                "timestamp": m.get("timestamp"),
            }
            for m in msgs
        ]

    # Relationship edges (the dashboard graph edges) via the store-driven reader.
    relationships: list[dict] = []
    try:
        from glimi.dashboard import DashboardReader
        snap = DashboardReader(store).snapshot()
        relationships = snap.get("relationships", [])
    except Exception:
        pass

    # Usage records (budget ledger) — claude/ollama log spend; echo logs nothing.
    usage: list[dict] = []
    try:
        usage = list(getattr(store, "_usage", []) or [])
    except Exception:
        usage = []

    # Agent roster (speaker_id → display name), so the verdict can map ids.
    agents: dict[str, str] = {}
    try:
        from team import LABELS
        agents = dict(LABELS)
    except Exception:
        pass

    return {
        "owner_id": OWNER_ID,
        "owner_name": OWNER_NAME,
        "agents": agents,
        "channels": channels,
        "relationships": relationships,
        "usage": usage,
    }


def run(rounds: int, run_id: str, goal: str = DEFAULT_GOAL,
        context: str = DEFAULT_CONTEXT, backlog: list | None = None) -> dict:
    """Drive a fresh workspace for ``rounds`` rounds and write the artifacts.

    Returns the runner's result envelope (backend, rounds_run, stopped_reason,
    paths to the store snapshot + log). The PASS/WARN/FAIL judgment is the
    verdict's job (run separately or via the --verdict flag).
    """
    backend = _backend()
    bl = list(backlog) if backlog is not None else list(DEFAULT_BACKLOG)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  Glimi Workspace QA — autonomous owner-driver loop")
    print("=" * 64)
    print(f"  run_id  : {run_id}")
    print(f"  backend : {backend}")
    print(f"  rounds  : {rounds}")
    print(f"  goal    : {goal}")
    print("=" * 64 + "\n")

    log_path = RESULTS_DIR / f"{run_id}.log"
    store_path = RESULTS_DIR / f"ws-store-{run_id[len('ws-run-'):] if run_id.startswith('ws-run-') else run_id}.json"
    result_path = RESULTS_DIR / f"{run_id}.json"

    g = _build_workspace(goal)
    # Each fresh echo store gets its own scripted-review counter; reset to be safe.
    try:
        import owner_agent
        owner_agent.reset_echo_state(g)
    except Exception:
        pass

    import driver

    start = time.time()
    err = None
    drive_result: dict = {}
    with open(log_path, "w", encoding="utf-8") as log_fh:
        on_event = _make_logger(log_fh)
        try:
            drive_result = asyncio.run(driver.drive_workspace(
                g,
                goal=goal,
                context=context,
                backlog=list(bl),
                owner_name=OWNER_NAME,
                max_rounds=rounds,
                round_delay=0.0,  # QA: no inter-round pause
                on_event=on_event,
            ))
        except Exception as exc:  # capture, never crash the harness
            import traceback
            err = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc()
            print(tb)
            log_fh.write("\n[WS-Runner] EXCEPTION\n" + tb + "\n")
    elapsed = time.time() - start

    snapshot = _snapshot_store(g)
    snapshot["run_id"] = run_id
    snapshot["backend"] = backend
    snapshot["goal"] = goal
    snapshot["context"] = context
    snapshot["backlog"] = list(bl)
    snapshot["drive_result"] = drive_result
    snapshot["elapsed_seconds"] = round(elapsed, 1)
    snapshot["error"] = err
    store_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    envelope = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "backend": backend,
        "rounds_requested": rounds,
        "rounds_run": drive_result.get("rounds", 0),
        "stopped_reason": drive_result.get("stopped_reason"),
        "done": drive_result.get("done", False),
        "elapsed_seconds": round(elapsed, 1),
        "error": err,
        "store_snapshot": store_path.name,
        "log": log_path.name,
    }

    print(f"\n[WS-Runner] 완료 — rounds_run={envelope['rounds_run']} "
          f"reason={envelope['stopped_reason']} ({elapsed:.1f}s)")
    print(f"[WS-Runner] 스토어 스냅샷: {store_path}")
    print(f"[WS-Runner] 로그: {log_path}")

    # Write a provisional run envelope. The verdict OVERWRITES result_path with
    # the full judged JSON (status/issues/metrics); writing it here means a
    # runner-only invocation still leaves a ws-run-*.json behind.
    result_path.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    envelope["result_path"] = str(result_path)
    envelope["store_path"] = str(store_path)
    return envelope


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Glimi Workspace QA runner")
    ap.add_argument("--rounds", type=int, default=3,
                    help="number of autonomous rounds to drive (default 3)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip backing up prior run artifacts")
    ap.add_argument("--no-verdict", action="store_true",
                    help="skip running the verdict after the run")
    ap.add_argument("--report", action="store_true",
                    help="emit a presentable portfolio report (Markdown + metrics JSON) "
                         "after the run — quality judge runs only on a real backend")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)write tests/e2e/ws-baseline.json from this run's metrics "
                         "(implies --report)")
    ap.add_argument("--goal", default=DEFAULT_GOAL,
                    help="the owner's project goal to drive (default: CLI-launch demo goal)")
    ap.add_argument("--context", default="",
                    help="optional owner context/brief; ignored unless --goal is custom")
    args = ap.parse_args(argv)

    if not args.no_backup:
        _backup_prior_runs()

    # Default goal keeps its hand-tuned context/backlog; a custom --goal drives from
    # the goal (+ optional --context) alone so launch-specific brief doesn't mislead.
    if args.goal == DEFAULT_GOAL:
        _ctx, _bl = DEFAULT_CONTEXT, list(DEFAULT_BACKLOG)
    else:
        _ctx, _bl = (args.context or ""), []

    run_id = f"ws-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    envelope = run(max(1, args.rounds), run_id, args.goal, _ctx, _bl)

    status = "?"
    if not args.no_verdict:
        try:
            from tests.e2e import ws_verdict
            verdict = ws_verdict.judge_run(run_id)
            print("\n[WS-Runner] 판정:")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            status = verdict.get("status", "?")
            emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "?")
            print(f"\n{emoji} {status}")
        except Exception as exc:
            import traceback
            print(f"[WS-Runner] 판정 실패 (run 자체는 완료): {exc}")
            print(traceback.format_exc())

    # Portfolio report (Markdown + metrics JSON) — judge runs only on a real backend.
    if args.report or args.write_baseline:
        try:
            from tests.e2e import ws_report
            snap = json.loads(Path(envelope["store_path"]).read_text(encoding="utf-8"))
            out = ws_report.generate_from_snapshot(
                snap, run_id=run_id, write_baseline=args.write_baseline,
            )
            q = out["quality"]
            qs = (f"{q.get('overall')}/10 ({'pass' if q.get('pass') else 'fail'})"
                  if q.get("status") == "scored" else f"{q.get('status')}")
            print(f"\n[WS-Runner] 리포트 — quality: {qs}  "
                  f"overall: {'PASS' if out['metrics']['pass_criteria']['overall_ok'] else 'FAIL'}")
            print(f"[WS-Runner] 리포트(MD): {out['report_paths']['md']}")
            print(f"[WS-Runner] 메트릭(JSON): {out['report_paths']['json']}")
            if out["report_paths"].get("baseline"):
                print(f"[WS-Runner] 베이스라인 갱신: {out['report_paths']['baseline']}")
        except Exception as exc:
            import traceback
            print(f"[WS-Runner] 리포트 실패 (run/판정은 완료): {exc}")
            print(traceback.format_exc())

    if not args.no_verdict:
        # Non-zero exit on hard FAIL so CI / tmux surfaces it.
        return 0 if status in ("PASS", "WARN") else 1
    return 0 if not envelope.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
