@echo off
echo ======================================
echo INICIANDO CRM - PRODUCCION
echo ======================================
start "API" cmd /k "cd C:\Users\PC\crm_api && venv\Scripts\activate.bat && uvicorn test_api:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 >nul
start "ngrok" cmd /k "cd C:\Users\PC\crm_api && ngrok http 8000 --request-header-add=ngrok-skip-browser-warning:1"
echo.
echo Dashboard: https://stemwellsupport-max.github.io/LEADS/
echo.
pause