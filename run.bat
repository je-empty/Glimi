@echo off
REM Project Glimi - Windows entry point (run.sh equivalent)
REM
REM Default (platform daemon, FastAPI + web UI):
REM   run.bat                          -> http://localhost:8000
REM   run.bat --port 9000
REM   run.bat --host 127.0.0.1
REM
REM Options (any mode):
REM   --local-models                   -> local LLM mode (dev, opt-in). Auto-install Ollama
REM                                       (winget) + start server + pull tier model.
REM                                       Skips anything already set up.
REM                                       Tier via GLIMI_LOCAL_TIER (default standard):
REM                                         lite=e2b / standard=e4b / quality=iq3-26b single (12GB)
REM                                         / prod=26b+e4b split (24GB+). See docs/local_models.md
REM   --setup-only                     -> run setup (venv/deps/ollama/model) then exit
REM
REM Legacy modes:
REM   run.bat --legacy ^<community^>     -> single bot (QA/debugging)
REM   run.bat tui                      -> legacy TUI wizard
REM   run.bat tui ^<community^>          -> legacy TUI dashboard
REM
REM Stop: Ctrl+C

setlocal EnableDelayedExpansion
chcp 65001 >nul 2>nul
cd /d "%~dp0"

REM === --help before any side effect (venv/deps/cleanup) ===
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help

REM === venv auto setup ===
if not exist .venv (
    echo [setup] Creating virtualenv...
    python -m venv .venv
    if errorlevel 1 (
        echo [setup] venv creation failed. Python 3.11+ required.
        exit /b 1
    )
    echo [setup] Virtualenv created.
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [setup] Virtualenv activation failed.
    exit /b 1
)

set "MARKER=.venv\.deps_installed"
if not exist "%MARKER%" (
    echo [setup] Installing dependencies...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [setup] pip install failed.
        exit /b 1
    )
    pip install -q -e . 2>nul
    echo. > "%MARKER%"
)

REM === load root .env (propagate ANTHROPIC_API_KEY / DISCORD_BOT_TOKEN to platform + child bots) ===
if exist .env (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
)

if not exist dev mkdir dev

REM === common flags (any position): --local-models / --setup-only ===
set "LOCAL_MODELS=0"
set "SETUP_ONLY=0"
echo %* | findstr /C:"--local-models" >nul 2>nul && set "LOCAL_MODELS=1"
echo %* | findstr /C:"--setup-only" >nul 2>nul && set "SETUP_ONLY=1"
if "%GLIMI_LOCAL_MODELS%"=="1" set "LOCAL_MODELS=1"

REM === Ollama 실행파일 해석 (where -> 표준 설치 위치 fallback) ===
set "OLLAMA_BIN="
for /f "delims=" %%i in ('where ollama 2^>nul') do set "OLLAMA_BIN=%%i"
if not defined OLLAMA_BIN if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

REM === --local-models: Ollama 자동 설치 (winget, 1회) ===
if "%LOCAL_MODELS%"=="1" if not defined OLLAMA_BIN (
    where winget >nul 2>nul
    if errorlevel 1 (
        echo [local] Ollama 미설치 + winget 없음 - https://ollama.com/download 에서 설치 후 재실행
        exit /b 1
    )
    echo [local] Ollama 설치 중 ^(winget, 1회^)...
    winget install -e --id Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_BIN=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    if not defined OLLAMA_BIN (
        echo [local] 설치 후에도 실행파일 못 찾음 - 새 터미널에서 재실행 필요할 수 있음
        exit /b 1
    )
)

REM === Ollama 서버 기동 (있을 때만, 안 떠 있으면 시작) ===
if not defined OLLAMA_BIN (
    echo [ollama] 실행파일 못 찾음 - 로컬 LLM 사용 시 --local-models 로 자동 설치 ^(claude 백엔드엔 영향 없음^)
) else (
    "!OLLAMA_BIN!" ps >nul 2>nul
    if errorlevel 1 (
        echo [ollama] 서버 시작 중... ^("!OLLAMA_BIN!"^)
        start "Ollama" /MIN "!OLLAMA_BIN!" serve
        timeout /t 5 /nobreak >nul
    ) else (
        echo [ollama] 이미 실행 중
    )
)

