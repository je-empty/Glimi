#!/bin/bash
# launchd wrapper — venv 활성화 + 대시보드 실행
cd /Users/jbsim/Documents/GitHub/Glimi
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Users/jbsim/.local/bin
source .venv/bin/activate
exec python scripts/web_dashboard.py "${1:-private}"
