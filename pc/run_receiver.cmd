@echo off
setlocal
cd /d "%~dp0"

set "MODE=wechat"
set "PYTHON=%~dp0..\.venv\Scripts\python.exe"
if /I "%~1"=="local" (
    set "MODE=local"
    set "PYTHON=%~dp0..\.venv-asr\Scripts\python.exe"
)

if not exist "%PYTHON%" (
    echo Python environment not found: %PYTHON%
    pause
    exit /b 1
)

"%PYTHON%" -u main.py --port auto --hotkey Ctrl+Win --mode %MODE%
if errorlevel 1 (
    echo Receiver exited with an error. Check the message above.
    pause
)
