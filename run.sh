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
#
# Workspace 앱:
#   ./run.sh workspace [--serve]     → Glimi Workspace (--serve 면 :8800 + 브라우저)
#
# 제거:
#   ./run.sh uninstall               → .venv (+ editable install) 삭제. 사용자 데이터는 보존
#   ./run.sh uninstall --purge       → data/, dev/ 등 로컬 데이터까지 삭제

set -e
cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── --help 는 부작용(venv 생성·deps 설치·프로세스 정리) 전에 즉시 처리 ──
case "${1:-}" in
    --help|-h)
        grep '^#' "$0" | sed -n '2,29p' | sed 's/^# \?//'
        exit 0 ;;
esac

# ── uninstall — 부작용(prereq 설치·venv 생성) 전에 즉시 처리 ──
# 기본: .venv 만 삭제 (editable install + deps 마커가 .venv 안에 있어 함께 사라짐). 사용자 데이터 보존.
# --purge: data/ (platform.db·.setup_complete) + dev/ 도 삭제. 시스템 도구는 절대 자동 제거 안 함 (안내만).
if [ "${1:-}" = "uninstall" ]; then
    PURGE=0; case " $* " in *" --purge "*) PURGE=1;; esac
    echo -e "${CYAN}◈ Glimi uninstall${NC}"
    if [ -d .venv ]; then
        rm -rf .venv
        echo -e "${GREEN}[uninstall] .venv 삭제됨 (editable 'pip install -e .' + deps 마커 포함)${NC}"
    else
        echo -e "${YELLOW}[uninstall] .venv 없음 (이미 제거됨)${NC}"
    fi
    if [ "$PURGE" = "1" ]; then
        rm -rf data dev
        echo -e "${GREEN}[uninstall] --purge: data/ (platform.db·.setup_complete), dev/ 삭제됨${NC}"
        echo -e "${YELLOW}  남은 사용자 데이터: communities/*/runtime, 흩어진 *.db 는 직접 확인/삭제${NC}"
    else
        echo -e "${YELLOW}[uninstall] 사용자 데이터 보존: data/, dev/, communities/*/runtime, *.db${NC}"
        echo -e "  로컬 데이터까지 지우려면: ${CYAN}./run.sh uninstall --purge${NC}"
    fi
    echo ""
    echo -e "${CYAN}런처가 자동 설치했을 수 있는 시스템 도구는 직접 제거하세요 (자동 제거 안 함):${NC}"
    echo -e "  ${CYAN}brew uninstall ollama${NC}"
    echo -e "  ${CYAN}brew uninstall node${NC}"
    echo -e "  ${CYAN}brew uninstall python@3.12${NC}"
    echo -e "  ${CYAN}npm uninstall -g @anthropic-ai/claude-code${NC}"
    echo -e "  Homebrew 자체: 공식 uninstall 스크립트 참고 (https://brew.sh)"
    echo ""
    echo -e "${GREEN}Glimi 제거됨 (프로젝트 파일은 그대로 — 완전 삭제는 이 폴더를 지우세요).${NC}"
    exit 0
fi

