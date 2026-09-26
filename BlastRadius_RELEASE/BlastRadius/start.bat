@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the virtual environment. Make sure Python is installed and available as "python".
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\.blastradius-installed" (
    echo Installing dependencies...
    python -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency installation failed.
        pause
        exit /b 1
    )
    type nul > ".venv\.blastradius-installed"
)

echo.
echo Starting BlastRadius at http://127.0.0.1:8000
start "BlastRadius" http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

endlocal
