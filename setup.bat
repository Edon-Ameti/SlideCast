@echo off
setlocal enabledelayedexpansion
title SlideCast setup
cd /d "%~dp0"

echo.
echo   SlideCast setup
echo   ---------------
echo.

rem winget is usually on PATH, but it is an app-execution alias and some
rem shells do not have WindowsApps on theirs. Fall back to the alias itself.
set "WINGET=winget"
where winget >nul 2>&1
if errorlevel 1 set "WINGET=%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"
"%WINGET%" --version >nul 2>&1
if errorlevel 1 (
  echo   This needs the Windows Package Manager ^(winget^), which was not found.
  echo   It ships with Windows 11. On Windows 10, install "App Installer" from
  echo   the Microsoft Store and run this again.
  echo.
  pause
  exit /b 1
)

echo   What this machine already has:
echo.

set "TODO="

where python >nul 2>&1
if errorlevel 1 (
  set "TODO=!TODO! Python.Python.3.13"
  echo     [ ] Python 3        - will install
) else (
  echo     [x] Python 3
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
  set "TODO=!TODO! Gyan.FFmpeg"
  echo     [ ] ffmpeg          - will install
) else (
  echo     [x] ffmpeg
)

set "HASCHROME=0"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "HASCHROME=1"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "HASCHROME=1"
if "!HASCHROME!"=="0" (
  set "TODO=!TODO! Google.Chrome"
  echo     [ ] Google Chrome   - will install
) else (
  echo     [x] Google Chrome
)

where docker >nul 2>&1
if errorlevel 1 (
  set "TODO=!TODO! Docker.DockerDesktop"
  echo     [ ] Docker Desktop  - will install ^(large, and it needs a reboot^)
) else (
  echo     [x] Docker Desktop
)

echo.
if "!TODO!"=="" goto ready

echo   These will be installed with winget:
echo     !TODO!
echo.
set /p "GO=  Install them now? [y/N] "
if /i not "!GO!"=="y" (
  echo.
  echo   Nothing was installed.
  pause
  exit /b 1
)

for %%P in (!TODO!) do (
  echo.
  echo   Installing %%P
  "!WINGET!" install --id %%P -e --accept-package-agreements --accept-source-agreements
)

echo.
echo   Done. Close this window and run  run.bat  - a new window is needed for
echo   Windows to see the programs that were just installed.
echo.
echo   Docker Desktop must be opened once by hand before the voice will work.
echo   For word-by-word subtitle highlighting, also run:
echo       python -m pip install faster-whisper
echo.
pause
exit /b 0

:ready
echo   Everything SlideCast needs is already installed.
echo.
set /p "GO=  Start SlideCast now? [Y/n] "
if /i "!GO!"=="n" exit /b 0
call run.bat