# ── (macOS) 부족한 prereq 자동 설치 — 별도 bootstrap 없이 ./run.sh 한 줄로 끝나게 ──
# 이미 있으면 즉시 통과(빠름). Python 3.11+ 가 없을 때만 Homebrew→Python 설치, Claude CLI 는
# 클라우드 응답용으로 best-effort(로컬모델이면 생략). 비-macOS 는 각자 패키지매니저/ run.bat.
_ensure_prereqs() {
    [ "$(uname)" = "Darwin" ] || return 0
    _LM=0; case " $* " in *" --local-models "*) _LM=1;; esac
    _havepy=0
    if command -v python3.12 >/dev/null 2>&1 || command -v python3.11 >/dev/null 2>&1 \
       || python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)' 2>/dev/null; then
        _havepy=1
    fi
    # 핵심(파이썬) + (클라우드면 claude) 다 있으면 바로 통과
    if [ "$_havepy" = "1" ] && { [ "$_LM" = "1" ] || command -v claude >/dev/null 2>&1; }; then
        return 0
    fi
    if ! command -v brew >/dev/null 2>&1; then
        echo -e "${CYAN}[setup] Homebrew 설치 중 (확인·비밀번호를 물어볼 수 있음)...${NC}"
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
            || echo -e "${YELLOW}[setup] Homebrew 설치 실패 — 수동: https://brew.sh${NC}"
    fi
    for _b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$_b" ] && eval "$("$_b" shellenv)" && break; done
    if [ "$_havepy" = "0" ] && command -v brew >/dev/null 2>&1; then
        echo -e "${CYAN}[setup] Python 3.12 설치 중...${NC}"; brew install python@3.12 || true
    fi
    if [ "$_LM" != "1" ] && ! command -v claude >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
        command -v node >/dev/null 2>&1 || { echo -e "${CYAN}[setup] Node 설치 중...${NC}"; brew install node || true; }
        echo -e "${CYAN}[setup] Claude CLI 설치 중...${NC}"; npm install -g @anthropic-ai/claude-code 2>/dev/null \
            || echo -e "${YELLOW}[setup] Claude CLI 설치 실패 — .env 의 ANTHROPIC_API_KEY 또는 --local-models 로 대체 가능${NC}"
    fi
}
_ensure_prereqs "$@"

# ── 자동 세팅 ──────────────────────────────────────────
if [ ! -d .venv ]; then
    echo -e "${CYAN}[setup] 가상환경 생성 중...${NC}"
    # 3.11+ 인 인터프리터를 우선순위로 선택 (시스템 python3 가 구버전일 수 있음).
    PY=""
    for _cand in python3.12 python3.11 python3; do
        if command -v "$_cand" >/dev/null 2>&1 && \
           "$_cand" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)' 2>/dev/null; then
            PY="$_cand"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo -e "${RED}[setup] Python 3.11+ 필요 — 미설치/구버전. macOS 면 ${CYAN}./scripts/bootstrap.sh${RED} 가 자동 설치, 아니면 https://www.python.org/downloads/${NC}"; exit 1
    fi
    "$PY" -m venv .venv || { echo -e "${RED}[setup] venv 생성 실패 ($PY)${NC}"; exit 1; }
    echo -e "${GREEN}[setup] 가상환경 생성 완료 ($PY)${NC}"
fi
source .venv/bin/activate

# ── 루트 .env 로드 ────────────────────────────────────
# 여기서 export 하면 플랫폼 + 자식 봇 프로세스가 상속 (ANTHROPIC_API_KEY / DISCORD_BOT_TOKEN 등).
# 커뮤니티별 .env 는 자식 봇이 override=True 로 다시 로드하므로 충돌 없음.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env 2>/dev/null || echo -e "${YELLOW}[setup] .env 파싱 경고 — 형식 확인${NC}"
    set +a
