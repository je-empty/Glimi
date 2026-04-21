"""QA 런 구조화 분석 — Claude (Opus) 가 raw 로그 안 읽게 하려고 모든 체크를 스크립트에서 끝내고
결과를 compact JSON 으로 출력. 이걸로 Claude 입력 토큰 ~60% 절감 예상.

사용:
  python -m tests.e2e.analyze_run              # 최신 런
  python -m tests.e2e.analyze_run run-YYYYMMDD-HHMMSS
  python -m tests.e2e.analyze_run --pretty     # 사람 읽기용 포맷

출력 스키마 (대략):
{
  "run_id": "...",
  "status": "PASS|WARN|FAIL",
  "elapsed_seconds": 1800,
  "verdict": "one-line summary",
  "issues": [{"severity": "BLOCKER|REGRESSION|DRIFT|FLAKY|COSMETIC",
              "category": "meta_leak|error|spam|...",
              "detail": "...",
              "evidence": "..."}],
  "metrics": {
    "msgs_total": 598,
    "errors": {...},
    "meta": {...},
    "yuna_activity": {...},
    "persona_quality": [{...}],
    "achievements": [...],
    "channels": {...},
    "memory_health": {...}
  }
}
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"
BACKUPS_DIR = PROJECT_ROOT / "communities" / "qa" / "backups"
LIVE_DB = PROJECT_ROOT / "communities" / "qa" / "community.db"
LIVE_LOGS = PROJECT_ROOT / "communities" / "qa" / "logs"


# ── 위치 해결 ────────────────────────────────────────────

def _resolve_run_id(arg: str | None) -> str:
    if arg:
        return arg
    jsons = sorted(RESULTS_DIR.glob("run-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        sys.exit("no run-*.json in tests/e2e/results/")
    return jsons[0].stem


def _resolve_sources(run_id: str) -> tuple[Path | None, Path | None, Path | None]:
    """run JSON, system.log, DB 경로 찾기. backup 이 있으면 backup 우선."""
    backup_dir = BACKUPS_DIR / run_id
    if backup_dir.exists():
        json_p = backup_dir / f"{run_id}.json"
        log_p = backup_dir / "logs" / "system.log"
        db_p = backup_dir / "community.db"
        return (json_p if json_p.exists() else None,
                log_p if log_p.exists() else None,
                db_p if db_p.exists() else None)
    # 백업 없으면 live 데이터 (최신 런 한정)
    json_p = RESULTS_DIR / f"{run_id}.json"
    log_p = LIVE_LOGS / "system.log"
    return (json_p if json_p.exists() else None,
            log_p if log_p.exists() else None,
            LIVE_DB if LIVE_DB.exists() else None)


# ── 체크 함수들 ─────────────────────────────────────────

def _analyze_errors(log_text: str) -> dict:
    """로그의 에러/경고 카운트."""
    patterns = {
        "cli_timeout": r"timed out after \d+ seconds",
        "tool_fail": r"\[Tool\] ✗",
        "a2a_error": r"에이전트간 대화 오류",
        "a2a_retry": r"⚠ A2A retry",
        "python_exception": r"Traceback|TypeError|NameError|KeyError|AttributeError|ValueError",
        "bot_crash": r"봇 즉시 종료|봇 준비 타임아웃",
        "streaming_cap": r"응답 10건 도달",
        "image_missing": r"\[이미지\] 파일 못 찾음",
    }
    out = {}
    for name, pat in patterns.items():
        matches = re.findall(pat, log_text)
        if matches:
            out[name] = len(matches)
    return out


def _analyze_meta(conn: sqlite3.Connection) -> dict:
    """persona 발화에서 메타 키워드 발견 (hard filter 이미 drop 했으면 0 — 뚫린 경우만 남음)."""
    out = {"leaks_in_db": [], "self_awareness_locks": [], "filter_drops_logged": 0}
    try:
        rows = conn.execute(
            "SELECT channel, speaker, substr(message,1,180) AS snippet, timestamp "
            "FROM conversations WHERE speaker LIKE 'agent-persona-%' "
            "AND (message LIKE '%에이전트%' OR message LIKE '%페르소나%' OR message LIKE '%시뮬레이션%' "
            "OR message LIKE '%AI%' OR message LIKE '%시스템 만%' OR message LIKE '%시스템 속%' "
            "OR message LIKE '%설계된%' OR message LIKE '%프롬프트%' OR message LIKE '%예측 가능%' "
            "OR message LIKE '%뭘 하는 곳%')"
        ).fetchall()
        out["leaks_in_db"] = [{"ch": r[0], "speaker": r[1], "snippet": r[2], "ts": r[3]} for r in rows]

        rows = conn.execute(
            "SELECT id, name, meta_breached_at FROM agents "
            "WHERE type='persona' AND meta_breached_at IS NOT NULL"
        ).fetchall()
        out["self_awareness_locks"] = [{"id": r[0], "name": r[1], "at": r[2]} for r in rows]
    except Exception as e:
        out["error"] = str(e)
    return out


def _analyze_yuna(log_text: str, conn: sqlite3.Connection) -> dict:
    """유나 호출 빈도 + 독백 누출 + 시스템 에러 발화 노출."""
    out = {}
    out["cli_calls"] = len(re.findall(r"\[agent-mgr-001\].*Claude CLI 호출", log_text))
    out["watcher_ticks"] = log_text.count("[자동알림]")
    try:
        rows = conn.execute(
            "SELECT substr(message,1,120) FROM conversations "
            "WHERE speaker='agent-mgr-001' AND (message LIKE '(%)' OR message LIKE '*(%)*')"
        ).fetchall()
        out["monologue_leaks"] = [r[0] for r in rows]
    except Exception:
        out["monologue_leaks"] = []
    # 시스템 에러 태그 유저 채널 노출 — 구조화 태그 [not_found] / [tool_error] / [ERROR] 만 검사.
    # (한글 말투 문자열 패턴 매칭은 스파게티 되므로 flat 태그 기반으로 통일.)
    try:
        rows = conn.execute(
            "SELECT substr(message,1,120) FROM conversations "
            "WHERE speaker LIKE 'agent-%' AND ("
            "  message LIKE '%[not_found]%' OR "
            "  message LIKE '%[tool_error]%' OR "
            "  message LIKE '%[ERROR]%' OR "
            "  message LIKE '%Traceback%'"
            ")"
        ).fetchall()
        out["system_error_leaks"] = [r[0] for r in rows]
    except Exception:
        out["system_error_leaks"] = []
    return out


def _analyze_create_room(log_text: str) -> dict:
    return {
        "created": len(re.findall(r"\[유나CMD\] 톡방 생성:", log_text)),
        "skip_existing": log_text.count("[create_room] 이미 존재"),
        "already_exists_spam_to_user": log_text.count("이미 있어:"),  # 유저 노출 케이스 (0 이어야 정상)
    }


def _analyze_persona_quality(conn: sqlite3.Connection) -> list[dict]:
    """persona 별 7 품질 체크."""
    try:
        agents = conn.execute(
            "SELECT id, name, meta_breached_at FROM agents WHERE type='persona'"
        ).fetchall()
    except Exception:
        return []
    results = []
    for a in agents:
        aid, name, breached = a[0], a[1], a[2]
        try:
            msgs = conn.execute(
                "SELECT message FROM conversations WHERE speaker=? AND length(message) > 0",
                (aid,),
            ).fetchall()
        except Exception:
            msgs = []
        if not msgs:
            continue
        msgs = [m[0] for m in msgs]
        n = len(msgs)
        avg_len = sum(len(m) for m in msgs) / n
        casual = sum(1 for m in msgs if "ㅋㅋ" in m or "ㅎㅎ" in m or "~" in m)
        questions = sum(1 for m in msgs if "?" in m or "뭐" in m or "어때" in m)
        tools = sum(1 for m in msgs if "<tools>" in m.lower() or "<call" in m.lower())
        # 반복 — 같은 첫 10자가 3회 이상
        prefixes = Counter(m[:10] for m in msgs if len(m) >= 10)
        repeats = sum(1 for _, c in prefixes.most_common(3) if c >= 3)
        # threshold — 내향형 persona (INFJ/INFP/INTJ 등) 는 casual/질문 비율 자연히 낮음.
        # 체크 기준은 "외향형 평균" 이 아니라 "치명적 문제 없음" 수준으로 관대하게.
        checks = {
            "casual_tone": casual / n >= 0.15,          # ㅋㅋ/~/ㅎㅎ — 최소한의 구어체
            "questions_ratio": questions / n >= 0.08,   # 되묻기 최소한
            "no_tools": tools == 0,                     # 도구 안 건드림 (엄격 — persona 권한 없음)
            "length_ok": avg_len <= 80,                 # 평균 발화 길이 (카톡 기준 넉넉하게)
            "no_repeats": repeats <= 1,                 # 반복 1회까진 허용 (LLM drift)
            "not_locked": breached is None,             # 메타 안 깨짐 (엄격)
            "has_msgs": n >= 3,                         # 최소 발화량
        }
        score = sum(1 for v in checks.values() if v)
        results.append({
            "name": name,
            "agent_id": aid,
            "score": f"{score}/7",
            "msgs": n,
            "avg_len": round(avg_len, 1),
            "locked": breached is not None,
            "failed_checks": [k for k, v in checks.items() if not v],
        })
    return results


def _analyze_channels(conn: sqlite3.Connection) -> dict:
    """채널 상태 + orchestrator 성과."""
    try:
        rows = conn.execute(
            "SELECT channel, status, COUNT(*) AS msgs FROM conversations "
            "JOIN channels USING(channel) GROUP BY channel, status"
        ).fetchall()
    except Exception:
        # channels 테이블 없거나 JOIN 실패
        try:
            rows = conn.execute(
                "SELECT channel, COUNT(*) FROM conversations GROUP BY channel"
            ).fetchall()
            rows = [(r[0], "?", r[1]) for r in rows]
        except Exception:
            return {}
    out = {"dm": 0, "group": 0, "internal_dm": 0, "internal_group": 0,
           "mgr": 0, "total_channels": len(rows)}
    for r in rows:
        ch = r[0]
        if ch.startswith("dm-"):
            out["dm"] += 1
        elif ch.startswith("group-"):
            out["group"] += 1
        elif ch.startswith("internal-dm-"):
            out["internal_dm"] += 1
        elif ch.startswith("internal-group-"):
            out["internal_group"] += 1
        elif ch.startswith("mgr-"):
            out["mgr"] += 1
    return out


def _analyze_memory_health(conn: sqlite3.Connection) -> dict:
    """메모리 엔티티 깨짐·정규화 상태."""
    out = {"broken_entities": 0, "role_term_leftover": 0, "total_memories": 0}
    try:
        row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        out["total_memories"] = row[0] if row else 0
        # related_entities 가 단일 글자 배열 포함 (["[", "나", ...])
        rows = conn.execute(
            "SELECT related_entities FROM memories WHERE related_entities IS NOT NULL"
        ).fetchall()
        for r in rows:
            try:
                arr = json.loads(r[0])
                if isinstance(arr, list) and any(
                    isinstance(e, str) and (len(e) == 1 or e in ("[", "]", '"', ","))
                    for e in arr
                ):
                    out["broken_entities"] += 1
                # 역할어 잔존 (정규화 안 됨)
                if isinstance(arr, list) and any(
                    e in ("오너", "owner", "user", "유저") for e in arr if isinstance(e, str)
                ):
                    out["role_term_leftover"] += 1
            except Exception:
                continue
    except Exception as e:
        out["error"] = str(e)
    return out


def _analyze_achievements(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT key, state, unlocked_at, completed_at FROM achievements "
            "WHERE state IN ('unlocked', 'done')"
        ).fetchall()
    except Exception:
        return []
    return [{"key": r[0], "state": r[1], "unlocked": r[2], "completed": r[3]}
            for r in rows]


def _analyze_events(conn: sqlite3.Connection) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        ).fetchall()
    except Exception:
        return []
    return [{"type": r[0], "count": r[1]} for r in rows]


# ── 종합 판정 ───────────────────────────────────────────

def _build_issues(metrics: dict, run_json: dict) -> list[dict]:
    """metrics 기반 이슈 분류 + 심각도 할당."""
    issues = []

    # BLOCKER: 튜토리얼 실패, 봇 크래시
    if not run_json.get("tutorial_done"):
        issues.append({"severity": "BLOCKER", "category": "tutorial",
                       "detail": "tutorial_done=false"})
    if metrics["errors"].get("bot_crash"):
        issues.append({"severity": "BLOCKER", "category": "bot",
                       "detail": f"bot_crash x{metrics['errors']['bot_crash']}"})

    # REGRESSION: 이전 픽스된 것 재발
    meta_leaks = metrics["meta"].get("leaks_in_db", [])
    if meta_leaks:
        issues.append({"severity": "REGRESSION", "category": "meta_leak",
                       "detail": f"persona 메타 발화 {len(meta_leaks)}건 DB 잔존 (필터 뚫림)",
                       "evidence": meta_leaks[:3]})
    if metrics["yuna"].get("monologue_leaks"):
        issues.append({"severity": "REGRESSION", "category": "yuna_monologue",
                       "detail": f"괄호 독백 누출 {len(metrics['yuna']['monologue_leaks'])}건",
                       "evidence": metrics['yuna']['monologue_leaks'][:3]})
    if metrics["yuna"].get("system_error_leaks"):
        issues.append({"severity": "REGRESSION", "category": "yuna_system_error",
                       "detail": f"'못 찾겠어' 류 시스템 에러 유저 노출 {len(metrics['yuna']['system_error_leaks'])}건",
                       "evidence": metrics['yuna']['system_error_leaks'][:3]})
    if metrics["create_room"].get("already_exists_spam_to_user"):
        issues.append({"severity": "REGRESSION", "category": "create_room_spam",
                       "detail": f"유저 노출 '이미 있어:' {metrics['create_room']['already_exists_spam_to_user']}건"})
    if metrics["memory"].get("broken_entities"):
        issues.append({"severity": "REGRESSION", "category": "broken_entities",
                       "detail": f"깨진 entity {metrics['memory']['broken_entities']}개"})

    # FLAKY
    if metrics["errors"].get("a2a_error"):
        issues.append({"severity": "FLAKY", "category": "a2a_timeout",
                       "detail": f"A2A error x{metrics['errors']['a2a_error']} "
                                 f"(retry 성공 시 괜찮음)"})

    # DRIFT: persona 품질 게이트
    for pq in metrics["persona_quality"]:
        passed = int(pq["score"].split("/")[0])
        if passed < 6 and not pq["locked"]:
            issues.append({"severity": "DRIFT", "category": "persona_quality",
                           "detail": f"{pq['name']} {pq['score']} "
                                     f"(실패: {', '.join(pq['failed_checks'])})"})

    # COSMETIC
    if metrics["errors"].get("image_missing"):
        issues.append({"severity": "COSMETIC", "category": "image_missing",
                       "detail": f"프로필 이미지 못 찾음 x{metrics['errors']['image_missing']}"})

    return issues


def _build_verdict(run_json: dict, issues: list[dict]) -> str:
    sev = Counter(i["severity"] for i in issues)
    if sev.get("BLOCKER"):
        return f"❌ BLOCKER {sev['BLOCKER']}건 — 다음 사이클 전 픽스 필수"
    if sev.get("REGRESSION"):
        return f"⚠️ REGRESSION {sev['REGRESSION']}건 — 이전 픽스 재발"
    if sev.get("DRIFT", 0) >= 2:
        return f"⚠️ DRIFT {sev['DRIFT']}건 — persona 품질 저하"
    if run_json.get("tutorial_done") and not sev.get("REGRESSION"):
        return f"✅ 양호 (이슈 {len(issues)}건: {dict(sev) or '없음'})"
    return f"🔶 관찰 (이슈 {len(issues)}건)"


# ── 메인 ───────────────────────────────────────────────

def analyze(run_id: str) -> dict:
    json_p, log_p, db_p = _resolve_sources(run_id)
    if not json_p:
        return {"run_id": run_id, "error": "run JSON not found"}

    run_json = json.loads(json_p.read_text(encoding="utf-8"))
    log_text = log_p.read_text(encoding="utf-8", errors="ignore") if log_p else ""

    conn = sqlite3.connect(db_p) if db_p else None
    metrics = {
        "msgs_total": run_json.get("metrics", {}).get("msgs_total", 0),
        "errors": _analyze_errors(log_text),
        "meta": _analyze_meta(conn) if conn else {},
        "yuna": _analyze_yuna(log_text, conn) if conn else {"cli_calls": 0},
        "create_room": _analyze_create_room(log_text),
        "persona_quality": _analyze_persona_quality(conn) if conn else [],
        "channels": _analyze_channels(conn) if conn else {},
        "memory": _analyze_memory_health(conn) if conn else {},
        "achievements": _analyze_achievements(conn) if conn else [],
        "events": _analyze_events(conn) if conn else [],
    }
    if conn:
        conn.close()

    issues = _build_issues(metrics, run_json)
    verdict = _build_verdict(run_json, issues)

    return {
        "run_id": run_id,
        "status": run_json.get("status"),
        "tutorial_done": run_json.get("tutorial_done"),
        "elapsed_seconds": run_json.get("elapsed_seconds"),
        "verdict": verdict,
        "issues": issues,
        "metrics": metrics,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?", default=None)
    ap.add_argument("--pretty", action="store_true", help="사람 읽기용 포맷")
    args = ap.parse_args()

    run_id = _resolve_run_id(args.run_id)
    result = analyze(run_id)

    if args.pretty:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