REM === --local-models: 티어별 모델 풀 + 백엔드 env (idempotent) ===
REM   GLIMI_LOCAL_TIER (기본 standard): lite=e2b단일 / standard=e4b단일 /
REM   quality=iq3-26b단일(12GB최적) / prod=26b매니저+e4b분리(24GB+). 상세 docs/local_models.md
set "_E2B=huihui_ai/gemma-4-abliterated:e2b"
set "_E4B=huihui_ai/gemma-4-abliterated:e4b"
set "_IQ3=gemma4-26b-a4b-abl:iq3"
if "%LOCAL_MODELS%"=="1" (
    set "GLIMI_LLM_BACKEND=ollama"
    if not defined OLLAMA_KEEP_ALIVE set "OLLAMA_KEEP_ALIVE=30m"
    if not defined GLIMI_LOCAL_TIER set "GLIMI_LOCAL_TIER=standard"

    set "PULL_MODEL="
    set "IMPORT_MODEL="
    if /i "!GLIMI_LOCAL_TIER!"=="lite"     ( set "PRIMARY=!_E2B!" & set "PULL_MODEL=!_E2B!" )
    if /i "!GLIMI_LOCAL_TIER!"=="standard" ( set "PRIMARY=!_E4B!" & set "PULL_MODEL=!_E4B!" )
    if /i "!GLIMI_LOCAL_TIER!"=="quality"  ( set "PRIMARY=!_IQ3!" & set "IMPORT_MODEL=!_IQ3!" )
    if /i "!GLIMI_LOCAL_TIER!"=="prod" (
        set "PRIMARY=!_E4B!" & set "PULL_MODEL=!_E4B!" & set "IMPORT_MODEL=!_IQ3!"
        if not defined OLLAMA_MAX_LOADED_MODELS set "OLLAMA_MAX_LOADED_MODELS=2"
        if not defined GLIMI_OLLAMA_MODEL_MAP set "GLIMI_OLLAMA_MODEL_MAP={\"mgr\":\"!_IQ3!\",\"creator\":\"!_IQ3!\",\"persona\":\"!_E4B!\",\"_default\":\"!_E4B!\"}"
    )
    if not defined PRIMARY (
        echo [local] 알 수 없는 티어: !GLIMI_LOCAL_TIER! ^(lite^|standard^|quality^|prod^)
        exit /b 1
    )
    if not defined GLIMI_OLLAMA_MODEL set "GLIMI_OLLAMA_MODEL=!PRIMARY!"

    if defined PULL_MODEL (
        "!OLLAMA_BIN!" list 2>nul | findstr /C:"!PULL_MODEL!" >nul
        if errorlevel 1 (
            echo [local] 모델 다운로드: !PULL_MODEL! ^(1회^)
            "!OLLAMA_BIN!" pull "!PULL_MODEL!"
            if errorlevel 1 ( echo [local] 다운로드 실패 & exit /b 1 )
        ) else (
            echo [local] 모델 준비됨: !PULL_MODEL! ^(스킵^)
        )
    )
    if defined IMPORT_MODEL (
        "!OLLAMA_BIN!" list 2>nul | findstr /C:"!IMPORT_MODEL!" >nul
        if errorlevel 1 (
            echo [local] '!GLIMI_LOCAL_TIER!' 티어는 !IMPORT_MODEL! 필요 - GGUF 임포트 후 재실행
            echo   ollama create !IMPORT_MODEL! -f Modelfile  ^(절차: docs/local_models.md^)
            echo   standard^(e4b^)로 폴백하려면 set GLIMI_LOCAL_TIER=standard
            exit /b 1
        )
    )
    echo [local] 로컬 모드 활성 - tier=!GLIMI_LOCAL_TIER!, model=!GLIMI_OLLAMA_MODEL!
    if /i "!GLIMI_LOCAL_TIER!"=="prod" echo   매니저/크리에이터=!_IQ3!, 그 외=!_E4B! ^(분리^)
)

if "%SETUP_ONLY%"=="1" (
    echo [setup] 세팅 완료 ^(--setup-only - 서버는 안 띄움^)
    exit /b 0
)

