#!/bin/bash
# Project Glimi — 전체 종료 (플랫폼 + 봇 + 레거시 TUI 전부)
cd "$(dirname "$0")/.."

echo "Glimi 종료중..."
pkill -f "src.platform" 2>/dev/null
pkill -f "src.discord_bot" 2>/dev/null
pkill -f "src.tui.dashboard" 2>/dev/null
pkill -f "src.tui.wizard" 2>/dev/null
pkill -f "src.tools.dev_runner" 2>/dev/null
rm -f dev/.bot*.pid dev/.platform.pid 2>/dev/null

sleep 1

# 남아있으면 강제
pkill -9 -f "src.platform" 2>/dev/null
pkill -9 -f "src.discord_bot" 2>/dev/null
pkill -9 -f "src.tui.dashboard" 2>/dev/null
pkill -9 -f "src.tools.dev_runner" 2>/dev/null

echo "종료 완료"
