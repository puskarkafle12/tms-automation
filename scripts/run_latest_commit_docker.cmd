@echo off
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\run_latest_commit_docker.py %*
  exit /b %errorlevel%
)

python scripts\run_latest_commit_docker.py %*
exit /b %errorlevel%
