#!/bin/bash
# Project Glimi — 통합 실행
# 세팅 안 되어 있으면 자동 세팅 → 기존 프로세스 정리 → 모니터(+봇) 시작
#
# 실행: ./start.sh [community_id]
# 종료: 모니터에서 q 또는 ./stop.sh

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

# ── 자동 세팅 ──────────────────────────────────────────

# 1) venv 생성
if [ ! -d .venv ]; then
    echo -e "${CYAN}[setup] 가상환경 생성 중...${NC}"
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[setup] venv 생성 실패. Python 3.11+ 가 설치되어 있는지 확인해주세요${NC}"
        exit 1
    fi
    echo -e "${GREEN}[setup] 가상환경 생성 완료${NC}"
fi

# 2) venv 활성화
source .venv/bin/activate

# 3) 패키지 설치 (requirements.txt가 venv보다 새로우면 재설치)
NEED_INSTALL=false
if [ ! -f .venv/.installed ]; then
    NEED_INSTALL=true
elif [ requirements.txt -nt .venv/.installed ]; then
    NEED_INSTALL=true
fi

if [ "$NEED_INSTALL" = true ]; then
    echo -e "${CYAN}[setup] 패키지 설치 중...${NC}"
    pip install -q -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}[setup] 패키지 설치 실패${NC}"
        exit 1
    fi
    touch .venv/.installed
    echo -e "${GREEN}[setup] 패키지 설치 완료${NC}"
fi

# 4) 필수 디렉토리
mkdir -p dev

# 5) 커뮤니티 .env 체크 (커뮤니티 디렉토리가 없으면 자동 생성 안내)
# 커뮤니티 디렉토리와 .env는 python에서 community.ensure_dirs()로 생성됨

# ── 기존 프로세스 정리 ─────────────────────────────────

echo "기존 프로세스 정리..."
pkill -f "src.discord_bot" 2>/dev/null
pkill -f "src.tui.dashboard" 2>/dev/null
pkill -f "src.tools.dev_runner" 2>/dev/null
rm -f dev/.bot.pid 2>/dev/null
sleep 1

# 남아있으면 강제 종료
pkill -9 -f "src.discord_bot" 2>/dev/null
pkill -9 -f "src.tui.dashboard" 2>/dev/null
pkill -9 -f "src.tools.dev_runner" 2>/dev/null

echo -e "${GREEN}◈ Project Glimi 시작${NC}"
if [ -n "$GLIMI_COMMUNITY" ]; then
    echo -e "  커뮤니티: ${GREEN}${GLIMI_COMMUNITY}${NC}"
fi
python -m src.tui.dashboard
