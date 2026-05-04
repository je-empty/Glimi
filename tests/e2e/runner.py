"""
Glimi E2E Test Runner — 튜토리얼 자동 테스트

1. qa 서버 자동 생성/초기화 (커뮤니티 + DB + 유저 프로필)
2. Glimi 봇 시작
3. 테스트 유저 봇 시작
4. 튜토리얼 완료 또는 타임아웃 대기
5. 로그 수집 + 결과 판정

사용법:
  python -m tests.e2e.runner
  python -m tests.e2e.runner --runs 3     # 3회 반복
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COMMUNITIES_DIR = PROJECT_ROOT / "communities"
QA_DIR = COMMUNITIES_DIR / "qa"
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"

QA_COMMUNITY_ID = "qa"
# 타임아웃 제거 — test_user_bot 자체 종료(--turns 소진) 또는 외부 중단(./scripts/qa.sh stop)까지 대기
TEST_TIMEOUT = None

# 테스트 유저 프로필 (환경변수 또는 기본값)
TEST_USER = {
    "name": os.environ.get("QA_USER_NAME", "김도윤"),
    "nickname": os.environ.get("QA_USER_NICKNAME", "도윤"),
    "age": int(os.environ.get("QA_USER_AGE", "26")),
    "birth_year": int(os.environ.get("QA_USER_BIRTH_YEAR", "2001")),
    "gender": os.environ.get("QA_USER_GENDER", "남"),
    "mbti": "",  # 튜토리얼에서 수집되도록 비움
    "background": "",  # 튜토리얼에서 수집되도록 비움
}


def _setup_qa_server(bot_token: str):
    """qa 서버 자동 생성 — 커뮤니티 디렉토리 + .env + DB + 유저 프로필"""
    # 1. 커뮤니티 디렉토리 생성
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.community import init_community
    init_community(QA_COMMUNITY_ID)

    # 2. .env에 봇 토큰 쓰기 (기존 설정 보존)
    env_path = QA_DIR / ".env"
    preserved = {}  # 보존할 키-값

    preserve_keys = (
        "TEST_BOT_TOKEN",
        "DISCORD_GUILD_ID",
        "QA_USER_NAME",
        "QA_USER_NICKNAME",
        "QA_USER_AGE",
        "QA_USER_BIRTH_YEAR",
        "QA_USER_GENDER",
        "GLIMI_IMAGEGEN",  # opt-in 도구 (로컬 LoRA 이미지 생성) — QA 에서 영구 활성
    )
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                for key in preserve_keys:
                    if stripped.startswith(f"{key}="):
                        preserved[key] = stripped

    env_content = (
        "# Glimi QA 서버 (자동 생성)\n"
        f"DISCORD_BOT_TOKEN='{bot_token}'\n"
    )
    for key in preserve_keys:
        if key in preserved:
            env_content += f"{preserved[key]}\n"

    env_path.write_text(env_content)

    # 3. registry.toml에 qa 등록
    _register_qa_community()

    # 4. DB 초기화 + 유저 프로필 삽입
    _init_qa_db()

    print(f"[Runner] qa 서버 세팅 완료: {QA_DIR}")


def _register_qa_community():
    """registry.toml에 qa 커뮤니티 등록"""
    registry_path = COMMUNITIES_DIR / "registry.toml"

    if registry_path.exists():
        content = registry_path.read_text()
        if f'[communities.{QA_COMMUNITY_ID}]' in content:
            return  # 이미 등록됨
    else:
        content = 'default = "qa"\n\n'

    content += (
        f'\n[communities.{QA_COMMUNITY_ID}]\n'
        f'description = "QA 자동 테스트"\n'
        f'language = "ko"\n'
    )
    registry_path.write_text(content)


def _init_qa_db():
    """qa DB 초기화 + 테스트 유저 프로필 삽입"""
    os.environ["GLIMI_COMMUNITY"] = QA_COMMUNITY_ID

    from src.community import set_community
    set_community(QA_COMMUNITY_ID)
    from src import db

    db.init_db()

    # 유저 프로필 삽입 (위저드가 하는 것과 동일)
    conn = db.get_conn()
    existing = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if not existing:
        import json as _json
        personality = _json.dumps({
            "gender": TEST_USER["gender"],
            "nickname": TEST_USER["nickname"],
        }, ensure_ascii=False)

        conn.execute(
            "INSERT INTO users (id, name, age, birth_year, personality) VALUES (?, ?, ?, ?, ?)",
            (
                "test-user",
                TEST_USER["name"],
                TEST_USER["age"],
                TEST_USER["birth_year"],
                personality,
            )
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("active_user_id", "test-user")
        )
        conn.commit()
        print(f"[Runner] 테스트 유저 등록: {TEST_USER['name']} ({TEST_USER['nickname']})")
    conn.close()


def _backup_qa(tag: str = "") -> Path | None:
    """reset 전 현재 DB + logs 를 communities/qa/backups/run-{date}-{tag}/ 로 백업.
    분석·회귀 비교용 — 사용자가 반복 요구한 정책.
    """
    from datetime import datetime as _dt
    db_path = QA_DIR / "community.db"
    logs_dir = QA_DIR / "logs"
    if not db_path.exists() and not (logs_dir.exists() and any(logs_dir.iterdir())):
        return None  # 처음 실행 — 백업할 게 없음
    suffix = _dt.now().strftime("%Y%m%d-%H%M%S")
    if tag:
        suffix = f"{suffix}-{tag}"
    dest = QA_DIR / "backups" / f"run-{suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    # DB (+ WAL sidecars)
    for s in ("", "-shm", "-wal", "-journal"):
        p = QA_DIR / f"community.db{s}"
        if p.exists():
            shutil.copy2(p, dest / p.name)
    # logs 통째로 (system.log / bot.log / flags 등)
    if logs_dir.exists():
        dst_logs = dest / "logs"
        dst_logs.mkdir(exist_ok=True)
        for f in logs_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_logs / f.name)
    # results (해당 run 의 latest.log 복사 — 존재 시)
    lat = RESULTS_DIR / "latest.log" if "RESULTS_DIR" in globals() else None
    try:
        from tests.e2e.runner import RESULTS_DIR as _RD  # noqa (fallback no-op)
        lat = _RD / "latest.log"
    except Exception:
        pass
    if lat and lat.exists():
        try:
            shutil.copy2(lat, dest / "latest.log")
        except Exception:
            pass
    print(f"[Runner] qa 백업: {dest}")
    return dest


def _reset_qa(backup: bool = True, backup_tag: str = ""):
    """qa 서버 초기화 — DB, 로그 삭제 + 디스코드 채널 정리 플래그.

    기본적으로 **reset 직전 자동 백업** — 이전 run 의 DB + logs 를 backups/run-{ts}/
    로 보존. 사용자가 '백업은 일관되게 무조건' 라 강조한 정책.
    """
    if backup:
        try:
            _backup_qa(tag=backup_tag)
        except Exception as e:
            print(f"[Runner] 백업 실패 (계속 진행): {e}")
    # WAL 모드 사이드카(-shm, -wal)까지 같이 지워야 다음 init_db에서 disk I/O error 안 남
    for suffix in ("", "-shm", "-wal", "-journal"):
        p = QA_DIR / f"community.db{suffix}"
        if p.exists():
            p.unlink()

    logs_dir = QA_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for f in logs_dir.iterdir():
        f.unlink()

    # .clean-channels 플래그 생성 → 봇 시작 시 기존 디스코드 채널 삭제
    (logs_dir / ".clean-channels").touch()

    # DB 재생성 + 유저 프로필 재삽입
    _init_qa_db()

    print("[Runner] qa 서버 초기화 완료 (디스코드 채널 정리 예약)")


def _get_bot_token() -> str | None:
    """Glimi 봇 토큰 로드 (qa .env → dev .env fallback)"""
    for env_dir in [QA_DIR, COMMUNITIES_DIR / "dev"]:
        env_path = env_dir / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("DISCORD_BOT_TOKEN=") and not stripped.startswith("#"):
                        val = stripped.split("=", 1)[1].strip().strip("'\"")
                        if val and val != "여기에_봇_토큰":
                            return val
    return None


def _get_test_token() -> str | None:
    """테스트 유저 봇 토큰 로드"""
    for env_dir in [QA_DIR, COMMUNITIES_DIR / "dev"]:
        env_path = env_dir / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("TEST_BOT_TOKEN="):
                        return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("TEST_BOT_TOKEN")


def _start_glimi_bot() -> subprocess.Popen:
    """Glimi 봇 시작 (qa 서버)"""
    # .env에서 DISCORD_GUILD_ID 로드
    guild_id = ""
    env_path = QA_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("DISCORD_GUILD_ID="):
                    guild_id = line.split("=", 1)[1].strip().strip("'\"")
    # test token도 로드
    test_token_val = ""
    if env_path.exists():
        with open(env_path) as f2:
            for line2 in f2:
                if line2.strip().startswith("TEST_BOT_TOKEN="):
                    test_token_val = line2.split("=", 1)[1].strip().strip("'\"")
    env = {
        **os.environ,
        "GLIMI_COMMUNITY": QA_COMMUNITY_ID,
    }
    if guild_id:
        env["DISCORD_GUILD_ID"] = guild_id
    # 봇이 .env를 읽기 전에 환경변수로 주입
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.discord_bot"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"[Runner] Glimi 봇 시작 (PID {proc.pid})")
    return proc


def _wait_for_bot_ready(timeout=60) -> bool:
    """봇이 준비될 때까지 대기 (.bot-ready 파일 감시)"""
    ready_path = QA_DIR / "logs" / ".bot-ready"
    start = time.time()
    while time.time() - start < timeout:
        if ready_path.exists():
            print("[Runner] Glimi 봇 준비 완료")
            return True
        time.sleep(1)
    print("[Runner] Glimi 봇 준비 타임아웃")
    return False


def _start_test_user(token: str, turns: int = 150, seed_prompt: str = "") -> subprocess.Popen:
    """테스트 유저 봇 시작.
    seed_prompt: 비어있지 않으면 test_user 의 초기 응답에 해당 지시 주입 —
    QA resume 시 "채린이한테 대시보드 바로잡기" 같은 시나리오 지시용."""
    cmd = [
        sys.executable, "-m", "tests.e2e.test_user_bot",
        "--token", token,
        "--turns", str(turns),
    ]
    if seed_prompt:
        cmd.extend(["--seed-prompt", seed_prompt])
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"[Runner] 테스트 유저 봇 시작 (PID {proc.pid})")
    return proc


def _collect_db_metrics() -> dict:
    """DB 기반 가시성 지표 수집 — 셀 단위 검증에 사용."""
    db_path = QA_DIR / "community.db"
    out = {
        "msgs_total": 0,
        "msgs_by_channel": {},
        "msgs_by_speaker": {},
        "agents_created": [],   # type='persona'
        "phases_seen": [],
        "yuna_questions_per_field": {},  # mbti/job/hobby asked count (rough)
    }
    if not db_path.exists():
        return out
    try:
        import sqlite3 as _sq
        c = _sq.connect(str(db_path))
        out["msgs_total"] = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        for ch, cnt in c.execute(
            "SELECT channel, COUNT(*) FROM conversations GROUP BY channel"
        ).fetchall():
            out["msgs_by_channel"][ch] = cnt
        for sp, cnt in c.execute(
            "SELECT speaker, COUNT(*) FROM conversations GROUP BY speaker"
        ).fetchall():
            out["msgs_by_speaker"][sp or "?"] = cnt
        out["agents_created"] = [
            r[0] for r in c.execute(
                "SELECT name FROM agents WHERE type='persona'"
            ).fetchall()
        ]
        # Yuna가 mbti/job/hobby 정보 **질문** 한 횟수 (중복 질문 추정).
        # 단순 단어 포함이 아니라 '물음표 + 키워드' 패턴 — 설명·앵커로 언급은 제외.
        for kw in ("MBTI", "직업", "취미"):
            n = c.execute(
                "SELECT COUNT(*) FROM conversations "
                "WHERE speaker='agent-mgr-001' "
                "  AND message LIKE ? "
                "  AND message LIKE '%?%'",
                (f"%{kw}%",),
            ).fetchone()[0]
            out["yuna_questions_per_field"][kw] = n
        c.close()
    except Exception as e:
        out["db_error"] = f"{type(e).__name__}: {e}"
    return out


def _collect_results(run_id: str, elapsed: float) -> dict:
    """로그 수집 + 결과 판정"""
    result = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "status": "unknown",
        "issues": [],
        "metrics": {},
    }

    # 시스템 로그 읽기
    log_path = QA_DIR / "logs" / "system.log"
    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
        result["log_lines"] = log_text.count("\n")

    # 에러 로그
    err_path = QA_DIR / "logs" / "runtime_error.log"
    if err_path.exists():
        err_text = err_path.read_text(encoding="utf-8")
        if err_text.strip():
            result["issues"].append(f"런타임 에러 발생: {err_text[:200]}")

    # 튜토리얼 완료 여부 — `.tutorial-complete` (phase==complete 시점에만 set)
    # cf. `.tutorial-done`은 "유나 첫 인사 완료" 용도 (대시보드 호환)
    tutorial_complete = (QA_DIR / "logs" / ".tutorial-complete").exists()
    result["tutorial_done"] = tutorial_complete

    # 로그 기반 판정
    if log_text:
        # 문제 감지
        if "[필터]" in log_text:
            count = log_text.count("[필터]")
            result["issues"].append(f"메시지 필터 차단 {count}회")

        if "❌" in log_text:
            errors = [l for l in log_text.split("\n") if "❌" in l]
            result["issues"].append(f"오류 로그 {len(errors)}건")

        if "FATAL" in log_text:
            result["issues"].append("FATAL 에러 발생")

        # CMD/QUERY 태그 노출 체크 (시스템 로그 외)
        for line in log_text.split("\n"):
            if "[CMD:" in line and "시스템 로그" not in line and "send_system_log" not in line:
                if "execute" not in line.lower() and "파싱" not in line:
                    result["issues"].append(f"CMD 태그 노출 가능: {line[:80]}")
                    break

        # 프로필 중복 수정 체크
        profile_edits = [l for l in log_text.split("\n") if "[프로필]" in l and "수정:" in l]
        seen_edits = set()
        dupes = 0
        for edit in profile_edits:
            key = edit.split("수정:")[1].strip() if "수정:" in edit else edit
            if key in seen_edits:
                dupes += 1
            seen_edits.add(key)
        if dupes > 0:
            result["issues"].append(f"프로필 중복 수정 {dupes}회")

        # Race condition 체크 (같은 초에 동일 에이전트 2번 호출)
        cli_calls = [l for l in log_text.split("\n") if "Claude CLI 호출" in l]
        for i in range(1, len(cli_calls)):
            if cli_calls[i][:8] == cli_calls[i-1][:8]:  # 같은 시간
                agent_a = cli_calls[i].split("]")[0] if "]" in cli_calls[i] else ""
                agent_b = cli_calls[i-1].split("]")[0] if "]" in cli_calls[i-1] else ""
                if agent_a == agent_b:
                    result["issues"].append("동시 응답 호출 감지 (race condition)")
                    break

    # ── DB 기반 세밀 검증 ─────────────────────────────────
    metrics = _collect_db_metrics()
    result["metrics"] = metrics

    # mgr-creator 채널이 만들어졌는데 test-user 가 거기서 한 마디도 안 함
    msgs_by_ch = metrics.get("msgs_by_channel", {})
    if "mgr-creator" in msgs_by_ch:
        try:
            import sqlite3 as _sq
            c = _sq.connect(str(QA_DIR / "community.db"))
            tu_in_creator = c.execute(
                "SELECT COUNT(*) FROM conversations "
                "WHERE channel='mgr-creator' AND speaker='test-user'"
            ).fetchone()[0]
            c.close()
        except Exception:
            tu_in_creator = -1
        if tu_in_creator == 0:
            result["issues"].append("test-user가 mgr-creator 채널에서 한 번도 발화 안 함")

    # 유나가 같은 분야 **질문**을 4번 이상 반복 (단순 언급 아님 — 물음표 포함만 집계)
    for kw, n in metrics.get("yuna_questions_per_field", {}).items():
        if n >= 4:
            result["issues"].append(f"유나 '{kw}' 질문 {n}회 (중복 질문 의심)")

    # Phase 2 도달했는데 create_agent_profile 한 번도 안 됨
    if tutorial_complete is False and "mgr-creator" in msgs_by_ch and not metrics.get("agents_created"):
        result["issues"].append("Phase 2 진입 후 create_agent_profile 호출 0회")

    # ── 최종 판정 ─────────────────────────────────────────
    fatal_only = any("FATAL" in i or "레거시" in i for i in result["issues"])
    if not tutorial_complete:
        result["status"] = "FAIL"
        result["issues"].append("튜토리얼 미완료")
    elif fatal_only:
        result["status"] = "FAIL"
    elif result["issues"]:
        result["status"] = "WARN"
    else:
        result["status"] = "PASS"

    return result


def _save_results(result: dict, run_id: str):
    """결과 저장"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 결과 JSON
    result_path = RESULTS_DIR / f"{run_id}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 로그 복사
    log_src = QA_DIR / "logs" / "system.log"
    if log_src.exists():
        log_dst = RESULTS_DIR / f"{run_id}.log"
        log_dst.write_text(log_src.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"[Runner] 결과 저장: {result_path}")


