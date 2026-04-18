#!/bin/bash
# Glimi QA Runner — tmux 세션으로 E2E 자동 테스트 실행
#
# 사용:
#   ./scripts/qa.sh            ← 1회 실행
#   ./scripts/qa.sh --runs 3   ← 3회 반복
#   ./scripts/qa.sh attach     ← 실행 중인 세션에 붙기
#   ./scripts/qa.sh stop       ← 세션 종료
#
# 세션 이름: Glimi-QA-Runner

set -e
cd "$(dirname "$0")/.."

# Homebrew bin 경로 보강 (non-interactive SSH 세션에서도 tmux/python 등 발견 가능하도록)
for p in /opt/homebrew/bin /usr/local/bin; do
    [ -d "$p" ] && [[ ":$PATH:" != *":$p:"* ]] && PATH="$p:$PATH"
done
export PATH

# Python 인터프리터 결정 (.venv > python3 > python)
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "ERROR: python interpreter not found" >&2
    exit 1
fi
export PYTHON

SESSION="Glimi-QA-Runner"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

case "${1:-}" in
    attach|a)
        tmux attach -t "$SESSION"
        exit 0
        ;;
    stop|kill)
        tmux kill-session -t "$SESSION" 2>/dev/null && \
            echo -e "${YELLOW}[$SESSION] 종료됨${NC}" || \
            echo -e "${YELLOW}[$SESSION] 실행 중인 세션 없음${NC}"
        exit 0
        ;;
esac

# 이미 세션 있으면 붙기 안내
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo -e "${YELLOW}[$SESSION] 이미 실행 중${NC}"
    echo -e "  붙기: ${CYAN}./scripts/qa.sh attach${NC}"
    echo -e "  종료: ${CYAN}./scripts/qa.sh stop${NC}"
    exit 1
fi

echo -e "${CYAN}◈ Glimi QA Runner${NC}"
echo -e "  세션: ${GREEN}$SESSION${NC}"
echo ""

# 로컬 QA 설정(.env)을 tmux 내부 shell에서 source → QA_USER_* 등 페르소나 주입
# 파일은 gitignore됨 (개인정보 커밋 방지)
tmux new-session -d -s "$SESSION" -n runner \
    "set -a; [ -f communities/qa/.env ] && source communities/qa/.env; set +a; \
     PYTHONUNBUFFERED=1 $PYTHON -u -m tests.e2e.runner $* 2>&1 | tee tests/e2e/results/latest.log"

echo -e "${GREEN}[$SESSION] 시작됨${NC}"
echo -e "  실시간 로그: ${CYAN}./scripts/qa.sh attach${NC}"
echo -e "  종료:        ${CYAN}./scripts/qa.sh stop${NC}"
echo -e "  tail 로그:   ${CYAN}tail -f tests/e2e/results/latest.log${NC}"
