@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\run_latest_commit_docker.py --pull-git %*
  set "EXIT_CODE=!errorlevel!"
  if not "!EXIT_CODE!"=="0" (
    echo.
    echo Script failed with exit code !EXIT_CODE!.
    pause
  )
  exit /b !EXIT_CODE!
)

python scripts\run_latest_commit_docker.py --pull-git %*
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Script failed with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
