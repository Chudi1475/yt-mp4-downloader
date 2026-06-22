@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.9+ from https://python.org
    pause
    exit /b 1
)
echo Installing/updating dependencies...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r requirements.txt
echo Launching...
python app.py
if errorlevel 1 pause
