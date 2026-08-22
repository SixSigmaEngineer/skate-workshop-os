@echo off
setlocal EnableExtensions
title Configure SKATE MCP for Claude Desktop

rem /quiet is passed by the installer. It suppresses the closing pause so the
rem post-install step does not leave a console window waiting for a keypress.
set "SKATE_QUIET="
if /I "%~1"=="/quiet" set "SKATE_QUIET=1"

set "SKATE_ROOT=%~dp0"
set "SKATE_MCP_EXE=%SKATE_ROOT%SKATE-MCP.exe"
set "SKATE_PYTHON=%SKATE_ROOT%.venv\Scripts\python.exe"
set "SKATE_MCP=%SKATE_ROOT%mcp_server\server.py"
set "HELPER=%SKATE_ROOT%tools\configure_claude_desktop.ps1"

if exist "%SKATE_MCP_EXE%" goto :runtime_ready

if not exist "%SKATE_PYTHON%" (
    echo SKATE's private Python environment does not exist yet.
    echo Run Start SKATE.bat once, close SKATE, then run this file again.
    goto :fail
)

"%SKATE_PYTHON%" -c "import mcp" >nul 2>nul
if errorlevel 1 (
    echo The MCP dependency is not installed yet.
    echo Run Start SKATE.bat once so it can install the updated requirements.
    goto :fail
)

:runtime_ready

if not exist "%HELPER%" (
    echo The Claude Desktop helper script is missing:
    echo   %HELPER%
    goto :fail
)

rem Claude Desktop not being installed is a normal state, not a failure. The
rem config is written anyway so Claude finds SKATE the first time it starts.
set "CLAUDE_PRESENT="
if exist "%APPDATA%\Claude" set "CLAUDE_PRESENT=1"
if not defined CLAUDE_PRESENT if exist "%LOCALAPPDATA%\Packages" for /f "delims=" %%I in ('dir /b /ad "%LOCALAPPDATA%\Packages\Claude_*" 2^>nul') do set "CLAUDE_PRESENT=1"
if not defined CLAUDE_PRESENT (
    echo Claude Desktop was not found on this computer.
    echo Writing the configuration anyway, so that SKATE is already connected
    echo the first time Claude Desktop runs. Nothing else is needed.
    echo.
)

if exist "%SKATE_MCP_EXE%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Command "%SKATE_MCP_EXE%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Command "%SKATE_PYTHON%" -ScriptPath "%SKATE_MCP%"
)
if errorlevel 1 (
    echo.
    echo The Claude Desktop configuration could not be saved.
    echo See the MCP section in README.md for manual setup.
    goto :fail
)

echo.
if defined CLAUDE_PRESENT (
    echo Restart Claude Desktop, then look for "skate" under
    echo Settings ^> Developer ^> MCP servers, or ask Claude to
    echo list active SKATE sessions.
) else (
    echo SKATE will appear under Settings ^> Developer ^> MCP servers
    echo once Claude Desktop is installed and started.
)
goto :done

:done
if not defined SKATE_QUIET (
    echo.
    pause
)
exit /b 0

:fail
if not defined SKATE_QUIET (
    echo.
    pause
)
exit /b 1
