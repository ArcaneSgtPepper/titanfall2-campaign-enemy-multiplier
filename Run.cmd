@echo off
setlocal
if exist "%~dp0CampaignEnemyMultiplier.exe" goto standalone
where python >nul 2>nul
if errorlevel 1 (
  echo This is the Python package. Use the Standalone ZIP for an installer that needs no Python.
  echo Alternatively install Python 3.10 or newer and enable its PATH option.
  pause
  exit /b 1
)
python "%~dp0cem.py" %*
goto done
:standalone
"%~dp0CampaignEnemyMultiplier.exe" %*
:done
set "cem_exit=%errorlevel%"
echo.
pause
exit /b %cem_exit%
