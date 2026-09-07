@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install Python and enable its PATH option.
  pause
  exit /b 1
)
python "%~dp0cem.py" %*
set "cem_exit=%errorlevel%"
echo.
pause
exit /b %cem_exit%