fi

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
# 티어 (GLIMI_LOCAL_TIER, 기본 standard) — 상세: docs/local_models.md
#   lite     = e2b 단일      (8GB VRAM / 16GB Mac)  · 최속, 도구 정확도 낮음
#   standard = e4b 단일      (12GB VRAM / 16GB Mac) · 균형 (기본)
#   quality  = iq3-26b 단일  (12GB VRAM / 24GB Mac) · 도구 3/3, 약간 오프로드. ※IQ3 gguf 임포트 필요
#   prod     = 26b 매니저 + e4b 그 외 분리 (24GB+ VRAM / 32GB Mac) · 최고품질. ※IQ3 임포트 필요
_E2B="huihui_ai/gemma-4-abliterated:e2b"
_E4B="huihui_ai/gemma-4-abliterated:e4b"
_IQ3="gemma4-26b-a4b-abl:iq3"
if [ "$LOCAL_MODELS" = "1" ]; then
    export GLIMI_LLM_BACKEND=ollama
    export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
    TIER="${GLIMI_LOCAL_TIER:-standard}"

    PULL_MODEL=""       # ollama pull 로 받을 모델 (레지스트리)
    IMPORT_MODEL=""     # gguf 임포트 필요 모델 (pull 불가)
    case "$TIER" in
        lite)     PRIMARY="$_E2B"; PULL_MODEL="$_E2B" ;;
        standard) PRIMARY="$_E4B"; PULL_MODEL="$_E4B" ;;
        quality)  PRIMARY="$_IQ3"; IMPORT_MODEL="$_IQ3" ;;
        prod)     PRIMARY="$_E4B"; PULL_MODEL="$_E4B"; IMPORT_MODEL="$_IQ3"
                  export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-2}"
                  export GLIMI_OLLAMA_MODEL_MAP="${GLIMI_OLLAMA_MODEL_MAP:-{\"mgr\":\"$_IQ3\",\"creator\":\"$_IQ3\",\"persona\":\"$_E4B\",\"_default\":\"$_E4B\"}}" ;;
        *) echo -e "${RED}[local] 알 수 없는 티어: $TIER (lite|standard|quality|prod)${NC}"; exit 1 ;;
    esac
    export GLIMI_OLLAMA_MODEL="${GLIMI_OLLAMA_MODEL:-$PRIMARY}"

    # 1) Ollama 설치 — 없으면 brew
    if ! command -v ollama >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            echo -e "${CYAN}[local] Ollama 설치 중 (brew)...${NC}"
            brew install ollama || { echo -e "${RED}[local] Ollama 설치 실패${NC}"; exit 1; }
        else
            echo -e "${RED}[local] Ollama 미설치 + Homebrew 없음 — https://ollama.com/download${NC}"; exit 1
        fi
    fi

    # 2) 서버 기동
    if ! ollama ps >/dev/null 2>&1; then
        echo -e "${CYAN}[local] Ollama 서버 시작...${NC}"
        nohup ollama serve > /tmp/ollama-serve.log 2>&1 &
        for _i in $(seq 1 15); do ollama ps >/dev/null 2>&1 && break; sleep 1; done
        ollama ps >/dev/null 2>&1 || { echo -e "${RED}[local] Ollama 서버 시작 실패 (/tmp/ollama-serve.log)${NC}"; exit 1; }
    fi

    # 3) pull 모델 (idempotent)
    if [ -n "$PULL_MODEL" ]; then
        if ollama list 2>/dev/null | grep -Fq "$PULL_MODEL"; then
            echo -e "${GREEN}[local] 모델 준비됨: ${PULL_MODEL} (스킵)${NC}"
        else
            echo -e "${CYAN}[local] 모델 다운로드: ${PULL_MODEL} (1회)${NC}"
            ollama pull "$PULL_MODEL" || { echo -e "${RED}[local] 다운로드 실패${NC}"; exit 1; }
        fi
    fi

    # 4) 임포트 필요 모델 — 레지스트리에 없으므로 자동 다운로드 불가. 안내만.
    if [ -n "$IMPORT_MODEL" ] && ! ollama list 2>/dev/null | grep -Fq "$IMPORT_MODEL"; then
        echo -e "${YELLOW}[local] '${TIER}' 티어는 ${IMPORT_MODEL} 가 필요한데 미등록.${NC}"
        echo -e "  GGUF 임포트 후 다시 실행: ${CYAN}ollama create ${IMPORT_MODEL} -f Modelfile${NC}"
        echo -e "  (절차: docs/local_models.md) — 우선 standard(e4b)로 폴백하려면 GLIMI_LOCAL_TIER=standard"
        exit 1
    fi

    echo -e "${GREEN}[local] 로컬 모드 활성 — tier=${TIER}, model=${GLIMI_OLLAMA_MODEL}${NC}"
    [ "$TIER" = "prod" ] && echo -e "  매니저/크리에이터=${_IQ3}, 그 외=${_E4B} (분리)"
