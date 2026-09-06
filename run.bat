@echo off
title SlideCast
cd /d "%~dp0"

rem Not `where python`: the Microsoft Store stub answers to that name even on a
rem machine with no Python. Run it, and fall back to the py launcher.
set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo.
  echo   Python was not found. Run  setup.bat  first, then open a NEW terminal.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting SlideCast. Leave this window open while you use it.
echo   Press Ctrl+C here to stop.
echo.
%PY% serve.py
pause
