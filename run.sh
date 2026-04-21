#!/bin/bash
# Project Glimi — 메인 진입점
#
# 기본 (플랫폼 데몬, FastAPI + 웹 UI):
#   ./run.sh                         → http://localhost:8000
#   ./run.sh --port 9000
#   ./run.sh --host 127.0.0.1
#
# 레거시 모드:
#   ./run.sh --legacy <community>    → 구 단일 봇 (QA/디버깅용)
#   ./run.sh tui                     → 구 TUI wizard (deprecated)
#   ./run.sh tui <community>         → 구 TUI dashboard

set -e
cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 자동 세팅 ──────────────────────────────────────────
if [ ! -d .venv ]; then
    echo -e "${CYAN}[setup] 가상환경 생성 중...${NC}"
    python3 -m venv .venv || { echo -e "${RED}[setup] venv 생성 실패. Python 3.11+ 필요${NC}"; exit 1; }
    echo -e "${GREEN}[setup] 가상환경 생성 완료${NC}"
fi
source .venv/bin/activate

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    pip install -q -r requirements.txt && pip install -q -e . 2>/dev/null
    touch "$MARKER"
fi

mkdir -p dev

# ── 기존 프로세스 정리 ────────────────────────────────
_cleanup_existing() {
    pkill -f "src.platform" 2>/dev/null || true
    pkill -f "src.discord_bot" 2>/dev/null || true
    pkill -f "src.tui.dashboard" 2>/dev/null || true
    pkill -f "src.tui.wizard" 2>/dev/null || true
    pkill -f "src.tools.dev_runner" 2>/dev/null || true
    rm -f dev/.bot*.pid dev/.platform.pid 2>/dev/null || true
    sleep 1
    pkill -9 -f "src.platform" 2>/dev/null || true
    pkill -9 -f "src.discord_bot" 2>/dev/null || true
    pkill -9 -f "src.tui.dashboard" 2>/dev/null || true
}
_cleanup_existing

echo -e "${CYAN}◈ Project Glimi${NC}"

# ── 레거시 TUI ────────────────────────────────────────
if [ "$1" = "tui" ]; then
    shift
    if [ -z "$1" ]; then
        echo -e "${YELLOW}  (레거시 TUI wizard — 플랫폼 웹으로 이전됨)${NC}"
        exec python -m src.tui.wizard
    else
        echo -e "  TUI dashboard: ${GREEN}$1${NC}"
        exec python -m src.tui.dashboard "$1"
    fi
fi

# ── 레거시 단일 봇 ────────────────────────────────────
if [ "$1" = "--legacy" ]; then
    shift
    if [ -n "$1" ]; then
        export GLIMI_COMMUNITY="$1"
        shift
    fi
    echo -e "${YELLOW}  레거시 단일 봇 모드${NC}"
    if [ -n "$GLIMI_COMMUNITY" ]; then
        echo -e "  커뮤니티: ${GREEN}${GLIMI_COMMUNITY}${NC}"
    fi
    echo ""

    PID_FILE="dev/.bot.pid"
    PAUSE_FILE="dev/.bot-paused"
    rm -f "$PAUSE_FILE"

    _leg_cleanup() {
        echo -e "\n${YELLOW}종료${NC}"
        [ -f "$PID_FILE" ] && kill "$(cat $PID_FILE)" 2>/dev/null && rm -f "$PID_FILE"
        exit 0
    }
    trap _leg_cleanup SIGINT SIGTERM

    while true; do
        if [ -f "$PAUSE_FILE" ]; then
            echo -e "${YELLOW}[legacy] pause flag — 대기${NC}"
            while [ -f "$PAUSE_FILE" ]; do sleep 1; done
        fi
        echo -e "${GREEN}[legacy] 봇 시작${NC}"
        python -m src.discord_bot &
        BOT_PID=$!
        echo $BOT_PID > "$PID_FILE"
        wait $BOT_PID
        EXIT_CODE=$?
        rm -f "$PID_FILE"

        if [ $EXIT_CODE -eq 42 ]; then
            echo -e "${CYAN}[legacy] 개발자 에이전트 실행${NC}"
            python -m src.tools.dev_runner
            echo -e "${GREEN}[legacy] 봇 재시작${NC}"
            sleep 2
            continue
        fi
        if [ $EXIT_CODE -eq 0 ]; then
            echo -e "${GREEN}[legacy] 정상 종료${NC}"
            break
        fi
        echo -e "${RED}[legacy] 비정상 종료 — 5초 후 재시작${NC}"
        sleep 5
    done
    exit 0
fi

# ── 플랫폼 모드 (기본) ─────────────────────────────────
HOST="${GLIMI_HOST:-0.0.0.0}"
PORT="${GLIMI_PORT:-8000}"
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2;;
        --port) PORT="$2"; shift 2;;
        --help|-h)
            grep '^#' "$0" | head -15 | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo -e "${RED}알 수 없는 옵션: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}◈ Glimi Platform${NC}"
echo -e "  URL: ${GREEN}http://${HOST}:${PORT}${NC}"
echo ""

python -m src.platform.accounts list > /dev/null 2>&1 || python -m src.platform.accounts bootstrap

exec python -m src.platform --host "$HOST" --port "$PORT"
