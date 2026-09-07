@echo off
setlocal
set PYTHON=python
if not exist "%~dp0backend\venv\Scripts\python.exe" python -m venv "%~dp0backend\venv"
set PYTHON="%~dp0backend\venv\Scripts\python.exe"
%PYTHON% -c "import fastapi, uvicorn, rapidfuzz" >nul 2>&1 || %PYTHON% -m pip install -r "%~dp0backend\requirements.txt"
if not exist "%~dp0frontend\node_modules" npm --prefix "%~dp0frontend" ci
echo Starting GovOrchestrator backend on http://127.0.0.1:8000
start "GovOrchestrator Backend" cmd /k "cd /d %~dp0backend && %PYTHON% -m uvicorn main:app --reload --port 8000"
echo Starting citizen portal on http://127.0.0.1:5173
start "GovOrchestrator Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1 --port 5173"
endlocal
