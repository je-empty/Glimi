"""QA 런 전/후 Claude 사용량 스냅샷 + 델타 기록.

사용:
  # 런 직전
  python -m tests.e2e.capture_usage snapshot > /tmp/usage_before.json

  # 런 직후
  python -m tests.e2e.capture_usage diff /tmp/usage_before.json --run-id run-xxxxx

델타는 `tests/e2e/results/token_usage.md` 에 append.

데이터 소스: `~/.claude/telemetry/*.json` 의 tengu_exit 이벤트.
Claude Code CLI 세션이 끝날 때마다 파일이 flush 되므로 런 중 snapshot→diff 가능.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from community.core.monitor import get_usage_stats  # noqa: E402

USAGE_LOG = PROJECT_ROOT / "tests" / "e2e" / "results" / "token_usage.md"


def snapshot() -> dict:
    """현재 누적 사용량 스냅샷."""
    s = get_usage_stats()
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "cost_total_usd": s.get("cost_total_usd", 0),
        "sessions_total": s.get("sessions_total", 0),
        "tokens_input": s.get("tokens_input", 0),
        "tokens_output": s.get("tokens_output", 0),
        "tokens_cache_read": s.get("tokens_cache_read", 0),
        "tokens_cache_write": s.get("tokens_cache_write", 0),
        "by_model": s.get("by_model", {}),
    }


def _diff(before: dict, after: dict) -> dict:
    d = {}
    for k in ("cost_total_usd", "sessions_total", "tokens_input",
             "tokens_output", "tokens_cache_read", "tokens_cache_write"):
        d[k] = (after.get(k, 0) or 0) - (before.get(k, 0) or 0)
    # by_model delta
    by_model_b = before.get("by_model") or {}
    by_model_a = after.get("by_model") or {}
    d["by_model"] = {
        m: (by_model_a.get(m, 0) - by_model_b.get(m, 0))
        for m in set(by_model_b) | set(by_model_a)
        if (by_model_a.get(m, 0) - by_model_b.get(m, 0)) != 0
    }
    return d


def _ensure_log_header():
    if USAGE_LOG.exists():
        return
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    USAGE_LOG.write_text(
        "# QA 런 토큰 사용량 누적 로그\n"
        "\n"
        "매 QA 런마다 한 줄씩 append. 평균/추세 참고용.\n"
        "\n"
        "**데이터 소스 2 종**:\n"
        "- `telemetry_*` 컬럼: `~/.claude/telemetry/` tengu_exit 이벤트 델타. 세션 종료 시에만 flush → 봇이 subprocess 로 `claude -p` 호출하는 패턴에선 실시간 반영 안 됨. 0으로 나올 수 있음.\n"
        "- `cli_calls_*` 컬럼: 런 중 system.log 에 찍힌 `Claude CLI 호출 (model)` 라인 카운트. 실제 봇 호출수의 정확한 근사. 평균 낼 때 이 값 사용 추천.\n"
        "\n"
        "| run_id | start | elapsed | status | cli_sonnet | cli_haiku | cli_opus | msgs_total | tel_in | tel_out | tel_cache_r | tel_cost |\n"
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|\n",
        encoding="utf-8",
    )


def _count_cli_calls(run_id: str) -> dict:
    """백업된 런의 system.log 에서 모델별 CLI 호출 수 집계."""
    import re
    log_path = PROJECT_ROOT / "communities" / "qa" / "backups" / run_id / "logs" / "system.log"
    if not log_path.exists():
        log_path = PROJECT_ROOT / "communities" / "qa" / "logs" / "system.log"
    if not log_path.exists():
        return {"sonnet": 0, "haiku": 0, "opus": 0}
    pat = re.compile(r"Claude CLI 호출 \(([^)]+)\)")
    counts = {"sonnet": 0, "haiku": 0, "opus": 0}
    try:
        for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = pat.search(line)
            if not m:
                continue
            model = m.group(1).lower()
            if "sonnet" in model:
                counts["sonnet"] += 1
            elif "haiku" in model:
                counts["haiku"] += 1
            elif "opus" in model:
                counts["opus"] += 1
    except Exception:
        pass
    return counts


def _count_msgs(run_id: str) -> int:
    """run-*.json 의 msgs_total."""
    p = PROJECT_ROOT / "tests" / "e2e" / "results" / f"{run_id}.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("metrics", {}).get("msgs_total", 0)
    except Exception:
        return 0


def _fmt_int(n: int) -> str:
    return f"{int(n):,}"


def _append_row(run_id: str, before: dict, delta: dict, meta: dict):
    _ensure_log_header()
    cli = _count_cli_calls(run_id)
    msgs = _count_msgs(run_id)
    row = (
        f"| {run_id} "
        f"| {before['ts'][:19]} "
        f"| {meta.get('elapsed', 0):.0f} "
        f"| {meta.get('status', '?')} "
        f"| {cli['sonnet']} "
        f"| {cli['haiku']} "
        f"| {cli['opus']} "
        f"| {msgs} "
        f"| {_fmt_int(delta['tokens_input'])} "
        f"| {_fmt_int(delta['tokens_output'])} "
        f"| {_fmt_int(delta['tokens_cache_read'])} "
        f"| {delta['cost_total_usd']:.4f} |\n"
    )
    with open(USAGE_LOG, "a", encoding="utf-8") as f:
        f.write(row)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    d = sub.add_parser("diff")
    d.add_argument("before", help="snapshot JSON 경로")
    d.add_argument("--run-id", required=True)
    d.add_argument("--elapsed", type=float, default=0)
    d.add_argument("--status", default="?")
    args = ap.parse_args()

    if args.cmd == "snapshot":
        json.dump(snapshot(), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if args.cmd == "diff":
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        after = snapshot()
        delta = _diff(before, after)
        _append_row(args.run_id, before, delta,
                    {"elapsed": args.elapsed, "status": args.status})
        json.dump(delta, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        print(f"[usage] appended to {USAGE_LOG.relative_to(PROJECT_ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
