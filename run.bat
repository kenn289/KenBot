@echo off
REM ════════════════════════════════════════════════════════
REM  Ken ClawdBot — Run Script (Windows)
REM  Starts Flask API + Content Scheduler in one window,
REM  then starts the WhatsApp bot in a second window.
REM ════════════════════════════════════════════════════════

echo.
echo ==================================================
echo   Ken ClawdBot — Starting
echo ==================================================
echo.

REM ── Keep laptop awake while bot runs ──────────────
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change standby-timeout-dc 0 >nul 2>&1
powercfg /change monitor-timeout-ac 0 >nul 2>&1
echo [OK] Sleep disabled — laptop will stay awake.
echo.

REM ── Check venv ────────────────────────────────────
IF NOT EXIST ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

REM ── Start Flask API + Scheduler ───────────────────
echo Starting Flask API + Content Scheduler...
start "Ken - API" cmd /k ".venv\Scripts\python run.py"

REM Wait 3 seconds for Flask to spin up
timeout /t 3 /nobreak >nul

REM ── Start WhatsApp Bot ────────────────────────────
echo Starting WhatsApp Bot...
start "Ken - WhatsApp" cmd /k "npm run whatsapp"

echo.
echo ==================================================
echo   Ken is starting up in two windows:
echo.
echo   Window 1: Flask API + Scheduler (port 5050)
echo   Window 2: WhatsApp Bot (scan QR to link)
echo.
echo   Dashboard: http://localhost:5050/health
echo ==================================================
echo.
