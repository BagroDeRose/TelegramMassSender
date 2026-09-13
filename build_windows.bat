@echo off
setlocal

echo ===============================================
echo   Telegram Mass Sender - Windows build script
echo ===============================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create virtual environment. Is Python installed and on PATH?
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists, skipping creation.
)

echo [2/5] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: failed to install dependencies.
    exit /b 1
)

echo [3/5] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [4/5] Generating Windows version-info resource...
".venv\Scripts\python.exe" scripts\generate_version_info.py
if errorlevel 1 (
    echo ERROR: failed to generate version_info.txt.
    exit /b 1
)

echo [5/5] Building with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller telegram_mass_sender.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

echo.
echo ===============================================
echo   Build complete!
echo   Executable: dist\TelegramMassSender\TelegramMassSender.exe
echo ===============================================

endlocal
