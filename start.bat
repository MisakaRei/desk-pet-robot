@echo off
setlocal
title Desk Pet Robot
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [setup] Creating virtual environment...
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3.12 -m venv .venv
        if errorlevel 1 py -3.11 -m venv .venv
    )
    if errorlevel 1 goto :error
)

"%PYTHON%" -c "import cv2, ultralytics, numpy, serial, pygame, yaml" >nul 2>nul
if errorlevel 1 (
    echo [setup] Installing project dependencies...
    "%PYTHON%" -m pip install -e ".[test]"
    if errorlevel 1 goto :error
)

"%PYTHON%" -m petbot.main
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [error] Program exited with code %EXIT_CODE%. See the messages above.
    pause
)
exit /b %EXIT_CODE%

:error
echo.
echo [error] Setup failed. See the messages above.
pause
exit /b 1
