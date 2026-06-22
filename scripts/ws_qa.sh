#!/bin/bash
# Glimi Workspace QA Runner — tmux 세션으로 자율 owner-driver 루프 E2E 테스트.
#
# Community 의 scripts/qa.sh 를 그대로 미러 — 단, 디스코드 봇/두 번째 봇이 필요 없다.
# 워크스페이스는 owner-agent 가 스스로 루프를 돌리므로 커널을 직접 구동한다
# (tests.e2e.ws_runner → workspace.driver.drive_workspace).
#
# 사용:
#   ./scripts/ws_qa.sh                  ← claude_cli 백엔드로 3 라운드 (비용 발생)
#   ./scripts/ws_qa.sh --rounds 5       ← 5 라운드
#   ./scripts/ws_qa.sh attach           ← 실행 중인 세션에 붙기
#   ./scripts/ws_qa.sh stop             ← 세션 종료
#
# 추가 args 는 전부 tests/e2e/ws_runner.py 로 pass-through.
#
# 무료 셀프테스트(비용 0)는 echo 백엔드로:
#   GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.ws_runner --rounds 2
#
# 세션 이름: Glimi-WS-QA

set -e
cd "$(dirname "$0")/.."

# Homebrew + 사용자 로컬 bin 경로 보강 (non-interactive SSH 세션 대비)
for p in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
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

# macOS Keychain 언락 — 부모 + tmux runner shell 양쪽 다 (qa.sh 와 동일 이유:
# detached tmux 안의 python subprocess 가 claude CLI 호출 시 keychain 접근 fail 방지).
KEYCHAIN_UNLOCK_PREFIX=""
if [ "$(uname)" = "Darwin" ] && [ -r "$HOME/.config/glimi/keychain-pw" ]; then
    /usr/bin/security unlock-keychain -p "$(cat "$HOME/.config/glimi/keychain-pw")" \
        "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null \
        && echo "[ws_qa.sh] login.keychain-db 언락 (부모)"
    KEYCHAIN_UNLOCK_PREFIX="/usr/bin/security unlock-keychain -p \"\$(cat '$HOME/.config/glimi/keychain-pw')\" '$HOME/Library/Keychains/login.keychain-db' 2>/dev/null && echo '[runner] keychain 언락';"
fi

SESSION="Glimi-WS-QA"

# 워크스페이스 QA 데이터 디렉토리 (in-memory store 라 실제 DB 파일은 없지만,
# 커널/예산 등이 GLIMI_DATA_DIR 를 참조할 수 있으므로 격리된 경로를 준다).
WS_QA_DATA_DIR="$PWD/tests/e2e/results/ws-data"
mkdir -p "$WS_QA_DATA_DIR"
mkdir -p "$PWD/tests/e2e/results"

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
    echo -e "  붙기: ${CYAN}./scripts/ws_qa.sh attach${NC}"
    echo -e "  종료: ${CYAN}./scripts/ws_qa.sh stop${NC}"
    exit 1
fi

echo -e "${CYAN}◈ Glimi Workspace QA Runner${NC}"
echo -e "  세션: ${GREEN}$SESSION${NC}"
echo -e "  백엔드: ${GREEN}claude_cli${NC} (비용 발생 — 무료 셀프테스트는 GLIMI_LLM_BACKEND=echo)"
echo ""

# 인자 escape (공백·한글 보존; qa.sh 와 동일)
ESCAPED_ARGS=""
for arg in "$@"; do
    ESCAPED_ARGS="$ESCAPED_ARGS $(printf '%q' "$arg")"
done

tmux new-session -d -s "$SESSION" -n runner \
    "ulimit -n 4096 2>/dev/null; \
     $KEYCHAIN_UNLOCK_PREFIX \
     PYTHONUNBUFFERED=1 PYTHONPATH=$PWD/glimi-core:$PWD/glimi-community:$PWD/glimi-workspace:$PWD GLIMI_DATA_DIR=$WS_QA_DATA_DIR GLIMI_LLM_BACKEND=claude_cli $PYTHON -u -m tests.e2e.ws_runner $ESCAPED_ARGS 2>&1 | tee tests/e2e/results/ws-latest.log"

echo -e "${GREEN}[$SESSION] 시작됨${NC}"
echo -e "  실시간 로그: ${CYAN}./scripts/ws_qa.sh attach${NC}"
echo -e "  종료:        ${CYAN}./scripts/ws_qa.sh stop${NC}"
echo -e "  tail 로그:   ${CYAN}tail -f tests/e2e/results/ws-latest.log${NC}"
