@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ================================================
echo    Agnes Video Generator - 免费 AI 短视频生成
echo    (Windows 一键启动)
echo ================================================
echo.

REM ── 环境校验 ────────────────────────────────
where python >nul 2>nul
if errorlevel 1 (
    echo [X] 未找到 python，请先安装 Python 3.10+：https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    python --version
    echo [X] Python 版本过低，需要 3.10+
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [X] 未找到 ffmpeg，视频处理依赖 ffmpeg
    echo     安装方式：winget install Gyan.FFmpeg   （安装后请重新打开终端）
    echo     或前往 https://www.gyan.dev/ffmpeg/builds/ 下载并加入 PATH
    pause
    exit /b 1
)

REM 检查端口 8765 是否被占用
netstat -ano | findstr ":8765" >nul 2>nul
if not errorlevel 1 (
    echo [W] 端口 8765 已被占用，请先关闭占用进程后重试
    pause
    exit /b 1
)

echo [OK] 环境检查通过
echo.

set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

if not exist "%VENV_PYTHON%" (
    echo [1/3] 创建虚拟环境...
    python -m venv "%VENV_DIR%"
)

echo [2/3] 安装依赖...
"%VENV_PIP%" install -q -r requirements.txt
if errorlevel 1 (
    echo [X] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

echo [3/3] 启动服务...
echo.
echo   浏览器将自动打开 http://localhost:8765
echo   按 Ctrl+C 停止服务
echo.

REM 延迟 3 秒后打开浏览器（服务启动中）
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8765"

"%VENV_PYTHON%" server.py

echo.
echo 服务已停止。
pause
endlocal
