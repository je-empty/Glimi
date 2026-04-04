#!/bin/bash
# Project Chaos — 전체 종료
cd "$(dirname "$0")/.."

echo "Chaos 종료중..."
pkill -f "src.discord_bot" 2>/dev/null
pkill -f "src.tui.dashboard" 2>/dev/null
pkill -f "src.tools.dev_runner" 2>/dev/null
rm -f dev/.bot.pid 2>/dev/null

sleep 1

# 남아있으면 강제
pkill -9 -f "src.discord_bot" 2>/dev/null
pkill -9 -f "src.tui.dashboard" 2>/dev/null
pkill -9 -f "src.tools.dev_runner" 2>/dev/null

echo "종료 완료"
