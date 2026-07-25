@echo off
setlocal EnableExtensions
title Configure SKATE MCP for Claude Desktop

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

if not exist "%APPDATA%\Claude" (
    echo Claude Desktop does not appear to be installed yet.
    echo The configuration will still be written so Claude Desktop
    echo finds SKATE the first time it starts.
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
echo Restart Claude Desktop, then look for "skate" under
echo Settings ^> Developer ^> MCP servers, or ask Claude to
echo list active SKATE sessions.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
