@echo off
rem Start the web service and open it in the browser.
rem Optional: quick_web.bat --port 8080 [--host 0.0.0.0] [--no-browser]
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Python venv not found: "%PY%"
  echo Install it with: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

cd /d "%ROOT%"
"%PY%" -X utf8 "%~dp0quick_web.py" %*
echo.
pause
