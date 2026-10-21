@echo off
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.10 or newer from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)
if not exist .env if not defined TELEGRAM_BOT_TOKEN (
    py -3 bot.py --setup
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
py -3 bot.py
pause
