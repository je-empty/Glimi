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
REM                                       (winget) + start server + pull default model
REM                                       (gemma4 e4b, ~9.6GB). Skips anything already set up.
REM                                       ENV: GLIMI_LOCAL_MODELS=1 equivalent.
REM                                       Split config (26b manager): docs/local_models.md
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

REM === --local-models: 기본 모델 풀 + 백엔드 env (idempotent) ===
if "%LOCAL_MODELS%"=="1" (
    set "GLIMI_LLM_BACKEND=ollama"
    if not defined GLIMI_OLLAMA_MODEL set "GLIMI_OLLAMA_MODEL=huihui_ai/gemma-4-abliterated:e4b"
    if not defined OLLAMA_KEEP_ALIVE set "OLLAMA_KEEP_ALIVE=30m"
    "!OLLAMA_BIN!" list 2>nul | findstr /C:"!GLIMI_OLLAMA_MODEL!" >nul
    if errorlevel 1 (
        echo [local] 모델 다운로드: !GLIMI_OLLAMA_MODEL! ^(~10GB, 1회^)
        "!OLLAMA_BIN!" pull "!GLIMI_OLLAMA_MODEL!"
        if errorlevel 1 (
            echo [local] 모델 다운로드 실패
            exit /b 1
        )
    ) else (
        echo [local] 모델 준비됨: !GLIMI_OLLAMA_MODEL! ^(스킵^)
    )
    echo [local] 로컬 모델 모드 활성 ^(backend=ollama, model=!GLIMI_OLLAMA_MODEL!^)
    echo   매니저 분리 구성^(26b^): docs/local_models.md
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

REM Bootstrap accounts on first run
python -m src.platform.accounts list >nul 2>nul
if errorlevel 1 (
    python -m src.platform.accounts bootstrap
)

python -m src.platform --host %HOST% --port %PORT%
