@echo off
set PATH=C:\ffmpeg\bin;%PATH%
cd /d "%~dp0"
.venv\Scripts\python.exe server.py
