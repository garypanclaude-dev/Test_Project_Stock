@echo off
chcp 65001 >nul
echo ============================
echo  Stock Platform - Starting
echo ============================
echo.
echo Backend API  : http://localhost:8000
echo Frontend     : http://localhost:5173
echo API Docs     : http://localhost:8000/docs
echo.
echo NOTE: First launch will download TW and US stock data (15-30 min)
echo       The frontend will show progress while downloading.
echo.

start "Backend API" cmd /k "cd /d %~dp0backend && venv\Scripts\activate.bat && python main.py"
timeout /t 2 /nobreak >nul
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Both windows opened. Waiting for startup...
echo Press any key to close this window (servers keep running in background)
pause >nul
