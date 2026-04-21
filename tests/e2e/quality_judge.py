"""QA Quality Judge — Haiku 로 대화 품질을 주기적으로 평가하는 백그라운드 감시자.

현 Sonnet watchdog 과 별개 역할:
- watchdog: 하드 실패 (크래시·tool 폭주·무활동) 감지 → ABORT
- judge:    대화 품질 (메타 drift / persona 이탈 / 흐름 단절) 평가 → 권고 기록

사용:
  python -m tests.e2e.quality_judge [--interval 600] [--window-min 15]

출력: /tmp/qa_quality.jsonl (한 줄 per tick).
심각(critical) 3회 연속 시 /tmp/qa_quality_abort 파일 생성 — watchdog 이 보면 stop 결정.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "communities" / "qa" / "community.db"
OUT_LOG = Path("/tmp/qa_quality.jsonl")
ABORT_FLAG = Path("/tmp/qa_quality_abort")
MODEL = "claude-haiku-4-5"


JUDGE_PROMPT = """너는 AI persona 대화 시뮬레이션의 품질 평가자야.
다음 최근 대화 기록을 보고 채점해. 평가 기준:

1. **persona 몰입 유지**: 에이전트들이 자연스러운 "사람" 으로 느껴지는가? 3인칭 서술/storyteller 모드/assistant 응대 톤 있나?
2. **메타 드리프트**: "난 AI", "에이전트", "캐릭터", "시뮬레이션", "대화가 끝났네요" 같은 메타 용어 유출?
3. **흐름 자연스러움**: 갑자기 맥락 없는 화제 / 이전 대화와 단절 / 반복 순환?
4. **오너 hijack**: persona 가 오너의 대사·행동·내심을 대신 서술?
5. **유나(mgr) 적절성**: 유나가 과도하게 개입하거나 같은 말 반복?

**엄격하게 JSON 만 출력**. 코멘트·설명·markdown 금지:
{"severity": "ok|warn|critical",
 "score": 0-10,
 "issues": [{"category": "meta_drift|storyteller|hijack|flow|yuna_over", "detail": "간단 설명", "example": "원문 인용 30자"}],
 "summary": "한 줄 총평"}

severity 기준:
- ok (8-10): 자연스러움. issue 0-1.
- warn (5-7): drift 시작. issue 1-3.
- critical (0-4): QA 의미 없음 수준. issue 3+.

대화 기록:
"""


def fetch_recent_convos(window_minutes: int = 15, limit: int = 50) -> list[dict]:
    """DB 의 timestamp 는 로컬 시간이지만 KST 봇과 UTC claude 세션이 섞일 가능성.
    window 를 넘치게 잡고 limit 에 의존."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT channel, speaker, message, timestamp FROM conversations "
        "ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def _resolve_name(agent_id: str) -> str:
    if not agent_id or not agent_id.startswith("agent-"):
        return agent_id or "?"
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
        return row[0] if row else agent_id
    finally:
        conn.close()


def format_convo(msgs: list[dict]) -> str:
    lines = []
    for m in msgs:
        speaker = _resolve_name(m["speaker"])
        ch = m["channel"]
        txt = (m["message"] or "")[:180].replace("\n", " ")
        lines.append(f"[{ch}] {speaker}: {txt}")
    return "\n".join(lines)


def call_haiku(prompt: str, timeout: int = 40) -> str:
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text", "--model", MODEL],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        return f"__ERROR__ {type(e).__name__}: {e}"


def extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    # JSON object 찾기 — LLM 이 코멘트 붙이는 경우 대비
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start:end+1])
    except Exception:
        return None


def judge_once(window_min: int) -> dict:
    msgs = fetch_recent_convos(window_minutes=window_min, limit=50)
    if not msgs:
        return {"ts": datetime.now().isoformat(timespec="seconds"),
                "severity": "ok", "score": None, "issues": [],
                "summary": f"최근 {window_min}분 내 대화 없음"}
    convo = format_convo(msgs)
    raw = call_haiku(JUDGE_PROMPT + convo)
    data = extract_json(raw) or {}
    verdict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "msg_count": len(msgs),
        "severity": data.get("severity", "ok"),
        "score": data.get("score"),
        "issues": data.get("issues", []),
        "summary": data.get("summary", ""),
        "raw_len": len(raw),
    }
    if raw.startswith("__ERROR__"):
        verdict["severity"] = "ok"  # 판정 실패는 warn 로 취급 X (noise)
        verdict["summary"] = f"judge failed: {raw[:80]}"
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=600, help="초 단위 주기 (기본 10분)")
    ap.add_argument("--window-min", type=int, default=15, help="평가 윈도우 (분)")
    ap.add_argument("--max-ticks", type=int, default=0, help="최대 tick 수 (0=무한)")
    args = ap.parse_args()

    consecutive_critical = 0
    tick = 0
    while True:
        tick += 1
        try:
            verdict = judge_once(args.window_min)
        except Exception as e:
            verdict = {"ts": datetime.now().isoformat(timespec="seconds"),
                       "severity": "ok", "summary": f"tick error: {e}"}
        with open(OUT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(verdict, ensure_ascii=False) + "\n")
        # critical 3회 연속 → abort flag
        if verdict.get("severity") == "critical":
            consecutive_critical += 1
            if consecutive_critical >= 3 and not ABORT_FLAG.exists():
                ABORT_FLAG.write_text(
                    json.dumps({
                        "triggered_at": verdict["ts"],
                        "reason": "quality judge 3회 연속 critical",
                        "last_verdict": verdict,
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        else:
            consecutive_critical = 0
        print(f"[judge #{tick}] {verdict.get('severity')} score={verdict.get('score')} "
              f"msgs={verdict.get('msg_count')} — {verdict.get('summary', '')[:80]}",
              flush=True)
        if args.max_ticks and tick >= args.max_ticks:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
