@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PYW=%~dp0.venv313\Scripts\pythonw.exe"
if not exist "%PYW%" (
    echo 找不到虚拟环境 .venv313，请先初始化：
    echo     python -m venv .venv313
    echo     .venv313\Scripts\python.exe -m pip install -e ".[gui]"
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src"
start "" "%PYW%" -m stampgen gui
