@echo off
REM ════════════════════════════════════════════════════════
REM  Ken ClawdBot — Windows Setup Script
REM  Run this ONCE on a fresh clone.
REM ════════════════════════════════════════════════════════

echo.
echo ==================================================
echo   Ken ClawdBot — Setup
echo ==================================================
echo.

REM ── Check Node.js ─────────────────────────────────
node --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Node.js is not installed.
    echo Download from https://nodejs.org  ^(v18+ required^)
    pause
    exit /b 1
)
echo [OK] Node.js found

REM ── Check Python ──────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Install Python 3.11+ from python.org
    pause
    exit /b 1
)
echo [OK] Python found

REM ── Create directories ─────────────────────────────
echo.
echo Creating directories...
mkdir credentials 2>nul
mkdir media\youtube 2>nul
mkdir media\temp 2>nul
mkdir memory\sessions 2>nul
mkdir logs 2>nul
echo [OK] Directories created

REM ── Python venv ───────────────────────────────────
echo.
echo Creating Python virtual environment...
python -m venv .venv
echo [OK] venv created

echo.
echo Installing Python packages (this may take a few minutes)...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt
echo [OK] Python packages installed

REM ── Node packages ─────────────────────────────────
echo.
echo Installing Node.js packages...
npm install
echo [OK] Node packages installed

REM ── Copy .env if needed ───────────────────────────
IF NOT EXIST ".env" (
    copy .env.example .env
    echo [OK] .env created from template — fill in your keys!
) ELSE (
    echo [OK] .env already exists
)

echo.
echo ==================================================
echo   Setup complete!
echo.
echo   Next steps:
echo   1. Edit .env and fill in Twitter API keys
echo      (from developer.twitter.com)
echo   2. For YouTube: add credentials/google_oauth.json
echo      (from Google Cloud Console)
echo   3. Run the bot: run.bat
echo ==================================================
echo.
pause
