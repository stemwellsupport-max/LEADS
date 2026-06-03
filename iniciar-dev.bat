@echo off
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 > nul
cd /d "%~dp0"
call venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001