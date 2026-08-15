@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ── 语言检测：仅中文系统区域显示中文，其他情况一律英文 ──────────
set "ZH=0"
set "SYS_LOCALE="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-WinSystemLocale).Name" 2^>nul') do set "SYS_LOCALE=%%i"
if not defined SYS_LOCALE (
    for /f "tokens=2 delims==" %%i in ('wmic os get locale /value ^| findstr "="') do set "SYS_LOCALE=%%i"
)
set "SYS_LOCALE=%SYS_LOCALE: =%"
if not defined SYS_LOCALE set "SYS_LOCALE=en-US"
echo %SYS_LOCALE% | findstr /i "^zh" >nul && set "ZH=1"

echo ================================================
call :msg "   Agnes Video Generator - 免费 AI 短视频生成" "   Agnes Video Generator - Free AI Short Video Generator"
call :msg "   (Windows 一键启动)" "   (One-click launch for Windows)"
echo ================================================
echo.

REM ── 环境校验 ────────────────────────────────
where python >nul 2>nul
if errorlevel 1 (
    call :msg "[X] 未找到 python，请先安装 Python 3.10+：https://www.python.org/downloads/" "[X] python not found. Please install Python 3.10+: https://www.python.org/downloads/"
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    python --version
    call :msg "[X] Python 版本过低，需要 3.10+" "[X] Python version too old. Required: 3.10+"
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    call :msg "[X] 未找到 ffmpeg，视频处理依赖 ffmpeg" "[X] ffmpeg not found. Video processing requires ffmpeg:"
    call :msg "     安装方式：winget install Gyan.FFmpeg   （安装后请重新打开终端）" "     Install: winget install Gyan.FFmpeg   (restart terminal afterwards)"
    call :msg "     或前往 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH" "     Or download from https://www.gyan.dev/ffmpeg/builds/ and add to PATH"
    pause
    exit /b 1
)

REM 检查端口 8765 是否被占用
netstat -ano | findstr ":8765" >nul 2>nul
if not errorlevel 1 (
    call :msg "[W] 端口 8765 已被占用，请先关闭占用进程后重试" "[W] Port 8765 is already in use. Close the occupying process and retry."
    pause
    exit /b 1
)

call :msg "[OK] 环境检查通过" "[OK] Environment check passed"
echo.

set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_PYTHON%" (
    call :msg "[1/3] 创建虚拟环境..." "[1/3] Creating virtual environment..."
    python -m venv "%VENV_DIR%"
)

call :msg "[2/3] 安装依赖..." "[2/3] Installing dependencies..."
"%VENV_PIP%" install -q -r requirements.txt
if errorlevel 1 (
    call :msg "[X] 依赖安装失败，请检查网络后重试" "[X] Dependency installation failed. Check your network and retry."
    pause
    exit /b 1
)

call :msg "[3/3] 启动服务..." "[3/3] Starting server..."
echo.
call :msg "   浏览器将自动打开 http://localhost:8765" "   The browser will open http://localhost:8765 automatically"
call :msg "   按 Ctrl+C 停止服务" "   Press Ctrl+C to stop the server"
echo.

REM 延迟 3 秒后打开浏览器（服务启动中）
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8765"

"%VENV_PYTHON%" server.py

echo.
call :msg "服务已停止。" "Server stopped."
pause
endlocal
goto :EOF

REM ── 双语消息子程序：call :msg "中文" "English" ──────────
:msg
if "%ZH%"=="1" (
    echo %~1
) else (
    echo %~2
)
exit /b
