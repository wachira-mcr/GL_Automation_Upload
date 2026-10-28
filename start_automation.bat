@echo off
title SME Bank - GL TFRS9 Automation Engine
cd /d "%~dp0"
echo ==============================================================
echo  Launching SME GL TFRS9 Automation Engine (Port 5056)...
echo ==============================================================
echo [1/3] Checking Python dependencies...
python -c "import flask, oracledb, paramiko" 2>nul
if %errorlevel% neq 0 (
    echo [!] Missing Python packages detected. Installing requirements...
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install packages. Please run: pip install -r requirements.txt
        pause
        exit /b 1
    )
)
echo [2/3] Opening Web Dashboard at http://127.0.0.1:5056 ...
start "" "http://127.0.0.1:5056"
echo [3/3] Starting Flask Server...
python app.py
pause
