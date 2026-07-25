@echo off
setlocal EnableExtensions
title Configure SKATE MCP for Codex

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

set "CODEX_EXE="
if exist "%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe" set "CODEX_EXE=%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe"
if not defined CODEX_EXE for /f "delims=" %%I in ('dir /b /s /a-d "%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe" 2^>nul') do if not defined CODEX_EXE set "CODEX_EXE=%%I"
if not defined CODEX_EXE for /f "delims=" %%I in ('where codex 2^>nul') do if not defined CODEX_EXE set "CODEX_EXE=%%I"
if not defined CODEX_EXE (
    echo Codex CLI was not found on PATH.
    echo You can still add SKATE from ChatGPT desktop Settings ^> MCP servers.
    echo See the MCP section in README.md for the exact values.
    goto :fail
)

echo Replacing any older SKATE MCP registration...
rem A command-line override keeps MCP setup working when an older Codex
rem config still contains the retired service_tier = "default" value.
set "CODEX_TIER_OVERRIDE=service_tier='flex'"
"%CODEX_EXE%" -c "%CODEX_TIER_OVERRIDE%" mcp remove skate >nul 2>nul
if exist "%SKATE_MCP_EXE%" (
    "%CODEX_EXE%" -c "%CODEX_TIER_OVERRIDE%" mcp add skate -- "%SKATE_MCP_EXE%" --transport stdio
) else (
    "%CODEX_EXE%" -c "%CODEX_TIER_OVERRIDE%" mcp add skate -- "%SKATE_PYTHON%" "%SKATE_MCP%" --transport stdio
)
if errorlevel 1 (
    echo.
    echo Codex could not save the MCP configuration.
    echo See the MCP section in README.md for manual setup.
    goto :fail
)

echo.
echo SKATE MCP is configured for local Codex clients.
echo Restart the ChatGPT desktop app, Codex CLI, or IDE extension.
echo Then type /mcp to confirm that "skate" is connected.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
