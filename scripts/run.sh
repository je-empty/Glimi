#!/bin/bash
# Project Glimi — 메인 실행 래퍼
# 봇 실행 + 개발 요청 처리 + 자동 재시작
#
# 사용: ./run.sh [community_id]
#   ./run.sh              ← registry.toml의 default 커뮤니티
#   ./run.sh private      ← 지정 커뮤니티
# 종료: Ctrl+C (봇 종료 후 루프도 종료)

set -e
cd "$(dirname "$0")/.."

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# 커뮤니티 결정
if [ -n "$1" ]; then
    export GLIMI_COMMUNITY="$1"
fi

echo -e "${CYAN}◈ Project Glimi — run.sh${NC}"
if [ -n "$GLIMI_COMMUNITY" ]; then
    echo -e "  커뮤니티: ${GREEN}${GLIMI_COMMUNITY}${NC}"
fi
echo ""

# 디렉토리 준비
mkdir -p dev

# PID 파일
PID_FILE="dev/.bot.pid"
DASHBOARD_PID_FILE="dev/.dashboard.pid"
DASHBOARD_PORT="${GLIMI_DASHBOARD_PORT:-8765}"

# 웹 대시보드 자동 시작 (외부망 접속용 — 포트 $DASHBOARD_PORT 포워딩하면 됨)
DASH_COMMUNITY="${GLIMI_COMMUNITY:-default}"
echo -e "${CYAN}[run.sh] 웹 대시보드 시작 (port ${DASHBOARD_PORT}, community ${DASH_COMMUNITY})${NC}"
python scripts/web_dashboard.py "$DASH_COMMUNITY" --port "$DASHBOARD_PORT" --host 0.0.0.0 \
    > dev/dashboard.log 2>&1 &
echo $! > "$DASHBOARD_PID_FILE"

cleanup() {
    echo -e "\n${YELLOW}Glimi 종료${NC}"
    if [ -f "$PID_FILE" ]; then
        kill "$(cat $PID_FILE)" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    if [ -f "$DASHBOARD_PID_FILE" ]; then
        kill "$(cat $DASHBOARD_PID_FILE)" 2>/dev/null || true
        rm -f "$DASHBOARD_PID_FILE"
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

while true; do
    echo -e "${GREEN}[run.sh] 봇 시작...${NC}"

    # 봇 실행 (백그라운드 X — 직접 실행)
    python -m src.discord_bot &
    BOT_PID=$!
    echo $BOT_PID > "$PID_FILE"

    # 봇 종료 대기
    wait $BOT_PID
    EXIT_CODE=$?
    rm -f "$PID_FILE"

    echo -e "${YELLOW}[run.sh] 봇 종료 (exit code: $EXIT_CODE)${NC}"

    # exit code 42 = 개발 요청
    if [ $EXIT_CODE -eq 42 ]; then
        # tmux 안이면 이 윈도우로 전환 (개발 과정 실시간 확인)
        tmux select-window -t glimi:0 2>/dev/null || true

        echo -e "${CYAN}[run.sh] 개발자 에이전트 실행...${NC}"
        python -m src.tools.dev_runner

        # 개발 완료 → 모니터로 복귀
        tmux select-window -t glimi:1 2>/dev/null || true

        echo -e "${GREEN}[run.sh] 봇 재시작${NC}"
        sleep 2
        continue
    fi

    # exit code 0 = 정상 종료
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}[run.sh] 정상 종료${NC}"
        break
    fi

    # 그 외 = 크래시 → 5초 후 재시작
    echo -e "${RED}[run.sh] 비정상 종료 — 5초 후 재시작${NC}"
    sleep 5
done
