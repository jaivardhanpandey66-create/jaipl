@echo off
REM zing launcher for Windows. Keeps the terminal window open on error so
REM the message is readable, which matters when a beginner runs a broken file.
setlocal
set "HERE=%~dp0"
if exist "%HERE%python\python.exe" (
    set "ZING_PY=%HERE%python\python.exe"
) else (
    set "ZING_PY=python"
)
if "%PYTHONPATH%"=="" (
    set "PYTHONPATH=%HERE%runtime"
) else (
    set "PYTHONPATH=%HERE%runtime;%PYTHONPATH%"
)
"%ZING_PY%" -m arcide.zing.cli %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo zing exited with code %CODE%
    pause
)
exit /b %CODE%
