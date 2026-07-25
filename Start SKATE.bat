@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Start SKATE

rem Self-contained SKATE server launcher for Windows.
rem Creates a private Python environment in .venv, installs dependencies when
rem requirements.txt changes, starts the local server, and opens the app.

set "SKATE_ROOT=%~dp0"
set "SKATE_UI=%SKATE_ROOT%ui"
set "SKATE_APP_PATH=%SKATE_UI%\app.py"
set "SKATE_APP=app.py"
set "SKATE_VENV=%SKATE_ROOT%.venv"
set "SKATE_PYTHON=%SKATE_VENV%\Scripts\python.exe"
set "SKATE_REQUIREMENTS=%SKATE_UI%\requirements.txt"
set "SKATE_REQ_STAMP=%SKATE_VENV%\.requirements.sha256"
set "SKATE_PID_FILE=%SKATE_ROOT%.skate-server.pid"
set "SKATE_STDOUT=%SKATE_ROOT%skate-server.out.log"
set "SKATE_STDERR=%SKATE_ROOT%skate-server.err.log"
set "SKATE_HOST=127.0.0.1"
set "SKATE_PORT=8765"
set "SKATE_URL=http://127.0.0.1:8765"

cd /d "%SKATE_ROOT%"

if not exist "%SKATE_APP_PATH%" (
    echo ERROR: The SKATE server entry point was not found:
    echo   %SKATE_APP_PATH%
    goto :fail
)

if exist "%SKATE_PID_FILE%" (
    powershell -NoProfile -Command "$serverId = [int](Get-Content -LiteralPath $env:SKATE_PID_FILE -ErrorAction SilentlyContinue); if ($serverId -and (Get-Process -Id $serverId -ErrorAction SilentlyContinue)) { exit 0 } else { exit 1 }"
    if not errorlevel 1 (
        echo SKATE is already running at %SKATE_URL%.
        start "" "%SKATE_URL%"
        exit /b 0
    )
    del /q "%SKATE_PID_FILE%" >nul 2>nul
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalAddress $env:SKATE_HOST -LocalPort $env:SKATE_PORT -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo ERROR: Port %SKATE_PORT% is already being used by another application.
    echo Stop that application or change SKATE_PORT in this launcher.
    goto :fail
)

if not exist "%SKATE_PYTHON%" (
    echo Creating SKATE's private Python environment...
    set "BOOTSTRAP_PYTHON="
    where py >nul 2>nul
    if not errorlevel 1 (
        for %%V in (3.13 3.12 3.11 3.10) do (
            if not defined BOOTSTRAP_PYTHON (
                py -%%V -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3,10),(3,11),(3,12),(3,13)] else 1)" >nul 2>nul
                if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -%%V"
            )
        )
    )
    if not defined BOOTSTRAP_PYTHON (
        where python >nul 2>nul
        if not errorlevel 1 (
            python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3,10),(3,11),(3,12),(3,13)] else 1)" >nul 2>nul
            if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
        )
    )
    if not defined BOOTSTRAP_PYTHON (
        echo ERROR: SKATE needs Python 3.10 through 3.13.
        echo Install Python from https://www.python.org/downloads/ and select
        echo "Add Python to PATH", then run this file again.
        goto :fail
    )
    !BOOTSTRAP_PYTHON! -m venv "%SKATE_VENV%"
    if errorlevel 1 (
        echo ERROR: Python could not create the private SKATE environment.
        goto :fail
    )
)

for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath $env:SKATE_REQUIREMENTS).Hash"`) do set "CURRENT_REQ_HASH=%%H"
set "INSTALLED_REQ_HASH="
if exist "%SKATE_REQ_STAMP%" set /p INSTALLED_REQ_HASH=<"%SKATE_REQ_STAMP%"

if /I not "!CURRENT_REQ_HASH!"=="!INSTALLED_REQ_HASH!" (
    echo Installing or updating SKATE dependencies...
    "%SKATE_PYTHON%" -m pip install --disable-pip-version-check --upgrade pip
    if errorlevel 1 goto :dependency_fail
    "%SKATE_PYTHON%" -m pip install --disable-pip-version-check -r "%SKATE_REQUIREMENTS%"
    if errorlevel 1 goto :dependency_fail
    >"%SKATE_REQ_STAMP%" echo !CURRENT_REQ_HASH!
)

echo Starting SKATE at %SKATE_URL%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$args = @($env:SKATE_APP, '--no-tray', '--host', $env:SKATE_HOST, '--port', $env:SKATE_PORT); $p = Start-Process -FilePath $env:SKATE_PYTHON -ArgumentList $args -WorkingDirectory $env:SKATE_UI -WindowStyle Hidden -RedirectStandardOutput $env:SKATE_STDOUT -RedirectStandardError $env:SKATE_STDERR -PassThru; Set-Content -LiteralPath $env:SKATE_PID_FILE -Value $p.Id -Encoding ascii"
if errorlevel 1 (
    echo ERROR: Windows could not start the SKATE server process.
    goto :fail
)

for /L %%I in (1,1,20) do (
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri $env:SKATE_URL -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch {}; exit 1" >nul 2>nul
    if not errorlevel 1 goto :ready
    ping 127.0.0.1 -n 2 >nul
)

echo ERROR: SKATE did not become ready within 20 seconds.
echo Review these logs:
echo   %SKATE_STDOUT%
echo   %SKATE_STDERR%
goto :fail

:ready
echo SKATE is running.
echo Native app window: SKATE
echo Stop it with: Stop SKATE.bat
exit /b 0

:dependency_fail
echo ERROR: SKATE dependencies could not be installed.
echo Check your internet connection and the messages above.

:fail
echo.
pause
exit /b 1