REM === cleanup existing processes ===
REM Use PowerShell Get-CimInstance for commandline-based process matching (wmic deprecated).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'src\.(platform|discord_bot|tui\.dashboard|tui\.wizard|tools\.dev_runner)' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>nul
del /q dev\.platform.pid 2>nul
del /q dev\.bot*.pid 2>nul
timeout /t 1 /nobreak >nul

echo.
echo === Project Glimi ===
echo.

REM === Legacy TUI mode ===
if "%~1"=="tui" (
    if "%~2"=="" (
        echo   Legacy TUI wizard ^(moved to web platform^)
        python -m src.tui.wizard
    ) else (
        echo   TUI dashboard: %~2
        python -m src.tui.dashboard "%~2"
    )
    exit /b
)

REM === Legacy single-bot mode ===
if "%~1"=="--legacy" (
    if not "%~2"=="" (
        set "GLIMI_COMMUNITY=%~2"
    )
    echo   Legacy single-bot mode
    if defined GLIMI_COMMUNITY (
        echo   Community: !GLIMI_COMMUNITY!
    )
    echo.

    set "CID=!GLIMI_COMMUNITY!"
    if not defined GLIMI_COMMUNITY set "CID=default"
    set "RUNTIME_DIR=communities\!CID!\runtime"
    if not exist "!RUNTIME_DIR!" mkdir "!RUNTIME_DIR!"
    set "PAUSE_FILE=!RUNTIME_DIR!\.bot-paused"
    if exist "!PAUSE_FILE!" del /q "!PAUSE_FILE!"

    :legacy_loop
    if exist "!PAUSE_FILE!" (
        echo [legacy] pause flag - waiting
        :pause_wait
        timeout /t 1 /nobreak >nul
        if exist "!PAUSE_FILE!" goto pause_wait
    )
    echo [legacy] Bot starting
    python -m src.discord_bot
    set "EXIT_CODE=!errorlevel!"

    if !EXIT_CODE! equ 42 (
        echo [legacy] Running dev agent ^(exit 42^)
        python -m src.tools.dev_runner
        echo [legacy] Bot restarting
        timeout /t 2 /nobreak >nul
        goto legacy_loop
    )
    if !EXIT_CODE! equ 0 (
        echo [legacy] Normal exit
        exit /b 0
    )
    echo [legacy] Abnormal exit ^(code !EXIT_CODE!^) - restarting in 5s
    timeout /t 5 /nobreak >nul
    goto legacy_loop
)

REM === Platform mode (default) ===
set "HOST=0.0.0.0"
set "PORT=8000"
if defined GLIMI_HOST set "HOST=%GLIMI_HOST%"
if defined GLIMI_PORT set "PORT=%GLIMI_PORT%"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--host" (set "HOST=%~2" & shift & shift & goto parse_args)
if /i "%~1"=="--port" (set "PORT=%~2" & shift & shift & goto parse_args)
if /i "%~1"=="--local-models" (shift & goto parse_args)
if /i "%~1"=="--setup-only" (shift & goto parse_args)
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help
echo Unknown option: %~1
echo Use --help for usage.
exit /b 1

:show_help
findstr /B /C:"REM" "%~f0"
exit /b 0

:args_done

echo   Glimi Platform
echo   URL: http://%HOST%:%PORT%
echo.

REM === LLM credential check (default Claude path) ===
if not "%LOCAL_MODELS%"=="1" if not defined ANTHROPIC_API_KEY (
    where claude >nul 2>nul
    if errorlevel 1 (
        echo [setup] WARNING: no Claude credential - agents will return empty replies.
        echo   Pick one:
        echo     1^) copy .env.example .env  then fill ANTHROPIC_API_KEY  ^(https://console.anthropic.com/settings/keys^)
        echo     2^) log in with the claude CLI  ^(Claude Code users^)
        echo     3^) local models: run.bat --local-models  ^(no key, docs/local_models.md^)
        echo   Dashboard still starts. Restart after configuring to enable chat.
        echo.
    )
)

REM Bootstrap accounts on first run
python -m src.platform.accounts list >nul 2>nul
if errorlevel 1 (
    python -m src.platform.accounts bootstrap
)

python -m src.platform --host %HOST% --port %PORT%
