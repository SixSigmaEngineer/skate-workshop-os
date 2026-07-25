@echo off
setlocal EnableExtensions
title SKATE MCP - Local Streamable HTTP

set "SKATE_ROOT=%~dp0"
set "SKATE_MCP_EXE=%SKATE_ROOT%SKATE-MCP.exe"
set "SKATE_PYTHON=%SKATE_ROOT%.venv\Scripts\python.exe"
set "SKATE_MCP=%SKATE_ROOT%mcp_server\server.py"

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

echo Starting the private SKATE MCP endpoint...
echo Local URL: http://127.0.0.1:8766/mcp
echo.
echo Keep this window open while using MCP Inspector or Secure MCP Tunnel.
echo Press Ctrl+C to stop the endpoint.
echo.
if exist "%SKATE_MCP_EXE%" (
    "%SKATE_MCP_EXE%" --transport streamable-http --host 127.0.0.1 --port 8766
) else (
    "%SKATE_PYTHON%" "%SKATE_MCP%" --transport streamable-http --host 127.0.0.1 --port 8766
)
exit /b %errorlevel%

:fail
echo.
pause
exit /b 1
