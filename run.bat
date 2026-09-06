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
rem Last resort, for when even the launcher is missing. winget does put Python
rem on the user PATH, but Windows searches the machine PATH first, so a
rem WindowsApps entry there leaves the Store stub answering to `python` anyway.
rem The installer lands in one of these two places.
if not defined PY (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set PY="%%D\python.exe"
  )
)
if not defined PY (
  for /d %%D in ("%ProgramFiles%\Python3*") do (
    if exist "%%D\python.exe" set PY="%%D\python.exe"
  )
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