fi

if [ "$SETUP_ONLY" = "1" ]; then
    echo -e "${GREEN}[setup] 세팅 완료 (--setup-only — 서버는 안 띄움)${NC}"
    exit 0
fi

mkdir -p dev

# ── 기존 프로세스 정리 ────────────────────────────────
_cleanup_existing() {
    pkill -f "community.platform" 2>/dev/null || true
    pkill -f "community.discord_bot" 2>/dev/null || true
    pkill -f "community.tui.dashboard" 2>/dev/null || true
    pkill -f "community.tui.wizard" 2>/dev/null || true
    pkill -f "community.tools.dev_runner" 2>/dev/null || true
    pkill -f "workspace/run.py" 2>/dev/null || true
    rm -f dev/.bot*.pid dev/.platform.pid 2>/dev/null || true
    sleep 1
    pkill -9 -f "community.platform" 2>/dev/null || true
    pkill -9 -f "community.discord_bot" 2>/dev/null || true
    pkill -9 -f "community.tui.dashboard" 2>/dev/null || true
}
_cleanup_existing

echo -e "${CYAN}◈ Project Glimi${NC}"

# ── 레거시 TUI ────────────────────────────────────────
if [ "$1" = "tui" ]; then
    shift
    if [ -z "$1" ]; then
        echo -e "${YELLOW}  (레거시 TUI wizard — 플랫폼 웹으로 이전됨)${NC}"
        exec python -m community.tui.wizard
    else
        echo -e "  TUI dashboard: ${GREEN}$1${NC}"
        exec python -m community.tui.dashboard "$1"
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
        python -m community.discord_bot &
        BOT_PID=$!
        echo $BOT_PID > "$PID_FILE"
        wait $BOT_PID
        EXIT_CODE=$?
        rm -f "$PID_FILE"

        if [ $EXIT_CODE -eq 42 ]; then
            echo -e "${CYAN}[legacy] 개발자 에이전트 실행${NC}"
            python -m community.tools.dev_runner
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

# ── Glimi Workspace 앱 모드 ───────────────────────────
# ./run.sh workspace [--server|--serve|--demo] [--name X] [--goal "..."] [--backend echo|claude_cli|ollama]
# 같은 venv·커널(glimi)로 workspace 를 실행.
#   (기본)   : --server — 멀티 워크스페이스 호스트(홈 + N 워크스페이스 대시보드). 사람용 기본값.
#   --server : 워크스페이스 목록(읽기전용 Demo + 생성분) + 워크스페이스별 대시보드 + 생성 폼.
#   --serve  : 작업을 한 번 돌린 뒤 그 팀을 대시보드(:8800)로 서빙 + 브라우저 자동 오픈.
#   --demo   : 시드된 실시간 LIVE 데모(자동으로 계속 업데이트되는 런치 팀)를 서빙 (오프라인, 키 불필요).
if [ "$1" = "workspace" ]; then
    shift
    WS_PORT="${GLIMI_WS_PORT:-8800}"
    echo -e "${CYAN}◈ Glimi Workspace${NC}"
    # 셸 런처(사람) 기본값: --serve/--demo/--server 가 하나도 없으면 멀티 워크스페이스 서버를
    # 띄운다. (모듈 직접 실행 `python -m workspace.run` 은 손대지 않음 — 테스트의 1회성
    # CLI 디폴트 유지.)
    case " $* " in
        *" --serve "*|*" --demo "*|*" --server "*) : ;;
        *) set -- --server "$@" ;;
    esac
    case " $* " in
        *" --serve "*|*" --demo "*|*" --server "*)
            echo -e "  대시보드: ${GREEN}http://127.0.0.1:${WS_PORT}${NC}"
            # --server 는 홈 API(/api/workspaces), --serve/--demo 는 단일 스토어
            # 대시보드(/api/snapshot) 로 준비 상태를 확인.
            _probe="/api/snapshot"
            case " $* " in *" --server "*) _probe="/api/workspaces" ;; esac
            if [ -z "${GLIMI_NO_BROWSER:-}" ]; then
                (
                    for _ in $(seq 1 60); do
                        curl -s -o /dev/null "http://127.0.0.1:${WS_PORT}${_probe}" 2>/dev/null && break
                        sleep 0.5
                    done
                    _u="http://127.0.0.1:${WS_PORT}"
                    if command -v open >/dev/null 2>&1; then open "$_u"
                    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$_u"; fi
                ) &
            fi
            ;;
    esac
    # -m (모듈 실행) → repo 루트가 sys.path 에 올라가 glimi/src 가 잡힘 (Community 의 -m 패턴과 동일).
    exec python -m workspace.run "$@"
