@echo off
title SlideCast
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python was not found. Run  setup.bat  first.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting SlideCast. Leave this window open while you use it.
echo   Press Ctrl+C here to stop.
echo.
python serve.py
pause
