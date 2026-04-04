#!/usr/bin/env python3
"""
Project Chaos — 개발자 에이전트

Claude Code CLI(Opus)를 실행하여 프로젝트 코드를 직접 수정한다.
CLAUDE.md는 Claude Code가 cwd에서 자동 발견하므로 별도 주입 불필요.

호출 경로:
  1. run.sh → exit(42) 후 자동 실행 (dev/pending.json 읽음)
  2. dev.sh "설명" → CLI 인자로 직접 실행
"""
import os
import sys
import json
import subprocess
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV_DIR = os.path.join(PROJECT_ROOT, "dev")
PENDING_FILE = os.path.join(DEV_DIR, "pending.json")
RESULT_FILE = os.path.join(DEV_DIR, "result.json")

os.makedirs(DEV_DIR, exist_ok=True)

from src import log_writer


def run(description: str, requested_by: str = "terminal") -> dict:
    """Claude Code CLI로 개발 요청 처리"""
    if not shutil.which("claude"):
        return {"status": "error", "message": "Claude Code CLI 없음"}

    log_writer.mark_dev_active()
    log_writer.dev(f"요청: {description}")
    log_writer.dev(f"요청자: {requested_by}")
    log_writer.system(f"🔧 개발 모드 시작 — {description[:60]}")

    print(f"\n{'═'*60}")
    print(f"  🔧 개발자 에이전트 (Opus)")
    print(f"  요청자: {requested_by}")
    print(f"  {description}")
    print(f"{'═'*60}\n")

    try:
        process = subprocess.Popen(
            [
                "claude",
                "-p", description,
                "--append-system-prompt",
                "너는 Project Chaos의 개발자 에이전트야. "
                "코드를 읽고 수정하고 새 기능을 추가하는 역할이야. "
                "수정 후 변경 사항을 명확히 보고해.",
                "--output-format", "text",
                "--model", "claude-opus-4-6",
                "--dangerously-skip-permissions",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=PROJECT_ROOT,
        )

        output_lines = []
        for line in process.stdout:
            line = line.rstrip('\n')
            print(f"  {line}")
            output_lines.append(line)
            log_writer.dev(line)

        process.wait(timeout=600)
        output = "\n".join(output_lines)

        if process.returncode == 0:
            print(f"\n  ✓ 완료")
            log_writer.dev("✓ 작업 완료")
            log_writer.system("🔧 개발 완료")
            return {
                "status": "success",
                "message": output[:3000],
                "requested_by": requested_by,
                "timestamp": datetime.now().isoformat(),
            }
        else:
            print(f"\n  ✗ 실패 (exit {process.returncode})")
            log_writer.dev(f"✗ 실패 (exit {process.returncode})")
            log_writer.system("🔧 개발 실패")
            return {
                "status": "error",
                "message": f"exit {process.returncode}: {output[:1000]}",
                "requested_by": requested_by,
                "timestamp": datetime.now().isoformat(),
            }

    except subprocess.TimeoutExpired:
        process.kill()
        log_writer.dev("✗ 타임아웃 (10분)")
        return {"status": "error", "message": "타임아웃 (10분)", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        log_writer.dev(f"✗ 오류: {e}")
        return {"status": "error", "message": str(e)[:500], "timestamp": datetime.now().isoformat()}
    finally:
        log_writer.mark_dev_done()


def main():
    if len(sys.argv) > 1:
        description = " ".join(sys.argv[1:])
        requested_by = "terminal"
    elif os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            pending = json.load(f)
        description = pending["description"]
        requested_by = pending.get("requested_by", "unknown")
        os.remove(PENDING_FILE)
    else:
        print("  처리할 요청 없음")
        return

    result = run(description, requested_by)

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  결과: {RESULT_FILE}")
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