fi

# ── 플랫폼 모드 = Glimi Community 앱 (기본) ─────────────
# `./run.sh community` (명시) 또는 `./run.sh` (기본) 둘 다 여기로 온다.
if [ "$1" = "community" ]; then shift; fi
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

# ── 첫 실행 판정 ──────────────────────────────────────
# 설정 마커도 platform.db 도 없으면 첫 실행 → 브라우저 setup wizard 로 안내.
_FIRST_RUN=0
if [ ! -f data/.setup_complete ] && [ ! -f data/platform.db ] && [ -z "${GLIMI_ADMIN_PASSWORD:-}" ]; then
    _FIRST_RUN=1
fi

# ── LLM 자격증명 점검 (이미 설정된 설치인데 키 없을 때만) ──
if [ "$_FIRST_RUN" != "1" ] && [ "$LOCAL_MODELS" != "1" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && ! command -v claude >/dev/null 2>&1; then
    echo -e "${YELLOW}[setup] ⚠ Claude 자격증명이 없다 — 에이전트가 응답을 못 만든다.${NC}"
    echo -e "  다음 중 하나:"
    echo -e "    1) ${CYAN}cp .env.example .env${NC} 후 ${CYAN}ANTHROPIC_API_KEY${NC} 채우기 (https://console.anthropic.com/settings/keys)"
    echo -e "    2) ${CYAN}claude${NC} CLI 로그인 (Claude Code 사용자)"
    echo -e "    3) 로컬 모델로: ${CYAN}./run.sh --local-models${NC}  (키 불필요, docs/local_models.md)"
    echo -e "  대시보드는 계속 뜬다. 위 설정 후 재시작하면 대화가 동작.${NC}"
    echo ""
fi

# ── 첫 실행 시 브라우저 자동 오픈 (서버 뜨면 /setup) ──
# 헤드리스/원격(tmux·SSH)에서는 GLIMI_NO_BROWSER=1 로 끈다.
if [ "$_FIRST_RUN" = "1" ] && [ -z "${GLIMI_NO_BROWSER:-}" ]; then
    echo -e "${CYAN}[setup] 첫 실행 — 브라우저에서 초기 설정 화면을 엽니다.${NC}"
    (
        for _ in $(seq 1 40); do
            curl -s -o /dev/null "http://localhost:${PORT}/healthz" 2>/dev/null && break
            sleep 0.5
        done
        _url="http://localhost:${PORT}/setup"
        if command -v open >/dev/null 2>&1; then open "$_url"
        elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$_url"
        fi
    ) &
fi

# 계정 부트스트랩은 더 이상 여기서 안 함 — 첫 실행은 웹 wizard(/setup), 헤드리스는
# 플랫폼 lifespan 이 GLIMI_ADMIN_PASSWORD 로 처리.
exec python -m community.platform --host "$HOST" --port "$PORT"
