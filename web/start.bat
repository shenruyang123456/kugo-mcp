@echo off
set "KUGO_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%KUGO_PYTHON%" (
  echo Python environment not found. Please complete the repository installation first.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8765 in your browser. Keep this window open.
"%KUGO_PYTHON%" "%~dp0server.py"
pause
