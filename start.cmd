@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set "R34_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "R34_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" if exist ".runtime\fastapi" set "PYTHONPATH=%~dp0.runtime"
"%R34_PYTHON%" -m backend.batch --output dist
if not exist "dist\index.html" (
  echo No batch output exists. See README.md.
  pause
  exit /b 1
)
echo R34 Observatory: http://127.0.0.1:8000
"%R34_PYTHON%" -m http.server 8000 --bind 127.0.0.1 --directory dist
pause
