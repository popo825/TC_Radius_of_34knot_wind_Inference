@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
) else if exist ".runtime\fastapi" (
  set "PYTHONPATH=%~dp0.runtime"
  python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
) else (
  echo Create an environment first. See README.md.
)
pause
