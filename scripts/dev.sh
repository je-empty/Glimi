#!/bin/bash
# Project Glimi — 터미널에서 직접 개발 요청
# 봇 없이 dev_runner.py를 바로 실행한다.
#
# 사용법:
#   ./dev.sh "버그 수정해줘"
#   ./dev.sh  (인자 없으면 대화형)
#   GLIMI_COMMUNITY=private ./dev.sh "..."

cd "$(dirname "$0")/.."

# 봇 실행 중이면 경고
if [ -f "dev/.bot.pid" ] && kill -0 "$(cat dev/.bot.pid)" 2>/dev/null; then
    echo "봇이 실행 중. 디스코드에서 요청하거나, scripts/stop.sh 로 먼저 종료해."
    read -p "봇 종료하고 진행? (y/N) " yn
    [[ "$yn" =~ ^[yY]$ ]] || exit 0
    ./scripts/stop.sh
    sleep 2
fi

# 요청 내용
if [ -n "$1" ]; then
    DESC="$*"
else
    read -p "개발 요청: " DESC
    [ -z "$DESC" ] && echo "취소" && exit 0
fi

python -m community.tools.dev_runner "$DESC"
