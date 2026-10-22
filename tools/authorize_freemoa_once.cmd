@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher py.exe is required.
  pause
  exit /b 1
)
py -3 -c "import playwright" >nul 2>nul
if errorlevel 1 (
  echo Installing Playwright Python library...
  py -3 -m pip install --user playwright==1.56.0
  if errorlevel 1 (
    echo Playwright installation failed.
    pause
    exit /b 1
  )
)
echo Freemoa one-time Google login in normal Chrome...
py -3 -m tools.freemoa_bootstrap_windows
echo.
pause
endlocal
