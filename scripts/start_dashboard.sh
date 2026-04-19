#!/bin/bash
# Glimi Web Dashboard — tmux 세션으로 상시 가동
#
# 사용:
#   ./scripts/start_dashboard.sh            # 기본 community (private) 로 시작
#   ./scripts/start_dashboard.sh qa         # 특정 community 로 시작
#   ./scripts/start_dashboard.sh stop       # 세션 종료
#   ./scripts/start_dashboard.sh attach     # 세션에 붙기 (로그 실시간)
#
# 특성:
#   - tmux detached 세션 → SSH 끊어도 계속 돔
#   - 크래시 시 3초 후 자동 재시작 (while true 루프)
#   - 재부팅 시에는 끊김 — 필요 시 사용자가 쉘 rc에 이 스크립트 호출 추가
#
# launchd 안 쓰는 이유:
#   macOS TCC 가 ~/Documents 내 실행파일에 launchd 접근 차단 → 'Operation not permitted'.
#   사용자가 "Full Disk Access" 로 launchd/bash 허용하면 가능하지만 GUI 수동 조작 필요.
#   tmux 는 로그인 세션이 이미 TCC 권한 상속하므로 바로 동작.

set -e
cd "$(dirname "$0")/.."

# macOS 기본 ulimit -n 이 256 으로 낮아서 장시간 구동 시 EMFILE (Too many open files).
# SQLite 커넥션 사이클 + 주기적 API 호출로 일시적 FD 사용량이 증가.
ulimit -n 4096 2>/dev/null || true

SESSION="Glimi-Dashboard"
COMMUNITY="${1:-private}"
# 모든 인터페이스 바인딩 — LAN (다른 PC/폰) + 외부 포트포워딩 둘 다 접근 가능.
# 로컬 전용으로 돌리고 싶으면 환경변수 GLIMI_DASHBOARD_HOST=127.0.0.1 로 오버라이드.
DASHBOARD_HOST="${GLIMI_DASHBOARD_HOST:-0.0.0.0}"

# Homebrew PATH 보강 (non-interactive SSH 대비)
for p in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
    [ -d "$p" ] && [[ ":$PATH:" != *":$p:"* ]] && PATH="$p:$PATH"
done
export PATH

case "$COMMUNITY" in
    stop|kill)
        tmux kill-session -t "$SESSION" 2>/dev/null && echo "[$SESSION] 종료" || echo "[$SESSION] 실행 중 아님"
        exit 0
        ;;
    attach|a)
        tmux attach -t "$SESSION"
        exit 0
        ;;
    status)
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            echo "[$SESSION] 실행 중"
            curl -s -o /dev/null -w "HTTP %{http_code}  http://127.0.0.1:8765/\n" --max-time 3 http://127.0.0.1:8765/ || echo "  (응답 없음)"
        else
            echo "[$SESSION] 꺼짐"
        fi
        exit 0
        ;;
esac

# 이미 세션 있으면 재시작
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[$SESSION] 이미 실행 중 — 재시작"
    tmux kill-session -t "$SESSION"
    sleep 1
fi

mkdir -p ~/Library/Logs

# 재시작 루프로 래핑
# ulimit 을 tmux 명령 안에 두어야 함 — tmux server 가 parent shell ulimit 상속 안 함.
tmux new-session -d -s "$SESSION" -n runner \
    "ulimit -n 4096 2>/dev/null; cd $(pwd); while true; do source .venv/bin/activate 2>/dev/null; python scripts/web_dashboard.py '$COMMUNITY' --host '$DASHBOARD_HOST' 2>&1 | tee -a ~/Library/Logs/glimi-dashboard.log; echo '[dashboard] 3초 후 재시작'; sleep 3; done"

sleep 3
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[$SESSION] 시작 (community=$COMMUNITY, host=$DASHBOARD_HOST)"
    echo "  로컬:    http://127.0.0.1:8765/"
    if [ "$DASHBOARD_HOST" = "0.0.0.0" ]; then
        # LAN IP 감지 — 내부망 기기에서 접근용
        LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
        [ -n "$LAN_IP" ] && echo "  LAN:     http://$LAN_IP:8765/"
        echo "  외부:    포트포워딩된 공용 IP/도메인:8765"
    fi
    echo "  로그: tail -f ~/Library/Logs/glimi-dashboard.log"
    echo "  붙기: ./scripts/start_dashboard.sh attach"
    echo "  종료: ./scripts/start_dashboard.sh stop"
else
    echo "[$SESSION] 시작 실패"
    exit 1
fi
