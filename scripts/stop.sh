#!/bin/bash
# Project Glimi — 전체 종료 (웹 플랫폼 + dev runner)
cd "$(dirname "$0")/.."

echo "Glimi 종료중..."
pkill -f "community.platform" 2>/dev/null
pkill -f "community.tools.dev_runner" 2>/dev/null
rm -f dev/.platform.pid 2>/dev/null

sleep 1

# 남아있으면 강제
pkill -9 -f "community.platform" 2>/dev/null
pkill -9 -f "community.tools.dev_runner" 2>/dev/null

echo "종료 완료"
