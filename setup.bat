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

rem `where python` is not enough. Windows ships a Microsoft Store stub called
rem python.exe in WindowsApps, which is on PATH, so the name is always found
rem even when no Python is installed - running it just advertises the Store.
rem Only actually running it proves anything.
set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
rem Last resort: PATH can simply be wrong - winget installs Python without
rem always putting it there, and the Store stub answers to `python` meanwhile.
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

rem Docker Desktop runs on WSL and will not start without it. Installing
rem Docker alone leaves you at a "WSL not installed" dialog on first launch.
wsl --status >nul 2>&1
if errorlevel 1 (
  set "NEEDWSL=1"
  echo     [ ] WSL             - Docker Desktop needs it, will install
) else (
  echo     [x] WSL
)

echo.
if "!TODO!"=="" if not defined NEEDWSL goto ready

echo   These will be installed:
if not "!TODO!"=="" echo     !TODO!   ^(winget^)
if defined NEEDWSL echo     WSL   ^(needs administrator rights, and a restart afterwards^)
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

if defined NEEDWSL (
  echo.
  echo   Installing WSL. Windows will ask for administrator rights.
  powershell -NoProfile -Command "Start-Process -FilePath wsl.exe -ArgumentList '--install' -Verb RunAs -Wait"
  echo.
  echo   *** Restart this PC before opening Docker Desktop. WSL is not usable
  echo   *** until you do, and Docker will show a "WSL not installed" error.
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
