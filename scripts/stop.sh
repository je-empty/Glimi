#!/bin/bash
# Project Glimi — 전체 종료 (플랫폼 + 봇 + 레거시 TUI 전부)
cd "$(dirname "$0")/.."

echo "Glimi 종료중..."
pkill -f "community.platform" 2>/dev/null
pkill -f "community.discord_bot" 2>/dev/null
pkill -f "community.tui.dashboard" 2>/dev/null
pkill -f "community.tui.wizard" 2>/dev/null
pkill -f "community.tools.dev_runner" 2>/dev/null
rm -f dev/.bot*.pid dev/.platform.pid 2>/dev/null

sleep 1

# 남아있으면 강제
pkill -9 -f "community.platform" 2>/dev/null
pkill -9 -f "community.discord_bot" 2>/dev/null
pkill -9 -f "community.tui.dashboard" 2>/dev/null
pkill -9 -f "community.tools.dev_runner" 2>/dev/null

echo "종료 완료"
