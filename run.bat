@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set TOKENCRAFT_LOCAL_MODE=true

echo Checking dependencies...
python -m pip install -q -r requirements.txt

echo Starting TokenCraft server...
start "TokenCraft Server" cmd /k "python -m uvicorn app:app --host 127.0.0.1 --port 8000"

echo Waiting for the server to be ready...
set count=0
:waitloop
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri http://127.0.0.1:8000/health -UseBasicParsing -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto ready
set /a count+=1
if !count! GEQ 30 (
    echo Server did not respond within 30 seconds — check the "TokenCraft Server" window for errors.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Server is ready — opening browser...
start "" http://127.0.0.1:8000
