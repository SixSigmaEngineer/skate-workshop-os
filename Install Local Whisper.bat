@echo off
setlocal EnableExtensions
title Install SKATE Local Whisper

set "SKATE_ROOT=%~dp0"
set "SKATE_PYTHON=%SKATE_ROOT%.venv\Scripts\python.exe"
set "MODEL_ROOT=%SKATE_ROOT%models\whisper"

cd /d "%SKATE_ROOT%"

if not exist "%SKATE_PYTHON%" (
    echo SKATE's private Python environment was not found.
    echo Run Start SKATE.bat once, stop SKATE, and then run this installer again.
    goto :fail
)

echo Installing the offline Whisper transcription engine...
"%SKATE_PYTHON%" -m pip install --disable-pip-version-check "numpy<3" "openai-whisper>=20250625"
if errorlevel 1 goto :fail

if not exist "%MODEL_ROOT%" mkdir "%MODEL_ROOT%"
echo.
echo Downloading the Tiny English-capable model for the first transcription...
"%SKATE_PYTHON%" -c "import whisper; whisper.load_model('tiny', download_root=r'%MODEL_ROOT%'); print('Tiny Whisper model is ready.')"
if errorlevel 1 goto :fail

echo.
echo Local Whisper is installed and ready.
echo Restart SKATE with Stop SKATE.bat and Start SKATE.bat.
pause
exit /b 0

:fail
echo.
echo Local Whisper could not be installed.
echo Check your internet connection and the messages above, then try again.
pause
exit /b 1
