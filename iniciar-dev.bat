@echo off 
echo ====================================== 
echo INICIANDO CRM - DESARROLLO 
echo ====================================== 
start "API" cmd /k "cd C:\Users\PC\crm_api && venv\Scripts\activate.bat && uvicorn test_api:app --reload --host 0.0.0.0 --port 8000" 
echo. 
echo DEV: http://localhost:8000 
echo Docs: http://localhost:8000/docs 
echo Dashboard: dashboard-dev.html 
echo. 
pause 
