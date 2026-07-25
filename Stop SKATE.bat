@echo off
REM ============================================================
REM  SKATE stop script - shuts down the local SKATE web server
REM  Double-click this file, or run:
REM      Stop SKATE.bat            (stops the default ports 8765 and 8766)
REM      Stop SKATE.bat 8765       (stops a specific port)
REM ============================================================
setlocal enabledelayedexpansion

set "PORTS=%~1"
if "%PORTS%"=="" set "PORTS=8765 8766"

echo.
echo Stopping SKATE on port^(s^): %PORTS% ...
echo.

set "ANY="
for %%Q in (%PORTS%) do (
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%%Q .*LISTENING"') do (
        set "ANY=1"
        echo Found SKATE listener on port %%Q ^(PID %%P^).
        taskkill /PID %%P /F >nul 2>nul
        if errorlevel 1 (
            echo   Could not stop PID %%P. Try running this file as Administrator.
        ) else (
            echo   Stopped PID %%P.
        )
    )
)

if not defined ANY echo No SKATE server was found on port^(s^) %PORTS%.

echo.
echo Done.
timeout /t 2 >nul
endlocal
