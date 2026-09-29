@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment. Make sure Python is installed and on PATH.
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
where ollama >nul 2>nul
if errorlevel 1 echo WARNING: Ollama was not found on PATH. Install Ollama first.
echo.
echo Starting CodePilot AI...
python -m streamlit run backend\app.py
pause
