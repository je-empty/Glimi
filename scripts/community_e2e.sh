#!/bin/bash
# Glimi Community TRUE WEB E2E Runner — tmux 세션으로 REAL 커뮤니티 서버를 HTTP+WS 로 구동하는 E2E.
#
# scripts/ws_e2e.sh 의 미러 (워크스페이스 → 커뮤니티). tests.e2e.community_e2e 가
# 'community.platform' 서버 서브프로세스를 격리된 temp data/communities 에 띄우고,
# 친구 DM 채널을 WS 로 구동(오너가 인사·질문·후속 → 친구가 답)한 뒤 판정한다.
# --keep-serving 이면 서버를 살려둔다(브라우저/터널로 라이브 관전).
#
# 사용:
#   ./scripts/community_e2e.sh                           ← claude_cli 백엔드 2 라운드 (비용 발생)
#   ./scripts/community_e2e.sh --rounds 3 --friends 2 --keep-serving --host 0.0.0.0
#   ./scripts/community_e2e.sh --port 8231
#   ./scripts/community_e2e.sh attach                    ← 실행 중 세션 붙기
#   ./scripts/community_e2e.sh stop                      ← 세션 종료
#
# 추가 args 는 전부 tests/e2e/community_e2e.py 로 pass-through.
#
# 무료 셀프테스트(비용 0)는 echo 백엔드로:
#   GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --rounds 1 --port 8231
#
# 세션 이름: Glimi-Community-E2E
# SAFETY: 격리 temp dir + 비표준 포트(기본 8230). je-empty(:8200)·실커뮤니티 미접촉. 터널 자동기동 X.

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

# macOS Keychain 언락 — 부모 + tmux runner shell 양쪽 (ws_e2e.sh 와 동일 이유:
# detached tmux 안의 python subprocess→claude CLI 호출 시 keychain 접근 fail 방지).
KEYCHAIN_UNLOCK_PREFIX=""
if [ "$(uname)" = "Darwin" ] && [ -r "$HOME/.config/glimi/keychain-pw" ]; then
    /usr/bin/security unlock-keychain -p "$(cat "$HOME/.config/glimi/keychain-pw")" \
        "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null \
        && echo "[community_e2e.sh] login.keychain-db 언락 (부모)"
    KEYCHAIN_UNLOCK_PREFIX="/usr/bin/security unlock-keychain -p \"\$(cat '$HOME/.config/glimi/keychain-pw')\" '$HOME/Library/Keychains/login.keychain-db' 2>/dev/null && echo '[runner] keychain 언락';"
fi

SESSION="Glimi-Community-E2E"

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
    echo -e "  붙기: ${CYAN}./scripts/community_e2e.sh attach${NC}"
    echo -e "  종료: ${CYAN}./scripts/community_e2e.sh stop${NC}"
    exit 1
fi

echo -e "${CYAN}◈ Glimi Community TRUE WEB E2E Runner${NC}"
echo -e "  세션: ${GREEN}$SESSION${NC}"
echo -e "  백엔드: ${GREEN}claude_cli${NC} (비용 발생 — 무료 셀프테스트는 GLIMI_LLM_BACKEND=echo)"
echo -e "  ${YELLOW}--keep-serving 이면 판정 후에도 서버를 살려둠 (브라우저/터널로 관전)${NC}"
echo ""

# 인자 escape (공백·한글 보존; ws_e2e.sh 와 동일)
ESCAPED_ARGS=""
for arg in "$@"; do
    ESCAPED_ARGS="$ESCAPED_ARGS $(printf '%q' "$arg")"
done

tmux new-session -d -s "$SESSION" -n runner \
    "ulimit -n 4096 2>/dev/null; \
     $KEYCHAIN_UNLOCK_PREFIX \
     PYTHONUNBUFFERED=1 PYTHONPATH=$PWD/glimi-core:$PWD/glimi-community:$PWD/glimi-workspace:$PWD GLIMI_LLM_BACKEND=claude_cli $PYTHON -u -m tests.e2e.community_e2e $ESCAPED_ARGS 2>&1 | tee tests/e2e/results/community-e2e-latest.log"

echo -e "${GREEN}[$SESSION] 시작됨${NC}"
echo -e "  실시간 로그: ${CYAN}./scripts/community_e2e.sh attach${NC}"
echo -e "  종료:        ${CYAN}./scripts/community_e2e.sh stop${NC}"
echo -e "  tail 로그:   ${CYAN}tail -f tests/e2e/results/community-e2e-latest.log${NC}"
