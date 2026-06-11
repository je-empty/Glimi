#!/bin/bash
# Project Glimi — 메인 진입점
#
# 기본 (플랫폼 데몬, FastAPI + 웹 UI):
#   ./run.sh                         → http://localhost:8000
#   ./run.sh --port 9000
#   ./run.sh --host 127.0.0.1
#
# 옵션 (어디서나 사용 가능):
#   --imagegen                       → 로컬 LoRA 프로필 이미지 생성 활성화
#                                       (1회: torch+diffusers ~수GB 설치 + Animagine XL 4.0 ~6.5GB
#                                        HF cache 다운로드. ENV: GLIMI_IMAGEGEN=1 도 동등)
#   --local-models                   → 로컬 LLM 모드 (개발중, opt-in). Ollama 자동 설치(brew) +
#                                       서버 기동 + 기본 모델(gemma4 e4b, ~9.6GB) 다운로드.
#                                       이미 설치/다운로드된 건 스킵. ENV: GLIMI_LOCAL_MODELS=1 동등.
#                                       매니저 분리 구성 등 상세: docs/local_models.md
#   --setup-only                     → 세팅(venv/deps/ollama/모델)만 하고 서버는 안 띄움
#
# 레거시 모드:
#   ./run.sh --legacy <community>    → 구 단일 봇 (QA/디버깅용)
#   ./run.sh tui                     → 구 TUI wizard (deprecated)
#   ./run.sh tui <community>         → 구 TUI dashboard

set -e
cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 자동 세팅 ──────────────────────────────────────────
if [ ! -d .venv ]; then
    echo -e "${CYAN}[setup] 가상환경 생성 중...${NC}"
    python3 -m venv .venv || { echo -e "${RED}[setup] venv 생성 실패. Python 3.11+ 필요${NC}"; exit 1; }
    echo -e "${GREEN}[setup] 가상환경 생성 완료${NC}"
fi
source .venv/bin/activate

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    pip install -q -r requirements.txt && pip install -q -e . 2>/dev/null
    touch "$MARKER"
fi

# ── 공통 플래그 추출 (모든 mode 공통, 위치 무관) ─────────
IMAGEGEN=0
LOCAL_MODELS=0
SETUP_ONLY=0
_FILTERED_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --imagegen)     IMAGEGEN=1;;
        --local-models) LOCAL_MODELS=1;;
        --setup-only)   SETUP_ONLY=1;;
        *)              _FILTERED_ARGS+=("$arg");;
    esac
done
set -- "${_FILTERED_ARGS[@]}"
# ENV 로 사전 활성화한 경우도 동일 처리
if [ "${GLIMI_IMAGEGEN:-0}" = "1" ] || [ "${GLIMI_IMAGEGEN:-}" = "true" ]; then
    IMAGEGEN=1
fi
if [ "${GLIMI_LOCAL_MODELS:-0}" = "1" ] || [ "${GLIMI_LOCAL_MODELS:-}" = "true" ]; then
    LOCAL_MODELS=1
fi

if [ "$IMAGEGEN" = "1" ]; then
    export GLIMI_IMAGEGEN=1
    IMAGEGEN_MARKER=".venv/.imagegen_installed"
    if [ ! -f "$IMAGEGEN_MARKER" ]; then
        echo -e "${CYAN}[imagegen] 1회 deps 설치 (torch + diffusers ~수 GB, ~5분)...${NC}"
        if pip install -q -e ".[imagegen]"; then
            touch "$IMAGEGEN_MARKER"
            echo -e "${GREEN}[imagegen] 활성화 완료. 첫 호출 시 Animagine XL 4.0 (~6.5GB) HF cache 다운로드.${NC}"
        else
            echo -e "${RED}[imagegen] deps 설치 실패 — 비활성으로 진행${NC}"
            unset GLIMI_IMAGEGEN
            IMAGEGEN=0
        fi
    else
        echo -e "${GREEN}[imagegen] 활성 (GLIMI_IMAGEGEN=1)${NC}"
    fi
fi

# ── --local-models: Ollama 로컬 LLM 자동 세팅 (idempotent) ──
if [ "$LOCAL_MODELS" = "1" ]; then
    export GLIMI_LLM_BACKEND=ollama
    export GLIMI_OLLAMA_MODEL="${GLIMI_OLLAMA_MODEL:-huihui_ai/gemma-4-abliterated:e4b}"
    export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

    # 1) Ollama 설치 확인 — 없으면 brew 로 설치
    if ! command -v ollama >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            echo -e "${CYAN}[local] Ollama 설치 중 (brew)...${NC}"
            brew install ollama || { echo -e "${RED}[local] Ollama 설치 실패${NC}"; exit 1; }
        else
            echo -e "${RED}[local] Ollama 미설치 + Homebrew 없음${NC}"
            echo -e "  https://ollama.com/download 에서 설치 후 다시 실행하세요"
            exit 1
        fi
    fi

    # 2) 서버 기동 확인 — 안 떠 있으면 백그라운드 시작
    if ! ollama ps >/dev/null 2>&1; then
        echo -e "${CYAN}[local] Ollama 서버 시작...${NC}"
        nohup ollama serve > /tmp/ollama-serve.log 2>&1 &
        for _i in $(seq 1 15); do
            ollama ps >/dev/null 2>&1 && break
            sleep 1
        done
        ollama ps >/dev/null 2>&1 || { echo -e "${RED}[local] Ollama 서버 시작 실패 (/tmp/ollama-serve.log)${NC}"; exit 1; }
    fi

    # 3) 기본 모델 — 이미 있으면 스킵
    if ollama list 2>/dev/null | grep -Fq "$GLIMI_OLLAMA_MODEL"; then
        echo -e "${GREEN}[local] 모델 준비됨: ${GLIMI_OLLAMA_MODEL} (스킵)${NC}"
    else
        echo -e "${CYAN}[local] 모델 다운로드: ${GLIMI_OLLAMA_MODEL} (~10GB, 1회)${NC}"
        ollama pull "$GLIMI_OLLAMA_MODEL" || { echo -e "${RED}[local] 모델 다운로드 실패${NC}"; exit 1; }
    fi
    echo -e "${GREEN}[local] 로컬 모델 모드 활성 (backend=ollama, model=${GLIMI_OLLAMA_MODEL})${NC}"
    echo -e "  매니저 정확도용 분리 구성(26b)은 docs/local_models.md 참고"
