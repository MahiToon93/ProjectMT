@echo off
setlocal

REM Run this file by double-clicking it. It must sit in the SAME FOLDER
REM as maketoon_beta.py (and MakeToons_logo_full.png / .ico if you have them).

cd /d "%~dp0"

echo === Checking for Python ===
python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found on PATH. Install it from https://python.org
    echo IMPORTANT: during install, check "Add python.exe to PATH".
    pause
    exit /b 1
)

echo === Creating virtual environment (venv) if needed ===
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo === Installing dependencies ===
python -m pip install --upgrade pip
pip install PySide6 pyinstaller

set ICON_ARG=
if exist MakeToons_logo_full.ico set ICON_ARG=--icon=MakeToons_logo_full.ico

set DATA_ARG=
if exist MakeToons_logo_full.png set DATA_ARG=--add-data "MakeToons_logo_full.png;."

echo === Building MakeToons.exe ===
pyinstaller --noconfirm --onefile --windowed %ICON_ARG% %DATA_ARG% --name MakeToons maketoon_beta.py

echo.
if exist dist\MakeToons.exe (
    echo SUCCESS: dist\MakeToons.exe is ready.
) else (
    echo Build finished but MakeToons.exe was not found - scroll up for errors.
)
pause