def _kill_proc(proc: subprocess.Popen):
    """프로세스 종료"""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_single_test(bot_token: str, test_token: str, run_id: str,
                     resume: bool = False, seed_prompt: str = "") -> dict:
    """단일 테스트 실행. resume=True 면 DB/채널 유지 (초기화 스킵)."""
    print(f"\n{'='*60}")
    print(f"  Test Run: {run_id} {'[RESUME]' if resume else ''}")
    print(f"{'='*60}\n")

    # 1. 초기화 — resume 모드면 건너뜀 (기존 DB/채널 유지)
    if not resume:
        _reset_qa()
        _setup_qa_server(bot_token)  # 봇 토큰 갱신 (.env에 최신 토큰 반영)
    else:
        print("[Runner] resume 모드 — DB/채널 유지, 봇만 재기동")
        _setup_qa_server(bot_token)  # 토큰만 갱신

    # 2. Glimi 봇 시작
    glimi_proc = _start_glimi_bot()
    time.sleep(3)

    if glimi_proc.poll() is not None:
        print("[Runner] Glimi 봇 즉시 종료됨")
        return {"run_id": run_id, "status": "ERROR", "issues": ["Glimi 봇 시작 실패"]}

    # 3. 봇 준비 대기
    if not _wait_for_bot_ready():
        _kill_proc(glimi_proc)
        return {"run_id": run_id, "status": "ERROR", "issues": ["Glimi 봇 준비 타임아웃"]}

    # 4. 유나 인사 대기 (튜토리얼 시작 시 유나가 먼저 메시지 보냄)
    time.sleep(15)

    # 5. 테스트 유저 봇 시작
    test_proc = _start_test_user(test_token, seed_prompt=seed_prompt)
    start_time = time.time()

    # 6. 대기 — test_user_bot이 자체 종료(--turns 소진)하거나 외부에서 중단될 때까지
    # TEST_TIMEOUT=None이면 무기한, 숫자면 해당 초 후 강제 종료
    try:
        test_proc.wait(timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"[Runner] 테스트 타임아웃 ({TEST_TIMEOUT}초)")
        _kill_proc(test_proc)

    elapsed = time.time() - start_time

    # 7. 테스트 유저 봇 출력
    stdout = test_proc.stdout.read() if test_proc.stdout else ""
    if stdout:
        print("\n[TestUser 출력]")
        print(stdout[-2000:])  # 마지막 2000자

    # 8. Glimi 봇 종료
    _kill_proc(glimi_proc)
    time.sleep(2)

    # 9. 결과 수집
    result = _collect_results(run_id, elapsed)
    _save_results(result, run_id)

    # 10. 결과 출력
    status_emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "ERROR": "💥"}.get(result["status"], "?")
    print(f"\n{status_emoji} 결과: {result['status']}")
    if result.get("issues"):
        for issue in result["issues"]:
            print(f"  - {issue}")
    print(f"  소요시간: {elapsed:.0f}초")
    print(f"  튜토리얼: {'완료' if result.get('tutorial_done') else '미완료'}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Glimi E2E Test Runner")
    parser.add_argument("--runs", type=int, default=1, help="반복 횟수")
    parser.add_argument("--bot-token", help="Glimi 봇 토큰 (없으면 .env에서 로드)")
    parser.add_argument("--test-token", help="테스트 유저 봇 토큰")
    parser.add_argument("--resume", action="store_true",
                        help="DB·채널 초기화 없이 이어서 실행 (QA 세션 유지)")
    parser.add_argument("--seed-prompt", default="",
                        help="test_user 초기 응답에 주입할 지시 (resume 시나리오용)")
    args = parser.parse_args()

    bot_token = args.bot_token or _get_bot_token()
    test_token = args.test_token or _get_test_token()

    if not bot_token:
        print("Glimi 봇 토큰이 필요합니다.")
        print("  --bot-token 인자 또는 communities/qa/.env에 DISCORD_BOT_TOKEN 설정")
        sys.exit(1)

    if not test_token:
        print("테스트 유저 봇 토큰이 필요합니다.")
        print("  --test-token 인자 또는 communities/qa/.env에 TEST_BOT_TOKEN 설정")
        print()
        print("  봇 생성: https://discord.com/developers/applications")
        print("    1. New Application → Bot 탭 → Token 복사")
        print("    2. OAuth2 → URL Generator → bot 체크 → Send Messages + Read Message History")
        print("    3. 생성된 URL로 QA 서버에 초대")
        sys.exit(1)

    # 첫 실행 시 qa 서버 자동 생성
    _setup_qa_server(bot_token)

    results = []
    for i in range(args.runs):
        run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        result = run_single_test(bot_token, test_token, run_id,
                                  resume=args.resume, seed_prompt=args.seed_prompt)
        results.append(result)

        if i < args.runs - 1:
            print("\n다음 테스트까지 10초 대기...")
            time.sleep(10)

    # 최종 요약
    if len(results) > 1:
        print(f"\n{'='*60}")
        print(f"  전체 결과 ({len(results)}회)")
        print(f"{'='*60}")
        for r in results:
            status = r.get("status", "?")
            emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "ERROR": "💥"}.get(status, "?")
            issues = len(r.get("issues", []))
            print(f"  {emoji} {r['run_id']} — {status} ({r.get('elapsed_seconds', 0):.0f}s, issues: {issues})")


if __name__ == "__main__":
    main()
