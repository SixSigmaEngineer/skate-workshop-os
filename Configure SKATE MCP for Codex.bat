@echo off
setlocal EnableExtensions
title Configure SKATE MCP for Codex

rem /quiet is passed by the installer. It suppresses the closing pause so the
rem post-install step does not leave a console window waiting for a keypress.
set "SKATE_QUIET="
if /I "%~1"=="/quiet" set "SKATE_QUIET=1"

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
    rem Not having Codex is a normal state, not a failure. Say so plainly and
    rem exit 0 so the installer does not report a problem.
    echo Codex was not found on this computer, so there is nothing to connect.
    echo SKATE itself is installed and works on its own.
    echo.
    echo If you install Codex or ChatGPT desktop later, run this file again
    echo from the SKATE folder. You can also add SKATE by hand from ChatGPT
    echo desktop under Settings ^> MCP servers - see README.md for the values.
    goto :nothing_to_do
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
goto :done

:nothing_to_do
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
