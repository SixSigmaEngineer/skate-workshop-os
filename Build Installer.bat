@echo off
setlocal EnableExtensions
title Build SKATE Installer

set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%build-app.ps1"
if errorlevel 1 goto :fail

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 was not found. Install it, then run this file again.
    goto :fail
)

"%ISCC%" "%ROOT%installer\SKATE.iss"
if errorlevel 1 goto :fail

echo.
echo Installer ready in build\installer\SKATE-Setup.exe
pause
exit /b 0

:fail
echo.
echo The installer was not built. Review the message above.
pause
exit /b 1
