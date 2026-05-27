@echo off
setlocal

echo ============================================
echo  Ken Research Email Campaign System
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Install from https://python.org  ^(check "Add to PATH"^)
    pause
    exit /b 1
)

:: Create venv on first run
if not exist "venv\Scripts\activate.bat" (
    echo First-time setup: creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
    echo Done.
    echo.
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install / sync dependencies
echo Checking dependencies...
pip install -r requirements.txt -q --disable-pip-version-check
echo.

:: Open browser then start app
echo Starting app at http://localhost:5000
echo Press Ctrl+C to stop.
echo.
start "" http://localhost:5000
python app.py

pause
