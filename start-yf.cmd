@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -c "import yf.app" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m ensurepip --upgrade
  if errorlevel 1 goto failure
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -m yf --open
if errorlevel 1 goto failure
exit /b 0
:failure
echo Startup failed. See the error above and docs/running.md.
pause
exit /b 1