fi

if [ "$SETUP_ONLY" = "1" ]; then
    echo -e "${GREEN}[setup] 세팅 완료 (--setup-only — 서버는 안 띄움)${NC}"
    exit 0
fi

mkdir -p dev

# ── 기존 프로세스 정리 ────────────────────────────────
_cleanup_existing() {
    pkill -f "src.platform" 2>/dev/null || true
    pkill -f "src.discord_bot" 2>/dev/null || true
    pkill -f "src.tui.dashboard" 2>/dev/null || true
    pkill -f "src.tui.wizard" 2>/dev/null || true
    pkill -f "src.tools.dev_runner" 2>/dev/null || true
    rm -f dev/.bot*.pid dev/.platform.pid 2>/dev/null || true
    sleep 1
    pkill -9 -f "src.platform" 2>/dev/null || true
    pkill -9 -f "src.discord_bot" 2>/dev/null || true
    pkill -9 -f "src.tui.dashboard" 2>/dev/null || true
}
_cleanup_existing

echo -e "${CYAN}◈ Project Glimi${NC}"

# ── 레거시 TUI ────────────────────────────────────────
if [ "$1" = "tui" ]; then
    shift
    if [ -z "$1" ]; then
        echo -e "${YELLOW}  (레거시 TUI wizard — 플랫폼 웹으로 이전됨)${NC}"
        exec python -m src.tui.wizard
    else
        echo -e "  TUI dashboard: ${GREEN}$1${NC}"
        exec python -m src.tui.dashboard "$1"
    fi
fi

# ── 레거시 단일 봇 ────────────────────────────────────
if [ "$1" = "--legacy" ]; then
    shift
    if [ -n "$1" ]; then
        export GLIMI_COMMUNITY="$1"
        shift
    fi
    echo -e "${YELLOW}  레거시 단일 봇 모드${NC}"
    if [ -n "$GLIMI_COMMUNITY" ]; then
        echo -e "  커뮤니티: ${GREEN}${GLIMI_COMMUNITY}${NC}"
    fi
    echo ""

    # 레거시 모드용 런타임 파일 — 커뮤니티 디렉토리 안에 격리 (루트 공유 금지)
    CID="${GLIMI_COMMUNITY:-default}"
    RUNTIME_DIR="communities/${CID}/runtime"
    mkdir -p "$RUNTIME_DIR"
    PID_FILE="${RUNTIME_DIR}/.bot.pid"
    PAUSE_FILE="${RUNTIME_DIR}/.bot-paused"
    rm -f "$PAUSE_FILE"

    _leg_cleanup() {
        echo -e "\n${YELLOW}종료${NC}"
        [ -f "$PID_FILE" ] && kill "$(cat $PID_FILE)" 2>/dev/null && rm -f "$PID_FILE"
        exit 0
    }
    trap _leg_cleanup SIGINT SIGTERM

    while true; do
        if [ -f "$PAUSE_FILE" ]; then
            echo -e "${YELLOW}[legacy] pause flag — 대기${NC}"
            while [ -f "$PAUSE_FILE" ]; do sleep 1; done
        fi
        echo -e "${GREEN}[legacy] 봇 시작${NC}"
        python -m src.discord_bot &
        BOT_PID=$!
        echo $BOT_PID > "$PID_FILE"
        wait $BOT_PID
        EXIT_CODE=$?
        rm -f "$PID_FILE"

        if [ $EXIT_CODE -eq 42 ]; then
            echo -e "${CYAN}[legacy] 개발자 에이전트 실행${NC}"
            python -m src.tools.dev_runner
            echo -e "${GREEN}[legacy] 봇 재시작${NC}"
            sleep 2
            continue
        fi
        if [ $EXIT_CODE -eq 0 ]; then
            echo -e "${GREEN}[legacy] 정상 종료${NC}"
            break
        fi
        echo -e "${RED}[legacy] 비정상 종료 — 5초 후 재시작${NC}"
        sleep 5
    done
    exit 0
fi

# ── 플랫폼 모드 (기본) ─────────────────────────────────
HOST="${GLIMI_HOST:-0.0.0.0}"
PORT="${GLIMI_PORT:-8000}"
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2;;
        --port) PORT="$2"; shift 2;;
        --help|-h)
            grep '^#' "$0" | head -15 | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo -e "${RED}알 수 없는 옵션: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}◈ Glimi Platform${NC}"
echo -e "  URL: ${GREEN}http://${HOST}:${PORT}${NC}"
echo ""

python -m src.platform.accounts list > /dev/null 2>&1 || python -m src.platform.accounts bootstrap

exec python -m src.platform --host "$HOST" --port "$PORT"
