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

call :findpy
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
if /i not "!GO:~0,1!"=="y" (
  echo.
  echo   Nothing was installed.
  pause
  exit /b 1
)

rem WSL first, always. Docker Desktop starts itself at the next login, and if
rem WSL is not there by then it bootstraps a broken engine that survives
rem reinstalling Docker - the distro imports but /opt/docker-desktop stays
rem empty, and it hangs on "Starting the Docker Engine" forever.
if defined NEEDWSL (
  echo.
  echo   Installing WSL first, because Docker Desktop is built on it.
  echo   Windows will ask for administrator rights.
  powershell -NoProfile -Command "Start-Process -FilePath wsl.exe -ArgumentList '--install' -Verb RunAs -Wait"
)

for %%P in (!TODO!) do (
  echo.
  echo   Installing %%P
  "!WINGET!" install --id %%P -e --accept-package-agreements --accept-source-agreements
)

echo.
if defined NEEDWSL (
  echo   *** RESTART THIS PC NOW, before opening Docker Desktop. ***
  echo.
  echo   WSL is not usable until the machine reboots. Docker Desktop opened
  echo   before that reboot builds a broken engine that a reinstall will not
  echo   repair, so let the restart happen first.
) else (
  echo   Done. Close this window and run  run.bat  - a new window is needed
  echo   for Windows to see the programs that were just installed.
  echo.
  echo   Docker Desktop must be opened once by hand before the voice works.
)
echo.
call :findpy
call :whisper
pause
exit /b 0

:ready
echo   Everything SlideCast needs is already installed.
echo.
call :whisper
set /p "GO=  Start SlideCast now? [Y/n] "
if /i "!GO:~0,1!"=="n" exit /b 0
call run.bat

goto :eof

:findpy
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
exit /b

:whisper
rem Word-by-word highlighting listens back to the generated voice, which is
rem the one thing here that needs a package rather than a program.
if not defined PY exit /b
%PY% -c "import faster_whisper" >nul 2>&1
if not errorlevel 1 (
  echo   [x] faster-whisper ^(word-by-word subtitle highlighting^)
  echo.
  exit /b
)
echo   Optional: word-by-word subtitle highlighting needs the faster-whisper
echo   package, about 200 MB with what it depends on. Everything else works
echo   without it.
set "FW="
set /p "FW=  Install it now? [y/N] "
if /i not "%FW:~0,1%"=="y" exit /b
%PY% -m pip install faster-whisper
echo.
exit /b
